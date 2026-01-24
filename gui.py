import customtkinter as ctk
import asyncio, threading, httpx, os
from PIL import Image
from io import BytesIO
from downloader import BooruDownloader
import config
from player import MediaPlayer

class BooruGui(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Booru Engine Pro - Lite")
        self.geometry("1300x900")
        
        # State Control
        self.downloader = BooruDownloader()
        self.current_page = 0
        self.booru_buttons = {}
        self._is_loading = False # LOCK: Prevents double-clicks from breaking the app

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.setup_topbar()
        self.setup_sidebar()
        self.setup_gallery()
        self.setup_tag_panel()
        
        self.select_booru(config.ACTIVE_BOORU)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_topbar(self):
        self.topbar = ctk.CTkFrame(self, height=70)
        self.topbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.search_entry = ctk.CTkEntry(self.topbar, placeholder_text="Enter tags...", height=40)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=20, pady=15)
        self.search_entry.bind("<Return>", lambda e: self.trigger_fetch(new=True))
        ctk.CTkButton(self.topbar, text="SEARCH", width=120, height=40, 
                      command=lambda: self.trigger_fetch(new=True)).pack(side="right", padx=20)

    def setup_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="nsew")

        self.status_lbl = ctk.CTkLabel(self.sidebar, text="Ready", text_color="gray")
        self.status_lbl.pack(pady=20)

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.pack(pady=10)
        ctk.CTkButton(nav, text="<", width=40, command=lambda: self.change_page(-1)).grid(row=0, column=0, padx=5)
        self.page_lbl = ctk.CTkLabel(nav, text="Pg 0")
        self.page_lbl.grid(row=0, column=1, padx=10)
        ctk.CTkButton(nav, text=">", width=40, command=lambda: self.change_page(1)).grid(row=0, column=2, padx=5)

        self.src_scroll = ctk.CTkScrollableFrame(self.sidebar, label_text="SOURCES")
        self.src_scroll.pack(expand=True, fill="both", padx=10, pady=10)
        for name in config.BOORUS.keys():
            row = ctk.CTkFrame(self.src_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            btn = ctk.CTkButton(row, text=name.upper(), width=140, command=lambda n=name: self.select_booru(n))
            btn.pack(side="left", expand=True, fill="x")
            self.booru_buttons[name] = btn
            ctk.CTkButton(row, text="⚙", width=30, fg_color="#333", 
                          command=lambda n=name: self.open_api_settings(n)).pack(side="right", padx=(5,0))

        ctk.CTkButton(self.sidebar, text="BULK DOWNLOAD", fg_color="#2c3e50", 
                      command=self.open_bulk_window).pack(pady=5, padx=10, fill="x")
        ctk.CTkButton(self.sidebar, text="GLOBAL SETTINGS", 
                      command=self.open_global_settings).pack(pady=(5, 20), padx=10, fill="x")

    def setup_gallery(self):
        self.gallery = ctk.CTkScrollableFrame(self, label_text="Gallery")
        self.gallery.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        for i in range(4): self.gallery.grid_columnconfigure(i, weight=1)

    def setup_tag_panel(self):
        self.tag_panel = ctk.CTkFrame(self, width=250)
        self.tag_panel.grid(row=1, column=2, sticky="nsew")
        ctk.CTkLabel(self.tag_panel, text="POST TAGS", font=("Arial", 14, "bold")).pack(pady=10)
        self.tag_container = ctk.CTkScrollableFrame(self.tag_panel, label_text="Click to add")
        self.tag_container.pack(expand=True, fill="both", padx=10, pady=10)

    # --- FETCH LOGIC
    def trigger_fetch(self, new=False):
        if self._is_loading: return # Stop spam clicks
        if new: self.current_page = 0
        
        self._is_loading = True
        self.page_lbl.configure(text=f"Pg {self.current_page}")
        self.status_lbl.configure(text="Searching...", text_color="yellow")
        
        # Clear gallery immediately for a snappy feel
        for w in self.gallery.winfo_children(): w.destroy()
        self.gallery._parent_canvas.yview_moveto(0) # Snap to top
        
        tags = self.search_entry.get()
        threading.Thread(target=self.run_async_fetch, args=(tags,), daemon=True).start()

    def run_async_fetch(self, tags):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            posts = loop.run_until_complete(self.downloader.get_image_urls(tags, config.SEARCH_LIMIT, self.current_page))
            if posts:
                # fetch_previews uses gather(), making page turns instant
                loop.run_until_complete(self.downloader.fetch_previews(posts, self.queue_display))
                self.after(0, lambda: self.status_lbl.configure(text="Ready", text_color="green"))
            else:
                self.after(0, lambda: self.status_lbl.configure(text="No Results", text_color="orange"))
        except Exception as e:
            print(f"Fetch Error: {e}")
            self.after(0, lambda: self.status_lbl.configure(text="Error!", text_color="red"))
        finally:
            self._is_loading = False # Crucial: Unlock the UI
            loop.close()

    def queue_display(self, pil_img, post, idx):
        self.after(0, self.display_item, pil_img, post, idx)

    def display_item(self, pil_img, post, idx):
        try:
            ctk_img = ctk.CTkImage(pil_img, size=(config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE))
            btn = ctk.CTkButton(self.gallery, image=ctk_img, text="", fg_color="transparent", 
                                command=lambda: self.open_preview(post))
            btn._ref = ctk_img # Prevent garbage collection
            btn.grid(row=idx//4, column=idx%4, padx=5, pady=5)
        except: pass

    # --- SHARED FEATURES ---
    def open_api_settings(self, name):
        pop = ctk.CTkToplevel(self); pop.title(f"{name} Auth"); pop.geometry("300x250")
        pop.attributes("-topmost", True) # Keep on top
        creds = config.CREDENTIALS.get(name, {"user_id": "", "api_key": ""})
        u_ent = ctk.CTkEntry(pop, placeholder_text="User ID"); u_ent.pack(pady=10); u_ent.insert(0, creds['user_id'])
        a_ent = ctk.CTkEntry(pop, placeholder_text="API Key", show="*"); a_ent.pack(pady=10); a_ent.insert(0, creds['api_key'])
        
        def save():
            config.CREDENTIALS[name] = {"api_key": a_ent.get(), "user_id": u_ent.get()}
            self.downloader.save_credentials(name, u_ent.get(), a_ent.get())
            pop.destroy()
        ctk.CTkButton(pop, text="SAVE", command=save).pack(pady=10)

    def select_booru(self, name):
        config.ACTIVE_BOORU = name
        self.downloader.site_data = config.BOORUS[name]
        for n, btn in self.booru_buttons.items():
            btn.configure(fg_color="#1f538d" if n == name else "#333333")

    def change_page(self, delta):
        if not self._is_loading:
            self.current_page = max(0, self.current_page + delta)
            self.trigger_fetch()

    def update_tags(self, post):
        for w in self.tag_container.winfo_children(): w.destroy()
        tag_list = self.downloader.get_tag_list(post)
        for t in tag_list:
            ctk.CTkButton(self.tag_container, text=t, fg_color="transparent", text_color="#3498db", 
                          height=24, command=lambda x=t: self.add_tag(x)).pack(fill="x")

    def add_tag(self, tag):
        cur = self.search_entry.get()
        self.search_entry.delete(0, 'end')
        self.search_entry.insert(0, f"{cur} {tag}".strip())
        self.trigger_fetch(new=True)

    def open_preview(self, post):
        self.update_tags(post)
        url = (post.get('file_url') or "").lower()
        if any(x in url for x in ['.mp4', '.webm', '.gif']):
            MediaPlayer(post).launch(status_callback=lambda m: self.status_lbl.configure(text=m))
        else:
            top = ctk.CTkToplevel(self); top.title("Preview")
            lbl = ctk.CTkLabel(top, text="Loading...")
            lbl.pack(expand=True, fill="both", padx=20, pady=20)
            ctk.CTkButton(top, text="DOWNLOAD", command=lambda: self.save_img(post)).pack(pady=10)
            threading.Thread(target=self._load_full_img, args=(post, lbl), daemon=True).start()

    def _load_full_img(self, post, lbl):
        try:
            url = post.get('sample_url') or post.get('file_url')
            if url.startswith('//'): url = 'https:' + url
            res = httpx.get(url, headers=config.DEFAULT_HEADERS)
            img = Image.open(BytesIO(res.content))
            img.thumbnail((800, 800))
            cimg = ctk.CTkImage(img, size=img.size)
            self.after(0, lambda: lbl.configure(image=cimg, text=""))
            lbl._ref = cimg
        except: self.after(0, lambda: lbl.configure(text="Failed to load"))

    def save_img(self, post):
        folder = self.downloader.get_valid_folder(self.search_entry.get())
        threading.Thread(target=lambda: asyncio.run(self.downloader.download_task(None, post, folder)), daemon=True).start()
        self.status_lbl.configure(text=f"Saved {post.get('id')}", text_color="cyan")

    def open_bulk_window(self):
        pop = ctk.CTkToplevel(self); pop.geometry("300x200")
        pop.attributes("-topmost", True)
        ctk.CTkLabel(pop, text="Download limit:").pack(pady=10)
        e = ctk.CTkEntry(pop); e.pack(); e.insert(0, "20")
        def run():
            limit = int(e.get()); pop.destroy()
            threading.Thread(target=self._bulk_proc, args=(self.search_entry.get(), limit), daemon=True).start()
        ctk.CTkButton(pop, text="START", command=run).pack(pady=20)

    def _bulk_proc(self, tags, limit):
        loop = asyncio.new_event_loop()
        posts = loop.run_until_complete(self.downloader.get_image_urls(tags, limit))
        folder = self.downloader.get_valid_folder(tags)
        self.after(0, lambda: self.status_lbl.configure(text="Downloading...", text_color="cyan"))
        for p in posts: 
            loop.run_until_complete(self.downloader.download_task(None, p, folder))
        self.after(0, lambda: self.status_lbl.configure(text="Bulk Done!", text_color="green"))
        loop.close()

    def open_global_settings(self):
        win = ctk.CTkToplevel(self); win.title("Global Settings"); win.geometry("400x350")
        win.attributes("-topmost", True)
        ctk.CTkLabel(win, text="Blacklist Tags:").pack(pady=10)
        bl_entry = ctk.CTkEntry(win, width=300); bl_entry.pack(); bl_entry.insert(0, config.BLACKLIST)
        
        ctk.CTkLabel(win, text="Thumbnail Size:").pack(pady=10)
        sz_entry = ctk.CTkEntry(win, width=300); sz_entry.pack(); sz_entry.insert(0, str(config.THUMBNAIL_SIZE))
        
        def save():
            config.BLACKLIST = bl_entry.get()
            config.THUMBNAIL_SIZE = int(sz_entry.get())
            # Use the method inside downloader to save
            self.downloader._update_config_file("BLACKLIST =", f'BLACKLIST = "{config.BLACKLIST}"\n')
            self.downloader._update_config_file("THUMBNAIL_SIZE =", f'THUMBNAIL_SIZE = {config.THUMBNAIL_SIZE}\n')
            win.destroy()
        ctk.CTkButton(win, text="SAVE ALL", command=save).pack(pady=20)

    def on_closing(self):
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.downloader.close())
            loop.close()
        except: pass
        self.destroy()

if __name__ == "__main__":
    BooruGui().mainloop()