import asyncio
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

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if self.is_bookmarks_mode:
                all_bms = settings.manager.bookmarks
                if self.bookmark_filter:
                    all_bms = [p for p in all_bms if p.get("_booru") == self.bookmark_filter]

                if self.tags.strip():
                    search_tags = self.tags.split()
                    all_bms = [p for p in all_bms if all(t in p.get('tags', []) for t in search_tags)]

                start = (self.current_page - 1) * settings.SEARCH_LIMIT
                end = start + settings.SEARCH_LIMIT
                posts = all_bms[start:end]
            else:
                posts = loop.run_until_complete(self.downloader.get_image_urls(self.tags, settings.SEARCH_LIMIT, self.current_page - 1))
                for p in posts: p["_booru"] = settings.manager.active_booru

            # Phase 1: Emit metadata immediately so the UI shows skeletons
            self.posts_ready.emit(posts, self.is_bookmarks_mode)

            # Phase 2: Fetch thumbnails in the background (non-blocking)
            if posts:
                def on_preview(pil_img, post, idx):
                    self.preview_ready.emit(pil_img, post, idx)
                loop.run_until_complete(self.downloader.fetch_previews(posts, on_preview))

            self.finished.emit(posts, self.is_bookmarks_mode)
        except Exception as e:
            from download_images import CloudflareBlockError
            if isinstance(e, CloudflareBlockError):
                self.error.emit(str(e))
            else:
                self.error.emit(str(e))
        finally:
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

    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader
        self._is_loading = False
        self._fetch_gen = 0  # generation counter to discard stale previews

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
        if self._is_loading: return
        self._is_loading = True
        self.loading_started.emit()
        self.status_updated.emit("Loading...", "yellow")
        self.thread = FetchThread(self.downloader, tags, current_page, is_bookmarks_mode, bookmark_filter)
        self._wire_thread(self.thread)
        self.thread.start()

    def trigger_fetch_append(self, tags, current_page, is_bookmarks_mode, bookmark_filter):
        """Like trigger_fetch but doesn't clear the gallery (infinite scroll)."""
        if self._is_loading: return
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
        self._is_loading = False
        self.loading_finished.emit()
        self.status_updated.emit("Error!", "red")
        print(f"Fetch Error: {error_msg}")

    def bulk_download(self, tags, limit):
        self.bulk_thread = BulkThread(self.downloader, tags, limit)
        self.bulk_thread.progress.connect(lambda msg: self.status_updated.emit(msg, "yellow"))
        self.bulk_thread.finished.connect(lambda count: self.status_updated.emit(f"Bulk downloaded {count} items!" if count > 0 else "No posts found.", "green" if count > 0 else "orange"))
        self.bulk_thread.error.connect(lambda err: self.status_updated.emit("Bulk Error!", "red"))
        self.bulk_thread.start()
