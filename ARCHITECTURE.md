# Architecture of BooruBrowser

## Overview

BooruBrowser is a Windows desktop booru browser built with PyQt6. It searches,
browses and downloads posts from booru sites while handling Cloudflare
protection. It ships with two built-in sites (Gelbooru, Safebooru); any site
running one of the nine supported engines can be added from the UI.

## Directory Map

```
booru/
├── main.py                  Entry point: logging, crash handler, starts the window
│
├── core/                    App-wide plumbing (no Qt)
│   ├── settings.py          Settings manager (settings.json) + defaults
│   ├── credentials.py       DPAPI-encrypted credentials.v2.bin (keys, tokens, cookies)
│   ├── app_paths.py         Where user data lives (portable / %LOCALAPPDATA% / override)
│   ├── validation.py        Guards for server-supplied URLs, paths, cookies; log redaction
│   ├── async_loop.py        Shared asyncio event loop (submit() / run())
│   └── fileutil.py          atomic_write_text
│
├── storage/                 Local databases and caches
│   ├── thumb_cache.py       Two-tier thumbnail cache (memory LRU + SQLite)
│   ├── bookmarks_db.py      Bookmarks (SQLite)
│   └── tag_cache.py         Autocomplete tag cache
│
├── cloudflare_bypasser/     HTTP engine chain + Cloudflare handling
│   ├── __init__.py          get_session(): per-booru session cache
│   ├── session.py           BypassSession: engine failover, retries, cookie scoping
│   ├── circuit_breaker.py   Pause a host after a Cloudflare block
│   ├── file_download.py     BypassSession.download_sync (stream to file)
│   ├── engines.py           curl_cffi / cloudscraper / httpx / requests / urllib
│   ├── fingerprint.py       Browser identity, headers, engine order
│   └── store.py             Per-booru cookie/UA persistence
│
├── adapters/                One adapter per booru API type (gelbooru, danbooru, e621, ...)
├── boorus/                  Booru registry: built-ins + custom_boorus.json, validated
│
├── download_images/         Search + download pipeline
│   ├── booru_client.py      BooruDownloader: what the UI calls
│   ├── api_client.py        search_posts(): API query, 401 retry, CF detection
│   ├── network.py           Request semaphore, CloudflareBlockError
│   ├── thumbnails.py        Thumbnail prefetch with cancellation
│   ├── thumb_client.py      Persistent httpx client for thumbnails
│   ├── image_downloader.py  Single-post download (.part + rename)
│   ├── engines.py           Download engines
│   ├── smart_folders.py     Organize downloads by artist/character
│   └── tag_categorizer.py   Tag categories via Danbooru (cached)
│
├── ui/                      PyQt6 interface (to be replaced by Flutter later)
│   ├── main_window.py       Main window, menus, signal wiring
│   ├── controller.py        Background threads (fetch, bulk download)
│   ├── gallery/             Virtualized thumbnail grid
│   ├── viewer/              Post viewer: image, video, tags, details
│   ├── views/               Pages: favorites, blacklist, downloads, API settings
│   ├── widgets/             Sidebar, tag panel, chips, text bar, navigation
│   ├── settings_view/       Settings page sections
│   ├── browser_dialog/      Embedded Chromium for CAPTCHA and logins
│   ├── search_bar/, autocomplete/, server_bar/, modals/, animations/
│   ├── style/               Colors and icons
│   └── assets/              theme.qss, app icon
│
├── updater/                 Checks GitHub releases (notify only, never downloads)
└── tests/                   pytest suite (offline; `pytest` from the repo root)
```

## User data

It lives next to the exe (or the repo root when running from source), so the
folder is portable. If that folder is not writable or is a temporary folder
(e.g. run from inside a zip), it goes to `%LOCALAPPDATA%\BooruBrowser`. The
`BOORUBROWSER_DATA_DIR` environment variable overrides both (the test suite
uses it).

| File | Contents |
|---|---|
| `settings.json` | Preferences (no secrets) |
| `credentials.v2.bin` | API keys, auth tokens, CF/session cookies. DPAPI-encrypted: tied to the Windows account, so logins must be re-entered on another PC |
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
  `core.validation.safe_media_path()` (id sanitised, extension allow-listed, final
  path asserted to stay inside the target folder).
- **URL schemes:** server URLs are resolved against the booru and must be
  http(s) (`require_http_url`), checked in the URL getters and again in
  `BypassSession.get/get_sync`.
- **Cookies** are stored without a domain, so they are only attached to URLs
  on the booru's registrable domain (`core.validation.same_site`). This applies in
  BypassSession, the thumbnail client, downloads, and on urllib redirects.
- **TLS** is always verified; there is no insecure retry.
- **Proxy:** when set, API searches, thumbnails, viewer media and downloads
  use it. Some helpers still connect directly (see Known gaps).

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
background thread, managed by `core/async_loop.py`. Qt code schedules work with
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
  → ui.browser_dialog.run_cf_bypass()
    → CloudflareAutoSolver (hidden browser, 30s timeout)
      → success: cookies saved, session invalidated, re-fetch
      → timeout: CloudflareBrowserDialog (visible, manual solve or cookie paste)
```

### Download
```
download_post()
  → BooruDownloader.get_file_url()      (resolved, http(s) only)
  → smart_folders.get_download_folder()
  → core.validation.safe_media_path()
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
- These connect directly and ignore the proxy setting: tag categorizer
  (Danbooru), tag autocomplete, add-booru auto-detect, favicon fetcher
  (sends each booru's domain to icons.duckduckgo.com), update checker
  (GitHub), session login, and the embedded WebEngine browser.
- `core.validation.same_site` uses a small heuristic, not the Public Suffix List:
  two sites on a shared host such as `*.github.io` count as the same site.
