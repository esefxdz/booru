# booru browser

Desktop app for browsing booru imageboards. Windows only, portable exe.

## Download

Go to [Releases](https://github.com/esefxdz/booru/releases) and grab the latest `.exe`. No installer, no dependencies. Just run it.

## What it does

- Search 15+ boorus (Gelbooru, Danbooru, Safebooru, e621, and others) from one app
- Browse results in a scrollable gallery
- View images, GIFs, and videos fullscreen
- Download posts individually or in bulk
- Bookmarks, favorites, and a tag blacklist

## Cloudflare

Most boorus sit behind Cloudflare. The app tries to get through automatically using a chain of HTTP engines that mimic a real browser. If that fails, it opens an embedded browser window where you solve the challenge once. After that, the cookie is saved and requests go through normally.

## Settings

- Concurrent downloads and rate limiting
- Proxy support
- Custom download path
- Smart folders (sort downloads by artist, character, etc.)
- Per-site API keys for accounts

## Running from source

```
pip install -r requirements.txt
python main.py
```

Python 3.12+. VLC or MPV recommended for video playback.

## Building

```
pip install pyinstaller
python -m PyInstaller BooruBrowser.spec
```

Output is in `dist/`.

## Structure

```
cloudflare_bypasser/    HTTP engine chain + cookie persistence
adapters/               API parsers per booru type
boorus/                 Site URLs and configs
download_images/        Search, thumbnails, download pipeline
displayers/             Image viewer, video player, sidebar
ui/                     Gallery, search bar, settings, autocomplete
updater/                Checks GitHub releases for new versions
tests/                  Unit tests
```

More detail in [ARCHITECTURE.md](ARCHITECTURE.md) if you're reading the code.

## Contributing

Pull requests are fine. Adding a new booru means writing a short adapter -- look at the existing ones in `adapters/` to see the pattern.
