"""
ui/windows_utils.py — Windows-specific UI helpers.

Currently contains the dark title bar enabler.  Add other Windows
shell / DWM helpers here so they don't clutter the main window.
"""

from __future__ import annotations

import ctypes
import logging


def apply_dark_title_bar(hwnd: int) -> None:
    """Enable Windows Immersive Dark Mode on the title bar.

    Requires Windows 10 build 18985+ or Windows 11.
    Safe to call on unsupported versions — failures are logged and swallowed.
    """
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        rendering_policy = ctypes.c_int(1)  # 1 = Enable
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(rendering_policy),
            ctypes.sizeof(rendering_policy),
        )
    except Exception as e:
        logging.error("[windows_utils] Failed to set dark title bar: %s", e)
