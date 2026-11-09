"""Team screen for one NBA team, readable in about 10 seconds: next or live game, last game, conference standing.

Which team comes from your config ([team] in config.toml; see docs/CONFIG.md), so the code holds no favorites.
Data comes from ESPN's unofficial public JSON endpoints (no API key needed).
Usage:
    python -m app.pages.team            # writes team_preview.png for your configured team
    from app.pages.team import fetch_team, render_team
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from app import config, style

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SCHEDULE_URL = ESPN + "/teams/{id}/schedule"
STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
SCOREBOARD_URL = ESPN + "/scoreboard"
CACHE_DIR = Path(os.path.expanduser("~/.cache"))

N_RECENT = 4
N_UPCOMING = 5


def configured_team():
    """{"id", "abbr", "name", "conference"} from config.toml (falls back to config.example.toml)."""
    t = config.get("team", {})
    return {"id": str(t.get("id", "")), "abbr": t.get("abbr", ""), "name": t.get("name", "") or t.get("abbr", ""),
            "conference": t.get("conference", "East")}


# ---------- fetching ----------

def _score(c):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("displayValue")
    return s


def _parse_game(ev, team_id):
    comp = ev["competitions"][0]
    status = comp["status"]["type"]
    me = next(c for c in comp["competitors"] if c["team"]["id"] == team_id)
    opp = next(c for c in comp["competitors"] if c["team"]["id"] != team_id)
    return {
        "id": ev.get("id"),
        "date": ev["date"],  # ISO UTC, e.g. 2026-10-20T19:00Z
        "state": status["state"],  # pre / in / post
        "detail": status.get("shortDetail", ""),
        "home": me["homeAway"] == "home",
        "opp": opp["team"]["abbreviation"],
        "opp_name": opp["team"]["shortDisplayName"],
        "my_score": _score(me),
        "opp_score": _score(opp),
        "won": me.get("winner"),
    }


def _parse_standings(data, conference="East"):
    conf = next(c for c in data["children"] if conference.lower() in c["name"].lower())
    rows = []
    for e in conf["standings"]["entries"]:
        s = {k["name"]: k.get("displayValue") for k in e["stats"]}
        rows.append({
            "abbr": e["team"]["abbreviation"],
            "record": s.get("overall", ""),
            "seed": int(s.get("playoffSeed") or 99),
            "gb": s.get("gamesBehind", "-"),
            "streak": s.get("streak", ""),
            "l10": s.get("Last Ten Games", ""),
        })
    return sorted(rows, key=lambda r: r["seed"])


def apply_live_scores(games, scoreboard, team_id=None):
    """ESPN's team-schedule endpoint has no scores for in-progress games; the scoreboard does.

    Fills my_score / opp_score / detail on the live games in `games` (in place) and returns them.
    Games not found on the scoreboard are left unchanged (the page shows a dash for a missing score).
    """
    team_id = team_id or configured_team()["id"]
    by_id = {ev.get("id"): ev for ev in scoreboard.get("events", [])}
    for g in games:
        if g["state"] != "in" or g.get("id") not in by_id:
            continue
        ev = by_id[g["id"]]
        comp = ev["competitions"][0]
        me = next((c for c in comp["competitors"] if c["team"]["id"] == team_id), None)
        opp = next((c for c in comp["competitors"] if c["team"]["id"] != team_id), None)
        if me and opp:
            g["my_score"], g["opp_score"] = _score(me), _score(opp)
        g["detail"] = ev.get("status", {}).get("type", {}).get("shortDetail") or g.get("detail", "")
    return games


def parse_boxscore(summary, top_n=3, team_id=None):
    """Key stats for the team from an ESPN game summary; None if the box score is missing."""
    team_id = team_id or configured_team()["id"]
    try:
        bs = summary["boxscore"]
        team = next(t for t in bs["teams"] if t["team"]["id"] == team_id)
        ts = {s["name"]: s["displayValue"] for s in team["statistics"]}
        pl = next(p for p in bs["players"] if p["team"]["id"] == team_id)["statistics"][0]
        keys = pl["keys"]
        players = []
        for a in pl["athletes"]:
            if a.get("didNotPlay") or not a.get("stats"):
                continue
            s = dict(zip(keys, a["stats"]))
            players.append({
                "name": a["athlete"].get("shortName", "?"),
                "pts": int(s.get("points") or 0), "reb": s.get("rebounds", "0"),
                "ast": s.get("assists", "0"), "min": s.get("minutes", ""),
            })
        players.sort(key=lambda p: p["pts"], reverse=True)
        return {
            "team": {
                "fg_pct": ts.get("fieldGoalPct"), "3p_pct": ts.get("threePointFieldGoalPct"),
                "ft_pct": ts.get("freeThrowPct"), "reb": ts.get("totalRebounds"),
                "ast": ts.get("assists"), "tov": ts.get("turnovers"),
            },
            "top": players[:top_n],
        }
    except (KeyError, StopIteration, IndexError, TypeError, ValueError) as e:
        logging.warning("box score unavailable: %s", e)
        return None


def fetch_boxscore(event_id, team_id, timeout=8):
    r = requests.get(ESPN + "/summary", params={"event": event_id}, timeout=timeout)
    r.raise_for_status()
    return parse_boxscore(r.json(), team_id=team_id)


def fetch_team(team=None, timeout=8):
    """Fetch and return display-ready data for `team` (default: your configured team). Falls back to cache."""
    team = team or configured_team()
    team_id = team["id"]
    cache_file = CACHE_DIR / f"team_{team_id}.json"
    try:
        sched = requests.get(SCHEDULE_URL.format(id=team_id), timeout=timeout)
        sched.raise_for_status()
        stand = requests.get(STANDINGS_URL, timeout=timeout)
        stand.raise_for_status()
        games = [_parse_game(e, team_id) for e in sched.json()["events"]]
        games.sort(key=lambda g: g["date"])
        if any(g["state"] == "in" for g in games):
            try:  # live scores are optional: never let them break the page
                sb = requests.get(SCOREBOARD_URL, timeout=timeout)
                sb.raise_for_status()
                apply_live_scores(games, sb.json(), team_id)
            except Exception as e:
                logging.warning("live score fetch failed: %s", e)
        data = {
            "fetched": datetime.now(timezone.utc).isoformat(),
            "team": team,
            "live": [g for g in games if g["state"] == "in"],
            "recent": [g for g in games if g["state"] == "post"][-N_RECENT:][::-1],
            "upcoming": [g for g in games if g["state"] == "pre"][:N_UPCOMING],
            "standings": _parse_standings(stand.json(), team["conference"]),
        }
        data["box"] = None
        if data["recent"] and data["recent"][0].get("id"):
            try:  # optional: never let a missing box score break the page
                data["box"] = fetch_boxscore(data["recent"][0]["id"], team_id, timeout)
            except Exception as e:
                logging.warning("box score fetch failed: %s", e)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data))
        except OSError as e:
            logging.warning("cache write failed: %s", e)
        return data
    except Exception as e:
        logging.error("team fetch failed: %s", e)
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            data["stale"] = True
            return data
        raise


def has_live_game(data):
    return bool(data.get("live"))


# ---------- rendering ----------
# Layout (1872x1404): header | left: NEXT GAME hero (or live score) + next 3 games, LAST GAME result + top scorer
#                     | right: conference standings.
# All sizes/inks come from app.style roles; see docs/STYLE_GUIDE.md.

LEFT_W = 1100
HERO_H = 380
STANDINGS_ROWS = 10      # seeds 1-10 = playoffs + play-in picture


def _local(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def _when(dt, now):
    """'Today' / 'Tomorrow' / 'Sat Nov 8' -- words a person would say."""
    days = (dt.date() - now.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return style.fmt_date(dt)


def _vs(g):
    return "vs" if g["home"] else "@"


def _pts(v):
    """A score for display; a dash when it is not available."""
    return "–" if v in (None, "") else str(v)


def _hero(d, box, data, now, team):
    """The one thing to read first: the live score if a game is on, otherwise the next game."""
    x1, y1, x2, y2 = box
    pad = 36
    live = data.get("live")
    upcoming = data.get("upcoming") or []
    if live:
        g = live[0]
        fg, sub = style.card(d, box, urgent=True)
        style.draw(d, (x1 + pad, y1 + 28), "LIVE  " + (g.get("detail") or ""), "LABEL", fill=sub)
        base = y1 + HERO_H - 36
        style.draw(d, (x1 + pad, y1 + 84), team["abbr"], "HEADING", fill=fg)
        style.draw(d, (x1 + pad, base), _pts(g["my_score"]), "HERO", fill=fg, anchor="ls")
        style.draw(d, (x2 - pad, y1 + 84), g["opp"], "HEADING", fill=fg, anchor="ra")
        style.draw(d, (x2 - pad, base), _pts(g["opp_score"]), "HERO", fill=fg, anchor="rs")
        style.draw(d, ((x1 + x2) // 2, base - 70), _vs(g), "DISPLAY", fill=sub, anchor="ms")
        return
    fg, sub = style.card(d, box, urgent=False)
    if not upcoming:
        style.draw(d, (x1 + pad, y1 + 28), "NEXT GAME", "LABEL", fill=sub)
        style.draw(d, ((x1 + x2) // 2, (y1 + y2) // 2 + 20), "No upcoming games", "DISPLAY", fill=fg, anchor="mm")
        return
    g = upcoming[0]
    dt = _local(g["date"])
    style.draw(d, (x1 + pad, y1 + 28), "NEXT GAME", "LABEL", fill=sub)
    style.draw(d, (x2 - pad, y1 + 20), _when(dt, now), "HEADING", fill=fg, anchor="ra")
    base = y1 + 290
    style.draw(d, (x1 + pad, base), _vs(g), "DISPLAY", fill=sub, anchor="ls")
    vs_w = int(style.text_width(d, _vs(g), "DISPLAY")) + 28
    style.draw(d, (x1 + pad + vs_w, base), g["opp"], "HERO", fill=fg, anchor="ls")
    style.draw(d, (x2 - pad, base), style.fmt_time(dt), "DISPLAY", fill=fg, anchor="rs")
    style.draw(d, (x1 + pad, y2 - 28), g.get("opp_name", ""), "LABEL", fill=sub, anchor="ls")


def _upcoming_rows(d, x, y, w, games, now, row_h=72):
    for g in games:
        dt = _local(g["date"])
        style.draw(d, (x, y), _when(dt, now), "BODY", fill=style.GRAY_TEXT)
        style.draw(d, (x + 330, y), f"{_vs(g)} {g['opp']}", "BODY", bold=True)
        style.draw(d, (x + w, y), style.fmt_time(dt), "BODY", fill=style.GRAY_TEXT, anchor="ra")
        y += row_h
    return y


def _last_game(d, x, y, w, data):
    """Just the result and the top scorer: readable at a glance (the full box score was too dense)."""
    recent = data.get("recent") or []
    if not recent:
        y = style.panel_title(d, x, y, w, "LAST GAME")
        style.draw(d, (x, y + 8), "No games played yet", "BODY", fill=style.GRAY_TEXT)
        return
    g = recent[0]
    y = style.panel_title(d, x, y, w, "LAST GAME")
    style.draw(d, (x, y + 8), f"{'W' if g['won'] else 'L'}  {g['my_score']}–{g['opp_score']}", "DISPLAY")
    style.draw(d, (x + w, y + 8), f"{_vs(g)} {g.get('opp_name') or g['opp']}", "DISPLAY", fill=style.GRAY_TEXT,
               anchor="ra")
    top = ((data.get("box") or {}).get("top") or [])
    if top:
        p = top[0]
        style.draw(d, (x, y + 130), style.fit_text(d, p["name"], "BODY", w - 300, bold=True), "BODY", bold=True)
        style.draw(d, (x + w, y + 130), f"{p['pts']} pts", "BODY", fill=style.GRAY_TEXT, anchor="ra")
    else:
        style.draw(d, (x, y + 130), "Box score not available", "BODY", fill=style.GRAY_TEXT)


def _standings(d, x, y, w, rows, team):
    y = style.panel_title(d, x, y, w, team["conference"].upper())
    if not rows:
        style.draw(d, (x, y + 8), "Standings unavailable", "BODY", fill=style.GRAY_TEXT)
        return
    shown = rows[:STANDINGS_ROWS]
    me = next((r for r in rows if r["abbr"] == team["abbr"]), None)
    if me and me not in shown:
        shown = shown[:-1] + [me]
    cols = {"seed": 0, "team": 90, "rec": 360, "gb": w - 8}
    for key, label, anchor in (("seed", "#", "la"), ("team", "TEAM", "la"), ("rec", "W-L", "la"), ("gb", "GB", "ra")):
        style.draw(d, (x + cols[key], y), label, "LABEL", fill=style.GRAY_TEXT, anchor=anchor)
    y += 56
    row_h = 94
    for r in shown:
        is_me = r["abbr"] == team["abbr"]
        if is_me:
            d.rounded_rectangle((x - 12, y - 6, x + w + 4, y + row_h - 14), radius=18, fill=style.INK)
        fg = style.PAPER if is_me else style.INK
        style.draw(d, (x + cols["seed"], y), str(r["seed"]), "BODY", fill=fg, bold=is_me)
        style.draw(d, (x + cols["team"], y), r["abbr"], "BODY", fill=fg, bold=True)
        style.draw(d, (x + cols["rec"], y), r["record"], "BODY", fill=fg, bold=is_me)
        style.draw(d, (x + cols["gb"], y), str(r["gb"]), "BODY", fill=fg, anchor="ra")
        if r["seed"] == 6 and not is_me:   # line under the 6th seed: top six skip the play-in
            d.line((x, y + row_h - 12, x + w, y + row_h - 12), fill=style.GRAY_MID, width=style.RULE)
        y += row_h


def render_team(data, size=style.PANEL, now=None):
    """Return the team page as a grayscale ('L') PIL image. The team comes from data["team"] (set by fetch_team)."""
    now = now or datetime.now().astimezone()
    team = {**configured_team(), **(data.get("team") or {})}
    img, d = style.new_canvas(size)
    W, H = size
    fetched = _local(data["fetched"])
    stale = bool(data.get("stale"))
    age = max(0, int((now - fetched).total_seconds() // 60))
    style.header(img, team["name"], clock_text=style.fmt_time(fetched), caption="Updated",
                 stale_minutes=age if stale else None)

    top = style.HEADER_H + 32
    x = style.MARGIN
    right_x = x + LEFT_W + 2 * style.GAP
    right_w = W - style.MARGIN - right_x

    _hero(d, (x, top, x + LEFT_W, top + HERO_H), data, now, team)
    y = top + HERO_H + style.GAP + 8
    upcoming = data.get("upcoming") or []
    rest = upcoming if data.get("live") else upcoming[1:]
    y = _upcoming_rows(d, x, y, LEFT_W, rest[:3], now)
    _last_game(d, x, y + style.GAP, LEFT_W, data)
    _standings(d, right_x, top, right_w, data.get("standings") or [], team)
    return img


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = fetch_team()
    out = render_team(data)
    path = sys.argv[1] if len(sys.argv) > 1 else "team_preview.png"
    out.save(path)
    print("wrote", path)
