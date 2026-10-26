// Where an auto-playlist's tracks come from, for the label on cards and the playlist page.

import type { AutoPlaylist } from "./api";
import type { IconName } from "./components/Icon.svelte";

export const ORIGINS: Record<AutoPlaylist["origin"], { label: string; icon: IconName; hint: string }> = {
  tags: { label: "Tags", icon: "tag", hint: "Aus den Genre- und Jahres-Tags deiner Dateien" },
  features: { label: "Audio-Merkmale", icon: "spark", hint: "Gemessen: Tempo, Energie, Tanzbarkeit, Tonart …" },
  styles: { label: "Klangerkennung", icon: "wave", hint: "Vom KI-Modell am Klang erkannter Stil" },
  custom: { label: "Eigene Regel", icon: "edit", hint: "Nach einer Regel, die der Admin angelegt hat" },
};

/** One sentence for the playlist page, including detected genres in tag playlists. */
export function originText(a: AutoPlaylist): string {
  const o = ORIGINS[a.origin];
  if (!a.detected_tracks) return `${o.hint}.`;
  const n = a.detected_tracks.toLocaleString("de-DE");
  return `${o.hint}; ${n} ${a.detected_tracks === 1 ? "Titel ohne Genre-Tag wurde" : "Titel ohne Genre-Tag wurden"} per Klangerkennung zugeordnet.`;
}
