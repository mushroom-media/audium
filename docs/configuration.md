# Configuration

All settings are environment variables with the prefix `AUDIUM_`. Defaults fit the Docker image.

## Paths

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_DATA_DIR` | `/data` | Database, cover cache, backups. Must be writable by the container user (uid 1000). |
| `AUDIUM_MUSIC_DIR` | `/music` | Where music is mounted (read-only). Library folders must lie inside it. |
| `AUDIUM_DATABASE_URL` | `sqlite:///<data>/audium.db` | SQLAlchemy URL. Only SQLite is supported today. |

## HTTP and reverse proxy

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_PORT` | `8080` | Listen port inside the container. |
| `AUDIUM_HOST` | `0.0.0.0` | Listen address. |
| `AUDIUM_BASE_PATH` | *(empty)* | Serve under a sub-path, e.g. `/audium`. The proxy must forward the full path (do not strip the prefix). |
| `AUDIUM_TRUSTED_PROXIES` | `127.0.0.1` | Comma-separated proxy IPs whose `X-Forwarded-For/-Proto` headers are trusted. Use `*` if only your proxy can reach the container. |
| `AUDIUM_COOKIE_SECURE` | `auto` | `auto` sets the `Secure` cookie flag when the request (as seen through the proxy) is HTTPS. `true`/`false` force it. |
| `AUDIUM_ACCESS_LOG` | `false` | Log every HTTP request. |
| `AUDIUM_API_DB_READERS` | `1` | Database reads the API runs at the same time. SQLite reads take milliseconds, and parallel connections in one process slow each other down (measured: 1 reader 41 req/s, 4 readers 25 req/s), so the default queues them. |

## Logging

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |
| `AUDIUM_LOG_FORMAT` | `json` | `json` (one JSON object per line) or `console` (human readable). |

## Accounts

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_ADMIN_USER` / `AUDIUM_ADMIN_PASSWORD` | *(unset)* | Create this admin on first start instead of using the setup token. Ignored once any user exists. |
| `AUDIUM_SESSION_TTL_DAYS` | `30` | Sessions expire after this many days without use. |
| `AUDIUM_LOGIN_MAX_ATTEMPTS` | `10` | Failed logins per username within the window before it is blocked (per IP: 3×). |
| `AUDIUM_LOGIN_WINDOW_MINUTES` | `15` | Rate-limit window. |

**First start without `AUDIUM_ADMIN_*`:** the log contains a line with `setup_token`. Open audium and enter it to create the admin account. A new token is generated on every start until the admin exists.

**Locked out?** `docker exec -it audium audium admin reset-password <username>` prints a new password.

## Library and scanner

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_LIBRARY_ROOTS` | *(unset)* | Comma-separated library folders to add on first start. Default: every top-level folder of `/music` (or `/music` itself if it has no sub-folders). Manage them later in the admin UI. |
| `AUDIUM_SCAN_ON_START` | `true` | Run an incremental scan when the container starts. |
| `AUDIUM_SCAN_INTERVAL_MINUTES` | `360` | Periodic incremental scan; `0` disables it. An unchanged library costs one `stat()` per file. |
| `AUDIUM_SCAN_WORKERS` | `4` | Parallel tag-reader processes (and cover threads). Raise for network shares with high latency, lower on a Raspberry Pi with little RAM. |
| `AUDIUM_MISSING_GRACE_DAYS` | `7` | Tracks whose files disappeared are hidden immediately and deleted from the database after this many days. Playlists and favorites survive a temporarily missing file. |
| `AUDIUM_IGNORED_ARTICLES` | `The El La Los Las Le Les Os As O A` | Leading words ignored when sorting artists ("The Beatles" sorts under B). |

## Audio analysis and auto-playlists

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_ANALYSIS_ENABLED` | `true` | Analyse audio (tempo, key, energy, ...) with Essentia in the background. Tag-based auto-playlists (genre, decade) work without it. |
| `AUDIUM_ANALYSIS_WORKERS` | `1` | Parallel analysis processes. They run at the lowest CPU priority (nice 19); 1 is gentle, 4 analyses about 100 tracks a minute on a typical desktop CPU. |

Analysis needs Essentia, which exists for **x86_64 only**. On arm64 (Raspberry Pi, many NAS) audium runs without it and says so in the admin settings; genre and decade playlists, smart playlists over tags and the radio (by genre/year) still work.

**Mood models (optional, experimental):** the `:ml` image variant (`docker build --build-arg AUDIUM_ML=1 .`) contains Essentia with TensorFlow. Download Essentia's MusiCNN mood classifiers yourself (`mood_happy-msd-musicnn-1.pb`, `mood_sad-...`, `mood_aggressive-...`, `mood_relaxed-...` plus their `.json` files) into `/data/models`. They are licensed for non-commercial use only, which is why audium does not ship them.

New auto-playlists appear as **suggestions** that only the admin sees (Entdecken → Vorschläge) until they are published.

### Why one library folder per mount

Mount each share as its own folder below `/music` (`/music/nas`, `/music/usb`). If a share is not mounted when a scan runs, its folder is empty: audium marks that library folder **offline** and keeps all its tracks, instead of treating the music as deleted.

## Reverse proxy notes

Complete examples for Caddy, nginx and Traefik, and why HTTPS matters for installing the app: [reverse-proxy.md](reverse-proxy.md).

- Live updates use Server-Sent Events on `/api/v1/events` (a long-lived HTTP response). audium sends `X-Accel-Buffering: no`, which nginx honours; with other proxies, disable response buffering for that path and allow idle connections of at least 30 s (audium sends a keep-alive every 15 s).
- Streaming uses HTTP Range requests; the proxy must pass the `Range` header through (nginx and Caddy do by default).
