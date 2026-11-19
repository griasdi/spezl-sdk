// The TypeScript SDK against the fake `spezl serve` of `tests/fake_spezl.py`: what it asks
// serve for and how it hands serve's notifications to the handlers.

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, test } from "node:test";
import { Bot, SpezlError, type Message } from "../src/index.ts";

const FAKE = join(import.meta.dirname, "../../../tests/fake_spezl.py");
const SERVER = "griasdi:server:test";
const CHANNEL = { server: SERVER, id: "c1", name: "general", group: "g1" };
const ALICE = { id: "a1ce".repeat(16), name: "alice", bot_id: false };

interface Request {
  method: string;
  params?: Record<string, unknown>;
}

function context(seq: number) {
  return {
    community: { id: "k1", name: "Crew" },
    channel: CHANNEL,
    seq,
    ts_ms: 1_700_000_000_000,
    sender: ALICE,
  };
}

function message(seq: number, text: string, mentionsMe: boolean) {
  return {
    method: "message",
    params: { ...context(seq), text, reply_to: null, mentions_me: mentionsMe },
  };
}

let dir: string;
let log: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "spezl-sdk-"));
  log = join(dir, "requests.jsonl");
  process.env["FAKE_SPEZL_LOG"] = log;
});

afterEach(() => {
  delete process.env["FAKE_SPEZL_LOG"];
  delete process.env["FAKE_SPEZL_SCENARIO"];
  rmSync(dir, { recursive: true, force: true });
});

/** A bot on the fake serve; the child inherits the scenario when the bot starts it. */
function bot(scenario: object): Bot {
  process.env["FAKE_SPEZL_SCENARIO"] = JSON.stringify(scenario);
  return new Bot({ binary: FAKE, home: dir });
}

function requests(): Request[] {
  return readFileSync(log, "utf8")
    .split("\n")
    .filter((line) => line !== "")
    .map((line) => JSON.parse(line) as Request);
}

function request(method: string): Record<string, unknown> | undefined {
  const found = requests().filter((r) => r.method === method);
  assert.equal(found.length, 1, `one ${method} request`);
  return found[0]?.params;
}

test("start announces the commands and no voice, then runs until closed", async () => {
  const b = bot({ notifications: [{ method: "ready", params: { server: SERVER } }] });
  const ready: Array<[string, string]> = [];
  b.command(
    {
      name: "poll",
      description: "Start a poll",
      fields: [{ type: "text", id: "q", label: "Question", maxChars: 50 }],
    },
    () => {},
  );
  b.onReady(async (server) => {
    ready.push([server, b.name]);
    await b.close();
  });
  await b.run();
  assert.deepEqual(ready, [[SERVER, "TestBot"]]);
  assert.deepEqual(
    requests().map((r) => r.method),
    ["info", "set_commands", "set_voice", "shutdown"],
  );
  assert.deepEqual(request("set_commands"), {
    commands: [
      {
        name: "poll",
        description: "Start a poll",
        fields: [
          {
            type: "text",
            id: "q",
            label: "Question",
            required: true,
            placeholder: "",
            max_chars: 50,
          },
        ],
      },
    ],
  });
  assert.deepEqual(request("set_voice"), { voice: false });
});

test("a mention is answered as a reply in its channel", async () => {
  const b = bot({
    notifications: [message(7, "just chatting", false), message(8, "@TestBot hi", true)],
  });
  const seen: number[] = [];
  const replies: number[] = [];
  b.onMessage((msg: Message) => {
    seen.push(msg.seq);
  });
  b.onMention(async (msg) => {
    replies.push(await msg.reply(`hi, @${msg.sender.name}!`));
    await b.close();
  });
  await b.run();
  assert.deepEqual(seen, [7, 8]);
  assert.deepEqual(replies, [101]);
  assert.deepEqual(request("send"), {
    server: SERVER,
    group: "g1",
    text: "hi, @alice!",
    reply_to: 8,
  });
});

test("a private answer goes to the invoking member only", async () => {
  const invocation = { ...context(9), command: "poll", values: { q: "Pizza?" } };
  const b = bot({
    notifications: [
      { method: "invocation", params: { ...invocation, command: "unknown" } },
      { method: "invocation", params: invocation },
    ],
  });
  const values: unknown[] = [];
  b.command({ name: "poll", description: "Start a poll" }, async (inv) => {
    values.push(inv.values);
    await inv.respond({ body: "Noted" }, { private: true });
    await b.close();
  });
  await b.run();
  assert.deepEqual(values, [{ q: "Pizza?" }]);
  assert.deepEqual(request("post_card"), {
    server: SERVER,
    group: "g1",
    card: { body: "Noted", blocks: [] },
    answers: 9,
    to: ALICE.id,
  });
});

test("a failing handler leaves the bot running", async (t) => {
  const printed: unknown[] = [];
  t.mock.method(console, "error", (err: unknown) => {
    printed.push(err);
  });
  const b = bot({
    notifications: [message(7, "boom", false), { method: "ready", params: { server: SERVER } }],
  });
  const ready: string[] = [];
  b.onMessage(() => {
    throw new Error("handler bug");
  });
  b.onReady(async (server) => {
    ready.push(server);
    await b.close();
  });
  await b.run();
  assert.deepEqual(ready, [SERVER]);
  assert.match(String(printed[0]), /handler bug/);
});

test("an error of serve reaches the caller with its code", async () => {
  const b = bot({
    notifications: [message(8, "@TestBot hi", true)],
    errors: { send: { code: -32000, message: "not in that channel" } },
  });
  const errors: Array<[number | undefined, string]> = [];
  b.onMention(async (msg) => {
    try {
      await msg.reply("hi");
    } catch (err) {
      assert.ok(err instanceof SpezlError);
      errors.push([err.code, err.message]);
    }
    await b.close();
  });
  await b.run();
  assert.deepEqual(errors, [[-32000, "not in that channel"]]);
});

test("a serve of another protocol is refused", async () => {
  const b = bot({ info: { protocol: 3 } });
  await assert.rejects(b.run(), (err: unknown) => {
    assert.ok(err instanceof SpezlError);
    assert.match(err.message, /protocol 3/);
    return true;
  });
  assert.deepEqual(
    requests().map((r) => r.method),
    ["info"],
  );
});
