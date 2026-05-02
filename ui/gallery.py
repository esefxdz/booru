import customtkinter as ctk
import settings
import threading
import asyncio
from displayer import UniversalViewer

class Gallery(ctk.CTkScrollableFrame):
    def __init__(self, parent, main_app):
        super().__init__(parent, label_text="Gallery")
        self.main_app = main_app
        for i in range(4): 
            self.grid_columnconfigure(i, weight=1)
        
    def queue_display(self, pil_img, post, idx):
        self.after(0, self.display_item, pil_img, post, idx)

    def display_item(self, pil_img, post, idx):
        try:
            f = ctk.CTkFrame(self, fg_color="transparent")
            f.grid(row=idx//4, column=idx%4, padx=5, pady=5)
            
            ctk_img = ctk.CTkImage(pil_img, size=(settings.THUMBNAIL_SIZE, settings.THUMBNAIL_SIZE))
            btn = ctk.CTkButton(f, image=ctk_img, text="", fg_color="transparent", 
                                command=lambda: self.open_preview(post))
            btn._ref = ctk_img # Prevent garbage collection
            btn.pack()
            
            # Bookmark overlay
            post_id = str(post.get("id"))
            
            def toggle_bm():
                is_bm = any(str(p.get("id")) == post_id for p in settings.BOOKMARKS)
                if is_bm:
                    settings.BOOKMARKS = [p for p in settings.BOOKMARKS if str(p.get("id")) != post_id]
                    bm_btn.configure(text="☆", text_color="white")
                else:
                    settings.BOOKMARKS.append(post)
                    bm_btn.configure(text="★", text_color="gold")
                settings.save_bookmarks()
                
            is_bm_init = any(str(p.get("id")) == post_id for p in settings.BOOKMARKS)
            bm_btn = ctk.CTkButton(f, text="★" if is_bm_init else "☆", width=30, height=30,
                                   fg_color="#222", hover_color="#444", 
                                   text_color="gold" if is_bm_init else "white",
                                   font=("Arial", 18), command=toggle_bm)
            bm_btn.place(relx=0.95, rely=0.05, anchor="ne")
            
        except Exception as e:
            print(f"[gui] display_item error at idx={idx}: {e}")

    def repack_rows(self):
        # Original gui.py had _repack_rows iterating over self.booru_rows 
        # But wait, self.booru_rows is actually in the sidebar!
        # Re-packing rows in Gallery isn't necessary, the sidebar handles booru rows.
        # Oh, _repack_rows is actually for the sidebar. I'll ignore it here.
        pass

    def open_preview(self, post):
        self.main_app.tag_panel.update_tags(post)
        UniversalViewer(self.main_app, post)

    def save_img(self, post):
        folder = self.main_app.downloader.get_valid_folder(self.main_app.search_entry.get())
        threading.Thread(target=lambda: asyncio.run(self.main_app.downloader.download_task(None, post, folder)), daemon=True).start()
        self.main_app.status_lbl.configure(text=f"Saved {post.get('id')}", text_color="cyan")
