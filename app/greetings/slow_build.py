"""Slow-build style: the name appears one letter at a time in round bubble letters, each with a sparkle,
then the sparkles scatter around the whole name and it holds.

Black on white, pure black/white only, so every frame goes out with the fast A2 mode and the build looks like a
little animation instead of a string of full refreshes. Uses the BUBBLY display role (Sniglet, SIL OFL), a
documented exception to the type scale (docs/STYLE_GUIDE.md, "Display faces").
"""
import math

from PIL import Image, ImageDraw

from app import style as s
from app.greetings import style

MAX_STEPS = 8          # long names add letters in groups, so the build never drags
STEP_S = 0.9           # target hold per build frame; an A2 full-screen push takes a few tenths of that
BUILD_SHARE = 0.65     # at most this much of show_s is spent building; the rest holds the finished name
SPARKLE_R = 46


def _sparkle(d, cx, cy, r):
    """A four-point star."""
    pts = []
    for k in range(8):
        a = math.pi / 4 * k - math.pi / 2
        rr = r if k % 2 == 0 else r * 0.28
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=s.INK)


def _steps(n):
    """How many letters are visible after each build step (ends at n)."""
    k = min(n, MAX_STEPS)
    return [math.ceil(n * (i + 1) / k) for i in range(k)]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@style("slow_build")
def render(name, size, show_s):
    text = name or "hello"
    W, H = size
    edge = s.SAFE_EDGE + s.MARGIN + SPARKLE_R
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    text = s.fit_text(probe, text, "BUBBLY", W - 2 * edge)
    f = s.font("BUBBLY")
    # Lay out the finished name once, centred; every frame draws a prefix from the same left/baseline point.
    full_w = probe.textlength(text, font=f)
    asc, desc = f.getmetrics()
    x0 = (W - full_w) / 2
    base = (H + asc - desc) / 2

    def frame(shown, sparkles):
        img, d = s.new_canvas(size)
        s.draw(d, (x0, base), text[:shown], "BUBBLY", anchor="ls")
        for cx, cy, r in sparkles:
            _sparkle(d, cx, cy, r)
        return img.point(lambda v: s.PAPER if v >= 128 else s.INK)   # A2-safe: no gray anti-aliasing

    counts = _steps(len(text))
    step = min(STEP_S, BUILD_SHARE * show_s / len(counts))
    frames = []
    for c in counts[:-1]:
        bx = probe.textbbox((x0, base), text[:c], font=f, anchor="ls")
        frames.append((frame(c, [(_clamp(bx[2] + 34, edge, W - edge), _clamp(bx[1] - 24, edge, H - edge), SPARKLE_R)]), step))

    bx = probe.textbbox((x0, base), text, font=f, anchor="ls")
    cx = (bx[0] + bx[2]) / 2
    scatter = [(bx[0] - 90, bx[1] + 30, 52), (bx[2] + 85, bx[1] - 5, 60), (bx[0] + 130, bx[3] + 100, 36),
               (bx[2] - 170, bx[3] + 110, 46), (cx, bx[1] - 110, 40)]
    scatter = [(_clamp(x, edge, W - edge), _clamp(y, edge, H - edge), r) for x, y, r in scatter]
    frames.append((frame(len(text), scatter), max(show_s - step * (len(counts) - 1), step)))
    return frames
