"""Saved-sources store tests — §P2.4. Pure Python, no Qt required."""

from __future__ import annotations

from modes.m3u.sources import MAX_SOURCES, SourcesStore


def test_add_list_and_cap_at_seven(tmp_path) -> None:
    store = SourcesStore(tmp_path / "m3u-sources.json")
    for i in range(MAX_SOURCES):
        added = store.add(f"Source {i}", "url", f"http://example.com/{i}.m3u8")
        assert added is not None
    assert store.full
    # The eighth must be refused — Add disables, never a silent failure (§P2.4).
    assert store.add("One too many", "url", "http://example.com/8.m3u8") is None
    assert len(store.list()) == MAX_SOURCES


def test_add_normalises_and_defaults(tmp_path) -> None:
    store = SourcesStore(tmp_path / "m3u-sources.json")
    source = store.add("  ", "url", "  http://example.com/list.m3u8  ")
    assert source is not None
    assert source.location == "http://example.com/list.m3u8"
    assert source.name  # fell back to something non-empty
    # Bad kind / empty location are refused outright.
    assert store.add("x", "carrier-pigeon", "http://x") is None
    assert store.add("x", "url", "   ") is None


def test_update_and_remove(tmp_path) -> None:
    store = SourcesStore(tmp_path / "m3u-sources.json")
    source = store.add("Old", "url", "http://example.com/old.m3u8")
    assert store.update(source.id, "New", "http://example.com/new.m3u8")
    assert store.get(source.id).name == "New"
    assert store.get(source.id).location == "http://example.com/new.m3u8"
    assert not store.update("missing-id", "x", "y")

    assert store.remove(source.id)
    assert store.get(source.id) is None
    assert not store.remove(source.id)


def test_persistence_round_trip(tmp_path) -> None:
    path = tmp_path / "m3u-sources.json"
    first = SourcesStore(path)
    first.add("IPTV", "url", "http://example.com/iptv.m3u")
    first.add("Backup", "file", r"C:\Lists\backup.m3u")

    second = SourcesStore(path)
    assert [s.name for s in second.list()] == ["IPTV", "Backup"]
    assert second.list()[1].kind == "file"


def test_corrupt_store_starts_empty(tmp_path) -> None:
    path = tmp_path / "m3u-sources.json"
    path.write_text("{ not json at all", encoding="utf-8")
    store = SourcesStore(path)
    assert store.list() == []
    # …and recovers on the next save.
    store.add("Fresh", "url", "http://example.com/a.m3u8")
    assert SourcesStore(path).list()[0].name == "Fresh"
