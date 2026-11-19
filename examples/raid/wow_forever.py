"""Classes, specs, races and raids of World of Warcraft: Forever, for the raid sign-up bot.

Sources, which agree on everything here:
- Blizzard, "Create the Hero You Want to Be in World of Warcraft: Forever" (Sep 22, 2026),
  http://worldofwarcraft.blizzard.com/news/24304075
- wow-forever.gg, /classes/ and /races/, game build 1.60.1.70532
- Blizzard, "World of Warcraft: Forever Raid Overview" (Oct 20, 2026),
  http://worldofwarcraft.blizzard.com/news/24303009

Feral Combat is one talent tree; it is split into Bear and Cat here because a raid roster
needs the role.
"""

from __future__ import annotations

from dataclasses import dataclass

TANK = "tank"
HEALER = "healer"
MELEE = "melee"
RANGED = "ranged"

# In the order the roster shows them.
ROLES = ((TANK, "🛡️ Tanks"), (HEALER, "💚 Healers"), (MELEE, "⚔️ Melee"), (RANGED, "🎯 Ranged"))

# The raid overview cited above; the raid card links to it.
RAID_OVERVIEW_URL = "http://worldofwarcraft.blizzard.com/news/24303009"


@dataclass(frozen=True)
class Spec:
    id: str
    name: str
    role: str


@dataclass(frozen=True)
class WowClass:
    id: str
    name: str
    icon: str
    # The class color of the game's UI, for the roster picture.
    color: str
    specs: tuple[Spec, ...]

    def spec(self, spec_id: str | None) -> Spec | None:
        return next((s for s in self.specs if s.id == spec_id), None)


@dataclass(frozen=True)
class Race:
    id: str
    name: str
    faction: str
    classes: tuple[str, ...]


def _class(id: str, name: str, icon: str, color: str, *specs: tuple[str, str, str]) -> WowClass:
    return WowClass(id, name, icon, color, tuple(Spec(*s) for s in specs))


CLASSES: dict[str, WowClass] = {
    c.id: c
    for c in (
        _class(
            "warrior",
            "Warrior",
            "🪓",
            "#C69B6D",
            ("arms", "Arms", MELEE),
            ("fury", "Fury", MELEE),
            ("protection", "Protection", TANK),
        ),
        _class(
            "paladin",
            "Paladin",
            "🔨",
            "#F48CBA",
            ("holy", "Holy", HEALER),
            ("protection", "Protection", TANK),
            ("retribution", "Retribution", MELEE),
        ),
        _class(
            "hunter",
            "Hunter",
            "🏹",
            "#AAD372",
            ("beast-mastery", "Beast Mastery", RANGED),
            ("marksmanship", "Marksmanship", RANGED),
            ("survival", "Survival", RANGED),
        ),
        _class(
            "rogue",
            "Rogue",
            "🗡️",
            "#FFF468",
            ("assassination", "Assassination", MELEE),
            ("combat", "Combat", MELEE),
            ("subtlety", "Subtlety", MELEE),
        ),
        _class(
            "priest",
            "Priest",
            "✨",
            "#FFFFFF",
            ("discipline", "Discipline", HEALER),
            ("holy", "Holy", HEALER),
            ("shadow", "Shadow", RANGED),
        ),
        _class(
            "shaman",
            "Shaman",
            "⚡",
            "#0070DD",
            ("elemental", "Elemental", RANGED),
            ("enhancement", "Enhancement", MELEE),
            ("restoration", "Restoration", HEALER),
        ),
        _class(
            "mage",
            "Mage",
            "🔮",
            "#3FC7EB",
            ("arcane", "Arcane", RANGED),
            ("fire", "Fire", RANGED),
            ("frost", "Frost", RANGED),
        ),
        _class(
            "warlock",
            "Warlock",
            "💀",
            "#8788EE",
            ("affliction", "Affliction", RANGED),
            ("demonology", "Demonology", RANGED),
            ("destruction", "Destruction", RANGED),
        ),
        _class(
            "druid",
            "Druid",
            "🐾",
            "#FF7C0A",
            ("balance", "Balance", RANGED),
            ("feral-bear", "Feral Combat (Bear)", TANK),
            ("feral-cat", "Feral Combat (Cat)", MELEE),
            ("restoration", "Restoration", HEALER),
        ),
    )
}

_ALLIANCE = "Alliance"
_HORDE = "Horde"
FACTION_ICONS = {_ALLIANCE: "🦁", _HORDE: "🐺"}

RACES: dict[str, Race] = {
    r.id: r
    for r in (
        Race(
            "human",
            "Human",
            _ALLIANCE,
            ("warrior", "paladin", "hunter", "rogue", "priest", "mage", "warlock"),
        ),
        Race(
            "dwarf",
            "Dwarf",
            _ALLIANCE,
            ("warrior", "paladin", "hunter", "rogue", "priest", "shaman"),
        ),
        Race(
            "night-elf", "Night Elf", _ALLIANCE, ("warrior", "hunter", "rogue", "priest", "druid")
        ),
        Race("gnome", "Gnome", _ALLIANCE, ("warrior", "rogue", "priest", "mage", "warlock")),
        Race(
            "high-order-skyborne",
            "High Order Skyborne",
            _ALLIANCE,
            ("warrior", "hunter", "rogue", "mage", "druid"),
        ),
        Race("orc", "Orc", _HORDE, ("warrior", "hunter", "rogue", "shaman", "mage", "warlock")),
        Race(
            "undead", "Undead", _HORDE, ("warrior", "paladin", "rogue", "priest", "mage", "warlock")
        ),
        Race("tauren", "Tauren", _HORDE, ("warrior", "hunter", "shaman", "druid")),
        Race(
            "troll",
            "Troll",
            _HORDE,
            ("warrior", "hunter", "rogue", "priest", "shaman", "mage", "warlock"),
        ),
        Race(
            "windshaper-skyborne",
            "Windshaper Skyborne",
            _HORDE,
            ("warrior", "hunter", "rogue", "shaman", "druid"),
        ),
    )
}


@dataclass(frozen=True)
class Raid:
    id: str
    name: str
    size: int
    phase: int


# The phase the game is in: /raid offers the raids up to it.
CURRENT_PHASE = 1

# Phase 1 opens on 9 December 2026. The spring and summer 2027 raids are not named yet.
RAIDS: dict[str, Raid] = {
    r.id: r
    for r in (
        Raid("barrow-deeps", "The Barrow Deeps", 10, 1),
        Raid("hyjal-summit", "Hyjal Summit", 20, 1),
        Raid("onyxias-lair", "Onyxia's Lair", 40, 1),
    )
}
