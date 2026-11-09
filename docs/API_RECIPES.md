# Adding a new API-driven page

Every page follows one pipeline: **fetch -> normalize -> render an image -> (compare) -> refresh**.
Keep these in separate functions; the renderer must not import any display driver, so you can preview it as a PNG.

```
app/services/<thing>_data.py   fetch + normalize (+ cache)      <- tested with saved JSON fixtures
app/pages/<thing>.py           render(data) -> PIL "L" image    <- previewed as PNG
```

## Rules that save you pain
1. **Inspect a real response before writing the parser.** Save it as a fixture and write the tests against it.
   The sports parser in this repo was built this way.
2. **Never block the display loop on the network.** Fetch in a background thread; render from the last good data.
3. **Cache the last good result and label it stale** instead of showing old data as live.
4. **Back off on errors** (e.g. double the interval up to a cap) and respect rate limits / provider terms.
5. **Secrets only via environment variables** (`.env`), never in code, fixtures or logs. **Personal choices**
   (which team, stop, city) come from `app.config` (see `CONFIG.md`), never hardcoded.
6. **Skip the refresh if the image didn't change**, and use a full GC16 refresh when switching pages.

## Skeleton
```python
# app/services/thing_data.py
import logging, os, requests

def fetch(timeout=(3, 10)):
    r = requests.get(os.environ["THING_URL"], timeout=timeout)
    r.raise_for_status()
    return normalize(r.json())

def normalize(payload):
    # Map the provider's real schema (from a saved fixture) to a stable dict/list.
    return [{"title": i["name"], "value": i["value"]} for i in payload.get("items", [])]
```
```python
# app/pages/thing.py  -- build from app.style only (see STYLE_GUIDE.md)
from app import style

def render(items, updated="", stale=False, size=style.PANEL):
    img, d = style.new_canvas(size)
    style.header(img, "Thing", clock_text=updated or None, caption="Updated" if updated else None,
                 stale_minutes=0 if stale else None)
    if not items:
        style.draw(d, (size[0] // 2, size[1] // 2 + 100), "Nothing to show", "DISPLAY", anchor="mm")
        return img
    y = style.HEADER_H + 32
    for it in items[:3]:
        style.draw(d, (style.MARGIN, y), f'{it["title"]}: {it["value"]}', "DISPLAY")
        y += 110
    return img
```
Then add demo data for every state in a `preview_thing.py`, register the page in `tests/test_pages_conform.py`, and run `python -m pytest`.
Preview: `render(fetch()).save("preview/thing.png")`, then look at it.

## Notes per kind of API
- **API key in a query string/header** (e.g. transit, weather): read it from the environment; send it only to the
  provider over HTTPS.
- **OAuth APIs** (e.g. private Google Calendar): a bare API key is not enough. Use a service account or an OAuth
  refresh token stored in a protected file on the Pi, or read a public/secret iCal URL instead (treat that URL as a secret).
- **Unofficial endpoints** (ESPN here): can change without notice; keep a saved fixture and a failing test so you notice.

These snippets are templates and have not been run against any particular provider.
