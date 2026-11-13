# Your settings vs. the shared code

This repo is shared, so it holds **code and neutral defaults only**. Anything that is about *your* display
(which team you follow, your bus stops, the name on the greeting, your Pi's address) lives outside it.

| What | Where | Committed? |
|---|---|---|
| Code, pages, tests, docs | this repo | yes |
| Neutral defaults (example team, empty stop list) | `config.example.toml` | yes |
| Your team, bus stops, greetings (names) | `config.toml` (repo root) or `~/.config/eink/config.toml` | **no** (git-ignored) |
| API keys (`OBA_KEY`) | `.env` on the device | **no** (git-ignored) |
| Pi host / user | `pi.env` in the repo root or `~/.config/eink/pi.env` (`PI_HOST=...`, `PI_USER=...`), one per PC | **no** (git-ignored) |
| Logos, reference photos, one-off pages for your house | a private folder or private repo of your own | **no** |

## Set up
```bash
cp config.example.toml config.toml   # then edit it
```
Only put the keys you want to change; anything missing falls back to `config.example.toml`.
To keep the file somewhere else (for example a private repo), point at it: `EINK_CONFIG=/path/to/config.toml`.

On the Pi, copy your `config.toml` next to the app (or to `~/.config/eink/config.toml`). It is not deployed by git.

## In code
```python
from app import config
config.get("team.abbr")
config.get("bus.stops", [])
```
Pages read config only for *what* to show; previews and tests use fixed demo data so they look the same on every
machine. `tests/conftest.py` forces the example config during tests.

## The guard
`tools/check_personal.py` reads the values in *your* `config.toml` and `.env` and fails if any of them appear in
files git would publish. The list of what to look for never enters the repo.
- `python -m pytest` runs it over every tracked file (skipped on machines with no personal config).
- The pre-commit hook runs it over staged changes. Enable once per clone: `git config core.hooksPath .githooks`.
- GitHub Actions runs it on every pull request, using an encrypted copy of your values (the `PERSONAL_TERMS` secret).
  This covers commits made where no `config.toml` exists, such as cloud sessions. Refresh it with `Pi-SyncPrivacyTerms`.

To protect words that aren't settings (your neighbourhood, street, family names), list them in `config.toml`:
```toml
[privacy]
extra_terms = ["word one", "word two"]
```
Matching ignores case and needs at least 4 characters.

Values that are also in `config.example.toml` are ignored, so following the example team is fine.

Git history is not rewritten by any of this: anything committed before stays in history.

## Greetings
Short full-screen "hello, <name>" moments over the bus screen. Off unless you list them; one block each:
```toml
[[greetings]]
name = "Alex"          # empty -> a plain "hello"
style = "spooky"       # "spooky" (one frame) or "slow_build" (the name builds letter by letter)
every_secs = 60        # how often
show_secs = 2          # how long it stays up; must be less than every_secs
```
For `slow_build`, give it about 10 seconds (`show_secs = 10`): roughly two thirds builds the name, the rest holds it.
Entries with an unknown style or a `show_secs` that isn't shorter than `every_secs` are logged and skipped.
The older single setting `[greeting] name = "..."` still works and means one spooky greeting every 60 s for 2 s.
The names are personal values, so after adding one, refresh the CI copy with `Pi-SyncPrivacyTerms`, and copy your
`config.toml` to the Pi (`Pi-PushConfig`): git deploys don't carry it.
