import logging
import os
import json
import asyncio
import httpx
import threading
import time
from pathlib import Path
import shutil

from ui import settings_view as settings
from ui.settings_view.manager import BASE_DIR

# ── Offline meta-tag knowledge base ──────────────────────────────────────
# These tags describe the *image itself* rather than its content and are
# categorised instantly without an API call.
_META_TAGS = {
    # Resolution / quality
    "highres", "absurdres", "incredibly_absurdres", "lowres", "bad_id",
    "bad_pixiv_id", "bad_link", "md5_mismatch", "resolution_mismatch",
    # Commentary / translation
    "commentary", "commentary_request", "english_commentary",
    "japanese_commentary", "chinese_commentary", "korean_commentary",
    "translated", "translation_request", "check_translation",
    "partially_translated", "unknown_commentary",
    # Image attributes
    "monochrome", "greyscale", "grayscale", "sepia",
    "wide_image", "tall_image", "border", "framed", "censored",
    "mosaic_censoring", "bar_censoring", "heart_censoring",
    "no_censoring", "uncensored", "partially_censored",
    # Artist / source
    "commission", "sketch", "rough", "doodle", "lineart", "flat_color",
    "colored_sketch", "finished", "work_in_progress", "wip",
    "pixiv_request", "fanbox_reward", "patreon_reward",
    "artist_request", "artist_self-portrait", "self-portrait",
    # Style / medium
    "traditional_media", "digital_media", "3d", "2d", "cg",
    "vector", "pixel_art", "voxel", "photograph", "cosplay",
    "oil_painting", "watercolor", "acrylic", "pencil",
    "marker", "pen", "crayon", "pastel", "chalk",
    # Post metadata
    "animated", "animated_gif", "animated_png", "video", "webm",
    "sound", "no_sound", "loop", "short_video",
    "long_image", "vertical_image", "horizontal_image",
    "panorama", "comic", "manga", "4koma", "multi-panel",
    "howto", "tutorial", "reference_sheet", "character_sheet",
    "model_sheet", "expression_sheet", "turnaround",
    # Content flags
    "safe", "questionable", "explicit", "rating:safe",
    "rating:questionable", "rating:explicit",
    "solo", "duo", "trio", "group", "multiple_boys", "multiple_girls",
    # Generation / AI
    "ai-generated", "ai_assisted", "ai_upscaled", "novelai",
    "stable_diffusion", "midjourney", "dalle", "nai_diffusion",
    # Common technical
    "signature", "watermark", "dated", "date", "year",
    "outside_border", "cropped", "scan", "screencap", "screenshot",
    "official_art", "fan_art", "redraw", "trace", "edit",
    "original", "parody", "alternate_version", "variant",
    "icon", "avatar", "wallpaper", "cover_art", "album_art",
}

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
        self.cache_file = BASE_DIR / "tag_cache.json"
        self._legacy_cache_file = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "tag_cache.json"
        self.cache = {}
        self._load_cache()
        self._lock = threading.Lock()
        self._fetch_lock = threading.Lock()
        
    def _load_cache(self):
        if not self.cache_file.exists() and self._legacy_cache_file.exists():
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self._legacy_cache_file, self.cache_file)
                self._legacy_cache_file.unlink(missing_ok=True)
                logging.info("[categorizer] Migrated tag_cache.json from %%APPDATA%%")
            except Exception as e:
                logging.warning("[categorizer] Could not migrate legacy tag_cache.json: %s", e)

        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception as e:
                logging.error(f"[tag_categorizer] Failed to load cache: {e}")

    def _save_cache(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
        except Exception as e:
            logging.error(f"[tag_categorizer] Failed to save cache: {e}")

    def _apply_heuristics(self, tag: str):
        """Apply offline heuristics to categorise a tag.

        These run BEFORE any API call so that common tags are categorised
        instantly even when the Danbooru API is unreachable.
        """
        t = tag.lower()

        # ── Danbooru-style suffixes ───────────────────────────────
        if t.endswith("_(artist)"):   return "artist"
        if t.endswith("_(copyright)"): return "copyright"
        if t.endswith("_(character)"): return "character"
        if t.endswith("_(cosplay)"):  return "meta"
        if t.endswith("_(style)"):    return "meta"
        if t.endswith("_(medium)"):   return "meta"

        # ── Known meta / technical tags ────────────────────────────
        if t in _META_TAGS:
            return "meta"

        # ── Artist markers (Pixiv / Twitter / etc.) ────────────────
        if t.endswith("_(pixiv)") or t.endswith("_(twitter)"):
            return "artist"
        if t.startswith("pixiv_") and t[6:].isdigit():
            return "artist"

        return None

    def categorize_tags(self, tags: list) -> dict:
        """Returns a dict of categorized tags: {'artist': [...], 'copyright': [...], ...}"""
        result = {"artist": [], "character": [], "copyright": [], "meta": [], "general": []}
        unknown_tags = []

        # 1. Check local cache and heuristics
        for tag in tags:
            cache_key = tag.replace(" ", "_").lower()
            cat = self._apply_heuristics(cache_key)
            if cat:
                result[cat].append(tag)
                continue
                
            if cache_key in self.cache:
                result[self.cache[cache_key]].append(tag)
            else:
                unknown_tags.append(tag)

        # 2. Fetch unknown tags from Danbooru (in chunks of 100 to avoid long URLs)
        if unknown_tags:
            # We don't use an async lock here because it causes issues across different event loops
            # in multiple threads. We just fetch and then update the cache.
            # Redundant fetches for the same tags in near-simultaneous calls are acceptable.
            tags_to_fetch = []
            with self._lock:
                tags_to_fetch = [t for t in unknown_tags if t.replace(" ", "_").lower() not in self.cache]
            
            if tags_to_fetch:
                self._fetch_from_danbooru(tags_to_fetch)
            
            with self._lock:
                # Re-evaluate previously unknown tags using now-populated cache
                for tag in unknown_tags:
                    cache_key = tag.replace(" ", "_").lower()
                    cat = self.cache.get(cache_key, "general") 
                    self.cache[cache_key] = cat 
                    result[cat].append(tag)
                self._save_cache()

        return result

    def _fetch_from_danbooru(self, tags: list):
        # Circuit breaker: if Danbooru was blocked recently, skip straight to e621.
        now = time.monotonic()
        if now - getattr(self, '_danbooru_blocked_until', 0) < 300:
            self._fetch_from_e621(tags)
            return

        chunk_size = 50
        resolved = set()
        blocked = False

        for i in range(0, len(tags), chunk_size):
            # If the first chunk confirmed we're blocked, stop immediately
            if blocked:
                break
            chunk = tags[i:i + chunk_size]
            chunk_query = [t.replace(" ", "_").lower() for t in chunk]
            import urllib.parse
            names = urllib.parse.quote(",".join(chunk_query))
            url = f"https://danbooru.donmai.us/tags.json?search[name_comma]={names}"
            try:
                with self._fetch_lock:
                    r = httpx.get(
                        url,
                        headers={"User-Agent": "BooruBrowser/1.0"},
                        timeout=8.0,
                    )
                if r.status_code == 200:
                    data = r.json() if callable(getattr(r, 'json', None)) else []
                    with self._lock:
                        for item in data:
                            name = item.get("name")
                            if name:
                                cache_key = name.lower()
                                cat_id = item.get("category", 0)
                                self.cache[cache_key] = CAT_MAP.get(cat_id, "general")
                                resolved.add(cache_key)
                elif r.status_code in (403, 503):
                    # Cloudflare or server block — circuit-break for 5 minutes
                    blocked = True
                    self._danbooru_blocked_until = now + 300
            except Exception:
                # Network error — don't retry other chunks
                blocked = True

        # Fallback: e621 for anything not resolved
        remaining = [t for t in tags if t.replace(" ", "_").lower() not in resolved]
        if remaining:
            self._fetch_from_e621(remaining)

    def _fetch_from_e621(self, tags: list):
        """Fallback categorisation via e621's tag API."""
        chunk_size = 50
        for i in range(0, len(tags), chunk_size):
            chunk = tags[i:i + chunk_size]
            chunk_query = [t.replace(" ", "_").lower() for t in chunk]
            import urllib.parse
            names = urllib.parse.quote(",".join(chunk_query))
            url = f"https://e621.net/tags.json?search[name_comma]={names}&limit={len(chunk)}"
            try:
                r = httpx.get(
                    url,
                    headers={"User-Agent": "BooruBrowser/1.0"},
                    timeout=10.0,
                )
                if r.status_code == 200:
                    data = r.json() if callable(getattr(r, 'json', None)) else []
                    with self._lock:
                        for item in data:
                            name = item.get("name")
                            if name:
                                cache_key = name.lower()
                                cat_id = item.get("category", 0)
                                self.cache[cache_key] = CAT_MAP.get(cat_id, "general")
            except Exception as e:
                logging.debug("[tag_categorizer] e621 fallback error: %s", e)

# Global instance — lazily created to avoid import-time filesystem access
_categorizer = None

def get_categorizer():
    global _categorizer
    if _categorizer is None:
        _categorizer = TagCategorizer()
    return _categorizer

