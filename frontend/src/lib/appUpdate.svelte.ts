// Updates of the Windows app (app/src-tauri/src/update.rs). The app downloads a new version in
// the background and installs it when it is closed; here only the hint for that and "restart
// now". Nothing of this exists in the browser.
import { isApp } from "./api";

export const appUpdate = $state<{ version: string | null; current: string | null; installing: boolean }>({
  version: null,
  current: null,
  installing: false,
});

let started = false;

export function watchAppUpdate() {
  if (!isApp || started) return;
  started = true;
  Promise.all([import("@tauri-apps/api/core"), import("@tauri-apps/api/event"), import("@tauri-apps/api/app")])
    .then(async ([{ invoke }, { listen }, { getVersion }]) => {
      await listen<string>("update-ready", (e) => (appUpdate.version = e.payload));
      appUpdate.version = (await invoke<string | null>("update_ready")) ?? appUpdate.version;
      appUpdate.current = await getVersion();
    })
    .catch(() => {
      /* not inside Tauri, or an app without updates (not Windows) */
    });
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
