# Style guide

Every screen should feel like it came from the same device. The reference is the bus **Departures** screen:
big, calm, honest, and it tells you what to do. This guide turns that into rules, and the rules into code
(`app/style.py`) and tests (`tests/test_style.py`, `tests/test_pages_conform.py`) so they are enforced, not just written.

Read the audit it was derived from: [BUS_EXPERIENCE_AUDIT.md](BUS_EXPERIENCE_AUDIT.md).

## Principles

1. **One question per screen, one hero.** Decide what the viewer wants to know first, and make that the largest thing.
2. **Words over icons.** Say what to do ("GO TO BUS STOP!", "LIVE"), not just what the data is.
3. **Fixed grid; nothing moves unless the data changes.**
4. **Update only what changed; scrub on a timer.** Prefer partial updates; do a full GC16 refresh when switching pages
   and on a schedule to clear ghosting.
5. **Always show data age and source quality.** Fresh/stale, predicted/scheduled, updated-at.
6. **Smooth numbers; never let them jump.** Debounce and smooth values that would flicker.
7. **Define every state:** normal, urgent/live, stale, empty, error, offline, setup.
8. **Three grays, plus pure black and white.** Pure black/white regions may use fast A2 updates.
9. **Interludes are short and always return** to the primary screen, and never starve it.

Added after review: **nothing smaller than 44 px** (about 14 pt on this panel). Fewer, larger elements beat more, smaller ones.

## Tokens (all in `app/style.py`)

Designed for the 1872x1404 panel (about 10.3 in, ~227 ppi; confirm from your panel's label).

| Type role | Size | Use |
|---|---|---|
| HERO | 260 | The one number or name read first (a score, an ETA, an opponent) |
| TITLE | 110 | Header bar title |
| DISPLAY | 84 | Scores, times, stat values |
| HEADING | 60 | Panel titles |
| BODY | 52 | Table rows and lists |
| LABEL | 44 | Captions, units, status tags (the minimum) |

| Ink | Value | Use |
|---|---|---|
| INK / PAPER | 0 / 255 | Text, fills, backgrounds; the only values used in A2 regions |
| GRAY_TEXT | 90 | Secondary text on white |
| GRAY_MID | 150 | Muted / departed / stale content |
| GRAY_LINE | 215 | Dividers on white; secondary text on the black header |

Geometry: margin 40, gap 28, header 200, corner radius 30, nothing within 24 px of a panel edge.
Fonts: bundled Barlow (SIL OFL, `app/assets/fonts/`). Set `EINK_FONT_DIR` to a folder with `Font-Regular.ttf` and
`Font-Bold.ttf` to use your own; the repo does not ship licensed fonts.

## Components

| Component | What it is |
|---|---|
| `style.header(img, title, clock_text=, caption=, stale_minutes=)` | Black bar, title left, clock right, outlined STALE pill when data is old |
| `style.panel_title(d, x, y, w, left, right=)` | Heading with a rule; returns where content starts |
| `style.card(d, box, urgent=)` | Hero card. `urgent=True` inverts it (black); this is the "live / go now" signal |
| `style.badge(d, x, y, size, text, inverted=)` | Rounded square for route numbers, seeds, etc. |
| `style.draw(d, xy, text, ROLE, fill=, bold=, anchor=)` | All text goes through this; the size comes from the role |
| `style.fit_text(...)` | Truncate with an ellipsis; text is never shrunk below its role |
| `style.message_screen(title, message)` | Empty / error / offline screen |

## States every page must handle

| State | Look |
|---|---|
| Normal | Hero + supporting panels |
| Urgent / live | The hero card inverted (`card(urgent=True)`) |
| Stale | Last good content stays; header shows `STALE` or `STALE 7m` |
| Empty | A plain sentence in place of the missing part ("No upcoming games") |
| Error / offline | `message_screen`, or stale content with the STALE pill |
| Missing optional data | The panel says so ("Box score not available"); it never disappears silently |

## How it is enforced

| Layer | What it catches |
|---|---|
| `tests/test_style.py` | Pages calling `truetype`, importing `ImageFont`, or passing raw gray values; any role under 44 px |
| `tests/test_pages_conform.py` | For every page and every state: exact panel size and mode; only palette inks; no text under the minimum; no text near the edges; no overlapping text; header present; clear margins; stale data always flagged; empty states have words |
| `python -m app.preview_team`, `python -m app.preview_sports` | Writes every state to `preview/*.png` so a reviewer can look |
| `.githooks/pre-commit` | Secret check (separate from style) |
| `CLAUDE.md`, PR template | Points AI helpers and reviewers at this guide and the tests |

Tests cannot judge taste. They catch violations; a person still looks at the previews.

## Adding a page

1. Copy the pattern in `app/pages/team.py`: fetch -> normalize -> `render_x(data, now=None) -> Image`.
2. Build it from `app.style` only. Pick a hero first, then supporting panels (at most three).
3. Add demo data for every state (normal, live, stale, empty) in a `preview_x.py`.
4. Add the page and its states to `PAGES` in `tests/test_pages_conform.py`. Run `python -m pytest`.
5. Look at the previews.

## Known gaps

- The Celtics page is rendered and sent as a full refresh on each rotation; the bus screen's partial-update and
  per-card diff behavior (principle 4) is documented here but not yet implemented in a shared display layer.
- The bus app itself still uses its own sizes and five grays. Porting it is tracked in the audit (section 5).
- Header clock: pages show "Updated <time>"; a live ticking clock is a bus-screen feature.
