"""Greetings: short, opt-in full-screen moments ("hello, <name>") that visit the bus screen and always leave.

A greeting is a *style* (how it looks) plus a schedule (how often, how long). Styles live in this package, one
module each, and register themselves with `@style("name")`. A style function is

    render(name: str, size: (w, h), show_s: float) -> [(image, hold_seconds), ...]

returning one or more frames, pure black/white (they are pushed with the fast A2 mode), whose holds add up to
roughly show_s. Use `app.style.interlude_screen()` to draw them.

Nothing is shown unless config.toml lists it (see docs/CONFIG.md):

    [[greetings]]
    name = "..."          # empty -> a plain "hello"
    style = "spooky"      # any registered style
    every_secs = 60
    show_secs = 2

The names live only in your config.toml, never in the repo. Like app/rotation.py, this module does no hardware
I/O and never sleeps on its own: `Greeting.run` takes `show`, `restore` and `sleep` callables.
"""
from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PIL import Image

from app import style as _style

log = logging.getLogger(__name__)

Frames = list  # [(PIL.Image, hold_seconds), ...]
STYLES: dict[str, Callable] = {}

# Style modules in this package. Add yours here (one line) so it registers on import.
STYLE_MODULES = ("spooky",)


def style(name: str):
    """Register a greeting style: `@style("spooky") def render(name, size, show_s): ...`."""
    def deco(fn):
        STYLES[name] = fn
        return fn
    return deco


def _load_styles():
    for mod in STYLE_MODULES:
        importlib.import_module(f"{__name__}.{mod}")


def render(style_name: str, name: str, size=_style.PANEL, show_s: float = 2.0) -> Frames:
    _load_styles()
    frames = STYLES[style_name]((name or "").strip(), size, show_s)
    if not frames:
        raise ValueError(f"greeting style {style_name!r} returned no frames")
    return frames


@dataclass
class Greeting:
    """Show a greeting every `every_s` seconds for about `show_s` seconds, then hand the screen back.

    The first showing is one full interval after start, so the bus screen always comes first.
    """
    name: str = ""
    style: str = "spooky"
    every_s: float = 60.0
    show_s: float = 2.0
    size: tuple = _style.PANEL
    clock: Callable[[], float] = time.monotonic
    _next: float = field(default=0.0, init=False, repr=False)
    _frames: Optional[Frames] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        _load_styles()
        if self.style not in STYLES:
            raise ValueError(f"unknown greeting style {self.style!r}; known: {sorted(STYLES)}")
        if not 0 < self.show_s < self.every_s:
            raise ValueError("a greeting must be shorter than its interval (it must never starve the bus screen)")
        self._next = self.clock() + self.every_s

    def due(self) -> bool:
        return self.clock() >= self._next

    def frames(self) -> Frames:
        if self._frames is None:          # a greeting never changes; render it once
            self._frames = render(self.style, self.name, self.size, self.show_s)
        return self._frames

    def run(self, show: Callable[[Image.Image], None], restore: Callable[[], None],
            sleep: Callable[[float], None] = time.sleep) -> None:
        """Push each frame and hold it, then always restore the bus screen.

        The next showing is scheduled from when this one started, so the cadence stays steady even though the
        refreshes themselves take time.
        """
        started = self.clock()
        try:
            for img, hold in self.frames():
                show(img)
                sleep(hold)
        finally:
            self._next = started + self.every_s
            restore()


def from_config(size=_style.PANEL, clock=time.monotonic) -> list[Greeting]:
    """The greetings listed in config.toml ([[greetings]]). Bad entries are logged and skipped, never fatal."""
    from app import config

    entries = config.get("greetings", None)
    if entries is None:                        # older single-greeting setting: [greeting] name = "..."
        legacy = (config.get("greeting.name", "") or "").strip()
        entries = [{"name": legacy}] if legacy else []
    out = []
    for i, e in enumerate(entries or []):
        try:
            out.append(Greeting(name=str(e.get("name", "")), style=str(e.get("style", "spooky")),
                                every_s=float(e.get("every_secs", 60)), show_s=float(e.get("show_secs", 2)),
                                size=size, clock=clock))
        except (ValueError, TypeError, AttributeError) as err:
            log.warning("greetings[%d] skipped: %s", i, err)
    return out


def next_due(greetings) -> Optional[Greeting]:
    """The first greeting that is due, if any (one per loop tick, so they never stack up)."""
    return next((g for g in greetings if g.due()), None)
