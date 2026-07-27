"""The QML module tree must actually describe the files on disk — §A.5.

The failure this guards against is quiet and expensive: QML resolves
``import Halcyon.Panels`` by looking for ``<import path>/Halcyon/Panels/qmldir``.
Nothing verifies that at import time, so a missing module directory or a typo'd
relative path shows up only when the window fails to load, as

    Main.qml:263:13: InfoPanel is not a type

These checks are pure Python — no Qt, no display, no libVLC — so they run
anywhere and fail loudly on the offending line instead of at startup.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_ROOT = ROOT / "Halcyon"

#: Modules provided by Qt itself or registered from Python (``@QmlElement``),
#: neither of which has a qmldir in this repository.
EXTERNAL_MODULES = {"Halcyon.Engine"}

IMPORT_RE = re.compile(r"^\s*import\s+(Halcyon\.[A-Za-z0-9_.]+)", re.MULTILINE)


def qmldir_files() -> list[Path]:
    return sorted(MODULE_ROOT.rglob("qmldir"))


def parse_qmldir(path: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(module_uri, [(type_name, relative_path), ...])``."""
    module = ""
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "module":
            module = parts[1]
            continue
        if parts[0] == "singleton":
            parts = parts[1:]
        if len(parts) >= 3:
            entries.append((parts[0], parts[2]))
    return module, entries


def repo_qml_files() -> list[Path]:
    return sorted(
        p
        for d in ("ui", "modes")
        for p in (ROOT / d).rglob("*.qml")
    )


def test_module_root_exists() -> None:
    assert MODULE_ROOT.is_dir(), (
        "Halcyon/ is the QML import root — without it no `import Halcyon.*` resolves"
    )
    assert qmldir_files(), "no qmldir files found under Halcyon/"


@pytest.mark.parametrize("qmldir", qmldir_files(), ids=lambda p: str(p.parent.name))
def test_module_uri_matches_directory(qmldir: Path) -> None:
    """``module Halcyon.Ui`` must live in ``Halcyon/Ui/`` — Qt maps URI to path."""
    module, _ = parse_qmldir(qmldir)
    expected = ".".join(qmldir.parent.relative_to(ROOT).parts)
    assert module == expected, (
        f"{qmldir.relative_to(ROOT)} declares '{module}' but its path spells "
        f"'{expected}'. Qt resolves imports by path, so these must agree."
    )


@pytest.mark.parametrize("qmldir", qmldir_files(), ids=lambda p: str(p.parent.name))
def test_declared_files_exist(qmldir: Path) -> None:
    module, entries = parse_qmldir(qmldir)
    assert entries, f"{qmldir.relative_to(ROOT)} declares no types"
    for type_name, rel in entries:
        target = (qmldir.parent / rel).resolve()
        assert target.is_file(), (
            f"{module}.{type_name} -> {rel} does not exist "
            f"(resolved to {target})"
        )


def test_every_imported_module_is_provided() -> None:
    """Every ``import Halcyon.X`` in the repo resolves to a real module."""
    provided = {parse_qmldir(q)[0] for q in qmldir_files()} | EXTERNAL_MODULES
    missing: list[str] = []
    for qml in repo_qml_files():
        for module in IMPORT_RE.findall(qml.read_text(encoding="utf-8")):
            if module not in provided:
                missing.append(f"{qml.relative_to(ROOT)} imports {module}")
    assert not missing, "unresolvable QML imports:\n  " + "\n  ".join(missing)


def test_every_type_used_is_imported() -> None:
    """A type used in a .qml must come from a module that file imports.

    This is the check that catches the original bug: Main.qml used ``InfoPanel``
    and ``Osd`` while importing only Halcyon.Ui and Halcyon.Shell.
    """
    # type name -> set of modules exporting it
    exporters: dict[str, set[str]] = {}
    for qmldir in qmldir_files():
        module, entries = parse_qmldir(qmldir)
        for type_name, _ in entries:
            exporters.setdefault(type_name, set()).add(module)

    problems: list[str] = []
    for qml in repo_qml_files():
        text = qml.read_text(encoding="utf-8")
        imported = set(IMPORT_RE.findall(text))
        # Types declared by this file's own directory resolve implicitly.
        siblings = {p.stem for p in qml.parent.glob("*.qml")}
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            m = re.match(r"^([A-Z][A-Za-z0-9_]*)\s*\{", stripped)
            if not m:
                continue
            name = m.group(1)
            if name in siblings or name not in exporters:
                continue  # own directory, or a Qt/registered type
            if not (exporters[name] & imported):
                want = " or ".join(sorted(exporters[name]))
                problems.append(
                    f"{qml.relative_to(ROOT)}:{line_no}: uses {name} "
                    f"but does not import {want}"
                )
    assert not problems, "missing QML imports:\n  " + "\n  ".join(problems)


def test_no_duplicate_type_registrations() -> None:
    """One implementation per type.

    Two qmldir entries pointing at different files for the same
    ``Module.Type`` is ambiguous; for a singleton it silently yields two
    instances and two sources of truth.
    """
    seen: dict[tuple[str, str], str] = {}
    duplicates: list[str] = []
    for qmldir in qmldir_files():
        module, entries = parse_qmldir(qmldir)
        for type_name, rel in entries:
            key = (module, type_name)
            target = str((qmldir.parent / rel).resolve())
            if key in seen and seen[key] != target:
                duplicates.append(f"{module}.{type_name}: {seen[key]} vs {target}")
            seen[key] = target
    assert not duplicates, "duplicate registrations:\n  " + "\n  ".join(duplicates)


def test_no_stale_qmldir_outside_module_root() -> None:
    """Source directories must not carry their own qmldir.

    ``ui/panels/qmldir`` never provided ``Halcyon.Panels`` — Qt would only have
    found it at ``Halcyon/Panels/qmldir`` — but its presence makes the module
    look defined and hides the real problem.
    """
    stray = [
        p.relative_to(ROOT)
        for d in ("ui", "modes", "core", "engine")
        for p in (ROOT / d).rglob("qmldir")
    ]
    assert not stray, (
        "qmldir outside Halcyon/ does not define a module: "
        + ", ".join(str(s) for s in stray)
    )


def test_shader_property_names_match_qml() -> None:
    """ShaderEffect sampler properties must match the .frag uniforms.

    They also must not collide with Item properties: ``property variant y``
    shadows ``Item.y`` and QML rejects the whole component.
    """
    frag = (ROOT / "ui" / "shaders" / "yuv420p.frag").read_text(encoding="utf-8")
    stage = (ROOT / "ui" / "shell" / "VideoStage.qml").read_text(encoding="utf-8")
    samplers = set(re.findall(r"uniform\s+sampler2D\s+(\w+)\s*;", frag))
    assert samplers, "no samplers found in yuv420p.frag"

    reserved = {"x", "y", "z", "width", "height", "opacity", "scale", "rotation"}
    clashing = samplers & reserved
    assert not clashing, (
        f"sampler name(s) {sorted(clashing)} shadow built-in Item properties"
    )

    declared = set(re.findall(r"property\s+variant\s+(\w+)\s*:", stage))
    assert samplers <= declared, (
        f"VideoStage.qml is missing sampler propert(ies) {sorted(samplers - declared)}"
    )
