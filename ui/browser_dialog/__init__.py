"""Embedded-browser dialogs for Cloudflare bypass and session login."""

from __future__ import annotations

from PyQt6.QtCore import QObject

from ui.browser_dialog.in_app_browser import InAppBrowser
from ui.browser_dialog.cloudflare_browser_dialog import CloudflareBrowserDialog
from ui.browser_dialog.session_login_browser_dialog import SessionLoginBrowserDialog
from ui.browser_dialog.auto_solver import CloudflareAutoSolver


def run_cf_bypass(
    booru_name: str,
    url: str,
    parent: QObject | None,
    on_success: callable,
) -> None:
    """Auto-solve the Cloudflare challenge, else show the manual dialog; on_success fires at most once."""
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
