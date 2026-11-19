# Architecture of BooruBrowser

## Overview

BooruBrowser is a Windows desktop booru browser built with PyQt6. It searches,
browses and downloads posts from booru sites while handling Cloudflare
protection. It ships with two built-in sites (Gelbooru, Safebooru); any site
running one of the nine supported engines can be added from the UI.

## Directory Map

```
booru/
├── main.py                  Entry point, logging, crash handler
├── gui.py                   Main window, menu bar, signal wiring
├── controller.py            Background threads (fetch, bulk download), cancellation
├── async_loop.py            Shared asyncio event loop (submit() / run())
├── credentials.py           DPAPI-encrypted credentials.bin (keys, tokens, bypass cookies)
├── thumb_cache.py           Two-tier thumbnail cache (L1 LRU memory + L2 SQLite)
├── validation.py            Input validation + guards for server-supplied data
├── tag_categorizer.py       Tag categorization via Danbooru API (cached)
│
├── cloudflare_bypasser/     ** CF bypass engine (the hard part) **
│   ├── __init__.py          get_session(): per-booru session cache, fingerprint invalidation
│   ├── session.py           BypassSession: multi-engine failover, retry, cookie scoping
│   ├── engines.py           Engine implementations + BypassResponse wrapper
│   ├── fingerprint.py       Browser identity, headers, engine order
│   └── store.py             Per-booru cookie/UA persistence
│
├── adapters/                Per-API-type adapter classes
│   ├── base.py              BaseAdapter + NormalizedPost dataclass
│   ├── gelbooru.py, danbooru.py, moebooru.py, e621.py, szurubooru.py,
│   ├── philomena.py, shimmie2.py, zerochan.py, html_scraper.py
│   └── session_login.py     Session-cookie login helpers (Danbooru Gold etc.)
│
├── boorus/__init__.py       Booru registry: built-ins + custom_boorus.json, validated
│
├── download_images/         Search + download pipeline
│   ├── booru_client.py      BooruDownloader: composition layer, safe URL getters
│   ├── api_client.py        search_posts(): API query, 401 retry, CF detection
│   ├── network.py           NetworkManager (semaphore), CloudflareBlockError
│   ├── thumbnails.py        Thumbnail prefetch with cancellation
│   ├── thumb_client.py      Lightweight persistent httpx client for thumbnails
│   ├── image_downloader.py  Single-post download (.part + rename)
│   ├── engines.py           Download engines: urllib, requests, httpx, curl_cffi
│   └── smart_folders.py     Organize downloads by artist/character
│
├── displayers/              Post display widgets (viewer, video player, sidebar, tags)
├── ui/                      Everything else UI (gallery, search, settings, browser dialogs)
├── updater/                 Checks GitHub releases (notify only, never downloads)
│
└── tests/                   pytest suite (offline; `pytest` from the repo root)
```

## User data

All of it lives next to the exe (or the repo root when running from source),
so the folder is portable:

| File | Contents |
|---|---|
| `settings.json` | Preferences (no secrets) |
| `credentials.bin` | API keys, auth tokens, CF/session cookies. DPAPI-encrypted: tied to the Windows account, so logins must be re-entered on another PC |
| `custom_boorus.json` | Added boorus, engine overrides, removed built-ins |
| `bookmarks.db`, `tag_cache.db`, `thumb_cache/` | Bookmarks and caches |

## Security boundaries

Booru servers are treated as untrusted: a compromised or malicious site
controls every field of its API responses.

- **Booru registry is data, never code.** Entries are validated (name, http(s)
  URL without quotes/credentials, API path charset, known engine) on add,
  save and load. Older versions generated `.py` files; those are migrated once
  by parsing with `ast`, never imported.
- **Paths:** post ids and file extensions from the server go through
  `validation.safe_media_path()` (id sanitised, extension allow-listed, final
  path asserted to stay inside the target folder).
- **URL schemes:** server URLs are resolved against the booru and must be
  http(s) (`require_http_url`), checked in the URL getters and again in
  `BypassSession.get/get_sync`.
- **Cookies** are stored without a domain, so they are only attached to URLs
  on the booru's registrable domain (`validation.same_site`). This applies in
  BypassSession, the thumbnail client, downloads, and on urllib redirects.
- **TLS** is always verified; there is no insecure retry.
- **Proxy:** when set, API requests, thumbnails and downloads all use it.

## Key Architectural Decisions

### 1. Multi-engine Cloudflare bypass with automatic failover

API requests go through a cascade of HTTP engines:

```
curl_cffi → cloudscraper → httpx → requests → urllib
```

`curl_cffi` mimics Chrome's TLS fingerprint (beating JA3 detection),
`cloudscraper` handles some JS challenges, and `urllib` is the stdlib
fallback. In auto mode the last engine that worked is tried first.

When every engine is blocked, the app falls back to an embedded **Chromium
browser** (`QWebEngineView`): first a hidden auto-solver, then a visible
window where the user solves the challenge. The resulting cookies + exact
User-Agent are saved per booru.

### 2. Session cache with fingerprint-based invalidation

`BypassSession` instances are cached per booru. The cache key covers
cookies, User-Agent, proxy, bypass method and the booru URL. When any of these
change (e.g. after solving a CAPTCHA) the next `get_session()` builds a fresh
session.

### 3. Two-tier thumbnail cache

- **L1**: in-memory LRU (default 64 MB).
- **L2**: SQLite on disk with WAL mode (default 500 MB), evicting the oldest
  10% when over the limit.

### 4. Adapter pattern for multi-site support

Each booru API type has an adapter implementing `BaseAdapter`: URL
construction, params, response parsing and tag extraction. Adding a new
engine type means writing one ~80-line adapter and registering it in
`adapters/__init__.py`.

### 5. Shared asyncio event loop

Async work (HTTP requests, thumbnails, warmup) runs on one event loop in a
background thread, managed by `async_loop.py`. Qt code schedules work with
`async_loop.submit(coro)` (returns a `concurrent.futures.Future`) or blocks
with `async_loop.run(coro)`.

### 6. Virtualized scrolling gallery

Only visible tiles (plus a small buffer) are rendered and recycled from a
pool as the user scrolls, so memory stays flat however many posts load.

### 7. Per-booru isolated browser profiles

The embedded browser uses a `QWebEngineProfile` per booru
(`cf_bypass_<name>`), so cookies and storage never bleed between sites.

## Data Flow

### Search
```
SearchBar → AppController.fetch() → FetchThread.run()
  → BooruDownloader.get_image_urls()
    → api_client.search_posts()
      → adapter.build_url() / build_params()
      → BypassSession.get()        (engine failover, scoped cookies)
      → adapter.parse_response()   (non-object entries dropped)
    → thumbnails.fetch_previews()  (thumb_client first, BypassSession fallback)
  → gallery.display()
```

### Cloudflare bypass
```
BypassSession.get() → every engine blocked
  → CloudflareBlockError → AppController cf_blocked signal
  → gui.run_cf_bypass()
    → CloudflareAutoSolver (hidden browser, 30s timeout)
      → success: cookies saved, session invalidated, re-fetch
      → timeout: CloudflareBrowserDialog (visible, manual solve or cookie paste)
```

### Download
```
download_post()
  → BooruDownloader.get_file_url()      (resolved, http(s) only)
  → smart_folders.get_download_folder()
  → validation.safe_media_path()
  → engine (urllib by default) → <name>.part → rename on success
```

## Dependencies

| Dependency | Why |
|---|---|
| PyQt6 + PyQt6-WebEngine | GUI + embedded Chromium for CF solving and logins |
| Pillow | Image handling |
| httpx[http2] | Thumbnail client, HTTP/2, bypass engine |
| requests | Bypass and download engine |
| curl_cffi | Chrome TLS impersonation (best Cloudflare results) |
| cloudscraper | JS-challenge engine in the bypass chain |
| python-mpv / python-vlc | Optional video backends |

Engines whose library is missing are skipped; urllib always works.

## Known gaps

- `session_keys` (session-cookie logins) are captured and stored but not yet
  attached to any request.
- Responses and downloads have no size cap.
- Smart folders send tag names to Danbooru's API for categorisation, even
  when browsing another site.
