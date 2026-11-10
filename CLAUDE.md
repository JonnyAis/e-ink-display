# Notes for AI assistants working in this repo

This project renders e-ink screens with Pillow. Before you add or change a page:

1. Read `docs/STYLE_GUIDE.md`. Every page must follow it; the rules are enforced by tests.
2. Build pages only from `app/style.py`: type **roles** (`style.draw(d, xy, text, "BODY")`), named **inks**
   (`style.INK`, `style.GRAY_TEXT`, ...) and components (`header`, `card`, `badge`, `panel_title`, `message_screen`).
   Never call `ImageFont.truetype`, never use raw font sizes or gray numbers; `tests/test_style.py` fails the build.
3. Pick one hero element first. At most three panels. Nothing under 44 px.
4. Handle every state: normal, live/urgent, stale, empty, missing optional data. Add demo data for each and register the
   page in `tests/test_pages_conform.py`.
5. Run `python -m pytest`, then run the page's `preview_*` module and **look at the PNGs** in `preview/`.
   The tests catch violations; they cannot judge whether it looks right.

Personal settings (team, bus stops, names, hosts) go in `config.toml` via `app.config`, never in code or docs;
see `docs/CONFIG.md`. `tests/test_no_personal_data.py` and the pre-commit hook check for them.

Security: never commit secrets, `.env`, passwords, or licensed fonts/logos. Credentials live outside the repo (see `SECURITY.md`).
Enable the local secret check with `git config core.hooksPath .githooks`.

Don't push to the Pi or restart the display service without the owner asking. `tools/pi.ps1` has the safe helpers.
How cloud sessions reach the repo, the Pi and the owner's local settings: `docs/PI_CONNECTION.md` ("Working with Claude").
