# Poll

`/poll` opens a form, and the bot answers with a poll built from it. The form asks for:

- the question (at most 300 characters);
- the options (2 to 10, each at most 100 characters);
- three toggles: "Allow several answers", "Show results only when it ends" (results stay
  hidden until then) and "Show who voted";
- when it ends: when the creator ends it, in 1 hour, in 1 day or in 1 week.

The same bot is here in Python and TypeScript.

## What it shows

- A slash command with a form: text, text list, toggle and choice fields (see
  [Commands and cards](https://griasdi.github.io/bots/#commands)).
- Answering an invocation with a card that holds a poll.

## Run it

From the repo root, with a bot identity that has joined a community:

```sh
spezl new PollBot
spezl --bot PollBot join '<invite link>'
```

Then start it in one of the languages below and type `/poll` in one of its channels. The
commands below run the default bot: make PollBot the default with `spezl default PollBot`, or
put `--bot PollBot` after `spezl`.

### Python

```sh
spezl run examples/poll/python/poll.py
```

The SDK comes in through `[tool.uv.sources]` in `python/pyproject.toml`, as an editable path
source.

### TypeScript

```sh
spezl run examples/poll/typescript/poll.ts
```

`poll.ts` imports the SDK relatively from `sdk/typescript/src/index.ts`; there is no build step.

## Requirements

- Python: [uv](https://docs.astral.sh/uv/) (Python ≥ 3.10).
- TypeScript: Node ≥ 22.18 or Bun.
