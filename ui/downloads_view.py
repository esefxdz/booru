"""
ui/downloads_view.py — Full-page Downloads tab.

Shows four sections:
  • Queued    — downloads waiting to start
  • Active    — currently downloading, with live progress bars
  • Completed — finished successfully (filename, path, timestamp)
  • Failed    — errored out (filename, reason, retry button)

Driven by BooruDownloader signals: download_started, download_progress,
download_finished, download_failed.
"""
from __future__ import annotations
import logging
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QCursor

from ui import colors
from ui import settings_view as settings

_log = logging.getLogger(__name__)


class _DownloadEntry(QFrame):
    """A single download row: filename, progress bar, status text."""

    def __init__(self, task_id: str, filename: str, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.filename = filename
        self.dest_path = ""
        self.error_reason = ""
        self.started_at = time.time()
        self._completed = False

        self.setStyleSheet(f"""
            _DownloadEntry {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # ── Top row: filename + status ────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_lbl = QLabel(filename)
        self.name_lbl.setStyleSheet(
            f"color: {colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;"
        )
        self.name_lbl.setWordWrap(True)
        top.addWidget(self.name_lbl, 1)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 12px;"
        )
        top.addWidget(self.status_lbl)
        layout.addLayout(top)

        # ── Progress bar ──────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {colors.MAIN_BG};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {colors.ACCENT};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress)

        # ── Bottom row: path or error ─────────────────────────────
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 11px;"
        )
        self.info_lbl.setWordWrap(True)
        layout.addWidget(self.info_lbl)

        # ── Retry button (hidden by default) ──────────────────────
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setFixedHeight(28)
        self.retry_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.retry_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.ACCENT};
                border: 1px solid {colors.ACCENT};
                border-radius: 4px;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {colors.ACCENT}; color: white; }}
        """)
        self.retry_btn.hide()
        layout.addWidget(self.retry_btn)

    def update_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress.setValue(pct)
            self.status_lbl.setText(f"{pct}%")

    def mark_completed(self, dest_path: str = ""):
        self._completed = True
        self.dest_path = dest_path
        self.progress.setValue(100)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {colors.MAIN_BG};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {colors.SUCCESS};
                border-radius: 3px;
            }}
        """)
        self.status_lbl.setText("Done")
        self.status_lbl.setStyleSheet(
            f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;"
        )
        if dest_path:
            self.info_lbl.setText(str(dest_path))
        elapsed = time.time() - self.started_at
        self.name_lbl.setToolTip(f"Completed in {elapsed:.1f}s")

    def mark_failed(self, error: str):
        self.error_reason = error
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {colors.MAIN_BG};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {colors.DANGER};
                border-radius: 3px;
            }}
        """)
        self.status_lbl.setText("Failed")
        self.status_lbl.setStyleSheet(
            f"color: {colors.DANGER}; font-weight: bold; font-size: 12px;"
        )
        self.info_lbl.setText(error)
        self.retry_btn.show()


class DownloadsView(QWidget):
    """Full-page view: Queued / Active / Completed / Failed downloads."""

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        # ── Data stores ───────────────────────────────────────────
        self._entries: dict[str, _DownloadEntry] = {}  # task_id → widget
        self._queued: list[tuple[str, str]] = []       # [(task_id, filename), ...]

        self._build_ui()
        self._wire_signals()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(24)

        # ── Header ────────────────────────────────────────────────
        title = QLabel("Downloads")
        title.setStyleSheet(
            f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};"
        )
        root.addWidget(title)

        subtitle = QLabel("Track your active, queued, and completed downloads.")
        subtitle.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_MUTED};")
        root.addWidget(subtitle)

        # ── Scroll area for all sections ──────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._sections_layout = QVBoxLayout(container)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(20)

        # ── Sections ──────────────────────────────────────────────
        self._queued_section = self._make_section("⏳ Queued")
        self._sections_layout.addWidget(self._queued_section["card"])
        self._queued_empty = QLabel("No downloads queued.")
        self._queued_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        self._queued_section["layout"].addWidget(self._queued_empty)

        self._active_section = self._make_section("⬇ Active")
        self._sections_layout.addWidget(self._active_section["card"])
        self._active_empty = QLabel("No active downloads.")
        self._active_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        self._active_section["layout"].addWidget(self._active_empty)

        self._completed_section = self._make_section("✔ Completed")
        self._sections_layout.addWidget(self._completed_section["card"])

        # Clear button row
        clear_row = QHBoxLayout()
        self._completed_empty = QLabel("No completed downloads yet.")
        self._completed_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        clear_row.addWidget(self._completed_empty, 1)
        clear_btn = QPushButton("Clear all")
        clear_btn.setFixedHeight(28)
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.TEXT_MUTED};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {colors.DANGER}; border-color: {colors.DANGER}; }}
        """)
        clear_btn.clicked.connect(self.clear_completed)
        clear_row.addWidget(clear_btn)
        self._completed_section["layout"].addLayout(clear_row)

        self._failed_section = self._make_section("✕ Failed")
        self._sections_layout.addWidget(self._failed_section["card"])
        self._failed_empty = QLabel("No failed downloads.")
        self._failed_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        self._failed_section["layout"].addWidget(self._failed_empty)

        self._sections_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    def _make_section(self, title: str) -> dict:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel(title)
        header.setStyleSheet(
            f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 16px;"
        )
        layout.addWidget(header)

        return {"card": card, "layout": layout}

    def _wire_signals(self):
        dl = self.main_app.downloader
        dl.download_started.connect(self._on_download_started)
        dl.download_progress.connect(self._on_download_progress)
        dl.download_finished.connect(self._on_download_finished)
        dl.download_failed.connect(self._on_download_failed)

    # ── Public API for queuing ────────────────────────────────────

    def enqueue(self, task_id: str, filename: str):
        """Add a download to the queue (not yet started)."""
        self._queued.append((task_id, filename))
        self._queued_empty.hide()
        entry = _DownloadEntry(task_id, filename)
        entry.status_lbl.setText("Queued")
        self._entries[task_id] = entry
        self._queued_section["layout"].addWidget(entry)

    # ── Signal handlers ───────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_download_started(self, task_id, filename):
        # Move from queued to active if it was queued; otherwise create new
        entry = self._entries.get(task_id)
        if entry is None:
            entry = _DownloadEntry(task_id, filename)
            self._entries[task_id] = entry
        else:
            # Remove from queued section layout
            self._queued_section["layout"].removeWidget(entry)
            self._queued = [(tid, fn) for tid, fn in self._queued if tid != task_id]
            if not self._queued:
                self._queued_empty.show()

        entry.status_lbl.setText("0%")
        self._active_section["layout"].addWidget(entry)
        self._active_empty.hide()
        entry.show()

    @pyqtSlot(str, int, int)
    def _on_download_progress(self, task_id, current, total):
        entry = self._entries.get(task_id)
        if entry:
            entry.update_progress(current, total)

    @pyqtSlot(str)
    def _on_download_finished(self, task_id):
        entry = self._entries.get(task_id)
        if entry is None:
            return

        # Move from active to completed
        self._active_section["layout"].removeWidget(entry)
        # Check if active section is now empty
        if self._active_section["layout"].count() <= 1:  # just the empty label
            self._active_empty.show()

        entry.mark_completed()
        self._completed_section["layout"].addWidget(entry)
        self._completed_empty.hide()
        entry.show()

    @pyqtSlot(str, str)
    def _on_download_failed(self, task_id, error):
        entry = self._entries.get(task_id)
        if entry is None:
            entry = _DownloadEntry(task_id, task_id)
            self._entries[task_id] = entry

        # Remove from wherever it was
        for section in [self._queued_section, self._active_section]:
            if entry.parent() is section["card"]:
                section["layout"].removeWidget(entry)

        entry.mark_failed(error)
        self._failed_section["layout"].addWidget(entry)
        self._failed_empty.hide()
        entry.show()

    # ── Clear completed ───────────────────────────────────────────

    def clear_completed(self):
        """Remove all completed entries from the view."""
        layout = self._completed_section["layout"]
        while layout.count() > 1:  # keep the empty label
            w = layout.itemAt(1).widget()
            if w and isinstance(w, _DownloadEntry):
                layout.removeWidget(w)
                tid = w.task_id
                self._entries.pop(tid, None)
                w.deleteLater()
            else:
                break
        self._completed_empty.show()
