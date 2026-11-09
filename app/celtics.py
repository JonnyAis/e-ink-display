"""Old name for the team page, kept so existing display loops that import it keep working.

New code should use app.pages.team. The team shown comes from your config, not from this file.
"""
from app.pages.team import (apply_live_scores, fetch_team as fetch_celtics, has_live_game,  # noqa: F401
                            parse_boxscore, render_team as render_celtics)

if __name__ == "__main__":
    import runpy
    runpy.run_module("app.pages.team", run_name="__main__")
