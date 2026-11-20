# booru browser

Desktop app for browsing booru imageboards. Windows only, portable exe.

## Download

Go to [Releases](https://github.com/esefxdz/booru/releases) and grab the latest `.exe`. No installer, no dependencies. Just run it.

## What it does

- Gelbooru and Safebooru built in; add any site running Danbooru, Gelbooru, Moebooru
  (yande.re, konachan), e621, Szurubooru, Philomena, Shimmie2 or Zerochan
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

## Your data

Everything is stored next to the exe, so the folder is portable:
`settings.json` (preferences), `custom_boorus.json` (sites you added),
`bookmarks.db`, and `credentials.bin`. API keys and Cloudflare cookies in
`credentials.bin` are encrypted with Windows DPAPI, which ties them to your
Windows account: on another PC or account you'll need to log in again.

## Running from source

```
pip install -r requirements.txt
python main.py
```

Python 3.12+. VLC or MPV recommended for video playback.

## Tests

```
pip install -r requirements-dev.txt
pytest
```

The suite runs offline and never touches your real settings or credentials.

## Building

```
pip install pyinstaller
python -m PyInstaller BooruBrowser.spec
```

Output is in `dist/`.

## Structure

```
main.py                 Entry point
core/                   Settings, credentials (DPAPI), data folder, validation, event loop
storage/                Thumbnail cache, bookmarks, tag cache (SQLite)
cloudflare_bypasser/    HTTP engine chain, circuit breaker, cookie persistence
adapters/               API parsers per booru type
boorus/                 Booru registry (built-ins + custom_boorus.json)
download_images/        Search, thumbnails, download pipeline, tag categories
ui/                     PyQt6 interface: main window, gallery, viewer, pages, widgets
updater/                Checks GitHub releases for new versions
tests/                  pytest suite
```

More detail in [ARCHITECTURE.md](ARCHITECTURE.md) if you're reading the code.

## Contributing

Pull requests are fine. Adding a new booru means writing a short adapter -- look at the existing ones in `adapters/` to see the pattern.
