###########################################################################################
#displayers/legacy_window.py — Legacy standalone media viewer (subprocess mode).
#
#Used only when `use_legacy_viewer` is enabled in Global Settings.
#Spawns a separate PyQt6 window as a subprocess, keeping it fully decoupled
#from the main app process.
#
#Entry point (called by UniversalViewer):
#    python -m displayers.legacy_window <url> <post_json>
############################################################################################

import sys
import os
import json
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QSettings
from PyQt6.QtGui import QPixmap, QMovie
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QSlider, QStyleOptionSlider,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
import httpx


# ══════════════════════════════════════════════════════════════════════
#  MODULE HELPERS  (standalone — no dependency on the rest of the app)
# ══════════════════════════════════════════════════════════════════════

_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
}


def _resolve_url(url):
    """Normalize protocol-relative URLs."""
    if url and url.startswith("//"):
        return "https:" + url
    return url or ""


def _fetch_bytes(url):
    """Download URL bytes. Raises on failure."""
    res = httpx.get(url, headers=_IMAGE_HEADERS, follow_redirects=True, timeout=30)
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code} from {url}")
    return res.content


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: ClickableVideoWidget                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝
class ClickableVideoWidget(QVideoWidget):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: ClickableSlider                                              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            val = self.style().sliderValueFromPosition(
                self.minimum(), self.maximum(),
                event.pos().x(), self.width(), opt.upsideDown
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(event)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: DisplayerWindow                                              ║
# ║  Legacy standalone window launched as a subprocess.                 ║
# ╚══════════════════════════════════════════════════════════════════════╝
class DisplayerWindow(QMainWindow):
    image_ready = pyqtSignal(bytes)
    gif_ready = pyqtSignal(str)

    def __init__(self, post, file_url):
        super().__init__()
        self.post = post
        self.file_url = file_url
        self.post_id = str(post.get("id"))
        self._viewing_original = False

        self.setWindowTitle(f"Media Viewer - Post #{self.post_id}")
        self.setStyleSheet("background-color: #121212; color: #ffffff;")

        # Restore saved window geometry, default 700x550
        self._qs = QSettings("BooruBrowser", "Displayer")
        w = self._qs.value("window_w", 700, type=int)
        h = self._qs.value("window_h", 550, type=int)
        self.resize(w, h)
        self.setMinimumSize(200, 150)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # --- Top Bar ---
        topbar = QWidget()
        topbar.setFixedHeight(50)
        topbar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(15, 0, 15, 0)

        title = QLabel(f"Post #{self.post_id}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ccc;")
        top_layout.addWidget(title)
        top_layout.addStretch()

        self.orig_btn = QPushButton("View Original")
        self.orig_btn.setStyleSheet(self._btn_css())
        self.orig_btn.clicked.connect(self._load_original)
        top_layout.addWidget(self.orig_btn)

        self.dl_btn = QPushButton("Download")
        self.dl_btn.setStyleSheet(self._btn_css())
        self.dl_btn.clicked.connect(self._download)
        top_layout.addWidget(self.dl_btn)

        self._is_bookmarked = self._check_bookmarked()
        self.bm_btn = QPushButton("Bookmarked" if self._is_bookmarked else "Bookmark")
        self.bm_btn.setStyleSheet(self._btn_css(gold=self._is_bookmarked))
        self.bm_btn.clicked.connect(self._toggle_bookmark)
        top_layout.addWidget(self.bm_btn)

        self.main_layout.addWidget(topbar)

        # --- Content Area ---
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.content, stretch=1)

        self.image_ready.connect(self._show_image)
        self.gif_ready.connect(self._show_gif)

        self.lbl = QLabel("Loading...")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.lbl)

        ext = self.file_url.rsplit("?", 1)[0].lower()
        if any(ext.endswith(v) for v in (".mp4", ".webm")):
            self._media_type = "video"
            self._init_video()
        elif ext.endswith(".gif"):
            self._media_type = "gif"
            self._load_gif(optimized=True)
        else:
            self._media_type = "image"
            self._load_image(optimized=True)

    # ----- Styles -----

    def _btn_css(self, gold=False):
        c = "gold" if gold else "white"
        return f"""
        QPushButton {{
            background-color: #333; color: {c}; border: none;
            border-radius: 4px; padding: 8px 15px; font-weight: bold;
        }}
        QPushButton:hover {{ background-color: #444; }}
        """

    # ----- Bookmarks -----

    def _bm_path(self):
        return Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "bookmarks.json"

    def _read_bookmarks(self):
        p = self._bm_path()
        if not p.exists():
            return []
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_bookmarks(self, bms):
        p = self._bm_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(bms, f, indent=2)

    def _check_bookmarked(self):
        return any(str(p.get("id")) == self.post_id for p in self._read_bookmarks())

    def _toggle_bookmark(self):
        bms = self._read_bookmarks()
        if self._is_bookmarked:
            bms = [p for p in bms if str(p.get("id")) != self.post_id]
            self._is_bookmarked = False
        else:
            bms.append(self.post)
            self._is_bookmarked = True
        self._write_bookmarks(bms)
        self.bm_btn.setText("Bookmarked" if self._is_bookmarked else "Bookmark")
        self.bm_btn.setStyleSheet(self._btn_css(gold=self._is_bookmarked))

    # ----- Download -----

    def _download(self):
        self.dl_btn.setText("Downloading...")
        def work():
            try:
                dl_dir = Path("files")
                dl_dir.mkdir(exist_ok=True)
                ext = os.path.splitext(self.file_url.split("?")[0])[1] or ".jpg"
                path = dl_dir / f"{self.post_id}{ext}"
                data = _fetch_bytes(self.file_url)
                path.write_bytes(data)
                self.dl_btn.setText("Downloaded")
            except Exception as e:
                print(f"[legacy_window] Download error: {e}")
                self.dl_btn.setText("Failed")
        threading.Thread(target=work, daemon=True).start()

    # ----- View Original -----

    def _load_original(self):
        if self._viewing_original:
            return
        self._viewing_original = True
        self.orig_btn.setText("Loading...")
        self.orig_btn.setEnabled(False)
        if self._media_type == "image":
            self._load_image(optimized=False)
        elif self._media_type == "gif":
            self._load_gif(optimized=False)

    # ----- Image Loading -----

    def _get_image_url(self, optimized):
        if optimized:
            url = (self.post.get("sample_url")
                   or self.post.get("large_file_url")
                   or self.file_url)
        else:
            url = self.file_url
        return _resolve_url(url)

    def _load_image(self, optimized):
        url = self._get_image_url(optimized)
        def work():
            try:
                data = _fetch_bytes(url)
                self.image_ready.emit(data)
            except Exception as e:
                print(f"[legacy_window] Image load error: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _show_image(self, data):
        pix = QPixmap()
        if not pix.loadFromData(data):
            print("[legacy_window] Failed to decode image bytes")
            self.lbl.setText("Failed to load image")
            return
        self._pixmap = pix
        self._fit_pixmap()
        self.lbl.setText("")
        if self._viewing_original:
            self.orig_btn.setText("Original")

    def _fit_pixmap(self):
        if not hasattr(self, "_pixmap"):
            return
        target = self.content.size()
        scaled = self._pixmap.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.lbl.setPixmap(scaled)

    # ----- GIF Loading -----

    def _load_gif(self, optimized):
        url = _resolve_url(self.file_url)
        self._gif_optimized = optimized
        def work():
            try:
                data = _fetch_bytes(url)
                tmp = Path("./temp_media")
                tmp.mkdir(exist_ok=True)
                path = tmp / f"view_{self.post_id}.gif"
                path.write_bytes(data)
                self.gif_ready.emit(str(path))
            except Exception as e:
                print(f"[legacy_window] GIF load error: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _show_gif(self, path):
        self.movie = QMovie(path)
        if self._gif_optimized:
            target = self.content.size()
            orig = self.movie.currentPixmap().size()
            if orig.width() > 0 and orig.height() > 0:
                scaled = orig.scaled(target, Qt.AspectRatioMode.KeepAspectRatio)
                self.movie.setScaledSize(scaled)
        self.lbl.setMovie(self.movie)
        self.movie.start()
        self.lbl.setText("")
        if self._viewing_original:
            self.orig_btn.setText("Original")

    # ----- Video -----

    def _init_video(self):
        self.lbl.hide()

        self.video_widget = ClickableVideoWidget()
        self.content_layout.addWidget(self.video_widget)
        self.video_widget.clicked.connect(self._toggle_play)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.setSource(QUrl(self.file_url))

        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(2)

        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #ff0000; border-radius: 2px; }
            QSlider::handle:horizontal {
                background: #ff0000; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
        """)
        self.seek_slider.sliderMoved.connect(self._set_position)
        controls_layout.addWidget(self.seek_slider)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(5, 5, 5, 0)

        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setStyleSheet("color: #ccc; font-size: 13px; font-weight: 500;")
        bottom_bar.addWidget(self.time_lbl)

        vol_lbl = QLabel("  🔊")
        vol_lbl.setStyleSheet("color: white; font-size: 14px;")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #fff; border-radius: 2px; }
            QSlider::handle:horizontal { background: #fff; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
        """)

        qs = QSettings("BooruBrowser", "Displayer")
        saved = qs.value("volume", 50, type=int)
        self.vol_slider.setValue(saved)
        self.audio.setVolume(saved / 100.0)
        self.vol_slider.valueChanged.connect(lambda v: (
            self.audio.setVolume(v / 100.0),
            qs.setValue("volume", v)
        ))

        bottom_bar.addWidget(vol_lbl)
        bottom_bar.addWidget(self.vol_slider)
        bottom_bar.addStretch()

        controls_layout.addLayout(bottom_bar)
        self.content_layout.addLayout(controls_layout)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.mediaStatusChanged.connect(self._loop_video)

        self.player.play()
        self.orig_btn.hide()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _format_time(self, ms):
        s = round(ms / 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02}:{s:02}"
        return f"{m}:{s:02}"

    def _update_time_label(self):
        cur = self._format_time(self.player.position())
        tot = self._format_time(self.player.duration())
        self.time_lbl.setText(f"{cur} / {tot}")

    def _position_changed(self, position):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self._update_time_label()

    def _duration_changed(self, duration):
        self.seek_slider.setRange(0, duration)
        self._update_time_label()

    def _set_position(self, position):
        self.player.setPosition(position)

    def _loop_video(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()

    # ----- Resize / Close -----

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._media_type == "image":
            self._fit_pixmap()

    def closeEvent(self, event):
        self._qs.setValue("window_w", self.width())
        self._qs.setValue("window_h", self.height())
        super().closeEvent(event)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: UniversalViewer                                              ║
# ║  Thin launcher used by gui.py when legacy mode is enabled.          ║
# ╚══════════════════════════════════════════════════════════════════════╝
class UniversalViewer:
    """Spawns the legacy PyQt6 displayer as a separate subprocess."""
    def __init__(self, parent_gui, post):
        import subprocess
        file_url = parent_gui.downloader.get_file_url(post)
        cmd = ["python", "-m", "displayers.legacy_window", file_url, json.dumps(post)]
        subprocess.Popen(cmd)


# ══════════════════════════════════════════════════════════════════════
#  MODULE ENTRYPOINT  (python -m displayers.legacy_window <url> <json>)
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m displayers.legacy_window <url> <post_json>")
        sys.exit(1)

    app = QApplication(sys.argv)
    file_url = sys.argv[1]
    post = json.loads(sys.argv[2])

    window = DisplayerWindow(post, file_url)
    window.show()
    sys.exit(app.exec())
