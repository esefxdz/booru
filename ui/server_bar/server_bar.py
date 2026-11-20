from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMenu
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QCursor
from core import settings
import boorus
from ui.style.icons import Icons
from ui.server_bar.booru_button import BooruButton
from ui.modals import AddBooruDialog

from ui.style import colors

class ServerBar(QWidget):

    def __init__(self, main_gui):
        super().__init__()
        self.main_gui = main_gui
        self.setFixedWidth(72)
        self.setStyleSheet(f"background-color: {colors.MAIN_BG};")
        self.icon_cache = {}
        self.fetchers = {}
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 12, 0, 12)
        self._main_layout.setSpacing(8)
        self._main_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        
        self.rebuild_list()

    def rebuild_list(self):
        while self._main_layout.count():
            item = self._main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.bookmark_btn = QPushButton()
        self.bookmark_btn.setFixedSize(48, 48)
        self.bookmark_btn.setIcon(Icons.get("bookmarks", colors.TEXT_PRIMARY))
        self.bookmark_btn.setIconSize(QSize(24, 24))
        self.bookmark_btn.setToolTip("Global Bookmarks")
        self.bookmark_btn.clicked.connect(self.main_gui.toggle_bookmarks_mode)
        self.update_bookmark_style()
        self._main_layout.addWidget(self.bookmark_btn)


        # Render the user's curated list. boorus.REGISTRY is just the catalog
        # of supported sites; only boorus the user has added (booru_order) show.
        for name in settings.manager.booru_order:
            if name in boorus.REGISTRY:
                btn = BooruButton(name, boorus.REGISTRY[name], self)
                self._main_layout.addWidget(btn)

        self.add_btn = QPushButton()
        self.add_btn.setFixedSize(48, 48)
        self.add_btn.setIcon(Icons.get("plus", colors.SUCCESS))
        self.add_btn.setIconSize(QSize(24, 24))
        self.add_btn.setToolTip("Add Custom Booru")
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.MAIN_BG};
                border-radius: 24px;
            }}
            QPushButton:hover {{
                background-color: {colors.SUCCESS};
                border-radius: 16px;
                icon: none; /* swaps to white icon via code on hover if we wanted */
            }}
        """)
        self.add_btn.clicked.connect(lambda: AddBooruDialog.show_dialog(self.main_gui))
        self._main_layout.addStretch()
        self._main_layout.addWidget(self.add_btn)

    def update_button_styles(self):
        self.update_active()

    def update_active(self):
        for i in range(self._main_layout.count()):
            w = self._main_layout.itemAt(i).widget()
            if isinstance(w, BooruButton):
                w.update_style()
        self.update_bookmark_style()

    def update_bookmark_style(self):
        if not hasattr(self, 'bookmark_btn'):
            return
        if self.main_gui.is_bookmarks_mode:
            self.bookmark_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                }}
            """)
        else:
            self.bookmark_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.MAIN_BG};
                    border-radius: 24px;
                }}
                QPushButton:hover {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                }}
            """)

    def _on_icon_ready(self, name, path):
        self.icon_cache[name] = path
        self.fetchers.pop(name, None)
        self.update_active()

    def _on_context_menu(self, name):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {colors.MODAL_BG}; color: {colors.TEXT_SECONDARY}; border: 1px solid {colors.BORDER}; padding: 4px; }}
            QMenu::item {{ padding: 6px 24px; border-radius: 2px; }}
            QMenu::item:selected {{ background-color: {colors.ACCENT}; color: {colors.TEXT_PRIMARY}; }}
        """)
        
        act = menu.addAction(f"⚙ Settings for {name}")
        act.triggered.connect(lambda: self.main_gui.show_api_settings(name))
        
        menu.exec(QCursor.pos())
