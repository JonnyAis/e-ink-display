# Bus Departures: experience audit (DRAFT)

Source: `app/main.py` (998 lines) and `app/predictor/pace.py` from the original transit display, plus a render of the
real `render_nav_complete` / `render_card_column` functions with fixture data (1872x1404). This is the baseline the
style guide will be extracted from. Findings marked **verify** come from reading code and should be checked on the device.

The reference render contains the King County Metro logo, so it is kept locally (`bus_reference.png`) and is not in this repo.

## 1. What the experience is

One screen answers one question: *when does my bus get here, and do I need to leave now?*

| Zone | Content |
|---|---|
| Header bar (black, 200 px) | Logo, title "Departures", date (2 lines), time with small AM/PM, thin vertical divider |
| Two columns | "Next Bus Downtown (South)" and "Next Bus Uptown (North)" (titles come from `config.toml`); up to 5 cards each |
| Card | Route badge, label ("Predicted"/"Scheduled Arrival"), time, stops away, headsign, status message |
| Header badge slot | Appears only on trouble: `STALE 3m`, `RATE LIMIT` |

Why it works: **one hero (the next bus), a fixed grid, big type, and words instead of icons** ("GO TO BUS STOP!",
"BUS DEPARTED"). It reads from across a room, and the status tells you what to do, not just what the data says.

## 2. Visual tokens (measured from code)

**Canvas:** 1872x1404, `L` mode. Right safe margin 24 px. Padding 28 px, column gap 28 px, header 200 px.

**Type scale (Marsden, role -> size px):**

| Role | Size | Used for |
|---|---|---|
| TITLE | 122 (68 x 1.2 x 1.2 x 1.25) | "Departures" |
| TIME | 82 (66 x 1.25) | Clock |
| H2 | 53 | Column titles, route number in badge |
| NUM | 50 | Time and stops on the *urgent* card |
| BODY | 45 | Time, stops, status message |
| MER | 45 | AM/PM |
| DATE | 37 | Date lines |
| SM | 35 | Labels, headsign, header badge |

Eight roles; several are derived from multiplied constants, so the real values are not obvious from the source.

**Grays used:** 0 (ink), 100, 120, 140, 160, 200, 255 (paper). There are five mid-grays doing three jobs:
secondary label (120), departed content (140 / 100 / 160), dividers and departed badge fill (200).
The style guide should collapse them into three named grays.

**Card geometry:** card height 160, badge 115 (corner radius = size/4), horizontal gap 23, 5 cards per column,
vertical pitch 210 (160 + 50).

**Header:** black bar, white text. Date is right-aligned against a 2 px divider, the time sits to its right.
The header is the only large black area; everything below is black on white.

## 3. Behavior (the part that makes it feel right)

1. **Per-card state:** `normal`, `urgent`, `departed`, `hidden`. A per-vehicle state machine
   (approach -> at_stop -> departed) uses hysteresis: 2 consecutive polls or ETA <= 15 s or <= 35 m before "at stop";
   20 s grace before "departed"; a bus that vanishes 15 s after arrival is marked departed; forgotten after 180 s.
   Departed cards stay visible but muted for about 30 s, then disappear.
2. **Urgency:** the *first* bus within 3 min (downtown) or 5 min (uptown), or any bus in `at_stop`, shows
   "GO TO BUS STOP!". The message blinks once a second via a tiny partial update. The card itself barely changes
   (NUM vs BODY is 50 vs 45 px), so urgency lives almost entirely in that message.
3. **Calm updates:** only changed cards are redrawn (GL16); the clock is a separate A2 patch; a full GC16 scrub
   happens every 30 minutes, with a column re-draw after 10 card updates to fight ghosting.
4. **Adaptive polling:** every 10 s when a bus is within 2 min, 30 s normally, 60 s when everything is far; jitter of
   +/- 2 s; exponential backoff to 10 min on errors; honours `Retry-After` on HTTP 429.
5. **Honest data:** on error, the last screen stays and a `STALE <n>m` or `RATE LIMIT` badge appears in the header;
   it clears itself on the next good poll. "Predicted" vs "Scheduled" is labelled on every card.
6. **Stable numbers:** `predictor/pace.py` fuses the API ETA with learned pace and kinematics (EMA 0.2, API weight
   0.25 to 0.85), so ETAs don't jump. Stops-away is shown minus 1 to compensate for API delay.
7. **Truncation:** headsigns are cut at 18 characters with an ellipsis.

## 4. State screens

| State | Today |
|---|---|
| Boot | Double white wipe, then header, then columns fill on first poll |
| Normal | as above |
| Fetch error | Stale badge in header; content unchanged |
| No buses | Column title only; the column is empty (no message) |
| Setup / no Wi-Fi | Separate welcome screen with QR code (mode `1`, own font sizing) |

## 5. Findings: places the bus screen departs from its own best ideas

These are small, and the design is strong enough that they stand out. They matter for the guide because the guide
should codify the intent, not the accidents.

1. **Per-card update windows don't match the card layout (verify).** Cards are drawn 210 px apart, but the
   update-diff boxes use 172 px (`CARD_H + GAP_V`). Cards 4 and 5, and the lower part of 3, fall outside the diff
   windows, so their changes would only appear at the next 10-update column scrub or the 30-min full refresh.
2. **The clock is redrawn every second.** The whole 1848x200 header is rendered and sent each tick in A2, though
   the displayed time only changes once a minute. That is avoidable flashing and SPI traffic.
3. **Warm-start cache is written but never read.** `save_cache_data` runs every poll; `load_cache_data` is defined
   but not called, so a restart shows empty columns until the first poll succeeds.
4. **Urgent card is nearly identical to normal.** Only the message and a 5 px font change. There is room for a
   clearer, still e-ink-friendly signal (e.g. a heavier border or inverted badge) without color.
5. **Headsign sits tight under the time** (title text at y+90 against a 50 px time baseline) and almost touches it
   in the render.
6. **Five near-identical grays** (100/120/140/160/200); contrast between "secondary" and "departed" is subtle on e-ink.
7. **Empty states are silent.** If there are no buses, the column is blank, which is indistinguishable from a
   frozen display.
8. **Dead and contradictory code:** a comment says blinking is disabled while a blink path is active; unused
   `status_msg_boxes` padding variables; a fixed `CARD_H + 50` pitch duplicated in two places.
9. **Stale data is only flagged in the header badge.** Cards themselves don't dim, and a stale "GO TO BUS STOP!"
   can stay on screen with no extra warning.
10. **Welcome screen has its own sizing system** (percentages of width, mode `1`), unrelated to the main screen's scale.

## 6. Principles to extract (candidates for the style guide)

1. One question per screen; one hero element.
2. Words over icons; the status says what to do.
3. Fixed grid; nothing moves unless data changes.
4. Update only what changed; scrub on a timer.
5. Always show data age and source quality (predicted vs scheduled, stale).
6. Smooth numbers; never let them jump.
7. Define every state, including empty, stale, error, offline and setup.
8. At most three gray levels beyond black and white; reserve pure black/white for A2 regions.
9. Interludes (other pages) are short and always return to the primary screen.

## 7. How the Celtics page compares

| Principle | Bus | Celtics, before | Celtics, now |
|---|---|---|---|
| One hero | Next bus | None; three equal panels | Next game (or live score) |
| Words that say what to do | Yes | No | "LIVE", "Today", "Tomorrow" |
| Data age shown | Yes | No | "Updated" time and STALE pill |
| Empty / error state | Partial | Message screen | Defined for each missing part |
| Shared header | Yes | No | Yes (`style.header`) |
| Type scale | 8 roles (35 px minimum) | Ad hoc sizes (26 px minimum) | 6 roles (44 px minimum) |
| Grays | 5, messy | A few, unrelated | 3 named |
| Partial updates | Yes | No | Not yet (known gap) |

## 8. Status

Principles approved. Built: `app/style.py`, the Celtics and scoreboard pages ported to it, tests that enforce it
(`docs/STYLE_GUIDE.md`). Not done: porting the bus app (section 5 lists its findings), a shared partial-update display
layer, and deploying the new Celtics page to the device.
