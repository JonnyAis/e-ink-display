"""Render the sports page with fixture data: python -m app.preview_sports"""
from pathlib import Path

from app.pages.sports import render_sports_page

GAMES = [
    {"away": "SEA", "home": "SF", "away_score": 17, "home_score": 14, "status": "Q3 06:21", "state": "live"},
    {"away": "NY", "home": "BOS", "away_score": 3, "home_score": 5, "status": "Final", "state": "final"},
    {"away": "LA", "home": "CHI", "away_score": 2, "home_score": 2, "status": "2nd period", "state": "live"},
    {"away": "DEN", "home": "PHX", "away_score": None, "home_score": None, "status": "Today 7:30 PM", "state": "scheduled"},
]

if __name__ == "__main__":
    Path("preview").mkdir(exist_ok=True)
    img = render_sports_page(GAMES, "8:14 PM")
    assert img.size == (1872, 1404), img.size
    img.save("preview/sports.png")
    print("wrote preview/sports.png", img.size)
