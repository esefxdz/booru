"""CloudflareBlockError and NetworkManager (global concurrency semaphore)."""

import asyncio
from core import settings


class CloudflareBlockError(Exception):
    pass

class BooruAPIError(Exception):
    pass


class NetworkManager:
    _semaphore: asyncio.Semaphore | None = None
    _last_limit = 0

    @classmethod
    def get_semaphore(cls):
        """Global semaphore, recreated when the limit setting changes."""
        limit = settings.manager.concurrent_downloads
        if cls._last_limit != limit or cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(limit)
            cls._last_limit = limit
        return cls._semaphore

    @classmethod
    async def fetch(cls, session, url, params=None, headers=None, bypass_rate_limit=False):
        if settings.manager.use_network_semaphore:
            async with cls.get_semaphore():
                return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
        else:
            return await session.get(url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)
