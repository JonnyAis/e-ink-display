"""Style guide enforcement, part 2: render every page in every state and check the result.

Add new pages/states to PAGES below. A page that fails here does not meet the style guide.
"""
import pytest

from app import style
from app.pages.sports import render_sports_page
from app.preview_team import NOW, variants
from app.preview_sports import GAMES
from app.pages.team import render_team
from app import greetings
from app.preview_greetings import STATES as GREETING_STATES, variants as greeting_variants
from helpers import overlaps, record_drawing

W, H = style.PANEL


def _team(name):
    return lambda: render_team(variants()[name], now=NOW)


PAGES = {f"team/{n}": _team(n) for n in variants()}
PAGES.update({
    "sports/normal": lambda: render_sports_page(GAMES, "8:14 PM"),
    "sports/stale": lambda: render_sports_page(GAMES, "8:14 PM", stale=True, stale_minutes=7),
    "sports/empty": lambda: render_sports_page([], "8:14 PM"),
    "message/offline": lambda: style.message_screen("Team", "No data yet", stale_minutes=0),
})
PAGES.update({   # every frame of every greeting style, rendered inside the test so its drawing is recorded
    f"greeting/{st}/{state}/{i}": (lambda st=st, state=state, i=i: greetings.render(st, GREETING_STATES[state], show_s=10.0)[i][0])
    for (st, state), frames in greeting_variants().items() for i in range(len(frames))
})

# Full-bleed interludes (docs/STYLE_GUIDE.md, "Display-face exception"): black, no header, shown for
# seconds. They skip only the header/margin check; every other rule still applies, plus pure black/white.
FULL_BLEED = {n for n in PAGES if n.startswith("greeting/")}


@pytest.fixture(params=sorted(PAGES), ids=str)
def page(request):
    with record_drawing() as rec:
        img = PAGES[request.param]()
    return request.param, img, rec


def test_image_matches_panel(page):
    _, img, _ = page
    assert img.size == style.PANEL and img.mode == "L"


def test_only_allowed_inks(page):
    name, _, rec = page
    assert rec.inks <= style.ALLOWED_INKS, f"{name} uses inks outside the palette: {sorted(rec.inks - style.ALLOWED_INKS)}"


def test_no_text_below_minimum_size(page):
    name, _, rec = page
    assert None not in rec.font_sizes, f"{name} drew text with an unknown font"
    assert min(rec.font_sizes) >= style.MIN_TEXT_PX, f"{name} has text smaller than {style.MIN_TEXT_PX}px"


def test_text_stays_inside_safe_edges(page):
    name, _, rec = page
    e = style.SAFE_EDGE
    for (x0, y0, x1, y1), text in rec.texts:
        assert x0 >= e and y0 >= e and x1 <= W - e and y1 <= H - e, f"{name}: '{text}' too close to the edge {(x0, y0, x1, y1)}"


def test_no_text_collisions(page):
    name, _, rec = page
    for i, (a, ta) in enumerate(rec.texts):
        for b, tb in rec.texts[i + 1:]:
            assert not overlaps(a, b), f"{name}: '{ta}' overlaps '{tb}'"


def test_has_header_and_clear_margins(page):
    name, img, _ = page
    if name in FULL_BLEED:
        assert {c for _, c in img.getcolors()} <= {style.INK, style.PAPER}, f"{name} must be pure black/white (A2-safe)"
        return
    px = img.load()
    assert px[5, 5] == 0 and px[W - 6, 5] == 0, f"{name} has no header bar"
    e = style.SAFE_EDGE
    below = range(style.HEADER_H + 1, H)
    assert all(px[x, y] == 255 for y in below for x in list(range(e)) + list(range(W - e, W))), f"{name} draws in the side margins"
    assert all(px[x, y] == 255 for y in range(H - e, H) for x in range(W)), f"{name} draws in the bottom margin"


def test_stale_data_is_always_flagged(page):
    """Honest data: stale data shows a STALE tag; fresh data never does."""
    name, _, rec = page
    shown = any("STALE" in t for _, t in rec.texts)
    expect = name.endswith("stale") or name.endswith("offline")
    assert shown == expect, f"{name}: STALE tag {'missing' if expect else 'shown on fresh data'}"


def test_empty_states_say_something():
    for name in ("team/empty", "sports/empty"):
        with record_drawing() as rec:
            PAGES[name]()
        words = " ".join(t for _, t in rec.texts)
        assert any(s in words for s in ("No upcoming games", "No games right now")), name


def test_never_prints_placeholder_text(page):
    """Missing values must render as a dash or a sentence, never as 'None' / 'nan' / 'null'."""
    name, _, rec = page
    for _, text in rec.texts:
        assert not any(bad in text.lower() for bad in ("none", "nan", "null")), f"{name}: prints '{text}'"
