# audium

Self-hosted music streaming for your own library: one Docker container, built for large collections (100,000+ tracks) on a home server or NAS. No cloud, no telemetry, works offline in your LAN.

> **Status: 0.1, first release.** The features below work; expect rough edges. Roadmap and design: [docs/plan.md](docs/plan.md).

## Quickstart

```bash
git clone <repository-url> audium && cd audium
cp .env.example .env    # set AUDIUM_MUSIC_PATH (port: AUDIUM_HOST_PORT, default 8091)
docker compose up -d --build
docker compose logs audium | grep setup_token
```

Open `http://<server>:8091`, enter the setup token from the log and create your admin account. audium scans your music in the background; you can browse and listen while it runs.

Prefer to skip the token? Set `AUDIUM_ADMIN_USER` and `AUDIUM_ADMIN_PASSWORD` for the first start.

## Your music, read-only

audium only sees folders you mount into the container, and it mounts them read-only: it never changes or deletes your files.

```yaml
volumes:
  - ./data:/data                    # database and cover cache (back this up)
  - /srv/music:/music/main:ro
  - /mnt/nas/music:/music/nas:ro    # as many as you like
```

Each folder directly below `/music` becomes a library folder. If a network share is not mounted during a scan, audium marks it offline and keeps its tracks, instead of treating your music as deleted. In the admin area you can add, disable or exclude folders, but only inside what is mounted.

## Features

- **Formats:** MP3, FLAC, Ogg Vorbis, Opus, AAC/M4A, ALAC, WMA, WAV, AIFF, APE, WavPack, Musepack, DSD and more. Broken or untagged files never stop a scan; missing tags are filled from the folder structure (`Artist/Album (Year)/01 - Title.ext`).
- **Incremental scanner:** unchanged files cost one `stat()`; moved files keep their identity; scans run in the background, show progress, and can be cancelled and resumed.
- **Covers:** extracted once (embedded or `cover.jpg`/`folder.jpg`), cached as WebP in 64/256/600 px.
- **Artist images:** `artist.jpg` or `artist.png` in the artist folder (`Artist/artist.jpg` next to `Artist/Album/`), or in the album folder for flat layouts; otherwise the newest album's cover.
- **Fast API at scale:** paginated lists, full-text prefix search, OpenAPI docs at `/api/docs`.
- **Accounts:** first user is admin, invites, argon2id passwords, login rate limiting, API tokens.
- **Streaming:** original files with HTTP Range (instant seeking, little RAM); formats the browser cannot play (WMA, APE, ...) are transcoded on the fly with ffmpeg to Opus/AAC/MP3. Lower streaming quality per user for slow connections.
- **Web player:** virtual scrolling through 100k+ tracks, search as you type, persistent player with queue, shuffle, repeat, keyboard shortcuts and Media Session (lock screen, Bluetooth and media keys).
- **Auto-playlists without the cloud:** genres (normalized), decades, "Rock der 90er", activity and mood lists ("Workout", "Zum Entspannen", ...) and mixes from audio analysis (Essentia: tempo, key, energy, danceability, brightness), each track with a short reason ("128 BPM · hohe Energie"). The admin publishes suggestions and controls who sees them; everyone can save a copy. Smart playlists with your own rules, "similar tracks" and radio from any track.
- **Playlists & sharing:** your own playlists, favorites and listening history; share a playlist with individual users as viewer or editor, or make it visible to everyone. Changes by others appear live (Server-Sent Events). Permissions are enforced on the server and covered by tests.
- **App on your phone:** installable as a PWA (needs HTTPS, see [reverse proxy](docs/reverse-proxy.md)), light and dark theme, works on small screens. The next track is preloaded, so albums play without pauses between tracks.
- **Subsonic apps:** the (Open)Subsonic API under `/rest` lets apps like Symfonium, Amperfy or Feishin play from audium, with offline downloads and CarPlay / Android Auto, using the same favorites, playlists and history. Each app gets its own revocable app password ([docs/apps.md](docs/apps.md)).
- **Admin area:** add library folders with a folder picker, exclude sub-folders, create and lock accounts, reset passwords, invite links, and see what the background jobs are doing.

## Updating and backups

```bash
git pull && docker compose up -d --build
```

Database migrations run automatically on start; audium copies the database to `data/backups/` first. To back up, copy the `data` folder (the cover cache in `data/covers` can be skipped, it is rebuilt by a scan). Your music is never written to, so it needs no audium-specific backup.

## Hardware

Any x86_64 or arm64 machine with Docker. In testing, the first scan of 100,000 files took about 4 minutes and a rescan without changes 17 seconds (SSD; a network share is slower). Audio analysis runs afterwards at low priority; for a large library it takes hours, but you can listen meanwhile. Audio analysis (Essentia) is available on x86_64 only; on arm64 everything else works.

## Configuration

Environment variables, all optional: see [docs/configuration.md](docs/configuration.md). HTTPS, sub-paths and examples for Caddy, nginx and Traefik: [docs/reverse-proxy.md](docs/reverse-proxy.md).

Health check: `GET /api/health` (used by the Docker `HEALTHCHECK`). Logs are JSON lines on stdout.

## Development

See [docs/development.md](docs/development.md). Design decisions: [docs/decisions.md](docs/decisions.md).

## License

The server (`backend/`, the Docker image) is [AGPL-3.0-or-later](LICENSE).
The web frontend (`frontend/`), which the audium apps are built from, is [MIT](frontend/LICENSE).
