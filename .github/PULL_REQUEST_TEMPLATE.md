## What changed

## Style checklist (see docs/STYLE_GUIDE.md)
- [ ] One hero element; at most three panels
- [ ] Built from `app/style.py` (no raw fonts, sizes, or gray values)
- [ ] Every state handled: normal, live/urgent, stale, empty, missing data
- [ ] Added/updated the page in `tests/test_pages_conform.py`; `python -m pytest` passes
- [ ] I looked at the preview PNGs (attach one if the look changed)

## Safety
- [ ] No secrets, `.env` files, passwords, or licensed fonts/logos
- [ ] Not deployed to a device as part of this PR (deploying is a separate, deliberate step)
