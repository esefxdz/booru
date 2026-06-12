# Booru Browser

Just a desktop client I made for browsing booru imageboards (Gelbooru, Danbooru, etc.) without having to deal with their web interfaces or ads. 

I mostly built this to make searching, viewing, and organizing images a bit easier and faster natively. It's written in Python using PyQt6.

## Features

* **Tag Searching**: Search multiple supported boorus with your standard tag syntax.
* **Smart Downloads**: Automatically sorts your downloaded images into folders based on their tags (like grouping by artist or character).
* **Built-in Media Player**: View images, GIFs, and videos directly in the app without launching a browser.
* **Bookmarks & Favorites**: Keep track of posts and save them locally.
* **Cloudflare Bypass**: Boorus love to throw up Cloudflare checks. This app has a few workarounds built-in (like spoofing Chrome TLS) to handle that so you don't get blocked while scrolling.
* **Smooth Gallery**: Scrolling doesn't lag, even if you load thousands of posts, because it recycles the UI widgets instead of drawing them all at once.

## Running from Source

If you want to run the code yourself:

1. Make sure you have Python installed.
2. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   python main.py
   ```

*Note: For the best video playback support, you'll probably want VLC installed on your system so the app can hook into it.*

## How it works

It's a pretty standard PyQt6 app. When you search, it hits the booru's public API to get the posts. To keep the app from lagging or eating all your RAM while you scroll, it caches thumbnails locally using SQLite and handles images in the background.

For the Cloudflare stuff, it rotates between a few HTTP engines (like `curl_cffi` and `cloudscraper`) to look like a real browser to the server.

## Contributing

This is basically just a side project in an alpha state, so expect some bugs or weird edge cases. Feel free to open an issue or submit a pull request if you want to fix something, add a feature, or write an adapter for a new booru site.
