from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QPushButton, QMenu
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QCursor
from ui import settings_view as settings
import boorus
from ui.icons import Icons
from ui.server_bar.draggable_booru_button import DraggableBooruButton

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: ServerBar                            ║
# ║  The left-most vertical sidebar (Discord style). Manages the list   ║
# ║  of booru site icons, bookmark/home buttons, and reordering logic.  ║
# ╚══════════════════════════════════════════════════════════════════════╝
from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: ServerBar                            ║
# ║  The left-most vertical sidebar (Discord style). Manages the list   ║
# ║  of booru site icons, bookmark/home buttons, and reordering logic.  ║
# ╚══════════════════════════════════════════════════════════════════════╗
class ServerBar(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — sets up the vertical layout and background cache    │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, main_gui):
        super().__init__()
        self.main_gui = main_gui
        self.setFixedWidth(72)
        self.setStyleSheet(f"background-color: {colors.MAIN_BG};")
        self.icon_cache = {}  # booru_name -> local path to favicon
        self.fetchers = {}    # Keeps track of running FaviconFetcher threads
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 12, 0, 12)
        self.layout.setSpacing(8)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        
        self.rebuild_list()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  rebuild_list  — clears all buttons and redraws them based on    │
    # │  BOORU_ORDER and the Booru Registry. Adds the special Bookmark   │
    # │  and Add Booru buttons at the top/bottom respectively.          │
    # └──────────────────────────────────────────────────────────────────┘
    def rebuild_list(self):
        # Clear existing buttons (properly delete widgets to avoid memory leaks)
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── BOOKMARKS BUTTON (Pinned to top) ──────────────────────────
        self.bookmark_btn = QPushButton()
        self.bookmark_btn.setFixedSize(48, 48)
        self.bookmark_btn.setIcon(Icons.get("bookmarks", colors.TEXT_PRIMARY))
        self.bookmark_btn.setIconSize(QSize(24, 24))
        self.bookmark_btn.setToolTip("Global Bookmarks")
        self.bookmark_btn.clicked.connect(self.main_gui.toggle_bookmarks_mode)
        self.update_bookmark_style()
        self.layout.addWidget(self.bookmark_btn)

        # Subtle separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedWidth(32)
        sep.setStyleSheet(f"background-color: {colors.BUTTON_HOVER}; border: none; min-height: 2px;")
        self.layout.addWidget(sep)

        # ── BOORU SITE BUTTONS ─────────────────────────────────────────
        # Show every registered booru; booru_order is only an ordering overlay
        for name in self.effective_order():
            btn = DraggableBooruButton(name, boorus.REGISTRY[name], self)
            self.layout.addWidget(btn)

        # ── ADD BOORU BUTTON (Pinned to bottom) ───────────────────────
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
        # Modals package handles the Add Booru dialog
        from ui.modals import AddBooruDialog
        self.add_btn.clicked.connect(lambda: AddBooruDialog.show_dialog(self.main_gui))
        self.layout.addStretch()
        self.layout.addWidget(self.add_btn)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  effective_order  — full display order for the server bar.       │
    # │  All registered boorus appear; booru_order positions the ones    │
    # │  the user has explicitly reordered, with the rest following in   │
    # │  registry order. This is the single source of truth for both    │
    # │  rendering and drag-reordering.                                  │
    # └──────────────────────────────────────────────────────────────────┘
    def effective_order(self):
        order = [n for n in settings.manager.booru_order if n in boorus.REGISTRY]
        order += [n for n in boorus.REGISTRY if n not in order]
        return order

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_button_styles  — compatibility alias for BooruGui        │
    # └──────────────────────────────────────────────────────────────────┘
    def update_button_styles(self):
        self.update_active()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_active  — called when the user switches boorus. Loops    │
    # │  over all buttons to refresh their highlight borders/shapes.    │
    # └──────────────────────────────────────────────────────────────────┘
    def update_active(self):
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            if isinstance(w, DraggableBooruButton):
                w.update_style()
        self.update_bookmark_style()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_bookmark_style  — specific styling for the Home/Book-   │
    # │  marks button. Turns accent color when bookmarks mode is active. │
    # └──────────────────────────────────────────────────────────────────┘
    def update_bookmark_style(self):
        if not hasattr(self, 'bookmark_btn'): return
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

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_icon_ready  — callback for FaviconFetcher threads. Stores  │
    # │  the path and forces a style update on the button so the site   │
    # │  favicon appears immediately once downloaded.                   │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_icon_ready(self, name, path):
        self.icon_cache[name] = path
        self.update_active()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_context_menu  — right-click menu for booru icons. Allows   │
    # │  quick access to credentials/engine settings for that site.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_context_menu(self, name):
        menu = QMenu(self)
        # Discord-style dark menu styling
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {colors.MODAL_BG}; color: {colors.TEXT_SECONDARY}; border: 1px solid {colors.BORDER}; padding: 4px; }}
            QMenu::item {{ padding: 6px 24px; border-radius: 2px; }}
            QMenu::item:selected {{ background-color: {colors.ACCENT}; color: {colors.TEXT_PRIMARY}; }}
        """)
        
        act = QAction(f"⚙ Settings for {name}", self)
        from ui.modals import APISettingsDialog
        act.triggered.connect(lambda: APISettingsDialog.show_dialog(self.main_gui, name))
        menu.addAction(act)
        
        menu.exec(QCursor.pos())
