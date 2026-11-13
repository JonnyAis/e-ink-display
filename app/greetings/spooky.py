"""Spooky style: "hello, <name>" in dripping Creepster letters, white on black, one frame.

Uses the SPOOKY display role, a documented exception to the type scale (docs/STYLE_GUIDE.md, "Display faces").
"""
from app import style as s
from app.greetings import style


@style("spooky")
def render(name, size, show_s):
    text = f"hello, {name}" if name else "hello"
    return [(s.interlude_screen(text, role="SPOOKY", size=size), show_s)]
