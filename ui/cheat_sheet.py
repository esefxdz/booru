"""
ui/cheat_sheet.py

Full-page widget for the Cheat Sheet (Keyboard Shortcuts & Booru Search syntax).
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QFrame, QScrollArea, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt
from ui import colors

class CheatSheetView(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(24)

        # Header
        header = QVBoxLayout()
        title = QLabel("Cheat Sheet")
        title.setStyleSheet(f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};")
        header.addWidget(title)

        subtitle = QLabel("Keyboard shortcuts and search syntax reference.")
        subtitle.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_MUTED};")
        header.addWidget(subtitle)
        root.addLayout(header)

        # Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(32)

        # Shortcuts Section
        content.addWidget(self._build_shortcuts_section())

        # Search Syntax Section
        content.addWidget(self._build_search_syntax_section())

        content.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    def _build_shortcuts_section(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("⌨️ Keyboard Shortcuts")
        title.setStyleSheet(f"color: {colors.ACCENT}; font-size: 18px; font-weight: 800;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setVerticalSpacing(16)
        grid.setHorizontalSpacing(16)
        grid.setColumnStretch(1, 1)

        shortcuts = [
            ("Ctrl+F", "Focus search bar"),
            ("Left / Right Arrow", "Navigate to previous/next page in gallery"),
            ("A / D", "Navigate to previous/next image in overlay viewer"),
            ("Esc", "Close the image overlay viewer"),
            ("Ctrl+S", "Open the Bulk Download dialog")
        ]

        for i, (keys, desc) in enumerate(shortcuts):
            k_lbl = QLabel(keys)
            k_lbl.setStyleSheet(f"""
                background: {colors.BUTTON_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 4px 8px;
                font-family: Consolas, monospace;
                font-weight: bold;
            """)
            k_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 14px;")
            d_lbl.setWordWrap(True)

            grid.addWidget(k_lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(d_lbl, i, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addLayout(grid)
        return card

    def _build_search_syntax_section(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("🔍 Booru Search Syntax")
        title.setStyleSheet(f"color: {colors.ACCENT}; font-size: 18px; font-weight: 800;")
        layout.addWidget(title)
        
        info = QLabel("Note: Combinations of the same metatag (with colons) often don't work, but you can combine different metatags (e.g., rating:questionable parent:100).")
        info.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px; font-style: italic;")
        info.setWordWrap(True)
        layout.addWidget(info)

        syntax_items = [
            ("tag1 tag2", "Search for posts that have tag1 and tag2."),
            ("( tag1 ~ tag2 )", "Search for posts that have tag1 or tag2. The spaces around the braces are required."),
            ("night~", "Fuzzy search for the tag night. Will return similar words (e.g. fight, bright)."),
            ("-tag1", "Search for posts that DON'T have tag1."),
            ("ta*1", "Wildcard search: tags starting with 'ta' and ending with '1'."),
            ("user:bob", "Search for posts uploaded by the user Bob."),
            ("md5:foo", "Search for posts with the exact MD5 hash foo."),
            ("md5:foo*", "Search for posts whose MD5 hash starts with foo."),
            ("rating:questionable", "Search for posts rated questionable (or safe, explicit)."),
            ("-rating:questionable", "Search for posts NOT rated questionable."),
            ("parent:1234", "Search for posts that have 1234 as a parent (includes post 1234)."),
            ("width:>=1000 height:>1000", "Find images with width >= 1000 and height > 1000."),
            ("score:>=10", "Find images with a score >= 10."),
            ("sort:updated:desc", "Sort posts by last updated, descending. Other sort properties: id, score, rating, user, height, width, parent, source.")
        ]

        grid = QGridLayout()
        grid.setVerticalSpacing(16)
        grid.setHorizontalSpacing(16)
        grid.setColumnStretch(1, 1)

        for i, (syntax, desc) in enumerate(syntax_items):
            s_lbl = QLabel(syntax)
            s_lbl.setStyleSheet(f"""
                color: {colors.SUCCESS};
                font-family: Consolas, monospace;
                font-weight: bold;
                font-size: 13px;
                background: {colors.INPUT_BG};
                padding: 4px;
                border-radius: 4px;
            """)
            s_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 14px;")
            d_lbl.setWordWrap(True)

            grid.addWidget(s_lbl, i, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(d_lbl, i, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        layout.addLayout(grid)
        return card
