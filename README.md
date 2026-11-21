# audium

Self-hosted music streaming for your own library: one Docker container, built for large collections (100,000+ tracks) on a home server or NAS. No cloud, no telemetry, works offline in your LAN.

> **Status: 0.1, first release.** The features below work; expect rough edges.

## Quickstart

You need Docker with the Compose plugin. No need to clone the repository: two files are enough.

```bash
mkdir audium && cd audium
curl -fLO https://raw.githubusercontent.com/mushroom-media/audium/main/docker-compose.yml
curl -fL -o .env https://raw.githubusercontent.com/mushroom-media/audium/main/.env.example
# edit .env: AUDIUM_MUSIC_PATH = your music folder (default: ./music), AUDIUM_HOST_PORT (default: 8091)
mkdir -p data && sudo chown 1000:1000 data    # the container runs as uid 1000
docker compose up -d
```

The image (`ghcr.io/mushroom-media/audium`) is built for x86_64 and arm64. On a NAS with a Docker UI (Synology Container Manager, Unraid, Portainer, ...) you can paste `docker-compose.yml` as a new project instead and set the music folder there.

Open `http://<server>:8091` within 30 minutes. A short dialog creates your admin account, checks that audium sees your music and shows what it found, and asks what audium may do. It then scans your music in the background; you can browse and listen while it runs.

**Reachable from the internet right away?** Whoever opens a new instance first becomes its admin. Switch on port forwarding only after the setup, or set `AUDIUM_ADMIN_USER` and `AUDIUM_ADMIN_PASSWORD` for the first start.

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
- **Artist images:** `artist.jpg` or `artist.png` in the artist folder (`Artist/artist.jpg` next to `Artist/Album/`), or in the album folder for flat layouts; without one, a `folder.jpg` in the artist folder (can be turned off by admins); otherwise the newest album's cover.
- **Fast API at scale:** paginated lists, full-text prefix search, OpenAPI docs at `/api/docs`.
- **Accounts:** first user is admin, invites, argon2id passwords, login rate limiting, API tokens.
- **Streaming:** original files with HTTP Range (instant seeking, little RAM); formats the browser cannot play (WMA, APE, ...) are transcoded on the fly with ffmpeg to Opus/AAC/MP3. Lower streaming quality per user for slow connections.
- **Web player:** virtual scrolling through 100k+ tracks, search as you type, persistent player with queue, shuffle, repeat, keyboard shortcuts and Media Session (lock screen, Bluetooth and media keys).
- **Auto-playlists without the cloud:** genres (normalized), decades, "Rock of the 90s", activity and mood lists ("Workout", "To relax", ...) and mixes from audio analysis (Essentia: tempo, key, energy, danceability, brightness), each track with a short reason ("128 BPM · high energy"). The admin publishes suggestions and controls who sees them; everyone can save a copy. Smart playlists with your own rules, "similar tracks" and radio from any track.
- **Playlists & sharing:** your own playlists, favorites and listening history; share a playlist with individual users as viewer or editor, or make it visible to everyone. Changes by others appear live (Server-Sent Events). Permissions are enforced on the server and covered by tests.
- **App on your phone:** installable as a PWA (needs HTTPS, see [reverse proxy](docs/reverse-proxy.md)), light and dark theme, works on small screens. The next track is preloaded, so albums play without pauses between tracks.
- **Subsonic apps:** the (Open)Subsonic API under `/rest` lets apps like Symfonium, Amperfy or Feishin play from audium, with offline downloads and CarPlay / Android Auto, using the same favorites, playlists and history. Each app gets its own revocable app password ([docs/apps.md](docs/apps.md)).
- **English and German:** the setup picks the server language; every user can choose their own in the settings. Generated playlist names ("Workout", "The 90s") follow each user's language.
- **Admin area:** add library folders with a folder picker, exclude sub-folders, create and lock accounts, reset passwords, invite links, and see what the background jobs are doing.

## Updating and backups

```bash
docker compose pull && docker compose up -d
```

The image tag `0.1` in `docker-compose.yml` follows the bug-fix releases of 0.1. For a new version (0.2, ...), read the [changelog](CHANGELOG.md) and change the tag. Database migrations run automatically on start; audium copies the database to `data/backups/` first. To back up, copy the `data` folder (the cover cache in `data/covers` can be skipped, it is rebuilt by a scan). Your music is never written to, so it needs no audium-specific backup.

## Hardware

Any x86_64 or arm64 machine with Docker. In testing, the first scan of 100,000 files took about 4 minutes and a rescan without changes 17 seconds (SSD; a network share is slower). Audio analysis runs afterwards at low priority; for a large library it takes hours, but you can listen meanwhile. Audio analysis (Essentia) is available on x86_64 only; on arm64 everything else works.

## Configuration

Environment variables, all optional: see [docs/configuration.md](docs/configuration.md). HTTPS, sub-paths and examples for Caddy, nginx and Traefik: [docs/reverse-proxy.md](docs/reverse-proxy.md).

Health check: `GET /api/health` (used by the Docker `HEALTHCHECK`). Logs are JSON lines on stdout.

## Development

See [docs/development.md](docs/development.md). To run your own build of the image: `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build` in a clone of the repository.

## License

The server (`backend/`, the Docker image) is [AGPL-3.0-or-later](LICENSE).
The web frontend (`frontend/`), which the audium apps are built from, is [MIT](frontend/LICENSE).
