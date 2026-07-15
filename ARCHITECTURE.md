# Architecture of BooruBrowser

## Overview

BooruBrowser is a desktop booru image browser built with PyQt6. It searches, browses, and downloads images from 15+ booru sites (Danbooru, Gelbooru, e621, etc.) while transparently handling Cloudflare protection.

## Directory Map

```
booru/
├── main.py                  Entry point, logging, crash handler
├── gui.py                   Main window, menu bar, signal wiring
├── controller.py            Background threads (fetch, bulk download), cancellation
├── async_loop.py            Shared asyncio event loop for all async work
├── credentials.py           Keyring-based secure credential storage
├── thumb_cache.py           Two-tier thumbnail cache (L1 LRU memory + L2 SQLite)
├── validation.py            Input validation (search terms, URLs)
├── tag_categorizer.py       Tag categorization via Danbooru API (cached)
├── generate_boorus.py       One-shot scaffold: writes booru config files
├── replace_print.py         Redirects print() to logging
│
├── cloudflare_bypasser/     ** CF bypass engine (the hard part) **
│   ├── __init__.py          Public API, session cache, fingerprint-based invalidation
│   ├── session.py           BypassSession orchestrator: multi-engine failover + retry
│   ├── engines.py           Engine implementations + BypassResponse wrapper
│   ├── fingerprint.py       Browser identity, headers, engine registry
│   └── store.py             Per-booru cookie/UA persistence
│
├── adapters/                Per-API-type adapter classes
│   ├── base.py              BaseAdapter + NormalizedPost dataclass
│   ├── danbooru.py, gelbooru.py, moebooru.py, e621.py, ...
│   └── session_login.py     Session cookie login for Danbooru Gold accounts
│
├── boorus/                  Auto-generated per-site config files
│   ├── danbooru.py, gelbooru.py, safebooru.py, ...
│   └── __init__.py          Registry: {name: {url, api_type, ...}}
│
├── download_images/         Image search + download pipeline
│   ├── booru_client.py      BooruDownloader: thin composition layer
│   ├── api_client.py        search_posts(): API query with CF detection
│   ├── network.py           NetworkManager, CloudflareBlockError
│   ├── thumbnails.py        Thumbnail prefetch with cancellation
│   ├── image_downloader.py  Single-post download with progress
│   ├── thumb_client.py      Lightweight thumbnail HTTP client
│   └── smart_folders.py     Organize downloads by artist/character
│
├── displayers/              Post display widgets
│   ├── media_viewer.py      Full-res image/video viewer overlay
│   ├── video_player.py      MPV/libVLC video playback
│   ├── sidebar.py           Post info sidebar (tags, stats, bookmark)
│   ├── overlay.py           Hover overlay with quick actions
│   ├── post_displayer_tags.py  Clickable tag chips with categorization
│   └── ...
│
├── ui/                      Everything UI
│   ├── gallery.py           Virtualized scrolling gallery
│   ├── gallery_layout.py    Layout manager for the gallery grid
│   ├── tile_pool.py         Pool of reusable tile widgets
│   ├── search_bar/          Search bar with autocomplete
│   ├── server_bar/          Booru switcher sidebar
│   ├── settings_view/       Settings dialog with sections
│   ├── browser_dialog/      Embedded Chromium for CF bypass + login
│   ├── bookmarks_main/      Bookmark database + UI
│   ├── modals/              Dialogs (add booru, bulk download)
│   ├── autocomplete/        Tag autocomplete engine
│   └── ...
│
└── tests/                   Unit tests
    ├── test_bypass_response.py
    ├── test_bypass_store.py
    ├── test_session_fingerprint.py
    └── test_cookie_extraction.py
```

## Key Architectural Decisions

### 1. Multi-engine Cloudflare bypass with automatic failover

The app tries to fetch every URL through a cascade of HTTP engines:

```
curl_cffi → cloudscraper → httpx → requests → urllib
```

Each engine adds a different level of browser impersonation. `curl_cffi` mimics Chrome's TLS fingerprint (beating JA3 detection). `cloudscraper` solves JS challenges. `urllib` is the always-available stdlib fallback.

When all lightweight engines fail (403), the app falls back to an embedded **Chromium browser** (`QWebEngineView`) that can solve Turnstile/CAPTCHA challenges with user interaction.

### 2. Session cache with fingerprint-based invalidation

`BypassSession` instances are cached per booru. The cache key is a "fingerprint" of cookies + User-Agent + proxy + bypass method. When any of these change (e.g., after solving a CAPTCHA), the fingerprint mismatches and a fresh session replaces the old one automatically. This prevents stale sessions while avoiding expensive TLS handshakes on every request.

### 3. Two-tier thumbnail cache

- **L1**: In-memory LRU cache (default 64 MB). Instant hits, no disk I/O.
- **L2**: SQLite on disk with WAL mode (default 500 MB). Persistent across restarts. Batch eviction of oldest 10% when over limit.

Both tiers use byte-level accounting and are thread-safe.

### 4. Adapter pattern for multi-site support

Each booru API type (Danbooru, Gelbooru, Moebooru, e621, etc.) has an adapter class implementing `BaseAdapter`. The adapter handles URL construction, parameter building, response parsing, and tag extraction. Adding a new booru type means writing one ~80-line adapter.

### 5. Shared asyncio event loop

All async work (HTTP requests, thumbnail downloads, warmup) runs on a single shared event loop managed by `async_loop.py`. The Qt main thread schedules async work via `async_run()` which bridges the Qt and asyncio event loops.

### 6. Virtualized scrolling gallery

The gallery uses a tile pool pattern: only visible tiles (+ a small buffer) are rendered. As the user scrolls, tiles are recycled. This keeps memory constant regardless of how many posts are loaded.

### 7. Per-booru isolated browser profiles

The embedded Chromium browser uses `QWebEngineProfile` instances named per booru (`cf_bypass_danbooru`, `cf_bypass_gelbooru`, etc.). This prevents cookie bleed between sites and gives each booru its own localStorage/cookie jar.

## Data Flow

### Search flow
```
User types tags → SearchBar → AppController.fetch() → FetchThread.run()
  → BooruDownloader.search_posts()
    → api_client.search_posts()
      → adapter.build_url() / build_params()
      → BypassSession.get() (multi-engine)
      → adapter.parse_response()
    → thumbnails.fetch_previews()
  → gallery.display()
```

### Cloudflare bypass flow
```
BypassSession.get() → all engines 403
  → CloudflareBlockError raised
  → AppController → cf_blocked signal
  → gui.run_cf_bypass()
    → CloudflareAutoSolver (hidden browser, 30s timeout)
      → on success: cookies saved, session invalidated, re-fetch
      → on timeout: CloudflareBrowserDialog (visible manual CAPTCHA)
```

### Download flow
```
User clicks download → download_post()
  → resolve file_url via adapter
  → NetworkManager.download() with progress callbacks
  → smart_folders determine target directory
```

## Dependencies

| Dependency | Why |
|---|---|
| PyQt6 + PyQt6-WebEngine | GUI + embedded Chromium for CF bypass |
| curl_cffi | TLS fingerprint impersonation (optional, falls back) |
| cloudscraper | JS challenge solver (optional, falls back) |
| httpx | HTTP/2 modern client (optional, falls back) |
| requests | Battle-tested HTTP (optional, falls back) |
| keyring | Secure credential storage |

All optional engine dependencies fall back gracefully — the app works with just PyQt6 + stdlib.
