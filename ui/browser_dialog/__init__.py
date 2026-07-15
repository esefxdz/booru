"""
ui/browser_dialog/__init__.py

Re-exports all browser dialog classes and the centralized bypass runner::

    from ui.browser_dialog import run_cf_bypass
    run_cf_bypass("danbooru", "https://danbooru.donmai.us", self,
                  on_success=lambda: print("unlocked!"))
"""

from __future__ import annotations

from PyQt6.QtCore import QObject

from ui.browser_dialog.in_app_browser import InAppBrowser
from ui.browser_dialog.cloudflare_browser_dialog import CloudflareBrowserDialog
from ui.browser_dialog.session_login_browser_dialog import SessionLoginBrowserDialog
from ui.browser_dialog.auto_solver import CloudflareAutoSolver


# ═══════════════════════════════════════════════════════════════════════
#  Centralized bypass runner
# ═══════════════════════════════════════════════════════════════════════

def run_cf_bypass(
    booru_name: str,
    url: str,
    parent: QObject | None,
    on_success: callable,
) -> None:
    """
    Run the Cloudflare bypass flow for *booru_name*.

    1. Try :class:`CloudflareAutoSolver` (hidden browser, auto-solve).
       If a ``cf_clearance`` cookie appears without user interaction,
       *on_success* is called and nothing is shown to the user.

    2. If the auto-solver times out, fall back to the interactive
       :class:`CloudflareBrowserDialog` so the user can solve the
       CAPTCHA manually.  *on_success* is called after they do.

    *on_success* is always called exactly once (or never, if the
    parent is destroyed before completion).
    """
    solver = CloudflareAutoSolver(booru_name, url, parent)

    def _on_auto_solved(_cookies: dict, _ua: str) -> None:
        on_success()

    def _on_auto_timeout() -> None:
        dlg = CloudflareBrowserDialog(url, booru_name, parent)
        dlg.cookies_captured.connect(lambda _: on_success())
        dlg.exec()

    solver.solved.connect(_on_auto_solved)
    solver.timed_out.connect(_on_auto_timeout)
    solver.start()


__all__ = [
    "InAppBrowser",
    "CloudflareBrowserDialog",
    "SessionLoginBrowserDialog",
    "CloudflareAutoSolver",
    "run_cf_bypass",
]
