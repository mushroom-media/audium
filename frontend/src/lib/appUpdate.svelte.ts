// Updates of the desktop app (app/src-tauri/src/update.rs). The app downloads a new version in
// the background. Windows installs it when the app is closed; macOS and Linux install it right
// away, for the next start. Here the hint for that, "restart now", and the check by hand in
// Settings > About. Nothing of this exists in the browser.
import { isApp } from "./api";

/** "on-close" (Windows), "next-start" (macOS, Linux AppImage), "manual": the app cannot replace
 * itself (a .deb package, a Mac app not in a folder of the user's), so new versions only come
 * from the download page. */
export type AppUpdateMode = "on-close" | "next-start" | "manual";

/** The desktop app's releases (tags app-v*, see .github/workflows/app.yml); "latest" on GitHub
 * stays the server's release, so this lists the app releases instead. */
export const APP_DOWNLOADS = "https://github.com/mushroom-media/audium/releases?q=app-v&expanded=true";

export const appUpdate = $state<{
  /** Downloaded and ready to install (Windows), or installed for the next start. */
  version: string | null;
  /** The running app's version; set only in the desktop app. */
  current: string | null;
  /** How it updates itself; null until known, and on phones. */
  mode: AppUpdateMode | null;
  installing: boolean;
  /** A check by hand runs (and downloads, if there is something new). */
  checking: boolean;
  /** Bytes of the download under way, from the check by hand or the one in the background. */
  progress: { downloaded: number; total: number | null } | null;
  /** How the last check by hand ended. */
  result: "latest" | "failed" | null;
}>({
  version: null,
  current: null,
  mode: null,
  installing: false,
  checking: false,
  progress: null,
  result: null,
});

let started = false;

export function watchAppUpdate() {
  if (!isApp || started) return;
  started = true;
  Promise.all([import("@tauri-apps/api/core"), import("@tauri-apps/api/event"), import("@tauri-apps/api/app")])
    .then(async ([{ invoke }, { listen }, { getVersion }]) => {
      const mode = await invoke<AppUpdateMode>("update_mode");
      if (mode === "manual") {
        appUpdate.current = await getVersion();
        appUpdate.mode = mode;
        return;
      }
      await listen<string>("update-ready", (e) => {
        appUpdate.version = e.payload;
        appUpdate.progress = null;
      });
      await listen<{ downloaded: number; total: number | null }>("update-progress", (e) => {
        if (!appUpdate.version) appUpdate.progress = e.payload;
      });
      appUpdate.version = (await invoke<string | null>("update_ready")) ?? appUpdate.version;
      appUpdate.current = await getVersion();
      appUpdate.mode = mode;
    })
    .catch(() => {
      /* not inside Tauri, or an app without updates (phones) */
    });
}

/** "Check for updates": asks GitHub now and downloads a newer version right away. */
export async function checkForAppUpdate() {
  if (appUpdate.checking || appUpdate.version || appUpdate.mode === "manual") return;
  appUpdate.checking = true;
  appUpdate.result = null;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const version = await invoke<string | null>("update_check");
    if (version) appUpdate.version = version;
    else appUpdate.result = "latest";
  } catch {
    appUpdate.result = "failed";
  } finally {
    appUpdate.checking = false;
    appUpdate.progress = null;
  }
}

/** Installs the waiting update and starts the new version. Returns only if that failed. */
export async function restartForUpdate() {
  if (appUpdate.installing) return;
  appUpdate.installing = true;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("update_now");
  } finally {
    appUpdate.installing = false;
  }
}
