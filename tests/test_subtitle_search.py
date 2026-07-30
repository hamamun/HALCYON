"""Subtitle download backend and the embedded/local split.

Two pieces, both pure-Python so they run anywhere:

* ``core.app._split_subtitle_tracks`` decides which spu is embedded and which
  came from a file on disk. Getting this wrong shows a downloaded subtitle
  under "Subtitles" (or worse, hides the media's own track under "Local").
* ``core.subtitles.SubtitleBackend`` drives the download flyout. The state
  machine is exercised end to end with injected transports — the same code
  paths the GUI thread runs, minus sockets and Qt Quick.
"""

from __future__ import annotations

import urllib.error

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Property, Signal

from core.app import _name_key, _split_subtitle_tracks
from core import subtitles
from core.subtitles import (
    SubtitleBackend,
    _clean_languages,
    _http_error_message,
    _normalise_results,
    _rank_and_split,
    _target_path,
)


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


# ----------------------------------------------------------------------
# embedded vs local classification
# ----------------------------------------------------------------------
TRACKS = [
    {"id": -1, "label": "Disable"},
    {"id": 0, "label": "English"},
    {"id": 1, "label": "Forced - [English]"},
    {"id": 2, "label": "Movie.2024.1080p.srt"},
]


class TestSplitSubtitleTracks:
    def test_no_external_files_means_all_embedded(self):
        embedded, local = _split_subtitle_tracks(TRACKS, [])
        assert local == []
        assert [t["id"] for t in embedded] == [-1, 0, 1, 2]

    def test_exact_file_name_marks_local(self):
        embedded, local = _split_subtitle_tracks(TRACKS, ["Movie.2024.1080p.srt"])
        assert [t["id"] for t in local] == [2]
        assert [t["id"] for t in embedded] == [-1, 0, 1]

    def test_cosmetic_differences_still_match(self):
        # VLC's description form is not guaranteed: it may drop extension or
        # swap separators for spaces. The key function must absorb all of it.
        assert _name_key("Movie.2024-1080p[x].srt") == _name_key("movie 2024 1080p x srt")

    def test_embedded_tracks_survive_a_same_language_external(self):
        tracks = TRACKS + [{"id": 3, "label": "Bangla.sub"}]
        embedded, local = _split_subtitle_tracks(tracks, ["Bangla.sub"])
        assert [t["id"] for t in local] == [3]
        assert 0 in [t["id"] for t in embedded]

    def test_disable_row_never_classifies_as_local(self):
        embedded, local = _split_subtitle_tracks(
            [{"id": -1, "label": "Disable"}], ["Disable.srt"]
        )
        assert local == []
        assert [t["id"] for t in embedded] == [-1]


# ----------------------------------------------------------------------
# result shaping
# ----------------------------------------------------------------------
def _row(lang="en", downloads=0, rating=0, hd=False, trusted=False, name="rel"):
    return {
        "file_id": hash((name, lang)) % 100000,
        "file_name": f"{name}.{lang}.srt",
        "name": name,
        "lang": lang,
        "downloads": downloads,
        "rating": rating,
        "hd": hd,
        "trusted": trusted,
    }


class TestResultShaping:
    def test_normalise_drops_rows_without_file_id(self):
        payload = {"data": [
            {"attributes": {"language": "en", "release": "ok",
                            "files": [{"file_id": 5, "file_name": "a.srt"}]}},
            {"attributes": {"language": "en", "release": "no-id", "files": []}},
            {"attributes": {"language": "en", "release": "",
                            "files": [{"file_name": "b.srt", "file_id": 7}]}},
        ]}
        rows = _normalise_results(payload)
        assert [r["file_id"] for r in rows] == [5, 7]
        assert rows[1]["name"] == "b.srt"  # falls back to the file name

    def test_normalise_tolerates_garbage(self):
        assert _normalise_results(None) == []
        assert _normalise_results({"data": "nope"}) == []

    def test_best_is_three_and_prefers_language(self):
        rows = [_row("fr", downloads=90000, name="french-release"),
                _row("en", downloads=10, name="tiny-english"),
                _row("en", downloads=8000, rating=8, hd=True, trusted=True, name="top-english"),
                _row("en", downloads=50, name="noise"),
                _row("es", downloads=9999, name="spanish")]
        best, others = _rank_and_split(rows, ["en", "fr"])
        assert len(best) == 3
        assert best[0]["name"] == "top-english"
        assert "noise" in [r["name"] for r in others] or "spanish" in [r["name"] for r in others]

    def test_split_is_stable_for_equal_scores(self):
        rows = [_row("en", name="a"), _row("en", name="b"), _row("en", name="c"),
                _row("en", name="d")]
        first = _rank_and_split(rows, ["en"])
        second = _rank_and_split(rows, ["en"])
        assert [r["name"] for r in first[0]] == [r["name"] for r in second[0]]

    def test_languages_are_cleaned_and_defaulted(self):
        assert _clean_languages(["EN", " en ", "bn"]) == ["en", "bn"]
        assert _clean_languages([]) == ["en"]
        assert _clean_languages(None) == ["en"]


# ----------------------------------------------------------------------
# save naming
# ----------------------------------------------------------------------
class TestTargetPath:
    def test_first_choice_is_the_sidecar_name(self, tmp_path):
        media = tmp_path / "My Movie.mkv"
        assert _target_path(str(media), "whatever.srt", "en") == tmp_path / "My Movie.srt"

    def test_collision_adds_the_language(self, tmp_path):
        media = tmp_path / "My Movie.mkv"
        (tmp_path / "My Movie.srt").write_text("x", encoding="utf-8")
        assert _target_path(str(media), "x.srt", "en") == tmp_path / "My Movie.en.srt"

    def test_second_collision_adds_a_counter(self, tmp_path):
        media = tmp_path / "My Movie.mkv"
        for name in ("My Movie.srt", "My Movie.en.srt"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        assert _target_path(str(media), "x.srt", "en") == tmp_path / "My Movie.en.2.srt"

    def test_wire_suffix_is_not_trusted(self, tmp_path):
        media = tmp_path / "My Movie.mkv"
        assert _target_path(str(media), "evil.exe", "en").suffix == ".srt"


# ----------------------------------------------------------------------
# the backend, end to end with fake transports
# ----------------------------------------------------------------------
class _FakeController(QObject):
    """The surface SubtitleBackend uses: media identity and the attach slot."""

    mediaNameChanged = Signal()

    def __init__(self, media_path=""):
        super().__init__()
        self._media_path = media_path
        self.attached: list[str] = []

    def _get_stem(self) -> str:
        from pathlib import Path as _P

        return _P(self._media_path).stem if self._media_path else ""

    currentFileStem = Property(str, _get_stem, notify=mediaNameChanged)  # noqa: N803

    def current_media_path(self) -> str:
        return self._media_path

    def loadSubtitle(self, path: str) -> None:  # noqa: N802 - mirrors App slot
        self.attached.append(path)


def _settings(tmp_path, monkeypatch):
    from core import settings as settings_module

    monkeypatch.setattr(settings_module.paths, "seed_defaults", lambda: None)
    return settings_module.Settings(path=tmp_path / "settings.json")


def _drain(backend, predicate, timeout_ms=4000):
    """Run the event loop until `predicate()` or give up — QThread jobs are
    the real thing here, so assertions wait for them properly."""
    app = QCoreApplication.instance()
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


class TestBackend:
    def test_media_name_mirrors_controller(self, qt_app, tmp_path, monkeypatch):
        controller = _FakeController(str(tmp_path / "Some Film 2024.mkv"))
        backend = SubtitleBackend(_settings(tmp_path, monkeypatch), controller)
        assert backend.mediaName == "Some Film 2024"

    def test_search_needs_a_key_first(self, qt_app, tmp_path, monkeypatch):
        backend = SubtitleBackend(_settings(tmp_path, monkeypatch), _FakeController("m.mkv"))
        backend.search("anything")
        assert backend.statusIsError
        assert "API key" in backend.status

    def test_api_key_and_languages_persist(self, qt_app, tmp_path, monkeypatch):
        settings = _settings(tmp_path, monkeypatch)
        backend = SubtitleBackend(settings, _FakeController())
        backend.apiKey = " key-123 "
        backend.languages = ["en", "bn", "BN"]
        settings.flush()

        fresh = SubtitleBackend(_settings(tmp_path, monkeypatch), _FakeController())
        assert fresh.apiKey == "key-123"
        assert fresh.languages == ["en", "bn"]

    def test_search_populates_best_and_others(self, qt_app, tmp_path, monkeypatch):
        payload = {"data": [
            {"attributes": {"language": "en", "release": f"rel-{i}",
                            "download_count": 100 - i, "ratings": 1,
                            "files": [{"file_id": i + 1, "file_name": f"r{i}.srt"}]}}
            for i in range(5)
        ]}

        def transport(url, key, body):
            assert "api.opensubtitles.com" in url
            return payload, None

        backend = SubtitleBackend(
            _settings(tmp_path, monkeypatch), _FakeController("m.mkv"), transport=transport
        )
        backend.apiKey = "k"
        backend.search("some movie")

        _drain(backend, lambda: not backend.searching and "5" in backend.status)
        assert len(backend.bestResults) == 3
        assert len(backend.otherResults) == 2
        idxs = {r["idx"] for r in backend.bestResults + backend.otherResults}
        assert idxs == set(range(5))

    def test_http_error_becomes_a_friendly_status(self, qt_app, tmp_path, monkeypatch):
        def transport(url, key, body):
            try:
                raise urllib.error.HTTPError(url, 401, "no", {}, None)
            except urllib.error.HTTPError as exc:
                return None, _http_error_message(exc)  # what _default_transport does

        backend = SubtitleBackend(
            _settings(tmp_path, monkeypatch), _FakeController("m.mkv"), transport=transport
        )
        backend.apiKey = "bad"
        backend.search("some movie")

        _drain(backend, lambda: not backend.searching and backend.statusIsError)
        assert "API key rejected" in backend.status
        assert backend.bestResults == []

    def test_download_saves_next_to_media_and_loads_it(self, qt_app, tmp_path, monkeypatch):
        media = tmp_path / "Night Sky.mkv"
        media.write_bytes(b"v")
        calls = []

        def transport(url, key, body):
            calls.append((url, body))
            if body == {"file_id": 42}:
                return {"link": "https://cdn.example/dl", "file_name": "night.srt",
                        "remaining": 9}, None
            return {"data": [
                {"attributes": {"language": "en", "release": "Night.Sky.2024",
                                "files": [{"file_id": 42, "file_name": "night.srt"}]}}
            ]}, None

        def transport_bytes(url, key):
            return b"1\n00:00:01,000 --> 00:00:02,000\nhello\n", None

        controller = _FakeController(str(media))
        backend = SubtitleBackend(
            _settings(tmp_path, monkeypatch), controller,
            transport=transport, transport_bytes=transport_bytes,
        )
        backend.apiKey = "k"
        backend.search("night sky")
        _drain(backend, lambda: not backend.searching)

        row = backend.bestResults[0]
        backend.download(row["idx"])

        _drain(backend, lambda: backend.busyIndex == -1 and "Loaded" in backend.status)
        saved = tmp_path / "Night Sky.srt"
        assert saved.read_text(encoding="utf-8").startswith("1\n")
        assert controller.attached == [str(saved)]

    def test_download_without_media_refuses_cleanly(self, qt_app, tmp_path, monkeypatch):
        def transport(url, key, body):
            return {"data": [
                {"attributes": {"language": "en", "release": "x",
                                "files": [{"file_id": 1, "file_name": "x.srt"}]}}
            ]}, None

        backend = SubtitleBackend(
            _settings(tmp_path, monkeypatch), _FakeController(""), transport=transport
        )
        backend.apiKey = "k"
        backend._results = [_row()]
        backend._results[0]["idx"] = 0
        backend._set_results([backend._results[0]], [])

        backend.download(0)
        assert backend.statusIsError
        assert backend.busyIndex == -1

    def test_http_error_messages_are_specific(self):
        err = urllib.error.HTTPError("u", 401, "x", {}, None)
        assert _http_error_message(err) == "API key rejected — check it and try again."
        err = urllib.error.HTTPError("u", 429, "x", {}, None)
        assert "Too many requests" in _http_error_message(err)
