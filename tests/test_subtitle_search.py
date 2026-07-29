"""Online subtitle search — the parts that decide what the user sees.

The network is not exercised here; ``QNetworkAccessManager`` needs a live
socket and a real API key, and neither belongs in a unit test. What *is*
exercised is everything that decides whether the right subtitle is on screen:

* the file hash, which is what makes an "exact" match possible at all;
* the filename -> query guess, which is what makes a *title* search work when
  the hash misses;
* the ranking, which is the entire difference between the two match modes the
  Settings dialog offers.

The last one matters most. "Best" and "All" are a user-facing promise —
"only what genuinely matches this file" versus "everything, best first" — and
without a test it is one sort-key edit away from being the same list twice.
"""

from __future__ import annotations

import struct

import pytest

from core.subtitles import (
    ALL_LIMIT,
    BEST_LIMIT,
    LANGUAGES,
    MATCH_ALL,
    MATCH_BEST,
    guess_query,
    opensubtitles_hash,
    rank_results,
)


# ---------------------------------------------------------------- hash ---
class TestHash:
    def _big_file(self, tmp_path, name="movie.mkv", pattern=b"\x01\x02\x03\x04\x05\x06\x07\x08"):
        target = tmp_path / name
        target.write_bytes(pattern * (128 * 1024 // len(pattern) + 8))
        return target

    def test_a_real_file_hashes_to_sixteen_hex_digits(self, tmp_path):
        digest, size = opensubtitles_hash(self._big_file(tmp_path))

        assert len(digest) == 16, "OpenSubtitles' hash is a 64-bit value in hex"
        assert int(digest, 16) >= 0
        assert size > 0

    def test_the_hash_is_stable(self, tmp_path):
        target = self._big_file(tmp_path)

        assert opensubtitles_hash(target) == opensubtitles_hash(target)

    def test_different_content_hashes_differently(self, tmp_path):
        a = self._big_file(tmp_path, "a.mkv", b"\x01\x02\x03\x04\x05\x06\x07\x08")
        b = self._big_file(tmp_path, "b.mkv", b"\x08\x07\x06\x05\x04\x03\x02\x01")

        assert opensubtitles_hash(a)[0] != opensubtitles_hash(b)[0]

    def test_a_too_small_file_degrades_instead_of_raising(self, tmp_path):
        tiny = tmp_path / "clip.mp4"
        tiny.write_bytes(b"\0" * 512)

        digest, size = opensubtitles_hash(tiny)

        assert digest == "", "no hash is a search by title, not a crash"
        assert size == 512

    def test_a_missing_file_degrades_instead_of_raising(self, tmp_path):
        assert opensubtitles_hash(tmp_path / "nope.mkv") == ("", 0)


# --------------------------------------------------------------- query ---
class TestGuessQuery:
    def test_an_episode_filename_yields_title_season_and_episode(self):
        got = guess_query("Andor.S02E01.1080p.WEB-DL.x265-GROUP.mkv")

        assert got["query"] == "andor"
        assert (got["season"], got["episode"]) == (2, 1)

    def test_release_noise_is_stripped_from_a_film(self):
        got = guess_query("Arrival.2016.2160p.UHD.BluRay.x265.DTS-HD.MA.7.1-TERMINAL.mkv")

        assert got["query"] == "arrival", (
            "sending the release tags as the title returns nothing at all — the "
            "server searches a *title* index"
        )
        assert got["year"] == 2016

    def test_a_year_is_kept_so_remakes_do_not_collide(self):
        assert guess_query("Dune.1984.mkv")["year"] == 1984
        assert guess_query("Dune.2021.mkv")["year"] == 2021

    def test_bracketed_groups_are_dropped(self):
        got = guess_query("[SubsPlease] Frieren - 01 (1080p) [ABC123].mkv")

        assert "subsplease" not in got["query"]
        assert "frieren" in got["query"]

    def test_underscores_and_dots_are_separators(self):
        assert guess_query("The_Wire_S01E03.avi")["query"] == "the wire"

    def test_a_plain_title_survives_untouched(self):
        assert guess_query("Casablanca.mkv")["query"] == "casablanca"

    def test_an_episode_beats_a_stray_year(self):
        """`S02E01` wins: 2016 in a TV filename is usually the air year, and
        sending it as `year=` filters the series out entirely."""
        got = guess_query("Westworld.2016.S02E01.mkv")

        assert (got["season"], got["episode"]) == (2, 1)
        assert got["year"] == 0


# ------------------------------------------------------------- ranking ---
def _entry(file_id, *, release, hash_match=False, downloads=0, language="en", feature=None):
    return {
        "attributes": {
            "release": release,
            "language": language,
            "download_count": downloads,
            "moviehash_match": hash_match,
            "feature_details": feature or {},
            "files": [{"file_id": file_id, "file_name": release + ".srt"}],
        }
    }


class TestRanking:
    QUERY = {"query": "andor", "season": 2, "episode": 1}
    FILE = "Andor.S02E01.1080p.WEB-DL.x265-GROUP.mkv"

    def _payload(self):
        return [
            _entry(1, release="Andor.S02E01.1080p.WEB-DL.x265-GROUP", hash_match=True),
            _entry(2, release="Andor.S02E01.HDTV.x264-OTHER", downloads=9000),
            _entry(3, release="Completely.Different.Show.S01E01", downloads=50000),
        ]

    def test_best_keeps_only_the_vouched_match(self):
        got = rank_results(self._payload(), mode=MATCH_BEST, query=self.QUERY, file_name=self.FILE)

        assert [e["fileId"] for e in got] == [1], (
            "the hash match is the subtitle for *this exact release*; showing it "
            "next to two guesses is what 'best' exists to avoid"
        )
        assert got[0]["matchKind"] == "hash"

    def test_all_keeps_everything(self):
        got = rank_results(self._payload(), mode=MATCH_ALL, query=self.QUERY, file_name=self.FILE)

        assert len(got) == 3
        assert {e["fileId"] for e in got} == {1, 2, 3}

    def test_all_still_puts_the_exact_match_first(self):
        got = rank_results(self._payload(), mode=MATCH_ALL, query=self.QUERY, file_name=self.FILE)

        assert got[0]["fileId"] == 1, (
            "'all' means unfiltered, not unsorted — a 50k-download subtitle for "
            "the wrong show must not outrank the hash match"
        )

    def test_the_unrelated_entry_is_badged_partial(self):
        got = rank_results(self._payload(), mode=MATCH_ALL, query=self.QUERY, file_name=self.FILE)
        odd = next(e for e in got if e["fileId"] == 3)

        assert odd["matchKind"] == "partial", "the badge is how the user spots it"

    def test_best_falls_back_to_a_title_match_when_no_hash_matched(self):
        payload = [
            _entry(2, release="Andor.S02E01.HDTV.x264-OTHER", downloads=9000),
            _entry(3, release="Unrelated.Movie.2011", downloads=99),
        ]

        got = rank_results(payload, mode=MATCH_BEST, query=self.QUERY, file_name=self.FILE)

        assert got[0]["fileId"] == 2
        assert got[0]["matchKind"] == "title"

    def test_best_never_returns_nothing_when_the_server_returned_something(self):
        """An empty list reads as "no subtitles exist", which would be a lie."""
        payload = [_entry(9, release="Something.Else.Entirely", downloads=5)]

        got = rank_results(payload, mode=MATCH_BEST, query=self.QUERY, file_name=self.FILE)

        assert got, "offer the weak candidates, badged 'partial', rather than nothing"
        assert got[0]["matchKind"] == "partial"

    def test_a_wrong_episode_is_demoted_even_with_a_matching_title(self):
        payload = [
            _entry(
                1,
                release="Andor.S02E05.1080p.WEB-DL",
                feature={"season_number": 2, "episode_number": 5},
                downloads=100000,
            ),
            _entry(
                2,
                release="Andor.S02E01.1080p.WEB-DL",
                feature={"season_number": 2, "episode_number": 1},
                downloads=10,
            ),
        ]

        got = rank_results(payload, mode=MATCH_ALL, query=self.QUERY, file_name=self.FILE)

        assert got[0]["fileId"] == 2, "episode 1 is what is playing, popularity is not"

    def test_entries_without_a_downloadable_file_are_dropped(self):
        payload = [{"attributes": {"release": "Broken", "files": []}}]

        assert rank_results(payload, mode=MATCH_ALL) == []

    def test_an_empty_payload_is_an_empty_list(self):
        assert rank_results([], mode=MATCH_BEST) == []
        assert rank_results(None, mode=MATCH_ALL) == []

    def test_the_result_shape_carries_what_the_row_renders(self):
        got = rank_results(self._payload(), mode=MATCH_ALL, query=self.QUERY)

        for key in ("fileId", "release", "language", "downloads", "matchKind"):
            assert key in got[0], f"the results delegate binds {key}"

    def test_limits_are_enforced(self):
        payload = [_entry(i, release=f"Andor.S02E01.Release{i}") for i in range(200)]

        assert len(rank_results(payload, mode=MATCH_BEST, query=self.QUERY)) <= BEST_LIMIT
        assert len(rank_results(payload, mode=MATCH_ALL, query=self.QUERY)) <= ALL_LIMIT


# ----------------------------------------------------------- languages ---
class TestLanguages:
    def test_codes_are_unique(self):
        codes = [code for code, _ in LANGUAGES]

        assert len(codes) == len(set(codes))

    def test_english_is_the_first_entry(self):
        assert LANGUAGES[0][0] == "en", "it is the default, so it should not need scrolling to"

    def test_every_entry_has_a_readable_name(self):
        for code, name in LANGUAGES:
            assert code and name and name != code


# ------------------------------------------------------------ settings ---
def test_the_online_subtitle_settings_have_defaults():
    """The Settings dialog binds these; a missing key renders an empty control."""
    from core.settings import DEFAULTS

    assert DEFAULTS["subs.online.apiKey"] == "", "no shared key ships with Halcyon"
    assert DEFAULTS["subs.online.matchMode"] == MATCH_BEST, "best is the default (§2.a)"
    assert DEFAULTS["subs.online.language"] == "en"
    assert DEFAULTS["subs.online.saveAlongsideMedia"] is True


# ------------------------------------------------------------- saving ---
class TestSaving:
    """Where a downloaded subtitle lands, which decides whether it auto-loads
    next time and whether it can destroy a subtitle the user already had."""

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path / "profile"))
        from PySide6.QtCore import QCoreApplication

        from core.settings import Settings
        from core.subtitles import SubtitleService

        QCoreApplication.instance() or QCoreApplication([])
        settings = Settings(path=tmp_path / "profile" / "settings.json")
        return SubtitleService(settings), settings

    @pytest.fixture
    def media(self, tmp_path):
        target = tmp_path / "media" / "Andor.S02E01.mkv"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"video")
        return target

    def test_it_saves_beside_the_media_with_a_language_suffix(self, service, media):
        svc, _ = service
        svc.set_media(str(media))
        svc._pending_download = {"language": "en"}

        saved = svc._save(b"subtitle", "whatever.srt")

        assert saved.parent == media.parent, (
            "beside the media is what makes the sidecar auto-loader pick it up "
            "on the next play"
        )
        assert saved.name == "Andor.S02E01.en.srt"

    def test_it_never_clobbers_an_existing_subtitle(self, service, media):
        svc, _ = service
        svc.set_media(str(media))
        svc._pending_download = {"language": "en"}

        first = svc._save(b"one", "a.srt")
        second = svc._save(b"two", "a.srt")

        assert first != second
        assert first.read_bytes() == b"one", "the user's existing file survives"
        assert second.read_bytes() == b"two"

    def test_it_falls_back_to_the_cache_when_told_not_to_write_alongside(
        self, service, media
    ):
        svc, settings = service
        settings.set("subs.online.saveAlongsideMedia", False)
        svc.set_media(str(media))
        svc._pending_download = {"language": "en"}

        saved = svc._save(b"subtitle", "a.srt")

        assert saved.parent != media.parent
        assert saved.parent.name == "subtitles"

    def test_a_hostile_extension_is_normalised(self, service, media):
        """The filename comes off the network; it does not get to pick .exe."""
        svc, _ = service
        svc.set_media(str(media))
        svc._pending_download = {"language": ""}

        saved = svc._save(b"subtitle", "payload.exe")

        assert saved.suffix == ".srt"

    def test_a_known_subtitle_extension_is_kept(self, service, media):
        svc, _ = service
        svc.set_media(str(media))
        svc._pending_download = {"language": "en"}

        assert svc._save(b"x", "styled.ass").suffix == ".ass"


class TestGuards:
    def test_searching_without_a_key_reports_instead_of_calling_out(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path))
        from PySide6.QtCore import QCoreApplication

        from core.settings import Settings
        from core.subtitles import SubtitleService

        QCoreApplication.instance() or QCoreApplication([])
        svc = SubtitleService(Settings(path=tmp_path / "settings.json"))
        seen = []
        svc.errorOccurred.connect(seen.append)

        svc.search("andor")

        assert not svc.configured
        assert seen and "API key" in seen[0], (
            "an unconfigured key is a state the UI explains, not a silent no-op"
        )
        assert not svc.busy, "a refused search must not leave the UI spinning"


class TestHostilePayloads:
    """The payload comes off the internet. It must degrade, never throw.

    opensubtitles.com sends clean JSON today, but a caching proxy, a captive
    portal, an error page or a future schema change can put a string where an
    int belonged or a list where an object belonged. An exception escaping the
    reply handler leaves the dialog spinning with no message and no results —
    the worst possible failure, because it looks like the app hung.

    Found by fuzzing, not by reading: `download_count: "x"` raised ValueError,
    and `feature_details: []` raised AttributeError, in code that looked
    perfectly defensive because it used `or {}` everywhere.
    """

    QUERY = {"query": "andor", "season": 2, "episode": 1}

    def _one(self, **attrs):
        base = {"release": "Andor.S02E01", "files": [{"file_id": 5, "file_name": "a.srt"}]}
        base.update(attrs)
        return [{"attributes": base}]

    @pytest.mark.parametrize(
        "value",
        ["x", None, "", [], {}, True, 1.5, float("nan"), float("inf"), 10**400],
        ids=repr,
    )
    def test_a_junk_download_count_does_not_raise(self, value):
        got = rank_results(
            self._one(download_count=value), mode=MATCH_ALL, query=self.QUERY
        )

        assert len(got) == 1
        assert isinstance(got[0]["downloads"], int)

    @pytest.mark.parametrize(
        "value", ["x", None, [], float("nan"), float("inf"), 10**400], ids=repr
    )
    def test_a_junk_rating_does_not_raise(self, value):
        got = rank_results(self._one(ratings=value), mode=MATCH_ALL, query=self.QUERY)

        assert len(got) == 1
        assert isinstance(got[0]["rating"], float)

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "a string",
            {},
            [None],
            [[]],
            [{"attributes": None}],
            [{"attributes": []}],
            [{"attributes": {"files": {}}}],
            [{"attributes": {"files": "x"}}],
            [{"attributes": {"files": [None]}}],
            [{"attributes": {"files": [{"file_id": 3}], "feature_details": []}}],
            [{"attributes": {"files": [{"file_id": 3}], "uploader": "bob"}}],
        ],
        ids=lambda p: repr(p)[:40],
    )
    def test_a_malformed_payload_shape_does_not_raise(self, payload):
        for mode in (MATCH_BEST, MATCH_ALL):
            rank_results(payload, mode=mode, query=self.QUERY, file_name="a.mkv")

    def test_a_good_entry_survives_a_malformed_sibling(self):
        """One bad row must not lose the whole result list."""
        payload = [
            {"attributes": None},
            {"attributes": {
                "release": "Andor.S02E01.WEB",
                "files": [None, {"file_id": 7, "file_name": "a.srt"}],
            }},
        ]

        got = rank_results(payload, mode=MATCH_ALL, query=self.QUERY)

        assert [e["fileId"] for e in got] == [7]

    def test_a_junk_feature_block_still_yields_a_row(self):
        got = rank_results(
            self._one(feature_details={"year": "x", "season_number": [], "episode_number": None}),
            mode=MATCH_ALL,
            query=self.QUERY,
        )

        assert len(got) == 1
        assert got[0]["year"] == 0


class TestSavePathSafety:
    """Both inputs to the filename come off the network.

    The stem is taken from the *media* file, so a hostile
    ``../../../../etc/passwd.srt`` in the server's ``file_name`` was already
    harmless. The language tag was not: it was interpolated straight into the
    path, so ``"language": "../../evil"`` walked out of the directory and
    raised FileNotFoundError — which on a differently-shaped tree would have
    been a silent write to the wrong place instead.
    """

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path / "profile"))
        from PySide6.QtCore import QCoreApplication

        from core.settings import Settings
        from core.subtitles import SubtitleService

        QCoreApplication.instance() or QCoreApplication([])
        settings = Settings(path=tmp_path / "profile" / "settings.json")
        svc = SubtitleService(settings)
        media = tmp_path / "media" / "Andor.S02E01.mkv"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"video")
        svc.set_media(str(media))
        return svc, media, settings

    @pytest.mark.parametrize(
        "language",
        ["../../evil", "e/n", "..", ".", "en\x00", "<script>", "a" * 50, "/abs"],
        ids=repr,
    )
    def test_a_hostile_language_tag_cannot_escape(self, service, language):
        svc, media, _ = service
        svc._pending_download = {"language": language}

        saved = svc._save(b"subtitle", "sub.srt")

        assert saved.parent.resolve() == media.parent.resolve()

    @pytest.mark.parametrize("language", ["en", "pt-BR", "zh-CN"])
    def test_a_real_language_tag_is_kept(self, service, language):
        svc, media, _ = service
        svc._pending_download = {"language": language}

        saved = svc._save(b"subtitle", "sub.srt")

        assert saved.name == f"{media.stem}.{language}.srt", (
            "sanitising must not throw away legitimate tags like pt-BR"
        )

    @pytest.mark.parametrize(
        "name",
        [
            "../../../../etc/passwd.srt",
            "..\\..\\windows\\system32\\evil.srt",
            "a/b/c.srt",
            "",
        ],
        ids=repr,
    )
    def test_a_hostile_suggested_name_cannot_escape(self, service, name):
        svc, media, _ = service
        svc._pending_download = {"language": "en"}

        saved = svc._save(b"subtitle", name)

        assert saved.parent.resolve() == media.parent.resolve()

    def test_the_cache_fallback_is_also_contained(self, service):
        svc, _, settings = service
        settings.set("subs.online.saveAlongsideMedia", False)
        svc._pending_download = {"language": "en"}

        saved = svc._save(b"subtitle", "../../../../etc/passwd.srt")

        assert saved.parent.name == "subtitles"


# ------------------------------------------- best mode must return something ---
class TestBestModeIsNarrowNotEmpty:
    """"Best match" is a narrower list, never a blank one.

    The reported failure: Best match found nothing and told the user to try
    All results; All results then returned a full list. Two modes over the same
    file, one of them apparently broken.

    What actually happened
    ----------------------
    Best sent ``moviehash_match=only``, which asks OpenSubtitles to discard
    everything its hash index does not vouch for. That index covers a small
    slice of the site, so for most real files the server returned an empty
    payload — and the good title matches the file genuinely had were filtered
    out server-side, where no amount of client ranking could recover them.

    The hash is still sent (it is what earns the "exact" badge), but as
    ``include``. Narrowing is now done once, client-side, in ``rank_results``.
    """

    @staticmethod
    def _code() -> str:
        """core/subtitles.py with ``#`` comments stripped.

        This asserts a string is *absent*, and the comment explaining why it is
        absent naturally contains it — so without this the module's own
        documentation fails its test.
        """
        import re as _re
        from pathlib import Path as _Path

        source = (
            _Path(__file__).parent.parent / "core" / "subtitles.py"
        ).read_text(encoding="utf-8")
        return "\n".join(
            _re.sub(r"(?<!['\"])#.*$", "", line) for line in source.splitlines()
        )

    def test_the_hash_never_filters_server_side(self):
        code = self._code()

        assert '"moviehash_match", "include"' in code
        assert '"only"' not in code, (
            "'only' makes Best return nothing for any file outside the hash "
            "index, which is most of them"
        )

    def test_both_modes_ask_the_server_the_same_question(self):
        """The difference between the modes is ranking, not two payloads."""
        code = self._code()
        search = code.split("def search(", 1)[1].split("def _on_search_finished", 1)[0]

        assert search.count("moviehash_match") == 1, (
            "one query shape; the modes diverge in rank_results, once"
        )

    def test_best_narrows_the_same_payload_all_would_show(self):
        payload = [
            _entry(1, release="Andor.S02E01.1080p.WEB-DL.x265-GROUP", hash_match=True),
            _entry(2, release="Andor.S02E01.HDTV.x264-OTHER", downloads=9000),
            _entry(3, release="Completely.Different.Show.S01E01", downloads=50000),
        ]
        query = {"query": "andor", "season": 2, "episode": 1}
        file_name = "Andor.S02E01.1080p.WEB-DL.x265-GROUP.mkv"

        best = rank_results(payload, mode=MATCH_BEST, query=query, file_name=file_name)
        every = rank_results(payload, mode=MATCH_ALL, query=query, file_name=file_name)

        assert len(best) < len(every), "narrower"
        assert best, "but never empty when the server returned rows"
        assert {e["fileId"] for e in best} <= {e["fileId"] for e in every}

    def test_best_returns_rows_when_nothing_hash_matched(self):
        """The common real case: no hash match, but good title matches exist."""
        payload = [
            _entry(2, release="Andor.S02E01.HDTV.x264-OTHER", downloads=9000),
            _entry(4, release="Andor.S02E01.WEBRip", downloads=120),
        ]

        got = rank_results(
            payload,
            mode=MATCH_BEST,
            query={"query": "andor", "season": 2, "episode": 1},
            file_name="Andor.S02E01.1080p.WEB-DL.mkv",
        )

        assert got, (
            "this is precisely what `moviehash_match=only` used to throw away "
            "before the client ever saw it"
        )
        assert all(e["matchKind"] == "title" for e in got)


# ============ the Settings section must actually drive the search ============
class TestSettingsReachTheSearch:
    """Point 5, end to end: what the Settings section says, the search does.

    The picker being switchable is only half of it. These pin the other half —
    that the value it writes is the value the search resolves and ranks with,
    both ways round and repeatedly.
    """

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path / "profile"))
        from PySide6.QtCore import QCoreApplication

        from core.settings import Settings
        from core.subtitles import SubtitleService

        QCoreApplication.instance() or QCoreApplication([])
        settings = Settings(path=tmp_path / "profile" / "settings.json")
        settings.set("subs.online.apiKey", "TESTKEY")
        service = SubtitleService(settings)

        media = tmp_path / "Andor.S02E01.1080p.WEB-DL.mkv"
        media.write_bytes(b"v" * 200_000)
        service.set_media(str(media))
        return service, settings

    def _sent_url(self, service, monkeypatch):
        """Run search() far enough to capture the query, never the network."""
        captured = {}

        def spy(url):
            captured["url"] = url.toString()
            raise RuntimeError("stop before the network")

        monkeypatch.setattr(service, "_request", spy)
        try:
            service.search("", "", "")
        except RuntimeError:
            pass
        service._busy = False
        return captured.get("url", "")

    def test_the_match_mode_switches_both_ways_and_keeps_switching(self, service):
        """Neither value may stick — that is the reported symptom."""
        _, settings = service

        for wanted in ("all", "best", "all", "best"):
            settings.set("subs.online.matchMode", wanted)
            assert settings.get("subs.online.matchMode") == wanted

    def test_the_language_setting_reaches_the_query(self, service, monkeypatch):
        svc, settings = service

        for code in ("en", "bn", "ar"):
            settings.set("subs.online.language", code)
            url = self._sent_url(svc, monkeypatch)
            assert f"languages={code}" in url, f"{code} never reached the server"

    def test_an_explicit_argument_overrides_the_setting(self, service, monkeypatch):
        """The dialog passes its live values; they must win over the store."""
        svc, settings = service
        settings.set("subs.online.language", "en")
        captured = {}

        def spy(url):
            captured["url"] = url.toString()
            raise RuntimeError("stop")

        monkeypatch.setattr(svc, "_request", spy)
        try:
            svc.search("", "bn", "all")
        except RuntimeError:
            pass

        assert "languages=bn" in captured["url"]

    def test_an_empty_argument_falls_back_to_the_setting(self, service, monkeypatch):
        svc, settings = service
        settings.set("subs.online.language", "ar")

        assert "languages=ar" in self._sent_url(svc, monkeypatch)

    @pytest.mark.parametrize("wanted", ["best", "all"])
    def test_the_resolved_mode_is_the_one_ranked_with(self, service, monkeypatch, wanted):
        """The setting must survive all the way to rank_results."""
        import core.subtitles as subtitles_module

        svc, settings = service
        settings.set("subs.online.matchMode", wanted)
        seen = {}
        original = subtitles_module.rank_results

        def spy(raw, *, mode, query=None, file_name=""):
            seen["mode"] = mode
            return original(raw, mode=mode, query=query, file_name=file_name)

        monkeypatch.setattr(subtitles_module, "rank_results", spy)

        mode = str(settings.get("subs.online.matchMode", "best")).strip()
        mode = MATCH_ALL if mode == MATCH_ALL else MATCH_BEST
        svc._on_search_finished(
            _FakeReply(), mode=mode, parsed={"query": "andor"}, language="en", size=0
        )

        assert seen["mode"] == wanted

    def test_an_unknown_mode_degrades_to_best(self, service, monkeypatch):
        """A hand-edited settings.json must not produce a third behaviour."""
        svc, settings = service
        settings.set("subs.online.matchMode", "nonsense")

        mode = str(settings.get("subs.online.matchMode", "best")).strip()
        mode = MATCH_ALL if mode == MATCH_ALL else MATCH_BEST

        assert mode == MATCH_BEST


class _FakeReply:
    """A 200 response carrying one result, with no socket behind it."""

    def attribute(self, *args):
        return 200

    def readAll(self):
        import json

        payload = {
            "data": [
                {
                    "attributes": {
                        "release": "Andor.S02E01.WEB",
                        "language": "en",
                        "download_count": 5,
                        "moviehash_match": False,
                        "feature_details": {},
                        "files": [{"file_id": 9, "file_name": "a.srt"}],
                    }
                }
            ]
        }
        return type("B", (), {"data": lambda s: json.dumps(payload).encode()})()

    def error(self):
        from PySide6.QtNetwork import QNetworkReply

        return QNetworkReply.NetworkError.NoError

    def errorString(self):
        return ""

    def deleteLater(self):
        pass
