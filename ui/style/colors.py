"""
ui/colors.py — Centralized color palette for the Booru Browser.

Uses a 'True Black' aesthetic with Discord-inspired accent colors.
"""

# ── Base Backgrounds ───────────────────────────────────────────
MAIN_BG   = "#000000"  # OLED/True Black
PANEL_BG  = "#000000"  # Sidebar and TagPanel
INPUT_BG  = "#020202"  # Search bars and text inputs
MODAL_BG  = "#020202"  # Dialog backgrounds

# ── Borders & Dividers ─────────────────────────────────────────
BORDER    = "#080808"
DIVIDER   = "#080808"

# ── Buttons ───────────────────────────────────────────────────
BUTTON_BG      = "#1E1F22"
BUTTON_HOVER   = "#2B2D31"
BUTTON_PRESSED = "#111214"

# ── Accents & States ───────────────────────────────────────────
ACCENT         = "#5865F2"  # Discord Blurple
ACCENT_HOVER   = "#4752C4"
SUCCESS        = "#23A559"  # Green
DANGER         = "#ED4245"  # Red
DANGER_HOVER   = "#DA373C"
WARNING        = "#FEE75C"  # Yellow
LINK           = "#00A8FC"  # Blue link
FAVORITE       = "#FFD700"  # Gold star

# ── Text ───────────────────────────────────────────────────────
TEXT_PRIMARY   = "#FFFFFF"
TEXT_SECONDARY = "#DBDEE1"
TEXT_MUTED     = "#80848E"

# ── Tag Categories ─────────────────────────────────────────────
TAG_ARTIST     = "#ED4245"
TAG_CHARACTER  = "#57F287"
TAG_COPYRIGHT  = "#EB459E"
TAG_METADATA   = "#FEE75C"
TAG_GENERAL    = "#DBDEE1"

# ── Dropdowns & Autocomplete ──────────────────────────────────
DROPDOWN_BG     = "#2B2D31"
DROPDOWN_BORDER = "#1E1F22"
DROPDOWN_SEP    = "#232428"
DROPDOWN_HOVER  = "#35373C"

# ── Autocomplete Tag Specifics (slightly brighter) ────────────
AC_TAG_ARTIST    = "#FF6666"
AC_TAG_CHARACTER = "#66BB66"
AC_TAG_COPYRIGHT = "#CC66FF"
AC_TAG_METADATA  = "#FFB533"
