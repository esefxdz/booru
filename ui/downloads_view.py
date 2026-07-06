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
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtCore import QUrl

from ui import colors

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
            _DownloadEntry, QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # ── Top row: filename + status ────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)
        self.name_lbl = QLabel(filename)
        self.name_lbl.setStyleSheet(
            f"color: {colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px; border: none;"
        )
        self.name_lbl.setWordWrap(True)
        top.addWidget(self.name_lbl, 1)

        self.status_lbl = QLabel("Queued")
        self.status_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 12px; border: none;"
        )
        top.addWidget(self.status_lbl)
        layout.addLayout(top)

        # ── Progress bar ──────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setFixedHeight(5)
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

        # ── Bottom row: path / error / elapsed ────────────────────
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 11px; border: none;"
        )
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.info_lbl.mousePressEvent = self._open_folder
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

    def _open_folder(self, event=None):
        """Open the folder containing the downloaded file in Explorer."""
        if self.dest_path:
            folder = str(Path(self.dest_path).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def update_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress.setValue(pct)
            mb_done = current / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.status_lbl.setText(f"{pct}%")
            self.info_lbl.setText(f"{mb_done:.1f} / {mb_total:.1f} MB")

    def mark_active(self):
        self.status_lbl.setText("0%")
        self.status_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px; border: none;")
        self.info_lbl.setText("")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

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
        self.status_lbl.setText("Done ✓")
        self.status_lbl.setStyleSheet(
            f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px; border: none;"
        )
        elapsed = time.time() - self.started_at
        if dest_path:
            self.info_lbl.setText(f"📁 {dest_path}  ({elapsed:.1f}s)")
            self.info_lbl.setToolTip("Click to open folder")
        else:
            self.info_lbl.setText(f"Done in {elapsed:.1f}s")

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
        self.status_lbl.setText("Failed ✕")
        self.status_lbl.setStyleSheet(
            f"color: {colors.DANGER}; font-weight: bold; font-size: 12px; border: none;"
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
        self._active_ids: set[str] = set()
        self._completed_ids: list[str] = []

        self._build_ui()
        self._wire_signals()

    # ─────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(20)

        # ── Header ────────────────────────────────────────────────
        header_row = QHBoxLayout()

        title = QLabel("Downloads")
        title.setStyleSheet(
            f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};"
        )
        header_row.addWidget(title)
        header_row.addStretch()

        # Live badge: "2 active · 14 completed"
        self._badge_lbl = QLabel("idle")
        self._badge_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 13px; padding: 4px 12px;"
            f"background: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px;"
        )
        header_row.addWidget(self._badge_lbl)
        root.addLayout(header_row)

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

        # ── Active section ────────────────────────────────────────
        self._active_section = self._make_section("⬇ Active")
        self._sections_layout.addWidget(self._active_section["card"])
        self._active_empty = QLabel("No active downloads.")
        self._active_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        self._active_section["layout"].addWidget(self._active_empty)

        # ── Queued section ────────────────────────────────────────
        self._queued_section = self._make_section("⏳ Queued")
        self._sections_layout.addWidget(self._queued_section["card"])
        self._queued_empty = QLabel("No downloads queued.")
        self._queued_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        self._queued_section["layout"].addWidget(self._queued_empty)

        # ── Completed section ─────────────────────────────────────
        self._completed_section = self._make_section("✔ Completed")
        self._sections_layout.addWidget(self._completed_section["card"])

        completed_ctrl = QHBoxLayout()
        self._completed_empty = QLabel("No completed downloads yet.")
        self._completed_empty.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        completed_ctrl.addWidget(self._completed_empty, 1)

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
        completed_ctrl.addWidget(clear_btn)
        self._completed_section["layout"].addLayout(completed_ctrl)

        # ── Failed section ────────────────────────────────────────
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
        layout.setSpacing(10)

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

    # ─────────────────────────────────────────────────────────────
    # Badge update
    # ─────────────────────────────────────────────────────────────

    def _update_badge(self):
        active = len(self._active_ids)
        completed = len(self._completed_ids)
        failed_count = 0
        for entry in self._entries.values():
            if entry.error_reason:
                failed_count += 1

        parts = []
        if active:
            parts.append(f"<span style='color:{colors.ACCENT}'>{active} active</span>")
        if completed:
            parts.append(f"<span style='color:{colors.SUCCESS}'>{completed} done</span>")
        if failed_count:
            parts.append(f"<span style='color:{colors.DANGER}'>{failed_count} failed</span>")

        self._badge_lbl.setText(" · ".join(parts) if parts else "idle")

    # ─────────────────────────────────────────────────────────────
    # Helper: move entry between section layouts
    # ─────────────────────────────────────────────────────────────

    def _move_to_section(self, entry: _DownloadEntry, section: dict):
        # Remove from any existing layout ownership
        if entry.parent() is not None:
            old_layout = None
            for sec in [self._queued_section, self._active_section,
                        self._completed_section, self._failed_section]:
                if sec["layout"].indexOf(entry) != -1:
                    old_layout = sec["layout"]
                    break
            if old_layout:
                old_layout.removeWidget(entry)
        entry.setParent(section["card"])
        section["layout"].addWidget(entry)
        entry.show()

    # ─────────────────────────────────────────────────────────────
    # Signal handlers
    # ─────────────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_download_started(self, task_id: str, filename: str):
        entry = self._entries.get(task_id)
        if entry is None:
            entry = _DownloadEntry(task_id, filename)
            self._entries[task_id] = entry

        entry.mark_active()
        self._move_to_section(entry, self._active_section)
        self._active_empty.hide()
        self._active_ids.add(task_id)
        self._update_badge()

    @pyqtSlot(str, int, int)
    def _on_download_progress(self, task_id: str, current: int, total: int):
        entry = self._entries.get(task_id)
        if entry:
            entry.update_progress(current, total)

    @pyqtSlot(str)
    def _on_download_finished(self, task_id: str):
        entry = self._entries.get(task_id)
        if entry is None:
            return

        self._active_ids.discard(task_id)
        self._completed_ids.append(task_id)

        # Resolve the actual dest path if the downloader put it in the post
        dest_path = ""
        entry.mark_completed(dest_path)

        self._move_to_section(entry, self._completed_section)
        self._completed_empty.hide()

        # Hide active empty label only if there really are no active entries
        if not self._active_ids:
            self._active_empty.show()

        self._update_badge()

    @pyqtSlot(str, str)
    def _on_download_failed(self, task_id: str, error: str):
        entry = self._entries.get(task_id)
        if entry is None:
            entry = _DownloadEntry(task_id, task_id)
            self._entries[task_id] = entry

        self._active_ids.discard(task_id)

        entry.mark_failed(error)
        self._move_to_section(entry, self._failed_section)
        self._failed_empty.hide()

        if not self._active_ids:
            self._active_empty.show()

        self._update_badge()

    # ─────────────────────────────────────────────────────────────
    # Clear completed
    # ─────────────────────────────────────────────────────────────

    def clear_completed(self):
        """Remove all completed entries from the view."""
        layout = self._completed_section["layout"]
        # Iterate in reverse to safely remove widgets
        for i in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, _DownloadEntry) and w._completed:
                layout.removeWidget(w)
                tid = w.task_id
                self._entries.pop(tid, None)
                if tid in self._completed_ids:
                    self._completed_ids.remove(tid)
                w.deleteLater()

        self._completed_empty.show()
        self._update_badge()
