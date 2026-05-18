import os
import json
import asyncio
import httpx
import threading
from pathlib import Path
from ui import settings_view as settings

# Danbooru categories: 0=general, 1=artist, 3=copyright, 4=character, 5=meta
CAT_MAP = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta"
}

class TagCategorizer:
    def __init__(self):
        self.cache_file = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "tag_cache.json"
        self.cache = {}
        self._load_cache()
        self._lock = threading.Lock()
        
    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception as e:
                print(f"[tag_categorizer] Failed to load cache: {e}")

    def _save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
        except Exception as e:
            print(f"[tag_categorizer] Failed to save cache: {e}")

    def _apply_heuristics(self, tag: str):
        """Apply simple heuristics for tags."""
        t = tag.lower()
        if t.endswith("_(artist)"): return "artist"
        if t.endswith("_(copyright)"): return "copyright"
        if t.endswith("_(character)"): return "character"
        if t in ["highres", "absurdres", "translated", "commentary_request", "commission"]: return "meta"
        return None

    async def categorize_tags(self, tags: list) -> dict:
        """Returns a dict of categorized tags: {'artist': [...], 'copyright': [...], ...}"""
        result = {"artist": [], "character": [], "copyright": [], "meta": [], "general": []}
        unknown_tags = []

        # 1. Check local cache and heuristics
        for tag in tags:
            cat = self._apply_heuristics(tag)
            if cat:
                result[cat].append(tag)
                continue
                
            if tag in self.cache:
                result[self.cache[tag]].append(tag)
            else:
                unknown_tags.append(tag)

        # 2. Fetch unknown tags from Danbooru (in chunks of 100 to avoid long URLs)
        if unknown_tags:
            # We don't use an async lock here because it causes issues across different event loops
            # in multiple threads. We just fetch and then update the cache.
            # Redundant fetches for the same tags in near-simultaneous calls are acceptable.
            tags_to_fetch = []
            with self._lock:
                tags_to_fetch = [t for t in unknown_tags if t not in self.cache]
            
            if tags_to_fetch:
                await self._fetch_from_danbooru(tags_to_fetch)
            
            with self._lock:
                # Re-evaluate previously unknown tags using now-populated cache
                for tag in unknown_tags:
                    cat = self.cache.get(tag, "general") 
                    self.cache[tag] = cat 
                    result[cat].append(tag)
                self._save_cache()

        return result

    async def _fetch_from_danbooru(self, tags: list):
        chunk_size = 50
        try:
            from cloudflare_bypasser import get_session
            session = get_session("danbooru")
        except Exception:
            # Fallback to raw httpx if bypass system isn't available
            session = None

        for i in range(0, len(tags), chunk_size):
            chunk = tags[i:i + chunk_size]
            names = ",".join(chunk)
            url = f"https://danbooru.donmai.us/tags.json?search[name_comma]={names}"
            try:
                if session:
                    r = await session.get(url, headers={"User-Agent": "BooruBrowser/1.0"})
                else:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        r = await client.get(url, headers={"User-Agent": "BooruBrowser/1.0"})
                if r.status_code == 200:
                    data = r.json() if callable(getattr(r, 'json', None)) else []
                    with self._lock:
                        for item in data:
                            name = item.get("name")
                            cat_id = item.get("category", 0)
                            cat_name = CAT_MAP.get(cat_id, "general")
                            self.cache[name] = cat_name
            except Exception as e:
                print(f"[tag_categorizer] Danbooru API error: {e}")

# Global instance
categorizer = TagCategorizer()
