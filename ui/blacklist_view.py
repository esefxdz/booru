from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QScrollArea,
    QLineEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QCursor

from ui import settings_view as settings
from ui.text_bar import BooruTextBar
# TagChip is shared between BlacklistView and FavoritesView — defined once in tag_chip.py
from ui.tag_chip import TagChip



from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: BlacklistView                                               ║
# ║  Full-page widget for managing the global tag blacklist.           ║
# ║  Tags here are automatically prepended as negatives (-tag) on      ║
# ║  every search so the user never sees them in results.              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class BlacklistView(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — sets up the full-page layout with a left tag-chip  │
    # │  column and a right info/help column, then tracks bulk mode     │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(40, 40, 40, 40)
        self.layout.setSpacing(24)

        # Build the title bar with the Save button
        self._build_header()

        # Split the body into left (tag management) and right (info card)
        content_h = QHBoxLayout()
        content_h.setSpacing(32)
        self.layout.addLayout(content_h, 1)

        # ── Left Column: all the interactive tag controls ──────────────
        left_v = QVBoxLayout()
        left_v.setSpacing(20)
        content_h.addLayout(left_v, 2)

        # Quick-add row: text input + "Add Tag" button side by side
        add_h = QHBoxLayout()
        self.add_input = BooruTextBar(self, placeholder="Add tags to blacklist...")
        # Submitting via Enter key also adds the tag
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

        # Scrollable chip area — one TagChip per blacklisted tag
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

        # Toggle link that switches between visual chip mode and raw text mode
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

        # Raw text editor — hidden initially, shown when bulk mode is active
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

        # ── Right Column: static info card + clear button ──────────────
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
        info_title = QLabel("Why blacklist?")
        info_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: bold; font-size: 16px;")
        info_v.addWidget(info_title)
        info_text = QLabel(
            "Blacklisting tags helps you filter out content you don't want to see.\n\n"
            "• It works across all Boorus\n"
            "• Supports wildcards (*)\n"
            "• Supports metadata (rating:q)\n"
            "• Use spaces to separate tags"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px; line-height: 1.4;")
        info_v.addWidget(info_text)
        info_v.addStretch()
        right_v.addWidget(info_card)

        # Danger-style clear button with red border that fills red on hover
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

        # Status label that shows "✔ Changes saved" briefly after saving
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
        self.layout.addWidget(self.status_lbl)
        self.layout.addWidget(QLabel(""))  # Small spacer at the bottom

        # Tracks whether we are in raw text edit mode (True) or chip mode (False)
        self._bulk_mode = False

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _build_header  — creates the big title + subtitle row and the  │
    # │  "Save Changes" button in the top-right corner                  │
    # └──────────────────────────────────────────────────────────────────┘
    def _build_header(self):
        header = QHBoxLayout()
        title_v = QVBoxLayout()
        title = QLabel("Your Blacklist")
        title.setStyleSheet(f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};")
        title_v.addWidget(title)
        subtitle = QLabel("Global filter system. Tags here are automatically excluded from all searches.")
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
        self.save_btn.clicked.connect(self.save_blacklist)
        header.addWidget(self.save_btn)
        self.layout.addLayout(header)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_blacklist  — called every time this page becomes visible  │
    # │  Reads from settings and repopulates chips + raw text editor    │
    # └──────────────────────────────────────────────────────────────────┘
    def load_blacklist(self):
        # Hide any stale "saved" message from a previous visit
        self.status_lbl.hide()
        tags = settings.manager.blacklist.split()
        self._clear_chips()
        for tag in tags:
            self._add_chip_ui(tag)
        # Keep the raw editor in sync too (even if it's currently hidden)
        self.raw_edit.setPlainText(settings.manager.blacklist)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _clear_chips  — removes every TagChip widget from the scroll   │
    # │  area and schedules them for deletion to free memory            │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_chips(self):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _add_chip_ui  — creates one TagChip and connects its removed   │
    # │  signal so clicking ✕ automatically updates the list            │
    # └──────────────────────────────────────────────────────────────────┘
    def _add_chip_ui(self, tag):
        chip = TagChip(tag)
        chip.removed.connect(self._on_tag_removed)
        self.chip_layout.addWidget(chip)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  mousePressEvent  — clicking blank space clears the text input  │
    # │  focus, making the UX feel more native                          │
    # └──────────────────────────────────────────────────────────────────┘
    def mousePressEvent(self, event):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        super().mousePressEvent(event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_add_tag  — adds one or more space-separated tags from the  │
    # │  input box, skipping duplicates, then auto-saves                │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_add_tag(self, text=None):
        # `text` is passed in when the BooruTextBar emits `submitted`
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
            if t not in current_tags:  # Skip tags already in the list
                self._add_chip_ui(t)
                current_tags.append(t)
                added = True

        if added:
            self.add_input.clear()
            self.save_blacklist()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  add_tag  — public helper so other parts of the app can push a  │
    # │  tag into the blacklist programmatically                        │
    # └──────────────────────────────────────────────────────────────────┘
    def add_tag(self, tag: str):
        self._on_add_tag(tag)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_tag_removed  — walks the chip list to find the matching    │
    # │  TagChip by its tag string, removes it, then saves after a     │
    # │  short delay (so the UI deletes the widget before saving)       │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_tag_removed(self, tag):
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, TagChip) and w.tag == tag:
                w.deleteLater()
                break
        # 100ms delay lets Qt process the deleteLater before we read the list again
        QTimer.singleShot(100, self.save_blacklist)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _get_current_tags  — returns the current tag list depending on │
    # │  which mode is active: reads chips in visual mode, or splits    │
    # │  the raw text box in bulk mode                                  │
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
    # │  _toggle_bulk_mode  — switches between visual chip mode and raw │
    # │  text mode. On entering bulk mode, serialises chips into the    │
    # │  text box. On leaving, parses the text back into chips.         │
    # └──────────────────────────────────────────────────────────────────┘
    def _toggle_bulk_mode(self):
        self._bulk_mode = not self._bulk_mode
        if self._bulk_mode:
            # Dump all chip tags into the raw text box as a space-separated string
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
    # │  _clear_all  — wipes chips and the raw editor, then saves the  │
    # │  now-empty blacklist to disk immediately                        │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_all(self):
        self._clear_chips()
        self.raw_edit.clear()
        self.save_blacklist()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  save_blacklist  — collects the current tag list, optionally    │
    # │  sanitises it via the validation module, writes it to           │
    # │  settings.manager.blacklist, persists to disk, and shows a brief       │
    # │  green "✔ Changes saved" confirmation label                     │
    # └──────────────────────────────────────────────────────────────────┘
    def save_blacklist(self):
        tags = self._get_current_tags()
        cleaned = " ".join(tags)

        # Run through the security sanitiser to strip any injected characters
        try:
            from validation import sanitize_tag_list
            cleaned = sanitize_tag_list(cleaned)
        except Exception:
            pass  # If validation module isn't available, use the raw list

        settings.manager.blacklist = cleaned
        settings.manager.save()

        # Show the confirmation label and animate the save button
        self.status_lbl.setText("✔ Changes saved")
        self.status_lbl.show()

        import ui.animations as anims
        anims.animate_button_press(self.save_btn)

        # Auto-hide the confirmation after 2 seconds so it doesn't linger
        QTimer.singleShot(2000, self.status_lbl.hide)
