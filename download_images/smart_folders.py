"""
download_images/smart_folders.py — Tag-based folder organisation for downloads.

Determines which subfolder a downloaded image goes into based on its tags.
Two strategies:

  1. Adapter-first:  Danbooru and e621 APIs return pre-categorised tag fields
     (tag_string_artist, tag_string_character, etc).  If these are populated,
     the folder is named after the first artist or character tag.

  2. TagCategorizer fallback:  For boorus that only return a flat tag list
     (Gelbooru, Moebooru, etc), queries Danbooru's tag DB + local heuristics
     to sort tags into artist/character/copyright/general buckets.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("image_downloader")

# Windows MAX_PATH is 260 characters. We reserve 60 chars for the filename
# itself, leaving 200 chars for the full directory path.
_MAX_DIR_PATH = 200 if sys.platform == "win32" else 4096


def _enforce_max_path(path: Path) -> Path:
    """Truncate the final path segment if the total path length would exceed
    the Windows MAX_PATH limit. Returns the (possibly shortened) path."""
    path_str = str(path)
    if len(path_str) <= _MAX_DIR_PATH:
        return path

    # Truncate the last segment to make the path fit
    overflow = len(path_str) - _MAX_DIR_PATH
    parent = path.parent
    name = path.name
    if len(name) > overflow + 4:  # keep at least 4 chars of the name
        truncated = name[: len(name) - overflow - 1]  # -1 for safety margin
        result = parent / truncated
        log.warning(
            "[smart_folders] Path too long (%d chars), truncated '%s' → '%s'",
            len(path_str), path, result,
        )
        return result

    # Name too short to truncate meaningfully — fall back to parent
    log.warning(
        "[smart_folders] Path too long (%d chars), using parent dir instead.",
        len(path_str),
    )
    return parent


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  get_download_folder — main entry point for single-post downloads   ║
# ╚══════════════════════════════════════════════════════════════════════╝

def get_download_folder(post: dict, downloader) -> Path:
    """Return the destination folder for a single post download.

    When smart folders are enabled, categorises tags and picks a folder
    name based on artist / character / copyright.  Otherwise falls back
    to ``<download_dir>/unsorted/``.

    *downloader* is a ``BooruDownloader`` instance used for adapter
    access and tag resolution.
    """
    from ui import settings_view as settings
    from validation import validate_directory_name

    # ── Static download (default) ─────────────────────────────────
    if not settings.manager.use_smart_folders:
        path = settings.manager.get_download_dir() / "unsorted"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ── Smart folder resolution ───────────────────────────────────
    booru = post.get("_booru", settings.manager.active_booru)
    tags = downloader.get_tag_list(post)
    adapter = downloader._get_adapter_for_post(post)

    try:
        cats = _categorize_post_tags(adapter, post, tags)
    except Exception as e:
        log.warning("Tag categorization failed: %s", e)
        cats = {"artist": [], "character": [], "copyright": [], "meta": [], "general": tags}

    folder_name = _pick_folder_name(cats)

    # Heuristic fallback — join first 5 tags if no category matched
    if not folder_name and tags:
        tag_join = "_".join(tags[:5])
        if len(tag_join) > 60:
            tag_join = tag_join[:57] + "..."
        folder_name = tag_join

    # ── Sanitize and create directory ─────────────────────────────
    try:
        safe_booru = validate_directory_name(booru)
    except Exception:
        safe_booru = "unknown_booru"

    try:
        safe_name = validate_directory_name(folder_name or "unsorted")
    except Exception:
        safe_name = "unsorted"

    try:
        path = settings.manager.get_download_dir() / safe_booru / safe_name
        path = _enforce_max_path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception as e:
        log.warning("Folder creation failed for '%s': %s", safe_name, e)
        fallback = settings.manager.get_download_dir() / safe_booru
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  get_bulk_folder — folder for bulk / batch downloads                ║
# ╚══════════════════════════════════════════════════════════════════════╝

def get_bulk_folder(tags: str) -> Path:
    """Return a folder named after the search query for bulk downloads."""
    from ui import settings_view as settings
    from validation import validate_directory_name

    try:
        safe = validate_directory_name(tags.strip()) or "unsorted"
    except Exception:
        safe = "unsorted"

    path = settings.manager.get_download_dir() / settings.manager.active_booru / safe
    path = _enforce_max_path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  _categorize_post_tags — adapter-first with TagCategorizer fallback ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _categorize_post_tags(adapter, post: dict, tags: list) -> dict:
    """Return categorized tag dict: {artist: [...], character: [...], ...}

    Strategy:
      1. Ask the adapter for pre-categorized tags (instant for Danbooru/e621)
      2. If artist/character are both empty, fall back to TagCategorizer
         which queries Danbooru's tag DB + heuristics + local JSON cache
    """
    cats = adapter.get_categorized_tags(post)

    # If the adapter already gave us useful data, trust it
    if cats.get("artist") or cats.get("character"):
        return cats

    # No tags to categorize → return adapter's (empty) result
    if not tags:
        return cats

    # ── TagCategorizer fallback ───────────────────────────────────
    try:
        from tag_categorizer import get_categorizer
        cats = get_categorizer().categorize_tags(tags)
    except Exception as e:
        log.warning("TagCategorizer fallback failed: %s", e)

    return cats


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  _pick_folder_name — choose the best name from categorized tags     ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _pick_folder_name(cats: dict) -> str | None:
    """Pick the best folder name from categorized tags.

    Respects the user's preference: artist-first vs character-first.
    Falls back to copyright, then returns None for the heuristic fallback.
    """
    from ui import settings_view as settings

    if settings.manager.download_folder_use_artist_folder:
        # User prefers artist → character
        if cats.get("artist"):
            return cats["artist"][0]
        if cats.get("character"):
            return cats["character"][0]
    else:
        # Default: character → artist
        if cats.get("character"):
            return cats["character"][0]
        if cats.get("artist"):
            return cats["artist"][0]

    # Last resort before the tag-join heuristic
    if cats.get("copyright"):
        return cats["copyright"][0]

    return None
