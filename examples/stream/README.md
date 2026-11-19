# Stream

Streams the video files of a directory into a channel as a screen share. `/videos` lists the
video files of the directory (`.mp4`, `.m4v`, `.mkv`, `.webm`, `.mov`, `.avi`, `.ogv`) with a
▶ Start button each and a ⏹ Stop button. The bot keeps where a file stopped in
`$SPEZL_HOME/stream.sqlite3`; such a file shows ▶ Resume and ⏮ From start instead.

## What it shows

- `stream_file` with a start offset and `stop_stream`.
- `@bot.on_stream_ended`, whose position the bot stores to resume from later.
- A command answered with a card of buttons.

See [Streaming video](https://griasdi.github.io/bots/#streaming) and the
[Python SDK](../../README.md#python).

## Run it

From the repo root:

```sh
spezl new StreamBot
spezl --bot StreamBot join '<invite link>'
spezl --bot StreamBot run examples/stream/stream.py ~/Videos
```

Without an argument it uses `./videos`. `--bot StreamBot` can go when StreamBot is the default
bot (`spezl default StreamBot`).

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python ≥ 3.10).
- GStreamer with the base, good and bad plugins, plus libav for H.264 and older formats. Which
  encoder (AV1 or H.264) is used and how `SPEZL_ENCODER` forces one is in
  [Streaming video](https://griasdi.github.io/bots/#streaming).
