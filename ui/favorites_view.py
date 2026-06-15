from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QScrollArea,
    QLineEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QCursor

from ui import settings_view as settings
from ui.icons import Icons
from ui.text_bar import BooruTextBar
# TagChip is shared with BlacklistView — defined once in tag_chip.py
from ui.tag_chip import TagChip


from validation import sanitize_tag_list
import ui.animations as anims
from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: FavoritesView                                               ║
# ║  Full-page widget for managing the global favorites tag list.      ║
# ║  Tags here are automatically appended to EVERY search query so the ║
# ║  user always sees content that matches at least one of them.       ║
# ╚══════════════════════════════════════════════════════════════════════╝
class FavoritesView(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — identical layout to BlacklistView, two-column:     │
    # │  left side has tag controls, right side has info + clear button │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(40, 40, 40, 40)
        self._main_layout.setSpacing(24)

        self._build_header()

        content_h = QHBoxLayout()
        content_h.setSpacing(32)
        self._main_layout.addLayout(content_h, 1)

        # ── Left Column: all interactive tag controls ──────────────────
        left_v = QVBoxLayout()
        left_v.setSpacing(20)
        content_h.addLayout(left_v, 2)

        # Quick-add row: a text input bar next to an "Add Tag" button
        add_h = QHBoxLayout()
        self.add_input = BooruTextBar(self, placeholder="Add tags to favorites...")
        # Pressing Enter in the input bar also triggers the add
        self.add_input.submitted.connect(self._on_add_tag)
        add_h.addWidget(self.add_input)

        self.add_btn = QPushButton("Add Tag")
        self.add_btn.setFixedSize(100, 44)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)
        self.add_btn.clicked.connect(self._on_add_tag)
        add_h.addWidget(self.add_btn)
        left_v.addLayout(add_h)

        # Scrollable chip area — one TagChip widget per saved favorite tag
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{ 
                border: 1px solid {colors.BORDER}; 
                border-radius: 8px; 
                background-color: {colors.INPUT_BG}; 
            }}
        """)
        self.chip_container = QWidget()
        self.chip_container.setStyleSheet("background-color: transparent;")
        self.chip_layout = QVBoxLayout(self.chip_container)
        self.chip_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chip_layout.setContentsMargins(12, 12, 12, 12)
        self.chip_layout.setSpacing(8)
        self.scroll.setWidget(self.chip_container)
        left_v.addWidget(self.scroll, 1)

        # Toggle link for switching between visual chips and raw text editing
        self.bulk_toggle = QPushButton("📝 Switch to Raw Text Mode")
        self.bulk_toggle.setStyleSheet(f"""
            color: {colors.LINK}; 
            text-align: left; 
            background: transparent; 
            border: none; 
            font-size: 13px;
        """)
        self.bulk_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bulk_toggle.clicked.connect(self._toggle_bulk_mode)
        left_v.addWidget(self.bulk_toggle)

        # The raw text editor is hidden by default; it appears in bulk edit mode
        self.raw_edit = QTextEdit()
        self.raw_edit.hide()
        self.raw_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {colors.INPUT_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', 'Monaco', monospace;
            }}
        """)
        left_v.addWidget(self.raw_edit, 1)

        # ── Right Column: static info card + clear-all button ──────────
        right_v = QVBoxLayout()
        right_v.setSpacing(20)
        content_h.addLayout(right_v, 1)

        info_card = QFrame()
        info_card.setStyleSheet(f"""
            background-color: {colors.PANEL_BG}; 
            border: 1px solid {colors.BORDER}; 
            border-radius: 12px; 
            padding: 20px;
        """)
        info_v = QVBoxLayout(info_card)
        info_title = QLabel("Why favorite tags?")
        info_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: bold; font-size: 16px;")
        info_v.addWidget(info_title)
        info_text = QLabel(
            "Favorite tags ensure content is always included in your searches.\n\n"
            "• Works across all Boorus\n"
            "• Automatically appended to every query\n"
            "• Opposite of the blacklist\n"
            "• Use spaces to separate tags"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px; line-height: 1.4;")
        info_v.addWidget(info_text)
        info_v.addStretch()
        right_v.addWidget(info_card)

        # Danger-style clear button — outline red, fills red on hover
        clear_btn = QPushButton("🗑 Clear All Tags")
        clear_btn.setFixedHeight(40)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {colors.DANGER};
                color: {colors.DANGER};
                border-radius: 8px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {colors.DANGER}; color: {colors.TEXT_PRIMARY}; }}
        """)
        clear_btn.clicked.connect(self._clear_all)
        right_v.addWidget(clear_btn)
        right_v.addStretch()

        # Confirmation label that briefly appears after saving
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
        self._main_layout.addWidget(self.status_lbl)
        self._main_layout.addWidget(QLabel(""))  # Visual bottom spacer

        # Tracks whether the user is currently in raw text bulk edit mode
        self._bulk_mode = False

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _build_header  — large title + subtitle + the Save button      │
    # └──────────────────────────────────────────────────────────────────┘
    def _build_header(self):
        header = QHBoxLayout()
        title_v = QVBoxLayout()
        title = QLabel("Favorite Tags")
        title.setStyleSheet(f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};")
        title_v.addWidget(title)
        subtitle = QLabel("Global inclusion system. Tags here are automatically added to all searches.")
        subtitle.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_MUTED};")
        title_v.addWidget(subtitle)
        header.addLayout(title_v)
        header.addStretch()
        self.save_btn = QPushButton("💾 Save Changes")
        self.save_btn.setFixedSize(160, 44)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.ACCENT}; color: {colors.TEXT_PRIMARY};
                font-size: 14px; font-weight: bold; border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {colors.ACCENT_HOVER}; }}
        """)
        self.save_btn.clicked.connect(self.save_favorites)
        header.addWidget(self.save_btn)
        self._main_layout.addLayout(header)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_favorites  — called every time this page becomes visible  │
    # │  Reads settings.manager.favorites and repopulates the chip list         │
    # └──────────────────────────────────────────────────────────────────┘
    def load_favorites(self):
        self.status_lbl.hide()  # Clear any stale confirmation from last visit
        tags = settings.manager.favorites.split()
        self._clear_chips()
        for tag in tags:
            self._add_chip_ui(tag)
        # Mirror into the raw text editor even while it's hidden
        self.raw_edit.setPlainText(settings.manager.favorites)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _clear_chips  — destroys all TagChip widgets and frees memory  │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_chips(self):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _add_chip_ui  — instantiates one TagChip and wires up its     │
    # │  removed signal to auto-update the list when ✕ is clicked      │
    # └──────────────────────────────────────────────────────────────────┘
    def _add_chip_ui(self, tag):
        chip = TagChip(tag)
        chip.removed.connect(self._on_tag_removed)
        self.chip_layout.addWidget(chip)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  mousePressEvent  — clicking blank space blurs any focused      │
    # │  text field for a more native-feeling interaction               │
    # └──────────────────────────────────────────────────────────────────┘
    def mousePressEvent(self, event):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        super().mousePressEvent(event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_add_tag  — parses space-separated tags from the input,     │
    # │  deduplicates against the existing list, adds new ones as chips │
    # │  and immediately saves to disk                                  │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_add_tag(self, text=None):
        if text is None:
            text = self.add_input.text().strip()
        else:
            text = text.strip()
        if not text:
            return

        new_tags = text.split()
        current_tags = self._get_current_tags()

        added = False
        for t in new_tags:
            if t not in current_tags:  # Skip duplicates silently
                self._add_chip_ui(t)
                current_tags.append(t)
                added = True

        if added:
            self.add_input.clear()
            self.save_favorites()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  add_tag  — public API so the rest of the app can programmatic- │
    # │  ally add a tag to the favorites list (e.g. from the tag panel) │
    # └──────────────────────────────────────────────────────────────────┘
    def add_tag(self, tag: str):
        self._on_add_tag(tag)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_tag_removed  — scans the chip list for the matching tag,   │
    # │  deletes that chip widget, then saves after a short delay so    │
    # │  Qt has time to process the widget deletion before we read list │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_tag_removed(self, tag):
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, TagChip) and w.tag == tag:
                w.deleteLater()
                break
        QTimer.singleShot(100, self.save_favorites)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _get_current_tags  — returns the tag list from wherever it     │
    # │  currently lives: the raw text box in bulk mode, or the chip   │
    # │  widgets in visual mode                                         │
    # └──────────────────────────────────────────────────────────────────┘
    def _get_current_tags(self):
        if self._bulk_mode:
            return self.raw_edit.toPlainText().split()
        tags = []
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, TagChip):
                tags.append(w.tag)
        return tags

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _toggle_bulk_mode  — flips between visual chip mode and raw   │
    # │  text edit mode, syncing the data both ways on each toggle      │
    # └──────────────────────────────────────────────────────────────────┘
    def _toggle_bulk_mode(self):
        self._bulk_mode = not self._bulk_mode
        if self._bulk_mode:
            # Serialise all chips to a single space-separated string for editing
            self.raw_edit.setPlainText(" ".join(self._get_current_tags()))
            self.scroll.hide()
            self.raw_edit.show()
            self.bulk_toggle.setText("✨ Switch to Visual Mode")
        else:
            # Parse the edited text back into individual chip widgets
            tags = self.raw_edit.toPlainText().split()
            self._clear_chips()
            for t in tags:
                self._add_chip_ui(t)
            self.raw_edit.hide()
            self.scroll.show()
            self.bulk_toggle.setText("📝 Switch to Raw Text Mode")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _clear_all  — empties both the chips and the raw editor then   │
    # │  saves the empty list to disk                                   │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_all(self):
        self._clear_chips()
        self.raw_edit.clear()
        self.save_favorites()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  save_favorites  — collects the current tags, sanitises them,   │
    # │  writes to settings.manager.favorites and persists to disk, then shows  │
    # │  a brief green confirmation label that fades after 2 seconds    │
    # └──────────────────────────────────────────────────────────────────┘
    def save_favorites(self):
        tags = self._get_current_tags()
        cleaned = " ".join(tags)

        # Sanitise through the validation module if available
        try:
            cleaned = sanitize_tag_list(cleaned)
        except Exception:
            pass

        settings.manager.favorites = cleaned
        settings.manager.save()

        self.status_lbl.setText("✔ Changes saved")
        self.status_lbl.show()

        anims.animate_button_press(self.save_btn)

        # Auto-hide the confirmation after 2 seconds
        QTimer.singleShot(2000, self.status_lbl.hide)
