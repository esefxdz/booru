"""
download_images/network.py — Network infrastructure for booru API requests.

Contains:
  - CloudflareBlockError  — exception for CF challenge walls
  - NetworkManager        — global semaphore for throttling concurrency
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
# ║  NetworkManager — global async semaphore                            ║
# ║                                                                     ║
# ║  Limits how many concurrent HTTP requests can run at once.          ║
# ║  All async work shares the global event loop from async_loop.py,    ║
# ║  so a single semaphore is sufficient.                               ║
# ║  The limit is read from settings.manager.concurrent_downloads.      ║
# ╚══════════════════════════════════════════════════════════════════════╝

class NetworkManager:
    _semaphore: asyncio.Semaphore | None = None
    _last_limit = 0

    @classmethod
    def get_semaphore(cls):
        """Get or create the global semaphore, recreated on limit changes."""
        limit = settings.manager.concurrent_downloads
        if cls._last_limit != limit or cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(limit)
            cls._last_limit = limit
        return cls._semaphore

    @classmethod
    async def fetch(cls, session, url, params=None, headers=None, bypass_rate_limit=False):
        """Fetch a URL, optionally throttled by the network semaphore."""
        if settings.manager.use_network_semaphore:
            async with cls.get_semaphore():
                return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
        else:
            return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
