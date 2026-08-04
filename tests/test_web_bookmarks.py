"""Unit tests for Web mode bookmarks permanent store (§P3.5)."""

from __future__ import annotations

from pathlib import Path

from modes.web.bookmarks import BookmarksStore


def test_bookmarks_start_completely_blank(tmp_path: Path):
    """Bookmarks store must start completely blank — no defaults (§P3.5)."""
    store_file = tmp_path / "bookmarks.json"
    store = BookmarksStore(path=store_file)
    assert store.count == 0
    assert store.getAll() == []
    assert not store.isBookmarked("https://www.google.com")


def test_bookmarks_add_update_remove_reorder(tmp_path: Path):
    """Verify add / edit / remove / search / reorder operations (§P3.5)."""
    store_file = tmp_path / "bookmarks.json"
    store = BookmarksStore(path=store_file)

    # 1. Add
    assert store.addBookmark("Google", "https://google.com")
    assert store.count == 1
    assert store.isBookmarked("https://google.com")
    assert store.getByUrl("https://google.com")["title"] == "Google"

    # 2. Add second
    assert store.addBookmark("Example", "https://example.com")
    assert store.count == 2
    items = store.getAll()
    assert [i["url"] for i in items] == ["https://google.com", "https://example.com"]

    # 3. Update
    assert store.updateBookmark("https://google.com", "Google Search", "https://www.google.com")
    assert not store.isBookmarked("https://google.com")
    assert store.isBookmarked("https://www.google.com")
    assert store.getByUrl("https://www.google.com")["title"] == "Google Search"

    # 4. Search
    results = store.search("example")
    assert len(results) == 1
    assert results[0]["title"] == "Example"

    # 5. Reorder (swap 0 and 1)
    assert store.reorder(0, 1)
    items_after = store.getAll()
    assert [i["url"] for i in items_after] == ["https://example.com", "https://www.google.com"]

    # 6. Remove
    assert store.removeBookmark("https://example.com")
    assert store.count == 1
    assert not store.isBookmarked("https://example.com")
