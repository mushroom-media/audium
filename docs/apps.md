# Subsonic apps

audium speaks the (Open)Subsonic API under `/rest`. With that, the many existing Subsonic apps work with your audium server: same users, playlists, favorites and listening history as the web UI, plus what those apps bring themselves, such as offline downloads, CarPlay / Android Auto and lock-screen controls.

| Platform | Apps (examples) |
|---|---|
| Android | Symfonium, Tempo / Tempus, DSub, Ultrasonic |
| iOS | Amperfy, play:Sub, Narjo |
| Desktop | Feishin, Supersonic, Sonixd |

## Connect an app

1. In the web UI open **Einstellungen → Apps verbinden → App verbinden** and give it a name (e.g. "Symfonium Handy").
2. audium shows the **server address**, your **username** and a new **app password** (`xxxx-xxxx-xxxx-xxxx-xxxx-xxxx`). The password is shown only this once; copy it into the app.
3. In the app, add a Subsonic (or "OpenSubsonic") server with these three values.

Your login password does **not** work in apps, on purpose: many apps store the password unencrypted, and an app password can be revoked on its own (Apps verbinden → Widerrufen) without changing your login. Use one app password per app or device. The list shows when and by which app each one was last used.

App passwords keep working when an admin resets your login password. They stop working immediately when revoked or when the account is disabled.

### App settings

- **Server address:** what audium shows, e.g. `https://music.example.org` or `http://192.168.1.10:8091`. Under a sub-path (`AUDIUM_BASE_PATH=/audium`) include it: `https://example.org/audium`. Do not add `/rest`, the apps do that.
- **Authentication:** leave "legacy authentication" / "plain-text password" **off**. The token method (default in all current apps) never sends the password itself. Plain text works too, but only use it over HTTPS.
- **Transcoding:** audium sends the original file when the app can play it (MP3, FLAC, Ogg Vorbis/Opus, AAC/ALAC, WAV) and the app's bitrate limit allows it. Otherwise it converts on the fly: to the format the app asks for (MP3, Opus or AAC), or to MP3. WMA, APE, WavPack, Musepack and DSD are always converted. A bitrate limit for mobile data ("max bitrate 128") is respected.
- **Outside your home network:** use HTTPS through a reverse proxy, see [reverse-proxy.md](reverse-proxy.md).

Tips per app:

- **Symfonium:** add the server as "Subsonic / OpenSubsonic". Apps that keep a local copy of the library index read it completely on the first sync; with a very large library that can take a few minutes.
- **Amperfy (iOS):** log in with server URL, username and app password.
- **Feishin (desktop):** choose server type "Subsonic" (not Navidrome or Jellyfin).
- **DSub / older apps** that browse by folders: audium does not show your real folders; the folder view is built from the tags (artist → album → tracks).

## What works

| | |
|---|---|
| Browse | artists (A–Z, articles like "The" ignored), albums, songs, genres, album lists (newest, random, A–Z, by year, by genre, frequent, recently played, starred) |
| Search | prefix search over titles, artists and albums, full library sync |
| Play | original file with seeking, on-the-fly transcoding with seeking (`timeOffset`), downloads |
| Covers | WebP for apps that ask for it, JPEG for all others |
| Favorites | the app's stars are your audium favorites (both directions) |
| History | plays from apps appear in your audium history with the app's name; plays an app reports later (offline listening) keep their time |
| Playlists | your own, shared and public playlists; create, rename, add/remove/reorder by replacing, delete, with the same rights as in the web UI. Smart playlists and auto-playlists appear read-only |
| Radio | "similar songs" / "instant mix" use audium's sound-based radio |
| Play queue | apps that save the play queue (e.g. to continue on another device) can do so |
| Now playing | shows only your own devices, never what other users listen to |

## What does not work

These are audium features the Subsonic protocol has no place for; use the web UI for them:

- creating smart playlists, the rule editor, Discover, freezing auto-playlists, the reasons why a track is in an auto-playlist;
- sharing playlists with roles (apps only see whether a playlist is public);
- library folders, scans (admins can start one), users and invites, audio analysis.

Not supported at all: ratings (1–5 stars, use favorites), lyrics, podcasts, internet radio, video, chat, jukebox mode, public share links, bookmarks. Apps that ask get empty lists or a "not supported" message.

## Troubleshooting

- **"Wrong username or password":** use an app password, not your login password. After 10 failed attempts (`AUDIUM_LOGIN_MAX_ATTEMPTS`) the account is blocked for apps for 15 minutes; the web login is not affected.
- **No cover art in an app:** check that `https://<server>/rest/ping` is reachable through your proxy (see [reverse-proxy.md](reverse-proxy.md)).
- **Admins:** `AUDIUM_SUBSONIC_ENABLED=false` switches `/rest` off entirely.
