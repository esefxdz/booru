"""
displayers/video_player.py — Multi-engine video player widget.

Supports three backends (selectable in Global Settings → Video Engine):
  1. "qt"  — Built-in QtMultimedia (default, no extra deps)
  2. "vlc" — python-vlc / libVLC (optional, better codec support)
  3. "mpv" — python-mpv / libmpv  (optional, best quality)

Falls back to Qt if the selected engine fails to load.
"""
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QStyle, QStyleOptionSlider,
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QSettings, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from ui import colors
from ui import settings_view as settings


#creator note, i know this is some yandere dev bullshit here, but im gonna keep all these ifs cause and keep this boilerplated code cuz im lazy

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: ClickableSlider                                             ║
# ║  A QSlider that jumps directly to the clicked position instead of  ║
# ║  stepping page-by-page (Qt's default behaviour). Used for seek.    ║
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
# ║  CLASS: ClickableVideoWidget                                        ║
# ║  Thin QVideoWidget wrapper that emits `clicked` on left-click so   ║
# ║  we can wire click-to-pause on the video surface itself.           ║
# ╚══════════════════════════════════════════════════════════════════════╝
class ClickableVideoWidget(QVideoWidget):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: VideoPlayerWidget                                           ║
# ║  Self-contained video player with seek bar, volume slider, time    ║
# ║  label, and auto-loop.  Engine selection is read from settings at  ║
# ║  construction time; if the chosen engine (VLC/MPV) isn't installed ║
# ║  it silently falls back to the Qt built-in.                        ║
# ╚══════════════════════════════════════════════════════════════════════╝
class VideoPlayerWidget(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — builds the widget tree: video container (top,     │
    # │  stretches) + controls bar (bottom, fixed height).  The actual │
    # │  playback engine is initialised in _init_engine().             │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)

        # ── Engine type from user settings ──
        self.engine_type = settings.manager.video_engine

        # ── Video render surface container ──
        self.video_container = QWidget()
        self._video_layout = QVBoxLayout(self.video_container)
        self._video_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.addWidget(self.video_container, 1)

        # ── Transport controls (seek, time, volume) ──
        self._init_controls()

        # ── Playback state ──
        self.player = None
        self.vlc_instance = None
        self.mpv_player = None
        self._timer = None

        # ── Boot the selected engine ──
        self._init_engine()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _init_controls  — seek bar, time label, volume icon + slider. │
    # │  Volume is persisted to QSettings so it survives app restarts. │
    # └──────────────────────────────────────────────────────────────────┘
    def _init_controls(self):
        self.controls_widget = QWidget()
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(10, 10, 10, 10)

        # ── Seek slider ──
        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: {colors.BUTTON_BG}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {colors.ACCENT}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {colors.ACCENT};
                width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
            }}
        """)
        self.seek_slider.sliderMoved.connect(self._set_position)
        controls_layout.addWidget(self.seek_slider)

        # ── Bottom bar: time label + volume ──
        bottom_bar = QHBoxLayout()

        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")
        bottom_bar.addWidget(self.time_lbl)

        vol_lbl = QLabel("🔊")
        vol_lbl.setStyleSheet(f"color: {colors.TEXT_PRIMARY};")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(80)

        from ui.settings_view.manager import BASE_DIR
        qs = QSettings(str(BASE_DIR / "displayers.ini"), QSettings.Format.IniFormat)
        saved_vol = qs.value("VideoPlayer/volume", 50, type=int)
        self.vol_slider.setValue(saved_vol)
        self.vol_slider.valueChanged.connect(self._set_volume)

        bottom_bar.addWidget(vol_lbl)
        bottom_bar.addWidget(self.vol_slider)
        bottom_bar.addStretch()
        controls_layout.addLayout(bottom_bar)

        self._main_layout.addWidget(self.controls_widget)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _init_engine  — tries the user's preferred engine; falls back │
    # │  to Qt if VLC or MPV can't be imported.  Each engine gets a    │
    # │  QTimer that ticks every 100 ms to update the seek bar.        │
    # └──────────────────────────────────────────────────────────────────┘
    def _init_engine(self):
        # ── Try VLC ──
        if self.engine_type == "vlc":
            try:
                import vlc
                self.vlc_instance = vlc.Instance()
                self.player = self.vlc_instance.media_player_new()

                self.video_frame = QWidget()
                self.video_frame.setStyleSheet("background-color: black;")
                self._video_layout.addWidget(self.video_frame)

                import sys
                if sys.platform.startswith("linux"):
                    self.player.set_xwindow(self.video_frame.winId())
                elif sys.platform == "win32":
                    self.player.set_hwnd(int(self.video_frame.winId()))
                elif sys.platform == "darwin":
                    self.player.set_nsobject(int(self.video_frame.winId()))

                self._timer = QTimer(self)
                self._timer.setInterval(100)
                self._timer.timeout.connect(self._update_vlc_ui)
                return
            except Exception as e:
                logging.info(f"[video_player] VLC unavailable, falling back to Qt: {e}")
                self.engine_type = "qt"

        # ── Try MPV ──
        if self.engine_type == "mpv":
            try:
                import mpv
                self.video_frame = QWidget()
                self.video_frame.setStyleSheet("background-color: black;")
                self._video_layout.addWidget(self.video_frame)

                self.mpv_player = mpv.MPV(
                    wid=int(self.video_frame.winId()),
                    log_handler=logging.info,
                )

                self._timer = QTimer(self)
                self._timer.setInterval(100)
                self._timer.timeout.connect(self._update_mpv_ui)
                return
            except Exception as e:
                logging.info(f"[video_player] MPV unavailable, falling back to Qt: {e}")
                self.engine_type = "qt"

        # ── Default: QtMultimedia ──
        self._qt_video_widget = ClickableVideoWidget()
        self._qt_video_widget.clicked.connect(self.toggle_play)
        self._video_layout.addWidget(self._qt_video_widget)

        self.player = QMediaPlayer()
        self._audio = QAudioOutput()
        self.player.setAudioOutput(self._audio)
        self.player.setVideoOutput(self._qt_video_widget)

        from ui.settings_view.manager import BASE_DIR
        qs = QSettings(str(BASE_DIR / "displayers.ini"), QSettings.Format.IniFormat)
        saved_vol = qs.value("VideoPlayer/volume", 50, type=int)
        self._audio.setVolume(saved_vol / 100.0)

        self.player.positionChanged.connect(self._qt_position_changed)
        self.player.durationChanged.connect(self._qt_duration_changed)
        self.player.mediaStatusChanged.connect(self._qt_status_changed)

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_url  — starts playback of the given URL (http or local). │
    # └──────────────────────────────────────────────────────────────────┘
    def load_url(self, url):
        if self.engine_type == "vlc":
            media = self.vlc_instance.media_new(url)
            self.player.set_media(media)
            self.player.play()
            if self._timer:
                self._timer.start()
        elif self.engine_type == "mpv":
            self.mpv_player.play(url)
            if self._timer:
                self._timer.start()
        else:
            import os
            from PyQt6.QtCore import QUrl
            if os.path.exists(url):
                self.player.setSource(QUrl.fromLocalFile(url))
            else:
                self.player.setSource(QUrl(url))
            self.player.play()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  toggle_play  — pause/resume.  Used by click-on-video.         │
    # └──────────────────────────────────────────────────────────────────┘
    def toggle_play(self):
        if self.engine_type == "vlc":
            if self.player:
                self.player.pause()
        elif self.engine_type == "mpv":
            if self.mpv_player:
                self.mpv_player.pause = not self.mpv_player.pause
        else:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  stop  — fully stops playback and frees resources so the next  │
    # │  post can start clean. Also stops the UI-update timer.         │
    # └──────────────────────────────────────────────────────────────────┘
    def stop(self):
        if self._timer:
            self._timer.stop()
        if self.engine_type == "vlc":
            if self.player:
                self.player.stop()
        elif self.engine_type == "mpv":
            if self.mpv_player:
                try:
                    self.mpv_player.command("stop")
                except Exception:
                    pass
        else:
            if self.player:
                self.player.stop()
                self.player.setSource(QUrl(""))

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — volume, seek, time formatting
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _set_volume  — applies volume and persists to QSettings.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _set_volume(self, v):
        from ui.settings_view.manager import BASE_DIR
        qs = QSettings(str(BASE_DIR / "displayers.ini"), QSettings.Format.IniFormat)
        qs.setValue("VideoPlayer/volume", v)
        if self.engine_type == "vlc":
            if self.player:
                self.player.audio_set_volume(v)
        elif self.engine_type == "mpv":
            if self.mpv_player:
                self.mpv_player.volume = v
        else:
            if hasattr(self, "_audio"):
                self._audio.setVolume(v / 100.0)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _set_position  — called when the user drags the seek bar.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _set_position(self, pos):
        if self.engine_type == "vlc":
            if self.player:
                self.player.set_time(pos)
        elif self.engine_type == "mpv":
            if self.mpv_player:
                self.mpv_player.time_pos = pos / 1000.0
        else:
            if self.player:
                self.player.setPosition(pos)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _format_time  — converts milliseconds to "M:SS" or "H:MM:SS" │
    # └──────────────────────────────────────────────────────────────────┘
    @staticmethod
    def _format_time(ms):
        s = max(0, round(ms / 1000))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02}:{s:02}" if h > 0 else f"{m}:{s:02}"

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — per-engine UI updaters (called by QTimer)
    # ══════════════════════════════════════════════════════════════════

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _update_vlc_ui  — polls VLC for position/duration and auto-   │
    # │  loops when playback reaches the end (state == 6 == Ended).    │
    # └──────────────────────────────────────────────────────────────────┘
    def _update_vlc_ui(self):
        if not self.player:
            return
        try:
            if not self.player.is_playing() and self.player.get_state() == 6:
                self.player.set_position(0)
                self.player.play()

            length = self.player.get_length()
            time = self.player.get_time()
            if length > 0:
                self.seek_slider.setRange(0, length)
                if not self.seek_slider.isSliderDown():
                    self.seek_slider.setValue(time)
                self.time_lbl.setText(
                    f"{self._format_time(time)} / {self._format_time(length)}"
                )
        except Exception:
            pass

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _update_mpv_ui  — polls MPV properties (seconds-based, not    │
    # │  ms) and auto-loops on EOF.                                    │
    # └──────────────────────────────────────────────────────────────────┘
    def _update_mpv_ui(self):
        if not self.mpv_player:
            return
        try:
            length = getattr(self.mpv_player, "duration", 0) or 0
            time = getattr(self.mpv_player, "time_pos", 0) or 0
            if length:
                length_ms = int(length * 1000)
                time_ms = int(time * 1000)
                self.seek_slider.setRange(0, length_ms)
                if not self.seek_slider.isSliderDown():
                    self.seek_slider.setValue(time_ms)
                self.time_lbl.setText(
                    f"{self._format_time(time_ms)} / {self._format_time(length_ms)}"
                )
            if getattr(self.mpv_player, "eof_reached", False):
                self.mpv_player.seek(0, reference="absolute")
                self.mpv_player.pause = False
        except Exception:
            pass

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  Qt-engine callbacks — connected to QMediaPlayer signals.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _qt_position_changed(self, pos):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(pos)
        self._qt_update_time()

    def _qt_duration_changed(self, dur):
        self.seek_slider.setRange(0, dur)
        self._qt_update_time()

    def _qt_update_time(self):
        cur = self._format_time(self.player.position())
        tot = self._format_time(self.player.duration())
        self.time_lbl.setText(f"{cur} / {tot}")

    def _qt_status_changed(self, status):
        """Auto-loop: restart from the beginning when the video ends."""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.play()
