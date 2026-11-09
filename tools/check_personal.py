"""Fail if a value from your personal config (or .env) appears in files git would publish.

    python tools/check_personal.py            # check every tracked file
    python tools/check_personal.py --staged   # check only what is staged (used by .githooks/pre-commit)
    python tools/check_personal.py --require-terms   # fail if there is nothing to check against (used by CI)
    python tools/check_personal.py --dump-terms      # print the terms, for piping into a GitHub secret

Machines with no personal config (GitHub Actions, for example) get the terms from $EINK_PRIVATE_TERMS, one per line.
With $CI set, output names the file but never any part of the value, because CI logs can be public.

Your values are read from your own config.toml / .env, so the list of what to look for never enters the repo.
Values that are also in config.example.toml (shared defaults) and very short values are ignored.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402

MIN_LEN = 4
SKIP = {"config.example.toml"}


def _strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, (str, int)) and not isinstance(node, bool):
        yield str(node).strip()


def _env_values(path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            out.append(line.split("=", 1)[1].strip().strip("'\""))
    return out


def personal_values():
    """Strings from your personal config and .env that must never be committed."""
    path = os.environ.get("EINK_PERSONAL_CONFIG") or config.personal_path()
    values = set()
    if path and Path(path).resolve() != config.EXAMPLE.resolve():
        values |= set(_strings(config._read(path)))
    values |= set(_env_values(ROOT / ".env"))
    values |= {t.strip() for t in os.environ.get("EINK_PRIVATE_TERMS", "").splitlines()}
    shared = set(_strings(config._read(config.EXAMPLE)))
    return sorted(v for v in values if len(v) >= MIN_LEN and v not in shared)


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def find_leaks(values, staged=False):
    """[(file, value)] for each personal value found in tracked (or staged) text."""
    if not values:
        return []
    leaks = []
    if staged:
        added = [l[1:] for l in _git("diff", "--cached", "-U0", "--no-color").splitlines()
                 if l.startswith("+") and not l.startswith("+++")]
        text = "\n".join(added).lower()
        leaks = [("(staged changes)", v) for v in values if v.lower() in text]
    else:
        for name in _git("ls-files").splitlines():
            if name in SKIP:
                continue
            try:
                text = (ROOT / name).read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue  # binary files (fonts, PNGs)
            leaks += [(name, v) for v in values if v.lower() in text]
    return leaks


def main(argv):
    values = personal_values()
    if "--dump-terms" in argv:
        print("\n".join(values))
        return 0
    if "--require-terms" in argv and not values:
        print("BLOCKED: no personal terms to check against. Is the PERSONAL_TERMS secret set?")
        return 1
    leaks = find_leaks(values, staged="--staged" in argv)
    for name, v in leaks:
        if os.environ.get("CI"):
            print(f"BLOCKED: a personal value was found in {name}")
            continue
        masked = v[:2] + "…" + v[-1:] if len(v) > 4 else "…"
        print(f"BLOCKED: personal value '{masked}' found in {name}")
    if leaks:
        print("Move it to config.toml (git-ignored) and read it with app.config.get(). See docs/CONFIG.md.")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
