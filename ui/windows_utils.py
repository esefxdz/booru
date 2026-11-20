"""Windows-specific UI helpers."""

from __future__ import annotations

import ctypes
import logging


def apply_dark_title_bar(hwnd: int) -> None:
    """Enable the dark title bar (Windows 10 build 18985+); failures are logged and swallowed."""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        rendering_policy = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(rendering_policy),
            ctypes.sizeof(rendering_policy),
        )
    except Exception as e:
        logging.error("[windows_utils] Failed to set dark title bar: %s", e)
