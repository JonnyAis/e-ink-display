"""Rotation timing: the bus screen is home, sports pages visit briefly, and nothing can strand the display."""
import pytest
from PIL import Image

from app import rotation as rot
from app.rotation import Page, Rotation


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def frame():
    return Image.new("L", (10, 10), 255)


def page(name, img=True, live=False, show_s=20):
    p = Page(name, lambda size: (frame() if img else None, live), show_s)
    p.refresh((10, 10))
    return p


def make(*pages, **kw):
    clock = Clock()
    kw.setdefault("bus_s", 120)
    kw.setdefault("live_bus_s", 45)
    return Rotation(list(pages), clock=clock, **kw), clock


def run(r, clock, log):
    def sleep(s):
        clock.t += s
    return r.run(show=lambda img: log.append("show"), restore=lambda: log.append("restore"), sleep=sleep)


def test_bus_screen_comes_first_then_pages_alternate():
    r, clock = make(page("celtics"), page("scores"))
    assert not r.due()
    clock.t += 119
    assert not r.due()
    clock.t += 1
    log = []
    assert run(r, clock, log) == "celtics"
    assert log == ["show", "restore"]
    assert not r.due()                 # a full bus stretch after every page
    clock.t += 120
    assert run(r, clock, []) == "scores"
    clock.t += 120
    assert run(r, clock, []) == "celtics"


def test_live_game_shortens_the_bus_stretch():
    r, clock = make(page("celtics", live=True), page("scores"))
    clock.t += 45
    assert r.due()


def test_empty_or_failed_pages_are_skipped():
    def boom(size):
        raise RuntimeError("ESPN down")
    broken = Page("celtics", boom)
    broken.refresh((10, 10))
    r, clock = make(broken, page("scores", img=False), page("third"))
    clock.t += 120
    assert run(r, clock, []) == "third"


def test_nothing_to_show_never_interrupts_the_bus_screen():
    r, clock = make(page("scores", img=False))
    clock.t += 10_000
    assert not r.due()
    assert run(r, clock, []) is None


def test_failed_refresh_keeps_last_good_frame():
    calls = {"n": 0}

    def flaky(size):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("timeout")
        return frame(), True
    p = Page("celtics", flaky)
    p.refresh((10, 10))
    p.refresh((10, 10))
    assert p.img is not None and p.live


def test_bus_screen_is_restored_even_if_showing_fails():
    r, clock = make(page("celtics"))
    clock.t += 120
    log = []

    def bad_show(img):
        raise OSError("SPI error")
    with pytest.raises(OSError):
        r.run(show=bad_show, restore=lambda: log.append("restore"), sleep=lambda s: None)
    assert log == ["restore"]
    assert not r.due()                 # and it does not retry in a tight loop


def test_each_page_has_its_own_time_on_screen():
    r, clock = make(page("team", show_s=15), page("scores", show_s=10))
    clock.t += 120
    start = clock.t
    run(r, clock, [])
    assert clock.t - start == 15
    clock.t += 120
    start = clock.t
    run(r, clock, [])
    assert clock.t - start == 10


def test_page_must_be_shorter_than_bus_stretch():
    with pytest.raises(ValueError):
        Rotation([page("a", show_s=20)], bus_s=20)
    with pytest.raises(ValueError):
        Rotation([page("a", show_s=20)], bus_s=120, live_bus_s=10)


def test_settings_come_from_config(monkeypatch, tmp_path):
    from app import config
    cfg = tmp_path / "config.toml"
    cfg.write_text('[rotation]\npages = ["scores"]\nbus_secs = 90\nscores_secs = 12\nleagues = ["nba"]\n')
    monkeypatch.setenv("EINK_CONFIG", str(cfg))
    config.reload()
    try:
        r = rot.from_config()
    finally:
        monkeypatch.undo()
        config.reload()
    assert [p.name for p in r.pages] == ["scores"]
    assert (r.bus_s, r.live_bus_s, r.pages[0].show_s) == (90, 45, 12)


def test_defaults_rotate_team_and_scores():
    r = rot.from_config()
    assert [p.name for p in r.pages] == ["team", "scores"]
    assert (r.bus_s, r.live_bus_s) == (120, 45)
    assert [p.show_s for p in r.pages] == [15, 15]


def test_scores_page_uses_cache_when_offline(monkeypatch, tmp_path):
    from app.services import sports_data
    games = [{"away": "NE", "home": "NYJ", "away_score": 10, "home_score": 7, "status": "Q2 3:00",
              "state": "live", "league": "NFL", "start": ""}]
    monkeypatch.setattr(sports_data, "CACHE_FILE", tmp_path / "c.json")
    sports_data.save_cache(games)

    def offline(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(sports_data, "fetch_games", offline)
    p = rot.scores_page(("NFL",), ("NE",))
    p.refresh((1872, 1404))
    assert p.img is not None and p.live
