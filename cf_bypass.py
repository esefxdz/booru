import webview
import sys
import json
import time
import threading

def main():
    if len(sys.argv) < 2:
        print("Usage: python cf_bypass.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    result_data = {}
    
    def check_cookies(window):
        # We need to poll for cf_clearance because it might take a few seconds after the user solves the captcha
        for _ in range(60): # wait up to 60 seconds for the user to solve it
            try:
                cookies = window.get_cookies()
                
                # Debug dump
                try:
                    with open("cookies_debug.txt", "a") as f:
                        f.write(f"[{time.time()}] Cookies found: {[('cf_clearance' in c) for c in cookies]} | Raw keys: {[list(c.keys()) for c in cookies]}\n")
                except: pass

                for c in cookies:
                    if 'cf_clearance' in c:
                        result_data['cf_clearance'] = c['cf_clearance'].value
                        window.destroy()
                        return
            except Exception:
                pass
            time.sleep(1)
            
    def on_loaded():
        if 'user_agent' not in result_data:
            ua = window.evaluate_js('navigator.userAgent')
            result_data['user_agent'] = ua if ua else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        threading.Thread(target=check_cookies, args=(window,), daemon=True).start()
            
    window = webview.create_window('Cloudflare Bypass (Solve Captcha)', url, width=800, height=600)
    window.events.loaded += on_loaded
    
    webview.start()
    
    if result_data:
        print(json.dumps(result_data))
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
