"""The repo must not contain anyone's personal settings. See docs/CONFIG.md."""
import importlib.util
from pathlib import Path

import pytest

from app import config

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_personal", ROOT / "tools" / "check_personal.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def test_personal_config_is_git_ignored():
    ignored = (ROOT / ".gitignore").read_text().split()
    assert "config.toml" in ignored and ".env" in ignored


def test_tests_use_the_example_config():
    assert config.personal_path() == config.EXAMPLE


def test_example_config_has_no_personal_values():
    assert config._read(config.EXAMPLE)["bus"]["stops"] == []
    assert config._read(config.EXAMPLE).get("greetings", []) == []   # greetings are opt-in


def test_no_personal_values_in_tracked_files():
    values = check.personal_values()
    if not values:
        pytest.skip("no personal config.toml or .env on this machine to check against")
    leaks = check.find_leaks(values)
    assert not leaks, f"personal values committed: {[(f, v[:2] + '…') for f, v in leaks]}"


def test_terms_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("EINK_PRIVATE_TERMS", "zz-term-from-ci\n\nab\n")
    values = check.personal_values()
    assert "zz-term-from-ci" in values
    assert "ab" not in values  # too short to match safely


def test_ci_output_never_shows_any_part_of_a_value(monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("EINK_PRIVATE_TERMS", "site.api.espn.com")   # a string we know is in the repo
    assert check.main([]) == 1
    out = capsys.readouterr().out
    assert "a personal value was found" in out
    assert "si…" not in out and "espn" not in out


def test_leak_finder_catches_a_value():
    assert check.find_leaks(["site.api.espn.com"])          # a string we know is in the repo
    assert not check.find_leaks(["zz-" + "absent" + "-zz"])  # built at runtime so this file does not contain it
