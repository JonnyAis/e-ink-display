# Rotating a page into an existing display loop

Existing loops usually update the panel incrementally (partial refreshes). To show another full-screen page
periodically, add an *interlude*: fetch/render in a background thread, show the page with a full refresh, then
restore your normal screen using whatever full-redraw sequence your loop already has.

```python
import threading
PAGE_SECONDS, MAIN_SECONDS, REFRESH_SECS = 5, 25, 300
_page = {"img": None}

def _worker(size):                      # never block the main loop on the network
    while True:
        try:
            _page["img"] = render_team(fetch_team(), size)   # from app.pages.team
        except Exception as e:
            logging.warning("page refresh failed: %s", e)
        time.sleep(REFRESH_SECS)

# once, after you know the panel size (W, H):
threading.Thread(target=_worker, args=((W, H),), daemon=True).start()
next_page = time.monotonic() + MAIN_SECONDS

# inside the main loop, before the pacing sleep:
if _page["img"] is not None and time.monotonic() >= next_page:
    try:
        draw_full(display, _page["img"])
        time.sleep(PAGE_SECONDS)
        restore_main_screen()           # your existing full-redraw + partial repaint
    except Exception as e:
        logging.error("interlude failed: %s", e)
    next_page = time.monotonic() + MAIN_SECONDS
```

Notes: a full e-ink refresh takes about 2-3 s, so a 5 s page is visible for roughly half that. Partial-update
overlays (badges, status text) are gone after a full redraw; re-draw them if you need them.
Inspect your driver's real `draw_full`/`draw_partial` signatures first; never assume `EPD.display()` exists.

## The sports rotation (wired in)

The bus screen lives in the repo (`app/main.py`, copied from the Pi) and rotates sports pages in using
`app/rotation.py`. The bus screen is home: every 2 minutes one sports page shows for 15 s, then the bus screen is
fully redrawn. By default only the team page rotates in; add "scores" to `[rotation] pages` for the scoreboard
too (pages then alternate). While a game is live the bus stretch drops to 45 s.
Pages refresh in a background thread (every 2 min, every 30 s during a live game); a page with no games or no data
yet is skipped, so the bus screen is never interrupted by an empty page.

Settings live in `config.toml` under `[rotation]` (defaults and comments in `config.example.toml`): `pages`,
`bus_secs`, `live_bus_secs`, `team_secs`, `scores_secs`, `leagues`, `favorites`. The bus screen reads its two stop
IDs and column titles from `[bus] stops` / `titles`; it exits with a message if the stops are not set.

The Marsden fonts and transit logo stay on the Pi in `~/transit-display/assets/` (licensed; not in git).

## Greetings (wired in)
`app/main.py` builds `greetings.from_config()` at start-up and, on each tick before the sports rotation check,
runs at most one due greeting: its frames go out with `draw_full_a2` (pure black/white, well under a second each),
then `restore_bus` does the usual full GC16 redraw. A full GC16 refresh takes 2-3 s, which is why greetings use A2:
with GC16 a 2 s greeting would barely appear. Each showing still costs one A2 push plus one full restore.

Adding a style: create `app/greetings/<style>.py` with a function decorated `@style("<style>")` that returns
`[(image, hold_seconds), ...]`, add the module name to `STYLE_MODULES` in `app/greetings/__init__.py`, and run
`python -m app.preview_greetings`. Tests pick up every registered style automatically.
