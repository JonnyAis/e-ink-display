import json
from pathlib import Path

from app.pages.team import parse_boxscore

FIX = Path(__file__).parent / "fixtures"


def test_boxscore_from_real_summary():
    box = parse_boxscore(json.loads((FIX / "espn_bos_summary.json").read_text()), team_id="2")
    assert box and len(box["top"]) == 3
    pts = [p["pts"] for p in box["top"]]
    assert pts == sorted(pts, reverse=True)
    assert box["team"]["reb"] and box["team"]["fg_pct"]


def test_boxscore_missing_returns_none():
    assert parse_boxscore({}) is None
    assert parse_boxscore({"boxscore": {"teams": [], "players": []}}) is None


def test_live_scores_come_from_the_scoreboard():
    from app.pages.team import apply_live_scores
    games = [
        {"id": "1", "state": "in", "my_score": None, "opp_score": None, "detail": ""},
        {"id": "2", "state": "pre", "my_score": None, "opp_score": None, "detail": ""},
    ]
    board = {"events": [{
        "id": "1", "status": {"type": {"shortDetail": "4:12 - 4th"}},
        "competitions": [{"competitors": [
            {"team": {"id": "30"}, "score": "67"}, {"team": {"id": "2"}, "score": "112"}]}],
    }]}
    apply_live_scores(games, board, team_id="2")
    assert (games[0]["my_score"], games[0]["opp_score"], games[0]["detail"]) == ("112", "67", "4:12 - 4th")
    assert games[1]["my_score"] is None            # only live games are touched


def test_live_score_overlay_tolerates_missing_game():
    from app.pages.team import apply_live_scores
    games = [{"id": "9", "state": "in", "my_score": None, "opp_score": None, "detail": "Q1"}]
    apply_live_scores(games, {"events": []}, team_id="2")
    assert games[0]["my_score"] is None and games[0]["detail"] == "Q1"
