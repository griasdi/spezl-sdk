"""Mickey: a voice bot that plays back what it heard, 1.5x faster.

Inside a voice channel the bot records what it hears. Once nobody has said anything for more
than 3 s, it plays the recording back sped up 1.5x: a fifth higher and shorter, like Mickey
Mouse.

Invite it from the griasdi desktop while you are in a voice channel: right-click the bot in
the member list and pick "Invite to voice". Hover over it in the voice channel and press
"Send home" to make it leave; it also leaves on its own once no human is left.

Run it with `spezl run examples/mickey/mickey.py`.
"""

import asyncio
import math
import sys
from array import array

import spezl

QUIET_S = 3.0
"""Silence after which the bot plays back what it recorded."""
LOUD_RMS = 300.0
"""16-bit RMS from which a frame counts as speech: about -40 dBFS."""
MAX_RECORDING_S = 30
"""The bot keeps the last this many seconds of a recording."""
SPEED = 1.5

bot = spezl.Bot(voice=True)

recording = array("h")
"""What the bot heard since the first loud frame."""
quiet = 0
"""Quiet samples at the end of `recording`."""
playing: asyncio.Task | None = None


def rms(samples: array) -> float:
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def faster(samples: array, speed: float) -> array:
    """`samples` played `speed` times as fast, by linear interpolation."""
    n = len(samples)
    out = array("h", bytes(2 * max(0, int((n - 1) / speed))))
    for i in range(len(out)):
        pos = i * speed
        j = int(pos)
        f = pos - j
        out[i] = round(samples[j] * (1 - f) + samples[j + 1] * f)
    return out


def reset() -> None:
    global recording, quiet
    recording = array("h")
    quiet = 0


async def play_back(clip: array) -> None:
    try:
        samples = await asyncio.to_thread(faster, clip, SPEED)
        await bot.play(samples)
    except spezl.SpezlError as e:
        print(f"cannot play back: {e}", file=sys.stderr, flush=True)


@bot.on_ready
async def ready(server: str) -> None:
    print(f"{bot.name} ready on {server}", flush=True)


@bot.on_voice_join
async def joined(voice: spezl.Voice) -> None:
    by = voice.by.name if voice.by else "nobody"
    print(f"joined {voice.channel.name}, invited by {by}", flush=True)


@bot.on_voice_leave
async def left(voice: spezl.Voice) -> None:
    by = f"sent home by {voice.by.name}" if voice.by else "on its own"
    print(f"left {voice.channel.name}, {by}", flush=True)
    reset()


@bot.on_audio
async def hear(audio: spezl.Audio) -> None:
    global quiet, playing
    if playing is not None and not playing.done():
        return
    loud = rms(audio.samples) >= LOUD_RMS
    if not recording and not loud:
        return
    recording.extend(audio.samples)
    quiet = 0 if loud else quiet + len(audio.samples)
    keep = MAX_RECORDING_S * spezl.SAMPLE_RATE
    if len(recording) > keep:
        del recording[: len(recording) - keep]
    if quiet >= QUIET_S * spezl.SAMPLE_RATE:
        clip = recording[: len(recording) - quiet]
        reset()
        playing = asyncio.create_task(play_back(clip))


bot.run()
