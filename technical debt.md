# Booru Browser - Technical Debt & Critique (Production Readiness)

Below is a comprehensive audit of the application's readiness for a 1M user release. **Brutal honesty:** The current architecture will *not* survive mass adoption without severe performance bottlenecks, memory leaks, and user complaints. It works as a prototype, but you have critical engineering flaws that need immediate addressing.

The issues are ranked from **CRITICAL** (app will crash or become unusable) to **LOW** (code quality and DX).

---

## ~~1. CRITICAL: Memory Leaks (Fake Infinite Scroll)~~ ✅ FIXED
~~Your `Gallery` infinite scroll is implemented by just appending more images (`trigger_fetch_append`).~~
- **The Problem:** ~~You are not using a *virtualized* list/masonry grid. If a user scrolls through 50 pages (2500 images), the UI will keep all 2500 `QPixmaps` and layout widgets in memory. Python and PyQt will consume Gigabytes of RAM and eventually crash (OOM).~~
- **The Fix:** ~~You *must* implement view virtualization. Only render the images currently visible on screen (plus a small buffer above/below). When items scroll out of view, replace them with empty placeholders or remove them from the layout entirely.~~
- **Resolution:** Replaced broken Structural Virtualization (150-widget pool) with **Resource Virtualization** in `ui/gallery.py`:
  1. **Permanent widgets** — each post gets its own `QPushButton` + star button, created once in `prepare_skeletons()`. Signals are connected once and never disconnected — eliminates signal crosstalk and pool exhaustion bugs.
  2. **Pixmap virtualization** — only the `QIcon`/`QPixmap` is cleared (`btn.setIcon(QIcon())`) for off-screen items and reloaded from `thumb_cache` when scrolled back. Keeps memory bounded while widgets stay structurally stable.
  3. **Byte eviction** — items scrolling ±4 viewport heights off-screen have their `safe_bytes` nulled out. Reloaded from `thumb_cache` (L1 memory / L2 SQLite) when scrolled back.
  4. **Y-index binary search** — `bisect`-based O(log n + k) viewport intersection for fast visibility checks.
  5. **Decoupled loading** — `FetchThread` emits `posts_ready` after metadata (instant skeletons), then fetches thumbnails in the background. Generation counter prevents stale previews from old searches.
  6. **Bounded decode pool** — PIL image decoding capped at 4 threads (`ThreadPoolExecutor`) to prevent CPU spikes.
  7. **Split cache locks** — `thumb_cache.py` L1 and L2 now use separate locks so fast memory hits are never blocked by slow SQLite disk I/O.
  8. **Structured logging** — `RotatingFileHandler` in `main.py` writes to `%APPDATA%/BooruBrowser/logs/app.log`.


## 2. CRITICAL: Thread Pool Flooding & UI Hitching
Your thumbnail fetching (`fetch_previews` in `downloader.py`) is extremely dangerous for weak CPUs.
- **The Problem:** You use `await loop.run_in_executor(None, decode)` for `PIL` image decoding. `None` uses the default Python thread pool (usually `min(32, os.cpu_count() + 4)`). If you fetch 50 large JPEGs concurrently, you will flood the thread pool. Image processing in `PIL` is CPU-bound, and because of Python's GIL and the underlying C-extensions, doing 50 at once will bottleneck the system, spike CPU to 100%, and cause the PyQt UI thread to stutter or freeze completely.
- **The Fix:** Create a dedicated, bounded `ProcessPoolExecutor` (or a small thread pool like `max_workers=4`) specifically for image decoding. Queue the decodes so you don't process more than 4 images simultaneously.

## 3. CRITICAL: Blocking the QThread (Fake Async)
In `controller.py`, you are mixing `QThread` and `asyncio` incorrectly.
- **The Problem:** 
  ```python
  loop.run_until_complete(self.downloader.fetch_previews(posts, on_preview))
  ```
  `loop.run_until_complete` blocks the entire `FetchThread` until *all* thumbnails are downloaded and decoded. While the previews pop up incrementally via signals, the "Loading..." state won't finish until the absolute last image is done. If one image times out, the user is stuck waiting 10-30 seconds.
- **The Fix:** The `FetchThread` should exit after fetching the JSON metadata. The thumbnail fetching should be an entirely separate async background task that is decoupled from the main loading state.

## 4. HIGH: "Security Theater" (Credential Storage)
- **The Problem:** Your `credentials.py` claims to encrypt API keys, but the key is derived from `uuid.getnode()` (MAC address) and `os.environ.get("USERNAME")`. This is "security through obscurity" at its worst. Any script kiddie or basic malware can instantly derive the exact same key and steal your users' API keys. 
- **The Fix:** For a public app with 1M users, use the OS's native secure storage. Use the Python `keyring` package which hooks into Windows DPAPI / Credential Manager. 

## 5. HIGH: No Application Logging
- **The Problem:** You are handling errors with `print()` and `except Exception: pass`. When you package this with PyInstaller for Windows, there is no terminal. When a user experiences a crash or silent failure, they will complain, and you will have *zero logs* to help them debug it.
- **The Fix:** Replace all `print()` statements with Python's standard `logging` module. Configure a `RotatingFileHandler` to write logs to `%APPDATA%/BooruBrowser/logs/app.log`.

## ~~6. HIGH: Cloudflare Bypasser & Proxies~~ ✅ FIXED
~~- **The Problem:** You are trying to evade Cloudflare using `curl_cffi`, but you don't rotate IPs or fully sandbox the cookies. At 1M users, Cloudflare will start hard-blocking the default fingerprints. Furthermore, you mentioned "privacy-conscious proxy support" in your own roadmap, but `NetworkManager` currently doesn't read any proxy configs.~~
~~- **The Fix:** Implement proxy support deeply into `NetworkManager` and ensure `curl_cffi` sessions are correctly isolating contexts and proxies.~~
- **Resolution:** Complete overhaul of the Cloudflare bypass infrastructure:
  1. **Root cause fixed** — `InAppBrowser` now uses a dedicated `QWebEngineProfile` with persistent cookie/localStorage storage. The old default profile couldn't persist CF challenge tokens, causing blank pages.
  2. **Three bypass methods** — `CloudflareBrowserDialog` now offers:
     - 🌐 **In-App Browser** — embedded Chromium with auto-detection (cookieAdded signal + JS polling fallback)
     - 📋 **Manual Cookie Paste** — user pastes cf_clearance + optional UA from real browser DevTools
     - 📥 **Browser Cookie Import** — auto-extracts cookies from Chrome/Firefox/Edge/Brave/Opera via `browser_cookie3` with manual SQLite+DPAPI fallback
  3. **Proxy support** — `BypassSession` passes `settings.manager.proxy_url` to all engines (curl_cffi, cloudscraper, httpx, requests, urllib). Configurable in Settings → Network.
  4. **Engine selection** — users can lock to a specific HTTP engine (curl_cffi, cloudscraper, httpx, requests, urllib) or use Auto mode in Settings → Network.

## 7. MEDIUM: Global Lock Contention in Caches
- **The Problem:** Both `thumb_cache.py` and `tag_categorizer.py` use massive global locks (`threading.Lock()`). In `thumb_cache.py`, the lock wraps both the fast L1 memory cache and the slow L2 SQLite disk cache. If the disk is slow (e.g., an old HDD), reading an L2 cache miss will block the entire lock, preventing the UI from reading instant L1 hits. 
- **The Fix:** Separate your locks. Use a fast lock for the L1 dictionary, and a separate lock (or rely on SQLite's WAL concurrency) for L2. 

## 8. MEDIUM: Schizophrenic File Structure (Duplicate Settings)
- **The Problem:** You have a `settings.py` in the root folder, but you *also* have `ui/settings_view/manager.py` functioning as the actual settings singleton. You have `gui.py` importing `ui.settings_view as settings`. This is going to cause massive tech-debt and circular imports.
- **The Fix:** Delete the root `settings.py` completely. Rename `ui.settings_view.manager` to something globally accessible like `core.config` so it isn't buried inside the `ui` folder. UI views should depend on core config, not the other way around.

## 9. LOW: UI Code and Hardcoded QSS
- **The Problem:** You have a 130-line `DISCORD_QSS` string hardcoded in `main.py`. This is messy.
- **The Fix:** Move the QSS into a separate `.qss` file (e.g., `assets/theme.qss`) and load it at runtime. It makes it easier to maintain and eventually allows users to drop in custom themes.

## 10. LOW: Dangerous Path Construction
- **The Problem:** In `downloader.py` `get_download_folder_for_post()`, you are joining up to 5 tags to create a folder name. Even with a 60-character slice, deeply nested booru names + custom download directories can easily exceed the Windows `MAX_PATH` limit (260 characters), causing silent download failures.
- **The Fix:** Opt-in to Windows Long Paths in your application manifest, or be much more aggressive about truncating directory and file names.

---

### Summary for Launch
Do **not** launch to 1M users with the infinite scroll memory leak or the CPU-blocking thumbnail decoder. Those two flaws alone will result in immediate uninstallations due to "app freezing and using 4GB of RAM." Address the architectural blockers first.
