"""The Python SDK against the real `spezl serve`, without a griasdi server: serve checks the
wire of commands and cards as strictly as with one (unknown keys and variants are errors). Skipped
without spezl (`SPEZL_BIN`, else `spezl` on `PATH`); get it from https://griasdi.github.io/bots/."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sdk/python/src"))

import spezl  # noqa: E402

SPEZL = os.environ.get("SPEZL_BIN") or shutil.which("spezl")
DEADLINE = 30.0

FIELDS = [
    spezl.TextField("text", "Text", placeholder="…", max_chars=50, required=False),
    spezl.TextListField("list", "List", min=2, max=5, max_chars=20),
    spezl.ToggleField("toggle", "Toggle", default=True),
    spezl.ChoiceField("choice", "Choice", [("a", "A"), ("b", "B")], default="a"),
    spezl.SelectField(
        "select",
        "Select",
        [("x", "X"), spezl.SelectOption("y", "Y", when=["b"])],
        on="choice",
        tiles=True,
    ),
    spezl.DateTimeField("when", "When"),
    spezl.ClientInfoField("client", "Client", required=False),
]

BUTTON = spezl.Button("ok", "OK", "primary")
BLOCKS = [
    spezl.Buttons([BUTTON, spezl.Button("no", "No", "danger")]),
    spezl.ItemList([spezl.ListItem("Row", "detail", [BUTTON])]),
    spezl.FormButton("form", "Open", spezl.Form("Form", FIELDS, text="Fill in", submit="Send")),
    spezl.Columns(["left", "right"]),
    spezl.HintedButtons([spezl.HintedButton("h", "Hinted", "a hint", "success")]),
    spezl.Links([spezl.LinkButton("Site", "https://griasdi.github.io/")]),
    spezl.Tally([spezl.TallyOption("t1", "Join"), spezl.TallyOption("t2", "Maybe", "late")]),
    spezl.Poll("Pizza?", ["Yes", "No"], multiple=True, closes_ms=1_900_000_000_000),
]


@unittest.skipUnless(SPEZL, "needs spezl: SPEZL_BIN or spezl on PATH")
class RealServe(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        subprocess.run(
            [SPEZL, "--dir", self.dir.name, "new", "SdkTest"],
            check=True,
            capture_output=True,
            timeout=DEADLINE,
        )
        self.home = str(Path(self.dir.name) / "bots/SdkTest")

    def tearDown(self) -> None:
        self.dir.cleanup()

    async def test_serve_takes_every_field_and_block_the_sdk_writes(self) -> None:
        bot = spezl.Bot(home=self.home, binary=SPEZL, voice=True)

        @bot.command("every-field", "Every field kind", FIELDS)
        async def every_field(inv: spezl.Invocation) -> None:
            pass

        running = asyncio.create_task(bot.start())
        try:
            # Polled: without a griasdi server no `ready` comes, and the SDK has no other
            # signal for "started"; `name` answers once serve's `info` is in.
            while not running.done():
                try:
                    name = bot.name
                    break
                except spezl.SpezlError:
                    await asyncio.sleep(0.02)
            self.assertEqual(name, "SdkTest")
            self.assertEqual(await bot.communities(), [])
            # The bot is on no server, so serve refuses a card for its server only after it
            # parsed the card and checked griasdi's limits: a wire mistake would be refused
            # for the card instead. One block per card keeps each within the limits.
            channel = spezl.Channel(server="griasdi:server:none", id="00", name="x", group="00")
            for block in BLOCKS:
                with self.subTest(block=type(block).__name__):
                    with self.assertRaises(spezl.SpezlError) as refused:
                        await bot.post_card(channel, spezl.Card("**A block**", [block]))
                    self.assertEqual(refused.exception.code, -32602)
                    self.assertIn("not a server link", str(refused.exception))
        finally:
            await bot.close()
            # Raises if serve refused set_commands or set_voice.
            await asyncio.wait_for(running, DEADLINE)


if __name__ == "__main__":
    unittest.main()
