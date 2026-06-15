import asyncio
import threading
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from ui import settings_view as settings
import boorus

class FetchThread(QThread):
    finished = pyqtSignal(list, bool) # posts, is_bookmarks_mode
    error = pyqtSignal(str)
    preview_ready = pyqtSignal(bytes, dict, int)  # safe JPEG bytes, post, idx
    posts_ready = pyqtSignal(list, bool)  # emitted after metadata, before thumbnails

    def __init__(self, downloader, tags, current_page, is_bookmarks_mode, bookmark_filter):
        super().__init__()
        self.downloader = downloader
        self.tags = tags
        self.current_page = current_page
        self.is_bookmarks_mode = is_bookmarks_mode
        self.bookmark_filter = bookmark_filter
        # Per-thread cancellation flag. AppController sets this before replacing
        # the thread so in-flight thumbnail downloads stop cleanly.
        self.cancel_event = threading.Event()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        sessions = {}
        def get_cached_session(booru_name):
            if booru_name not in sessions:
                from cloudflare_bypasser import get_session
                sessions[booru_name] = get_session(booru_name)
            return sessions[booru_name]

        try:
            if self.is_bookmarks_mode:
                from ui.bookmarks_main.bookmarks_db import db
                all_bms = db.get_all_bookmarks()
                if self.bookmark_filter:
                    all_bms = [p for p in all_bms if p.get("_booru") == self.bookmark_filter]

                if self.tags.strip():
                    search_tags = self.tags.split()
                    all_bms = [p for p in all_bms if all(t in p.get('tags', []) for t in search_tags)]

                start = (self.current_page - 1) * settings.SEARCH_LIMIT
                end = start + settings.SEARCH_LIMIT
                posts = all_bms[start:end]
            else:
                posts = loop.run_until_complete(self.downloader.get_image_urls(self.tags, settings.SEARCH_LIMIT, self.current_page - 1, session_manager=get_cached_session))
                for p in posts: p["_booru"] = settings.manager.active_booru

            # Phase 1: Emit metadata immediately so the UI shows skeletons
            self.posts_ready.emit(posts, self.is_bookmarks_mode)

            # Phase 2: Fetch thumbnails — skip entirely if already cancelled
            if posts and not self.cancel_event.is_set():
                def on_preview(pil_img, post, idx):
                    if not self.cancel_event.is_set():
                        self.preview_ready.emit(pil_img, post, idx)
                loop.run_until_complete(
                    self.downloader.fetch_previews(posts, on_preview, self.cancel_event, session_manager=get_cached_session)
                )

            self.finished.emit(posts, self.is_bookmarks_mode)
        except Exception as e:
            from download_images import CloudflareBlockError
            from download_images.network import BooruAPIError
            if isinstance(e, (CloudflareBlockError, BooruAPIError)):
                self.error.emit(str(e))
            else:
                import logging
                logging.exception("FetchThread crashed")
                self.error.emit(str(e))
        finally:
            for s in sessions.values():
                try:
                    loop.run_until_complete(s.close())
                except Exception:
                    pass
            loop.close()

class BulkThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, downloader, tags, limit):
        super().__init__()
        self.downloader = downloader
        self.tags = tags
        self.limit = limit

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.progress.emit("Fetching metadata...")
            posts = loop.run_until_complete(self.downloader.get_image_urls(self.tags, self.limit, 0))
            if not posts:
                self.finished.emit(0)
                return

            self.progress.emit(f"Downloading {len(posts)} items...")

            from download_images import download_post, get_bulk_folder
            folder = get_bulk_folder(self.tags)

            success = 0
            for i, post in enumerate(posts):
                self.progress.emit(f"Downloading {i+1}/{len(posts)}...")
                if download_post(post, folder, self.downloader):
                    success += 1

            self.finished.emit(success)
        except Exception as e:
            import logging
            logging.exception("BulkThread crashed")
            self.error.emit(str(e))
        finally:
            loop.close()


class AppController(QObject):
    status_updated = pyqtSignal(str, str)
    posts_fetched = pyqtSignal(list)
    loading_started = pyqtSignal()         # clears gallery
    loading_started_append = pyqtSignal()  # does NOT clear gallery
    loading_finished = pyqtSignal()
    preview_ready = pyqtSignal(bytes, dict, int)
    cf_blocked = pyqtSignal(str, str)      # booru_name, url — emitted when CF blocks a booru

    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader
        self._is_loading = False
        self._fetch_gen = 0
        self._thread_lock = threading.Lock()  # guards _is_loading check-and-set
        self.thread: FetchThread | None = None

    @property
    def is_loading(self) -> bool:
        return self._is_loading

    def _cancel_active_thread(self):
        """Signal the current FetchThread to stop and wait up to 2 s for it.

        Must be called while holding ``_thread_lock`` or from the Qt main
        thread before a new thread is started.  The 2-second timeout prevents
        the UI from hanging if a CDN request is slow to cancel.
        """
        if self.thread is not None and self.thread.isRunning():
            self.thread.cancel_event.set()
            self.thread.quit()
            self.thread.wait(2000)  # ms

    def _wire_thread(self, thread):
        """Connect a FetchThread's signals, guarded by a generation counter.

        If the user starts a new search while thumbnails are still loading,
        the old thread keeps running harmlessly but its preview_ready signals
        are silently discarded because the generation has advanced.
        """
        self._fetch_gen += 1
        gen = self._fetch_gen

        thread.posts_ready.connect(lambda posts, bm: self._on_posts_ready(posts, bm, gen))
        thread.finished.connect(lambda posts, bm: self._on_fetch_finished(posts, bm, gen))
        thread.error.connect(self._on_fetch_error)
        thread.preview_ready.connect(
            lambda b, p, i: self._on_preview(b, p, i, gen)
        )

    def _on_preview(self, safe_bytes, post, idx, gen):
        """Forward preview only if this generation is still current."""
        if gen == self._fetch_gen:
            self.preview_ready.emit(safe_bytes, post, idx)

    def trigger_fetch(self, tags, current_page, is_bookmarks_mode, bookmark_filter):
        with self._thread_lock:
            self._cancel_active_thread()
            self._is_loading = True
        self.loading_started.emit()
        self.status_updated.emit("Loading...", "yellow")
        self.thread = FetchThread(self.downloader, tags, current_page, is_bookmarks_mode, bookmark_filter)
        self._wire_thread(self.thread)
        self.thread.start()

    def trigger_fetch_append(self, tags, current_page, is_bookmarks_mode, bookmark_filter):
        """Like trigger_fetch but doesn't clear the gallery (infinite scroll)."""
        with self._thread_lock:
            if self._is_loading:
                return
            self._is_loading = True
        self.loading_started_append.emit()
        self.status_updated.emit("Loading more\u2026", "yellow")
        self.thread = FetchThread(self.downloader, tags, current_page, is_bookmarks_mode, bookmark_filter)
        self._wire_thread(self.thread)
        self.thread.start()

    @pyqtSlot(list, bool)
    def _on_posts_ready(self, posts, is_bookmarks_mode, gen):
        """Metadata arrived — show skeletons immediately and unlock the UI."""
        if gen != self._fetch_gen:
            return  # stale generation, discard
        with self._thread_lock:
            self._is_loading = False
        self.loading_finished.emit()
        if posts:
            self.status_updated.emit("Ready", "green")
            self.posts_fetched.emit(posts)
        else:
            self.status_updated.emit("No Results", "orange")
            self.posts_fetched.emit([])

    @pyqtSlot(list, bool)
    def _on_fetch_finished(self, posts, is_bookmarks_mode, gen):
        """All thumbnails done. Nothing to do — UI was already unblocked by posts_ready."""
        pass

    @pyqtSlot(str)
    def _on_fetch_error(self, error_msg):
        with self._thread_lock:
            self._is_loading = False
        self.loading_finished.emit()
        import logging
        logging.getLogger(__name__).error("Fetch error: %s", error_msg)
        # Route Cloudflare-block errors to the dedicated signal so the GUI
        # can offer to open the CAPTCHA solver automatically.
        if "Cloudflare" in error_msg:
            from ui import settings_view as settings
            self.status_updated.emit("🔐 Cloudflare blocked — solve CAPTCHA?", "orange")
            self.cf_blocked.emit(settings.manager.active_booru, error_msg)
        else:
            self.status_updated.emit("Error!", "red")

    def bulk_download(self, tags, limit):
        self.bulk_thread = BulkThread(self.downloader, tags, limit)
        self.bulk_thread.progress.connect(lambda msg: self.status_updated.emit(msg, "yellow"))
        self.bulk_thread.finished.connect(lambda count: self.status_updated.emit(f"Bulk downloaded {count} items!" if count > 0 else "No posts found.", "green" if count > 0 else "orange"))
        self.bulk_thread.error.connect(lambda _: self.status_updated.emit("Bulk Error!", "red"))
        self.bulk_thread.start()
