from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt, QSize, QMimeData
from PyQt6.QtGui import QCursor, QDrag, QIcon
from ui import settings_view as settings
from ui.icons import Icons
from ui.server_bar.favicon_fetcher import FaviconFetcher

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                   CLASS: DraggableBooruButton                       ║
# ║  A QPushButton that also acts as a drag source and drop target,     ║
# ║  letting the user reorder boorus by dragging them in the sidebar.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                   CLASS: DraggableBooruButton                       ║
# ║  A QPushButton that also acts as a drag source and drop target,     ║
# ║  letting the user reorder boorus by dragging them in the sidebar.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class DraggableBooruButton(QPushButton):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — creates the button and enables drag-and-drop       │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, booru_name, data, server_bar):
        super().__init__()
        self.booru_name = booru_name
        self.data = data
        self.server_bar = server_bar
        self.setFixedSize(48, 48)
        self.setIconSize(QSize(28, 28))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(data.get('url', booru_name))  # Shows the URL on hover
        
        self.update_style()  # Apply the correct active/inactive look immediately
        
        # Right-click opens a context menu (API settings, delete, etc.)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.server_bar._on_context_menu(self.booru_name)
        )
        self.clicked.connect(self._on_clicked)
        
        # Accept drops so other booru buttons can be reordered onto this one
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_clicked  — plays a quick press animation and switches the  │
    # │  active booru to this one in the main window                    │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_clicked(self):
        import ui.animations as anims
        anims.animate_button_press(self)
        self.server_bar.main_gui.select_booru(self.booru_name)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_style  — refreshes the button's icon and border color   │
    # │  Called whenever the active booru changes or icons load.        │
    # │  Active booru gets a solid square; others get a rounded          │
    # │  ghost style that morphs on hover (Discord-style).               │
    # └──────────────────────────────────────────────────────────────────┘
    def update_style(self):
        # If the favicon was already downloaded, use it instead of the generic box icon
        cached_icon = self.server_bar.icon_cache.get(self.booru_name)
        if cached_icon:
            self.setIcon(QIcon(cached_icon))
        else:
            # Use a bright primary text color for the active booru so it stands out
            if self.booru_name == settings.manager.active_booru:
                self.setIcon(Icons.get("box", colors.TEXT_PRIMARY))
            else:
                self.setIcon(Icons.get("box", colors.TEXT_SECONDARY))
            
            # Kick off background favicon download if we haven't tried yet
            if self.booru_name not in self.server_bar.fetchers and self.data.get("url"):
                fetcher = FaviconFetcher(self.booru_name, self.data["url"])
                fetcher.finished.connect(self.server_bar._on_icon_ready)
                self.server_bar.fetchers[self.booru_name] = fetcher
                fetcher.start()

        # In bookmarks mode, nothing is visually "active" (it's a virtual feed)
        is_active = (
            self.booru_name == settings.manager.active_booru
            and not self.server_bar.main_gui.is_bookmarks_mode
        )

        # ── CF bypass status indicator ────────────────────────────
        from cloudflare_bypasser import store as cf_store
        cf_ok = cf_store.has_active_bypass(self.booru_name)
        cf_color = colors.SUCCESS if cf_ok else colors.WARNING
        cf_border = f"border-bottom: 3px solid {cf_color};" if not is_active else ""

        if is_active:
            # Solid square with tight radius = selected/active look
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                    {cf_border}
                }}
            """)
        else:
            # Fully rounded by default, squarifies on hover — matches Discord behavior
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.MAIN_BG};
                    border-radius: 24px;
                    {cf_border}
                }}
                QPushButton:hover {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                }}
            """)
        self.setToolTip(
            f"{self.booru_name}\n"
            f"{'✓ Cloudflare bypass active' if cf_ok else '⚠ Cloudflare bypass needed — right-click to solve CAPTCHA'}"
        )

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  mousePressEvent  — records where the drag started so we can    │
    # │  detect if the user is actually dragging vs just clicking        │
    # └──────────────────────────────────────────────────────────────────┘
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  mouseMoveEvent  — starts a drag operation once the mouse moves  │
    # │  far enough from where it was pressed (10px threshold)           │
    # └──────────────────────────────────────────────────────────────────┘
    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_start_pos') and (event.pos() - self.drag_start_pos).manhattanLength() > 10:
            # Encode this button's booru name as the drag payload
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(self.booru_name)
            drag.setMimeData(mime_data)
            drag.exec(Qt.DropAction.MoveAction)
            return  # Don't call super() — it would interfere with the drag
        super().mouseMoveEvent(event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  dragEnterEvent  — accepts the drag so we can receive the drop  │
    # └──────────────────────────────────────────────────────────────────┘
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  dropEvent  — reorders the booru list when another button is    │
    # │  dropped here. Moves the dragged booru to just before this one   │
    # │  in BOORU_ORDER, then rebuilds the sidebar list to reflect it.  │
    # └──────────────────────────────────────────────────────────────────┘
    def dropEvent(self, event):
        source_booru = event.mimeData().text()
        target_booru = self.booru_name
        
        if source_booru != target_booru:
            if source_booru in settings.manager.booru_order and target_booru in settings.manager.booru_order:
                # Make a clean copy of the list to mutate safely
                order = settings.manager.booru_order[:]
                order.remove(source_booru)
                # Insert the dragged booru immediately before the drop target
                target_index = order.index(target_booru)
                order.insert(target_index, source_booru)
                settings.manager.booru_order = order
                settings.manager.save()
                self.server_bar.rebuild_list()
        
        event.acceptProposedAction()
