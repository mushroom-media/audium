# Changelog

All notable changes to audium are listed here. Versions follow [semantic versioning](https://semver.org/); while audium is 0.x, a new minor version (0.2, 0.3, ...) may need you to read this file before updating, bug-fix releases (0.1.1, ...) never do.

Images: `ghcr.io/mushroom-media/audium:<version>` for linux/amd64 and linux/arm64.

## [Unreleased]

## [0.1.3] - 2026-11-26

### Added
- Playlists: tracks picked automatically (by a smart playlist, "fill automatically" or a saved auto-playlist) are marked with a small spark, "Added automatically".
- Playlists filled automatically can be edited: change the filters and fill the playlist anew with the new selection.
- When the server cannot be reached, a notice says so instead of the page looking broken; audium keeps trying and loads what was missed once the server is back. The desktop app started without network opens with the last session instead of an empty window.
- Settings > Shortcuts: "Seek with ← / →".
- Desktop app for macOS (one app for Apple silicon and Intel) and Linux (AppImage, .deb package), with the same features as on Windows: the top bar as the title bar, "now playing" in full screen, swipe back and forward, updates by itself. On macOS and in the AppImage a new version is put in place in the background and is there at the next start; the .deb package is updated by hand.
- Settings > Connect apps: the download section is now "audium for Windows, macOS and Linux", with a hint for the system you use.

### Changed
- The plain ← / → keys no longer seek 10 seconds unless turned on under Settings > Shortcuts; they are left to the page (lists, sliders). Shift+← / → still skip tracks.

### Fixed
- Artist pictures: an `artist.jpg` in an artist's folder no longer goes to another artist who has an album in that folder (a collaboration, an odd album artist tag, Various Artists).
- Artist page: "Appears on" loads faster in large libraries.
- Linux app: the window belongs to the audium launcher in the dock and task bar (the program is now called `audium`), and the scroll bar no longer covers the last row.

## [0.1.2] - 2026-11-23

### Added
- Settings > About: the version of the server (and of the desktop app), links to the source code, the changelog and the bug reports, and the licenses.
- Desktop app for Windows (`app/`, Tauri): the web interface as a program of its own that connects to your audium server. It has its own versions and releases (`app-v*` tags); see [app/README.md](app/README.md).
- Settings > Connect apps: a section "audium for Windows" with the download link and the server address to enter.
- Desktop app: its own title bar with the search field and the window buttons, like in a browser.
- Desktop app: updates itself. New versions are downloaded in the background and installed when you close the app (or at the next start, if Windows was shut down with the app open). It never closes by itself while you listen; "Update ready" in the top bar offers "Restart now". Apps installed before this version need the new version installed by hand once.
- Desktop app: "Now playing" fills the whole screen; closing it leaves full screen again.
- Desktop app: swipe back and forward, from the window edge on a touch screen or with two fingers on a touchpad.
- Desktop app: links to other sites open in the browser.

### Changed
- Home: "Radios for you" shows only the stations, without the reason below ("Played a lot").
- Settings: the list shows only the names of the pages, without the short description below each.
- The buttons for new smart playlists (home page, sidebar) are gone; existing smart playlists keep working.

### Fixed
- Desktop app: after hours in the background the window could stay black until the app was restarted (WebView2 had ended or lost the page). The app now reloads the page, or restarts itself, and notes it in `%LOCALAPPDATA%\io.github.mushroommedia.audium\logs\webview.log`.

## [0.1.1] - 2026-11-22

### Fixed
- A first start that was stopped while the database was being created (container stopped, NAS restarted) left a half-created database, and audium no longer started (`table ... already exists`). Database upgrades are now all-or-nothing, and such a half-created database without accounts is set aside (`audium.db.unfinished-<time>`) and created again.

### Added
- `AGENTS.md`: installation and setup guide for AI assistants. Paste the repository link into your assistant and it knows how audium is installed.
- `SECURITY.md` (how to report vulnerabilities) and `CONTRIBUTING.md`.
- README: automatic nightly updates with a cron job.

### Changed
- Phones show the volume slider in the now-playing view while they control another device.

## [0.1.0] - 2026-11-22

First public release.

### Library
- One container for large collections (100,000+ tracks), several read-only music folders below `/music`.
- Incremental scanner: unchanged files cost one `stat()`, moved files keep their identity, network shares that are not mounted are marked offline instead of deleted. Scans run in the background, can be cancelled and resumed.
- All common formats (MP3, FLAC, Ogg, Opus, AAC/ALAC, WMA, WAV, AIFF, APE, WavPack, Musepack, DSD, ...); missing tags are filled from the folder structure.
- Covers and artist images, cached as WebP; full-text prefix search that ignores punctuation (`nwa` finds N.W.A., `ac dc` finds AC/DC).

### Listening
- Web player with queue, shuffle, repeat, gapless-style preloading, keyboard shortcuts and Media Session (lock screen, media keys); installable as a PWA.
- Streaming of original files with seeking; on-the-fly transcoding with ffmpeg for formats the browser cannot play, and a lower quality per user for slow connections.
- Remote control between your devices; several browser tabs act as one player.
- Radio from a track, an album or an artist, with feedback.

### Playlists and discovery
- Playlists, favorites, listening history; sharing with individual users as viewer or editor, or with everyone; live updates.
- Smart playlists with a rule editor (several genres per condition, "in the direction of" an artist).
- Auto-playlists without the cloud: normalized genres and styles, decades, activities and moods, and mixes from audio analysis (Essentia: tempo, key, energy, danceability), each track with a short reason. Generated playlists get covers of their own.
- Discover page, similar artists, "Appears on" on artist pages.
- Audio analysis on x86_64; the style models (CC BY-NC-SA 4.0) are downloaded on first use, not shipped.

### Apps
- (Open)Subsonic API under `/rest` for apps like Symfonium, Amperfy or Feishin, with a revocable app password per app.

### Accounts and administration
- Setup wizard in the browser on first start: admin account, music check, permissions.
- Invites, argon2id passwords, login rate limiting, API tokens; own username, display name, avatar color and password.
- Admin area: library folders with folder picker and exclusions, accounts, background jobs.
- English and German, per user.
- Database migrations run on start, with a backup copy of the database first.

[Unreleased]: https://github.com/mushroom-media/audium/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/mushroom-media/audium/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mushroom-media/audium/releases/tag/v0.1.0
