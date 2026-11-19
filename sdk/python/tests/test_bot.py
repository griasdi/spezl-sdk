"""The Python SDK against the fake `spezl serve` of `tests/fake_spezl.py`: what it asks serve
for and how it hands serve's notifications to the handlers."""

from __future__ import annotations

import contextlib
import io
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sdk/python/src"))

import spezl  # noqa: E402

FAKE = str(ROOT / "tests/fake_spezl.py")
DEADLINE = 10.0
SERVER = "griasdi:server:test"
CHANNEL = {"server": SERVER, "id": "c1", "name": "general", "group": "g1"}
ALICE = {"id": "a1ce" * 16, "name": "alice", "bot_id": False}


def context(seq: int) -> dict:
    return {
        "community": {"id": "k1", "name": "Crew"},
        "channel": CHANNEL,
        "seq": seq,
        "ts_ms": 1_700_000_000_000,
        "sender": ALICE,
    }


def message(seq: int, text: str, *, mentions_me: bool) -> dict:
    params = {**context(seq), "text": text, "reply_to": None, "mentions_me": mentions_me}
    return {"method": "message", "params": params}


class FakeServe(unittest.IsolatedAsyncioTestCase):
    """Each test runs a bot against the fake serve with its own scenario and request log."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.log = Path(self.dir.name) / "requests.jsonl"
        self.env = {
            k: os.environ.get(k) for k in ("FAKE_SPEZL_LOG", "FAKE_SPEZL_SCENARIO")
        }
        os.environ["FAKE_SPEZL_LOG"] = str(self.log)

    def tearDown(self) -> None:
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.dir.cleanup()

    def bot(self, scenario: dict, **kwargs) -> spezl.Bot:
        # The child inherits the environment when the bot starts it.
        os.environ["FAKE_SPEZL_SCENARIO"] = json.dumps(scenario)
        return spezl.Bot(binary=FAKE, home=self.dir.name, **kwargs)

    def requests(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def request(self, method: str) -> dict:
        found = [r for r in self.requests() if r["method"] == method]
        self.assertEqual(len(found), 1, f"one {method} request")
        return found[0].get("params") or {}

    async def run_bot(self, bot: spezl.Bot) -> None:
        await asyncio.wait_for(bot.start(), DEADLINE)

    async def test_start_announces_commands_and_voice_then_runs_until_closed(self) -> None:
        bot = self.bot({"notifications": [{"method": "ready", "params": {"server": SERVER}}]},
                       voice=True)
        ready = []

        @bot.command("poll", "Start a poll", [spezl.TextField("q", "Question", max_chars=50)])
        async def poll(inv: spezl.Invocation) -> None:
            pass

        @bot.on_ready
        async def on_ready(server: str) -> None:
            ready.append((server, bot.name))
            await bot.close()

        await self.run_bot(bot)
        self.assertEqual(ready, [(SERVER, "TestBot")])
        self.assertEqual(
            [r["method"] for r in self.requests()],
            ["info", "set_commands", "set_voice", "shutdown"],
        )
        self.assertEqual(
            self.request("set_commands"),
            {
                "commands": [
                    {
                        "name": "poll",
                        "description": "Start a poll",
                        "fields": [
                            {
                                "type": "text",
                                "id": "q",
                                "label": "Question",
                                "required": True,
                                "placeholder": "",
                                "max_chars": 50,
                            }
                        ],
                    }
                ]
            },
        )
        self.assertEqual(self.request("set_voice"), {"voice": True})

    async def test_a_mention_is_answered_as_a_reply_in_its_channel(self) -> None:
        bot = self.bot({
            "notifications": [
                message(7, "just chatting", mentions_me=False),
                message(8, "@TestBot hi", mentions_me=True),
            ]
        })
        seen, replies = [], []

        @bot.on_message
        async def on_message(msg: spezl.Message) -> None:
            seen.append(msg.seq)

        @bot.on_mention
        async def on_mention(msg: spezl.Message) -> None:
            replies.append(await msg.reply(f"hi, @{msg.sender.name}!"))
            await bot.close()

        await self.run_bot(bot)
        self.assertEqual(sorted(seen), [7, 8])
        self.assertEqual(replies, [101])
        self.assertEqual(
            self.request("send"),
            {"server": SERVER, "group": "g1", "text": "hi, @alice!", "reply_to": 8},
        )

    async def test_a_private_answer_goes_to_the_invoking_member_only(self) -> None:
        invocation = {**context(9), "command": "poll", "values": {"q": "Pizza?"}}
        bot = self.bot({
            "notifications": [
                {"method": "invocation", "params": {**invocation, "command": "unknown"}},
                {"method": "invocation", "params": invocation},
            ]
        })
        values = []

        @bot.command("poll", "Start a poll", [spezl.TextField("q", "Question")])
        async def poll(inv: spezl.Invocation) -> None:
            values.append(inv.values)
            await inv.respond(spezl.Card("Noted"), private=True)
            await bot.close()

        await self.run_bot(bot)
        self.assertEqual(values, [{"q": "Pizza?"}])
        self.assertEqual(
            self.request("post_card"),
            {
                "server": SERVER,
                "group": "g1",
                "card": {"body": "Noted", "blocks": []},
                "answers": 9,
                "to": ALICE["id"],
            },
        )

    async def test_a_failing_handler_leaves_the_bot_running(self) -> None:
        bot = self.bot({
            "notifications": [
                message(7, "boom", mentions_me=False),
                {"method": "ready", "params": {"server": SERVER}},
            ]
        })
        ready = []

        @bot.on_message
        async def on_message(msg: spezl.Message) -> None:
            raise RuntimeError("handler bug")

        @bot.on_ready
        async def on_ready(server: str) -> None:
            ready.append(server)
            await bot.close()

        printed = io.StringIO()
        with contextlib.redirect_stderr(printed):
            await self.run_bot(bot)
        self.assertEqual(ready, [SERVER])
        self.assertIn("RuntimeError: handler bug", printed.getvalue())

    async def test_an_error_of_serve_reaches_the_caller_with_its_code(self) -> None:
        bot = self.bot({
            "notifications": [message(8, "@TestBot hi", mentions_me=True)],
            "errors": {"send": {"code": -32000, "message": "not in that channel"}},
        })
        errors = []

        @bot.on_mention
        async def on_mention(msg: spezl.Message) -> None:
            try:
                await msg.reply("hi")
            except spezl.SpezlError as e:
                errors.append((e.code, str(e)))
            await bot.close()

        await self.run_bot(bot)
        self.assertEqual(errors, [(-32000, "not in that channel")])

    async def test_a_serve_of_another_protocol_is_refused(self) -> None:
        bot = self.bot({"info": {"protocol": 3}})
        with self.assertRaisesRegex(spezl.SpezlError, "protocol 3"):
            await self.run_bot(bot)
        self.assertEqual([r["method"] for r in self.requests()], ["info", "shutdown"])


if __name__ == "__main__":
    unittest.main()
