from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QScrollArea,
    QLineEdit
)
from PyQt6.QtCore import Qt, QTimer

from core import settings
from ui.widgets.text_bar import BooruTextBar
from ui.widgets.tag_chip import TagChip


from core.validation import sanitize_tag_list
import ui.animations as anims
from ui.style import colors

class BlacklistView(QWidget):

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(40, 40, 40, 40)
        self._main_layout.setSpacing(24)

        self._build_header()

        content_h = QHBoxLayout()
        content_h.setContentsMargins(0, 0, 0, 0)
        content_h.setSpacing(32)
        self._main_layout.addLayout(content_h, 1)

        left_v = QVBoxLayout()
        left_v.setSpacing(20)
        content_h.addLayout(left_v, 2)

        add_h = QHBoxLayout()
        self.add_input = BooruTextBar(self, placeholder="Add tags to blacklist...")
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

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
        self._main_layout.addWidget(self.status_lbl)
        self._main_layout.addWidget(QLabel(""))

        self._bulk_mode = False

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
        self._main_layout.addLayout(header)

    def load_blacklist(self):
        self.status_lbl.hide()
        tags = settings.manager.blacklist.split()
        self._clear_chips()
        for tag in tags:
            self._add_chip_ui(tag)
        self.raw_edit.setPlainText(settings.manager.blacklist)

    def _clear_chips(self):
        while self.chip_layout.count():
            item = self.chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_chip_ui(self, tag):
        chip = TagChip(tag)
        chip.removed.connect(self._on_tag_removed)
        self.chip_layout.addWidget(chip)

    def mousePressEvent(self, event):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        super().mousePressEvent(event)

    def _on_add_tag(self, text=None):
        # `text` is a str when the text bar emits `submitted`, but a bool
        # when the Add button is clicked.  Only use `text` if it's a string.
        if not isinstance(text, str):
            text = self.add_input.text().strip()
        else:
            text = text.strip()
        if not text:
            return

        new_tags = text.split()
        current_tags = self._get_current_tags()

        added = False
        for t in new_tags:
            if t not in current_tags:
                self._add_chip_ui(t)
                current_tags.append(t)
                added = True

        if added:
            self.add_input.clear()
            self.save_blacklist()

    def add_tag(self, tag: str):
        self._on_add_tag(tag)

    def _on_tag_removed(self, tag):
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, TagChip) and w.tag == tag:
                w.deleteLater()
                break
        # 100ms delay lets Qt process the deleteLater before we read the list again
        QTimer.singleShot(100, self.save_blacklist)

    def _get_current_tags(self):
        if self._bulk_mode:
            return self.raw_edit.toPlainText().split()
        tags = []
        for i in range(self.chip_layout.count()):
            w = self.chip_layout.itemAt(i).widget()
            if isinstance(w, TagChip):
                tags.append(w.tag)
        return tags

    def _toggle_bulk_mode(self):
        self._bulk_mode = not self._bulk_mode
        if self._bulk_mode:
            self.raw_edit.setPlainText(" ".join(self._get_current_tags()))
            self.scroll.hide()
            self.raw_edit.show()
            self.bulk_toggle.setText("✨ Switch to Visual Mode")
        else:
            tags = self.raw_edit.toPlainText().split()
            self._clear_chips()
            for t in tags:
                self._add_chip_ui(t)
            self.raw_edit.hide()
            self.scroll.show()
            self.bulk_toggle.setText("📝 Switch to Raw Text Mode")

    def _clear_all(self):
        self._clear_chips()
        self.raw_edit.clear()
        self.save_blacklist()

    def save_blacklist(self):
        tags = self._get_current_tags()
        cleaned = " ".join(tags)

        # Run through the security sanitiser to strip any injected characters
        try:
            cleaned = sanitize_tag_list(cleaned)
        except Exception:
            pass  # If validation module isn't available, use the raw list

        settings.manager.blacklist = cleaned
        settings.manager.save()

        self.status_lbl.setText("✔ Changes saved")
        self.status_lbl.show()
        anims.animate_button_press(self.save_btn)

        QTimer.singleShot(2000, self.status_lbl.hide)
