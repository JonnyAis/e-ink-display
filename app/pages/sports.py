"""Sports scoreboard page: pure Pillow, no hardware imports.

render_sports_page(games, updated_at, stale=False, stale_minutes=0, title="Scores") -> PIL.Image (mode 'L', 1872x1404)
One league per page; `title` is the league's name (e.g. "NBA").
Look and feel come from app.style (see docs/STYLE_GUIDE.md): a live game is the "urgent" inverted card.
"""
from app import style

MAX_GAMES = 4
CARD_H = 262
CARD_GAP = 20


def _card(d, box, g):
    x1, y1, x2, y2 = box
    pad = 36
    live = g.get("state") == "live"
    fg, sub = style.card(d, box, urgent=live)
    status = ("LIVE  " if live else "") + str(g.get("status", ""))
    style.draw(d, (x1 + pad, y1 + 16), status, "LABEL", fill=sub)
    scored = g.get("away_score") is not None
    for i, (name, score) in enumerate(((g["away"], g.get("away_score")), (g["home"], g.get("home_score")))):
        y = y1 + 64 + i * 84
        style.draw(d, (x1 + pad, y), name, "DISPLAY", fill=fg)
        style.draw(d, (x2 - pad, y), str(score) if scored else "–", "DISPLAY", fill=fg, anchor="ra")


def render_sports_page(games, updated_at="", stale=False, stale_minutes=0, size=style.PANEL, title="Scores"):
    img, d = style.new_canvas(size)
    style.header(img, title, clock_text=updated_at or None, caption="Updated" if updated_at else None,
                 stale_minutes=stale_minutes if stale else None)
    if not games:
        style.draw(d, (size[0] // 2, (size[1] + style.HEADER_H) // 2), "No games right now", "DISPLAY", anchor="mm")
        return img
    y = style.HEADER_H + 32
    for g in games[:MAX_GAMES]:
        _card(d, (style.MARGIN, y, size[0] - style.MARGIN, y + CARD_H), g)
        y += CARD_H + CARD_GAP
    return img
