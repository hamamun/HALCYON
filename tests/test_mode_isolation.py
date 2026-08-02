"""Architecture checks for keeping shared core code mode-neutral."""

from __future__ import annotations

import ast
from pathlib import Path


def test_core_app_does_not_import_local_mode() -> None:
    """Shared app controller must not reach into Local mode implementation.

    Local, M3U and future modes are registered through the mode API; core code
    may use core-level helpers but must not import from a concrete mode package.
    """
    tree = ast.parse(Path("core/app.py").read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                assert not module.startswith("modes.local"), (
                    f"core/app.py imports concrete mode module {module!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("modes.local"), (
                f"core/app.py imports concrete mode module {module!r}"
            )
