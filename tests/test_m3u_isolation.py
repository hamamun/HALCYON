"""Phase 2 isolation checks — §A.1/§A.2. AST-based: no Qt import needed.

These pin the promises the whole phase contract rests on:

* M3U never imports Local (or Web) — modes are independent (rule 1);
* the registry lists m3u exactly once, after local, via the single permitted
  edit to ``core/modes.py``;
* the M3U spec declares the real frozen ModeSpec fields (the ``controls=...``
  draft never shipped — plan v3.2);
* the parser layer stays Qt-free, so it is testable headless.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M3U_DIR = ROOT / "modes" / "m3u"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_m3u_imports_no_other_mode() -> None:
    for path in M3U_DIR.rglob("*.py"):
        for name in _imports(path):
            assert not name.startswith(("modes.local", "modes.web")), (
                f"{path.name} imports {name!r} — modes must be independent (§A.1)"
            )
            assert name != "modes" or path.name == "__init__.py"


def test_m3u_imports_no_project_package_beyond_core_engine_itself() -> None:
    # Project top-levels — anything else (stdlib, PySide6) is fine by definition.
    project_packages = {"core", "engine", "modes", "ui", "Halcyon", "tools", "tests"}
    for path in M3U_DIR.rglob("*.py"):
        for name in _imports(path):
            top = name.split(".")[0]
            if top not in project_packages:
                continue
            assert top in {"core", "engine"} or name.startswith("modes.m3u"), (
                f"{path.name} imports unexpected project package {name!r}"
            )


def test_registry_appends_m3u_after_local() -> None:
    tree = ast.parse((ROOT / "core" / "modes.py").read_text(encoding="utf-8"),
                     filename="core/modes.py")
    registry = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REGISTRY":
                    registry = node.value
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "REGISTRY":
            registry = node.value
    assert registry is not None and isinstance(registry, ast.List)
    entries = [e for e in registry.elts if isinstance(e, ast.Attribute)]
    names = [e.value.id for e in entries]
    assert [e.attr for e in entries] == ["SPEC"] * len(entries)
    assert names[:2] == ["local", "m3u"], (
        "REGISTRY must keep M3U appended immediately after Local"
    )


def test_m3u_spec_declares_real_fields() -> None:
    tree = ast.parse((M3U_DIR / "__init__.py").read_text(encoding="utf-8"),
                     filename="modes/m3u/__init__.py")
    call = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", "")) == "ModeSpec"
        ):
            call = node
    assert call is not None, "SPEC = ModeSpec(...) not found"
    keywords = {kw.arg for kw in call.keywords if kw.arg}
    assert "controls" not in keywords, "the controls=[...] draft never shipped (plan v3.2)"
    for required in ("id", "title", "panel_qml", "transport_qml", "osd_enabled", "setup"):
        assert required in keywords, f"ModeSpec missing {required}"


def test_parser_is_qt_free() -> None:
    for module in ("parser.py", "sources.py"):
        for name in _imports(M3U_DIR / module):
            assert not name.startswith("PySide6"), (
                f"{module} must stay Qt-free (headless-testable)"
            )
