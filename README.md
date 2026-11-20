# spezl SDKs

The Python and TypeScript SDKs and the example bots for
[spezl](https://griasdi.github.io/bots/), the bot runner of griasdi. A spezl bot is an ordinary
griasdi member: it has its own identity, joins a community through a normal invite link and
reads and writes the channels it may view. The SDKs here have no dependencies; they start
`spezl serve`, a sidecar that speaks JSON-RPC on stdin/stdout.

## spezl

The bots need the `spezl` program: download it for Linux (x86_64, ARM64) from
https://griasdi.github.io/bots/ and unpack it into `~/.local`. The bot guide there documents
the `spezl` command, the events and the `spezl serve` protocol the SDKs speak. `spezl` is free
for non-commercial use under its own license; the SDKs and examples here are MIT-licensed
([LICENSE](LICENSE)).

Changes are welcome: the checks run without a griasdi server, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Python

The SDK is in `sdk/python`, uses only the standard library and needs Python ≥ 3.10. It is on
PyPI as `spezl`:

```sh
pip install spezl   # or: uv add spezl
```

```python
import spezl

bot = spezl.Bot()  # Bot(home=..., binary=...) overrides SPEZL_HOME / SPEZL_BIN


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.on_mention  # @bot.on_message gets every message
async def greet(msg: spezl.Message) -> None:
    await msg.reply(f"hi, @{msg.sender.name}!")


bot.run()
```

- **Messages**: `msg.text`, `msg.sender.name`, `msg.sender.bot_id` (a convention of honest bot
  software, not proof), `msg.channel.name`, `msg.community.name`, `msg.seq`, `msg.reply_to`.
- **Sending**: `await bot.send(channel, text, reply_to=None)` sends to a `spezl.Channel`, and
  `await bot.send_dm(server, user, text)` a direct message to a member (user id).
  `await bot.communities()` lists the communities with their channels.
- **Errors**: an exception in a handler is printed and the bot keeps running.
- **Commands**: `@bot.command(name, description, fields=[...])` registers the handler of one
  command, with `spezl.TextField`, `TextListField`, `ToggleField`, `ChoiceField`,
  `SelectField` (options as `(id, label)` pairs or `spezl.SelectOption(id, label, when=[…])`,
  with `on=` and `tiles=`), `DateTimeField` and `ClientInfoField` (the member's app fills in
  their operating system and app version; they may edit it); `inv.values` maps field ids to
  the values, and `await inv.respond(card)` answers (`private=True`: only the invoking member
  sees it).
- **Cards**: `spezl.Card(body, blocks=[spezl.Buttons([spezl.Button(id, label, style)]),
  spezl.HintedButtons([spezl.HintedButton(id, label, hint, style)]),
  spezl.Tally([spezl.TallyOption(id, label, hint, style, members=[user ids])]),
  spezl.ItemList([spezl.ListItem(title, detail, [buttons])]), spezl.FormButton(id, label,
  spezl.Form(title, fields, text=…, submit=…)), spezl.Columns([markdown, …]),
  spezl.Image(await bot.upload_image(channel, png_bytes), alt), spezl.Links([spezl.LinkButton(label,
  url, style)]), spezl.Poll(question, options, multiple=…,
  hidden_results=…, show_voters=…, closes_ms=…, creator=…)])`; `await bot.post_card(channel,
  card, to=None)` posts one (`to`: the user id of the only member who sees it), `await
  bot.edit_card(channel, seq, body)` replaces its body, `await bot.replace_card(channel, seq,
  card)` its body and blocks in place, `await bot.delete_message(channel, seq)` deletes it,
  `await bot.reveal(channel, action, target)` scrolls the presser's chat to card `target`,
  `@bot.on_press` gets presses and
  `await press.reply(text, private=False)` answers one; `@bot.on_submit` gets filled-in forms
  (`submit.values`, `submit.card`, `submit.button`) and `await submit.reply(text, private=…)`;
  `await press.reveal(seq)` and `await submit.reveal(seq)` reveal a card in answer to that press
  or form.
- **Voice**: `spezl.Bot(voice=True)` takes voice invites; `@bot.on_voice_join` and
  `@bot.on_voice_leave` get a `spezl.Voice` (`voice.channel`, `voice.community`, `voice.by`:
  who invited the bot or sent it home, `None` when it left on its own); `@bot.on_audio` gets
  every `spezl.Audio` frame in order (`audio.samples`: `array('h')`, `spezl.AUDIO_FRAME`
  samples at `spezl.SAMPLE_RATE`); `await bot.play(samples)` plays an `array('h')` and raises
  `SpezlError` when the bot is in no voice channel or leaves before the end.
- **New members**: `@bot.on_member_join` gets a `spezl.MemberJoined` (`joined.community` with its
  `channels`, `joined.member`).

Each Python example (e.g. `examples/hello/python`) shows how a project pulls in the SDK: with
uv, through `[tool.uv.sources] spezl = { path = "../../../sdk/python", editable = true }`.

## TypeScript

The SDK is in `sdk/typescript`. It uses only `node:` modules and runs on Node ≥ 22.18 and on
Bun. It is on npm as `@griasdilab/spezl`, compiled to JavaScript with type declarations:

```sh
npm install @griasdilab/spezl   # then: import { Bot } from "@griasdilab/spezl";
npm install -D typescript @types/node   # optional, to typecheck your bot
```

Your `package.json` needs `"type": "module"`.

The examples here import the SDK by its path instead (`../../../sdk/typescript/src/index.ts`).

```ts
import { Bot } from "../../../sdk/typescript/src/index.ts";

const bot = new Bot(); // new Bot({ home, binary }) overrides SPEZL_HOME / SPEZL_BIN
bot.onReady((server) => console.log(`${bot.name} ready on ${server}`));
bot.onMention(async (msg) => {
  await msg.reply(`hi, @${msg.sender.name}!`);
});
await bot.run(); // resolves when the bot stops (SIGINT/SIGTERM or bot.close())
```

- **Fields** are camelCase: `msg.sender.botId`, `msg.replyTo`, `msg.mentionsMe`.
- **Sending**: `bot.send(channel, text, { replyTo })`, `bot.sendDm(server, user, text)` for a
  direct message, and `bot.communities()` lists the communities.
- **New members**: `bot.onMemberJoin(handler)` gets a `MemberJoined` (`community`, `member`).
- **Typecheck**: `cd sdk/typescript && npm install && npm run check`.
- **Commands**: `bot.command({ name, description, fields }, handler)` with fields like
  `{ type: "textList", id, label, min, max, maxChars }`, `{ type: "clientInfo", id, label }`
  or `{ type: "select", id, label, options: [{ id, label, when }], on, tiles }`;
  `inv.respond(card, { private })` answers,
  `bot.postCard(channel, card, { to })` posts a card (blocks `buttons`, `poll`, `{ type:
  "list", items }`, `{ type: "form", button, form: { title, text, fields, submit } }`,
  `{ type: "columns", columns }`, `{ type: "hintedButtons", buttons: [{ id, label, style,
  hint }] }`, `{ type: "image", image: await bot.uploadImage(channel, bytes), alt }`,
  `{ type: "links", links: [{ label, url, style }] }` and `{ type: "tally", options: [{ id,
  label, style, hint, members }] }`),
  `bot.editCard(channel, seq, body)` replaces its body, `bot.replaceCard(channel, seq, card)`
  its body and blocks in place, `bot.deleteMessage(channel, seq)` deletes it,
  `bot.reveal(channel, action, target)` and `press.reveal(seq)`/`submit.reveal(seq)` scroll the
  presser's chat to a card,
  `bot.onPress(handler)` gets presses,
  `press.reply(text, { private })` answers one, and `bot.onSubmit(handler)` gets filled-in
  forms (`submit.values`, `submit.reply`).

## Examples

Every example has its own folder and README; run them from the repo root with `spezl run`.

| Folder | Languages | What it shows |
|---|---|---|
| [`examples/hello`](examples/hello) | Python, TypeScript | answering an @mention |
| [`examples/poll`](examples/poll) | Python, TypeScript | a slash command with a form, answered with a poll |
| [`examples/raid`](examples/raid) | Python | a raid sign-up bot: forms, private cards, tallies, images, `replace_card`, `reveal`, SQLite |
| [`examples/mickey`](examples/mickey) | Python | voice: hearing and playing audio |
| [`examples/stream`](examples/stream) | Python | streaming video files as a screen share |
| [`examples/welcome`](examples/welcome) | Python | greeting new members in a channel and by direct message; filing `/issue` and `/request` as GitHub issues |
