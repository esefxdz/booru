from PyQt6.QtCore import QThread, pyqtSignal
import logging
import re
import httpx
from core import settings

_log = logging.getLogger(__name__)

def _cache_filename(domain):
    """Filesystem-safe cache name. A ":port" must not reach the filename: on NTFS
    "host:8080.png" is an alternate data stream of a file called "host"."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", domain) + ".png"

def _cache_dir():
    """Favicon cache directory, resolved lazily so settings are initialized first."""
    return settings.manager.get_download_dir() / ".icons"

class FaviconFetcher(QThread):
    finished = pyqtSignal(str, str)

    def __init__(self, name, url):
        super().__init__()
        self.name = name
        self.url = url

    def run(self):
        try:
            cache_dir = _cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            domain = self.url.replace("https://", "").replace("http://", "").split("/")[0]
            if not domain:
                return
            
            cache_file = cache_dir / _cache_filename(domain)

            if cache_file.exists():
                self.finished.emit(self.name, str(cache_file))
                return
            
            # Fetch through DuckDuckGo's icon service — it reliably serves .ico files
            # even for sites that don't advertise them at /favicon.ico
            resp = httpx.get(f"https://icons.duckduckgo.com/ip3/{domain}.ico", timeout=5.0)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(cache_file, "wb") as f:
                    f.write(resp.content)
                self.finished.emit(self.name, str(cache_file))
        except Exception as e:
            _log.warning("Favicon fetch failed for %s (%s): %s", self.name, self.url, e)
