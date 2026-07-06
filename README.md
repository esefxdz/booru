# booru browser

a desktop client for browsing booru imageboards (gelbooru, danbooru, safebooru, etc.) without having to deal with their web interfaces or ads.

i built this because doing bulk downloads and organizing tags manually is annoying. written in python using pyqt6.

## download

if you just want to use the app, you don't need to mess with python. check the releases tab for the standalone `.exe`. no install needed, just run it.

## usage

once you launch the app, simply select a site from the server bar on the left (like gelbooru or danbooru), type your tags in the search bar at the top, and hit enter. the app will seamlessly handle api routing and bypass cloudflare checks in the background.

double click any thumbnail to view the full resolution image or video. click the download button on the bottom panel to save it locally.

## features

- **tag searching**: search multiple supported boorus with standard tag syntax.
- **smart downloads**: automatically sorts your downloaded images into folders based on tags (like grouping by artist or character).
- **built-in media player**: view images, gifs, and videos directly in the app without launching a browser.
- **bookmarks & favorites**: keep track of posts and save them locally.
- **cloudflare bypass**: boorus love to throw up cloudflare checks. this app rotates through different http engines to spoof a real browser's tls so you don't get blocked while scrolling.
- **smooth gallery**: scrolling doesn't lag even with thousands of posts. it caches thumbnails locally in sqlite and recycles ui widgets instead of rendering everything at once.

## running from source

if you want to run the code yourself instead of using the exe:

1. install python 3.12 or newer.
2. install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. run the app:
   ```bash
   python main.py
   ```

*note: for the best video playback support, you'll probably want vlc installed on your system so the app can hook into it.*

## contributing

this is a side project, but i tried to keep the code organized and modular. feel free to open an issue or submit a pull request if you want to fix a bug, add a feature, or write an adapter for a new booru site.
