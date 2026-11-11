import json
from pathlib import Path

import pytest

from app.services.sports_data import LEAGUES, normalize_scoreboard, resolve_league, sort_games

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


def test_leagues_by_short_name_or_espn_path():
    assert resolve_league("nba") == ("basketball/nba", "NBA")
    assert resolve_league("EPL") == ("soccer/eng.1", "Premier League")
    assert resolve_league("Soccer/NED.1") == ("soccer/ned.1", "NED.1")
    for bad in ("", "curling", "a/b/c", "/nba"):
        with pytest.raises(ValueError):
            resolve_league(bad)
    assert all(path.count("/") == 1 for path, _ in LEAGUES.values())


def test_caches_are_kept_per_league(monkeypatch, tmp_path):
    from app.services import sports_data
    monkeypatch.setattr(sports_data, "CACHE_FILE", tmp_path / "c.json")
    sports_data.save_cache([{"away": "A"}], "football/nfl")
    sports_data.save_cache([{"away": "B"}], "hockey/nhl")
    assert sports_data.load_cache("football/nfl")[0] == [{"away": "A"}]
    assert sports_data.load_cache("hockey/nhl")[0] == [{"away": "B"}]
    assert sports_data.load_cache("soccer/eng.1") == (None, None)


def test_league_titles_fit_beside_the_stale_tag_and_clock():
    from PIL import Image, ImageDraw
    from app import style
    d = ImageDraw.Draw(Image.new("L", (10, 10)))
    for _, title in LEAGUES.values():
        assert style.text_width(d, title, "TITLE") < 1100, title
