"""Render the scores pages (one per league) with fixture data: python -m app.preview_sports"""
from pathlib import Path

from app.pages.sports import render_sports_page

GAMES = [
    {"away": "SEA", "home": "SF", "away_score": 17, "home_score": 14, "status": "Q3 06:21", "state": "live"},
    {"away": "NYG", "home": "DAL", "away_score": 23, "home_score": 27, "status": "Final", "state": "final"},
    {"away": "KC", "home": "DEN", "away_score": 10, "home_score": 10, "status": "Halftime", "state": "live"},
    {"away": "LAR", "home": "ARI", "away_score": None, "home_score": None, "status": "Sun 1:05 PM", "state": "scheduled"},
]

# One page per league; the title is the league name. The long title checks the header still fits.
LEAGUES = {
    "nfl": ("NFL", GAMES),
    "epl": ("Premier League", [
        {"away": "ARS", "home": "LIV", "away_score": 1, "home_score": 1, "status": "67'", "state": "live"},
        {"away": "CHE", "home": "MCI", "away_score": 0, "home_score": 2, "status": "FT", "state": "final"},
    ]),
    "ucl": ("Champions League", [
        {"away": "RMA", "home": "BAY", "away_score": None, "home_score": None, "status": "Sat 7:00 PM",
         "state": "scheduled"},
    ]),
}

if __name__ == "__main__":
    Path("preview").mkdir(exist_ok=True)
    for key, (title, games) in LEAGUES.items():
        img = render_sports_page(games, "8:14 PM", title=title)
        assert img.size == (1872, 1404), img.size
        img.save(f"preview/sports_{key}.png")
        print(f"wrote preview/sports_{key}.png")
    render_sports_page(GAMES, "8:14 PM", stale=True, stale_minutes=12, title="NFL").save("preview/sports_stale.png")
    render_sports_page([], "8:14 PM", title="NHL").save("preview/sports_empty.png")
    print("wrote preview/sports_stale.png, preview/sports_empty.png")
