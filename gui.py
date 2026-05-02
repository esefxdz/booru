import customtkinter as ctk
import settings
import boorus
from downloader import BooruDownloader
from controller import AppController
from ui.sidebar import Sidebar, TagPanel
from ui.gallery import Gallery
from ui.dialogs import APISettingsDialog, GlobalSettingsDialog, BulkDownloadDialog, AddBooruDialog

class BooruGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Booru Engine Pro - Lite")
        self.geometry("1300x900")

        # State Control
        self.downloader = BooruDownloader()
        self.controller = AppController(self, self.downloader)
        
        self.current_page = 1
        self.booru_buttons = {}
        self._is_loading = False
        self.is_bookmarks_mode = False
        self.bookmark_filter = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.setup_topbar()
        
        self.sidebar = Sidebar(self, self)
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        
        self.gallery = Gallery(self, self)
        self.gallery.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        
        self.tag_panel = TagPanel(self, self)
        self.tag_panel.grid(row=1, column=2, sticky="nsew")

        self.rebuild_source_list()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, lambda: self.trigger_fetch(new=True))

    def setup_topbar(self):
        self.topbar = ctk.CTkFrame(self, height=70)
        self.topbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.search_entry = ctk.CTkEntry(self.topbar, placeholder_text="Enter tags...", height=40)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=20, pady=15)
        self.search_entry.bind("<Return>", lambda e: self.trigger_fetch(new=True))
        ctk.CTkButton(self.topbar, text="SEARCH", width=120, height=40,
                      command=lambda: self.trigger_fetch(new=True)).pack(side="right", padx=20)

    def trigger_fetch(self, new=False):
        tags = self.search_entry.get()
        self.controller.trigger_fetch(tags, new)

    def change_page(self, delta):
        if self._is_loading: return
        new_p = self.current_page + delta
        if new_p < 1: new_p = 1
        self.current_page = new_p
        self.trigger_fetch()

    def add_tag(self, tag):
        cur = self.search_entry.get()
        self.search_entry.delete(0, 'end')
        self.search_entry.insert(0, f"{cur} {tag}".strip())
        self.trigger_fetch(new=True)

    def select_booru(self, name):
        if self.is_bookmarks_mode:
            self.bookmark_filter = name
            for n, btn in self.booru_buttons.items():
                btn.configure(fg_color="#1f538d" if n == name else "#333333")
            self.trigger_fetch(new=True)
            return

        settings.ACTIVE_BOORU = name
        for n, btn in self.booru_buttons.items():
            btn.configure(fg_color="#1f538d" if n == name else "#333333")
        self.trigger_fetch(new=True)

    def rebuild_source_list(self):
        for w in self.sidebar.src_scroll.winfo_children():
            w.destroy()
        
        self.booru_rows = []
        self.booru_buttons = {}

        items = list(boorus.REGISTRY.keys())
        if settings.USE_ARROWS_FOR_SORTING:
            items.sort() # Fallback sorting
        
        for idx, name in enumerate(items):
            row = ctk.CTkFrame(self.sidebar.src_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            self.booru_rows.append(row)

            if settings.USE_ARROWS_FOR_SORTING:
                def move_up(curr=idx):
                    if curr > 0:
                        items[curr], items[curr-1] = items[curr-1], items[curr]
                        # Hacky resort
                        boorus.REGISTRY = {k: boorus.REGISTRY[k] for k in items}
                        self.rebuild_source_list()

                def move_down(curr=idx):
                    if curr < len(items) - 1:
                        items[curr], items[curr+1] = items[curr+1], items[curr]
                        boorus.REGISTRY = {k: boorus.REGISTRY[k] for k in items}
                        self.rebuild_source_list()

                up_btn = ctk.CTkButton(row, text="▲", width=24, fg_color="#444", command=move_up)
                up_btn.pack(side="left", padx=(2, 0))
                dn_btn = ctk.CTkButton(row, text="▼", width=24, fg_color="#444", command=move_down)
                dn_btn.pack(side="left", padx=(2, 0))

            btn = ctk.CTkButton(row, text=name.upper(), 
                                fg_color="#1f538d" if (name == settings.ACTIVE_BOORU and not getattr(self, 'is_bookmarks_mode', False)) else "#333333",
                                anchor="w", command=lambda n=name: self.select_booru(n))
            btn.pack(side="left", fill="x", expand=True)
            self.booru_buttons[name] = btn

            if not settings.USE_ARROWS_FOR_SORTING:
                # Drag & Drop sorting
                def on_press(e, r=row):
                    self._drag_start_y = e.y_root
                    self._drag_row = r

                def on_motion(e, r=row):
                    if not hasattr(self, '_drag_row') or self._drag_row != r: return
                    y_offset = e.y_root - self._drag_start_y
                    if abs(y_offset) > 20:
                        idx_in_list = self.booru_rows.index(r)
                        if y_offset < 0 and idx_in_list > 0:
                            self.booru_rows[idx_in_list], self.booru_rows[idx_in_list-1] = self.booru_rows[idx_in_list-1], self.booru_rows[idx_in_list]
                            self._repack_rows()
                            self._drag_start_y = e.y_root
                        elif y_offset > 0 and idx_in_list < len(self.booru_rows) - 1:
                            self.booru_rows[idx_in_list], self.booru_rows[idx_in_list+1] = self.booru_rows[idx_in_list+1], self.booru_rows[idx_in_list]
                            self._repack_rows()
                            self._drag_start_y = e.y_root

                def on_release(e):
                    if hasattr(self, '_drag_row'):
                        del self._drag_row
                        new_reg = {}
                        for r in self.booru_rows:
                            for k, b in self.booru_buttons.items():
                                if b.winfo_parent() == str(r):
                                    new_reg[k] = boorus.REGISTRY[k]
                                    break
                        boorus.REGISTRY = new_reg

                # Bind to the internal elements of CTkButton to capture mouse events
                btn._canvas.bind("<Button-1>", on_press)
                btn._canvas.bind("<B1-Motion>", on_motion)
                btn._canvas.bind("<ButtonRelease-1>", on_release)
                if hasattr(btn, '_text_label') and btn._text_label:
                    btn._text_label.bind("<Button-1>", on_press)
                    btn._text_label.bind("<B1-Motion>", on_motion)
                    btn._text_label.bind("<ButtonRelease-1>", on_release)

            from ui.dialogs import APISettingsDialog
            ctk.CTkButton(row, text="⚙", width=30, fg_color="#555", 
                          command=lambda n=name: APISettingsDialog.show(self, n)).pack(side="right", padx=(5,0))

    def _repack_rows(self):
        for r in self.booru_rows:
            r.pack_forget()
        for r in self.booru_rows:
            r.pack(fill="x", pady=2)

    def remove_booru(self, name):
        import os
        if name in boorus.REGISTRY:
            del boorus.REGISTRY[name]
        booru_file = os.path.join(os.path.dirname(__file__), "boorus", f"{name}.py")
        if os.path.exists(booru_file):
            try:
                os.remove(booru_file)
            except Exception as e:
                print(f"Error deleting booru file: {e}")
        self.rebuild_source_list()
        
        if settings.ACTIVE_BOORU == name:
            if boorus.REGISTRY:
                settings.ACTIVE_BOORU = list(boorus.REGISTRY.keys())[0]
            else:
                settings.ACTIVE_BOORU = "danbooru"
            self.downloader.init_adapter()
            self.trigger_fetch(new=True)

    def on_closing(self):
        import shutil
        tmp = settings.DOWNLOAD_DIR / "temp_media"
        if tmp.exists():
            try:
                shutil.rmtree(tmp)
            except:
                pass
        self.destroy()