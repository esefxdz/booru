# Booru Browser — Production Readiness & Scaling Audit

> Honest assessment of what will break, embarrass you, or get you banned before reaching 1M users.
> Every issue is grounded in the actual source files. No generic advice.

---

## Section 1: Bugs That Are Wrong Right Now

These are not "scale concerns" — they are plain bugs in the current code that will be triggered by ordinary users within their first session.

---

### ~~1. `credentials.py` Has Two Conflicting Definitions of Every Function~~ ✅ FIXED

**File:** `credentials.py` — lines 198–237

The module defined `set_credential`, `get_credential`, `delete_credential`, `list_boorus_with_credentials`, and `migrate_from_settings` **twice**. The second block (lines 218–237) shadowed the first (lines 198–216), meaning the first block — which returns `bool` — was completely dead code. The second block also changed the return type of `set_credential` from `bool` to `None` silently.

**Resolution:** Deleted the duplicate "Convenience functions" block (the original 20 lines). The first block is now the only definition and correctly returns `bool` from `set_credential`.

---

### ~~2. `thumbnails.py` Cache Key Is Just a Raw Post ID~~ ✅ FIXED

**File:** `download_images/thumbnails.py` — line 61

Cache keys are now built as `f"{booru}:{post_id}"` (e.g. `"danbooru:1234"`), matching the pattern documented in `thumb_cache.py`'s own docstring. Both the `get()` and `put()` calls use the namespaced key.

---

### ~~3. `engines.py` Disables SSL Verification Globally and Silently~~ ✅ FIXED

**File:** `download_images/engines.py`

**Resolution:** Each of the five engines now attempts the download with SSL verification **enabled** first. Only if an `SSLError` (or equivalent) is raised does it retry with `verify=False`, and when it does it logs a `WARNING` via the `image_downloader` logger so the event is traceable. Silent unconditional `verify=False` is gone.

---

### ~~4. `validation.py` Silently Corrupts Search Queries~~ ✅ FIXED

**File:** `validation.py`

**Resolution:** Removed the regex filter and `re.sub` strip entirely. `validate_search_term` now only enforces a length cap and normalises whitespace (`" ".join(term.split())`). The Booru API handles malformed syntax itself — it is not the client's job to silently rewrite query operators it doesn't understand.

---

### ~~5. `manager.py` Saves Session Tokens to a Plaintext JSON File~~ ✅ FIXED

**File:** `ui/settings_view/manager.py`

**Resolution:** `SettingsManager.save()` now excludes `bypass_data`, `session_keys`, `auth_tokens`, and `bookmarks` from the serialised dict via a `_SENSITIVE_KEYS` set. These fields remain in memory for the current session but are never written to `settings.json`.

---

### ~~6. `controller.py` — The `_is_loading` Guard Has a Race Condition~~ ✅ FIXED

**File:** `controller.py`

**Resolution:**
- `_thread_lock = threading.Lock()` now guards all check-and-set operations on `_is_loading`.
- Each `FetchThread` owns a `cancel_event = threading.Event()`. Before starting a new thread, `_cancel_active_thread()` sets that event, calls `quit()`, and waits up to 2 seconds for a clean exit.
- `trigger_fetch` (new search) always cancels and replaces. `trigger_fetch_append` (infinite scroll) still returns early if a load is already in progress, preventing double-appends.
- `_on_fetch_error` now logs via `logging.getLogger(__name__)` instead of `print()`.

---

### ~~7. `thumbnails.py` — `asyncio.gather` Has No Concurrency Limit~~ ✅ FIXED

**File:** `download_images/thumbnails.py`

**Resolution:**
- `asyncio.Semaphore(8)` (`_MAX_CONCURRENT`) is acquired inside each `fetch_one` coroutine before the HTTP request. At most 8 CDN connections run simultaneously regardless of page size.
- The `cancel_event` from `FetchThread` is checked at the top of each `fetch_one` and again before acquiring the semaphore, so cancelled searches abort with zero wasted requests.
- The event also threads through `BooruDownloader.fetch_previews` → `thumbnails.fetch_previews` with a `None` default so existing call sites that don't pass it continue to work.

---

### 8. `main.py` — QSS Theme String Is 130 Lines of Hardcoded Python

**File:** `main.py` — lines 26–159

`DISCORD_QSS` is a 130-line f-string embedded in `main.py`. This makes it impossible to:
- Support user-supplied themes without shipping a new binary
- Hot-reload the theme during development
- Allow community theme packs
- Keep `main.py` focused on application bootstrap logic

**Fix:** Move it to `assets/theme.qss` and load it at runtime with `open(Path(__file__).parent / "assets/theme.qss")`. Substitute color tokens using a simple `str.replace` or template engine. This is a low-effort change with high long-term benefit.

---

## Section 2: What Will Break at Scale

These issues are not bugs today but become crises when thousands of users run the app simultaneously.

---

### 9. The Default User-Agent Will Get the App Banned

**File:** `ui/settings_view/manager.py` — line 20

```python
"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
```

This is an incomplete, truncated UA string. Real Chrome sends a 100+ character UA including the full version chain. Booru server logs will immediately identify this as a scraper bot because:

1. The UA is cut off mid-string (missing the Chrome version and platform tokens)
2. Every single install of the app sends the exact same UA
3. At 1M users, this UA appears millions of times per day — trivial to identify and block

When Danbooru or Gelbooru bans this UA, every user's app stops working simultaneously, and they all think the app is broken.

**Fix:** Use a full, rotating, realistic UA string. At minimum, complete the existing string: `"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"`. Rotate between a small pool of current Chrome/Firefox UAs.

---

### 10. No Rate Limiting Anywhere in the Network Stack

There is no throttle, no delay, and no token bucket anywhere between the user pressing Enter and 50 simultaneous HTTP requests flying to a Booru server. At 1M installs, a popular tag like `touhou` will cause tens of thousands of users to hit the same endpoint at the same time (e.g., after a new game release). The Booru host will see a traffic spike indistinguishable from a DDoS attack and will block the app's IP ranges.

This already happened to other popular Booru clients (Hydrus, etc.) — certain sites added per-IP rate limits specifically because of client apps.

**Fix:**
- Add a per-host `asyncio.Semaphore` in `NetworkManager` limiting concurrent requests to any single domain.
- Add a configurable request delay between pages (even 250ms per page request prevents thundering herd).
- Expose these as Settings → Network options so power users can tune them.

---

### 11. `SettingsManager` Is Instantiated at Module Import Time

**File:** `ui/settings_view/manager.py` — line 207

```python
manager = SettingsManager()
```

This runs at the moment any file does `from ui import settings_view as settings`. The singleton constructor calls `_SETTINGS_DIR = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser"` and also executes `DOWNLOAD_DIR.mkdir(exist_ok=True)` at line 18 — creating filesystem directories as a side effect of importing a module.

This makes unit testing impossible without mocking the filesystem, makes CLI usage impossible, and means any import ordering issue in a cold startup will try to create directories before the user's profile is fully loaded (relevant on domain-joined machines and fast user switching).

**Fix:** Delay the `mkdir` call to `manager.load()`. Make the singleton lazy — only call `_init()` when `.load()` is first called, not in `__new__`.

---

### 12. Bookmarks Are Loaded Into RAM as a Full JSON List

**File:** `ui/settings_view/manager.py` — lines 145–152

```python
def load_bookmarks(self):
    with open(_BOOKMARKS_FILE, ...) as f:
        self.bookmarks = json.load(f)
```

And in `gui.py` line 196, `load_bookmarks()` is called on **every search trigger** while in bookmarks mode. The bookmarks list is stored in memory as a full Python list of post dicts. A power user with 50,000 bookmarks would load ~25MB of JSON into RAM on every keypress-triggered search.

In-memory bookmark search (`gui.py` line 31) iterates the entire list with `all(t in p.get('tags', []) for t in search_tags)` — an O(n × m) scan with no indexing.

**Fix:** Move bookmarks to their own SQLite table. Build an FTS (Full-Text Search) index on the tags column. Do not reload from disk on every search — use an in-memory flag to track dirty state.

---

### 13. Crash Reporting Is `print()` to a File Nobody Will Find

**File:** `main.py` — lines 162–181, and throughout the codebase

Logging is correctly configured with `RotatingFileHandler` writing to `%APPDATA%/BooruBrowser/logs/app.log`. However, the vast majority of error handling across the codebase uses `print()` (e.g., `credentials.py` lines 81, 92, 117, 134), which only goes to `logging.StreamHandler` (the console). In a PyInstaller build there is no console window, so these messages vanish.

More critically, unhandled exceptions in QThreads do not propagate to the main thread — they print to stderr and are silently swallowed. If `FetchThread.run()` crashes on an unexpected exception type after line 55, the `except` block catches it, but there is no stack trace logged, only the string representation of the exception.

**Fix:** Replace all `print()` calls with `logging.getLogger(__name__)`. In `FetchThread.run()`, log the full traceback with `logging.exception("FetchThread crashed")` inside the `except` block. Consider integrating Sentry for automatic remote crash reporting — even a free tier captures enough to diagnose production bugs.

---

## Section 3: Distribution & Public Release Requirements

These are not code issues — they are the infrastructure you need before publishing.

---

### 14. Unsigned PyInstaller Executables Will Be Quarantined

The PyInstaller `.exe` will be deleted or blocked by Windows Defender SmartScreen on first run for a large fraction of users. SmartScreen's reputation system is based on how many users have downloaded and run a specific file hash. A new, unsigned file from an unknown publisher starts with zero reputation — meaning the full "Windows protected your PC" block screen appears.

Beyond SmartScreen, many antivirus products (Avast, Malwarebytes, Bitdefender) heuristically flag any PE binary that:
- Contains embedded Python bytecode
- Makes network requests on startup
- Reads from `%APPDATA%`
- Uses `ctypes` to call DWM APIs (which this app does in `gui.py` line 389)

All of the above apply to this application.

**Options in order of cost and effectiveness:**
1. **EV Code Signing Certificate** (~$300–500/year from DigiCert or Sectigo) — immediately grants SmartScreen reputation. The gold standard.
2. **Microsoft Store distribution** — free, pre-approved, no SmartScreen. Requires MSIX packaging and a Dev Center account. Best for reach.
3. **winget submission** — free, reaches power users. Requires a GitHub release with a verifiable hash.
4. **VirusTotal pre-submission** — not a fix, but useful for identifying which AV engines flag false positives before release.

---

### 15. No Auto-Update Mechanism

Booru sites change their API response schemas, add Cloudflare, rotate their CDN domains, and occasionally shut down. Any of these events breaks the app for every existing installation simultaneously. There is no way to push a fix without users manually re-downloading the executable.

At 1M users, even a 0.1% complaint rate is 1,000 users opening issues or leaving negative reviews.

**Fix:** Add a startup version check against a GitHub release or a simple JSON endpoint:
```python
# On startup, in a background thread:
response = httpx.get("https://yourdomain.com/latest.json", timeout=5)
latest = response.json()["version"]
if latest > settings.VERSION:
    notify_user_of_update(latest)
```
This does not need to be a silent auto-installer — even just showing a banner "Update available: v1.2.0" with a link is enough to dramatically reduce stale-client complaints.

---

## Production Readiness Checklist

**Must fix before any public release:**
- [ ] Delete the duplicate function definitions in `credentials.py` (lines 218–237)
- [ ] Namespace thumbnail cache keys as `booru:post_id` in `thumbnails.py`
- [ ] Fix the `_is_loading` race condition in `controller.py` with a proper lock
- [ ] Add `asyncio.Semaphore` to `thumbnails.py` to cap concurrent CDN requests at ~8
- [ ] Fix the User-Agent string to be a complete, realistic Chrome UA
- [ ] Exclude `bypass_data`, `session_keys`, and `auth_tokens` from `settings.json`
- [ ] Replace all `print()` error paths with `logging.getLogger(__name__)`

**Should fix before public release:**
- [ ] Add per-host rate limiting in `NetworkManager`
- [ ] Move `DISCORD_QSS` out of `main.py` into a `.qss` asset file
- [ ] Move bookmarks to SQLite with FTS indexing
- [ ] Delay `DOWNLOAD_DIR.mkdir()` and `SettingsManager._init()` out of module import time
- [ ] Fix `validation.py` to stop silently mutating search queries

**Required before 1M users:**
- [ ] Code signing certificate or Store distribution
- [ ] Startup version check with update notification
- [ ] Full tracebacks logged for all QThread exceptions
- [ ] SSL verification fallback with user-facing warning instead of silent `verify=False`
