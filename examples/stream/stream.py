"""Streams video files into a channel: /videos lists the files of a directory, ▶ Start streams
one as a screen share. A file stopped before its end is remembered with its position (SQLite
in the bot home); /videos then offers ▶ Resume and ⏮ From start. Run it with the directory:

    spezl run examples/stream/stream.py ~/Videos
"""

import os
import sqlite3
import sys
from pathlib import Path

import spezl

bot = spezl.Bot()

VIDEOS = Path(sys.argv[1] if len(sys.argv) > 1 else "videos").resolve()
EXTENSIONS = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ogv"}
# `spezl run` sets SPEZL_HOME; without it, the current directory.
DB_PATH = Path(os.environ.get("SPEZL_HOME") or ".") / "stream.sqlite3"

# 7 lists of 10 items fit beside the Buttons block: a card has at most 8 blocks.
MAX_FILES = 70
PER_LIST = 10
MAX_TITLE = 80
MAX_SHARE_TITLE = 64
"""griasdi's `MAX_SHARE_TITLE`: a receiver drops a share whose title is longer."""

# Card seq → the files that card lists. Buttons carry indexes, so no path a member sends ever
# reaches the bot.
listings: dict[tuple[str, str, int], list[Path]] = {}
# Listings kept: the oldest card's buttons go stale beyond them.
MAX_LISTINGS = 50
# (server, group) of the running stream; None while nothing streams.
streaming_in: tuple[str, str] | None = None


def videos() -> list[Path]:
    """The video files directly in `VIDEOS`, by name."""
    files = [
        p for p in VIDEOS.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.casefold())


def shorten(name: str, limit: int = MAX_TITLE) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def readable(path: Path) -> str:
    """The file name as a title: no extension and, in a name without spaces, `.` and `_` as
    spaces, so a long name wraps beside the buttons."""
    # A file name can hold anything a file system takes, control characters included.
    name = "".join(c if c.isprintable() else " " for c in path.stem)
    if " " not in name:
        name = name.replace(".", " ").replace("_", " ")
    return " ".join(name.split()) or "Video"


def file_size(path: Path) -> str:
    """`1.5 GB`, `700 MB` or `12 kB`."""
    n = path.stat().st_size
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n / 1000:.0f} kB"


def clock(ms: int) -> str:
    """`m:ss`, or `h:mm:ss` from an hour on."""
    s = ms // 1000
    if ms >= 3_600_000:
        return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}"
    return f"{s // 60}:{s % 60:02}"


def saved(path: Path) -> int | None:
    """Where `path` stopped, in ms; `None` when it played to its end or never ran."""
    row = db.execute(
        "SELECT position_ms FROM positions WHERE path = ?", (str(path),)
    ).fetchone()
    return row[0] if row else None


def remember(path: str, ms: int) -> None:
    with db:
        db.execute(
            "INSERT INTO positions (path, position_ms) VALUES (?, ?) "
            "ON CONFLICT(path) DO UPDATE SET position_ms = excluded.position_ms",
            (path, ms),
        )


def forget(path: str) -> None:
    with db:
        db.execute("DELETE FROM positions WHERE path = ?", (path,))


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.command("videos", "List the videos I can stream")
async def list_videos(inv: spezl.Invocation) -> None:
    every = videos()
    files = every[:MAX_FILES]
    if not files:
        await inv.respond(spezl.Card(f"No videos in `{VIDEOS.name}`."))
        return
    body = (
        f"🎬 **Videos** in `{VIDEOS.name}`\n"
        "A file plays here once someone opens the stream; a new start replaces the running one."
    )
    if len(every) > MAX_FILES:
        body += f"\nShowing the first {MAX_FILES} of {len(every)}."
    items = []
    for i, path in enumerate(files):
        ms = saved(path)
        parts = [path.suffix[1:].upper(), file_size(path)]
        if ms is None:
            buttons = [spezl.Button(f"play-{i}", "▶ Start", "primary")]
        else:
            parts.append(f"stopped at {clock(ms)}")
            buttons = [
                spezl.Button(f"resume-{i}", "▶ Resume", "primary"),
                spezl.Button(f"play-{i}", "⏮ From start"),
            ]
        items.append(
            spezl.ListItem(
                title=shorten(readable(path)), detail=" · ".join(parts), buttons=buttons
            )
        )
    blocks: list = [
        spezl.ItemList(items[at : at + PER_LIST]) for at in range(0, len(items), PER_LIST)
    ]
    blocks.append(spezl.Buttons([spezl.Button("stop", "⏹ Stop", "danger")]))
    seq = await inv.respond(spezl.Card(body, blocks))
    listings[(inv.channel.server, inv.channel.group, seq)] = files
    while len(listings) > MAX_LISTINGS:
        del listings[next(iter(listings))]


@bot.on_press
async def pressed(press: spezl.Press) -> None:
    global streaming_in
    here = (press.channel.server, press.channel.group)
    if press.button == "stop":
        # A list in another channel cannot stop what streams here.
        if streaming_in not in (None, here):
            await press.reply("The stream runs in another channel.", private=True)
        else:
            stopped = await bot.stop_stream()
            streaming_in = None
            if not stopped:
                await press.reply("Nothing is streaming.", private=True)
        return
    if press.button.startswith("resume-"):
        resume, index = True, press.button.removeprefix("resume-")
    elif press.button.startswith("play-"):
        resume, index = False, press.button.removeprefix("play-")
    else:
        return
    if streaming_in not in (None, here):
        await press.reply("A stream runs in another channel: it has to end first.", private=True)
        return
    files = listings.get((press.channel.server, press.channel.group, press.card))
    if files is None or not index.isdigit() or int(index) >= len(files):
        await press.reply("This list is out of date: run /videos again.", private=True)
        return
    path = files[int(index)]
    if not path.is_file():
        await press.reply(f"`{path.name}` is gone.", private=True)
        return
    # Starting over keeps the saved position: the next end overwrites or deletes it.
    start_ms = (saved(path) or 0) if resume else 0
    title = shorten(readable(path), MAX_SHARE_TITLE)
    # Claimed before the await: a press from another channel meanwhile is refused.
    streaming_in = here
    try:
        await bot.stream_file(press.channel, path, title=title, start_ms=start_ms)
    except spezl.SpezlError as e:
        # `stream_file` stopped the running stream before it failed.
        streaming_in = None
        await press.reply(f"Cannot stream `{path.name}`: {e}", private=True)
        return
    streaming_in = here
    start = f" from {clock(start_ms)}," if start_ms > 0 else ","
    await press.reply(
        f"▶ **{title}**{start} started by {press.sender.name}. Open the stream above to "
        "watch; it starts with the first viewer."
    )


@bot.on_stream_ended
async def ended(ended: spezl.StreamEnded) -> None:
    global streaming_in
    # A replaced stream ends with "stopped" while its successor runs.
    if ended.reason != "stopped":
        streaming_in = None
    title = ended.title
    # Positions under a second are not worth a ▶ Resume.
    if ended.reason != "finished" and ended.position_ms >= 1000:
        remember(ended.path, ended.position_ms)
    else:
        forget(ended.path)
    if ended.reason == "stopped":
        text = f"⏹ **{title}** was stopped."
    elif ended.reason == "failed":
        text = f"⚠️ **{title}** failed: {ended.error}"
    elif ended.reason == "lost":
        text = f"⏹ **{title}** ended: the server closed the stream."
    else:
        text = f"⏹ **{title}** has ended."
    await bot.send(ended.channel, text)


if not VIDEOS.is_dir():
    print(
        f"no video directory {VIDEOS}: pass one, e.g. spezl run examples/stream/stream.py ~/Videos",
        file=sys.stderr,
    )
    sys.exit(2)

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(DB_PATH)
with db:
    db.execute(
        "CREATE TABLE IF NOT EXISTS positions "
        "(path TEXT PRIMARY KEY, position_ms INTEGER NOT NULL)"
    )

bot.run()
