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
| `AUDIUM_SUBSONIC_ENABLED` | `true` | Serve the Subsonic API under `/rest` for third-party apps ([apps.md](apps.md)). `false` turns it off (404). With it on, admins can still switch the API off under Einstellungen > Schnittstellen; apps then get a Subsonic error. |
| `AUDIUM_APP_ORIGINS` | `tauri://localhost,http://tauri.localhost,https://tauri.localhost` | Origins of the audium apps, comma-separated. They may call `/api` from another origin (CORS), only with a bearer token, never with cookies. Empty: no app can connect. Add your own only for app development. Admins can also refuse all bearer tokens (apps and API tokens) under Einstellungen > Schnittstellen. |
| `AUDIUM_API_DB_READERS` | `1` | Database reads the API runs at the same time. SQLite reads take milliseconds, and parallel connections in one process slow each other down (measured: 1 reader 41 req/s, 4 readers 25 req/s), so the default queues them. |

## Logging

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error`. |
| `AUDIUM_LOG_FORMAT` | `json` | `json` (one JSON object per line) or `console` (human readable). |

## Accounts

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_ADMIN_USER` / `AUDIUM_ADMIN_PASSWORD` | *(unset)* | Create this admin on first start instead of in the browser. Scans then start without waiting for the first-run dialog. Ignored once any user exists. |
| `AUDIUM_SESSION_TTL_DAYS` | `30` | Sessions expire after this many days without use. |
| `AUDIUM_LOGIN_MAX_ATTEMPTS` | `10` | Failed logins per username within the window before it is blocked (per IP: 3×). |
| `AUDIUM_LOGIN_WINDOW_MINUTES` | `15` | Rate-limit window. Subsonic apps (`/rest`) have their own counters with the same limits. |
| `AUDIUM_SECRET_KEY` | *(unset)* | Key (any passphrase) that encrypts the app passwords of Subsonic apps. Unset: a random key is created in `<data>/secret.key` on first start. |

**First start without `AUDIUM_ADMIN_*`:** open audium in a browser and create the admin account. This works for 30 minutes after the start; after that, restart the container to get another 30 minutes. Whoever opens a new instance first becomes its admin, so if it can be reached from the internet, switch on port forwarding after the setup or set `AUDIUM_ADMIN_*`.

**First-run dialog:** an admin then gets a short dialog: which folders to use (with a trial scan that shows what audium finds), the analysis, connections to the outside and apps. Scans and the analysis wait for it, unless `AUDIUM_ADMIN_*` or `AUDIUM_LIBRARY_ROOTS` are set. Admins can open it again under Einstellungen > Musikordner.

**Starting over:** Einstellungen > Zurücksetzen (admins, with their password) empties the library, the analysis, playlists, favourites, history, auto-playlists, server settings and jobs, and logs everyone out (apps and API tokens too). The music files are not touched, cover files stay in `/data/covers` for the next scan. The accounts can stay (with their own settings and Subsonic app passwords); without them only the admin from `AUDIUM_ADMIN_*` remains, otherwise the first admin is created in the browser again (30 minutes from the reset). Then the first-run dialog opens as on a new installation.

**Locked out?** `docker exec -it audium audium admin reset-password <username>` prints a new password.

**Backups:** back up `secret.key` together with `audium.db` (both are in `/data`). Without the key, the app passwords in the database cannot be read any more; Subsonic apps then need new ones (Einstellungen → Apps verbinden), nothing else is lost. The same applies when `AUDIUM_SECRET_KEY` changes.

## Library and scanner

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_LIBRARY_ROOTS` | *(unset)* | Comma-separated library folders to add on first start, without waiting for the first-run dialog. Default: every top-level folder of `/music` (or `/music` itself if it has no sub-folders), chosen in the dialog. Manage them later in the admin UI. |
| `AUDIUM_SCAN_ON_START` | `true` | Run an incremental scan when the container starts (once the first-run dialog is done). |
| `AUDIUM_SCAN_INTERVAL_MINUTES` | `360` | Periodic incremental scan; `0` disables it. An unchanged library costs one `stat()` per file. |
| `AUDIUM_SCAN_WORKERS` | `4` | Parallel tag-reader processes (and cover threads). Raise for network shares with high latency, lower on a Raspberry Pi with little RAM. |
| `AUDIUM_MISSING_GRACE_DAYS` | `7` | Tracks whose files disappeared are hidden immediately and deleted from the database after this many days. Playlists and favorites survive a temporarily missing file. |
| `AUDIUM_IGNORED_ARTICLES` | `The El La Los Las Le Les Os As O A` | Leading words ignored when sorting artists ("The Beatles" sorts under B). |

## Audio analysis and auto-playlists

| Variable | Default | Meaning |
|---|---|---|
| `AUDIUM_ANALYSIS_ENABLED` | `true` | Analyse audio (tempo, key, energy, ...) with Essentia in the background. Tag-based auto-playlists (genre, decade) work without it. |
| `AUDIUM_ANALYSIS_WORKERS` | `1` | Parallel analysis processes, one CPU core each (TensorFlow is limited to one thread per process). They run at the lowest CPU priority (nice 19); 1 is gentle, 4 analyses about 100 tracks a minute on a typical desktop CPU (without style detection; with it roughly half). Admins can override it, pause the analysis or limit it to a time window (server time, see `TZ`) under Einstellungen > Audioanalyse > Rechenleistung, without a restart. |
| `AUDIUM_ANALYSIS_DOWNLOAD_MODELS` | `true` | Download the pre-trained style and fingerprint models (~20 MB) into `/data/models` on first use. With it on, admins can still switch the download off under Einstellungen > Schnittstellen. |

Analysis needs Essentia, which exists for **x86_64 only**. On arm64 (Raspberry Pi, many NAS) audium runs without it and says so in the admin settings; genre and decade playlists, smart playlists over tags and the radio (by genre/year) still work.

**Style detection and audio fingerprints (x86_64):** the image contains Essentia with TensorFlow. On first analysis audium downloads Essentia's Discogs-EffNet model and its 400-style classifier from essentia.upf.edu (three files, checked against fixed SHA-256 sums; no user data is sent). Per track it then stores a sound fingerprint, which "similar tracks" and radio use instead of the handful of descriptors, and the detected styles ("Deep House", "Shoegaze"). Styles map to genres; tracks **without genre tags** get detected genres (smoothed with their album), tags always win. Styles with at least 25 tracks become auto-playlist suggestions, and rules can filter by style. Tracks analysed before the models were there are analysed again in the background. The analysis takes about 4–6 s per track with one worker.

To avoid the download, set `AUDIUM_ANALYSIS_DOWNLOAD_MODELS=false` and put `discogs-effnet-bs64-1.pb`, `genre_discogs400-discogs-effnet-1.pb` and `genre_discogs400-discogs-effnet-1.json` into `/data/models` yourself. The models are licensed **CC BY-NC-SA 4.0 (non-commercial use only)**, which is why audium does not ship them; for a private server that is fine. Build an image without TensorFlow (~300 MB smaller, descriptors only) with `docker build --build-arg AUDIUM_ML=0 .`

**Mood models (optional, experimental):** download Essentia's MusiCNN mood classifiers yourself (`mood_happy-msd-musicnn-1.pb`, `mood_sad-...`, `mood_aggressive-...`, `mood_relaxed-...` plus their `.json` files) into `/data/models`. Same licence.

New auto-playlists appear as **suggestions** that only the admin sees (Entdecken → Vorschläge) until they are published.

In Entdecken the admin can switch the source to **Nur Klangerkennung**: suggestions then come only from the sound recognition, as detected styles plus "Klang-Mixe" (k-means over the sound fingerprints, named after their most common styles). Genre, decade, "Stimmung & Aktivität" and the feature mixes are no longer suggested; published playlists and own rule playlists stay. Switching back to **Alle Quellen** restores them on the next generation.

### Radio and mix sources

Under Einstellungen > Radio & Mixe the admin decides, for the whole server, what radio stations, "Ähnliche Titel" and the Subsonic apps (similar songs and artists) are made from. Each source has a switch and a weight (1–100): sound fingerprints, audio features, genre & year, similar artists from ListenBrainz, and each listener's own taste (favourite tracks, albums and artists and what they play often move up among the tracks the other sources found; it adds no tracks of its own). Every switched-on source ranks its own candidates; a track scores the weight of each source times how high it ranks there, so tracks several sources agree on come first. At least one source stays on; if none of them finds anything (e.g. only "Klang" on, but no analysis yet), genre & year stand in. Switching "Klang" or "Audio-Merkmale" off also stops the sound mixes or the feature mixes among the auto-playlist suggestions.

**Similar artists (ListenBrainz), off by default:** when switched on, the scan worker asks labs.api.listenbrainz.org which artists listeners play together with each artist of the library, by its MusicBrainz id. Artists without an id in their tags are looked up by name at musicbrainz.org first (exact matches only). This sends artist names and MusicBrainz ids, never what the users listen to. About one request per second, artists with the most tracks first; answers are refreshed after 90 days, failed requests retried after a day. Only artists that are in the library are kept.

"Keine großen Tempo-Sprünge" (on by default) orders each batch of a station so that, of the next four tracks in line, the one closest in BPM to the previous comes first; half and double time count as close. The genre & year source needs a shared genre (tagged or detected) or the same artist; the year only orders among those, never on its own.

A track skipped within its first 30 seconds of a radio station ranks lower for that user in later stations like it: the same station fully, stations of the same artists less, artists ListenBrainz calls similar a little. Skips fade over two months and are deleted after six. Shuffle, playlists and "Ähnliche Titel" are not affected.

Why a track is in a station or an auto-playlist ("Klingt ähnlich 70 % · Genre: Rock, 1994 30 %") is shown to admins only, in the column next to the title.

### Why one library folder per mount

Mount each share as its own folder below `/music` (`/music/nas`, `/music/usb`). If a share is not mounted when a scan runs, its folder is empty: audium marks that library folder **offline** and keeps all its tracks, instead of treating the music as deleted.

## Reverse proxy notes

Complete examples for Caddy, nginx and Traefik, and why HTTPS matters for installing the app: [reverse-proxy.md](reverse-proxy.md).

- Live updates use Server-Sent Events on `/api/v1/events` (a long-lived HTTP response). audium sends `X-Accel-Buffering: no`, which nginx honours; with other proxies, disable response buffering for that path and allow idle connections of at least 30 s (audium sends a keep-alive every 15 s).
- Streaming uses HTTP Range requests; the proxy must pass the `Range` header through (nginx and Caddy do by default).
