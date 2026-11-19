# Raid

A raid sign-up bot for World of Warcraft: Forever. `/char` saves a member's characters, `/raid`
posts a raid card, and members sign up through "Join" on it, which posts a sign-up card only
they see: their saved characters to sign up with (Sign off on the signed-up one), a status row
(Late, Maybe, Bench, Absent; the held one selected, a second press undoes it) and "➕ New
character", which opens a dialog with class tiles whose spec and race choices follow the class,
saves the character and signs it up. Join scrolls the member's chat down to their sign-up card,
and a sign-up there scrolls it back up to the raid card (`reveal`).

The raid card shows a picture of the raid's composition that the bot draws with Pillow and
uploads with `upload_image` (per role a tile with one row per class and its count, class icons
from game-icons.net in the class colors, text in the bundled Atkinson Hyperlegible Next), the
roster with names as text in columns below it, a tally row (Join, Late, Maybe, Bench and Absent)
that counts each status, marks the viewer's own and names who chose it on hover and turns
disabled while sign-ups are closed, and a link to Blizzard's raid overview; the bot replaces the
whole card with `replace_card` on every change.

`/raid` offers the raids of the current and earlier phases from a list (phase 1: The Barrow
Deeps, Hyjal Summit and Onyxia's Lair, in `wow_forever.py`), which set the card's title and
size, takes the start from the date picker and optionally a sign-up deadline; the card shows
the raid's phase.
The leader then gets a leader panel only they see (again with `/raids` → "👑 Manage"): "📣
Announce", which pings the picked members, a lock toggle, "❌ Cancel raid" with a confirmation, a
form to change or clear the deadline and Raid and Bench buttons per sign-up (the chosen one
selected). The leader panel and each member's sign-up card follow every sign-up in place with
`replace_card`; asking again posts a fresh card and deletes the previous one with
`delete_message`. A cancelled raid turns them into a "cancelled" card. Every other answer to a
member's command or button is a private card. The bot keeps its data in SQLite and reminds the
signed-up members (once there is a roster: the picked ones) 15 minutes before the start.

## Commands

- `/raid`: create a raid sign-up.
- `/raids`: list upcoming raids; manage one, post it again or cancel it.
- `/char`: save a character. A member keeps one character per class: saving another of the
  same class replaces it.
- `/chars`: list your saved characters.
- `/char-delete`: delete a saved character.
- `/export`: export a raid's sign-ups as CSV.

## What it shows

- Slash commands with forms, form buttons and select fields with tiles.
- Private cards (`to`, `private=True`) and `reveal`.
- Cards with images (`upload_image`), columns, hinted buttons, links and tallies.
- `replace_card` and `delete_message` to keep cards current.
- SQLite storage in the bot home.

See [Commands and cards](https://griasdi.github.io/bots/#commands) and the
[Python SDK](../../README.md#python).

## Run it

From the repo root:

```sh
spezl new RaidBot
spezl --bot RaidBot join '<invite link>'
spezl --bot RaidBot run examples/raid/raid.py
```

`--bot RaidBot` can go when RaidBot is the default bot (`spezl default RaidBot`).

## Configuration

- `RAIDHELPER_DB`: the SQLite file; default `$SPEZL_HOME/raidhelper.sqlite3`.
- `RAIDHELPER_TZ`: the time zone of the shown times, an IANA zone such as `Europe/Vienna`;
  default the host's zone.

## Requirements

[uv](https://docs.astral.sh/uv/) (Python ≥ 3.10). Pillow comes in through `pyproject.toml`.

## Credits

- Class icons: [game-icons.net](https://game-icons.net), CC BY 3.0, see `icons/LICENSE.md`.
- Font: Atkinson Hyperlegible Next, SIL OFL 1.1, see `fonts/OFL.txt`.
