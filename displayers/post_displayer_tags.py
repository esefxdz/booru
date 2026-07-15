"""
displayers/post_displayer_tags.py — Categorized clickable tags view.

Two-pass categorization strategy:
  1. Adapter-native (instant for Danbooru / e621 — tags come pre-sorted)
  2. TagCategorizer fallback (Danbooru API + heuristics + local cache) for
     every other booru whose API returns a flat tag string.

Each tag renders as a compact colored chip that adds the tag to the search
bar on click.
"""
from __future__ import annotations
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from displayers.details import CollapsibleWidget
from ui import colors

# ---------------------------------------------------------------------------
# Per-category accent colors (matches the tag_chip palette)
# ---------------------------------------------------------------------------
_CAT_COLORS = {
    "artist":    colors.TAG_ARTIST,     # red
    "character": colors.TAG_CHARACTER,  # green
    "copyright": colors.TAG_COPYRIGHT,  # pink/magenta
    "meta":      colors.TAG_METADATA,   # yellow
    "general":   colors.TAG_GENERAL,    # white/grey
}

_CAT_ORDER = ["artist", "character", "copyright", "meta", "general"]

_CAT_LABELS = {
    "artist":    "Artist",
    "character": "Character",
    "copyright": "Copyright",
    "meta":      "Meta",
    "general":   "General",
}


# ---------------------------------------------------------------------------
# Background worker — runs TagCategorizer off the UI thread
# ---------------------------------------------------------------------------
class _CategorizerThread(QThread):
    """Runs TagCategorizer.categorize_tags() in a background thread."""
    done = pyqtSignal(dict, int)   # (categories, generation)
    failed = pyqtSignal(int)       # generation

    def __init__(self, tags: list[str], generation: int):
        super().__init__()
        self._tags = tags
        self._generation = generation

    def run(self):
        try:
            from tag_categorizer import get_categorizer
            cats = get_categorizer().categorize_tags(self._tags)
            self.done.emit(cats, self._generation)
        except Exception as e:
            logging.error("[post_displayer_tags] Categorizer thread failed: %s", e)
            self.failed.emit(self._generation)


# ---------------------------------------------------------------------------
# Chip widget — a single clickable tag pill
# ---------------------------------------------------------------------------
class _TagChip(QPushButton):
    def __init__(self, tag: str, color: str, on_click):
        super().__init__(tag)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._color = color
        self._apply_style(False)
        self.clicked.connect(lambda: on_click(tag))
        self.setToolTip(f"Search: {tag}")

    def _apply_style(self, hovered: bool):
        bg = self._color + "22"  # 13 % alpha background
        bg_hover = self._color + "44"  # 27 % alpha on hover
        self.setStyleSheet(f"""
            QPushButton {{
                color: {self._color};
                background-color: {'transparent' if not hovered else bg_hover};
                border: 1px solid {self._color}55;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
                border-color: {self._color}AA;
            }}
            QPushButton:pressed {{
                background-color: {self._color}33;
            }}
        """)

    def enterEvent(self, e):
        self._apply_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._apply_style(False)
        super().leaveEvent(e)


# ---------------------------------------------------------------------------
# Wrapping flow layout for chips
# ---------------------------------------------------------------------------
class _FlowLayout(QWidget):
    """Renders tag chips in a wrapping left-to-right flow."""

    def __init__(self, tags: list[str], color: str, on_click):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(6)
        self._color = color
        self._on_click = on_click
        self._build(tags)

    def _build(self, tags: list[str]):
        # Dynamic wrapping logic using a reasonable row size to prevent excessive width
        ROW_SIZE = 4
        for i in range(0, len(tags), ROW_SIZE):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for tag in tags[i:i + ROW_SIZE]:
                chip = _TagChip(tag, self._color, self._on_click)
                row.addWidget(chip)
            row.addStretch()
            self._outer.addLayout(row)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------
class ClickableTagsDropdown(CollapsibleWidget):
    """Modern tag panel with an accordion toggle.
    
    Uses a bounded scroll area so it always fits on the UI.
    """

    def __init__(self, sidebar):
        super().__init__("Tags")
        self.sidebar = sidebar
        self._worker: _CategorizerThread | None = None
        self._current_post: dict | None = None
        self._all_cats: dict = {}

        # Scroll Area for Tags
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.tags_layout = QVBoxLayout(self.content_widget)
        self.tags_layout.setContentsMargins(0, 4, 0, 4)
        self.tags_layout.setSpacing(12)
        
        self.scroll.setWidget(self.content_widget)
        self.content_layout.addWidget(self.scroll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_post(self, post: dict):
        self._current_post = post
        self._generation = getattr(self, '_generation', 0) + 1
        gen = self._generation

        # Stop any running worker
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(500)

        self._clear()
        self._all_cats = {}

        import boorus
        from adapters import get_adapter

        booru_name = post.get("_booru", "")
        site_data = boorus.REGISTRY.get(booru_name, {})
        adapter = get_adapter(site_data.get("api_type", "gelbooru"))

        # Pass 1: adapter-native (instant for Danbooru / e621)
        cats = adapter.get_categorized_tags(post)
        if cats.get("artist") or cats.get("character"):
            self._all_cats = cats
            self._render_all_tags()
            return

        # Pass 2: flat tags → TagCategorizer (async, background thread)
        tags = adapter.get_tags(post)
        if not tags:
            self._show_empty()
            return

        # Show a loading state while the categorizer works
        self._show_loading()
        self._worker = _CategorizerThread(tags, gen)
        self._worker.done.connect(self._on_cats_ready)
        self._worker.failed.connect(self._on_cats_failed)
        self._worker.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_cats_ready(self, cats: dict, generation: int):
        if generation != getattr(self, '_generation', 0):
            return  # stale result from a previous post
        self._apply_cats(cats)

    def _on_cats_failed(self, generation: int):
        if generation != getattr(self, '_generation', 0):
            return
        # Fallback: show all tags as general
        try:
            from adapters import get_adapter
            import boorus
            post = self._current_post
            if post:
                booru_name = post.get("_booru", "")
                site_data = boorus.REGISTRY.get(booru_name, {})
                adapter = get_adapter(site_data.get("api_type", "gelbooru"))
                tags = adapter.get_tags(post)
                self._apply_cats({"general": tags})
        except Exception:
            self._apply_cats({"general": []})

    def _apply_cats(self, cats: dict):
        # If categorizer returned nothing useful, flatten into general
        if not any(cats.values()):
            all_tags = []
            for v in cats.values():
                all_tags.extend(v)
            cats = {"general": all_tags}
        self._all_cats = cats
        self._render_all_tags()

        # If only meta + general have tags, API categorization didn't work —
        # show a hint to unlock Danbooru so artist/character/copyright appear.
        has_meaningful = bool(
            cats.get("artist") or cats.get("character") or cats.get("copyright")
        )
        if not has_meaningful and (cats.get("general") or cats.get("meta")):
            self._show_unlock_hint()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_all_tags(self):
        self._clear()
        
        for cat in _CAT_ORDER:
            tag_list = self._all_cats.get(cat, [])
            if tag_list:
                self._add_section(cat, tag_list)
        for cat, tag_list in self._all_cats.items():
            if cat not in _CAT_ORDER and tag_list:
                self._add_section(cat, tag_list)
                
        # Add stretch at bottom to prevent weird spacing
        self.tags_layout.addStretch()

    def _clear(self):
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _show_loading(self):
        self._clear()
        lbl = QLabel("Categorizing tags…")
        lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px; font-style: italic;")
        self.tags_layout.addWidget(lbl)

    def _show_empty(self):
        self._clear()
        lbl = QLabel("No tags found.")
        lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px; font-style: italic;")
        self.tags_layout.addWidget(lbl)

    def _show_unlock_hint(self):
        """Show a hint when all tags are uncategorized (Danbooru API blocked)."""
        hint = QLabel(
            "💡 Tags are not categorized yet.\n"
            "Click below to unlock Danbooru — solve one CAPTCHA and all "
            "future tags will show artist/character/copyright groups."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {colors.WARNING}; font-size: 11px; "
            f"background: {colors.WARNING}15; padding: 8px; border-radius: 6px;"
        )
        self.tags_layout.addWidget(hint)

        btn = QPushButton("🔐  Unlock Tag Categories (Solve CAPTCHA)")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {colors.ACCENT};
                color: {colors.TEXT_PRIMARY};
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {colors.ACCENT}DD; }}
        """)
        btn.clicked.connect(self._open_danbooru_cf_bypass)
        self.tags_layout.addWidget(btn)

    def _open_danbooru_cf_bypass(self):
        """Open the Cloudflare bypass dialog for Danbooru."""
        from ui.browser_dialog import run_cf_bypass
        run_cf_bypass(
            "danbooru", "https://danbooru.donmai.us", self,
            on_success=lambda: self._on_danbooru_unlocked(),
        )

    def _on_danbooru_unlocked(self):
        """Called after the user solves the Danbooru CAPTCHA — re-categorize."""
        if self._current_post:
            self.load_post(self._current_post)

    def _add_section(self, cat: str, tags: list[str]):
        color = _CAT_COLORS.get(cat, colors.TEXT_MUTED)
        label_text = _CAT_LABELS.get(cat, cat.capitalize())

        # ── Category header ──────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 8px;")
        dot.setFixedWidth(12)
        header.addWidget(dot)

        cat_lbl = QLabel(f"{label_text}  <span style='color:{colors.TEXT_MUTED};font-size:11px;'>({len(tags)})</span>")
        cat_lbl.setTextFormat(Qt.TextFormat.RichText)
        cat_lbl.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 12px; letter-spacing: 0.5px;")
        header.addWidget(cat_lbl)
        header.addStretch()

        section = QWidget()
        section.setStyleSheet("background: transparent;")
        sec_v = QVBoxLayout(section)
        sec_v.setContentsMargins(0, 0, 0, 0)
        sec_v.setSpacing(6)
        sec_v.addLayout(header)

        # ── Chips ────────────────────────────────────────────────────
        flow = _FlowLayout(tags, color, self._tag_clicked)
        sec_v.addWidget(flow)

        # ── Divider ──────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background-color: {colors.BORDER}; margin-top: 4px; margin-bottom: 4px;")
        divider.setFixedHeight(1)
        sec_v.addWidget(divider)

        self.tags_layout.addWidget(section)

    # ------------------------------------------------------------------
    # Tag click
    # ------------------------------------------------------------------

    def _tag_clicked(self, tag: str):
        try:
            self.sidebar.overlay.parent_gui.add_tag(tag)
        except Exception as e:
            logging.error(f"[post_displayer_tags] add_tag failed: {e}")

