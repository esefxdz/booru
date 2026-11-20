import json
import logging
import shutil
import threading

from core.fileutil import atomic_write_text

from core.app_paths import legacy_appdata_dir
from core.settings import BASE_DIR

# Tags about the image itself; categorised without an API call.
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

_EMPTY = ("artist", "character", "copyright", "meta", "general")


class TagCategorizer:
    """Tag -> category cache (tag_cache.json) plus offline rules. Makes no requests."""

    def __init__(self):
        self.cache_file = BASE_DIR / "tag_cache.json"
        self._legacy_cache_file = legacy_appdata_dir() / "tag_cache.json"
        self.cache = {}
        self._load_cache()
        self._lock = threading.Lock()

    def _load_cache(self):
        if not self.cache_file.exists() and self._legacy_cache_file.exists():
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self._legacy_cache_file, self.cache_file)   # copy, keep the original
                logging.info("[categorizer] Copied tag_cache.json from %APPDATA% (original kept)")
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
            atomic_write_text(self.cache_file, json.dumps(self.cache))
        except Exception as e:
            logging.error(f"[tag_categorizer] Failed to save cache: {e}")

    def _apply_heuristics(self, tag: str):
        """Offline guess for *tag*, or None."""
        t = tag.lower()

        if t.endswith("_(artist)"):   return "artist"
        if t.endswith("_(copyright)"): return "copyright"
        if t.endswith("_(character)"): return "character"
        if t.endswith("_(cosplay)"):  return "meta"
        if t.endswith("_(style)"):    return "meta"
        if t.endswith("_(medium)"):   return "meta"

        if t in _META_TAGS:
            return "meta"

        if t.endswith("_(pixiv)") or t.endswith("_(twitter)"):
            return "artist"
        if t.startswith("pixiv_") and t[6:].isdigit():
            return "artist"

        return None

    @staticmethod
    def _key(tag: str) -> str:
        return tag.replace(" ", "_").lower()

    def _category(self, tag: str):
        key = self._key(tag)
        return self.cache.get(key) or self._apply_heuristics(key)  # the booru beats the guesses

    def has_unknown(self, tags: list) -> bool:
        return any(self._category(t) is None for t in tags)

    def learn(self, mapping: dict) -> None:
        """Remember {tag: category} pairs read from a booru and save them."""
        if not mapping:
            return
        with self._lock:
            self.cache.update({self._key(k): v for k, v in mapping.items() if v in _EMPTY})
            self._save_cache()

    def categorize_tags(self, tags: list) -> dict:
        """Return {category: [tags]}; tags with no known category go under general."""
        result = {c: [] for c in _EMPTY}
        for tag in tags:
            result[self._category(tag) or "general"].append(tag)
        return result


def categorize_post(post: dict) -> dict:
    """Categorised tags for *post*: from the API response if it has them, else
    from the booru's own post page (cached per tag). Blocking: call off the GUI thread."""
    import boorus
    from adapters import get_adapter
    from core import settings

    booru = post.get("_booru") or settings.manager.active_booru
    site = boorus.REGISTRY.get(booru, {})
    adapter = get_adapter(site.get("api_type", "gelbooru"))

    cats = adapter.get_categorized_tags(post)
    if any(cats.get(c) for c in ("artist", "character", "copyright", "meta")):
        return cats

    tags = adapter.get_tags(post)
    categorizer = get_categorizer()
    url = adapter.tag_types_url(post, site) if categorizer.has_unknown(tags) else ""
    if url:
        try:
            from cloudflare_bypasser import get_session
            r = get_session(booru).get_sync(url, timeout=15)
            if r.status_code == 200:
                categorizer.learn(adapter.parse_tag_types(r.text))
        except Exception as e:
            logging.warning("[tag_categorizer] tag lookup on %s failed: %s", booru, e)
    return categorizer.categorize_tags(tags)


# Created lazily to avoid filesystem access at import.
_categorizer = None


def get_categorizer():
    global _categorizer
    if _categorizer is None:
        _categorizer = TagCategorizer()
    return _categorizer
