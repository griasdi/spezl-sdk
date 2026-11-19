// The TypeScript SDK against the real `spezl serve`, without a griasdi server: serve checks the
// wire of commands and cards as strictly as with one (unknown keys and variants are errors).
// Skipped without spezl (`SPEZL_BIN`, else `spezl` on `PATH`); get it from
// https://griasdi.github.io/bots/.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import { Bot, SpezlError, type Block, type Field } from "../src/index.ts";

function findSpezl(): string | undefined {
  if (process.env["SPEZL_BIN"]) return process.env["SPEZL_BIN"];
  try {
    return execFileSync("sh", ["-c", "command -v spezl"], { encoding: "utf8" }).trim() || undefined;
  } catch {
    return undefined;
  }
}

const SPEZL = findSpezl();

const FIELDS: Field[] = [
  { type: "text", id: "text", label: "Text", placeholder: "…", maxChars: 50, required: false },
  { type: "textList", id: "list", label: "List", min: 2, max: 5, maxChars: 20 },
  { type: "toggle", id: "toggle", label: "Toggle", default: true },
  {
    type: "choice",
    id: "choice",
    label: "Choice",
    options: [
      { id: "a", label: "A" },
      { id: "b", label: "B" },
    ],
    default: "a",
  },
  {
    type: "select",
    id: "select",
    label: "Select",
    options: [
      { id: "x", label: "X" },
      { id: "y", label: "Y", when: ["b"] },
    ],
    on: "choice",
    tiles: true,
  },
  { type: "dateTime", id: "when", label: "When" },
  { type: "clientInfo", id: "client", label: "Client", required: false },
];

const BUTTON = { id: "ok", label: "OK", style: "primary" } as const;
const BLOCKS: Block[] = [
  { type: "buttons", buttons: [BUTTON, { id: "no", label: "No", style: "danger" }] },
  { type: "list", items: [{ title: "Row", detail: "detail", buttons: [BUTTON] }] },
  {
    type: "form",
    button: { id: "form", label: "Open" },
    form: { title: "Form", text: "Fill in", fields: FIELDS, submit: "Send" },
  },
  { type: "columns", columns: ["left", "right"] },
  { type: "hintedButtons", buttons: [{ id: "h", label: "Hinted", hint: "a hint", style: "success" }] },
  { type: "links", links: [{ label: "Site", url: "https://griasdi.github.io/" }] },
  {
    type: "tally",
    options: [
      { id: "t1", label: "Join" },
      { id: "t2", label: "Maybe", hint: "late" },
    ],
  },
  { type: "poll", question: "Pizza?", options: ["Yes", "No"], multiple: true, closesMs: 1_900_000_000_000 },
];

test(
  "serve takes every field and block the SDK writes",
  { skip: SPEZL === undefined && "needs spezl: SPEZL_BIN or spezl on PATH" },
  async () => {
    const spezl = SPEZL as string;
    const dir = mkdtempSync(join(tmpdir(), "spezl-sdk-"));
    try {
      execFileSync(spezl, ["--dir", dir, "new", "SdkTest"], { stdio: "ignore" });
      const bot = new Bot({ home: join(dir, "bots/SdkTest"), binary: spezl });
      bot.command({ name: "every-field", description: "Every field kind", fields: FIELDS }, () => {});
      // Rejects if serve refused set_commands or set_voice.
      const running = bot.run();
      let ended = false;
      running.then(
        () => (ended = true),
        () => (ended = true),
      );
      // Polled: without a griasdi server no `ready` comes, and the SDK has no other signal for
      // "started"; `name` answers once serve's `info` is in.
      for (;;) {
        try {
          assert.equal(bot.name, "SdkTest");
          break;
        } catch (err) {
          if (!(err instanceof SpezlError)) throw err;
          if (ended) {
            await running;
            throw err;
          }
          await sleep(20);
        }
      }
      try {
        assert.deepEqual(await bot.communities(), []);
        // The bot is on no server, so serve refuses a card for its server only after it parsed
        // the card and checked griasdi's limits: a wire mistake would be refused for the card
        // instead. One block per card keeps each within the limits.
        const channel = { server: "griasdi:server:none", id: "00", name: "x", group: "00" };
        for (const block of BLOCKS) {
          await assert.rejects(bot.postCard(channel, { body: "**A block**", blocks: [block] }), (err) => {
            assert.ok(err instanceof SpezlError);
            assert.equal(err.code, -32602, `${block.type}: ${err.message}`);
            assert.match(err.message, /not a server link/, block.type);
            return true;
          });
        }
      } finally {
        await bot.close();
        await running;
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  },
);
