# Mickey

A voice bot. It records what it hears in voice and, after more than 3 s of quiet, plays it back
1.5× as fast: a fifth higher and shorter, like Mickey Mouse.

Invite it from the griasdi desktop app while you are in a voice channel: right-click the bot in
the member list and pick "Invite to voice". Hover over it in the voice channel and press "Send
home" to make it leave; it also leaves on its own once no human is left.

## What it shows

- Declaring voice with `spezl.Bot(voice=True)`.
- Hearing with `@bot.on_audio`.
- Playing samples with `await bot.play(samples)`.

See [Voice](https://griasdi.github.io/bots/#voice) and the [Python SDK](../../README.md#python).

## Run it

From the repo root:

```sh
spezl new Mickey
spezl --bot Mickey join '<invite link>'
spezl --bot Mickey run examples/mickey/mickey.py
```

`--bot Mickey` can go when Mickey is the default bot (`spezl default Mickey`).

Python only: the TypeScript SDK has no voice.

## Requirements

[uv](https://docs.astral.sh/uv/) (Python ≥ 3.10).
