import os
import httpx
import threading
from pathlib import Path
import config

class MediaPlayer:
    def __init__(self, post):
        self.url = post.get('file_url') or post.get('sample_url') or ""
        self.pid = post.get('id', 'temp')
        if self.url.startswith('//'): 
            self.url = 'https:' + self.url

    #background stream thread
    def launch(self, status_callback=None):
        if not self.url: return
        threading.Thread(target=self._stream, args=(status_callback,), daemon=True).start()

    def _stream(self, status_callback):
        try:
            # Setup temp directory
            tmp = Path("./temp_media")
            tmp.mkdir(exist_ok=True)

            ext = os.path.splitext(self.url.split('?')[0])[1] or ".mp4"
            path = tmp / f"view_{self.pid}{ext}"

            # Skip download if file exists
            if path.exists():
                os.startfile(str(path.absolute()))
                return

            if status_callback: status_callback("Streaming...")

            # Use config.HEADERS to stay consistent with the downloader
            with httpx.stream("GET", self.url, headers=config.HEADERS, follow_redirects=True) as r:
                with open(path, "wb") as f:
                    for i, chunk in enumerate(r.iter_bytes(chunk_size=8192)):
                        f.write(chunk)
                        f.flush()
                        
                        # Open the file as soon as we have enough data to buffer
                        if i == 32: 
                            os.startfile(str(path.absolute()))
                            if status_callback: status_callback("Playing...")
            
            if status_callback: status_callback("Ready")
        except:
            if status_callback: status_callback("Stream Failed")