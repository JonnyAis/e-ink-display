"""Personal settings (your team, bus stops, greeting) live in a config file that is never committed.

Lookup order, first file found wins:
    1. $EINK_CONFIG                      (explicit path)
    2. ./config.toml                     (repo root; git-ignored)
    3. ~/.config/eink/config.toml        (per user, outside the repo)
Values missing from your file fall back to config.example.toml, which is committed and holds neutral defaults.
Secrets (API keys) do not go here: they stay in .env on the device. See docs/CONFIG.md.

    from app import config
    config.get("team.abbr")          # -> "BOS"
    config.get("bus.stops", [])      # -> your stop IDs
"""
import os
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11 (older Raspberry Pi OS)
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config.example.toml"


def candidates():
    env = os.environ.get("EINK_CONFIG")
    if env:
        return [Path(env).expanduser()]
    return [ROOT / "config.toml", Path.home() / ".config" / "eink" / "config.toml"]


def personal_path():
    """The personal config file in use, or None if only the example is available."""
    return next((p for p in candidates() if p.is_file()), None)


def _read(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=None)
def load():
    """The merged settings: example defaults overlaid with your personal file."""
    cfg = _read(EXAMPLE)
    path = personal_path()
    if path and path.resolve() != EXAMPLE.resolve():
        cfg = _merge(cfg, _read(path))
    return cfg


def get(dotted, default=None):
    node = load()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def reload():
    load.cache_clear()
