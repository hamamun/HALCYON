#!/usr/bin/env python3
"""Compile ``ui/shaders/*.frag`` to ``.qsb`` — Milestone 1.0 / 1.9.

``.qsb`` files are build products, so they are gitignored and regenerated here.
Run after touching any shader, and as part of the packaging step (a missing
``.qsb`` shows up as black video, which is a confusing way to find out).

    python tools/build_shaders.py [--check]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHADER_DIR = ROOT / "ui" / "shaders"

# Targets: GLSL for desktop/ES, HLSL for D3D11 (the Windows default), MSL for
# completeness. Qt picks whichever the active RHI backend needs.
QSB_ARGS = ["--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12"]


def find_qsb() -> str | None:
    for name in ("pyside6-qsb", "qsb"):
        path = shutil.which(name)
        if path:
            return path
    # venv layout when not on PATH
    for candidate in (
        Path(sys.executable).parent / "pyside6-qsb",
        Path(sys.executable).parent / "pyside6-qsb.exe",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _shader_sources() -> list[Path]:
    return sorted(SHADER_DIR.glob("*.frag")) + sorted(SHADER_DIR.glob("*.vert"))


def build_all() -> tuple[int, int]:
    """Compile every shader source under ``ui/shaders``.

    Returns ``(built, failed)``. When the ``qsb`` tool is unavailable, every
    source counts as failed so callers can tell nothing was produced (the
    ``.qsb`` files simply will not exist). Importable from :mod:`main` so the
    first run can self-heal a missing shader instead of silently dropping to
    the RV32 fallback.
    """
    sources = _shader_sources()
    if not sources:
        return 0, 0

    qsb = find_qsb()
    if not qsb:
        return 0, len(sources)

    built = failed = 0
    for src in sources:
        out = src.with_suffix(src.suffix + ".qsb")
        cmd = [qsb, *QSB_ARGS, "-o", str(out), str(src)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            failed += 1
            print(f"FAIL {src.name}\n{result.stderr.strip()}", file=sys.stderr)
        else:
            built += 1
            print(f"  ok {src.name} -> {out.name}")
    return built, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report which shaders are missing or stale; compile nothing",
    )
    args = parser.parse_args()

    sources = _shader_sources()
    if not sources:
        print("no shader sources found in", SHADER_DIR)
        return 0

    stale = [
        src
        for src in sources
        if not (out := src.with_suffix(src.suffix + ".qsb")).exists()
        or out.stat().st_mtime < src.stat().st_mtime
    ]

    if args.check:
        for src in stale:
            print("STALE:", src.relative_to(ROOT))
        if stale:
            print(f"\n{len(stale)} shader(s) need compiling: python tools/build_shaders.py")
            return 1
        print(f"all {len(sources)} shader(s) up to date")
        return 0

    if not find_qsb():
        print("error: pyside6-qsb not found — is PySide6 installed in this venv?",
              file=sys.stderr)
        return 2

    built, failed = build_all()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
