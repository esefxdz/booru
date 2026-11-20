"""Bulk download reports real success counts, and download_file says ok/False."""
import asyncio

from controller import BulkThread


class _Dl:
    def __init__(self, results):
        self.results = list(results)

    async def get_image_urls(self, tags, limit, page):
        return [{"id": i} for i in range(len(self.results))]

    def download_file(self, task_id, post, folder):
        r = self.results[post["id"]]
        if isinstance(r, Exception):
            raise r
        return r


def test_bulk_counts_only_real_successes(monkeypatch, tmp_path):
    import download_images
    from core import async_loop
    monkeypatch.setattr(download_images, "get_bulk_folder", lambda tags: tmp_path)
    monkeypatch.setattr(async_loop, "run", lambda coro: asyncio.run(coro))
    t = BulkThread(_Dl([True, False, RuntimeError("x"), True]), "tag", 4)
    done = []
    t.bulk_done.connect(lambda ok, total: done.append((ok, total)))
    t.run()
    assert done == [(2, 4)]


def test_download_file_returns_ok_flag(monkeypatch, tmp_path):
    from download_images import booru_client, image_downloader
    dl = booru_client.BooruDownloader.__new__(booru_client.BooruDownloader)
    for sig in ("download_started", "download_progress", "download_finished", "download_failed"):
        setattr(dl, sig, type("S", (), {"emit": lambda self, *a: None})())
    post = {"id": 1, "file_ext": "png"}
    monkeypatch.setattr(image_downloader, "download_post", lambda *a, **k: True)
    assert dl.download_file("t", post, tmp_path) is True
    monkeypatch.setattr(image_downloader, "download_post", lambda *a, **k: False)
    assert dl.download_file("t", post, tmp_path) is False
    def boom(*a, **k): raise OSError("x")
    monkeypatch.setattr(image_downloader, "download_post", boom)
    assert dl.download_file("t", post, tmp_path) is False
