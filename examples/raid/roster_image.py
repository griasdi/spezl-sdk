"""The roster picture of the raid bot's card: the raid's title, its fill and, per role, the
classes signed up with their counts. The names stay in the card's text columns.

Icons are grayscale masks in `icons/` (game-icons.net, CC BY 3.0, see `icons/LICENSE.md`);
the footer credits them. Fonts are Atkinson Hyperlegible Next in `fonts/` (SIL OFL 1.1, see
`fonts/OFL.txt`), the font griasdi's own UI is built on.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from wow_forever import CLASSES, HEALER, MELEE, RANGED, TANK


ICONS = Path(__file__).parent / "icons"
FONTS = Path(__file__).parent / "fonts"

# Twice the 416 px a griasdi card shows a picture at, so it stays sharp on a 2× screen and
# every size below is twice its size on screen. The app letterboxes a picture taller than
# 440 px, so the height stays below 880.
W = 832
L, R = 24, 808
GOLD = "#F0C75E"
TEXT = "#ECEEF4"
MUTED = "#AAAFC0"
PANEL = "#242838"
TRACK = "#2E3244"
GREEN = "#4CAF60"
TOP = (0x14, 0x16, 0x1E)
BOTTOM = (0x1F, 0x22, 0x30)

# Label, icon and color of each role tile.
ROLE_STYLES = {
    TANK: ("Tanks", "tank", "#6FA8DC"),
    HEALER: ("Healers", "healer", "#57BB8A"),
    MELEE: ("Melee", "melee", "#E06666"),
    RANGED: ("Ranged", "ranged", "#F6B26B"),
}

# The role tiles: a 2×2 grid, tanks and healers on top like the card's text columns.
TILE_W, TILE_STEP, TILES_TOP, TILES_GAP = 384, 400, 184, 20
# A tile's header and the step and height of its class rows.
TILE_HEAD, ROW, ROW_H = 62, 50, 44
CREDIT = "Icons: Lorc, Delapouite, Sbed · game-icons.net · CC BY 3.0"


@lru_cache
def _mask(name: str) -> Image.Image:
    return Image.open(ICONS / f"{name}.png").convert("L")


@lru_cache
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    weight = "Bold" if bold else "Medium"
    return ImageFont.truetype(FONTS / f"AtkinsonHyperlegibleNext-{weight}.ttf", size)


def tint(img: Image.Image, name: str, color: str, xy: tuple[int, int], px: int) -> None:
    """Paints icon `name` at `xy`, `px` square, in `color`."""
    mask = _mask(name).resize((px, px), Image.Resampling.LANCZOS)
    img.paste(Image.new("RGB", (px, px), color), xy, mask)


def clip(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    """`text`, cut with "…" until it fits `width` pixels."""
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _gradient(height: int) -> Image.Image:
    img = Image.new("RGB", (W, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
        draw.line([(0, y), (W, y)], fill=color)
    return img


def _diamond(draw: ImageDraw.ImageDraw, x: int, y: int, r: int) -> None:
    draw.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=GOLD)


def _tile_height(roles: list[tuple[str, list[tuple[str, int]]]]) -> int:
    return TILE_HEAD + ROW * max(1, *(len(classes) for _, classes in roles))


def render(
    title: str,
    subtitle: str,
    status: str,
    filled: int,
    size: int,
    roles: list[tuple[str, list[tuple[str, int]]]],
) -> bytes:
    """The picture as RGB PNG bytes. `roles`: `(role id, [(class id, count), …])` in `ROLES`
    order, the classes in `CLASSES` order and only those with a count; `status` and `filled`
    of `size` make the progress line ("Signed up 12/40")."""
    h1, h2 = _tile_height(roles[:2]), _tile_height(roles[2:])
    height = TILES_TOP + h1 + TILES_GAP + h2 + 48
    img = _gradient(height)
    draw = ImageDraw.Draw(img)

    # Header.
    tint(img, "dragon", GOLD, (L, 18), 72)
    draw.text((112, 14), clip(title, _font(46, True), R - 112), font=_font(46, True), fill=GOLD)
    draw.text((112, 70), clip(subtitle, _font(26), R - 112), font=_font(26), fill=MUTED)
    draw.line([(L, 116), (R, 116)], fill=GOLD, width=2)
    _diamond(draw, W // 2, 116, 7)
    _diamond(draw, W // 2 - 22, 116, 4)
    _diamond(draw, W // 2 + 22, 116, 4)

    # Progress: the track ends 14 px before the text, so a long status never overlaps it.
    progress = f"{status} {filled}/{size}"
    font = _font(28, True)
    end = R - round(font.getlength(progress)) - 14
    draw.rounded_rectangle((L, 134, end, 160), radius=13, fill=TRACK)
    share = min(filled, size) / size if size else 0
    if share > 0:
        right = L + max(26, round((end - L) * share))
        draw.rounded_rectangle((L, 134, right, 160), radius=13, fill=GREEN)
    draw.text((R, 130), progress, font=font, fill=TEXT, anchor="ra")

    # Role tiles: one row per class with its count.
    for i, (role, classes) in enumerate(roles):
        x = L + (i % 2) * TILE_STEP
        y = TILES_TOP if i < 2 else TILES_TOP + h1 + TILES_GAP
        label, icon, color = ROLE_STYLES[role]
        tint(img, icon, color, (x, y + 2), 34)
        total = sum(n for _, n in classes)
        draw.text((x + 46, y), f"{label} ({total})", font=_font(32, True), fill=TEXT)
        draw.line([(x, y + 50), (x + TILE_W, y + 50)], fill=color, width=3)
        if not classes:
            draw.text((x + 4, y + 66), "nobody yet", font=_font(26), fill=MUTED)
            continue
        for j, (cid, n) in enumerate(classes):
            ry = y + TILE_HEAD + ROW * j
            cls = CLASSES[cid]
            draw.rounded_rectangle((x, ry, x + TILE_W, ry + ROW_H), radius=8, fill=PANEL)
            draw.rectangle((x, ry, x + 6, ry + ROW_H), fill=cls.color)
            tint(img, cid, cls.color, (x + 14, ry + 4), 36)
            draw.text((x + 62, ry + 6), cls.name, font=_font(28), fill=cls.color)
            draw.text(
                (x + TILE_W - 14, ry + 5), f"×{n}", font=_font(30, True), fill=TEXT, anchor="ra"
            )

    # Footer: the attribution CC BY asks for.
    draw.text((R, height - 30), CREDIT, font=_font(20), fill=MUTED, anchor="ra")

    out = io.BytesIO()
    # Fast over small: griasdi re-encodes an opaque picture to JPEG anyway.
    img.save(out, format="PNG", compress_level=1)
    return out.getvalue()
