"""Style guide enforcement, part 1: the tokens themselves and a lint of the code.

Rules (docs/STYLE_GUIDE.md): pages never load fonts or pick raw gray values; they use roles and named inks from app.style.
"""
import ast
from pathlib import Path

import pytest

from app import style

APP = Path(__file__).resolve().parents[1] / "app"
# The bus screen (app/main.py) predates the style guide and still draws with its own Marsden fonts.
# It is the reference design the guide was written from; restyling it is separate work, so it is exempt for now.
LEGACY = {APP / "main.py"}
SOURCES = [p for p in APP.rglob("*.py") if p.name != "style.py" and p not in LEGACY]


def test_type_scale_respects_minimum():
    assert style.MIN_TEXT_PX >= 44
    assert all(size >= style.MIN_TEXT_PX for size, _ in style.ROLES.values())


def test_exactly_three_grays_plus_black_and_white():
    assert style.ALLOWED_INKS == {0, 255, style.GRAY_TEXT, style.GRAY_MID, style.GRAY_LINE}
    assert len({style.GRAY_TEXT, style.GRAY_MID, style.GRAY_LINE}) == 3
    assert style.GRAY_TEXT < style.GRAY_MID < style.GRAY_LINE   # darker = stronger


def test_bundled_font_loads():
    f = style.font("BODY")
    assert getattr(f, "size", None) == style.ROLES["BODY"][0]
    assert "Barlow" in f.getname()[0] or style.os.environ.get("EINK_FONT_DIR")


def test_unknown_role_is_an_error():
    with pytest.raises(KeyError):
        style.font("SMALL")


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(APP)))
def test_pages_do_not_load_fonts_or_use_raw_grays(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in {"truetype", "load_default"}:
                problems.append(f"line {node.lineno}: call {name}() - use style.font(role)")
            for kw in node.keywords:
                if kw.arg in {"fill", "outline"} and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, int) and kw.value.value not in (0, 255):
                    problems.append(f"line {node.lineno}: {kw.arg}={kw.value.value} - use a style.* ink")
        if isinstance(node, ast.ImportFrom) and node.module == "PIL" and any(a.name == "ImageFont" for a in node.names):
            problems.append(f"line {node.lineno}: imports ImageFont - fonts come from app.style")
    assert not problems, f"{path.name} breaks the style rules:\n  " + "\n  ".join(problems)


def _is_interlude(rel):
    return rel.startswith("greetings/") or rel == "preview_greetings.py"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(APP)))
def test_novelty_face_only_on_interludes(path):
    """The SPOOKY display face is a documented exception for interludes, never for data pages."""
    if _is_interlude(path.relative_to(APP).as_posix()):
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value in style.INTERLUDE_ROLES]
    assert not used, f"{path.name} uses an interlude-only role on lines {used}; see STYLE_GUIDE 'Display-face exception'"


@pytest.mark.parametrize("role", sorted(style.INTERLUDE_ROLES))
def test_display_faces_are_bundled_with_their_license(role):
    """Every display face is a bundled SIL OFL font with its license next to it (OFL-<Family>.txt)."""
    family = style._FILES[style.ROLES[role][1]].split("-")[0]
    assert style.font(role).getname()[0].replace(" ", "") == family
    assert "Open Font License" in (style._BUNDLED / f"OFL-{family}.txt").read_text(encoding="utf-8")
