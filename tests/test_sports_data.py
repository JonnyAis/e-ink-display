import json
from pathlib import Path

import pytest

from app.services.sports_data import normalize_scoreboard, sort_games

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name,league", [
    ("espn_basketball_nba.json", "NBA"), ("espn_football_nfl.json", "NFL"), ("espn_hockey_nhl.json", "NHL")])
def test_real_payloads_normalize(name, league):
    payload = json.loads((FIX / name).read_text())
    games = normalize_scoreboard(payload, league)
    assert len(games) == len(payload["events"])
    for g in games:
        assert g["state"] in ("live", "final", "scheduled")
        assert g["away"] and g["home"]
        if g["state"] == "scheduled":
            assert g["away_score"] is None
        else:
            assert isinstance(g["away_score"], int) and isinstance(g["home_score"], int)


def test_malformed_event_skipped():
    assert normalize_scoreboard({"events": [{"bad": 1}]}) == []
    assert normalize_scoreboard({}) == []


def test_sort_favorites_then_live_first():
    g = lambda a, h, s: {"away": a, "home": h, "state": s, "start": "2026-01-01"}
    out = sort_games([g("A", "B", "final"), g("C", "D", "live"), g("SEA", "X", "final")], favorites=["sea"])
    assert [x["away"] for x in out] == ["SEA", "C", "A"]
