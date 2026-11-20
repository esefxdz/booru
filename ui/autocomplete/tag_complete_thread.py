"""Background worker that fetches tag autocomplete results, cache first."""
import re
import json
import httpx
from PyQt6.QtCore import QRunnable, QObject, pyqtSignal
from storage.tag_cache import search_tags, store_tags

from core import settings
import boorus
from adapters import get_adapter


# Regex to strip JSONP callback wrappers like `jQuery123({...})`
_JSONP_RE = re.compile(r"^\s*[a-zA-Z_$][\w$]*\s*\(\s*(.*)\s*\)\s*;?\s*$", re.DOTALL)


def _strip_jsonp(text: str):
    """Try to parse as JSON; if that fails, strip a JSONP wrapper first."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = _JSONP_RE.match(text)
        if m:
            return json.loads(m.group(1))
        raise


class TagCompleteSignals(QObject):
    results_ready = pyqtSignal(list)


class TagCompleteWorker(QRunnable):
    def __init__(self, prefix):
        super().__init__()
        self._prefix = prefix
        self.signals = TagCompleteSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        site_data = boorus.REGISTRY.get(settings.manager.active_booru, {})
        adapter = get_adapter(site_data.get("api_type", "gelbooru"))
        booru_name = settings.manager.active_booru

        cached = search_tags(booru_name, self._prefix, limit=15)
        if cached and not self._is_cancelled:
            self.signals.results_ready.emit(cached)
            # Don't return — still try the network to refresh the cache
            # but if we're cancelled by then, the user already has results.

        urls = getattr(adapter, "get_tag_autocomplete_urls", lambda s, p: [])(site_data, self._prefix)
        if not urls and hasattr(adapter, "get_tag_autocomplete_url"):
            u = adapter.get_tag_autocomplete_url(site_data, self._prefix)
            if u:
                urls = [u]

        if not urls:
            if not cached and not self._is_cancelled:
                self.signals.results_ready.emit([])
            return

        try:
            results = []
            headers = settings.DEFAULT_HEADERS.copy()
            with httpx.Client(timeout=4.0, headers=headers) as c:
                for url in urls:
                    if self._is_cancelled:
                        break
                    try:
                        r = c.get(url)
                        if self._is_cancelled:
                            break
                        if r.status_code == 200:
                            data = _strip_jsonp(r.text)
                            res = adapter.parse_tag_autocomplete(data)
                            if res:
                                results = res
                                break
                    except Exception:
                        continue

            if results:
                try:
                    store_tags(booru_name, results)
                except Exception:
                    pass  # Cache write failure is non-fatal

            if not self._is_cancelled:
                if results:
                    self.signals.results_ready.emit(results)
                elif not cached:
                    self.signals.results_ready.emit([])
        except Exception:
            if not self._is_cancelled and not cached:
                self.signals.results_ready.emit([])
