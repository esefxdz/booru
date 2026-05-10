# BooruBrowser: Professional-Grade Roadmap & Technical Debt Audit

This document serves as the master blueprint for transitioning BooruBrowser from a functional prototype to a robust, scalable, and professional desktop application capable of supporting millions of users.

---

## 🛑 1. HIGH-RISK ARCHITECTURE (Must Fix Before Launch)

### 1.2 Global State Pollution
*   **Current Issue:** `settings.py` uses module-level globals (e.g., `ACTIVE_BOORU`). This makes the app hard to test, prone to race conditions, and difficult to reason about.
*   **Professional Fix:** Refactor to a `SettingsManager` Singleton class with a defined schema (using `pydantic` or a simple validator) to ensure data integrity.

### 1.3 Thread "Execution" (Safety Risk)
*   **Current Issue:** `AutocompleteHandler` uses `self._thread.terminate()`. 
*   **Danger:** This is a "brutal" kill that can leave network sockets open, locks held, or memory leaked.
*   **Professional Fix:** Use `QThread.requestInterruption()` and check `isInterruptionRequested()` inside the thread loop, or move to a `QRunnable` with a cancellation flag.

---

## ⚡ 2. PERFORMANCE & SCALABILITY

### 2.1 Virtualized Gallery Rendering
*   **Current Issue:** Every image is a `QPushButton`. 1,000 images = 1,000 widgets. This kills the UI event loop.
*   **Professional Fix:** 
    *   Implement **Viewport Virtualization**: Only render the widgets currently visible on screen.
    *   Use `QListView` with a `QStyledItemDelegate` or a custom `QAbstractScrollArea` that recycles image containers.

### 2.2 Advanced Cache Management
*   **Current Issue:** `OrderedDict` only tracks the raw `bytes`. It doesn't track the memory used by `QPixmap` (GPU textures) or the `PIL.Image` objects.
*   **Professional Fix:** Implement a tiered cache:
    1. **L1 (Memory):** Fixed number of decoded `QPixmap` objects for immediate display.
    2. **L2 (Disk):** Persistent SQLite database or hashed folder for thumbnails to avoid re-downloading/re-processing on app restart.

    *   **Professional Fix:** Standardize on a global `NetworkManager` that uses a `Semaphore` to limit total outgoing requests across the entire app, preventing IP bans and socket exhaustion.

---

## 🛡️ 3. SECURITY & PRIVACY

### 3.1 Sandbox Re-Enablement
*   **Current Issue:** `--no-sandbox` is enabled for WebEngine.
*   **Requirement:** Identify the driver or OpenGL conflict causing the need for this flag and resolve it. A mass-market app cannot ship with the Chromium sandbox disabled.

### 3.2 Credential Hardening
*   **Current Issue:** Plaintext migration is good, but is the system keyring always available?
*   **Requirement:** Implement a fallback for headless or restricted environments (e.g., portable mode) using an encrypted local blob with a machine-specific salt.

### 3.3 SSL Pinning & Validation
*   **Requirement:** Ensure all API requests strictly validate SSL certificates. Add support for user-defined proxy settings (SOCKS5/HTTP) for privacy-conscious users.

---

## 🎨 4. UX & DESIGN EXCELLENCE

### 4.1 High-DPI & Scaling Support
*   **Current Issue:** Hardcoded pixel values (e.g., `row_h = 38`).
*   **Professional Fix:** Use `logicalDpiX()` and `logicalDpiY()` to scale layouts dynamically, or use layout margins/spacings that are DPI-aware.

### 4.2 Modern Animation System
*   **Current Issue:** Animations are basic fade-ins.
*   **Requirement:** Add "Skeletal Loaders" (shimmering boxes) for images that haven't loaded yet. Add smooth transitions between "Gallery" and "Viewer" modes.

### 4.3 Full Keyboard Accessibility
*   **Requirement:** Ensure the entire app is navigable via `Tab`, `Arrow Keys`, and `Enter`. Add customizable global hotkeys (e.g., `Ctrl+S` to download, `F` to favorite).

---

## 📦 5. DISTRIBUTION & MAINTENANCE

### 5.1 Auto-Updater Implementation
*   **Requirement:** Mass public use requires a zero-friction update path. Integrate `PyUpdater` or a GitHub-based version checker with an "Update on Restart" flow.

### 5.2 Crash Reporting & Telemetry
*   **Requirement:** Integrate **Sentry** (or a self-hosted alternative) to catch production crashes. Add **anonymous** telemetry (opt-in) to see which Booru sites are failing or which features are unused.

### 5.3 Internationalization (i18n)
*   **Requirement:** Move all UI strings to `.ts` files using `Qt Linguist`. Prepare for Japanese, Chinese, and European localizations, as Booru users are global.

### 5.4 CI/CD Pipeline
*   **Requirement:** Automated builds via GitHub Actions.
    *   **Linting:** Ruff.
    *   **Type Checking:** Mypy.
    *   **Testing:** Pytest for all adapters and validation logic.
    *   **Packaging:** Auto-generate `.exe` and `.zip` on every tag.

---

## ⚙️ 6. BOORU ENGINE COMPATIBILITY (Frictionless Multi-Site Support)

### 6.1 Universal Normalization Layer  ✅ DONE
*   **Implemented:** `NormalizedPost` dataclass in `adapters/base.py` with strict fields (`id`, `file_url`, `preview_url`, `sample_url`, `tags`, `rating`, `score`, `source`).
*   `normalize_post()` method resolves protocol-relative URLs (`//`) and normalizes ratings (`s/q/e` → `safe/questionable/explicit`) via `_RATING_MAP`.

### 6.2 Authentication Variation Handling  ✅ DONE (existing)
*   **Status:** Already handled — each adapter's `build_params()` injects credentials in the engine-specific way (query params for Danbooru/Gelbooru, header via `_get_client_args` for session-based sites).

### 6.3 Auto-Discovery & Capability Detection  ✅ DONE (existing)
*   **Status:** Already implemented in `AddBooruDialog.AutoDetectThread` — probes `/posts.json`, `/post.json`, DAPI, Philomena, Szurubooru, and Shimmie2 endpoints automatically.

### 6.4 Pagination Standardization  ✅ DONE
*   **Implemented:** `get_pagination_params(page_index, limit)` in `BaseAdapter` with three styles:
    *   `page1` — 1-indexed (Danbooru, Moebooru, e621, Philomena)
    *   `pid` — offset page ID (Gelbooru, HTML Scraper)
    *   `offset` — raw offset (Szurubooru)
    *   Custom overrides for Zerochan (`p` param) and Shimmie2 (0-indexed `page`).
*   Controller only passes `page_index`; adapters handle the math.

### 6.5 Autocomplete Fragmentation  ✅ DONE
*   **JSONP Stripping:** `_strip_jsonp()` in `tag_complete_thread.py` removes `callback(...)` wrappers before JSON parse.
*   **Local SQLite Tag Cache:** `ui/autocomplete/tag_cache.py` stores tags per-booru in `%APPDATA%/BooruBrowser/tag_cache.db`.
*   **Fuzzy Matching:** `search_tags()` uses `LIKE %prefix%` so `girl` matches `1girl`, `catgirl`, etc.
*   Worker checks cache first (instant), then fetches network, then updates cache.

---

## 🎥 7. ADVANCED MEDIA & PLAYBACK

### 7.1 Immersive Slideshow Mode
*   **Missing Feature:** No way to "lean back" and watch a gallery.
*   **Professional Fix:** Implement a Fullscreen Slideshow with:
    1. Adjustable transition timers.
    2. Cross-fade or slide animations.
    3. Auto-looping for videos/GIFs before moving to the next post.

### 7.2 Unified Video Engine (MPV/VLC Integration)
*   **Current Issue:** Qt Multimedia is notorious for codec issues and performance overhead on Windows.
*   **Professional Fix:** Integrate `libmpv` or `vlc-python` as an optional backend. It supports hardware decoding for almost every format (AV1, HEVC) without needing system-wide codecs.

### 7.3 Heavy Media Optimization (AVIF/WebP)
*   **Current Issue:** Thumbnails are always JPEGs, but modern CDNs serve WebP or AVIF which are 50% smaller.
*   **Professional Fix:** Add native support for **AVIF** and **WebP** decoding in the downloader to save bandwidth and improve load speeds.

---

## 💬 8. COMMUNITY & INTERACTION (Social Layer)

### 8.1 Comment Threading & Viewing
*   **Missing Feature:** Users can't see the context or discussion behind an image.
*   **Professional Fix:** Add a "Comments" tab in the viewer. Standardize the disparate comment APIs (Danbooru's nested JSON vs. Gelbooru's flat list).

### 8.2 Two-Way Favorite Sync
*   **Current Issue:** "Bookmarks" are local-only.
*   **Professional Fix:** Implement **Two-Way Sync**. When a user stars an image in the app, call the Booru's API to add it to their site-wide favorites automatically.

---

## 🚀 9. POWER-USER WORKFLOWS

### 9.1 Advanced Download Queue Manager
*   **Current Issue:** Downloads are "fire and forget" with no way to prioritize or pause.
*   **Professional Fix:** Implement a **Download Manager** view with:
    1. **Retry Logic:** Auto-retry on 5xx errors or timeouts.
    2. **Speed Limiter:** Don't saturate the user's home network.
    3. **Disk Space Check:** Prevent OS crashes by checking space BEFORE starting bulk downloads.

### 9.2 Search Macros & Aliases
*   **Missing Feature:** Typing `rating:general score:>100 order:rank` is tedious.
*   **Professional Fix:** Implement **Search Macros**. Allow users to define `.favs` which expands to a complex set of filters instantly in the search bar.

---

## 🔒 10. PRIVACY & ANONYMITY (The "Ninja" Mode)

### 10.1 Metadata Stripping (EXIF/XMP)
*   **Current Issue:** Downloaded images contain uploader metadata or source URLs.
*   **Professional Fix:** Automatically strip all non-essential EXIF/metadata from images during the download process to protect user privacy.

### 10.2 Native SOCKS5/Proxy Tunneling
*   **Current Issue:** The app relies on system-wide proxy settings.
*   **Professional Fix:** Add app-specific **SOCKS5/HTTP Proxy** support. Allow users to route Booru Browser traffic through Tor or a VPN without affecting the rest of the OS.

---

## 🏢 11. INFRASTRUCTURE & SCALING (The 1M User Challenge)

### 11.1 API Key Rotation & "BYOK" Strategy
*   **Requirement:** Providing a "Default" key for 1M users will get you banned.
*   **Fix:** Strictly enforce a **"Bring Your Own Key" (BYOK)** flow with a guided UI tutorial for each major site to keep the app's traffic footprint distributed.

### 11.2 Portable Mode Support
*   **Requirement:** Many users run Booru tools from USB drives or cloud folders.
*   **Fix:** Add a `portable.txt` check at launch. If present, redirect all `%APPDATA%` paths to the local directory to keep the installation self-contained.
