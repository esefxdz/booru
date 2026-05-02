import os
import customtkinter as ctk
import settings

class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, width=250, corner_radius=0)
        self.main_app = main_app
        self.setup_ui()
        
    def setup_ui(self):
        self.status_lbl = ctk.CTkLabel(self, text="Ready", text_color="gray")
        self.status_lbl.pack(pady=20)

        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(pady=10)
        ctk.CTkButton(nav, text="<", width=40, command=lambda: self.main_app.change_page(-1)).grid(row=0, column=0, padx=5)
        self.page_lbl = ctk.CTkLabel(nav, text="Pg 1")
        self.page_lbl.grid(row=0, column=1, padx=10)
        ctk.CTkButton(nav, text=">", width=40, command=lambda: self.main_app.change_page(1)).grid(row=0, column=2, padx=5)

        self.src_scroll = ctk.CTkScrollableFrame(self, label_text="SOURCES")
        self.src_scroll.pack(expand=True, fill="both", padx=10, pady=10)

        from ui.dialogs import AddBooruDialog
        ctk.CTkButton(self, text="+ ADD BOORU", fg_color="#1a3a1a",
                      command=lambda: AddBooruDialog.show(self.main_app)).pack(pady=(0, 5), padx=10, fill="x")
                      
        from ui.dialogs import BulkDownloadDialog
        ctk.CTkButton(self, text="BULK DOWNLOAD", fg_color="#2c3e50",
                      command=lambda: BulkDownloadDialog.show(self.main_app, self.main_app.search_entry.get())).pack(pady=5, padx=10, fill="x")

        def open_files_folder():
            os.startfile(str(settings.DOWNLOAD_DIR.absolute()))

        ctk.CTkButton(self, text="OPEN FILES", fg_color="#8B6914",
                      command=open_files_folder).pack(pady=5, padx=10, fill="x")

        def toggle_bookmarks_mode():
            self.main_app.is_bookmarks_mode = not getattr(self.main_app, 'is_bookmarks_mode', False)
            if self.main_app.is_bookmarks_mode:
                self.bm_mode_btn.configure(fg_color="#ffd700", text_color="#000")
                self.src_scroll.configure(label_text="LOCAL BOOKMARKS (ALL)")
                self.main_app.bookmark_filter = None
                for btn in self.main_app.booru_buttons.values(): btn.configure(fg_color="#333333")
            else:
                self.bm_mode_btn.configure(fg_color="#4B0082", text_color="white")
                self.src_scroll.configure(label_text="SOURCES")
                self.main_app.bookmark_filter = None
                if settings.ACTIVE_BOORU in self.main_app.booru_buttons:
                    self.main_app.booru_buttons[settings.ACTIVE_BOORU].configure(fg_color="#1f538d")
            self.main_app.trigger_fetch(new=True)

        self.bm_mode_btn = ctk.CTkButton(self, text="BOOKMARKS", fg_color="#4B0082",
                                         command=toggle_bookmarks_mode)
        self.bm_mode_btn.pack(pady=5, padx=10, fill="x")

        from ui.dialogs import GlobalSettingsDialog
        ctk.CTkButton(self, text="GLOBAL SETTINGS",
                      command=lambda: GlobalSettingsDialog.show(self.main_app)).pack(pady=(5, 20), padx=10, fill="x")

class TagPanel(ctk.CTkFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, width=250)
        self.main_app = main_app
        self.setup_ui()
        
    def setup_ui(self):
        ctk.CTkLabel(self, text="POST TAGS", font=("Arial", 14, "bold")).pack(pady=10)
        self.container = ctk.CTkScrollableFrame(self, label_text="Click to add")
        self.container.pack(expand=True, fill="both", padx=10, pady=10)

    def update_tags(self, post):
        import asyncio
        for w in self.container.winfo_children(): w.destroy()
        cats = self.main_app.downloader.get_categorized_tags(post)
        
        total_tags = sum(len(v) for v in cats.values())
        is_flat = total_tags > 0 and len(cats["general"]) == total_tags

        if is_flat:
            self._render_tags(cats)
            async def fetch_and_render():
                from tag_categorizer import categorizer
                new_cats = await categorizer.categorize_tags(cats["general"])
                if self.container.winfo_exists():
                    self.after(0, lambda: self._render_tags(new_cats))
            
            import threading
            threading.Thread(target=lambda: asyncio.run(fetch_and_render()), daemon=True).start()
        else:
            self._render_tags(cats)

    def _render_tags(self, cats):
        for w in self.container.winfo_children(): w.destroy()
        colors = {
            "artist": "#e74c3c",     # red
            "copyright": "#9b59b6",  # purple
            "meta": "#e67e22",       # orange
            "general": "#3498db"     # blue
        }
        labels = {
            "artist": "🎨 ARTIST",
            "copyright": "© COPYRIGHT",
            "meta": "📌 METADATA",
            "general": "🏷️ GENERAL"
        }
        for cat in ["artist", "copyright", "meta", "general"]:
            tags = sorted(cats.get(cat, []))
            if not tags: continue
            
            lbl = ctk.CTkLabel(self.container, text=labels[cat], text_color=colors[cat], font=("Arial", 11, "bold"))
            lbl.pack(fill="x", pady=(10 if self.container.winfo_children() else 0, 2))
            
            for t in tags:
                if not t: continue
                ctk.CTkButton(self.container, text=t, fg_color="transparent", text_color=colors[cat], hover_color="#2c3e50",
                              height=24, command=lambda x=t: self.main_app.add_tag(x)).pack(fill="x")
