from PyQt6.QtCore import QThread, pyqtSignal
import httpx
from ui import settings_view as settings

# The favicon cache lives next to the downloads folder, in a hidden .icons subfolder.
# This avoids hitting the network every time the app launches.
CACHE_DIR = settings.manager.get_download_dir() / ".icons"

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                      CLASS: FaviconFetcher                          ║
# ║  Background thread — downloads the site favicon from DuckDuckGo's  ║
# ║  icon proxy so we never request the booru site directly.            ║
# ╚══════════════════════════════════════════════════════════════════════╝
class FaviconFetcher(QThread):
    # Signal emits (booru_name, local_file_path) when download completes
    finished = pyqtSignal(str, str)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — stores the booru name and its base URL             │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, name, url):
        super().__init__()
        self.name = name
        self.url = url

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  run  — does the actual network request on a background thread   │
    # │  Strips https:// to get the bare domain, then checks disk cache  │
    # │  before hitting the DuckDuckGo favicon proxy.                    │
    # └──────────────────────────────────────────────────────────────────┘
    def run(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # Extract just "danbooru.donmai.us" from "https://danbooru.donmai.us"
            domain = self.url.replace("https://", "").replace("http://", "").split("/")[0]
            if not domain:
                return
            
            cache_file = CACHE_DIR / f"{domain}.png"

            # If we already downloaded this favicon before, emit from cache immediately
            if cache_file.exists():
                self.finished.emit(self.name, str(cache_file))
                return
            
            # Fetch through DuckDuckGo's icon service — it reliably serves .ico files
            # even for sites that don't advertise them at /favicon.ico
            resp = httpx.get(f"https://icons.duckduckgo.com/ip3/{domain}.ico", timeout=5.0)
            # Only save if we got a real image back (not an empty 404 response)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(cache_file, "wb") as f:
                    f.write(resp.content)
                self.finished.emit(self.name, str(cache_file))
        except Exception:
            # Silently fail — missing favicons just show the default box icon
            pass
