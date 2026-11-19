# Hello

The smallest bot: it answers every @mention with `hi, @<name>!`. The same bot is here in
Python and TypeScript.

## What it shows

- Reacting to a mention: `@bot.on_mention` in [Python](../../README.md#python),
  `bot.onMention` in [TypeScript](../../README.md#typescript).
- Answering with `reply`.

## Run it

From the repo root, with a bot identity that has joined a community:

```sh
spezl new HelloBot
spezl --bot HelloBot join '<invite link>'
```

Then start it in one of the languages below and write `@HelloBot hi` in one of its channels. The
commands below run the default bot: make HelloBot the default with `spezl default HelloBot`, or
put `--bot HelloBot` after `spezl`.

### Python

```sh
spezl run examples/hello/python/hello.py
```

The SDK comes in through `[tool.uv.sources]` in `python/pyproject.toml`, as an editable path
source.

### TypeScript

```sh
spezl run examples/hello/typescript/hello.ts
```

`hello.ts` imports the SDK relatively from `sdk/typescript/src/index.ts`; there is no build
step.

## Requirements

- Python: [uv](https://docs.astral.sh/uv/) (Python ≥ 3.10).
- TypeScript: Node ≥ 22.18 or Bun.
