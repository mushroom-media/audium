# AGENTS.md

Guide for AI assistants. Someone pasted the link to this repository and wants help with audium: usually installing and setting it up, sometimes connecting apps, updating or fixing a problem. This file says what audium is, how to install it and where things go wrong. Details are in [README.md](README.md) and [docs/](docs/). If you are working **on the code**, read the last section.

## What audium is

- A self-hosted music streaming server for the user's own music files, like a private Spotify for their own MP3/FLAC collection. One Docker container, web interface in the browser, built for large libraries (100,000+ tracks).
- Runs on a home server, NAS, mini PC or Raspberry Pi (x86_64 or arm64). It works without the internet and sends no telemetry.
- **It never changes the music files.** Music is mounted read-only. Everything audium creates (database, cover cache, backups) lives in one `data` folder.
- Features: web player (installable as a PWA), playlists and sharing between users, smart and auto-playlists, radio, audio analysis (x86_64 only), English and German UI, and the (Open)Subsonic API, so phone apps like Symfonium (Android) or Amperfy (iOS) work with it.
- License: server AGPL-3.0, web frontend MIT. Free, no account with anyone needed.

## What the user needs

- **Docker with Compose**: Docker Engine + Compose plugin on Linux; Docker Desktop on Windows/macOS; the built-in container app on a NAS (Synology Container Manager, Unraid, TrueNAS, Portainer, ...). Check with `docker compose version`.
- **The music folder's path** on that machine, e.g. `/srv/music`, `/volume1/music` (Synology), `/mnt/user/media/music` (Unraid), `C:/Users/<name>/Music` (Windows, forward slashes).
- **A free port.** Default 8091. audium always listens on 8080 inside the container.
- About 1.6 GB of disk for the image (x86_64), plus space in `data` for the database and the cover cache, which grow with the library.

Ask the user for the music path and which system they use before giving commands. Do not guess paths.

## Installation (standard way)

No `git clone` needed. Two files from this repository are enough, and the image comes ready built from `ghcr.io/mushroom-media/audium`.

```bash
mkdir audium && cd audium
curl -fLO https://raw.githubusercontent.com/mushroom-media/audium/main/docker-compose.yml
curl -fL -o .env https://raw.githubusercontent.com/mushroom-media/audium/main/.env.example
```

Edit `.env`:

```ini
AUDIUM_HOST_PORT=8091              # port on the host
AUDIUM_MUSIC_PATH=/srv/music       # the user's music folder (uncomment the line!)
TZ=Europe/Berlin                   # time zone
```

Make the data folder writable for the container user (uid 1000), then start:

```bash
mkdir -p data && sudo chown -R 1000:1000 data    # Linux/NAS; not needed with Docker Desktop on Windows/macOS
docker compose up -d
docker compose logs -f                          # optional: watch the start (Ctrl+C only stops watching)
```

**NAS with a web UI and no terminal:** create a new "project"/"stack", paste the content of `docker-compose.yml`, replace `${AUDIUM_MUSIC_PATH:-./music}` with the real music path and `./data` with a folder on the NAS (for example `/volume1/docker/audium/data`). That folder must be writable for uid 1000. If that is awkward, set `user: "<uid>:<gid>"` in the compose file to the user who owns the folder (`id -u` / `id -g`).

**Several music folders:** add one volume line per folder below `/music`, each read-only:

```yaml
      - /srv/music:/music/main:ro
      - /mnt/nas/music:/music/nas:ro
```

Each folder directly below `/music` becomes its own library folder. audium can only see what is mounted here.

## First start and setup (in the browser)

1. Open `http://<server-ip>:8091` **within 30 minutes** of starting the container. After that time the setup is locked for safety; `docker compose restart` gives another 30 minutes.
2. Create the admin account. **Whoever opens a new instance first becomes the admin.** If the server can be reached from the internet, turn on port forwarding only after this step, or set `AUDIUM_ADMIN_USER` and `AUDIUM_ADMIN_PASSWORD` in `.env` before the first start (and remove them afterwards).
3. A short dialog follows: which music folders to use (a trial scan shows what audium found), the audio analysis, connections to the outside (such as similar artists from ListenBrainz) and apps.
4. audium then scans in the background. The user can browse and listen while it runs. For about 100,000 files the first scan takes minutes; audio analysis afterwards takes hours, at the lowest CPU priority.

Further accounts: Settings > Users (create directly or send an invite link). Every user picks their own language under Settings.

## Phone and desktop apps

- **Web app:** in the phone browser, "Add to home screen". This needs HTTPS for full PWA support, so use a reverse proxy.
- **Subsonic apps** (Symfonium, Tempo, DSub, Ultrasonic on Android; Amperfy, play:Sub on iOS; Feishin, Supersonic on desktop): in audium, go to Settings > Connect apps > Connect an app. audium shows the server address, the username and a one-time **app password**. Enter these three in the app as a "Subsonic"/"OpenSubsonic" server. The normal login password does **not** work in apps, on purpose. Details: [docs/apps.md](docs/apps.md).
- **From outside the home network:** use HTTPS through a reverse proxy (Caddy, nginx, Traefik; examples in [docs/reverse-proxy.md](docs/reverse-proxy.md)) or a VPN such as Tailscale/WireGuard. Do not expose port 8091 directly to the internet over plain HTTP.

## Updating and backups

```bash
docker compose pull && docker compose up -d
```

- The tag `0.1` in `docker-compose.yml` receives bug fixes automatically. For a new version (0.2, ...), read [CHANGELOG.md](CHANGELOG.md) first, then change the tag.
- Database migrations run on start. Before each one, audium saves a copy of the database in `data/backups/`.
- **Backup** = the `data` folder, above all `audium.db` and `secret.key` (`data/covers` can be skipped, a scan rebuilds it). The music needs no audium backup, because audium never writes to it.

## Configuration

All optional, as environment variables in `docker-compose.yml` (`environment:`) or `.env`. Full list: [docs/configuration.md](docs/configuration.md). The most common:

| Variable | Purpose |
|---|---|
| `AUDIUM_ADMIN_USER`, `AUDIUM_ADMIN_PASSWORD` | create the admin on first start instead of in the browser |
| `AUDIUM_BASE_PATH` | serve under a sub-path behind a proxy, e.g. `/audium` |
| `AUDIUM_TRUSTED_PROXIES` | trust `X-Forwarded-*` from the reverse proxy (`*` if only the proxy can reach the container) |
| `AUDIUM_SCAN_INTERVAL_MINUTES` | periodic rescan, default 360, `0` = off |
| `AUDIUM_ANALYSIS_ENABLED` | `false` turns the audio analysis off (weak hardware) |

## Troubleshooting

Look first: `docker compose ps` (status) and `docker compose logs --tail 100 audium` (logs, one JSON line per event; look at `"level": "error"` and the `hint` field). Health: `curl http://localhost:8091/api/health`.

| Symptom | Cause and fix |
|---|---|
| Container stops right away, log `startup.data_dir_not_writable` | `data` is not writable for uid 1000: `sudo chown -R 1000:1000 data`, or set `user:` in the compose file |
| Browser shows "audium is starting" | normal for a few seconds (migrations); wait |
| Setup page says the time is over | the 30 minutes have passed: `docker compose restart`, then open it right away |
| No music found / folder empty | wrong path in `AUDIUM_MUSIC_PATH`, or uid 1000 cannot read the music: check `docker compose exec audium ls /music/main` |
| Network share shown as offline | the share was not mounted on the host when the container started; mount it and rescan (the tracks are kept meanwhile) |
| Port already in use | change `AUDIUM_HOST_PORT` in `.env`, then `docker compose up -d` |
| App: "wrong username or password" | use the app password from Settings > Connect apps, not the login password |
| Forgot the admin password | `docker exec -it audium audium admin reset-password <username>` prints a new one |
| No moods/tempo mixes on a Raspberry Pi / arm64 | audio analysis exists for x86_64 only; everything else works |
| 0.1.0 does not start after a first start was stopped half-way (`table ... already exists`) | fixed in 0.1.1: update. On 0.1.0, delete `data/audium.db*` if no account was created yet |

## Rules for assistants

- **Never** suggest mounting the music folder without `:ro`, and never run commands that write to the user's music folder. audium does not need write access.
- Do not delete `data/` or `audium.db` to "fix" something if the user has accounts or playlists. Point to `data/backups/` instead.
- Do not suggest exposing audium to the internet without HTTPS or a VPN.
- Ask for the user's system, paths and port; do not invent them. Commands for Linux/NAS differ from Docker Desktop on Windows/macOS (no `sudo chown` there, paths with forward slashes).
- The audio analysis models are downloaded from essentia.upf.edu on first use and are licensed non-commercially (CC BY-NC-SA 4.0). That is fine for private use; mention it if the user plans something commercial.

## Working on the code

- Development setup, tests and layout: [docs/development.md](docs/development.md). Everything runs in Docker (`docker-compose.dev.yml`); `docker-compose.build.yml` builds the image from source.
- Backend: Python 3.12, FastAPI, SQLAlchemy Core, SQLite, Alembic. Frontend: Svelte 5 + Vite + TypeScript.
- Before a commit: `ruff check`, `ruff format --check` and `pytest` in the dev container, plus `npm run check` and `npm test` in `frontend/`. CI runs the same.
- Migrations only append: never change a released migration, always add a new one. Real installations upgrade through all of them.
- UI texts are German in the source and translated in `frontend/src/lib/i18n/en.ts` (server-side texts in `backend/audium/i18n.py`). New texts need both.
