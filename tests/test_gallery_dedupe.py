"""Gallery dedupe/lookup is keyed on (booru, id), not the raw id."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect

from ui.gallery import gallery as gallery_mod
from storage import bookmarks_db


class _FakeGallery:
    """Stand-in carrying only the state the unbound methods touch."""

    def __init__(self):
        self._post_id_set = set()
        self._post_id_to_idx = {}
        self._posts = []
        self._rects = []
        self._aspect_ratios = {}
        self._post_bookmarked = {}
        self.bookmark_toggled = type("S", (), {"emit": lambda s, *a: self.emitted.append(a)})()
        self.emitted = []

    def get_adjacent_post(self, post, direction="next"):
        return gallery_mod.Gallery.get_adjacent_post(self, post, direction)

    def _do_refresh(self):
        pass

    def _get_aspect_ratio(self, post):
        return 1.0

    def _style_star(self, *a):
        pass

    def prepare(self, posts):
        gallery_mod.Gallery.prepare_skeletons(self, posts)


def _g(monkeypatch, bookmarked=()):
    monkeypatch.setattr(bookmarks_db.db, "bookmarked_keys", lambda posts: set(bookmarked))
    return _FakeGallery()


def test_same_id_different_booru_both_kept(monkeypatch):
    g = _g(monkeypatch)
    a = {"id": 5, "_booru": "gelbooru"}
    b = {"id": 5, "_booru": "danbooru"}
    g.prepare([a, b])
    assert g._posts == [a, b]
    assert g._post_id_to_idx[("gelbooru", "5")] == 0
    assert g._post_id_to_idx[("danbooru", "5")] == 1


def test_true_duplicates_still_deduped(monkeypatch):
    g = _g(monkeypatch)
    g.prepare([{"id": 5, "_booru": "gelbooru"}, {"id": "5", "_booru": "gelbooru"}])
    g.prepare([{"id": 5, "_booru": "gelbooru"}])
    assert len(g._posts) == 1


def test_bookmark_state_and_toggle_are_per_booru(monkeypatch):
    g = _g(monkeypatch, bookmarked={("danbooru", "5")})
    a = {"id": 5, "_booru": "gelbooru"}
    b = {"id": 5, "_booru": "danbooru"}
    g.prepare([a, b])
    assert g._post_bookmarked == {0: False, 1: True}
    gallery_mod.Gallery._on_star_clicked(g, a, object())
    assert g._post_bookmarked == {0: True, 1: True}
    assert g.emitted == [(a, True)]


def test_adjacent_post_uses_booru(monkeypatch):
    g = _g(monkeypatch)
    a = {"id": 5, "_booru": "gelbooru"}
    b = {"id": 5, "_booru": "danbooru"}
    c = {"id": 6, "_booru": "danbooru"}
    g.prepare([a, b, c])
    assert gallery_mod.Gallery.get_adjacent_post(g, b, "next") is c
    assert gallery_mod.Gallery.get_adjacent_post(g, b, "prev") is a
    assert gallery_mod.Gallery.get_adjacent_post(g, c, "next") is None


def test_overlay_prev_next_start_from_the_right_booru(monkeypatch):
    from ui.viewer.overlay import MediaOverlay
    g = _g(monkeypatch)
    a = {"id": 5, "_booru": "gelbooru"}
    b = {"id": 5, "_booru": "danbooru"}
    c = {"id": 6, "_booru": "danbooru"}
    g.prepare([a, b, c])

    class _Ov:
        shown = []
        post = b
        parent_gui = type("P", (), {"gallery": g})()
        isVisible = lambda self: True
        show_post = lambda self, p: self.shown.append(p)

    ov = _Ov()
    MediaOverlay.prev_post(ov)
    MediaOverlay.next_post(ov)
    assert ov.shown == [a, c]
