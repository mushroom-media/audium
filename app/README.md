# audium app (desktop)

The audium web interface as a desktop app, built with [Tauri 2](https://tauri.app). It connects to an
audium server you enter on the first start, logs in with a bearer token and plays from there. The
app has no music, database or audio analysis of its own: everything comes from the server.

Status: first version, Windows only so far. Linux, macOS and Android follow.

License: MIT (like `frontend/`), see [LICENSE](LICENSE).

## How it fits together

- `frontend/` is the same code as the web UI. `npm run build:app` builds it with `--mode app`
  (`frontend/.env.app` sets `VITE_AUDIUM_APP=1`) into `frontend/dist-app/`. In that mode the login
  screen also asks for the server address, requests use a bearer token instead of the cookie, and
  stream, cover and event URLs carry a media token (`frontend/src/lib/api.ts`).
- `app/src-tauri/` is the Tauri shell around it: window, icons, installer. The frontend calls no
  Rust code; it only talks HTTP to the server.
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

For development, `npm run dev` starts the frontend in app mode (Vite, port 5173) and opens it in
the app window with hot reload. A local server to connect to: `docker compose -f
docker-compose.dev.yml up app` in the repository root, then `http://localhost:8080` in the app.
