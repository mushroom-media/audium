// App-wide UI state: the track context menu, the text prompt, short notifications.

import type { Track } from "./api";

export const ui = $state({
  menu: null as null | { x: number; y: number; tracks: Track[]; label: string },
  prompt: null as null | { title: string; value: string; confirm: string; resolve: (v: string | null) => void },
  toast: null as null | { text: string; id: number },
  share: null as null | { playlistId: number },
  /** The "Info" dialog of a track is open. */
  info: null as null | { trackId: number },
  /** The "new smart playlist" rule editor is open. */
  smartEditor: false,
});

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export function toast(text: string) {
  clearTimeout(toastTimer);
  ui.toast = { text, id: Date.now() };
  toastTimer = setTimeout(() => (ui.toast = null), 2600);
}

/** Opens the "…" menu for one or more tracks next to the clicked element. */
export function openTrackMenu(e: MouseEvent, tracks: Track[], label = "") {
  e.preventDefault();
  e.stopPropagation();
  const r = (e.currentTarget as HTMLElement | null)?.getBoundingClientRect();
  ui.menu = {
    x: r ? r.right : e.clientX,
    y: r ? r.bottom + 4 : e.clientY,
    tracks,
    label: label || (tracks.length === 1 ? tracks[0].title : `${tracks.length} Titel`),
  };
}

export function promptText(title: string, value = "", confirm = "OK"): Promise<string | null> {
  return new Promise((resolve) => {
    ui.prompt = { title, value, confirm, resolve };
  });
}
