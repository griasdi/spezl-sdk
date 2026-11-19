"""A raid sign-up bot for World of Warcraft: Forever.

A member posts a raid with /raid: they pick one of the raids of the current phase from a list,
the start with the date picker and optionally a time after which nobody can sign up. The raid
card shows a picture of the roster, one column per role with every character's class icon in
the class color (the icons are from game-icons.net, credited in `icons/LICENSE.md`), and the
same roster as text below it. Below that sits a tally row: "Join" opens the member's own
sign-up card, which lists their saved characters with a Sign up button each (and Sign off on
the signed-up one), a status row (Late, Maybe, Bench, Absent) and "➕ New character": a dialog
with class tiles where the spec and race choices follow the class. Join scrolls the member's
chat down to that card, and signing up there scrolls it back up to the raid card. Late, Maybe,
Bench and Absent work right on the raid card too, a tally row that counts each status, marks
the member's own and names who chose it on hover, and pressing the status one holds again
undoes it.
Characters (name, class, spec, race) are also saved with /char and are reused for every raid.
The leader gets a leader panel only they see right after /raid, and again with
/raids → 👑 Manage: announce the roster (which pings the picked members), lock and unlock
sign-ups, cancel the raid after a confirmation, change the sign-up deadline and pick Raid or
Bench for every sign-up. /raids also posts a raid's card again or cancels the raid, and /export
gives the leader the sign-ups as CSV. Signed-up members (once there is a roster: the picked
ones) get a reminder shortly before the start.
Answers to a member's command or button only that member sees; the raid card, announcements
and reminders are public.

Everything is stored in SQLite next to the bot home (`$SPEZL_HOME/raidhelper.sqlite3`, or
`$RAIDHELPER_DB`). A member keeps one character per class: saving another of the same class
replaces it. Times are shown in `$RAIDHELPER_TZ` (an IANA zone such as Europe/Vienna), or the
host's local time zone.

Run it with `spezl run examples/raid/raid.py`.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import roster_image
import spezl
from wow_forever import (
    CLASSES,
    CURRENT_PHASE,
    FACTION_ICONS,
    RACES,
    RAIDS,
    RAID_OVERVIEW_URL,
    ROLES,
    Race,
    Spec,
    WowClass,
)

DB_PATH = Path(
    os.environ.get("RAIDHELPER_DB")
    or Path(os.environ.get("SPEZL_HOME") or ".") / "raidhelper.sqlite3"
)
# None: the host's zone, with the offset of each shown instant (daylight saving included).
TZ = ZoneInfo(os.environ["RAIDHELPER_TZ"]) if os.environ.get("RAIDHELPER_TZ") else None
REMIND_BEFORE_MS = 15 * 60_000
REMIND_EVERY_S = 30
# griasdi's limit for a card body, in characters.
MAX_BODY = 4000
# griasdi's limit for a column of a Columns block, in characters.
MAX_COLUMN = 1000
# griasdi's limit for the members of one tally option.
MAX_TALLY_MEMBERS = 100
# griasdi's limit for the items of one List block.
MAX_LIST_ITEMS = 10
# 3000-01-01 UTC: later dates break datetime.
MAX_START_MS = 32_503_680_000_000

SIGNED, LATE, TENTATIVE, BENCH, ABSENT = "signed", "late", "tentative", "bench", "absent"
# The statuses that take a slot in the raid.
COUNTED = (SIGNED, LATE)
OPEN, LOCKED, CANCELLED = "open", "locked", "cancelled"
# The leader's roster decision of a sign-up; NULL while undecided.
ROSTER_RAID, ROSTER_BENCH = "raid", "bench"
# List blocks on a leader panel: 8 blocks minus the leader row and the deadline form.
ROSTER_LISTS = 6
STATUS_NOTES = {LATE: " (late)", TENTATIVE: " (maybe)", BENCH: " (bench by choice)"}
STATUS_LABELS = {
    SIGNED: "signed up",
    LATE: "late",
    TENTATIVE: "maybe",
    BENCH: "bench by choice",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    user_id TEXT NOT NULL, class TEXT NOT NULL, name TEXT NOT NULL, spec TEXT, race TEXT,
    manual INTEGER NOT NULL DEFAULT 1, updated_ms INTEGER NOT NULL,
    PRIMARY KEY (user_id, class));
CREATE TABLE IF NOT EXISTS raids (
    id INTEGER PRIMARY KEY AUTOINCREMENT, server TEXT NOT NULL, grp TEXT NOT NULL,
    channel_id TEXT NOT NULL, channel_name TEXT NOT NULL, card_seq INTEGER,
    title TEXT NOT NULL, description TEXT NOT NULL, start_ms INTEGER NOT NULL,
    size INTEGER NOT NULL, leader_id TEXT NOT NULL, leader_name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open', reminded INTEGER NOT NULL DEFAULT 0, instance TEXT,
    deadline_ms INTEGER);
CREATE TABLE IF NOT EXISTS signups (
    raid_id INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE, user_id TEXT NOT NULL,
    user_name TEXT NOT NULL, char_name TEXT NOT NULL, class TEXT, spec TEXT,
    status TEXT NOT NULL, signed_ms INTEGER NOT NULL, roster TEXT,
    PRIMARY KEY (raid_id, user_id));
CREATE TABLE IF NOT EXISTS char_pickers (
    server TEXT NOT NULL, grp TEXT NOT NULL, card_seq INTEGER NOT NULL,
    user_id TEXT NOT NULL, raid_id INTEGER NOT NULL, PRIMARY KEY (server, grp, card_seq));
CREATE TABLE IF NOT EXISTS roster_cards (
    server TEXT NOT NULL, grp TEXT NOT NULL, card_seq INTEGER NOT NULL,
    raid_id INTEGER NOT NULL, PRIMARY KEY (server, grp, card_seq));
"""

COUNTED_SQL = "status IN ('signed', 'late') AND class IS NOT NULL"


class Store:
    """The bot's data. The bot runs on one asyncio thread, so blocking calls are fine here."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        with self.conn:
            self.conn.executescript(SCHEMA)
            # Raids from before the raid list have no instance.
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(raids)")}
            if "instance" not in columns:
                self.conn.execute("ALTER TABLE raids ADD COLUMN instance TEXT")
            if "deadline_ms" not in columns:
                self.conn.execute("ALTER TABLE raids ADD COLUMN deadline_ms INTEGER")
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(signups)")}
            if "roster" not in columns:
                self.conn.execute("ALTER TABLE signups ADD COLUMN roster TEXT")
            # Characters a class button saved before only /char counted as saved: no race,
            # named after the member as in one of their sign-ups of that class.
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(characters)")}
            if "manual" not in columns:
                self.conn.execute(
                    "ALTER TABLE characters ADD COLUMN manual INTEGER NOT NULL DEFAULT 1"
                )
                self.conn.execute(
                    "UPDATE characters SET manual = 0 WHERE race IS NULL AND EXISTS (SELECT 1 "
                    "FROM signups s WHERE s.user_id = characters.user_id "
                    "AND s.class = characters.class AND s.user_name = characters.name)"
                )

    def _one(self, sql: str, *args) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def _all(self, sql: str, *args) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    # -- characters ----------------------------------------------------------

    def character(self, user: str, cls: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM characters WHERE user_id = ? AND class = ?", user, cls)

    def latest_character(self, user: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM characters WHERE user_id = ? AND spec IS NOT NULL AND manual = 1 "
            "ORDER BY updated_ms DESC LIMIT 1",
            user,
        )

    def characters(self, user: str) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM characters WHERE user_id = ? AND manual = 1 "
            "ORDER BY updated_ms DESC",
            user,
        )

    def save_character(
        self, user: str, cls: str, name: str, race: str | None, spec: str, now_ms: int
    ) -> None:
        """Saves the member's character of class `cls`."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO characters (user_id, class, name, spec, race, manual, updated_ms) "
                "VALUES (?, ?, ?, ?, ?, 1, ?) ON CONFLICT (user_id, class) DO UPDATE SET "
                "name = excluded.name, race = excluded.race, manual = 1, "
                "spec = excluded.spec, updated_ms = excluded.updated_ms",
                (user, cls, name, spec, race, now_ms),
            )

    def touch_character(self, user: str, cls: str, now_ms: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE characters SET updated_ms = ? WHERE user_id = ? AND class = ?",
                (now_ms, user, cls),
            )

    def delete_character(self, user: str, cls: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM characters WHERE user_id = ? AND class = ? AND manual = 1",
                (user, cls),
            )
        return cur.rowcount > 0

    # -- raids -----------------------------------------------------------------

    def add_raid(
        self,
        channel: spezl.Channel,
        instance: str,
        title: str,
        description: str,
        start_ms: int,
        size: int,
        leader: spezl.Sender,
        deadline_ms: int | None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO raids (server, grp, channel_id, channel_name, instance, title, "
                "description, start_ms, size, leader_id, leader_name, deadline_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    channel.server,
                    channel.group,
                    channel.id,
                    channel.name,
                    instance,
                    title,
                    description,
                    start_ms,
                    size,
                    leader.id,
                    leader.name,
                    deadline_ms,
                ),
            )
        return cur.lastrowid

    def set_card(self, raid_id: int, seq: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE raids SET card_seq = ? WHERE id = ?", (seq, raid_id))

    def delete_raid(self, raid_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM raids WHERE id = ?", (raid_id,))

    def raid(self, raid_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM raids WHERE id = ?", raid_id)

    def raid_by_card(self, server: str, grp: str, seq: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM raids WHERE server = ? AND grp = ? AND card_seq = ?", server, grp, seq
        )

    def upcoming_raids(self, server: str, grp: str, now_ms: int) -> list[sqlite3.Row]:
        """The next raids of a channel, with `counted`: how many take a slot."""
        return self._all(
            "SELECT r.*, (SELECT COUNT(*) FROM signups s WHERE s.raid_id = r.id "
            f"AND {COUNTED_SQL}) AS counted "
            "FROM raids r WHERE r.server = ? AND r.grp = ? AND r.state != 'cancelled' "
            "AND r.start_ms >= ? ORDER BY r.start_ms LIMIT 20",
            server,
            grp,
            now_ms,
        )

    def set_state(self, raid_id: int, state: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE raids SET state = ? WHERE id = ?", (state, raid_id))

    def set_deadline(self, raid_id: int, deadline_ms: int | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE raids SET deadline_ms = ? WHERE id = ?", (deadline_ms, raid_id)
            )

    def mark_reminded(self, raid_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE raids SET reminded = 1 WHERE id = ?", (raid_id,))

    def due_reminders(self, now_ms: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM raids WHERE state != 'cancelled' AND reminded = 0 "
            "AND card_seq IS NOT NULL AND start_ms - ? <= ?",
            REMIND_BEFORE_MS,
            now_ms,
        )

    def open_deadlines(self, now_ms: int) -> list[sqlite3.Row]:
        """Raids not started yet with a card and a sign-up deadline."""
        return self._all(
            "SELECT * FROM raids WHERE state != 'cancelled' AND card_seq IS NOT NULL "
            "AND deadline_ms IS NOT NULL AND start_ms > ?",
            now_ms,
        )

    # -- sign-ups --------------------------------------------------------------

    def signups(self, raid_id: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT rowid AS rid, * FROM signups WHERE raid_id = ? ORDER BY signed_ms", raid_id
        )

    def signup_by_rowid(self, raid_id: int, rid: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT rowid AS rid, * FROM signups WHERE raid_id = ? AND rowid = ?", raid_id, rid
        )

    def signup(self, raid_id: int, user: str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM signups WHERE raid_id = ? AND user_id = ?", raid_id, user)

    def upsert_signup(
        self,
        raid_id: int,
        user: str,
        user_name: str,
        char_name: str,
        cls: str | None,
        spec: str | None,
        status: str,
        signed_ms: int,
    ) -> None:
        # Switching the character or going absent drops the leader's roster decision. SQLite
        # evaluates every SET against the old row.
        with self.conn:
            self.conn.execute(
                "INSERT INTO signups (raid_id, user_id, user_name, char_name, class, spec, "
                "status, signed_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (raid_id, user_id) DO UPDATE SET user_name = excluded.user_name, "
                "char_name = excluded.char_name, class = excluded.class, spec = excluded.spec, "
                "status = excluded.status, signed_ms = excluded.signed_ms, "
                "roster = CASE WHEN excluded.status = 'absent' "
                "OR excluded.class IS NOT signups.class THEN NULL ELSE signups.roster END",
                (raid_id, user, user_name, char_name, cls, spec, status, signed_ms),
            )

    def set_roster(self, raid_id: int, user: str, roster: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE signups SET roster = ? WHERE raid_id = ? AND user_id = ?",
                (roster, raid_id, user),
            )

    def remove_signup(self, raid_id: int, user: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM signups WHERE raid_id = ? AND user_id = ?", (raid_id, user)
            )
        return cur.rowcount > 0

    def counted_except(self, raid_id: int, user: str) -> int:
        row = self._one(
            f"SELECT COUNT(*) FROM signups WHERE raid_id = ? AND user_id != ? AND {COUNTED_SQL}",
            raid_id,
            user,
        )
        return row[0]

    # -- character pickers -----------------------------------------------------

    def add_picker(self, server: str, grp: str, seq: int, user: str, raid_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO char_pickers (server, grp, card_seq, user_id, raid_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (server, grp, seq, user, raid_id),
            )

    def picker(self, server: str, grp: str, seq: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM char_pickers WHERE server = ? AND grp = ? AND card_seq = ?",
            server,
            grp,
            seq,
        )

    # -- roster cards ------------------------------------------------------------

    def add_roster_card(self, server: str, grp: str, seq: int, raid_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO roster_cards (server, grp, card_seq, raid_id) "
                "VALUES (?, ?, ?, ?)",
                (server, grp, seq, raid_id),
            )

    def roster_card(self, server: str, grp: str, seq: int) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM roster_cards WHERE server = ? AND grp = ? AND card_seq = ?",
            server,
            grp,
            seq,
        )

    def roster_cards_of(self, raid_id: int) -> list[int]:
        """The seqs of the raid's roster cards: one from now on, several in older databases."""
        rows = self._all(
            "SELECT card_seq FROM roster_cards WHERE raid_id = ? ORDER BY card_seq", raid_id
        )
        return [r[0] for r in rows]

    def pickers_with_users(self, raid_id: int) -> list[tuple[int, str]]:
        rows = self._all(
            "SELECT card_seq, user_id FROM char_pickers WHERE raid_id = ? ORDER BY card_seq",
            raid_id,
        )
        return [(r[0], r[1]) for r in rows]

    def picker_of(self, raid_id: int, user: str) -> int | None:
        """The seq of `user`'s newest sign-up card for the raid."""
        row = self._one(
            "SELECT card_seq FROM char_pickers WHERE raid_id = ? AND user_id = ? "
            "ORDER BY card_seq DESC LIMIT 1",
            raid_id,
            user,
        )
        return None if row is None else row[0]

    def pickers_of_user(self, raid_id: int, user: str) -> list[int]:
        rows = self._all(
            "SELECT card_seq FROM char_pickers WHERE raid_id = ? AND user_id = ? ORDER BY card_seq",
            raid_id,
            user,
        )
        return [r[0] for r in rows]

    def remove_picker(self, server: str, grp: str, seq: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM char_pickers WHERE server = ? AND grp = ? AND card_seq = ?",
                (server, grp, seq),
            )

    def remove_roster_card(self, server: str, grp: str, seq: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM roster_cards WHERE server = ? AND grp = ? AND card_seq = ?",
                (server, grp, seq),
            )


bot = spezl.Bot()
store = Store(DB_PATH)
# One lock per raid: a sign-up and the card edit after it run in order.
locks: dict[int, asyncio.Lock] = {}
reminder_task: asyncio.Task | None = None
# Per raid, the task that re-renders its cards when the sign-up deadline passes.
closers: dict[int, asyncio.Task] = {}


# -- rendering -------------------------------------------------------------------


def local(ms: int) -> datetime:
    """The instant `ms` in `TZ`, with that date's own offset."""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(TZ)


def fmt(ms: int) -> str:
    return local(ms).strftime("%a %Y-%m-%d %H:%M %Z")


def now_ms() -> int:
    return int(time.time() * 1000)


def fit(body: str) -> str:
    """`body`, cut to griasdi's limit for a card body."""
    return body if len(body) <= MAX_BODY else body[: MAX_BODY - 2] + "\n…"


def item_lists(items: list) -> list[spezl.ItemList]:
    """`items` as List blocks of at most `MAX_LIST_ITEMS` items."""
    return [
        spezl.ItemList(items[i : i + MAX_LIST_ITEMS]) for i in range(0, len(items), MAX_LIST_ITEMS)
    ]


def spec_of(cls: str | None, spec: str | None) -> tuple[WowClass, Spec] | None:
    wow_class = CLASSES.get(cls or "")
    found = wow_class.spec(spec) if wow_class else None
    return (wow_class, found) if wow_class and found else None


def is_counted(s: sqlite3.Row) -> bool:
    return s["status"] in COUNTED and s["class"] is not None


def phase_of(raid: sqlite3.Row) -> str:
    """` · P<phase>` of the raid's instance; empty for a raid from before the raid list."""
    return f" · P{RAIDS[raid['instance']].phase}" if raid["instance"] in RAIDS else ""


def deadline_problem(deadline_ms: int | None, start_ms: int, now_ms: int) -> str | None:
    """Why `deadline_ms` cannot be a raid's sign-up deadline; None when it can."""
    if deadline_ms is None:
        return None
    if deadline_ms >= MAX_START_MS:
        return "The deadline is too far ahead: pick one before the year 3000."
    if deadline_ms <= now_ms:
        return f"The deadline {fmt(deadline_ms)} is in the past."
    if deadline_ms > start_ms:
        return f"The deadline {fmt(deadline_ms)} is after the start {fmt(start_ms)}."
    return None


def closed_reason(raid: sqlite3.Row, now_ms: int) -> str | None:
    """Why nobody can sign up for `raid` at `now_ms`; None while sign-ups are open."""
    if raid["state"] == LOCKED:
        return f"sign-ups for **{raid['title']}** are locked."
    if raid["deadline_ms"] is not None and now_ms >= raid["deadline_ms"]:
        return f"sign-ups for **{raid['title']}** closed at {fmt(raid['deadline_ms'])}."
    return None


def rosterable(s: sqlite3.Row) -> bool:
    """Whether the leader can put sign-up `s` on the roster: present, with a known spec."""
    return s["status"] != ABSENT and spec_of(s["class"], s["spec"]) is not None


def roster_mode(signups: list[sqlite3.Row]) -> bool:
    """Whether the leader started the roster: then it, not the sign-ups, fills the raid."""
    return any(s["roster"] is not None for s in signups)


def progress(n: int, size: int) -> str:
    filled = min(10, -(-n * 10 // size))
    return "🟩" * filled + "⬜" * (10 - filled)


def by_role(
    rows: list[sqlite3.Row],
) -> list[tuple[str, str, list[tuple[sqlite3.Row, WowClass, Spec]]]]:
    """`(role id, label, members)` for every role in `ROLES` order; a member is a row of `rows`
    with its class and spec. Rows without a known spec are left out."""
    groups = []
    for role, label in ROLES:
        members = []
        for s in rows:
            found = spec_of(s["class"], s["spec"])
            if found is not None and found[1].role == role:
                members.append((s, *found))
        groups.append((role, label, members))
    return groups


def role_groups(rows: list[sqlite3.Row]) -> list[str]:
    """One group per role listing `rows` with that role."""
    # One group per role: the desktop turns a single newline into a hard break, so a header
    # right after a list item would be read as part of that item and indented under it.
    groups = []
    for _, label, members in by_role(rows):
        lines = [
            f"- {cls.icon} **{s['char_name']}** · {spec.name} {cls.name}"
            f"{STATUS_NOTES.get(s['status'], '')}"
            for s, cls, spec in members
        ]
        groups.append("\n".join([f"**{label} ({len(lines)})**", *(lines or ["- *nobody yet*"])]))
    return groups


def fit_column(text: str) -> str:
    """`text` cut to griasdi's limit for a column: trailing lines give way to a "… and k more"
    line."""
    if len(text) <= MAX_COLUMN:
        return text
    lines = text.split("\n")
    for keep in range(len(lines) - 1, 0, -1):
        cut = "\n".join([*lines[:keep], f"- *… and {len(lines) - keep} more*"])
        if len(cut) <= MAX_COLUMN:
            return cut
    return text[: MAX_COLUMN - 1] + "…"


def role_columns(rows: list[sqlite3.Row]) -> list[spezl.Columns]:
    """`rows` by role as text: tanks beside healers, melee beside ranged."""
    tanks, healers, melee, ranged = (fit_column(g) for g in role_groups(rows))
    return [spezl.Columns([tanks, healers]), spezl.Columns([melee, ranged])]


def lineup(signups: list[sqlite3.Row]) -> tuple[str, list[sqlite3.Row]]:
    """What fills the raid: the roster once the leader started it, else the counted sign-ups,
    with the word the progress line uses for it."""
    if roster_mode(signups):
        return "Roster", [s for s in signups if s["roster"] == ROSTER_RAID]
    return "Signed up", [s for s in signups if is_counted(s)]


def raid_picture(raid: sqlite3.Row, signups: list[sqlite3.Row]) -> bytes:
    """The roster picture of the raid card, PNG."""
    status, rows = lineup(signups)
    roles = []
    for role, _, members in by_role(rows):
        counts = Counter(cls.id for _, cls, _ in members)
        roles.append((role, [(cid, counts[cid]) for cid in CLASSES if counts[cid]]))
    return roster_image.render(
        raid["title"],
        f"{fmt(raid['start_ms'])} · {raid['size']} players{phase_of(raid)}"
        f" · Leader {raid['leader_name']}",
        status,
        len(rows),
        raid["size"],
        roles,
    )


def roster_others(signups: list[sqlite3.Row], absent: bool) -> list[str]:
    """The lines of the benched and not yet picked sign-ups, and with `absent` the absent
    ones; each only when non-empty."""
    rows = (
        ("🪑 Bench", [s for s in signups if s["roster"] == ROSTER_BENCH]),
        ("⏳ Not picked yet", [s for s in signups if s["roster"] is None and rosterable(s)]),
        ("🚫 Absent", [s for s in signups if s["status"] == ABSENT] if absent else []),
    )
    return [f"**{label}:** {', '.join(s['char_name'] for s in r)}" for label, r in rows if r]


def deadline_line(raid: sqlite3.Row) -> str | None:
    if raid["deadline_ms"] is None:
        return None
    return f"⏳ Sign-ups until **{fmt(raid['deadline_ms'])}**"


def render_raid_body(raid: sqlite3.Row) -> str:
    """The raid card's text above the picture; the roster itself is in the picture and the
    columns."""
    meta = (
        f"🕗 **{fmt(raid['start_ms'])}** · 👥 {raid['size']} players{phase_of(raid)} · "
        f"👑 {raid['leader_name']} · Raid #{raid['id']}"
    )
    if raid["state"] == CANCELLED:
        return fit(f"## ❌ {raid['title']}: cancelled\n\n{meta}")
    signups = store.signups(raid["id"])
    counted = [s for s in signups if is_counted(s)]
    groups = [f"## 🐉 {raid['title']}", meta]
    if raid["description"]:
        groups.append(f"> {raid['description']}")
    if (line := deadline_line(raid)) is not None:
        groups.append(line)
    if raid["state"] == LOCKED:
        groups.append("🔒 **Sign-ups are locked.**")
    status, rows = lineup(signups)
    line = f"**{status}: {len(rows)}/{raid['size']}** {progress(len(rows), raid['size'])}"
    if roster_mode(signups):
        groups.append(f"{line} · Signed up: {len(counted)}")
        others = roster_others(signups, absent=True)
    else:
        groups.append(line)
        others = []
        for status, label in (
            (TENTATIVE, "❔ Maybe"),
            (BENCH, "🪑 Bench"),
            (ABSENT, "🚫 Absent"),
        ):
            names = [s["char_name"] for s in signups if s["status"] == status]
            if names:
                others.append(f"**{label}:** {', '.join(names)}")
    if others:
        groups.append("\n".join(others))
    return fit("\n\n".join(groups))


def render_raid_card(raid: sqlite3.Row, image: spezl.Image | None) -> spezl.Card:
    """The raid card: `image` (the roster picture; None when it could not be uploaded), the
    roster as columns, the status tally (the viewer's own status marked, counts, names on hover)
    and the raid overview link. "Join" opens the member's sign-up card; the leader's
    controls are on the leader panel only they see."""
    if raid["state"] == CANCELLED:
        # Without the picture: replacing the card with this one deletes it on the server.
        return spezl.Card(render_raid_body(raid))
    closed = closed_reason(raid, now_ms()) is not None
    signups = store.signups(raid["id"])

    def option(
        id: str, status: str, label: str, hint: str, style: str = "secondary"
    ) -> spezl.TallyOption:
        # Members past griasdi's limit drop out of the row; the roster text still lists them.
        members = [s["user_id"] for s in signups if s["status"] == status][:MAX_TALLY_MEMBERS]
        # Presses would be refused anyway while sign-ups are closed.
        return spezl.TallyOption(id, label, hint, "disabled" if closed else style, members)

    blocks: list = [image] if image is not None else []
    blocks += role_columns(lineup(signups)[1])
    blocks += [
        # Short labels without emoji: a segment is a fifth of the card, and its check mark
        # beside an emoji or a label as long as "Sign up" wraps the label to two lines.
        spezl.Tally(
            [
                option(
                    "mine",
                    SIGNED,
                    "Join",
                    "Pick your character and your status on a card only you see",
                    "success",
                ),
                option(LATE, LATE, "Late", "Arriving after the start; press again to undo"),
                option(TENTATIVE, TENTATIVE, "Maybe", "You take no slot yet; press again to undo"),
                option(BENCH, BENCH, "Bench", "Come along as a stand-in; press again to undo"),
                option(
                    ABSENT, ABSENT, "Absent", "Tell the leader you cannot come; press again to undo"
                ),
            ]
        ),
        spezl.Links([spezl.LinkButton("📖 Raid overview", RAID_OVERVIEW_URL)]),
    ]
    return spezl.Card(render_raid_body(raid), blocks)


async def raid_card(channel: spezl.Channel, raid: sqlite3.Row) -> spezl.Card:
    """The raid card with a freshly uploaded roster picture: a picture belongs to one card
    version, and griasdi deletes the previous one when the card is replaced."""
    image = None
    if raid["state"] != CANCELLED:
        try:
            uploaded = await bot.upload_image(
                channel, raid_picture(raid, store.signups(raid["id"]))
            )
            image = spezl.Image(uploaded, alt=f"{raid['title']}: the roster by role")
        except spezl.SpezlError as e:
            print(f"raid #{raid['id']} picture: {e}", file=sys.stderr)
    return render_raid_card(raid, image)


def render_roster_body(raid: sqlite3.Row) -> str:
    """The body of the leader panel."""
    signups = store.signups(raid["id"])
    raiders = [s for s in signups if s["roster"] == ROSTER_RAID]
    groups = [
        f"## 👑 Leader panel: {raid['title']}",
        f"🕗 **{fmt(raid['start_ms'])}** · 👥 {raid['size']} players · Raid #{raid['id']}",
        deadline_line(raid) or "⏳ No sign-up deadline",
    ]
    if raid["state"] == LOCKED:
        groups.append("🔒 **Sign-ups are locked.**")
    groups += [
        f"**In the raid: {len(raiders)}/{raid['size']}**",
        *role_groups(raiders),
    ]
    if others := roster_others(signups, absent=False):
        groups.append("\n".join(others))
    extra = sum(1 for s in signups if rosterable(s)) - ROSTER_LISTS * MAX_LIST_ITEMS
    if extra > 0:
        groups.append(f"*{extra} more sign-ups do not fit on this card.*")
    return fit("\n\n".join(groups))


def cancelled_card(raid: sqlite3.Row) -> spezl.Card:
    """What the leader panel and the sign-up cards of a cancelled raid turn into."""
    return spezl.Card(f"## ❌ {raid['title']}: cancelled")


def render_roster_card(raid: sqlite3.Row, confirm: bool = False) -> spezl.Card:
    """The leader panel: the leader row (announce, lock toggle, cancel; with `confirm` the
    cancel confirmation instead), the deadline form and each sign-up with Raid and Bench
    buttons."""
    if raid["state"] == CANCELLED:
        return cancelled_card(raid)
    signups = store.signups(raid["id"])
    raiders = sum(1 for s in signups if s["roster"] == ROSTER_RAID)
    rows = [s for s in signups if rosterable(s)][: ROSTER_LISTS * MAX_LIST_ITEMS]
    items = []
    for s in rows:
        wow_class, spec = spec_of(s["class"], s["spec"])
        # The member's id prefix ties a press to them: SQLite may hand a deleted sign-up's
        # rowid to someone else's new one.
        tag = f"{s['rid']}-{s['user_id'][:6]}"
        # A selected button draws its own check mark.
        if s["roster"] == ROSTER_RAID:
            raid_button = spezl.Button(f"raid-{tag}", "Raid", "selected")
        else:
            full = raiders >= raid["size"]
            raid_button = spezl.Button(f"raid-{tag}", "Raid", "disabled" if full else "primary")
        if s["roster"] == ROSTER_BENCH:
            bench_button = spezl.Button(f"bench-{tag}", "Bench", "selected")
        else:
            bench_button = spezl.Button(f"bench-{tag}", "Bench")
        items.append(
            spezl.ListItem(
                f"{wow_class.icon} {s['char_name']}",
                f"{spec.name} {wow_class.name} · {STATUS_LABELS[s['status']]} · {s['user_name']}",
                [raid_button, bench_button],
            )
        )
    if confirm:
        leader_row = [
            spezl.HintedButton(
                "confirm", "⚠️ Really cancel the raid?", "Cancels it for everyone", "danger"
            ),
            spezl.HintedButton("keep", "Keep the raid", "Back to the leader panel"),
        ]
    else:
        locked = raid["state"] == LOCKED
        leader_row = [
            # `announce` still checks for an empty roster: a stale card can race it.
            spezl.HintedButton(
                "announce",
                "📣 Announce",
                "Ping everyone in the raid in the raid card's thread",
                "primary" if raiders else "disabled",
            ),
            # Never disabled: the leader must be able to unlock.
            spezl.HintedButton(
                "lock",
                "🔒 Locked" if locked else "🔒 Lock sign-ups",
                "Sign-ups are stopped: press to open them again" if locked else "Stop sign-ups",
                "selected" if locked else "secondary",
            ),
            spezl.HintedButton(
                "cancel",
                "❌ Cancel raid",
                "Cancel the raid for everyone; asks first",
                "danger",
            ),
        ]
    blocks: list = [
        spezl.HintedButtons(leader_row),
        spezl.FormButton(
            "deadline",
            "⏳ Sign-up deadline",
            spezl.Form(
                "Sign-up deadline",
                [spezl.DateTimeField("deadline", "Sign-ups until", required=False)],
                text="Sign-ups close at this time. Leave it empty for no deadline.",
                submit="Set",
            ),
            "secondary",
        ),
    ]
    blocks.extend(item_lists(items))
    return spezl.Card(render_roster_body(raid), blocks)


def picker_status(raid: sqlite3.Row, user: str, full: bool) -> str | None:
    """The line on `user`'s sign-up for `raid` atop their sign-up card; None without
    one. `full`: the sign-up just went to the bench because the raid is full."""
    s = store.signup(raid["id"], user)
    if s is None:
        return None
    title = raid["title"]
    if s["status"] == ABSENT:
        return f"🚫 You are absent from **{title}**."
    found = spec_of(s["class"], s["spec"])
    if found is None:
        return f"✔ **{s['char_name']}** is signed up for **{title}**."
    cls, spec = found
    who = f"{cls.icon} **{s['char_name']}** · {spec.name} {cls.name}"
    if s["status"] == BENCH:
        return f"🪑 {who} is on the bench for **{title}**" + (
            ": the raid is full." if full else "."
        )
    return f"✔ {who} is signed up for **{title}**{STATUS_NOTES.get(s['status'], '')}."


def render_picker(raid: sqlite3.Row, user: str, full: bool = False) -> spezl.Card:
    """`user`'s sign-up card: their sign-up, their saved characters (Sign up on each, Sign
    off on the signed-up one), the status row, where the held status is selected and a second
    press undoes it, and "➕ New character", a dialog that saves a new one and signs it up."""
    if raid["state"] == CANCELLED:
        return cancelled_card(raid)
    chars = [
        (c, *found)
        for c in store.characters(user)
        if (found := spec_of(c["class"], c["spec"]))
    ]
    groups = [
        f"## ⚔️ {raid['title']}: your sign-up",
        picker_status(raid, user, full) or "You are not signed up yet.",
    ]
    if not chars:
        groups.append("You have no saved characters yet: ➕ New character adds one.")
    blocks: list = []
    closed = closed_reason(raid, now_ms()) is not None
    signup = store.signup(raid["id"], user)

    def button(id: str, label: str, style: str = "secondary") -> spezl.Button:
        return spezl.Button(id, label, "disabled" if closed else style)

    if chars:
        items = []
        for c, cls, spec in chars:
            race = RACES.get(c["race"] or "")
            race_part = f" · {FACTION_ICONS[race.faction]} {race.name}" if race else ""
            if signup is not None and signup["class"] == cls.id and signup["status"] != ABSENT:
                buttons = [
                    button(f"char-{cls.id}", "Signed up", "selected"),
                    button("leave", "Sign off", "danger"),
                ]
            else:
                buttons = [button(f"char-{cls.id}", "Sign up", "primary")]
            items.append(
                spezl.ListItem(
                    f"{cls.icon} {c['name']}", f"{spec.name} {cls.name}{race_part}", buttons
                )
            )
        blocks.append(spezl.ItemList(items))
    statuses = []
    for id, label, hint in (
        (LATE, "⏰ Late", "Arriving after the start"),
        (TENTATIVE, "❔ Maybe", "You take no slot yet"),
        (BENCH, "🪑 Bench", "Come along as a stand-in"),
        (ABSENT, "🚫 Absent", "Tell the leader you cannot come"),
    ):
        held = signup is not None and signup["status"] == id
        if closed:
            style = "disabled"
        else:
            style = "selected" if held else "secondary"
        statuses.append(
            spezl.HintedButton(id, label, f"{hint} · Press again to undo" if held else hint, style)
        )
    blocks.append(spezl.HintedButtons(statuses))
    blocks.append(
        spezl.FormButton(
            "new",
            "➕ New character",
            spezl.Form(
                "New character",
                CHAR_FIELDS,
                text=f"Saves the character and signs it up for {raid['title']}.",
                submit="Save & sign up",
            ),
            "disabled" if closed else "secondary",
        )
    )
    return spezl.Card(fit("\n\n".join(groups)), blocks)


def render_raids_card(
    channel: spezl.Channel,
    user: str,
    now_ms: int,
    notice: str | None = None,
    confirm: int | None = None,
) -> spezl.Card:
    """The /raids card for `user`: the channel's upcoming raids; on each raid `user` leads,
    "👑 Manage" (a fresh leader panel), "📌 Post again" (a fresh raid card, for one that was
    deleted: the bot cannot see that) and "❌ Cancel", which `confirm` (a raid id) turns into
    "Really cancel?" and "Keep". `notice` tops the card after a press."""
    rows = store.upcoming_raids(channel.server, channel.group, now_ms)
    groups = [notice] if notice else []
    if not rows:
        groups.append("No upcoming raids in this channel.")
        return spezl.Card(fit("\n\n".join(groups)))
    groups.append("**Upcoming raids**")
    items = []
    for r in rows:
        locked = " · 🔒 locked" if r["state"] == LOCKED else ""
        rid = r["id"]
        if r["leader_id"] != user:
            buttons = []
        elif rid == confirm:
            buttons = [
                spezl.Button(f"confirm-{rid}", "Really cancel?", "danger"),
                spezl.Button(f"keep-{rid}", "Keep"),
            ]
        else:
            buttons = [
                spezl.Button(f"manage-{rid}", "👑 Manage"),
                spezl.Button(f"post-{rid}", "📌 Post again"),
                spezl.Button(f"cancel-{rid}", "❌ Cancel", "danger"),
            ]
        items.append(
            spezl.ListItem(
                f"#{rid} {r['title']}{phase_of(r)}",
                f"🕗 {fmt(r['start_ms'])} · {r['counted']}/{r['size']} signed up{locked}"
                f" · 👑 {r['leader_name']}",
                buttons,
            )
        )
    # upcoming_raids returns at most 20 rows.
    blocks = item_lists(items)
    return spezl.Card(fit("\n\n".join(groups)), blocks)


async def say(inv: spezl.Invocation, body: str) -> None:
    await inv.respond(spezl.Card(fit(body)), private=True)


# -- commands --------------------------------------------------------------------

CLASS_OPTIONS = [(c.id, c.name) for c in CLASSES.values()]
RAID_OPTIONS = [
    (r.id, f"{r.name} ({r.size}) · P{r.phase}") for r in RAIDS.values() if r.phase <= CURRENT_PHASE
]
CHAR_FIELDS = [
    spezl.TextField("name", "Character name", placeholder="Thrall", max_chars=24),
    spezl.SelectField(
        "class", "Class", [(c.id, f"{c.icon} {c.name}") for c in CLASSES.values()], tiles=True
    ),
    spezl.SelectField(
        "spec",
        "Spec",
        [
            spezl.SelectOption(f"{c.id}-{s.id}", s.name, when=[c.id])
            for c in CLASSES.values()
            for s in c.specs
        ],
        on="class",
        tiles=True,
    ),
    spezl.SelectField(
        "race",
        "Race",
        [
            spezl.SelectOption(r.id, f"{FACTION_ICONS[r.faction]} {r.name}", when=list(r.classes))
            for r in RACES.values()
        ],
        on="class",
        required=False,
    ),
]


def char_from_values(values: dict) -> tuple[WowClass, Spec, str, Race | None] | None:
    """The class, spec, name and race of `CHAR_FIELDS` values; `None` when they do not fit
    together in WoW Forever."""
    wow_class = CLASSES.get(values.get("class") or "")
    if wow_class is None:
        return None
    spec_id = values.get("spec") or ""
    if not spec_id.startswith(f"{wow_class.id}-"):
        return None
    spec = wow_class.spec(spec_id.removeprefix(f"{wow_class.id}-"))
    name = (values.get("name") or "").strip()
    if spec is None or not name:
        return None
    race = None
    if values.get("race"):
        race = RACES.get(values["race"])
        if race is None or wow_class.id not in race.classes:
            return None
    return wow_class, spec, name, race


@bot.command(
    "raid",
    "Create a raid sign-up",
    fields=[
        spezl.ChoiceField("raid", "Raid", RAID_OPTIONS),
        spezl.DateTimeField("start", "Start"),
        spezl.DateTimeField("deadline", "Sign-ups until", required=False),
        spezl.TextField(
            "description",
            "Description",
            placeholder="Bring fire resistance",
            max_chars=1000,
            required=False,
        ),
    ],
)
async def raid_command(inv: spezl.Invocation) -> None:
    v = inv.values
    instance = RAIDS[v["raid"]]
    start_ms = v["start"]
    # The bot's own clock: a sender's timestamp is whatever their machine claims.
    now = now_ms()
    if start_ms <= now:
        await say(inv, f"The start {fmt(start_ms)} is in the past.")
        return
    if start_ms >= MAX_START_MS:
        await say(inv, "The start is too far ahead: pick one before the year 3000.")
        return
    problem = deadline_problem(v.get("deadline"), start_ms, now)
    if problem:
        await say(inv, problem)
        return
    raid_id = store.add_raid(
        inv.channel,
        instance.id,
        instance.name,
        (v.get("description") or "").strip(),
        start_ms,
        instance.size,
        inv.sender,
        v.get("deadline"),
    )
    try:
        seq = await inv.respond(await raid_card(inv.channel, store.raid(raid_id)))
    except BaseException:
        # Any failure, a cancellation too, leaves no raid without its card behind.
        store.delete_raid(raid_id)
        raise
    store.set_card(raid_id, seq)
    schedule_close(store.raid(raid_id))
    try:
        await show_roster(inv.channel, inv.sender.id, store.raid(raid_id))
    except spezl.SpezlError as e:
        # The raid stands; /raids → 👑 Manage posts the panel again.
        print(f"raid #{raid_id} leader panel: {e}", file=sys.stderr)


@bot.command("char", "Save a character", fields=CHAR_FIELDS)
async def char_command(inv: spezl.Invocation) -> None:
    found = char_from_values(inv.values)
    if found is None:
        await say(
            inv, "That character does not fit WoW Forever: pick its class, spec and race again."
        )
        return
    wow_class, spec, name, race = found
    store.save_character(
        inv.sender.id, wow_class.id, name, race.id if race else None, spec.id, now_ms()
    )
    race_part = f" ({FACTION_ICONS[race.faction]} {race.name})" if race else ""
    await say(
        inv, f"✔ {wow_class.icon} **{name}** · {spec.name} {wow_class.name}{race_part} saved."
    )


@bot.command("chars", "List your saved characters")
async def chars_command(inv: spezl.Invocation) -> None:
    rows = store.characters(inv.sender.id)
    if not rows:
        await say(inv, "No characters yet: save one with /char.")
        return
    lines = ["**Your characters**"]
    for c in rows:
        wow_class = CLASSES[c["class"]]
        spec = wow_class.spec(c["spec"])
        race = RACES.get(c["race"] or "")
        race_part = f" ({FACTION_ICONS[race.faction]} {race.name})" if race else ""
        spec_name = spec.name if spec else "no spec"
        lines.append(
            f"- {wow_class.icon} **{c['name']}** · {spec_name} {wow_class.name}{race_part}"
        )
    await say(inv, "\n".join(lines))


@bot.command(
    "char-delete",
    "Delete a saved character",
    fields=[spezl.ChoiceField("class", "Class", CLASS_OPTIONS)],
)
async def char_delete_command(inv: spezl.Invocation) -> None:
    wow_class = CLASSES[inv.values["class"]]
    old = store.character(inv.sender.id, wow_class.id)
    if old is not None and store.delete_character(inv.sender.id, wow_class.id):
        await say(inv, f"Deleted {old['name']} ({wow_class.name}).")
    else:
        await say(inv, f"You have no {wow_class.name} saved.")


@bot.command("raids", "List upcoming raids; manage one, post it again or cancel it")
async def raids_command(inv: spezl.Invocation) -> None:
    await inv.respond(render_raids_card(inv.channel, inv.sender.id, now_ms()), private=True)


@bot.command(
    "export",
    "Export a raid's sign-ups as CSV",
    fields=[spezl.TextField("raid", "Raid number", placeholder="1", max_chars=10)],
)
async def export_command(inv: spezl.Invocation) -> None:
    value = inv.values["raid"].strip()
    try:
        raid = store.raid(int(value.lstrip("#")))
    except ValueError:
        raid = None
    # A raid of another channel is not shown here, not even its existence.
    if (
        raid is None
        or raid["server"] != inv.channel.server
        or raid["grp"] != inv.channel.group
    ):
        await say(inv, f"No raid #{value}.")
        return
    if inv.sender.id != raid["leader_id"]:
        await say(
            inv, f"Only {raid['leader_name']}, who created raid #{raid['id']}, can export it."
        )
        return
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["name", "class", "spec", "role", "status", "roster", "member", "signed_at"])
    for s in store.signups(raid["id"]):
        wow_class = CLASSES.get(s["class"] or "")
        spec = wow_class.spec(s["spec"]) if wow_class else None
        signed_at = local(s["signed_ms"]).isoformat(timespec="seconds")
        writer.writerow(
            [
                s["char_name"],
                wow_class.name if wow_class else "",
                spec.name if spec else "",
                spec.role if spec else "",
                s["status"],
                s["roster"] or "",
                s["user_name"],
                signed_at,
            ]
        )
    # Cards of at most MAX_BODY characters; every one starts with the header row.
    rows = out.getvalue().splitlines(keepends=True)
    room = MAX_BODY - len("```csv\n```")
    chunk = rows[0]
    for row in rows[1:]:
        if len(chunk) + len(row) > room:
            await say(inv, f"```csv\n{chunk}```")
            chunk = rows[0]
        chunk += row
    await say(inv, f"```csv\n{chunk}```")


# -- presses ---------------------------------------------------------------------


def lock_of(raid_id: int) -> asyncio.Lock:
    return locks.setdefault(raid_id, asyncio.Lock())


def signup_with(
    raid: sqlite3.Row,
    sender: spezl.Sender,
    cls: str,
    char_name: str,
    spec: str | None,
    status: str,
    now_ms: int,
) -> bool:
    """Signs `sender` up with a character; True if it went to the bench because the raid is
    full."""
    full = store.counted_except(raid["id"], sender.id) >= raid["size"]
    benched = status in COUNTED and full
    if benched:
        status = BENCH
    old = store.signup(raid["id"], sender.id)
    # Changing the character but not the status keeps the place in the queue.
    signed_ms = old["signed_ms"] if old is not None and old["status"] == status else now_ms
    store.upsert_signup(raid["id"], sender.id, sender.name, char_name, cls, spec, status, signed_ms)
    store.touch_character(sender.id, cls, now_ms)
    return benched


STATUS_BUTTONS = (LATE, TENTATIVE, BENCH, ABSENT, "leave")


async def status_press(press: spezl.Press, raid: sqlite3.Row, now: int) -> None:
    """A status button of the raid card or of the sender's sign-up card: `late`, `tentative`,
    `bench` or `absent` (pressing the status the sender holds undoes it), or `leave`. The
    caller holds the raid's lock."""
    sender = press.sender
    reason = closed_reason(raid, now)
    if reason:
        await press.reply(f"@{sender.name} {reason}", private=True)
        return
    old = store.signup(raid["id"], sender.id)
    button = press.button
    undo = old is not None and old["status"] == button
    if button in (LATE, TENTATIVE, BENCH) or (button == ABSENT and undo):
        status = SIGNED if undo else button
        picked = signed_character(sender.id, old)
        if picked is None:
            if button != ABSENT:
                await press.reply(
                    f"@{sender.name} sign up with a character first: Join.", private=True
                )
                return
            # Absent without a character: undoing it leaves no sign-up.
            store.remove_signup(raid["id"], sender.id)
        else:
            cls, char_name, spec = picked
            # Only counted statuses go to the bench.
            if signup_with(raid, sender, cls, char_name, spec, status, now):
                await press.reply(bench_reply(sender, char_name), private=True)
    elif button == ABSENT:
        if old is not None:
            cls, char_name, spec = old["class"], old["char_name"], old["spec"]
        else:
            cls, char_name, spec = None, sender.name, None
        store.upsert_signup(
            raid["id"], sender.id, sender.name, char_name, cls, spec, ABSENT, now
        )
    elif button == "leave":
        if not store.remove_signup(raid["id"], sender.id):
            return
    else:
        return
    await refresh(press.channel, raid["id"])
    seq = store.picker_of(raid["id"], sender.id)
    if seq is not None:
        await bot.replace_card(press.channel, seq, render_picker(store.raid(raid["id"]), sender.id))


async def refresh(channel: spezl.Channel, raid_id: int, pickers: bool = False) -> None:
    """Updates the raid card, the leader panels and, when `pickers` or once cancelled, the
    sign-up cards. All of them were posted into the raid card's channel."""
    raid = store.raid(raid_id)
    await bot.replace_card(channel, raid["card_seq"], await raid_card(channel, raid))
    for seq in store.roster_cards_of(raid_id):
        await bot.replace_card(channel, seq, render_roster_card(raid))
    if pickers or raid["state"] == CANCELLED:
        for seq, user in store.pickers_with_users(raid_id):
            await bot.replace_card(channel, seq, render_picker(raid, user))


def bench_reply(sender: spezl.Sender, char_name: str) -> str:
    return f"@{sender.name} the raid is full: {char_name} is on the bench."


@bot.on_press
async def pressed(press: spezl.Press) -> None:
    server, grp = press.channel.server, press.channel.group
    raid = store.raid_by_card(server, grp, press.card)
    if raid is not None:
        async with lock_of(raid["id"]):
            await raid_press(press, store.raid(raid["id"]))
        return
    picker = store.picker(server, grp, press.card)
    if picker is not None:
        await picker_press(press, picker)
        return
    roster = store.roster_card(server, grp, press.card)
    if roster is not None:
        async with lock_of(roster["raid_id"]):
            await roster_press(press, roster)
        return
    await raids_press(press)


async def raid_press(press: spezl.Press, raid: sqlite3.Row) -> None:
    sender, button, now = press.sender, press.button, now_ms()
    if raid["state"] == CANCELLED:
        return
    if button == "mine":
        reason = closed_reason(raid, now)
        if reason:
            await press.reply(f"@{sender.name} {reason}", private=True)
        else:
            await show_picker(press, raid)
        return
    if button in (LATE, TENTATIVE, BENCH, ABSENT):
        await status_press(press, raid, now)
        return
    # A button this card no longer has (a card from an older layout): show the current card.
    await refresh(press.channel, raid["id"])


async def retire(
    channel: spezl.Channel, seqs: list[int], forget: Callable[[str, str, int], None]
) -> None:
    """Forgets the bot's cards `seqs` with `forget` and deletes them in `channel`. A card that
    cannot be deleted (pinned, or a send failure) stays, but no longer follows the raid."""
    for seq in seqs:
        forget(channel.server, channel.group, seq)
        try:
            await bot.delete_message(channel, seq)
        except spezl.SpezlError as e:
            print(f"deleting card {seq}: {e}", file=sys.stderr)


async def reveal_card(action: spezl.Press | spezl.Submit, seq: int) -> None:
    """Scrolls the member's chat to the bot's card `seq`; a failure only costs the jump."""
    try:
        await action.reveal(seq)
    except spezl.SpezlError as e:
        print(f"revealing card {seq}: {e}", file=sys.stderr)


async def show_roster(channel: spezl.Channel, user: str, raid: sqlite3.Row) -> None:
    """Posts the leader panel to `user` and deletes the previous ones: the leader may have
    deleted a panel for themselves, which the bot cannot see, so every call posts a fresh
    one. Sign-up changes replace it in place (refresh)."""
    old = store.roster_cards_of(raid["id"])
    seq = await bot.post_card(channel, render_roster_card(raid), to=user)
    store.add_roster_card(channel.server, channel.group, seq, raid["id"])
    await retire(channel, old, store.remove_roster_card)


async def repost(channel: spezl.Channel, raid: sqlite3.Row) -> None:
    """Posts the raid card afresh and deletes the previous one: a member may have deleted it,
    for everyone or for themselves, which the bot cannot see. A card that cannot be deleted
    (pinned) stays, but no longer follows the raid."""
    old = raid["card_seq"]
    seq = await bot.post_card(channel, await raid_card(channel, raid))
    store.set_card(raid["id"], seq)
    schedule_close(store.raid(raid["id"]))
    if old is not None:
        try:
            await bot.delete_message(channel, old)
        except spezl.SpezlError as e:
            print(f"deleting raid card {old}: {e}", file=sys.stderr)


async def roster_press(press: spezl.Press, card: sqlite3.Row) -> None:
    raid = store.raid(card["raid_id"])
    if raid is None or raid["state"] == CANCELLED or press.sender.id != raid["leader_id"]:
        return
    if press.button == "announce":
        await announce(press, raid)
        return
    if press.button == "lock":
        state = OPEN if raid["state"] == LOCKED else LOCKED
        store.set_state(raid["id"], state)
        await refresh(press.channel, raid["id"], pickers=True)
        deadline_ms = raid["deadline_ms"]
        if state == OPEN and deadline_ms is not None and now_ms() >= deadline_ms:
            await press.reply(
                f"sign-ups stay closed: the deadline {fmt(deadline_ms)} has passed. "
                "Change it with ⏳ Sign-up deadline.",
                private=True,
            )
        return
    if press.button in ("cancel", "keep"):
        card = render_roster_card(raid, confirm=press.button == "cancel")
        await bot.replace_card(press.channel, press.card, card)
        return
    if press.button == "confirm":
        store.set_state(raid["id"], CANCELLED)
        await refresh(press.channel, raid["id"])
        return
    action, _, rest = press.button.partition("-")
    if action not in (ROSTER_RAID, ROSTER_BENCH):
        return
    rid, _, tag = rest.partition("-")
    try:
        n = int(rid)
    except ValueError:
        return
    # A sign-up keeps its rowid while the member changes it, and the button names the member
    # too (an empty tag: a card from before tags). A stale card's press, after a sign-up was
    # deleted and its rowid reused, so finds no sign-up instead of someone else's.
    s = store.signup_by_rowid(raid["id"], n)
    if s is None or not s["user_id"].startswith(tag):
        await press.reply("That sign-up is gone.", private=True)
        return
    if s["status"] == ABSENT:
        await press.reply(f"{s['char_name']} is absent now.", private=True)
        return
    if action == ROSTER_RAID and s["roster"] != ROSTER_RAID:
        raiders = sum(1 for r in store.signups(raid["id"]) if r["roster"] == ROSTER_RAID)
        if raiders >= raid["size"]:
            await press.reply(
                f"The roster is full ({raid['size']}): bench someone first.", private=True
            )
            return
    store.set_roster(raid["id"], s["user_id"], action)
    await refresh(press.channel, raid["id"])


RAIDS_ACTIONS = ("manage", "post", "cancel", "confirm", "keep")


async def raids_press(press: spezl.Press) -> None:
    """A leader's press on a /raids card; the card then shows the list afresh."""
    action, _, rest = press.button.partition("-")
    if action not in RAIDS_ACTIONS:
        return
    try:
        raid_id = int(rest)
    except ValueError:
        return
    notice, confirm = None, None
    now = now_ms()
    async with lock_of(raid_id):
        raid = store.raid(raid_id)
        if (
            raid is None
            or raid["server"] != press.channel.server
            or raid["grp"] != press.channel.group
        ):
            # The list only ever shows raids of its own channel.
            return
        if press.sender.id != raid["leader_id"]:
            notice = f"Only {raid['leader_name']} can do that."
        elif action == "keep":
            pass
        elif raid["state"] == CANCELLED:
            notice = f"Raid #{raid_id} is already cancelled."
        elif raid["start_ms"] < now:
            notice = f"Raid #{raid_id} has started already."
        elif action == "manage":
            await show_roster(press.channel, press.sender.id, raid)
            notice = f"👑 The leader panel of raid #{raid_id} **{raid['title']}** is below."
        elif action == "post":
            await repost(press.channel, raid)
            notice = f"✔ Raid #{raid_id} **{raid['title']}** is posted again."
        elif action == "cancel":
            confirm = raid_id
        else:
            store.set_state(raid_id, CANCELLED)
            await refresh(press.channel, raid_id)
            notice = f"❌ Raid #{raid_id} **{raid['title']}** is cancelled."
    await bot.replace_card(
        press.channel,
        press.card,
        render_raids_card(press.channel, press.sender.id, now, notice, confirm),
    )


async def announce(press: spezl.Press, raid: sqlite3.Row) -> None:
    """Pings the roster in the raid card's thread."""
    signups = store.signups(raid["id"])
    raiders = [s for s in signups if s["roster"] == ROSTER_RAID]
    bench = [s for s in signups if s["roster"] == ROSTER_BENCH]
    if not raiders:
        await press.reply("Nobody is in the roster yet.", private=True)
        return
    text = f"📣 **{raid['title']}** · 🕗 {fmt(raid['start_ms'])}: the roster is set."
    text += "\n\n**In the raid:** " + " ".join(f"@{s['user_name']}" for s in raiders)
    if bench:
        text += "\n\n**🪑 Bench:** " + " ".join(f"@{s['user_name']}" for s in bench)
    await bot.send(press.channel, text, reply_to=raid["card_seq"])


async def show_picker(press: spezl.Press, raid: sqlite3.Row) -> None:
    """Posts the sender's sign-up card for the raid and deletes their previous ones (a
    card deleted for oneself is invisible to the bot). Sign-up changes replace it in place."""
    sender = press.sender
    old = store.pickers_of_user(raid["id"], sender.id)
    seq = await bot.post_card(press.channel, render_picker(raid, sender.id), to=sender.id)
    store.add_picker(press.channel.server, press.channel.group, seq, sender.id, raid["id"])
    await reveal_card(press, seq)
    await retire(press.channel, old, store.remove_picker)


async def picker_press(press: spezl.Press, picker: sqlite3.Row) -> None:
    if press.sender.id != picker["user_id"]:
        return
    if press.button.startswith("char-"):
        await picker_signup(press, picker["raid_id"], press.button.removeprefix("char-"), now_ms())
        return
    if press.button not in STATUS_BUTTONS:
        return
    async with lock_of(picker["raid_id"]):
        raid = store.raid(picker["raid_id"])
        if raid is None or raid["state"] == CANCELLED:
            return
        await status_press(press, raid, now_ms())


@bot.on_submit
async def submitted(sub: spezl.Submit) -> None:
    """"⏳ Sign-up deadline" on a leader panel sets the deadline; "➕ New character" on a
    sign-up card saves the character and signs it up."""
    server, grp = sub.channel.server, sub.channel.group
    roster = store.roster_card(server, grp, sub.card)
    if roster is not None:
        if sub.button == "deadline":
            async with lock_of(roster["raid_id"]):
                await deadline_submit(sub, roster)
        return
    picker = store.picker(server, grp, sub.card)
    if picker is None or sub.button != "new" or sub.sender.id != picker["user_id"]:
        return
    found = char_from_values(sub.values)
    if found is None:
        await sub.reply("That character does not fit WoW Forever.", private=True)
        return
    wow_class, spec, name, race = found
    now = now_ms()
    store.save_character(
        sub.sender.id, wow_class.id, name, race.id if race else None, spec.id, now
    )
    await picker_signup(sub, picker["raid_id"], wow_class.id, now)


async def deadline_submit(sub: spezl.Submit, card: sqlite3.Row) -> None:
    raid = store.raid(card["raid_id"])
    if raid is None or raid["state"] == CANCELLED or sub.sender.id != raid["leader_id"]:
        return
    deadline_ms = sub.values.get("deadline")
    problem = deadline_problem(deadline_ms, raid["start_ms"], now_ms())
    if problem:
        await sub.reply(problem, private=True)
        return
    store.set_deadline(raid["id"], deadline_ms)
    await refresh(sub.channel, raid["id"], pickers=True)
    schedule_close(store.raid(raid["id"]))


async def picker_signup(
    action: spezl.Press | spezl.Submit,
    raid_id: int,
    cls_id: str,
    now_ms: int,
) -> None:
    """Signs the member who sent `action` up for raid `raid_id` with their saved `cls_id`
    character, scrolls their chat to the raid card and shows the result on their newest sign-up
    card."""
    channel, sender = action.channel, action.sender
    char = store.character(sender.id, cls_id)
    if char is None or spec_of(cls_id, char["spec"]) is None:
        text = f"@{sender.name} that character is gone: save it again with /char."
        await action.reply(text, private=True)
        return
    async with lock_of(raid_id):
        raid = store.raid(raid_id)
        if raid is None or raid["state"] == CANCELLED:
            return
        reason = closed_reason(raid, now_ms)
        if reason:
            text = f"@{sender.name} {reason}"
            await action.reply(text, private=True)
            return
        benched = signup_with(raid, sender, cls_id, char["name"], char["spec"], SIGNED, now_ms)
        await refresh(channel, raid["id"])
        await reveal_card(action, raid["card_seq"])
        # The newest sign-up card: the pressed one may have been replaced since.
        seq = store.picker_of(raid_id, sender.id)
        if seq is not None:
            await bot.replace_card(
                channel, seq, render_picker(store.raid(raid_id), sender.id, benched)
            )


def signed_character(user: str, old: sqlite3.Row | None) -> tuple[str, str, str] | None:
    """The class, name and spec a status button signs up with: the class of the member's
    sign-up, else their last saved character."""
    if old is not None and old["class"] is not None:
        char = store.character(user, old["class"])
        if char is not None and spec_of(char["class"], char["spec"]):
            return char["class"], char["name"], char["spec"]
        if spec_of(old["class"], old["spec"]):
            return old["class"], old["char_name"], old["spec"]
    char = store.latest_character(user)
    if char is not None and spec_of(char["class"], char["spec"]):
        return char["class"], char["name"], char["spec"]
    return None


# -- ready, reminders and deadlines ----------------------------------------------


def raid_channel(raid: sqlite3.Row) -> spezl.Channel:
    """The channel of `raid`'s card."""
    return spezl.Channel(
        server=raid["server"],
        id=raid["channel_id"],
        name=raid["channel_name"],
        group=raid["grp"],
    )


def schedule_close(raid: sqlite3.Row | None) -> None:
    """Re-renders the raid's cards when its deadline passes: nothing else does then, and the
    sign-up buttons have to turn disabled."""
    if raid is None:
        return
    old = closers.pop(raid["id"], None)
    if old is not None:
        old.cancel()
    if raid["deadline_ms"] is None or raid["state"] == CANCELLED or raid["card_seq"] is None:
        return
    closers[raid["id"]] = asyncio.create_task(close_at(raid["id"], raid["deadline_ms"]))


async def close_at(raid_id: int, deadline_ms: int) -> None:
    await asyncio.sleep(max(0, deadline_ms - now_ms()) / 1000)
    async with lock_of(raid_id):
        raid = store.raid(raid_id)
        if raid is None or raid["deadline_ms"] != deadline_ms or raid["state"] == CANCELLED:
            return
        try:
            await refresh(raid_channel(raid), raid_id, pickers=True)
        except spezl.SpezlError as e:
            print(f"closing raid #{raid_id}: {e}", file=sys.stderr)


async def remind_loop() -> None:
    while True:
        try:
            now = now_ms()
            for raid in store.due_reminders(now):
                signups = store.signups(raid["id"])
                # Once the leader started the roster, it decides who raids.
                _, picked = lineup(signups)
                names = [f"@{s['user_name']}" for s in picked]
                if now < raid["start_ms"] and names:
                    text = f"⏰ **{raid['title']}** starts at {fmt(raid['start_ms'])}: " + " ".join(
                        names
                    )
                    try:
                        await bot.send(raid_channel(raid), text, reply_to=raid["card_seq"])
                    except spezl.SpezlError as e:
                        print(f"reminder for raid #{raid['id']}: {e}", file=sys.stderr)
                # A raid whose start passed while the bot was offline is marked without a
                # message.
                store.mark_reminded(raid["id"])
        except Exception as e:  # keep reminding whatever one round hit
            print(f"reminders: {e!r}", file=sys.stderr)
        await asyncio.sleep(REMIND_EVERY_S)


@bot.on_ready
async def ready(server: str) -> None:
    global reminder_task
    print(f"{bot.name} ready on {server}", flush=True)
    # Not awaited: the bot waits for its handlers before it shuts down, and this loop runs
    # forever. asyncio.run cancels it at exit.
    if reminder_task is None:
        reminder_task = asyncio.create_task(remind_loop())
    # A deadline that passed while the bot was offline closes at once; a second `ready`
    # replaces the tasks of the first.
    for raid in store.open_deadlines(now_ms()):
        schedule_close(raid)


bot.run()
