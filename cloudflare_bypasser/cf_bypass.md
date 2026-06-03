# Cloudflare Bypass — Implementation Plan

> **Status of existing code:** The multi-engine `session.py`
> (curl_cffi → cloudscraper → httpx → requests → urllib) is solid and
> well-structured. The problems are in the **UI layer** (browser dialog crashes,
> dangling `_profile` reference) and the fact that no programmatic engine can
> handle **interactive CAPTCHA challenges** — those require a real human.
> This plan fixes the known bugs and describes how to build each engine robustly.

---

## Immediate Bug Fixes

### Bug 1 — `load_url()` crash in `in_app_browser.py` ✅ FIXED
`line 114` called `.toString()` on a value that had already passed the
`isinstance(url, str)` check, but the `urlChanged` signal emits a `QUrl`.
**Fixed** by normalizing to `str` at the very top of `load_url()`.

### Bug 2 — `self._profile` never assigned (two files broken)

`in_app_browser.py` creates the profile as a local variable:
```python
profile = QWebEngineProfile.defaultProfile()   # ← local, not self._profile
```

`session_login_browser_dialog.py:42` then does `self._profile.cookieStore()`
and crashes with `AttributeError: 'SessionLoginBrowserDialog' has no attribute '_profile'`.

**Fix — `in_app_browser.py`:** Store as an instance attribute.
```python
# Change:
profile = QWebEngineProfile.defaultProfile()
# To:
self._profile = QWebEngineProfile.defaultProfile()
profile = self._profile
```
No other changes needed — all subclasses inherit `self._profile` automatically.

### Bug 3 — `CloudflareBrowserDialog` uses shared `defaultProfile()`

Using the default profile means all WebEngine instances share one cookie jar.
If any other dialog (e.g. SessionLoginBrowserDialog) is open at the same time,
Cloudflare cookies bleed across boorus and sessions.

**Fix:** Use a per-booru **named persistent profile**:
```python
profile_name = f"cf_bypass_{booru_name}"
self._cf_profile = QWebEngineProfile(profile_name, self)
self._cf_profile.setPersistentCookiesPolicy(
    QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
)
self._cf_profile.setHttpUserAgent(_CHROME_UA)
page = QWebEnginePage(self._cf_profile, self.browser)
self.browser.setPage(page)
cookie_store = self._cf_profile.cookieStore()
cookie_store.cookieAdded.connect(self._on_cookie_added)
```

---

## Engine Architecture

```
User right-clicks booru → "Cloudflare" tab
              │
              ▼
  ┌─────────────────────────────────────┐
  │       CloudflareBrowserDialog       │
  │  ┌──────────┐ ┌────────┐ ┌───────┐ │
  │  │ Engine 1 │ │Engine 2│ │Engine3│ │
  │  │ In-App   │ │ Manual │ │Browser│ │
  │  │ Browser  │ │ Paste  │ │Import │ │
  │  └──────────┘ └────────┘ └───────┘ │
  └─────────────────────────────────────┘
              │
              ▼
    store.save_bypass(booru, cookies, ua)
              │
              ▼
    BypassSession.get() uses cookies automatically
```

All three engines produce a `(cookies: dict, user_agent: str)` pair stored via
`store.save_bypass()`. The programmatic engine chain in `session.py` is already
solid — it just needs these cookies to work against CF-protected boorus.

---

## Engine 1 — In-App Browser (Interactive CAPTCHA)

**Files:** `ui/browser_dialog/cloudflare_browser_dialog.py`, `in_app_browser.py`

### Remaining Problems After Bug Fixes

| Problem | Impact |
|---|---|
| `cookieAdded` only fires for `Set-Cookie` headers | Misses cookies set by CF's inline JS (`document.cookie`) — dialog never auto-closes |
| No user-facing status | User can't tell if challenge was detected or if they should wait |
| UA not captured from WebEngine on success | Bypass session uses hardcoded UA instead of the exact one CF fingerprinted |

### Fixes

**1A — JS polling alongside `cookieAdded`**

CF's Turnstile widget sets `cf_clearance` via JS, not a server header.
Poll every 500 ms after page load:

```python
self._poll_timer = QTimer(self)
self._poll_timer.setInterval(500)
self._poll_timer.timeout.connect(self._poll_js_cookies)

def _on_load_finished(self, ok):
    if ok:
        self._poll_timer.start()
        # Stop polling after 60 s max to avoid zombie timers
        QTimer.singleShot(60_000, self._poll_timer.stop)

def _poll_js_cookies(self):
    self.browser.page().runJavaScript(
        "document.cookie",
        lambda result: self._check_js_cookies(result or "")
    )

def _check_js_cookies(self, cookie_str: str):
    if "cf_clearance" in cookie_str and not self._captured:
        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()
        self._captured = True
        self._poll_timer.stop()
        QTimer.singleShot(800, lambda: self._finalize(cookies))
```

**1B — Status bar**

Add a `QLabel` below the browser that cycles through:
- `⏳ Waiting for Cloudflare…` (initial)
- `🔐 Challenge detected — please solve the CAPTCHA` (on 403 page load)
- `✅ Clearance captured — closing…` (on success)

Detect the 403 challenge page via `loadFinished` + a JS check for
`document.title.includes("Just a moment")`.

**1C — Capture the real UA on finalize**

```python
def _finalize(self, cookies):
    ua = self._cf_profile.httpUserAgent()
    from cloudflare_bypasser import store
    store.save_bypass(self.booru_name, cookies, ua)
    self.cookies_captured.emit(cookies)
    self.accept()
```

---

## Engine 2 — Manual Cookie Paste

**File:** `ui/browser_dialog/cloudflare_browser_dialog.py` (fallback bar)

### Current Problems

- Only accepts the `cf_clearance` value — no UA field
- No validation that the pasted value is a valid CF token
- Blocking `QMessageBox` on empty input interrupts the workflow

### Fixes

**2A — Add a UA input field**

```
┌────────────────────────────────────────────────────────────┐
│  Not loading? Import cookies manually from DevTools        │
│                                                            │
│  cf_clearance:  [______________________________________]   │
│  User-Agent:    [______________________________________]   │
│  (optional — leave blank to use default Chrome UA)        │
│                                         [Apply & Close]   │
└────────────────────────────────────────────────────────────┘
```

**2B — Pre-populate UA with the app default** so the user only has to paste
`cf_clearance`.

**2C — Inline warning instead of blocking dialog**

```python
def _apply_pasted(self):
    cf_val = self._cf_input.text().strip()
    if not cf_val:
        self._warn_lbl.setText("⚠ Paste a cf_clearance value first.")
        return
    if not cf_val.startswith("v1."):
        self._warn_lbl.setText("⚠ Doesn't look like a cf_clearance token (should start with v1.)")
    ua = self._ua_input.text().strip() or _CHROME_UA
    cookies = {"cf_clearance": cf_val, **self._found_cookies}
    from cloudflare_bypasser import store
    store.save_bypass(self.booru_name, cookies, ua)
    self._finalize(cookies)
```

---

## Engine 3 — Browser Cookie Auto-Import

**New file:** `ui/browser_dialog/browser_cookie_importer.py`

Reads `cf_clearance` cookies directly from the user's real system browser
profile files — no extensions or manual DevTools needed.

### Supported Browsers (Windows)

| Browser | Cookie DB path |
|---|---|
| Chrome | `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies` |
| Edge | `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies` |
| Brave | `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies` |
| Opera | `%APPDATA%\Opera Software\Opera Stable\Network\Cookies` |
| Firefox | `%APPDATA%\Mozilla\Firefox\Profiles\*.default*\cookies.sqlite` |

### Implementation Sketch

```python
# browser_cookie_importer.py

import sqlite3, shutil, tempfile
from pathlib import Path

CHROMIUM_PATHS = {
    "Chrome": Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
    "Edge":   Path.home() / "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies",
    "Brave":  Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Network/Cookies",
}

def find_cf_clearance(domain: str) -> dict[str, str]:
    """Return {browser_name: cookie_value} for every browser that has cf_clearance for domain."""
    results = {}
    for browser, path in CHROMIUM_PATHS.items():
        if path.exists():
            val = _read_chromium_cookie(path, domain, "cf_clearance")
            if val:
                results[browser] = val
    ff = _read_firefox_cookie(domain, "cf_clearance")
    if ff:
        results["Firefox"] = ff
    return results

def _read_chromium_cookie(db_path: Path, domain: str, name: str) -> str | None:
    # Copy first — Chrome locks the DB while it's running
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        shutil.copy2(db_path, tmp.name)
        tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        row = conn.execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE host_key LIKE ? AND name = ? "
            "ORDER BY last_access_utc DESC LIMIT 1",
            (f"%{domain}%", name)
        ).fetchone()
        conn.close()
        if row:
            return _decrypt_chromium_value(row[0])
    except Exception:
        pass
    return None

def _decrypt_chromium_value(encrypted_value: bytes) -> str | None:
    """Decrypt a Chromium DPAPI/AES-GCM encrypted cookie on Windows."""
    try:
        if encrypted_value[:3] == b"v10":
            # AES-256-GCM — key is in Local State encrypted with DPAPI
            # Requires reading %LOCALAPPDATA%\Google\Chrome\User Data\Local State
            # and decrypting the "encrypted_key" field first.
            # See: https://stackoverflow.com/a/60611900
            return _decrypt_aes_gcm(encrypted_value)
        # Legacy DPAPI (older Chrome / pre-v80)
        import ctypes, ctypes.wintypes
        import win32crypt  # pywin32
        data, _ = win32crypt.CryptUnprotectData(
            encrypted_value, None, None, None, 0
        )
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None
```

**UI integration:** Add an "Auto-Import from Browser" button in the CF dialog that:
1. Runs `find_cf_clearance(booru_domain)` in a thread (non-blocking)
2. Shows a list of results: `Chrome — found ✅` / `Firefox — not found`
3. User clicks the browser name to apply that cookie immediately

**Graceful degradation:** If `pywin32` is missing or decryption fails, show:
> "Auto-import unavailable — please use Manual Paste instead."

---

## Auto-Invalidation on Expired Bypass (403)

**File:** `downloader.py`

When `is_blocked` is True on a 403, the stored clearance has expired.
Auto-clear it so the next request doesn't keep sending a dead cookie:

```python
# In get_image_urls(), replace the existing 403 check block:
if r.status_code == 403 and getattr(r, "is_blocked", False):
    from cloudflare_bypasser import invalidate_session
    invalidate_session(settings.manager.active_booru)
    raise CloudflareBlockError(
        f"'{booru}' Cloudflare clearance has expired. "
        f"Right-click the booru icon → Cloudflare tab to re-solve."
    )
```

Also in thumbnail fetching (`fetch_one`): a 403 on a CDN URL should log and
skip the image — not crash or retry endlessly.

---

## Bug Summary

| File | Line | Bug | Fix |
|---|---|---|---|
| `in_app_browser.py` | 114 | `AttributeError: 'str' has no .toString()` | ✅ Fixed |
| `in_app_browser.py` | 82 | `profile` is local, not `self._profile` | Store as `self._profile` |
| `session_login_browser_dialog.py` | 42 | `AttributeError: self._profile` | Inherit from fixed parent |
| `cloudflare_browser_dialog.py` | 32 | Shared `defaultProfile()` cookie jar | Named per-booru persistent profile |
| `cloudflare_browser_dialog.py` | — | JS-set `cf_clearance` never detected | Add 500ms JS polling |
| `cloudflare_browser_dialog.py` | — | UA not captured from WebEngine | Capture from `profile.httpUserAgent()` in `_finalize` |
| `downloader.py` | — | Expired 403 cookies never cleared | Auto-call `invalidate_session()` on `is_blocked` |
| Manual paste | — | No UA field, blocking dialog on error | Add UA field, inline warnings |
