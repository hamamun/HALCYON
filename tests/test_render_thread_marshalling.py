"""QML-facing signals never fire from Qt Quick's render thread."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "engine" / "surface.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def _method(name: str) -> str:
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"method {name!r} not found")


def test_update_paint_node_does_not_emit_qml_facing_signals():
    # There are two overrides; inspect the VideoSurface one specifically.
    video_surface = SOURCE.read_text(encoding="utf-8").split("class VideoSurface", 1)[1]
    paint = video_surface.split("def updatePaintNode", 1)[1].split("def _plane_view", 1)[0]
    assert "frameRendered.emit" not in paint
    assert "_set_has_video" not in paint
    assert "frameCommitted.emit" in paint


def test_render_completion_is_delivered_by_gui_slot():
    slot = _method("_on_frame_committed_gui")
    assert "_set_has_video(True)" in slot
    assert "frameRendered.emit()" in slot
    source = SOURCE.read_text(encoding="utf-8")
    assert "self._on_frame_committed_gui, Qt.ConnectionType.QueuedConnection" in source


def test_decoder_format_callback_only_marshals_the_immutable_format():
    callback = _method("_on_format_threadsafe")
    assert "self._fmt =" not in callback
    assert "formatArrived.emit(fmt)" in callback


def test_render_reader_releases_the_same_generation_claim():
    source = SOURCE.read_text(encoding="utf-8")
    video_surface = source.split("class VideoSurface", 1)[1]
    paint = video_surface.split("def updatePaintNode", 1)[1].split("def _plane_view", 1)[0]
    assert "release_read(claim)" in paint
