"""
displayers/tags.py — Categorized tags view.

Parses tags from the current post using the booru adapter and
displays them categorized (artist, character, general, etc).
"""
from PyQt6.QtWidgets import QVBoxLayout, QLabel
from displayers.details import CollapsibleWidget
from ui import colors


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: TagsDropdown                                                ║
# ║  Subclasses CollapsibleWidget to show a categorized list of tags.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class TagsDropdown(CollapsibleWidget):
    
    def __init__(self, sidebar):
        super().__init__("Tags")
        self.sidebar = sidebar
        
        self.tags_layout = QVBoxLayout()
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(5)
        self.content_layout.addLayout(self.tags_layout)
        
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — uses the booru adapter to categorize the raw      │
    # │  tags array, then renders a section for each category.          │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post):
        # Clear previous tags
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        import boorus
        from adapters import get_adapter
        
        booru_name = post.get('_booru')
        site_data = boorus.REGISTRY.get(booru_name, {})
        adapter = get_adapter(site_data.get('api_type', 'danbooru'))
        
        cats = adapter.get_categorized_tags(post)
        has_tags = False
        
        # Render categories
        for cat_name, tag_list in cats.items():
            if not tag_list: 
                continue
            has_tags = True
            
            cat_lbl = QLabel(cat_name.capitalize())
            cat_lbl.setStyleSheet(f"color: {colors.ACCENT}; font-weight: bold; font-size: 14px; margin-top: 5px;")
            self.tags_layout.addWidget(cat_lbl)
            
            tags_str = ", ".join(tag_list)
            tags_lbl = QLabel(tags_str)
            tags_lbl.setWordWrap(True)
            tags_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 13px;")
            self.tags_layout.addWidget(tags_lbl)
            
        if not has_tags:
            lbl = QLabel("No tags found.")
            lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")
            self.tags_layout.addWidget(lbl)
