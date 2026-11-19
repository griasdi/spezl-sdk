from __future__ import annotations

import base64
import sys
from array import array
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._bot import Bot


class SpezlError(Exception):
    """An error from the SDK or from `spezl serve` (JSON-RPC error code in `code`)."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Sender:
    id: str
    name: str
    bot_id: bool
    """Whether the id carries the bot marker: a convention of honest bot software, not
    proof."""


@dataclass(frozen=True)
class Channel:
    server: str
    id: str
    name: str
    group: str


@dataclass(frozen=True)
class CommunityRef:
    id: str
    name: str


@dataclass(frozen=True)
class Community:
    server: str
    id: str
    name: str
    channels: list[Channel]


@dataclass(frozen=True)
class MemberJoined:
    community: Community
    """The community, with the text channels the bot can view."""
    member: Sender
    """The new member; `name` is their profile name, or the first 8 hex digits of their id when
    no profile arrived within 30 s."""


@dataclass(frozen=True)
class Message:
    community: CommunityRef
    channel: Channel
    seq: int
    ts_ms: int
    """The sender's own clock, unchecked: never use it to decide what a member may do."""
    sender: Sender
    text: str
    reply_to: int | None
    mentions_me: bool
    _bot: "Bot" = field(repr=False, compare=False)

    async def reply(self, text: str) -> int:
        """Send `text` into the same channel as a reply to this message; returns its seq."""
        return await self._bot.send(self.channel, text, reply_to=self.seq)


def channel_from_wire(d: dict) -> Channel:
    return Channel(server=d["server"], id=d["id"], name=d["name"], group=d["group"])


def community_from_wire(d: dict) -> Community:
    return Community(
        server=d["server"],
        id=d["id"],
        name=d["name"],
        channels=[channel_from_wire(c) for c in d["channels"]],
    )


def member_joined_from_wire(d: dict) -> MemberJoined:
    member = d["member"]
    return MemberJoined(
        community=community_from_wire(d["community"]),
        member=Sender(id=member["id"], name=member["name"], bot_id=member["bot_id"]),
    )


def message_from_wire(d: dict, bot: "Bot") -> Message:
    sender = d["sender"]
    community = d["community"]
    return Message(
        community=CommunityRef(id=community["id"], name=community["name"]),
        channel=channel_from_wire(d["channel"]),
        seq=d["seq"],
        ts_ms=d["ts_ms"],
        sender=Sender(id=sender["id"], name=sender["name"], bot_id=sender["bot_id"]),
        text=d["text"],
        reply_to=d.get("reply_to"),
        mentions_me=d["mentions_me"],
        _bot=bot,
    )


# -- bot interfaces -----------------------------------------------------------


@dataclass(frozen=True)
class TextField:
    """A one-line text of at most `max_chars` characters."""

    id: str
    label: str
    _: KW_ONLY
    placeholder: str = ""
    max_chars: int = 300
    required: bool = True

    def to_wire(self) -> dict:
        return {
            "type": "text",
            "id": self.id,
            "label": self.label,
            "required": self.required,
            "placeholder": self.placeholder,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True)
class TextListField:
    """`min` to `max` lines of at most `max_chars` characters each."""

    id: str
    label: str
    _: KW_ONLY
    placeholder: str = ""
    min: int = 1
    max: int = 10
    max_chars: int = 100
    required: bool = True

    def to_wire(self) -> dict:
        return {
            "type": "text_list",
            "id": self.id,
            "label": self.label,
            "required": self.required,
            "placeholder": self.placeholder,
            "min": self.min,
            "max": self.max,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True)
class ToggleField:
    """An on/off switch; the invocation always carries it."""

    id: str
    label: str
    _: KW_ONLY
    default: bool = False

    def to_wire(self) -> dict:
        return {"type": "toggle", "id": self.id, "label": self.label, "default": self.default}


@dataclass(frozen=True)
class ChoiceField:
    """One of `options`, `(id, label)` pairs; the invocation carries the chosen id."""

    id: str
    label: str
    options: list[tuple[str, str]]
    _: KW_ONLY
    default: str | None = None
    required: bool = True

    def to_wire(self) -> dict:
        return {
            "type": "choice",
            "id": self.id,
            "label": self.label,
            "required": self.required,
            "options": [{"id": i, "label": label} for i, label in self.options],
            "default": self.default,
        }


@dataclass(frozen=True)
class DateTimeField:
    """A date and time the member picks; the invocation carries the instant in Unix milliseconds."""

    id: str
    label: str
    _: KW_ONLY
    required: bool = True

    def to_wire(self) -> dict:
        return {"type": "date_time", "id": self.id, "label": self.label, "required": self.required}


@dataclass(frozen=True)
class ClientInfoField:
    """The member's operating system and app version, which their app fills in when the form
    opens; they may edit or clear it. The invocation carries it as a string of at most 300
    characters, written for people: its format is not fixed."""

    id: str
    label: str
    _: KW_ONLY
    required: bool = True

    def to_wire(self) -> dict:
        return {
            "type": "client_info",
            "id": self.id,
            "label": self.label,
            "required": self.required,
        }


@dataclass(frozen=True)
class SelectOption:
    """An option of a `SelectField`; with a non-empty `when` it is offered only while the field
    the select depends on (`on`) holds one of these ids."""

    id: str
    label: str
    _: KW_ONLY
    when: tuple[str, ...] | list[str] = ()

    def to_wire(self) -> dict:
        return {"id": self.id, "label": self.label, "when": list(self.when)}


@dataclass(frozen=True)
class SelectField:
    """One of `options` (`(id, label)` pairs or `SelectOption`s); the values carry the chosen
    id. `tiles`: a grid of tiles instead of a dropdown. `on`: the id of an earlier choice or
    select field whose choice filters the options by their `when`."""

    id: str
    label: str
    options: list[tuple[str, str] | SelectOption]
    _: KW_ONLY
    on: str | None = None
    tiles: bool = False
    default: str | None = None
    required: bool = True

    def to_wire(self) -> dict:
        options = [o if isinstance(o, SelectOption) else SelectOption(*o) for o in self.options]
        return {
            "type": "select",
            "id": self.id,
            "label": self.label,
            "required": self.required,
            "options": [o.to_wire() for o in options],
            "default": self.default,
            "on": self.on,
            "tiles": self.tiles,
        }


Field = (
    TextField
    | TextListField
    | ToggleField
    | ChoiceField
    | DateTimeField
    | ClientInfoField
    | SelectField
)


@dataclass(frozen=True)
class Button:
    """A button; a press reaches the bot's `on_press` handlers. `style`: "primary",
    "secondary", "danger", "success", "warning", "disabled" (shown but not pressable: neither
    the press nor a form behind it reaches the bot) or "selected" (the current choice;
    pressable)."""

    id: str
    label: str
    style: str = "secondary"

    def to_wire(self) -> dict:
        return {"id": self.id, "label": self.label, "style": self.style}


@dataclass(frozen=True)
class Buttons:
    """A row of buttons."""

    buttons: list[Button]

    def to_wire(self) -> dict:
        return {"type": "buttons", "buttons": [b.to_wire() for b in self.buttons]}


@dataclass(frozen=True)
class Poll:
    """A poll every member's client counts itself. `closes_ms`: when voting ends (Unix
    milliseconds); `creator`: the user id who may end it besides the bot."""

    question: str
    options: list[str]
    _: KW_ONLY
    multiple: bool = False
    hidden_results: bool = False
    show_voters: bool = True
    closes_ms: int | None = None
    creator: str | None = None

    def to_wire(self) -> dict:
        return {
            "type": "poll",
            "question": self.question,
            "options": list(self.options),
            "multiple": self.multiple,
            "hidden_results": self.hidden_results,
            "show_voters": self.show_voters,
            "closes_ms": self.closes_ms,
            "creator": self.creator,
        }


@dataclass(frozen=True)
class ListItem:
    """A row of an `ItemList`: a bold `title`, a muted `detail` line and buttons on the right."""

    title: str
    detail: str = ""
    buttons: tuple[Button, ...] | list[Button] = ()

    def to_wire(self) -> dict:
        return {
            "title": self.title,
            "detail": self.detail,
            "buttons": [b.to_wire() for b in self.buttons],
        }


@dataclass(frozen=True)
class ItemList:
    """Rows of a title, a detail line and buttons; a press reaches `on_press`."""

    items: list[ListItem]

    def to_wire(self) -> dict:
        return {"type": "list", "items": [i.to_wire() for i in self.items]}


@dataclass(frozen=True)
class Form:
    """A form a `FormButton` opens as a dialog: `text` above its fields and a `submit` button."""

    title: str
    fields: list[Field]
    _: KW_ONLY
    text: str = ""
    submit: str = "Submit"

    def to_wire(self) -> dict:
        return {
            "title": self.title,
            "text": self.text,
            "fields": [f.to_wire() for f in self.fields],
            "submit": self.submit,
        }


@dataclass(frozen=True)
class FormButton:
    """A button that opens `form` as a dialog; what the member fills in reaches the bot's
    `on_submit` handlers."""

    id: str
    label: str
    form: Form
    style: str = "secondary"

    def to_wire(self) -> dict:
        return {
            "type": "form",
            "button": {"id": self.id, "label": self.label, "style": self.style},
            "form": self.form.to_wire(),
        }


@dataclass(frozen=True)
class HintedButton:
    """A button of a `HintedButtons` row with `hint` shown while the pointer is over it (at most
    200 characters, no control characters, may be empty)."""

    id: str
    label: str
    hint: str = ""
    style: str = "secondary"

    def to_wire(self) -> dict:
        return {"id": self.id, "label": self.label, "style": self.style, "hint": self.hint}


@dataclass(frozen=True)
class HintedButtons:
    """A row of 1–5 buttons with hints; a press reaches `on_press`."""

    buttons: list[HintedButton]

    def to_wire(self) -> dict:
        return {"type": "hinted_buttons", "buttons": [b.to_wire() for b in self.buttons]}


@dataclass(frozen=True)
class TallyOption:
    """An option of a `Tally`: a button with `hint` shown while the pointer is over it (at most
    200 characters, no control characters, may be empty) and `members`, the user ids of the
    members who chose it (at most 100, each in at most one option of the row)."""

    id: str
    label: str
    hint: str = ""
    style: str = "secondary"
    members: tuple[str, ...] | list[str] = ()

    def to_wire(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "style": self.style,
            "hint": self.hint,
            "members": list(self.members),
        }


@dataclass(frozen=True)
class Tally:
    """A row of 2–5 options in equal widths; members see how many chose each and their own
    option marked. A press reaches `on_press`; the bot then replaces the card with the new
    members."""

    options: list[TallyOption]

    def to_wire(self) -> dict:
        return {"type": "tally", "options": [o.to_wire() for o in self.options]}


@dataclass(frozen=True)
class Columns:
    """2–3 columns of markdown side by side, each at most 1000 characters, at least one not
    blank; below each other where the card is too narrow."""

    columns: list[str]

    def to_wire(self) -> dict:
        return {"type": "columns", "columns": list(self.columns)}


@dataclass(frozen=True)
class LinkButton:
    """A button of a `Links` row that opens `url`, an http or https address, in the browser;
    a press sends nothing to the bot."""

    label: str
    url: str
    style: str = "secondary"

    def to_wire(self) -> dict:
        return {"label": self.label, "url": self.url, "style": self.style}


@dataclass(frozen=True)
class Links:
    """A row of 1–5 `LinkButton`s."""

    links: list[LinkButton]

    def to_wire(self) -> dict:
        return {"type": "links", "links": [link.to_wire() for link in self.links]}


@dataclass(frozen=True)
class CardImage:
    """A picture `Bot.upload_image` stored on the server, for an `Image` block. It belongs to
    one card: deleting that card, or replacing it with one that no longer shows the picture,
    deletes it on the server, so another card uploads its own copy. `key` opens the picture:
    keep it out of logs."""

    blob: str
    key: str = field(repr=False)
    nonce: str = field(repr=False)
    mime: str
    width: int
    height: int

    @classmethod
    def from_wire(cls, d: dict) -> CardImage:
        return cls(
            blob=d["blob"],
            key=d["key"],
            nonce=d["nonce"],
            mime=d["mime"],
            width=d["width"],
            height=d["height"],
        )


@dataclass(frozen=True)
class Image:
    """A picture at the card's width; `alt` shows while it loads or when it cannot be shown.
    A card holds at most two."""

    image: CardImage
    alt: str = ""

    def to_wire(self) -> dict:
        i = self.image
        return {
            "type": "image",
            "blob": i.blob,
            "key": i.key,
            "nonce": i.nonce,
            "mime": i.mime,
            "width": i.width,
            "height": i.height,
            "alt": self.alt,
        }


Block = Buttons | Poll | ItemList | FormButton | Columns | HintedButtons | Image | Links | Tally


@dataclass(frozen=True)
class Card:
    """What a bot posts: markdown `body` above `blocks` (`Buttons`, `HintedButtons`, `ItemList`s,
    `FormButton`s, `Columns`, `Links`, `Tally`s, at most two `Image`s and at most one `Poll`)."""

    body: str = ""
    blocks: tuple[Block, ...] | list[Block] = ()

    def to_wire(self) -> dict:
        return {"body": self.body, "blocks": [b.to_wire() for b in self.blocks]}


@dataclass(frozen=True)
class Invocation:
    """A member ran one of the bot's commands. `values` maps field ids to a string (text,
    choice, select, client info), a list of strings (text list), a bool (toggle) or an int (date
    and time, Unix milliseconds); every toggle is there."""

    community: CommunityRef
    channel: Channel
    seq: int
    ts_ms: int
    """The sender's own clock, unchecked: never use it to decide what a member may do."""
    sender: Sender
    command: str
    values: dict
    _bot: "Bot" = field(repr=False, compare=False)

    async def respond(self, card: Card, *, private: bool = False) -> int:
        """Answer with `card` in the invocation's channel; returns its seq. `private`: only the
        invoking member sees it."""
        return await self._bot.post_card(
            self.channel, card, answers=self.seq, to=self.sender.id if private else None
        )


@dataclass(frozen=True)
class Press:
    """A member pressed button `button` on the bot's card `card`."""

    community: CommunityRef
    channel: Channel
    seq: int
    ts_ms: int
    """The sender's own clock, unchecked: never use it to decide what a member may do."""
    sender: Sender
    card: int
    button: str
    _bot: "Bot" = field(repr=False, compare=False)

    async def reply(self, text: str, *, private: bool = False) -> int:
        """Send `text` into the card's channel as a reply to the card; returns its seq.
        `private`: only the presser sees it, as a card."""
        if private:
            return await self._bot.post_card(self.channel, Card(text), to=self.sender.id)
        return await self._bot.send(self.channel, text, reply_to=self.card)

    async def reveal(self, target: int) -> None:
        """Scroll the presser's chat to the bot's card `target` in this channel (see
        `Bot.reveal`)."""
        await self._bot.reveal(self.channel, self.seq, target)


@dataclass(frozen=True)
class Submit:
    """A member filled in the form behind button `button` of the bot's card `card`. `values`
    like an `Invocation`'s; every toggle is there."""

    community: CommunityRef
    channel: Channel
    seq: int
    ts_ms: int
    """The sender's own clock, unchecked: never use it to decide what a member may do."""
    sender: Sender
    card: int
    button: str
    values: dict
    _bot: "Bot" = field(repr=False, compare=False)

    async def reply(self, text: str, *, private: bool = False) -> int:
        """Send `text` into the card's channel as a reply to the card; returns its seq.
        `private`: only the member who sent the form sees it, as a card."""
        if private:
            return await self._bot.post_card(self.channel, Card(text), to=self.sender.id)
        return await self._bot.send(self.channel, text, reply_to=self.card)

    async def reveal(self, target: int) -> None:
        """Scroll the chat of the member who sent the form to the bot's card `target` in this
        channel (see `Bot.reveal`)."""
        await self._bot.reveal(self.channel, self.seq, target)


def _context(d: dict) -> dict:
    sender = d["sender"]
    community = d["community"]
    return {
        "community": CommunityRef(id=community["id"], name=community["name"]),
        "channel": channel_from_wire(d["channel"]),
        "seq": d["seq"],
        "ts_ms": d["ts_ms"],
        "sender": Sender(id=sender["id"], name=sender["name"], bot_id=sender["bot_id"]),
    }


def invocation_from_wire(d: dict, bot: "Bot") -> Invocation:
    return Invocation(**_context(d), command=d["command"], values=d["values"], _bot=bot)


def press_from_wire(d: dict, bot: "Bot") -> Press:
    return Press(**_context(d), card=d["card"], button=d["button"], _bot=bot)


def submit_from_wire(d: dict, bot: "Bot") -> Submit:
    return Submit(
        **_context(d), card=d["card"], button=d["button"], values=d["values"], _bot=bot
    )


SAMPLE_RATE = 48_000
"""Sample rate of `Audio` and of `Bot.play`: 48 kHz mono, griasdi's voice rate."""

AUDIO_FRAME = 960
"""Samples per `Audio` frame: 20 ms."""


@dataclass(frozen=True)
class Voice:
    """A voice channel the bot joined or left. `by`: who invited it (`on_voice_join`) or sent
    it home (`on_voice_leave`); `None` when it left on its own: nobody but bots was left, or
    the server ended the session."""

    community: CommunityRef
    channel: Channel
    by: Sender | None


@dataclass(frozen=True)
class Audio:
    """20 ms of what the bot hears: every other participant mixed. `samples`: `AUDIO_FRAME`
    16-bit samples (`array('h')`), 48 kHz mono."""

    samples: array


def voice_from_wire(d: dict) -> Voice:
    community = d["community"]
    by = d.get("by")
    return Voice(
        community=CommunityRef(id=community["id"], name=community["name"]),
        channel=channel_from_wire(d["channel"]),
        by=None
        if by is None
        else Sender(id=by["id"], name=by["name"], bot_id=by["bot_id"]),
    )


def audio_from_wire(d: dict) -> Audio:
    samples = array("h")
    samples.frombytes(base64.b64decode(d["samples"]))
    if sys.byteorder == "big":
        samples.byteswap()
    return Audio(samples=samples)


def samples_to_wire(samples: array) -> str:
    """`samples` as base64 of their little-endian bytes."""
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    return base64.b64encode(samples.tobytes()).decode("ascii")


@dataclass(frozen=True)
class StreamEnded:
    """A stream of the bot ended. `reason`: "finished", "stopped", "failed" (then `error`
    says why) or "lost" (the server ended the share). `path`: the file's absolute path (the
    SDK resolves a relative `stream_file` path against the working directory);
    `position_ms`: how far it played (the start when nobody watched)."""

    channel: Channel
    path: str
    title: str
    reason: str
    error: str | None
    position_ms: int


def stream_ended_from_wire(d: dict) -> StreamEnded:
    return StreamEnded(
        channel=channel_from_wire(d["channel"]),
        path=d["path"],
        title=d["title"],
        reason=d["reason"],
        error=d.get("error"),
        position_ms=d["position_ms"],
    )
