"""
displayers/comments.py -- Sidebar comments section.

Fetches and renders post comments from any supported booru API.
Uses the cloudflare_bypasser session so it works on protected sites.

Supported engines and their comment API patterns:
  - Danbooru:   GET /comments.json?search[post_id]=<id>
  - Gelbooru:   GET /index.php?page=dapi&s=comment&q=index&post_id=<id>&json=1
  - Moebooru:   GET /comment.json?post_id=<id>
  - e621:       GET /comments.json?search[post_id]=<id>  (same as Danbooru)
  - Philomena:  GET /api/v1/json/images/<id>/comments
"""
from __future__ import annotations
import logging

import re
import html
import asyncio
import traceback
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame,
)

from displayers.details import CollapsibleWidget
from ui import colors
from ui import settings_view as settings


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: _FetchThread                                                ║
# ║  Runs the comment API request in a background QThread using        ║
# ║  asyncio.run() — exactly the same pattern as FetchThread in        ║
# ║  controller.py.  This avoids event loop conflicts with Qt.         ║
# ╚══════════════════════════════════════════════════════════════════════╝
class _FetchThread(QThread):
    done = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, post_id, booru_name: str):
        super().__init__()
        self._post_id = post_id
        self._booru_name = booru_name

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  run  — creates a fresh event loop (no conflicts with Qt's      │
    # │  loop), builds a bypass session, and dispatches to the correct  │
    # │  engine-specific fetcher based on api_type.                     │
    # └──────────────────────────────────────────────────────────────────┘
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            comments = loop.run_until_complete(self._fetch())
            self.done.emit(comments)
        except Exception as e:
            logging.exception("Exception traceback")
            self.error.emit(str(e))
        finally:
            loop.close()

    async def _fetch(self) -> list[dict]:
        import boorus
        from cloudflare_bypasser import get_session

        site_data = boorus.REGISTRY.get(self._booru_name, {})
        api_type = site_data.get("api_type", "gelbooru")
        base_url = site_data.get("url", "").rstrip("/")

        if not base_url:
            return []

        session = get_session(self._booru_name)

        # ── Dispatch table ────────────────────────────────────────
        dispatch = {
            "danbooru":   self._danbooru,
            "gelbooru":   self._gelbooru,
            "moebooru":   self._moebooru,
            "e621":       self._e621,
            "philomena":  self._philomena,
        }

        handler = dispatch.get(api_type)
        if handler is None:
            logging.info(f"[comments] No comment handler for api_type={api_type}")
            return []

        return await handler(session, base_url, self._post_id)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  Engine-specific fetchers.  Each returns a list of dicts:       │
    # │    {"author": str, "body": str, "date": str}                   │
    # │  Uses session.get() (async) directly — the same codepath the   │
    # │  downloader and image fetcher use.                              │
    # └──────────────────────────────────────────────────────────────────┘

    async def _danbooru(self, session, url, post_id) -> list[dict]:
        """Danbooru / Safebooru (donmai): /comments.json?search[post_id]=X"""
        creds = settings.manager.get_credential(self._booru_name) or {}
        params = {"search[post_id]": str(post_id), "limit": "50"}
        if creds.get("user_id") and creds.get("api_key"):
            params["login"] = creds["user_id"]
            params["api_key"] = creds["api_key"]
            
        r = await session.get(
            f"{url}/comments.json",
            params=params,
        )
        if r.status_code == 401 and "api_key" in params:
            logging.info("[comments] Danbooru returned 401 with creds, retrying without...")
            params.pop("login", None)
            params.pop("api_key", None)
            r = await session.get(f"{url}/comments.json", params=params)

        if r.status_code != 200:
            logging.info(f"[comments] Danbooru returned {r.status_code}")
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "author": c.get("creator_name", "Anonymous"),
                "body":   _clean(c.get("body", "")),
                "date":   _fmt_date(c.get("created_at", "")),
            }
            for c in data if c.get("body", "").strip()
        ]

    async def _gelbooru(self, session, url, post_id) -> list[dict]:
        """Gelbooru / Rule34 / Safebooru.org / xBooru: DAPI comment endpoint.

        Response format varies:
          - Gelbooru.com: {"comment": [...]}
          - Rule34.xxx:   bare list [...]
          - Some sites:   XML (json=1 ignored)
        """
        creds = settings.manager.get_credential(self._booru_name) or {}
        params = {
            "page": "dapi", "s": "comment", "q": "index",
            "post_id": str(post_id), "json": "1",
        }
        if creds.get("user_id") and creds.get("api_key"):
            params["user_id"] = creds["user_id"]
            params["api_key"] = creds["api_key"]
            
        r = await session.get(
            f"{url}/index.php",
            params=params,
        )
        if r.status_code == 401 and "api_key" in params:
            logging.info("[comments] Gelbooru returned 401 with creds, retrying without...")
            params.pop("user_id", None)
            params.pop("api_key", None)
            r = await session.get(f"{url}/index.php", params=params)

        if r.status_code != 200:
            logging.info(f"[comments] Gelbooru returned {r.status_code}")
            return []

        # Try JSON first
        try:
            data = r.json()
        except Exception:
            # Fallback: XML
            return _parse_xml(r.text)

        raw_list = []
        if isinstance(data, dict):
            # Gelbooru wraps comments: {"comment": [...]}
            raw_list = data.get("comment", [])
            if not isinstance(raw_list, list):
                raw_list = []
        elif isinstance(data, list):
            # Rule34.xxx returns a bare list
            raw_list = data

        return [
            {
                "author": c.get("creator", c.get("owner", "Anonymous")),
                "body":   _clean(c.get("body", c.get("comment", ""))),
                "date":   _fmt_date(c.get("created_at", "")),
            }
            for c in raw_list
            if isinstance(c, dict) and (c.get("body") or c.get("comment", "")).strip()
        ]

    async def _moebooru(self, session, url, post_id) -> list[dict]:
        """Moebooru (yande.re, konachan): /comment.json?post_id=X"""
        r = await session.get(
            f"{url}/comment.json",
            params={"post_id": str(post_id)},
        )
        if r.status_code != 200:
            logging.info(f"[comments] Moebooru returned {r.status_code}")
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "author": c.get("creator", "Anonymous"),
                "body":   _clean(c.get("body", "")),
                "date":   _fmt_date(c.get("created_at", "")),
            }
            for c in data if c.get("body", "").strip()
        ]

    async def _e621(self, session, url, post_id) -> list[dict]:
        """e621 / e926: /comments.json?search[post_id]=X (Danbooru fork)."""
        r = await session.get(
            f"{url}/comments.json",
            params={"search[post_id]": str(post_id), "limit": "50"},
        )
        if r.status_code != 200:
            logging.info(f"[comments] e621 returned {r.status_code}")
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "author": c.get("creator_name", "Anonymous"),
                "body":   _clean(c.get("body", "")),
                "date":   _fmt_date(c.get("created_at", "")),
            }
            for c in data if c.get("body", "").strip()
        ]

    async def _philomena(self, session, url, post_id) -> list[dict]:
        """Philomena (Derpibooru, Ponerpics): /api/v1/json/images/<id>/comments"""
        r = await session.get(
            f"{url}/api/v1/json/images/{post_id}/comments",
        )
        if r.status_code != 200:
            logging.info(f"[comments] Philomena returned {r.status_code}")
            return []
        data = r.json()
        cl = data.get("comments", []) if isinstance(data, dict) else []
        return [
            {
                "author": c.get("author", "Anonymous"),
                "body":   _clean(c.get("body", "")),
                "date":   _fmt_date(c.get("created_at", "")),
            }
            for c in cl if c.get("body", "").strip()
        ]


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: CommentsSection                                             ║
# ║  Collapsible sidebar panel.  On load_post() it spawns a            ║
# ║  _FetchThread, then renders results as styled comment cards.       ║
# ╚══════════════════════════════════════════════════════════════════════╝
class CommentsSection(CollapsibleWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  -- builds the scroll area and comment container.     │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, sidebar):
        super().__init__("Comments")
        self.sidebar = sidebar
        self._worker: _FetchThread | None = None
        self._current_id = None

        # Scroll area so long comment threads don't break the sidebar
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        self.inner = QWidget()
        self.inner.setStyleSheet("background: transparent;")
        self.comments_layout = QVBoxLayout(self.inner)
        self.comments_layout.setContentsMargins(0, 6, 0, 6)
        self.comments_layout.setSpacing(8)
        self.comments_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.inner)
        self.content_layout.addWidget(self.scroll)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  -- entry point called by OverlaySidebar.            │
    # │  Kills any running worker, clears the UI, shows "Loading...",  │
    # │  then spawns a QThread to hit the API.                         │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post: dict):
        post_id = post.get("id")
        booru_name = post.get("_booru", settings.manager.active_booru)

        # Guard: skip if already showing this post
        if str(post_id) == str(self._current_id):
            return
        self._current_id = post_id

        # Kill previous worker if still running
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(300)

        self._clear()
        self._show_status("Loading comments...")

        self._worker = _FetchThread(post_id, booru_name)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  Slots — run on the GUI thread after the QThread finishes.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_done(self, comments: list[dict]):
        self._clear()
        if not comments:
            self._show_status("No comments on this post.")
            return
        self._render(comments)

    def _on_error(self, msg: str):
        self._clear()
        self._show_status(f"Could not load comments.")
        logging.error(f"[comments] Error: {msg}")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _render  -- builds a card for each comment.  Layout:          │
    # │                                                                  │
    # │    ┌─ accent bar (3px) ── card body ───────────────────────┐    │
    # │    │  AuthorName                           2024-05-11      │    │
    # │    │  Comment text goes here, wrapping as needed...        │    │
    # │    └───────────────────────────────────────────────────────┘    │
    # └──────────────────────────────────────────────────────────────────┘
    def _render(self, comments: list[dict]):
        # Header with count
        n = len(comments)
        hdr = QLabel(f"{n} comment{'s' if n != 1 else ''}")
        hdr.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 11px;"
            f" font-weight: 600; letter-spacing: 0.5px;"
        )
        self.comments_layout.addWidget(hdr)

        for c in comments:
            card = self._build_card(c)
            self.comments_layout.addWidget(card)

        self.comments_layout.addStretch()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _build_card  -- a single comment rendered as a QFrame with    │
    # │  a left accent bar, author label, optional date, and body.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _build_card(self, c: dict) -> QFrame:
        author = c.get("author", "Anonymous")
        body   = c.get("body", "")
        date   = c.get("date", "")

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.BUTTON_BG};
                border: 1px solid {colors.BORDER};
                border-left: 3px solid {colors.ACCENT};
                border-radius: 6px;
            }}
        """)

        v = QVBoxLayout(card)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)

        # ── Author + date row ─────────────────────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)

        author_lbl = QLabel(author)
        author_lbl.setStyleSheet(
            f"color: {colors.ACCENT}; font-weight: 700; font-size: 12px;"
            f" border: none; background: transparent;"
        )
        top.addWidget(author_lbl)
        top.addStretch()

        if date:
            date_lbl = QLabel(date)
            date_lbl.setStyleSheet(
                f"color: {colors.TEXT_MUTED}; font-size: 10px;"
                f" border: none; background: transparent;"
            )
            top.addWidget(date_lbl)

        v.addLayout(top)

        # ── Body ──────────────────────────────────────────────────
        body_lbl = QLabel(body)
        body_lbl.setWordWrap(True)
        body_lbl.setTextFormat(Qt.TextFormat.PlainText)
        body_lbl.setStyleSheet(
            f"color: {colors.TEXT_SECONDARY}; font-size: 12px;"
            f" border: none; background: transparent;"
        )
        v.addWidget(body_lbl)

        return card

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  Helpers — layout clearing and status messages.                 │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear(self):
        while self.comments_layout.count():
            item = self.comments_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _show_status(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 12px; font-style: italic;"
        )
        self.comments_layout.addWidget(lbl)


# ──────────────────────────────────────────────────────────────────────
#  Module helpers (pure functions, no state)
# ──────────────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    """Strip HTML tags, BBCode, decode entities, collapse whitespace."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[/?[a-zA-Z]+\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fmt_date(raw: str) -> str:
    """Best-effort date formatting -> 'YYYY-MM-DD'."""
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(raw[:26], fmt)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return raw[:10] if len(raw) >= 10 else raw


def _parse_xml(text: str) -> list[dict]:
    """Fallback XML parser for Gelbooru sites that ignore json=1."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        out = []
        for c in root.findall(".//comment"):
            body = c.get("body", c.text or "")
            if not body.strip():
                continue
            out.append({
                "author": c.get("creator", "Anonymous"),
                "body":   _clean(body),
                "date":   _fmt_date(c.get("created_at", "")),
            })
        return out
    except Exception:
        return []
