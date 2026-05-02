import asyncio
import threading
import settings
import boorus

class AppController:
    def __init__(self, main_app, downloader):
        self.main_app = main_app
        self.downloader = downloader

    def trigger_fetch(self, tags, is_new=False):
        if self.main_app._is_loading: return
        self.main_app._is_loading = True

        if is_new:
            self.main_app.current_page = 1

        self.main_app.sidebar.page_lbl.configure(text=f"Pg {self.main_app.current_page}")
        self.main_app.sidebar.status_lbl.configure(text="Loading...", text_color="yellow")
        for w in self.main_app.gallery.winfo_children(): w.destroy()
        self.main_app.tag_panel.container.winfo_children() # Just to be safe, could clear tags too

        threading.Thread(target=self.run_async_fetch, args=(tags,), daemon=True).start()

    def run_async_fetch(self, tags):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if getattr(self.main_app, 'is_bookmarks_mode', False):
                all_bms = settings.BOOKMARKS
                if getattr(self.main_app, 'bookmark_filter', None):
                    all_bms = [p for p in all_bms if p.get("_booru") == self.main_app.bookmark_filter]

                if tags.strip():
                    search_tags = tags.split()
                    all_bms = [p for p in all_bms if all(t in p.get('tags', []) for t in search_tags)]

                start = (self.main_app.current_page - 1) * settings.SEARCH_LIMIT
                end = start + settings.SEARCH_LIMIT
                posts = all_bms[start:end]
            else:
                posts = loop.run_until_complete(self.downloader.get_image_urls(tags, settings.SEARCH_LIMIT, self.main_app.current_page - 1))
                for p in posts: p["_booru"] = settings.ACTIVE_BOORU

            if posts:
                loop.run_until_complete(self.downloader.fetch_previews(posts, self.main_app.gallery.queue_display))
                self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="Ready", text_color="green"))
            else:
                self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="No Results", text_color="orange"))
        except Exception as e:
            print(f"Fetch Error: {e}")
            self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="Error!", text_color="red"))
        finally:
            self.main_app._is_loading = False
            loop.close()

    def bulk_download(self, tags, limit):
        threading.Thread(target=self._bulk_proc, args=(tags, limit), daemon=True).start()

    def _bulk_proc(self, tags, limit):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="Fetching metadata...", text_color="yellow"))
            posts = loop.run_until_complete(self.downloader.get_image_urls(tags, limit, 0))
            if not posts:
                self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="No posts found.", text_color="orange"))
                return
            
            folder = self.downloader.get_valid_folder(tags)
            self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text=f"Downloading {len(posts)} items...", text_color="yellow"))
            
            async def dls():
                tasks = []
                for p in posts:
                    tasks.append(self.downloader.download_task(None, p, folder))
                await asyncio.gather(*tasks)

            loop.run_until_complete(dls())
            self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text=f"Bulk downloaded {len(posts)} items!", text_color="green"))
        except Exception as e:
            print(f"[bulk] error: {e}")
            self.main_app.after(0, lambda: self.main_app.sidebar.status_lbl.configure(text="Bulk Error!", text_color="red"))
        finally:
            loop.close()
