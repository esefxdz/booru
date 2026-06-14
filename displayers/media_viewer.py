"""
displayers/media_viewer.py — Central media display widget.

Handles three content types:
  • Images  — fetched in a background thread, displayed via QPixmap
  • GIFs    — downloaded to temp_media/, played via QMovie
  • Videos  — delegated to VideoPlayerWidget (video_player.py)

All network fetches use the CF-bypass session so Cloudflare-protected
sites work without extra configuration.
"""
import logging
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QPixmap, QMovie, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui import settings_view as settings
import boorus
from ui import colors


# ══════════════════════════════════════════════════════════════════════
#  MODULE HELPERS
# ══════════════════════════════════════════════════════════════════════

# User-Agent is intentionally omitted here — it is injected dynamically
# inside _fetch_bytes() via settings.manager.get_user_agent() so it always
# reflects the user's current setting without needing a restart.
_IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}


def _resolve_url(url, site_data=None):
    """Normalise protocol-relative and root-relative URLs."""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/") and site_data:
        return site_data.get("url", "").rstrip("/") + url
    return url


def _fetch_bytes(url, booru_name=None):
    """Download raw bytes through the CF-bypass session."""
    from cloudflare_bypasser import get_session
    headers = _IMAGE_HEADERS.copy()
    headers["User-Agent"] = settings.manager.get_user_agent()

    target_booru = booru_name or settings.manager.active_booru
    site_data = boorus.REGISTRY.get(target_booru, {})

    if site_data.get("url"):
        headers["Referer"] = site_data["url"]

    resp = get_session(target_booru).get_sync(url, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}")
    return resp.content


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: MediaViewer                                                 ║
# ║  Owns a QLabel (for images/GIFs) and lazily creates a              ║
# ║  VideoPlayerWidget when a video post is opened. Signals are used   ║
# ║  to marshal data from background download threads back to the      ║
# ║  GUI thread safely.                                                ║
# ╚══════════════════════════════════════════════════════════════════════╝
class MediaViewer(QWidget):
    image_ready = pyqtSignal(bytes)
    gif_ready = pyqtSignal(str)
    video_ready = pyqtSignal(str)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — a single QLabel used for images/GIFs/loading text │
    # │  plus a slot for the video widget that gets created on demand.  │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self.post = None
        self._viewing_original = False
        self._media_type = None
        self._video_widget = None  # lazily created

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl = QLabel("Loading...")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setStyleSheet(
            f"color: {colors.TEXT_SECONDARY}; font-size: 16px; background: transparent;"
        )
        self._main_layout.addWidget(self.lbl)

        # ── Loading animation ────────────────────────────────────
        self._loading_dots = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.timeout.connect(self._pulse_loading)
        self._loading_timer.setInterval(400)

        # Cross-thread signals → GUI-thread slots
        self.image_ready.connect(self._show_image)
        self.gif_ready.connect(self._show_gif)
        self.video_ready.connect(self._show_video)

    def _pulse_loading(self):
        dots = [".  ", ".. ", "..."]
        self._loading_dots = (self._loading_dots + 1) % 3
        self.lbl.setText(f"Loading{dots[self._loading_dots]}")

    def _start_loading(self):
        self._loading_dots = 0
        self.lbl.setText("Loading.  ")
        self.lbl.show()
        self._loading_timer.start()

    def _stop_loading(self):
        self._loading_timer.stop()
        self.lbl.setText("")

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — determines media type from the file extension    │
    # │  and dispatches to the appropriate loader.                     │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post, original=False):
        self.stop()
        
        # Clean up any previously viewed temp files to prevent disk leak
        from ui import settings_view as settings
        tmp = settings.manager.get_download_dir() / "temp_media"
        if tmp.exists():
            for f in tmp.glob("view_*"):
                try:
                    f.unlink()
                except Exception:
                    pass

        self.post = post
        self._viewing_original = original
        self.lbl.setText("Loading...")
        self.lbl.show()

        parent_gui = self.overlay.parent_gui
        self.file_url = parent_gui.downloader.get_file_url(self.post)

        ext = self.file_url.rsplit("?", 1)[0].lower()
        if any(ext.endswith(v) for v in (".mp4", ".webm")):
            self._media_type = "video"
            self._load_video()
        elif ext.endswith(".gif"):
            self._media_type = "gif"
            self._load_gif(optimized=not original)
        else:
            self._media_type = "image"
            self._load_image(optimized=not original)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  stop  — tears down whichever media is currently playing so    │
    # │  the next post (or overlay close) starts clean.                │
    # └──────────────────────────────────────────────────────────────────┘
    def stop(self):
        # Stop video player if it exists
        if self._video_widget is not None:
            self._video_widget.stop()
            self._video_widget.hide()

        # Stop GIF animation if running
        if hasattr(self, "_movie") and self._movie is not None:
            self._movie.stop()
            self.lbl.setMovie(None)
            self._movie = None

        # Clear any leftover pixmap
        self.lbl.setPixmap(QPixmap())

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _cleanup_previous_temp  — deletes the last-viewed GIF/video    │
    # │  temp file so the temp_media folder doesn't grow unbounded      │
    # │  during long browsing sessions (Part 6 §3).                     │
    # └──────────────────────────────────────────────────────────────────┘
    def _cleanup_previous_temp(self):
        if hasattr(self, "_current_temp_path"):
            try:
                Path(self._current_temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — adapter / URL helpers
    # ══════════════════════════════════════════════════════════════════

    def _get_site_data(self):
        post_booru = self.post.get("_booru", settings.manager.active_booru)
        return boorus.REGISTRY.get(post_booru, {})

    def _get_adapter(self):
        from adapters import get_adapter
        site_data = self._get_site_data()
        return get_adapter(site_data.get("api_type", "gelbooru"))

    def _get_image_url(self, optimized):
        site_data = self._get_site_data()
        adapter = self._get_adapter()
        if optimized:
            url = adapter.get_sample_url(self.post) or self.file_url
        else:
            url = adapter.get_file_url(self.post) or self.file_url
        return _resolve_url(url, site_data)

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — image loading
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _load_image  — fetches image bytes in a background thread,    │
    # │  then emits image_ready to hand the data back to the GUI.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _load_image(self, optimized):
        url = self._get_image_url(optimized)

        def work():
            try:
                data = _fetch_bytes(url, self.post.get('_booru'))
                self.image_ready.emit(data)
            except Exception as e:
                logging.error(f"[media_viewer] Image load error: {e}")

        threading.Thread(target=work, daemon=True).start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _show_image  — slot (GUI thread): decodes the raw bytes into  │
    # │  a QPixmap, scales it to fit, and updates the sidebar details. │
    # └──────────────────────────────────────────────────────────────────┘
    def _show_image(self, data):
        self._stop_loading()
        pix = QPixmap()
        if not pix.loadFromData(data):
            self.lbl.setText("Failed to load image")
            return
        self._pixmap = pix
        self._zoom = 1.0
        self._pan_offset = QPoint(0, 0)
        self._fit_pixmap()
        self.lbl.setText("")

        if hasattr(self.overlay, "sidebar"):
            self.overlay.sidebar.set_original_loaded(self._viewing_original)
            self.overlay.sidebar.details.update_resolution(pix.width(), pix.height())

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _fit_pixmap  — scales the stored pixmap to the current widget │
    # │  size while keeping aspect ratio. Called on every resizeEvent. │
    # └──────────────────────────────────────────────────────────────────┘
    def _fit_pixmap(self):
        if not hasattr(self, "_pixmap"):
            return
        target = self.size()
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl.setPixmap(scaled)

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — GIF loading
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _load_gif  — downloads the GIF to a temp file (QMovie needs  │
    # │  a file path, not raw bytes) then signals the GUI thread.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _load_gif(self, optimized):
        site_data = self._get_site_data()
        url = _resolve_url(self.file_url, site_data)
        self._gif_optimized = optimized

        # ── Clean up previous temp file to prevent unbounded disk growth ──
        self._cleanup_previous_temp()

        def work():
            try:
                data = _fetch_bytes(url, self.post.get('_booru'))
                from ui import settings_view as settings
                tmp = settings.manager.get_download_dir() / "temp_media"
                tmp.mkdir(exist_ok=True, parents=True)
                path = tmp / f"view_{self.post.get('id')}.gif"
                path.write_bytes(data)
                self._current_temp_path = str(path)
                self.gif_ready.emit(str(path))
            except Exception as e:
                logging.error(f"[media_viewer] GIF load error: {e}")

        threading.Thread(target=work, daemon=True).start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _show_gif  — slot (GUI thread): plays the downloaded GIF via  │
    # │  QMovie, optionally scaling it down if viewing the optimised   │
    # │  sample version.                                               │
    # └──────────────────────────────────────────────────────────────────┘
    def _show_gif(self, path):
        self._stop_loading()
        self._movie = QMovie(path)
        if self._gif_optimized:
            target = self.size()
            orig = self._movie.currentPixmap().size()
            if orig.width() > 0 and orig.height() > 0:
                scaled = orig.scaled(target, Qt.AspectRatioMode.KeepAspectRatio)
                self._movie.setScaledSize(scaled)
        self.lbl.setMovie(self._movie)
        self._movie.start()
        self.lbl.setText("")
        if hasattr(self.overlay, "sidebar"):
            self.overlay.sidebar.set_original_loaded(self._viewing_original)

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — video loading
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _load_video  — fetches video into temp_media to avoid FFmpeg    │
    # │  errors and CF blocks when streaming directly via Qt/libVLC.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _load_video(self):
        site_data = self._get_site_data()
        url = _resolve_url(self.file_url, site_data)
        ext = url.rsplit("?", 1)[0].split(".")[-1] or "mp4"

        # ── Clean up previous temp file to prevent unbounded disk growth ──
        self._cleanup_previous_temp()

        def work():
            try:
                data = _fetch_bytes(url, self.post.get('_booru'))
                from ui import settings_view as settings
                tmp = settings.manager.get_download_dir() / "temp_media"
                tmp.mkdir(exist_ok=True, parents=True)
                path = tmp / f"view_{self.post.get('id')}.{ext}"
                path.write_bytes(data)
                self._current_temp_path = str(path)
                self.video_ready.emit(str(path))
            except Exception as e:
                logging.error(f"[media_viewer] Video load error: {e}")

        threading.Thread(target=work, daemon=True).start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _show_video  — lazily creates a VideoPlayerWidget on first      │
    # │  use, then loads the local file path into it.                    │
    # └──────────────────────────────────────────────────────────────────┘
    def _show_video(self, path):
        self.lbl.hide()

        if self._video_widget is None:
            from displayers.video_player import VideoPlayerWidget
            self._video_widget = VideoPlayerWidget()
            self._main_layout.addWidget(self._video_widget, 1)

        self._video_widget.show()
        
        import os
        # Convert absolute path to proper QUrl file:/// format, or just pass absolute path
        abs_path = os.path.abspath(path)
        self._video_widget.load_url(abs_path)

        if hasattr(self.overlay, "sidebar"):
            self.overlay.sidebar.set_original_loaded(True)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  resizeEvent  — re-scales image to fit when the overlay is     │
    # │  resized (e.g. window maximise/restore).                       │
    # └──────────────────────────────────────────────────────────────────┘
    # ══════════════════════════════════════════════════════════════════
    #  Zoom & Pan
    # ══════════════════════════════════════════════════════════════════

    def wheelEvent(self, event):
        if self._media_type != "image" or not hasattr(self, "_pixmap"):
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = getattr(self, "_zoom", 1.0) * factor
        self._zoom = max(0.25, min(self._zoom, 10.0))
        self._apply_zoom()
        event.accept()

    def mousePressEvent(self, event):
        if self._media_type == "image" and event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_start = event.pos()
            self._pan_offset_start = getattr(self, "_pan_offset", QPoint(0, 0))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_panning", False):
            delta = event.pos() - self._pan_start
            self._pan_offset = self._pan_offset_start + delta
            self._apply_zoom()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._panning = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._media_type == "image":
            self._zoom = 1.0
            self._pan_offset = QPoint(0, 0)
            self._apply_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _apply_zoom(self):
        if not hasattr(self, "_pixmap"):
            return
        zoom = getattr(self, "_zoom", 1.0)
        offset = getattr(self, "_pan_offset", QPoint(0, 0))
        target_size = self.size()
        scaled = self._pixmap.scaled(
            target_size * zoom, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Create a larger pixmap to pan within, then crop to the widget
        result = QPixmap(target_size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        x = (target_size.width() - scaled.width()) // 2 + offset.x()
        y = (target_size.height() - scaled.height()) // 2 + offset.y()
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self.lbl.setPixmap(result)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._media_type == "image":
            if getattr(self, "_zoom", 1.0) != 1.0:
                self._apply_zoom()
            else:
                self._fit_pixmap()
