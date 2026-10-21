# audium

Self-hosted music streaming for your own library: one Docker container, built for large collections (100,000+ tracks) on a home server or NAS. No cloud, no telemetry, works offline in your LAN.

> **Status: early development (phase 3 of 5).** Library scanning, accounts, streaming, the web player, playlists and sharing work. Auto-playlists (audio analysis) and the admin UI follow. See [docs/plan.md](docs/plan.md).

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

## Features so far

- **Formats:** MP3, FLAC, Ogg Vorbis, Opus, AAC/M4A, ALAC, WMA, WAV, AIFF, APE, WavPack, Musepack, DSD and more. Broken or untagged files never stop a scan; missing tags are filled from the folder structure (`Artist/Album (Year)/01 - Title.ext`).
- **Incremental scanner:** unchanged files cost one `stat()`; moved files keep their identity; scans run in the background, show progress, and can be cancelled and resumed.
- **Covers:** extracted once (embedded or `cover.jpg`/`folder.jpg`), cached as WebP in 64/256/600 px.
- **Fast API at scale:** paginated lists, full-text prefix search, OpenAPI docs at `/api/docs`.
- **Accounts:** first user is admin, invites, argon2id passwords, login rate limiting, API tokens.
- **Streaming:** original files with HTTP Range (instant seeking, little RAM); formats the browser cannot play (WMA, APE, ...) are transcoded on the fly with ffmpeg to Opus/AAC/MP3. Lower streaming quality per user for slow connections.
- **Web player:** virtual scrolling through 100k+ tracks, search as you type, persistent player with queue, shuffle, repeat, keyboard shortcuts and Media Session (lock screen, Bluetooth and media keys).
- **Playlists & sharing:** your own playlists, favorites and listening history; share a playlist with individual users as viewer or editor, or make it visible to everyone. Changes by others appear live (Server-Sent Events). Permissions are enforced on the server and covered by tests.

## Configuration

Environment variables, all optional: see [docs/configuration.md](docs/configuration.md). Reverse proxy under a sub-path: set `AUDIUM_BASE_PATH=/audium` and `AUDIUM_TRUSTED_PROXIES`.

Health check: `GET /api/health` (used by the Docker `HEALTHCHECK`). Logs are JSON lines on stdout.

## Development

See [docs/development.md](docs/development.md). Design decisions: [docs/decisions.md](docs/decisions.md).

## License

[AGPL-3.0-or-later](LICENSE).
