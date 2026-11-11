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
fully redrawn. By default only the team page rotates in; add "scores" to `[rotation] pages` for scoreboards too
(pages then take turns). While a favorite's game is live the bus stretch drops to 45 s.

Scoreboards are one page per league, titled with the league's name, so sports never mix on one screen. `leagues`
takes short names (`NFL`, `NBA`, `EPL`, ... listed in `config.example.toml` and `LEAGUES` in
`app/services/sports_data.py`) or any ESPN scoreboard path, `"<sport>/<league>"`: the part of
`site.api.espn.com/apis/site/v2/sports/<sport>/<league>/scoreboard` for that league, e.g. `"soccer/ned.1"`.
Only head-to-head sports work (golf, racing and tennis scoreboards have a different shape). Place a single league
in the order you like with `"scores:<league>"` in `pages`. `favorites` puts those teams first on every scores page;
`only_favorites = true` hides other games and skips a league whose favorites aren't playing.
Pages refresh in a background thread (every 2 min, every 30 s during a live game); a page with no games or no data
yet is skipped, so the bus screen is never interrupted by an empty page.

Settings live in `config.toml` under `[rotation]` (defaults and comments in `config.example.toml`): `pages`,
`bus_secs`, `live_bus_secs`, `team_secs`, `scores_secs`, `leagues`, `favorites`, `only_favorites`. The bus screen reads its two stop
IDs and column titles from `[bus] stops` / `titles`; it exits with a message if the stops are not set.

The Marsden fonts and transit logo stay on the Pi in `~/transit-display/assets/` (licensed; not in git).
