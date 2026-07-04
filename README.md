# Booru Browser

just a desktop client i made for browsing booru imageboards (gelbooru, danbooru, safebooru, etc.) without having to deal with their web interfaces or ads.

i mostly built this because doing bulk downloads and organizing tags manually is annoying. it's written in python using pyqt6.

## download

if you just want to use the app, you don't need to mess with python. **check the releases tab for the standalone `.exe`**. no install needed, just run it. 

## features

* **tag searching**: search multiple supported boorus with standard tag syntax.
* **smart downloads**: automatically sorts your downloaded images into folders based on tags (like grouping by artist or character).
* **built-in media player**: view images, gifs, and videos directly in the app without launching a browser.
* **bookmarks & favorites**: keep track of posts and save them locally.
* **cloudflare bypass**: boorus love to throw up cloudflare checks. this app rotates through a few http engines (like `curl_cffi`) to spoof a real browser's tls so you don't get blocked while scrolling.
* **smooth gallery**: scrolling doesn't lag even with thousands of posts because it caches thumbnails locally in sqlite and recycles ui widgets instead of rendering everything at once.

## running from source

if you want to run the code yourself instead of using the exe:

1. make sure you have python 3.12 or newer installed.
2. install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. run the app:
   ```bash
   python main.py
   ```

*note: for the best video playback support, you'll probably want VLC installed on your system so the app can hook into it.*

## contributing / for devs

this is a side project, but i tried to keep the code organized and modular. there's a [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) that explains the architecture and how things work under the hood. read that before you start digging around.

feel free to open an issue or submit a pull request if you want to fix a bug, add a feature, or write an adapter for a new booru site.
