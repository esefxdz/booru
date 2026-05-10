"""
displayers/comments.py — Sidebar comments section.

Fetches and displays comments for the currently viewed post.
Uses the CF bypass session so it works on Cloudflare-protected sites.
"""
import threading
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal

from ui import colors
from ui import settings_view as settings


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: CommentsSection                                             ║
# ║  A scrollable area that fetches comments from the booru API in a   ║
# ║  background thread and renders them as styled blocks.              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class CommentsSection(QWidget):
    # Signal emitted when background thread finishes fetching
    comments_ready = pyqtSignal(list)
    
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — sets up the scroll area and connects the signal.   │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, sidebar):
        super().__init__()
        self.sidebar = sidebar
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        
        title = QLabel("Comments")
        title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: bold; font-size: 14px;")
        self._main_layout.addWidget(title)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 10, 0, 0)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll.setWidget(self.content)
        self._main_layout.addWidget(self.scroll)
        
        self.comments_ready.connect(self._render_comments)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — clears old comments, shows 'Loading...', and      │
    # │  spawns a thread to hit the API using cloudflare_bypasser.        │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        lbl = QLabel("Loading comments...")
        lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")
        self.content_layout.addWidget(lbl)
        
        post_id = post.get('id')
        booru_name = post.get('_booru', settings.manager.active_booru)
        
        def fetch():
            try:
                import boorus
                from cloudflare_bypasser import get_session

                site_data = boorus.REGISTRY.get(booru_name, {})
                api_type = site_data.get('api_type', 'danbooru')
                url = site_data.get('url', '').rstrip('/')

                comments = []
                headers = {"User-Agent": "Mozilla/5.0"}
                if url:
                    headers["Referer"] = url

                session = get_session(booru_name)
                
                if api_type == 'danbooru' and url:
                    res = session.get_sync(f"{url}/comments.json?search[post_id]={post_id}", headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        for c in data:
                            comments.append({
                                "creator": c.get("creator_name", "Anonymous"),
                                "body": c.get("body", "")
                            })
                elif api_type == 'gelbooru' and url:
                    res = session.get_sync(f"{url}/index.php?page=dapi&s=comment&q=index&post_id={post_id}&json=1", headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, dict) and "comment" in data:
                            for c in data["comment"]:
                                comments.append({
                                    "creator": c.get("creator", "Anonymous"),
                                    "body": c.get("body", "")
                                })
                
                self.comments_ready.emit(comments)
            except Exception as e:
                print(f"[comments] Fetch error: {e}")
                self.comments_ready.emit([])
                
        threading.Thread(target=fetch, daemon=True).start()
        
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _render_comments  — slot (GUI thread) triggered when the API   │
    # │  call finishes. Renders blocks or a "No comments" message.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _render_comments(self, comments):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): 
                item.widget().deleteLater()
            
        if not comments:
            lbl = QLabel("No comments found.")
            lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")
            self.content_layout.addWidget(lbl)
            return
            
        for c in comments:
            c_widget = QWidget()
            c_layout = QVBoxLayout(c_widget)
            c_layout.setContentsMargins(10, 10, 10, 10)
            c_widget.setStyleSheet(f"background-color: {colors.INPUT_BG}; border-radius: 6px;")
            
            creator = QLabel(c.get('creator', 'Anonymous'))
            creator.setStyleSheet(f"color: {colors.ACCENT}; font-weight: bold;")
            c_layout.addWidget(creator)
            
            body = QLabel(c.get('body', ''))
            body.setWordWrap(True)
            body.setStyleSheet(f"color: {colors.TEXT_PRIMARY};")
            c_layout.addWidget(body)
            
            self.content_layout.addWidget(c_widget)
