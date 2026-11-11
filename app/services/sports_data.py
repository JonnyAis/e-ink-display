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

# Short names for common ESPN scoreboards: short name -> (ESPN "sport/league" path, page title).
# Any other ESPN head-to-head scoreboard works too: put its path in config, e.g. "soccer/ned.1" or "rugby/164205".
# Find a path in the URL of the league's page on espn.com or in the ESPN API (site.api.espn.com/apis/site/v2/sports/).
# Golf, racing and tennis scoreboards are not head-to-head games and are not supported.
LEAGUES = {
    "NFL": ("football/nfl", "NFL"),
    "NCAAF": ("football/college-football", "College Football"),
    "CFL": ("football/cfl", "CFL"),
    "NBA": ("basketball/nba", "NBA"),
    "WNBA": ("basketball/wnba", "WNBA"),
    "NCAAM": ("basketball/mens-college-basketball", "NCAA Men's"),
    "NCAAW": ("basketball/womens-college-basketball", "NCAA Women's"),
    "NHL": ("hockey/nhl", "NHL"),
    "MLB": ("baseball/mlb", "MLB"),
    "MLS": ("soccer/usa.1", "MLS"),
    "NWSL": ("soccer/usa.nwsl", "NWSL"),
    "EPL": ("soccer/eng.1", "Premier League"),
    "LALIGA": ("soccer/esp.1", "La Liga"),
    "BUNDESLIGA": ("soccer/ger.1", "Bundesliga"),
    "SERIEA": ("soccer/ita.1", "Serie A"),
    "LIGUE1": ("soccer/fra.1", "Ligue 1"),
    "UCL": ("soccer/uefa.champions", "Champions League"),
}


def resolve_league(name):
    """Short name ("NBA") or ESPN path ("soccer/ned.1") -> (path, title). Raises ValueError if neither."""
    key = str(name).strip()
    if key.upper() in LEAGUES:
        return LEAGUES[key.upper()]
    if key.count("/") == 1 and all(part.strip() for part in key.split("/")):
        path = key.lower()
        return path, path.split("/")[1].upper()
    raise ValueError(f"unknown league {name!r}: use one of {', '.join(LEAGUES)} or an ESPN path like 'soccer/ned.1'")


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
    """Fetch and merge scoreboards (short names or ESPN paths). Raises if every league fails."""
    out, errors = [], 0
    for lg in leagues:
        try:
            r = requests.get(BASE.format(path=resolve_league(lg)[0]), timeout=timeout)
            r.raise_for_status()
            out += normalize_scoreboard(r.json(), lg)
        except Exception as e:
            errors += 1
            logging.error("ESPN %s failed: %s", lg, e)
    if errors == len(leagues):
        raise RuntimeError("all ESPN requests failed")
    return sort_games(out, favorites)


def _cache_file(key):
    if not key:
        return CACHE_FILE
    safe = "".join(c if c.isalnum() else "_" for c in str(key).lower())
    return CACHE_FILE.with_name(f"{CACHE_FILE.stem}_{safe}{CACHE_FILE.suffix}")


def save_cache(games, key=""):
    """Remember the last good games; `key` keeps one cache per page (e.g. the league)."""
    _cache_file(key).write_text(json.dumps({"t": time.time(), "games": games}))


def load_cache(key=""):
    """Return (games, age_seconds) or (None, None)."""
    try:
        d = json.loads(_cache_file(key).read_text())
        return d["games"], time.time() - d["t"]
    except (OSError, ValueError, KeyError):
        return None, None
