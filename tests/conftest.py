"""Tests always run against config.example.toml, never against anyone's personal config.

The personal file's path is kept in EINK_PERSONAL_CONFIG so test_no_personal_data can check the repo against it.
"""
import os

from app import config

_personal = config.personal_path()
if _personal:
    os.environ["EINK_PERSONAL_CONFIG"] = str(_personal)
os.environ["EINK_CONFIG"] = str(config.EXAMPLE)
config.reload()
