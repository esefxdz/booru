"""Picks the download subfolder for a post from its tags (adapter categories first, TagCategorizer fallback)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger("image_downloader")

# Windows MAX_PATH is 260; reserve 60 for the filename.
_MAX_DIR_PATH = 200 if sys.platform == "win32" else 4096


def _enforce_max_path(path: Path) -> Path:
    """Shorten the last path segment so the path stays under the Windows limit."""
    path_str = str(path)
    if len(path_str) <= _MAX_DIR_PATH:
        return path

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

    log.warning(
        "[smart_folders] Path too long (%d chars), using parent dir instead.",
        len(path_str),
    )
    return parent


def get_download_folder(post: dict, downloader) -> Path:
    """Destination folder for one post: smart (artist/character/copyright) or ``<download_dir>/unsorted``."""
    from core import settings
    from core.validation import validate_directory_name

    if not settings.manager.use_smart_folders:
        path = settings.manager.get_download_dir() / "unsorted"
        path.mkdir(parents=True, exist_ok=True)
        return path

    booru = post.get("_booru", settings.manager.active_booru)
    tags = downloader.get_tag_list(post)
    adapter = downloader._get_adapter_for_post(post)

    try:
        cats = _categorize_post_tags(adapter, post, tags)
    except Exception as e:
        log.warning("Tag categorization failed: %s", e)
        cats = {"artist": [], "character": [], "copyright": [], "meta": [], "general": tags}

    folder_name = _pick_folder_name(cats)

    # No category matched: join the first 5 tags.
    if not folder_name and tags:
        tag_join = "_".join(tags[:5])
        if len(tag_join) > 60:
            # No "..." suffix: validate_directory_name rejects "..".
            tag_join = tag_join[:60].rstrip("._ ")
        folder_name = tag_join

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


def get_bulk_folder(tags: str) -> Path:
    from core import settings
    from core.validation import validate_directory_name

    try:
        safe = validate_directory_name(tags.strip()) or "unsorted"
    except Exception:
        safe = "unsorted"

    path = settings.manager.get_download_dir() / settings.manager.active_booru / safe
    path = _enforce_max_path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _categorize_post_tags(adapter, post: dict, tags: list) -> dict:
    """Categorised tags from the API response, else from the booru's own post page."""
    cats = adapter.get_categorized_tags(post)

    if cats.get("artist") or cats.get("character") or not tags:
        return cats

    try:
        from download_images.tag_categorizer import categorize_post
        cats = categorize_post(post)
    except Exception as e:
        log.warning("Tag categorization failed: %s", e)

    return cats


def _pick_folder_name(cats: dict) -> str | None:
    """First artist/character (order per setting), else copyright, else None."""
    from core import settings

    if settings.manager.download_folder_use_artist_folder:
        if cats.get("artist"):
            return cats["artist"][0]
        if cats.get("character"):
            return cats["character"][0]
    else:
        if cats.get("character"):
            return cats["character"][0]
        if cats.get("artist"):
            return cats["artist"][0]

    if cats.get("copyright"):
        return cats["copyright"][0]

    return None
