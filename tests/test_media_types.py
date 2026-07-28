"""Media-type knowledge belongs to the chassis, not to a mode — §A.3.

``core/app.py`` used to reach into ``modes.local.playlist`` to ask "is this a
subtitle?". It did so lazily, to soften the coupling, but the dependency was
real and ``tools/check_isolation.py`` reported it on every run as a rule 2
violation: *nothing shared imports a mode*.

The dependency was also the wrong way round. "``.srt`` is a subtitle" is a fact
about media, not about Local's queue, and Phase 2's M3U and Phase 3's Web need
the same answer. Deleting ``modes/local`` must not take it with them — which is
the mechanical test §A.2 describes.

So the sets moved down into ``core/media_types.py`` and the mode re-exports
them. These tests pin both halves: the knowledge is reachable without a mode,
and the mode's public names still work so nothing that imported them broke.
"""

from __future__ import annotations

import ast
from pathlib import Path

from core import media_types

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------- the answers ---
class TestClassification:
    def test_common_video_containers(self):
        for name in ("a.mkv", "a.mp4", "a.avi", "a.mov", "a.webm", "a.ts"):
            assert media_types.is_video(name), name
            assert not media_types.is_audio(name), name

    def test_common_audio_formats(self):
        for name in ("a.mp3", "a.flac", "a.opus", "a.m4a", "a.wav"):
            assert media_types.is_audio(name), name
            assert not media_types.is_video(name), name

    def test_subtitles_are_not_media(self):
        for name in ("a.srt", "a.ass", "a.ssa", "a.sub", "a.vtt"):
            assert media_types.is_subtitle(name), name
            assert not media_types.is_media(name), (
                f"{name} in the queue makes libVLC open it as a track with no "
                "video and no audio, tearing the pipeline down"
            )

    def test_video_and_audio_do_not_overlap(self):
        assert not (media_types.VIDEO_EXTENSIONS & media_types.AUDIO_EXTENSIONS)

    def test_media_is_exactly_video_plus_audio(self):
        assert media_types.MEDIA_EXTENSIONS == (
            media_types.VIDEO_EXTENSIONS | media_types.AUDIO_EXTENSIONS
        )

    def test_case_is_ignored(self):
        assert media_types.is_video("FILM.MKV")
        assert media_types.is_subtitle("SUBS.SRT")

    def test_a_full_path_works_not_just_a_name(self):
        assert media_types.is_video(r"E:\drvie personal\Andor S02E01.mkv")

    def test_an_unknown_extension_is_nothing_in_particular(self):
        assert not media_types.is_video("notes.txt")
        assert not media_types.is_audio("notes.txt")


# ------------------------------------------------------------- the isolation ---
class TestIsolation:
    def test_core_does_not_import_a_mode(self):
        """The rule 2 violation, pinned so it cannot come back.

        Checked by parsing rather than by running the guard script, so the
        failure names the file and line directly.
        """
        offenders = []
        for py in (ROOT / "core").rglob("*.py"):
            if py.name == "modes.py":       # the registry — the one exception
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name == "modes" or name.startswith("modes."):
                        offenders.append(
                            f"{py.relative_to(ROOT)}:{node.lineno} imports {name}"
                        )
        assert not offenders, "core must not depend on a mode (§A.3):\n  " + "\n  ".join(
            offenders
        )

    def test_media_types_needs_no_mode_to_import(self):
        """The mechanical test from §A.2, for this module.

        Parsed, not grepped: the module's docstring explains *why* it no longer
        lives under ``modes/``, so a plain text search finds the word in the
        prose and fails the file for documenting itself.
        """
        path = ROOT / "core" / "media_types.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [n for n in imported if n == "modes" or n.startswith("modes.")]

    def test_the_mode_still_exports_the_old_names(self):
        """Moving the sets must not break anything that imported them."""
        from modes.local import playlist

        assert playlist.VIDEO_EXTENSIONS is media_types.VIDEO_EXTENSIONS
        assert playlist.AUDIO_EXTENSIONS is media_types.AUDIO_EXTENSIONS
        assert playlist.MEDIA_EXTENSIONS == media_types.MEDIA_EXTENSIONS
        assert playlist.SUBTITLE_EXTENSIONS is media_types.SUBTITLE_EXTENSIONS

    def test_there_is_only_one_definition_of_each_set(self):
        """Re-exported, not re-declared — two copies would drift."""
        source = (ROOT / "modes" / "local" / "playlist.py").read_text(encoding="utf-8")

        assert "VIDEO_EXTENSIONS = {" not in source
        assert "SUBTITLE_EXTENSIONS = {" not in source
