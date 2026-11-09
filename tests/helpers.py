"""Test helper: record what a page draws so tests can check it against the style rules."""
from contextlib import contextmanager
from dataclasses import dataclass, field

from PIL import ImageDraw


@dataclass
class Drawn:
    inks: set = field(default_factory=set)       # every fill/outline value used
    font_sizes: set = field(default_factory=set)  # every text size used
    texts: list = field(default_factory=list)     # (bbox, string) for every text drawn


@contextmanager
def record_drawing():
    rec = Drawn()
    originals = {}

    def wrap_shape(name):
        orig = getattr(ImageDraw.ImageDraw, name)
        originals[name] = orig

        def wrapper(self, *args, **kwargs):
            for key in ("fill", "outline"):
                if kwargs.get(key) is not None:
                    rec.inks.add(kwargs[key])
            return orig(self, *args, **kwargs)
        setattr(ImageDraw.ImageDraw, name, wrapper)

    orig_text = ImageDraw.ImageDraw.text
    originals["text"] = orig_text

    def text_wrapper(self, xy, text, fill=None, font=None, anchor=None, *args, **kwargs):
        if fill is not None:
            rec.inks.add(fill)
        rec.font_sizes.add(getattr(font, "size", None))
        rec.texts.append((self.textbbox(xy, text, font=font, anchor=anchor), text))
        return orig_text(self, xy, text, fill=fill, font=font, anchor=anchor, *args, **kwargs)

    for name in ("line", "rectangle", "rounded_rectangle", "ellipse", "polygon"):
        wrap_shape(name)
    ImageDraw.ImageDraw.text = text_wrapper
    try:
        yield rec
    finally:
        for name, fn in originals.items():
            setattr(ImageDraw.ImageDraw, name, fn)


def overlaps(a, b, tol=2):
    """True if two (x0, y0, x1, y1) boxes intersect by more than `tol` px in both directions."""
    return (min(a[2], b[2]) - max(a[0], b[0]) > tol) and (min(a[3], b[3]) - max(a[1], b[1]) > tol)
