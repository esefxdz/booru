"""
displayers/post_displayer_tags.py — Categorized clickable tags view.

Parses tags from the current post using the booru adapter and
displays them categorized (artist, character, general, etc).
Each tag is a clickable link that adds the tag to the search bar.
"""
from PyQt6.QtWidgets import QVBoxLayout, QLabel
from PyQt6.QtCore import Qt
from displayers.details import CollapsibleWidget
from ui import colors


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: ClickableTagsDropdown                                       ║
# ║  Subclasses CollapsibleWidget to show a categorized list of tags.   ║
# ║  Tags are clickable and integrated with the main search bar.        ║
# ╚══════════════════════════════════════════════════════════════════════╝
class ClickableTagsDropdown(CollapsibleWidget):
    
    def __init__(self, sidebar):
        super().__init__("Tags")
        self.sidebar = sidebar
        
        self.tags_layout = QVBoxLayout()
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(5)
        self.content_layout.addLayout(self.tags_layout)
        
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
        adapter = get_adapter(site_data.get('api_type', 'gelbooru'))
        
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
            
            tag_links = []
            for t in tag_list:
                tag_links.append(f'<a href="{t}" style="color: {colors.TEXT_SECONDARY}; text-decoration: none;">{t}</a>')
                
            tags_str = ", ".join(tag_links)
            tags_lbl = QLabel(tags_str)
            tags_lbl.setWordWrap(True)
            tags_lbl.setTextFormat(Qt.TextFormat.RichText)
            tags_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            
            # The parent_gui is self.sidebar.overlay.parent_gui
            try:
                tags_lbl.linkActivated.connect(self.sidebar.overlay.parent_gui.add_tag)
            except Exception as e:
                print(f"[post_displayer_tags] Failed to connect linkActivated: {e}")
            
            # Optional: Add hover effect style globally to the label
            tags_lbl.setStyleSheet(f"""
                QLabel a {{ color: {colors.TEXT_SECONDARY}; text-decoration: none; }}
            """)
            self.tags_layout.addWidget(tags_lbl)
            
        if not has_tags:
            lbl = QLabel("No tags found.")
            lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY};")
            self.tags_layout.addWidget(lbl)
