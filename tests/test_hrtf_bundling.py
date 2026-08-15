"""Bundled SOFA HRTF discovery — the binauralizer's data file.

libVLC's ``spatialaudio`` filter builds its default HRTF path as
``config_GetDataDir() + "/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa"``, and on
Windows ``config_GetDataDir()`` is ``VLC_DATA_PATH`` when set, otherwise the
directory holding ``libvlccore.dll``. Our bundle puts that DLL in
``vendor/vlc``, so the canonical location is ``vendor/vlc/hrtfs/``.

The failure mode this guards is deliberately quiet: a missing HRTF makes
libVLC print "Could not load the SOFA HRTF" *to stderr* — outside Halcyon's
logging — and then downmix anyway. Audio keeps playing, so nothing looks
broken; only binaural spatialisation is gone. These tests pin the discovery
rules so a packaging change cannot silently reintroduce that.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_hrtf_helpers():
    """Extract the HRTF helpers without importing PySide6.

    ``engine.vlc_engine`` pulls in PySide6 at import time, which a headless
    container may not have. The functions under test are pure path logic, so
    they are compiled out of the module source instead — that keeps this test
    meaningful on a box with no Qt, exactly like the other engine tests.
    """
    tree = ast.parse((ROOT / "engine" / "vlc_engine.py").read_text())
    wanted_funcs = {"find_bundled_hrtf", "_instance_args"}
    wanted_consts = {"BASE_VLC_ARGS", "HRTF_DIR_NAME", "DEFAULT_HRTF_NAME"}
    body = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted_funcs)
        or (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") in wanted_consts
        )
    ]
    namespace: dict = {"Path": Path, "log": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<hrtf>", "exec"), namespace)
    return namespace


HRTF = _load_hrtf_helpers()
find_bundled_hrtf = HRTF["find_bundled_hrtf"]
_instance_args = HRTF["_instance_args"]
BASE_VLC_ARGS = HRTF["BASE_VLC_ARGS"]
DEFAULT_HRTF_NAME = HRTF["DEFAULT_HRTF_NAME"]
HRTF_DIR_NAME = HRTF["HRTF_DIR_NAME"]


def _hrtf_flags(base) -> list[str]:
    return [arg for arg in _instance_args(base) if "hrtf" in arg]


def test_canonical_layout_needs_no_option(tmp_path: Path) -> None:
    """hrtfs/<canonical name> is what libVLC finds unaided.

    Passing --hrtf-file here would be redundant, so the argument list must
    stay identical to the base one.
    """
    (tmp_path / HRTF_DIR_NAME).mkdir()
    (tmp_path / HRTF_DIR_NAME / DEFAULT_HRTF_NAME).write_bytes(b"sofa")

    found, needs_option = find_bundled_hrtf(tmp_path)

    assert found is not None and found.name == DEFAULT_HRTF_NAME
    assert needs_option is False
    assert _hrtf_flags(tmp_path) == []
    assert _instance_args(tmp_path) == BASE_VLC_ARGS


def test_loose_sofa_in_vendor_root_is_rescued(tmp_path: Path) -> None:
    """A .sofa dropped straight into vendor/vlc/ still works.

    libVLC cannot find it there — it only looks in hrtfs/ — so this is exactly
    the case that must produce an explicit --hrtf-file rather than a silent
    loss of spatial audio.
    """
    sofa = tmp_path / DEFAULT_HRTF_NAME
    sofa.write_bytes(b"sofa")

    found, needs_option = find_bundled_hrtf(tmp_path)

    assert found == sofa
    assert needs_option is True
    assert _hrtf_flags(tmp_path) == [f"--hrtf-file={sofa}"]


def test_renamed_sofa_is_pointed_at_explicitly(tmp_path: Path) -> None:
    """Only the canonical filename auto-loads, so a custom one needs the flag."""
    (tmp_path / HRTF_DIR_NAME).mkdir()
    sofa = tmp_path / HRTF_DIR_NAME / "my_own_ears.sofa"
    sofa.write_bytes(b"sofa")

    found, needs_option = find_bundled_hrtf(tmp_path)

    assert found == sofa
    assert needs_option is True
    assert _hrtf_flags(tmp_path) == [f"--hrtf-file={sofa}"]


def test_canonical_wins_over_a_loose_file(tmp_path: Path) -> None:
    """With both present, prefer the one libVLC resolves by itself."""
    (tmp_path / HRTF_DIR_NAME).mkdir()
    canonical = tmp_path / HRTF_DIR_NAME / DEFAULT_HRTF_NAME
    canonical.write_bytes(b"sofa")
    (tmp_path / "stray.sofa").write_bytes(b"sofa")

    found, needs_option = find_bundled_hrtf(tmp_path)

    assert found == canonical
    assert needs_option is False


@pytest.mark.parametrize("base", [None])
def test_no_vendor_dir_is_not_an_error(base) -> None:
    """A system-libVLC dev box has no vendor dir; that must not add options."""
    assert find_bundled_hrtf(base) == (None, False)
    assert _instance_args(base) == BASE_VLC_ARGS


def test_missing_hrtf_leaves_playback_arguments_untouched(tmp_path: Path) -> None:
    """No HRTF is a degraded-audio condition, never a playback-blocking one."""
    found, needs_option = find_bundled_hrtf(tmp_path)

    assert found is None and needs_option is False
    assert _instance_args(tmp_path) == BASE_VLC_ARGS


def test_avcodec_hw_none_survives_the_hrtf_addition(tmp_path: Path) -> None:
    """The vmem/green-picture guard must not be displaced by the new option."""
    (tmp_path / HRTF_DIR_NAME).mkdir()
    (tmp_path / HRTF_DIR_NAME / "x.sofa").write_bytes(b"sofa")

    args = _instance_args(tmp_path)

    assert "--avcodec-hw=none" in args
    assert args[: len(BASE_VLC_ARGS)] == BASE_VLC_ARGS


def test_packaging_ships_the_hrtf_directory() -> None:
    """The frozen build must keep hrtfs/ beside libvlccore.dll.

    Nuitka only copies what it is told to; without this the source checkout
    has spatial audio and the packaged build quietly does not.
    """
    build_script = (ROOT / "tools" / "build_nuitka.py").read_text()

    assert "vendor/vlc/hrtfs" in build_script
    assert 'vendor" / "vlc" / "hrtfs"' in build_script


def test_update_tab_lists_the_hrtf_folder() -> None:
    """The Update tab's copy-these-files guidance must mention hrtfs/."""
    from core import update_checker as uc

    assert any("hrtfs" in name for name, _ in uc.VLC_FILES)
    assert any("hrtfs" in path for path, _ in uc.VLC_PLACE_PATHS)
