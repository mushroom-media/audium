# audium app (desktop)

The audium web interface as a desktop app, built with [Tauri 2](https://tauri.app). It connects to an
audium server you enter on the first start, logs in with a bearer token and plays from there. The
app has no music, database or audio analysis of its own: everything comes from the server.

Status: Windows, macOS (Apple silicon and Intel, one universal app) and Linux (AppImage, .deb).
Windows is tested in daily use; macOS and Linux are new. Android follows.

License: MIT (like `frontend/`), see [LICENSE](LICENSE).

## How it fits together

- `frontend/` is the same code as the web UI. `npm run build:app` builds it with `--mode app`
  (`frontend/.env.app` sets `VITE_AUDIUM_APP=1`) into `frontend/dist-app/`. In that mode the login
  screen also asks for the server address, requests use a bearer token instead of the cookie, and
  stream, cover and event URLs carry a media token (`frontend/src/lib/api.ts`).
- `app/src-tauri/` is the Tauri shell around it: window, icons, installer, updates. The window has
  no system title bar; the page's top bar takes its place, with the search field
  (`frontend/src/lib/components/WindowFrame.svelte`, window permissions in
  `capabilities/default.json`). On Windows and Linux the frontend draws the window buttons
  (`tauri.windows.conf.json`, `tauri.linux.conf.json`); on macOS the page reaches up under a
  transparent title bar that keeps the system's buttons at the top left (`tauri.macos.conf.json`).
  On Windows a page lost by WebView2 is reloaded (`src/recover.rs`). Otherwise the frontend calls
  no Rust code but the updates (`src/update.rs`); it only talks HTTP to the server.
- On Linux the window is WebKitGTK, which plays audio through GStreamer. The AppImage brings the
  GStreamer plugins along (`bundleMediaFramework`); the .deb package depends on the system's
  `gstreamer1.0-plugins-base` and `-good`. Formats GStreamer cannot play (AAC, for example) the
  player requests converted from the server.
- The server allows the app's origin (`http://tauri.localhost` on Windows, `tauri://localhost` on
  macOS/Linux) through `AUDIUM_APP_ORIGINS`, which contains both by default. Admins can switch apps
  off under Settings > Interfaces.

## Building on Windows

You need, once:

1. **Node.js** 20 or newer (`winget install OpenJS.NodeJS.LTS`).
2. **Microsoft C++ Build Tools** with the workload "Desktop development with C++":
   `winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`
3. **Rust**: `winget install Rustlang.Rustup`, then open a new terminal.
4. **WebView2**: already part of Windows 10/11.

Then, in this folder:

```powershell
npm install
npm run build
```

The first build takes a few minutes. The installer ends up in
`src-tauri\target\release\bundle\nsis\audium_<version>_x64-setup.exe`; the bare program is
`src-tauri\target\release\audium-app.exe`. The installer is not signed yet, so Windows shows a
SmartScreen warning ("More info" > "Run anyway").

## Building on macOS and Linux

The same `npm install` and `npm run build` in this folder, after installing Node.js and Rust
(`rustup`). On macOS also the Xcode command line tools (`xcode-select --install`); the app is in
`src-tauri/target/release/bundle/macos/`, the disk image in `bundle/dmg/`. On Linux (Debian,
Ubuntu) first:

```bash
sudo apt install libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev patchelf \
  build-essential curl file gstreamer1.0-plugins-base gstreamer1.0-plugins-good
```

The AppImage and the .deb package end up in `src-tauri/target/release/bundle/appimage/` and
`bundle/deb/`. Without a Mac or a Linux machine: the workflow `.github/workflows/app.yml` builds
all three on every pull request that changes `app/`; the packages are on the run's page.

The Mac app is signed only ad hoc (no Apple Developer account), so macOS blocks its first start
once: System Settings > Privacy & Security > "Open Anyway".

For development, `npm run dev` starts the frontend in app mode (Vite, port 5173) and opens it in
the app window with hot reload. A local server to connect to: `docker compose -f
docker-compose.dev.yml up app` in the repository root, then `http://localhost:8080` in the app.

## Updates

The installed app updates itself from the GitHub releases: it downloads a new version in the
background. Windows installs it when you close the app; macOS and the Linux AppImage put it in
place right away, for the next start. The .deb package and a Mac app outside a folder of the user's
(still on the disk image, say) do not update themselves; Settings > About links to the downloads. How it works and how to release:
[docs/development.md](../docs/development.md#app-updates).
