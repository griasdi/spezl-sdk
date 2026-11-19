from __future__ import annotations

import asyncio
import base64
import os
import shutil
import signal
import sys
import traceback
from array import array
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ._rpc import CLOSE_TIMEOUT, Connection
from ._types import (
    Audio,
    Card,
    CardImage,
    Channel,
    Community,
    Field,
    Invocation,
    MemberJoined,
    Message,
    Press,
    SpezlError,
    StreamEnded,
    Submit,
    Voice,
    audio_from_wire,
    community_from_wire,
    invocation_from_wire,
    member_joined_from_wire,
    message_from_wire,
    press_from_wire,
    samples_to_wire,
    stream_ended_from_wire,
    submit_from_wire,
    voice_from_wire,
)

PROTOCOL = 2

AUDIO_BACKLOG = 50
"""Heard frames held for slow audio handlers: 1 s of 20 ms frames, as in the Rust SDK. While
it is full, newer frames are dropped."""

MessageHandler = Callable[[Message], Awaitable[None]]
ReadyHandler = Callable[[str], Awaitable[None]]
InvocationHandler = Callable[[Invocation], Awaitable[None]]
PressHandler = Callable[[Press], Awaitable[None]]
_M = TypeVar("_M", bound=MessageHandler)
_R = TypeVar("_R", bound=ReadyHandler)
_I = TypeVar("_I", bound=InvocationHandler)
_P = TypeVar("_P", bound=PressHandler)
SubmitHandler = Callable[[Submit], Awaitable[None]]
_S = TypeVar("_S", bound=SubmitHandler)
VoiceHandler = Callable[[Voice], Awaitable[None]]
_V = TypeVar("_V", bound=VoiceHandler)
AudioHandler = Callable[[Audio], Awaitable[None]]
_A = TypeVar("_A", bound=AudioHandler)
StreamEndedHandler = Callable[[StreamEnded], Awaitable[None]]
_E = TypeVar("_E", bound=StreamEndedHandler)
MemberJoinedHandler = Callable[[MemberJoined], Awaitable[None]]
_J = TypeVar("_J", bound=MemberJoinedHandler)


class Bot:
    """A griasdi bot. Register handlers, then call `run()`."""

    def __init__(
        self, *, home: str | None = None, binary: str | None = None, voice: bool = False
    ) -> None:
        """`voice`: whether the bot takes voice invites; members in a voice channel then offer
        "Invite to voice" for it."""
        resolved = binary or os.environ.get("SPEZL_BIN") or shutil.which("spezl")
        if not resolved:
            raise SpezlError("spezl not found: put it on PATH or set SPEZL_BIN")
        self._binary = resolved
        self._home = home or os.environ.get("SPEZL_HOME") or None
        self._conn: Connection | None = None
        self._closing = False
        self._user_id: str | None = None
        self._name: str | None = None
        self._message_handlers: list[MessageHandler] = []
        self._mention_handlers: list[MessageHandler] = []
        self._ready_handlers: list[ReadyHandler] = []
        self._tasks: set[asyncio.Task] = set()
        self._commands: dict[str, dict] = {}
        self._command_handlers: dict[str, InvocationHandler] = {}
        self._press_handlers: list[PressHandler] = []
        self._submit_handlers: list[SubmitHandler] = []
        self._voice = voice
        self._voice_join_handlers: list[VoiceHandler] = []
        self._voice_leave_handlers: list[VoiceHandler] = []
        self._audio_handlers: list[AudioHandler] = []
        self._audio_queue: asyncio.Queue[Audio | None] | None = None
        self._stream_ended_handlers: list[StreamEndedHandler] = []
        self._member_join_handlers: list[MemberJoinedHandler] = []

    # -- registration ---------------------------------------------------------

    def on_message(self, handler: _M) -> _M:
        """Register `handler` for every message in a channel the bot can read."""
        self._message_handlers.append(handler)
        return handler

    def on_mention(self, handler: _M) -> _M:
        """Register `handler` for messages that mention the bot."""
        self._mention_handlers.append(handler)
        return handler

    def on_ready(self, handler: _R) -> _R:
        """Register `handler(server)`, called when a server is connected and synced."""
        self._ready_handlers.append(handler)
        return handler

    def command(
        self, name: str, description: str, fields: list[Field] | None = None
    ) -> Callable[[_I], _I]:
        """Offer the slash command `/name` in every channel; members fill in `fields` and
        the decorated `handler(invocation)` runs. One handler per name."""

        def register(handler: _I) -> _I:
            self._commands[name] = {
                "name": name,
                "description": description,
                "fields": [f.to_wire() for f in fields or []],
            }
            self._command_handlers[name] = handler
            return handler

        return register

    def on_press(self, handler: _P) -> _P:
        """Register `handler(press)` for presses of buttons on the bot's cards."""
        self._press_handlers.append(handler)
        return handler

    def on_submit(self, handler: _S) -> _S:
        """Register `handler(submit)` for forms members send from the bot's cards."""
        self._submit_handlers.append(handler)
        return handler

    def on_voice_join(self, handler: _V) -> _V:
        """Register `handler(voice)`, called when a member invited the bot into a voice
        channel and it joined. Needs `Bot(voice=True)`."""
        self._voice_join_handlers.append(handler)
        return handler

    def on_voice_leave(self, handler: _V) -> _V:
        """Register `handler(voice)`, called when the bot left its voice channel."""
        self._voice_leave_handlers.append(handler)
        return handler

    def on_audio(self, handler: _A) -> _A:
        """Register `handler(audio)` for every 20 ms of what the bot hears in voice. Frames
        come one at a time, in order: a handler that takes longer than 20 ms falls behind."""
        self._audio_handlers.append(handler)
        return handler

    def on_stream_ended(self, handler: _E) -> _E:
        """Register `handler(ended)`, called when a stream of the bot ended."""
        self._stream_ended_handlers.append(handler)
        return handler

    def on_member_join(self, handler: _J) -> _J:
        """Register `handler(joined)`, called once for each member who joined a community of
        the bot, also for one who joined while the bot was offline."""
        self._member_join_handlers.append(handler)
        return handler

    # -- properties -----------------------------------------------------------

    @property
    def user_id(self) -> str:
        if self._user_id is None:
            raise SpezlError("the bot has not started yet")
        return self._user_id

    @property
    def name(self) -> str:
        if self._name is None:
            raise SpezlError("the bot has not started yet")
        return self._name

    # -- calls ----------------------------------------------------------------

    def _connection(self) -> Connection:
        if self._conn is None:
            raise SpezlError("the bot has not started yet")
        return self._conn

    async def communities(self) -> list[Community]:
        result = await self._connection().request("communities")
        return [community_from_wire(c) for c in result]

    async def send(
        self, channel: Channel, text: str, *, reply_to: int | None = None
    ) -> int:
        """Send `text` into `channel`; returns the seq of the new message."""
        result = await self._connection().request(
            "send",
            {
                "server": channel.server,
                "group": channel.group,
                "text": text,
                "reply_to": reply_to,
            },
        )
        return result["seq"]

    async def send_dm(self, server: str, user: str, text: str) -> int:
        """Send `text` as a direct message to member `user` (user id) on `server`; returns its
        seq."""
        result = await self._connection().request(
            "send_dm", {"server": server, "user": user, "text": text}
        )
        return result["seq"]

    async def post_card(
        self,
        channel: Channel,
        card: Card,
        *,
        answers: int | None = None,
        to: str | None = None,
    ) -> int:
        """Post `card` into `channel`; `answers` is the seq of the invocation it answers, `to`
        the member (user id) who alone sees the card. Returns the seq of the card."""
        params = {
            "server": channel.server,
            "group": channel.group,
            "card": card.to_wire(),
            "answers": answers,
        }
        if to is not None:
            params["to"] = to
        result = await self._connection().request("post_card", params)
        return result["seq"]

    async def edit_card(self, channel: Channel, seq: int, body: str) -> None:
        """Replace the markdown body of the bot's own card `seq` in `channel`; its buttons and
        poll stay."""
        await self._connection().request(
            "edit_card",
            {"server": channel.server, "group": channel.group, "seq": seq, "body": body},
        )

    async def replace_card(self, channel: Channel, seq: int, card: Card) -> None:
        """Replace the bot's own card `seq` in `channel`, body and blocks, in place."""
        await self._connection().request(
            "replace_card",
            {"server": channel.server, "group": channel.group, "seq": seq, "card": card.to_wire()},
        )

    async def delete_message(self, channel: Channel, seq: int) -> None:
        """Delete the bot's own message `seq` in `channel` for everyone."""
        await self._connection().request(
            "delete_message", {"server": channel.server, "group": channel.group, "seq": seq}
        )

    async def reveal(self, channel: Channel, action: int, target: int) -> None:
        """Scroll the chat of the member who sent `action` (the seq of a press or form
        submission on one of the bot's cards in `channel`) to the bot's card `target` there that
        they see: one just posted for them or one just replaced. Their app follows only the
        first reveal per press, within 10 s of it, on the device they pressed on, while that chat
        is open. Raises `SpezlError` when `action` is no press on the bot's card or `target` no
        card of the bot the member sees."""
        await self._connection().request(
            "reveal",
            {"server": channel.server, "group": channel.group, "action": action, "target": target},
        )

    async def upload_image(self, channel: Channel, data: bytes) -> CardImage:
        """Store a picture (PNG, JPEG, GIF or WebP; griasdi shrinks it to at most 1200 px per
        side) encrypted on `channel`'s server for one card's `Image` block. Deleting that card,
        or replacing it with one that no longer shows the picture, deletes it, so every card
        uploads its own; raises `SpezlError` when `data` is no image griasdi can open."""
        result = await self._connection().request(
            "upload_image",
            {
                "server": channel.server,
                "group": channel.group,
                "data": base64.b64encode(data).decode("ascii"),
            },
        )
        return CardImage.from_wire(result)

    async def play(self, samples: array) -> None:
        """Play `samples` (`array('h')`, 48 kHz mono, at most 60 s) into the bot's voice
        channel, after what earlier calls queued. Returns once they are played; raises
        `SpezlError` when the bot is in no voice channel or leaves before the end."""
        if not isinstance(samples, array) or samples.typecode != "h":
            raise TypeError("play takes array('h') samples")
        await self._connection().request(
            "play_audio", {"samples": samples_to_wire(samples)}
        )

    async def stream_file(
        self,
        channel: Channel,
        path: str | os.PathLike[str],
        *,
        title: str = "",
        start_ms: int = 0,
    ) -> None:
        """Stream the video file at `path` into `channel` as a screen share titled `title`
        (blank: the file name). A running stream stops first. Returns once the stream is
        live; it plays from the first viewer on, and `on_stream_ended` handlers run at its
        end. `start_ms`: where in the file to begin; a start within about 2 s of the end fails
        with `video: start at … too close to the end …`."""
        await self._connection().request(
            "stream_file",
            {
                "server": channel.server,
                "group": channel.group,
                "path": os.path.abspath(os.fspath(path)),
                "title": title,
                "start_ms": start_ms,
            },
        )

    async def stop_stream(self) -> bool:
        """Stop the running stream; returns whether one ran."""
        return await self._connection().request("stop_stream")

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Connect to `spezl serve` and dispatch events until it ends."""
        conn = await Connection.open(self._binary, self._home)
        self._conn = conn
        self._closing = False
        try:
            info = await conn.request("info")
            if info.get("protocol") != PROTOCOL:
                raise SpezlError(
                    f"spezl serve speaks protocol {info.get('protocol')}, "
                    f"this SDK {PROTOCOL}"
                )
            self._user_id = info["user_id"]
            self._name = info["name"]
            # Always, also an empty set: it withdraws the commands of an earlier run.
            await conn.request("set_commands", {"commands": list(self._commands.values())})
            # Always, so that turning voice off is announced too.
            await conn.request("set_voice", {"voice": self._voice})
            if self._audio_handlers:
                self._audio_queue = asyncio.Queue(maxsize=AUDIO_BACKLOG)
                self._spawn(self._hear())

            async for note in conn.notifications():
                try:
                    self._dispatch(note)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
            if self._audio_queue is not None:
                # The end marker always fits: it replaces the oldest frame if need be.
                if self._audio_queue.full():
                    self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(None)
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
        except BaseException:
            if not self._closing:
                await self._shutdown_quietly()
            raise
        code = conn.exit_code
        if code not in (0, None) and not self._closing:
            raise SpezlError(f"spezl serve exited with code {code}")

    def _dispatch(self, note: dict) -> None:
        method = note.get("method")
        params = note.get("params") or {}
        if method == "message":
            msg = message_from_wire(params, self)
            for handler in self._message_handlers:
                self._spawn(handler(msg))
            if msg.mentions_me:
                for handler in self._mention_handlers:
                    self._spawn(handler(msg))
        elif method == "ready":
            for handler in self._ready_handlers:
                self._spawn(handler(params["server"]))
        elif method == "invocation":
            inv = invocation_from_wire(params, self)
            handler = self._command_handlers.get(inv.command)
            if handler is not None:
                self._spawn(handler(inv))
        elif method == "press":
            press = press_from_wire(params, self)
            for handler in self._press_handlers:
                self._spawn(handler(press))
        elif method == "submit":
            submit = submit_from_wire(params, self)
            for handler in self._submit_handlers:
                self._spawn(handler(submit))
        elif method == "voice_joined":
            voice = voice_from_wire(params)
            for handler in self._voice_join_handlers:
                self._spawn(handler(voice))
        elif method == "voice_left":
            voice = voice_from_wire(params)
            for handler in self._voice_leave_handlers:
                self._spawn(handler(voice))
        elif method == "audio":
            q = self._audio_queue
            if q is not None and not q.full():
                q.put_nowait(audio_from_wire(params))
        elif method == "stream_ended":
            ended = stream_ended_from_wire(params)
            for handler in self._stream_ended_handlers:
                self._spawn(handler(ended))
        elif method == "member_joined":
            joined = member_joined_from_wire(params)
            for handler in self._member_join_handlers:
                self._spawn(handler(joined))

    async def _hear(self) -> None:
        """Hands heard frames to the audio handlers, one at a time and in order."""
        queue = self._audio_queue
        assert queue is not None
        while (audio := await queue.get()) is not None:
            for handler in self._audio_handlers:
                await self._guard(handler(audio))

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(self._guard(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _guard(coro: Awaitable[None]) -> None:
        try:
            await coro
        except Exception:
            traceback.print_exc(file=sys.stderr)

    async def _shutdown_quietly(self) -> None:
        try:
            await self.close()
        except Exception:
            pass

    async def close(self) -> None:
        """Ask `spezl serve` to shut down and wait for it."""
        conn = self._conn
        if conn is None:
            return
        self._closing = True
        try:
            await asyncio.wait_for(conn.request("shutdown"), CLOSE_TIMEOUT)
        except (SpezlError, asyncio.TimeoutError):
            pass
        await conn.close()

    def run(self) -> None:
        """Run the bot until `spezl serve` ends, Ctrl-C or SIGTERM."""
        try:
            asyncio.run(self._main())
        except KeyboardInterrupt:
            pass

    async def _main(self) -> None:
        loop = asyncio.get_running_loop()
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGTERM, lambda: self._spawn(self.close()))
        try:
            await self.start()
        finally:
            if sys.platform != "win32":
                loop.remove_signal_handler(signal.SIGTERM)
            await self.close()
