// The desktop app (Tauri) shows "now playing" in full screen: opening the view puts the window
// in full screen, closing it leaves full screen again. Only a full screen this module entered is
// left, so a window that already was in full screen stays so.
import { isApp } from "./api";

/** The app on a desktop system (Windows, macOS, Linux), not in a browser and not on a phone. */
export const desktopApp = isApp && typeof navigator !== "undefined" && !/Android|iPhone|iPad/.test(navigator.userAgent);

export const appFullscreen = $state({ on: false });

let entered = false;
let queue: Promise<void> = Promise.resolve();

export function setNowPlayingFullscreen(open: boolean): void {
  if (!desktopApp) return;
  // One after the other: opening and closing quickly must not end in the wrong state.
  queue = queue.then(async () => {
    try {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const win = getCurrentWindow();
      if (open) {
        if (await win.isFullscreen()) return;
        await win.setFullscreen(true);
        entered = true;
        appFullscreen.on = true;
      } else if (entered) {
        entered = false;
        appFullscreen.on = false;
        await win.setFullscreen(false);
      }
    } catch {
      /* not inside Tauri (the app build opened in a browser): nothing to do */
    }
  });
}
