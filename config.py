from pathlib import Path

# --- CORE SETTINGS ---
ACTIVE_BOORU = "safebooru"
SEARCH_LIMIT = 50
TIMEOUT = 30.0

# Directory where images are saved
DOWNLOAD_DIR = Path("files")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# --- BOORU DATABASE ---
BOORUS = {
    "safebooru": {"url": "https://safebooru.org",   "api_path": "/index.php", "post_key": None},
    "gelbooru":  {"url": "https://gelbooru.com",     "api_path": "/index.php", "post_key": "post"},
    "rule34":    {"url": "https://api.rule34.xxx",  "api_path": "/index.php", "post_key": None},
    "realbooru": {"url": "https://realbooru.com",   "api_path": "/index.php", "post_key": None},
    "hypnohub":  {"url": "https://hypnohub.net",    "api_path": "/index.php", "post_key": None},
    "xbooru":    {"url": "https://xbooru.com",      "api_path": "/index.php", "post_key": None}
}

# API Credentials
CREDENTIALS = {
    'gelbooru': {'api_key': '', 'user_id': ''},
    'rule34': {'api_key': '123', 'user_id': '123'},
    'safebooru': {'api_key': '123', 'user_id': '123'}
}

# --- NETWORK SETTINGS ---
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

# --- SEARCH & UI ---
SEARCH_TAGS = "scenery"  # Added to prevent main.py from crashing
BLACKLIST = ""
THUMBNAIL_SIZE = 250
PREVIEW_QUALITY = "sample_url"