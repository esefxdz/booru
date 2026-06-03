"""Quick diagnostic — run from project root: python cloudflare_bypasser/_debug_test.py"""
import logging
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ui import settings_view as settings
settings.manager.load()

import boorus
logging.info(f"Active booru: {settings.manager.active_booru}")
for name in list(boorus.REGISTRY.keys())[:8]:
    d = boorus.REGISTRY[name]
    logging.info(f"  {name}: {d.get('url')} ({d.get('api_type')})")

logging.info()
from cloudflare_bypasser import get_session
from cloudflare_bypasser import store as st

for name in list(boorus.REGISTRY.keys())[:5]:
    d = boorus.REGISTRY[name]
    url = d.get("url", "").rstrip("/")
    has_bypass = st.has_active_bypass(name)
    logging.info(f"\n--- {name} (bypass={has_bypass}) ---")
    s = get_session(name)
    try:
        r = s.get_sync(url, timeout=10)
        logging.info(f"  GET {url} => {r.status_code} ({len(r.text)} bytes)")
    except Exception as e:
        logging.error(f"  GET {url} => FAILED: {e}")
