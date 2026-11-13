"""Preview every greeting style (no hardware): python -m app.preview_greetings

Writes preview/greeting_<style>_<state>[_<frame>].png. Demo names only; real names live in your config.toml.
"""
from pathlib import Path

from app import greetings

STATES = {"normal": "Sam", "no_name": "", "long_name": "Sam the Magnificent of Nowhere-in-Particular"}


def variants():
    """{(style, state): frames} for every registered style."""
    greetings._load_styles()
    return {(st, state): greetings.render(st, name, show_s=10.0)
            for st in sorted(greetings.STYLES) for state, name in STATES.items()}


if __name__ == "__main__":
    out = Path("preview")
    out.mkdir(exist_ok=True)
    for (st, state), frames in variants().items():
        for i, (img, _hold) in enumerate(frames):
            suffix = f"_{i}" if len(frames) > 1 else ""
            path = out / f"greeting_{st}_{state}{suffix}.png"
            img.save(path)
            print("wrote", path)
