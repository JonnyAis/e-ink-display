"""Visual style for every page: tokens + shared components.

This is the single source of truth for how pages look. Pages must not call
ImageFont.truetype or use raw font sizes / gray values; they ask this module
for a *role* (BODY, HEADING, ...) or a *named ink* (INK, GRAY_TEXT, ...).
tests/test_style.py enforces that. See docs/STYLE_GUIDE.md for the reasoning.

Designed for the 1872x1404 IT8951 panel (~10.3 in, ~227 ppi). Everything is
plain Pillow, so any page can be previewed as a PNG without hardware.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- canvas ----
PANEL = (1872, 1404)
MARGIN = 40           # page margin for content
SAFE_EDGE = 24        # nothing (text) may come closer to a panel edge than this
GAP = 28              # standard gap between blocks
HEADER_H = 200        # black header bar, same height as the bus screen
RADIUS = 30           # card / badge corner radius
RULE = 3              # divider thickness
RULE_HEAVY = 6        # outline of an emphasised (hero) card

# ----------------------------------------------------------------- inks -----
# Pure black and white are reserved for regions that may use fast A2 updates.
# Beyond that there are exactly three grays, each with one job.
INK = 0
PAPER = 255
GRAY_TEXT = 90        # secondary text on white (labels, units, "scheduled")
GRAY_MID = 150        # muted / departed / stale content, thin separators on black
GRAY_LINE = 215       # dividers on white; secondary text on the black header
ALLOWED_INKS = frozenset({INK, PAPER, GRAY_TEXT, GRAY_MID, GRAY_LINE})

# ----------------------------------------------------------------- type -----
# role -> (pixel size, default weight). One scale for every page.
MIN_TEXT_PX = 44      # nothing smaller than this; readable across a room
ROLES = {
    "HERO":    (260, "bold"),     # the one number/name you read first
    "TITLE":   (110, "bold"),     # header bar title
    "DISPLAY": (84,  "bold"),     # scores, times, stat values
    "HEADING": (60,  "bold"),     # panel titles
    "BODY":    (52,  "regular"),  # table rows, lists
    "LABEL":   (44,  "regular"),  # captions, units, status tags
    # Deliberate exception: novelty display faces for greetings only (see
    # docs/STYLE_GUIDE.md, "Display faces"). Never use them for data.
    "SPOOKY":  (320, "spooky"),   # Creepster, SIL OFL 1.1 (Font Diner, Inc)
}
INTERLUDE_ROLES = frozenset({"SPOOKY"})   # roles only greetings (app/greetings/) may use
assert all(size >= MIN_TEXT_PX for size, _ in ROLES.values())

_BUNDLED = Path(__file__).resolve().parent / "assets" / "fonts"
_FILES = {"regular": "Barlow-Regular.ttf", "bold": "Barlow-SemiBold.ttf",
          "spooky": "Creepster-Regular.ttf"}
_OVERRIDE = {"regular": "Font-Regular.ttf", "bold": "Font-Bold.ttf"}  # optional EINK_FONT_DIR


@lru_cache(maxsize=None)
def _load(size: int, weight: str):
    cands = []
    override = os.environ.get("EINK_FONT_DIR")
    if override and weight in _OVERRIDE:
        cands.append(Path(override) / _OVERRIDE[weight])
    cands.append(_BUNDLED / _FILES[weight])
    cands.append(Path("/usr/share/fonts/truetype/dejavu") /
                 ("DejaVuSans-Bold.ttf" if weight == "bold" else "DejaVuSans.ttf"))
    for c in cands:
        try:
            return ImageFont.truetype(str(c), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def font(role: str, bold: bool | None = None):
    """Font for a type role. `bold` overrides the role's default weight."""
    size, weight = ROLES[role]
    if bold is not None and weight in ("regular", "bold"):
        weight = "bold" if bold else "regular"
    return _load(size, weight)


# ------------------------------------------------------------ text helpers --
def new_canvas(size=PANEL):
    img = Image.new("L", size, PAPER)
    return img, ImageDraw.Draw(img)


def draw(d, xy, text, role, *, fill=INK, bold=None, anchor="la"):
    """Draw text in a role. anchor: 'la' left/top, 'ra' right/top, 'ma' centre/top, 'ls' left/baseline, 'rs' right/baseline."""
    d.text(xy, text, font=font(role, bold), fill=fill, anchor=anchor)


def text_width(d, text, role, bold=None):
    return d.textlength(text, font=font(role, bold))


def fit_text(d, text, role, max_w, bold=None):
    """Truncate with an ellipsis so the text fits; the size is never reduced."""
    f = font(role, bold)
    if d.textlength(text, font=f) <= max_w:
        return text
    while text and d.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def fmt_time(dt):
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_date(dt):
    return f"{dt:%a %b} {dt.day}"


# ------------------------------------------------------------ components ----
def header(img, title, *, clock_text=None, caption=None, stale_minutes=None):
    """Black header bar: title left; optional clock (with caption above) right; STALE pill if data is old.

    stale_minutes: None = fresh. 0 = stale (age under a minute). n = stale for n minutes.
    """
    W = img.size[0]
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, HEADER_H), fill=INK)
    draw(d, (MARGIN, HEADER_H // 2 + 4), title, "TITLE", fill=PAPER, anchor="lm")
    x_right = W - MARGIN
    if clock_text:
        if caption:
            draw(d, (x_right, 36), caption, "LABEL", fill=GRAY_LINE, anchor="ra")
            draw(d, (x_right, 84), clock_text, "DISPLAY", fill=PAPER, anchor="ra")
        else:
            draw(d, (x_right, HEADER_H // 2 + 4), clock_text, "DISPLAY", fill=PAPER, anchor="rm")
        x_right -= int(text_width(d, clock_text, "DISPLAY")) + 48
    if stale_minutes is not None:
        label = f"STALE {stale_minutes}m" if stale_minutes > 0 else "STALE"
        w = int(text_width(d, label, "LABEL")) + 48
        top, bottom = HEADER_H // 2 - 36, HEADER_H // 2 + 44
        d.rounded_rectangle((x_right - w, top, x_right, bottom), radius=RADIUS, outline=PAPER, width=RULE)
        draw(d, (x_right - w // 2, (top + bottom) // 2), label, "LABEL", fill=PAPER, anchor="mm")


def panel_title(d, x, y, w, left, right=None):
    """Panel heading with a rule under it; returns the y where content starts."""
    draw(d, (x, y), left, "HEADING")
    if right:
        draw(d, (x + w, y), right, "HEADING", fill=GRAY_TEXT, anchor="ra")
    y += int(ROLES["HEADING"][0] * 1.2)
    d.line((x, y, x + w, y), fill=INK, width=RULE)
    return y + 16


def card(d, box, *, urgent=False):
    """A hero card. urgent=True inverts it (black); returns (foreground, secondary) inks to draw on it."""
    if urgent:
        d.rounded_rectangle(box, radius=RADIUS, fill=INK)
        return PAPER, GRAY_LINE
    d.rounded_rectangle(box, radius=RADIUS, outline=INK, width=RULE_HEAVY)
    return INK, GRAY_TEXT


def badge(d, x, y, size, text, *, inverted=False, role="HEADING"):
    """Rounded square with centred text (route number, seed, ...)."""
    d.rounded_rectangle((x, y, x + size, y + size), radius=size // 4,
                        fill=PAPER if inverted else INK, outline=INK, width=RULE_HEAVY)
    draw(d, (x + size // 2, y + size // 2), text, role, fill=INK if inverted else PAPER, anchor="mm")


def message_screen(title, message, *, size=PANEL, stale_minutes=None):
    """State screen for empty / error / offline conditions, in the same visual language."""
    img, d = new_canvas(size)
    header(img, title, stale_minutes=stale_minutes)
    W, H = size
    draw(d, (W // 2, (H + HEADER_H) // 2), message, "DISPLAY", anchor="mm")
    return img


def interlude_screen(message, *, role="SPOOKY", size=PANEL):
    """Full-bleed interlude: one message, white on pure black, centred.

    Uses only INK and PAPER, so the whole frame is A2-safe (the fast black/white
    update mode). It has no header on purpose: it is on screen for a moment and
    then the primary screen comes back (principle 9).
    """
    img = Image.new("L", size, INK)
    d = ImageDraw.Draw(img)
    W, H = size
    text = fit_text(d, message, role, W - 2 * (MARGIN + SAFE_EDGE))
    draw(d, (W // 2, H // 2), text, role, fill=PAPER, anchor="mm")
    # Snap anti-aliased edges to pure black/white so A2 shows exactly this frame.
    return img.point(lambda v: PAPER if v >= 128 else INK)
