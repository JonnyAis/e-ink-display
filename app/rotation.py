"""Rotate full-screen sports pages in between stretches of the bus screen.

The bus screen is home. Every `bus_s` seconds the main loop asks `rotation.due()`; if it is, `rotation.run(...)`
shows the next ready sports page for its own `show_s` seconds and then hands the screen back via the loop's own
restore function. While any page reports a live game the bus stretch shrinks to `live_bus_s`, so scores come
round more often during a game.

Pages fetch and render in a background thread (`start_worker`), so a slow or failing ESPN request can never stall
the bus loop. A page with nothing worth showing (render returns None, or it has failed every time) is skipped;
the bus screen is never interrupted by an empty or error page.

This module does no hardware I/O and never sleeps on its own; `run` takes `show`, `restore` and `sleep`
callables, which keeps it testable. Settings come from config.toml's [rotation] section (see `from_config`).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image

log = logging.getLogger(__name__)


@dataclass
class Page:
    """One rotating page. `build(size)` fetches and renders: returns (image or None, is_live)."""
    name: str
    build: Callable[[tuple], tuple]
    show_s: float = 15.0
    img: Optional[Image.Image] = field(default=None, repr=False)
    live: bool = False
    updated: Optional[float] = None

    def refresh(self, size, clock=time.monotonic):
        try:
            img, live = self.build(size)
        except Exception as e:   # keep the last good frame; a failed fetch is not a reason to go blank
            log.warning("%s refresh failed: %s", self.name, e)
            return
        self.img, self.live, self.updated = img, bool(live) and img is not None, clock()


class Rotation:
    def __init__(self, pages, bus_s=120.0, live_bus_s=45.0, clock=time.monotonic):
        if not pages:
            raise ValueError("a rotation needs at least one page")
        if min(bus_s, live_bus_s) <= max(p.show_s for p in pages):
            raise ValueError("the bus screen must stay up longer than a sports page (it is the home screen)")
        self.pages = list(pages)
        self.bus_s, self.live_bus_s = float(bus_s), float(live_bus_s)
        self.clock = clock
        self._i = 0
        self._last_return = clock()   # the bus screen always comes first

    @property
    def live(self) -> bool:
        return any(p.live for p in self.pages)

    def gap(self) -> float:
        return self.live_bus_s if self.live else self.bus_s

    def _next_ready(self) -> Optional[Page]:
        n = len(self.pages)
        for k in range(n):
            p = self.pages[(self._i + k) % n]
            if p.img is not None:
                self._i = (self._i + k + 1) % n
                return p
        return None

    def due(self) -> bool:
        return self.clock() - self._last_return >= self.gap() and any(p.img is not None for p in self.pages)

    def run(self, show: Callable[[Image.Image], None], restore: Callable[[], None],
            sleep: Callable[[float], None] = time.sleep) -> Optional[str]:
        """Show the next ready page for its show_s, then always restore the bus screen. Returns the page name shown."""
        page = self._next_ready()
        if page is None:
            return None
        try:
            show(page.img)
            sleep(page.show_s)
        finally:
            try:
                restore()
            finally:
                self._last_return = self.clock()   # the bus gets a full stretch after every page
        return page.name

    def refresh_all(self, size):
        for p in self.pages:
            p.refresh(size, self.clock)

    def start_worker(self, size, every_s=120.0, live_every_s=30.0):
        """Refresh every page in a daemon thread; faster while a game is live."""
        def loop():
            while True:
                self.refresh_all(size)
                time.sleep(live_every_s if self.live else every_s)
        t = threading.Thread(target=loop, name="sports-rotation", daemon=True)
        t.start()
        return t


# ---------- the real pages ----------

def team_page(show_s=15.0) -> Page:
    from app.pages.team import fetch_team, has_live_game, render_team

    def build(size):
        data = fetch_team()
        return render_team(data, size), has_live_game(data)
    return Page("team", build, show_s)


def scores_page(leagues=("NFL", "NHL"), favorites=(), max_games=4, show_s=15.0) -> Page:
    """Today's games in `leagues`, favorites first. Skipped when there are no games."""
    from datetime import datetime
    from app.pages.sports import render_sports_page
    from app.services.sports_data import fetch_games, load_cache, save_cache

    fav = {f.upper() for f in favorites}

    def build(size):
        try:
            games = fetch_games(leagues, favorites)
            save_cache(games)
            stale_min = 0
        except Exception:
            games, age = load_cache()
            if games is None:
                raise
            stale_min = int(age // 60)
        games = games[:max_games]
        if not games:
            return None, False
        live = any(g["state"] == "live" and {g["away"], g["home"]} & fav for g in games)
        stamp = datetime.now().strftime("%I:%M %p").lstrip("0")
        img = render_sports_page(games, stamp, stale=stale_min >= 10, stale_minutes=stale_min, size=size)
        return img, live
    return Page("scores", build, show_s)


def from_config(clock=time.monotonic) -> Rotation:
    """Build the rotation from config.toml's [rotation] section (defaults in config.example.toml)."""
    from app import config

    def num(key, default):
        try:
            return float(config.get(f"rotation.{key}", default))
        except (TypeError, ValueError):
            return default

    def names(key, default):
        return tuple(str(v).strip().upper() for v in (config.get(f"rotation.{key}", default) or ()) if str(v).strip())

    makers = {
        "TEAM": lambda: team_page(num("team_secs", 15)),
        "CELTICS": lambda: team_page(num("team_secs", 15)),   # old name
        "SCORES": lambda: scores_page(names("leagues", ("NFL", "NHL")), names("favorites", ()),
                                      show_s=num("scores_secs", 15)),
    }
    pages = [makers[n]() for n in names("pages", ("team",)) if n in makers]
    return Rotation(pages, bus_s=num("bus_secs", 120), live_bus_s=num("live_bus_secs", 45), clock=clock)
