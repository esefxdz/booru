
class OldBookmarkManager:
    # --- Bookmark Helpers ---

    def load_bookmarks(self):
        if not _BOOKMARKS_FILE.exists():
            return
        try:
            with open(_BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                self.bookmarks = json.load(f)
        except Exception as e:
            logging.info(f"[settings] Could not read bookmarks: {e}")

    def save_bookmarks(self):
        try:
            _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(_BOOKMARKS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.bookmarks, f, indent=2)
        except Exception as e:
            logging.info(f"[settings] Could not save bookmarks: {e}")

    def is_post_bookmarked(self, post_id):
        pid = str(post_id)
        return any(str(p.get("id")) == pid for p in self.bookmarks)

    def add_bookmark(self, post):
        if not self.is_post_bookmarked(post.get("id")):
            if "_booru" not in post:
                post["_booru"] = self.active_booru
            self.bookmarks.append(post)
            self.save_bookmarks()

    def remove_bookmark(self, post_id):
        pid = str(post_id)
        self.bookmarks = [p for p in self.bookmarks if str(p.get("id")) != pid]
        self.save_bookmarks()
