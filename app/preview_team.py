"""Demo data + previews for the team page (no network): python -m app.preview_team

Writes preview/team_<variant>.png for each state the page must handle. The demo team is fixed here (not read
from your config) so previews and tests look the same on every machine.
tests/test_pages_conform.py renders the same variants and checks them against the style rules.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path

from app.pages.team import render_team

NOW = datetime(2026, 11, 6, 20, 14, tzinfo=timezone.utc).astimezone()


def _g(date, opp, name, home, state="pre", mine=None, theirs=None, won=None, detail="", gid=None):
    return {"id": gid, "date": date, "state": state, "detail": detail, "home": home, "opp": opp,
            "opp_name": name, "my_score": mine, "opp_score": theirs, "won": won}


STANDINGS = [
    {"abbr": a, "record": r, "seed": i + 1, "gb": gb, "streak": "", "l10": ""}
    for i, (a, r, gb) in enumerate([
        ("CLE", "12-2", "-"), ("NYK", "10-4", "2"), ("BOS", "9-5", "3"), ("ORL", "9-6", "3.5"),
        ("MIL", "8-6", "4"), ("DET", "8-7", "4.5"), ("ATL", "7-7", "5"), ("MIA", "7-8", "5.5"),
        ("TOR", "6-9", "6.5"), ("CHI", "6-9", "6.5"), ("PHI", "5-9", "7"), ("IND", "5-10", "7.5"),
    ])
]

DEMO_TEAM = {"id": "2", "abbr": "BOS", "name": "Celtics", "conference": "East"}

DEMO = {
    "fetched": NOW.isoformat(),
    "team": DEMO_TEAM,
    "live": [],
    "recent": [
        _g("2026-11-04T00:30Z", "MIA", "Heat", True, "post", "112", "101", True, gid="1"),
        _g("2026-11-02T00:00Z", "NYK", "Knicks", False, "post", "98", "104", False),
        _g("2026-10-30T23:30Z", "CHI", "Bulls", True, "post", "121", "99", True),
        _g("2026-10-28T23:30Z", "DET", "Pistons", False, "post", "105", "108", False),
    ],
    "upcoming": [
        _g("2026-11-07T00:30Z", "ORL", "Magic", False),
        _g("2026-11-09T00:00Z", "ATL", "Hawks", True),
        _g("2026-11-11T00:30Z", "TOR", "Raptors", True),
        _g("2026-11-13T00:30Z", "PHI", "76ers", False),
        _g("2026-11-15T00:00Z", "CLE", "Cavaliers", True),
    ],
    "standings": STANDINGS,
    "box": {
        "team": {"fg_pct": "48.3", "3p_pct": "37.1", "ft_pct": "80.0", "reb": "44", "ast": "25", "tov": "11"},
        "top": [
            {"name": "J. Tatum", "pts": 31, "reb": "9", "ast": "6", "min": "36"},
            {"name": "J. Brown", "pts": 24, "reb": "5", "ast": "4", "min": "34"},
            {"name": "D. White", "pts": 15, "reb": "4", "ast": "5", "min": "32"},
        ],
    },
}


def variants():
    live = copy.deepcopy(DEMO)
    live["live"] = [_g("2026-11-06T23:30Z", "ORL", "Magic", False, "in", "54", "51", detail="Q3 6:21")]
    live["upcoming"] = live["upcoming"][1:]
    noscore = copy.deepcopy(live)   # ESPN's schedule endpoint has no live scores; the page must not print "None"
    noscore["live"][0].update({"my_score": None, "opp_score": None})
    stale = copy.deepcopy(DEMO)
    stale["stale"] = True
    stale["fetched"] = datetime(2026, 11, 6, 19, 50, tzinfo=timezone.utc).astimezone().isoformat()
    empty = copy.deepcopy(DEMO)
    empty.update({"upcoming": [], "recent": [], "box": None, "standings": []})
    nobox = copy.deepcopy(DEMO)
    nobox["box"] = None
    outside = copy.deepcopy(DEMO)   # your team outside the top 10 must still appear
    for r in outside["standings"]:
        r["seed"] = {"BOS": 12, "IND": 3}.get(r["abbr"], r["seed"] + (1 if r["seed"] in (3,) else 0))
    outside["standings"].sort(key=lambda r: r["seed"])
    return {"normal": DEMO, "live": live, "live_no_score": noscore, "stale": stale, "empty": empty, "no_box_score": nobox,
            "my_team_outside_top10": outside}


if __name__ == "__main__":
    out = Path("preview")
    out.mkdir(exist_ok=True)
    for name, data in variants().items():
        img = render_team(data, now=NOW)
        img.save(out / f"team_{name}.png")
        print("wrote", out / f"team_{name}.png", img.size)
