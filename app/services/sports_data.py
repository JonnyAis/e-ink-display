"""ESPN scoreboard fetch + normalization (unofficial, undocumented public JSON; may change).

Normalized game dict (consumed by app.pages.sports.render_sports_page):
  {"away","home": str abbreviations, "away_score","home_score": int|None,
   "status": str, "state": "live"|"final"|"scheduled", "league": str, "start": ISO str}
"""
import json
import logging
import os
import time
from pathlib import Path

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
LEAGUES = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
    "NHL": "hockey/nhl",
    "MLB": "baseball/mlb",
    "MLS": "soccer/usa.1",
}
CACHE_FILE = Path(os.environ.get("SPORTS_CACHE", "sports_cache.json"))
_STATE = {"in": "live", "post": "final", "pre": "scheduled"}


def _score(c):
    try:
        return int(c.get("score"))
    except (TypeError, ValueError):
        return None


def normalize_scoreboard(payload, league=""):
    games = []
    for ev in payload.get("events", []):
        try:
            comp = ev["competitions"][0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            home, away = sides["home"], sides["away"]
            st = ev["status"]["type"]
            state = _STATE.get(st.get("state"), "scheduled")
            games.append({
                "away": away["team"].get("abbreviation", "?"),
                "home": home["team"].get("abbreviation", "?"),
                "away_score": _score(away) if state != "scheduled" else None,
                "home_score": _score(home) if state != "scheduled" else None,
                "status": st.get("shortDetail") or st.get("description", ""),
                "state": state,
                "league": league,
                "start": ev.get("date", ""),
            })
        except (KeyError, IndexError, TypeError) as e:
            logging.warning("skipping malformed ESPN event: %s", e)
    return games


def sort_games(games, favorites=()):
    """Favorites first, then live, scheduled (by start), final."""
    order = {"live": 0, "scheduled": 1, "final": 2}
    fav = {f.upper() for f in favorites}
    return sorted(games, key=lambda g: (
        0 if {g["away"], g["home"]} & fav else 1, order[g["state"]], g["start"]))


def fetch_games(leagues=("NBA",), favorites=(), timeout=(3, 10)):
    """Fetch and merge scoreboards. Raises if every league fails."""
    out, errors = [], 0
    for lg in leagues:
        try:
            r = requests.get(BASE.format(path=LEAGUES[lg]), timeout=timeout)
            r.raise_for_status()
            out += normalize_scoreboard(r.json(), lg)
        except Exception as e:
            errors += 1
            logging.error("ESPN %s failed: %s", lg, e)
    if errors == len(leagues):
        raise RuntimeError("all ESPN requests failed")
    return sort_games(out, favorites)


def save_cache(games):
    CACHE_FILE.write_text(json.dumps({"t": time.time(), "games": games}))


def load_cache():
    """Return (games, age_seconds) or (None, None)."""
    try:
        d = json.loads(CACHE_FILE.read_text())
        return d["games"], time.time() - d["t"]
    except (OSError, ValueError, KeyError):
        return None, None
