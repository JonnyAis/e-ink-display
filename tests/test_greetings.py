"""Greetings: opt-in, on a steady cadence, short, and they always hand the screen back."""
import pytest

from app import config, greetings
from app.greetings import Greeting
from helpers import record_drawing


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make(clock, **kw):
    kw.setdefault("name", "Sam")
    return Greeting(clock=clock, **kw)


def test_first_showing_is_one_interval_after_start():
    c = Clock()
    g = make(c)
    c.t += 59.9
    assert not g.due()
    c.t += 0.1
    assert g.due()


def test_shows_for_show_secs_then_restores_on_a_steady_cadence():
    c = Clock()
    g = make(c)
    events = []
    c.t += 60
    g.run(lambda img: events.append(("show", c.t, img.size)), lambda: events.append(("restore", c.t)), sleep=c.sleep)
    assert events == [("show", 1060.0, (1872, 1404)), ("restore", 1062.0)]
    c.t += 5                     # the restore redraw took a while
    assert not g.due()
    c.t = 1120.0                 # next one is 60 s after the last one started
    assert g.due()


def test_multi_frame_styles_hold_each_frame(monkeypatch):
    from PIL import Image
    frame = Image.new("L", (10, 10), 0)
    monkeypatch.setitem(greetings.STYLES, "test_build", lambda name, size, show_s: [(frame, 1.0), (frame, 2.5)])
    c = Clock()
    g = make(c, style="test_build", show_s=3.5)
    shown = []
    g.run(lambda img: shown.append(c.t), lambda: shown.append("restore"), sleep=c.sleep)
    assert shown == [1000.0, 1001.0, "restore"] and c.t == 1003.5


def test_restore_runs_even_if_show_fails():
    c = Clock()
    g = make(c)
    restored = []

    def boom(_img):
        raise RuntimeError("panel busy")

    with pytest.raises(RuntimeError):
        g.run(boom, lambda: restored.append(True), sleep=c.sleep)
    assert restored == [True] and not g.due()


def test_frames_are_rendered_once(monkeypatch):
    calls = []
    real = greetings.STYLES["spooky"]
    monkeypatch.setitem(greetings.STYLES, "spooky", lambda *a: calls.append(1) or real(*a))
    g = make(Clock())
    g.frames(), g.frames()
    assert len(calls) == 1


def test_a_greeting_cannot_starve_the_bus_screen():
    with pytest.raises(ValueError):
        make(Clock(), every_s=2, show_s=2)


def test_unknown_style_is_an_error():
    with pytest.raises(ValueError):
        make(Clock(), style="nope")


@pytest.mark.parametrize("name, shown", [("Sam", "hello, Sam"), ("  ", "hello"), ("", "hello")])
def test_spooky_says_hello(name, shown):
    with record_drawing() as rec:
        greetings.render("spooky", name)
    assert [t for _, t in rec.texts] == [shown]


def _with_config(monkeypatch, cfg):
    def get(dotted, default=None):
        node = cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node
    monkeypatch.setattr(config, "get", get)


def test_off_by_default():
    assert greetings.from_config() == []


def test_from_config_reads_the_list_and_skips_bad_entries(monkeypatch):
    _with_config(monkeypatch, {"greetings": [
        {"name": "Sam", "style": "spooky", "every_secs": 90, "show_secs": 3},
        {"name": "Bad", "style": "no-such-style"},
        {"name": "Greedy", "every_secs": 5, "show_secs": 10},
        {"name": "Defaults"},
    ]})
    got = greetings.from_config()
    assert [(g.name, g.style, g.every_s, g.show_s) for g in got] == [
        ("Sam", "spooky", 90.0, 3.0), ("Defaults", "spooky", 60.0, 2.0)]


def test_older_single_greeting_setting_still_works(monkeypatch):
    _with_config(monkeypatch, {"greeting": {"name": "Sam"}})
    assert [(g.name, g.style) for g in greetings.from_config()] == [("Sam", "spooky")]


def test_next_due_picks_one():
    c = Clock()
    a, b = make(c, every_s=30), make(c, every_s=60)
    assert greetings.next_due([a, b]) is None
    c.t += 61
    assert greetings.next_due([a, b]) is a


@pytest.mark.parametrize("name, built", [
    ("Sam", ["S", "Sa", "Sam"]),
    ("", ["h", "he", "hel", "hell", "hello"]),
])
def test_slow_build_adds_letters_one_frame_at_a_time(name, built):
    with record_drawing() as rec:
        frames = greetings.render("slow_build", name, show_s=10.0)
    assert [t for _, t in rec.texts] == built
    assert len(frames) == len(built)
    assert abs(sum(hold for _, hold in frames) - 10.0) < 1e-6
    assert frames[-1][1] > frames[0][1]          # the finished name holds longest
    for img, _ in frames:                         # every frame is A2-safe
        assert {c for _, c in img.getcolors()} <= {0, 255}


def test_slow_build_caps_the_number_of_steps():
    frames = greetings.render("slow_build", "Abcdefghijklmnop", show_s=10.0)
    assert len(frames) <= 8
