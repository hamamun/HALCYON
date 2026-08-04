#!/usr/bin/env python3
"""Isolation guard — §A.5.

Makes §A.1's promise enforceable instead of aspirational. Run before every merge;
CI runs it too.

Three rules:

1. **No mode imports another mode.** M3U's parser must never touch Local. If it
   does, deleting one breaks the other and the "three channels, one radio"
   contract is a lie.
2. **Nothing shared imports a mode.** ``engine/``, ``core/`` and ``ui/shell/``
   are the chassis; they cannot know what band is tuned in. The single, explicit
   exception is ``core/modes.py``, whose entire job is the registry.
3. **A later phase does not edit a frozen earlier-phase path.** Checked against
   git when a phase tag exists.

Also verifies the mechanical test from §A.2: with ``modes/m3u`` and
``modes/web`` deleted, nothing outside those directories still refers to them.

    python tools/check_isolation.py          # rules 1 and 2, plus dangling refs
    python tools/check_isolation.py --phase 2   # adds the frozen-path check
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODES_DIR = ROOT / "modes"

#: Directories that make up the shared chassis (§A.3 rule 3).
SHARED_DIRS = ["engine", "core", "ui/shell", "ui/components", "ui/transport"]

#: The one file allowed to import modes — it *is* the extension point.
REGISTRY_FILE = ROOT / "core" / "modes.py"

#: Paths frozen at Phase 1 sign-off. A phase-2+ change to any of these means the
#: foundation was wrong; fix Phase 1 rather than patching around it (§A.3).
PHASE1_FROZEN = [
    "engine/",
    "core/mode_api.py",
    "core/settings.py",
    "core/paths.py",
    "ui/shell/",
    "ui/components/",
    "ui/transport/",
    "ui/Theme.qml",
    "ui/Actions.qml",
    "main.py",
]

#: ...except this one line, which each phase appends to (§A.2).
FROZEN_EXCEPTIONS = ["core/modes.py"]

#: Disclosed Phase-2 fixes to frozen Phase 1 paths — the guard's own rule 3
#: wording says it outright: "If a later phase needs this, the foundation is
#: wrong — fix Phase 1 properly." Phase 1 shipped the reader refcount and the
#: ring *for* §P2.5 ("PiP calls it on its own surface against the same
#: VideoOutput") but left the notification path as single-slot attributes, so
#: a second surface silently disconnected the first. Completing the
#: multi-reader contract is a foundation fix, not a workaround; each entry
#: names the exact files and must carry a comment when added.
PHASE2_DISCLOSED = [
    # Fan-out every frame/format/stop notification to all registered readers
    # (§P2.5); VideoSurface now registers per-surface callbacks instead of
    # overwriting the engine's single slots. Regression-tested in
    # tests/test_video_pip_notify.py.
    "engine/video_out.py",
    "engine/surface.py",
]

#: Disclosed Phase-3 additions to frozen Phase 1 paths — generic v4.0 mode
#: capability changes (§P3.3, §A.3 rule 1): ``panel_enabled`` (no left dock in
#: Web) and ``keep_stage_alive`` (stage parked on switch so web tabs/pages
#: survive mode changes), plus COM/pythonnet bootstrap in main.py and shell UI
#: integration. Each change is documented in the v4.0 changelog and covered by
#: regression tests.
PHASE3_DISCLOSED = [
    "core/mode_api.py",
    "main.py",
    "ui/Main.qml",
    "ui/shell/Stage.qml",
    "ui/shell/PanelHost.qml",
]


class Failure:
    def __init__(self, rule: str, where: str, detail: str) -> None:
        self.rule = rule
        self.where = where
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.rule}] {self.where}\n    {self.detail}"


def python_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return [p for p in directory.rglob("*.py") if "__pycache__" not in p.parts]


def qml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return list(directory.rglob("*.qml"))


def installed_modes() -> list[str]:
    if not MODES_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in MODES_DIR.iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    )


def imported_names(path: Path) -> list[tuple[str, int]]:
    """Every module path imported by ``path``, with line numbers."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [(f"<syntax error: {exc}>", exc.lineno or 0)]
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.append((node.module, node.lineno))
    return found


def check_mode_cross_imports(modes: list[str]) -> list[Failure]:
    """Rule 1 — no mode imports another mode."""
    failures: list[Failure] = []
    for mode in modes:
        others = [m for m in modes if m != mode]
        for py in python_files(MODES_DIR / mode):
            rel = py.relative_to(ROOT)
            for name, line in imported_names(py):
                for other in others:
                    if name == f"modes.{other}" or name.startswith(f"modes.{other}."):
                        failures.append(
                            Failure(
                                "rule 1",
                                f"{rel}:{line}",
                                f"mode '{mode}' imports mode '{other}' "
                                f"({name}) — modes must be independent (§A.1)",
                            )
                        )
        # QML side: a mode must not load another mode's components either.
        for qml in qml_files(MODES_DIR / mode):
            rel = qml.relative_to(ROOT)
            text = qml.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                for other in others:
                    if f"modes/{other}" in line:
                        failures.append(
                            Failure(
                                "rule 1",
                                f"{rel}:{lineno}",
                                f"mode '{mode}' references mode '{other}' in QML",
                            )
                        )
    return failures


def check_shared_does_not_import_modes(modes: list[str]) -> list[Failure]:
    """Rule 2 — the chassis does not know about the bands."""
    failures: list[Failure] = []
    for shared in SHARED_DIRS:
        for py in python_files(ROOT / shared):
            if py.resolve() == REGISTRY_FILE.resolve():
                continue
            rel = py.relative_to(ROOT)
            for name, line in imported_names(py):
                if name == "modes" or name.startswith("modes."):
                    failures.append(
                        Failure(
                            "rule 2",
                            f"{rel}:{line}",
                            f"shared code imports '{name}' — only core/modes.py "
                            f"may reference modes (§A.3)",
                        )
                    )
        for qml in qml_files(ROOT / shared):
            rel = qml.relative_to(ROOT)
            text = qml.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "modes/" in line and "ModeSpec" not in line:
                    failures.append(
                        Failure(
                            "rule 2",
                            f"{rel}:{lineno}",
                            "shared QML hardcodes a mode path — it must come "
                            "from ModeSpec instead (§A.2)",
                        )
                    )
    return failures


def check_no_dangling_mode_refs(modes: list[str]) -> list[Failure]:
    """§A.2's mechanical test, statically: nothing outside ``modes/`` may name a
    mode that is not installed."""
    failures: list[Failure] = []
    known = set(modes)
    search_dirs = [ROOT / d for d in SHARED_DIRS] + [ROOT / "ui", ROOT / "tests"]
    for directory in search_dirs:
        for py in python_files(directory):
            rel = py.relative_to(ROOT)
            for name, line in imported_names(py):
                if name.startswith("modes."):
                    mode = name.split(".")[1]
                    if mode not in known:
                        failures.append(
                            Failure(
                                "dangling",
                                f"{rel}:{line}",
                                f"references mode '{mode}', which is not installed",
                            )
                        )
    return failures


def changed_files(base_ref: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def check_frozen_paths(base_ref: str) -> list[Failure]:
    """Rule 3 — a phase-2+ change must not touch frozen Phase 1 paths.

    ``PHASE2_DISCLOSED`` names the exception files and the reason each one is
    there; anything else on a frozen path is still a rule-3 failure.
    """
    failures: list[Failure] = []
    for path in changed_files(base_ref):
        if path in FROZEN_EXCEPTIONS or path in PHASE2_DISCLOSED or path in PHASE3_DISCLOSED:
            continue
        for frozen in PHASE1_FROZEN:
            hit = path.startswith(frozen) if frozen.endswith("/") else path == frozen
            if hit:
                failures.append(
                    Failure(
                        "rule 3",
                        path,
                        f"frozen Phase 1 path modified since {base_ref}. "
                        f"If a later phase needs this, the foundation is wrong — "
                        f"fix Phase 1 properly (§A.3 rule 1).",
                    )
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        type=int,
        default=1,
        help="phase being checked; 2+ also enforces the frozen-path rule",
    )
    parser.add_argument(
        "--base",
        default="v0.1.0-local",
        help="git ref that froze Phase 1 (default: the v0.1.0-local tag)",
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    modes = installed_modes()
    failures: list[Failure] = []
    failures += check_mode_cross_imports(modes)
    failures += check_shared_does_not_import_modes(modes)
    failures += check_no_dangling_mode_refs(modes)
    if args.phase >= 2:
        failures += check_frozen_paths(args.base)

    if failures:
        print(f"isolation check FAILED — {len(failures)} problem(s)\n", file=sys.stderr)
        for failure in failures:
            print(str(failure), file=sys.stderr)
            print(file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"isolation OK — modes installed: {', '.join(modes) or '(none)'}")
        print(f"  rule 1  no mode imports another mode")
        print(f"  rule 2  nothing shared imports a mode (except core/modes.py)")
        print(f"  rule 3  frozen-path check {'on' if args.phase >= 2 else 'off (phase 1)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
