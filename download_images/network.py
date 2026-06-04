"""
download_images/network.py — Network infrastructure for booru API requests.

Contains:
  - CloudflareBlockError  — exception for CF challenge walls
  - NetworkManager        — per-loop semaphore for throttling concurrency
"""

import asyncio
from ui import settings_view as settings


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CloudflareBlockError                                               ║
# ║  Raised when a booru returns a Cloudflare challenge page instead    ║
# ║  of actual content. The controller catches this to prompt the user  ║
# ║  to solve the CAPTCHA via the Cloudflare bypass dialog.             ║
# ╚══════════════════════════════════════════════════════════════════════╝

class CloudflareBlockError(Exception):
    pass

class BooruAPIError(Exception):
    pass


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NetworkManager — per-loop async semaphore                          ║
# ║                                                                     ║
# ║  Limits how many concurrent HTTP requests can run at once.          ║
# ║  Each event loop gets its own semaphore so QThreads don't clash.    ║
# ║  The limit is read from settings.manager.concurrent_downloads.      ║
# ╚══════════════════════════════════════════════════════════════════════╝

class NetworkManager:
    _semaphores = {}
    _last_limit = 0

    @classmethod
    def get_semaphore(cls):
        """Get or create a semaphore for the current event loop."""
        loop = asyncio.get_running_loop()

        # Reset all semaphores if the user changed the concurrency limit
        if cls._last_limit != settings.manager.concurrent_downloads:
            cls._semaphores.clear()
            cls._last_limit = settings.manager.concurrent_downloads

        if loop not in cls._semaphores:
            cls._semaphores[loop] = asyncio.Semaphore(settings.manager.concurrent_downloads)

        return cls._semaphores[loop]

    @classmethod
    async def fetch(cls, session, url, params=None, headers=None, bypass_rate_limit=False):
        """Fetch a URL, optionally throttled by the network semaphore."""
        if settings.manager.use_network_semaphore:
            async with cls.get_semaphore():
                return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
        else:
            return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
