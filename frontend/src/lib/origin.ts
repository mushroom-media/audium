// Where an auto-playlist's tracks come from, for the label on cards and the playlist page.

import type { AutoPlaylist } from "./api";
import type { IconName } from "./components/Icon.svelte";
import { msg, t, tn } from "./i18n.svelte";

export const ORIGINS: Record<AutoPlaylist["origin"], { label: string; icon: IconName; hint: string }> = {
  // label and hint are translation keys: shown with t()
  tags: { label: msg("Tags"), icon: "tag", hint: msg("Aus den Genre- und Jahres-Tags deiner Dateien") },
  features: { label: msg("Audio-Merkmale"), icon: "spark", hint: msg("Gemessen: Tempo, Energie, Tanzbarkeit, Tonart …") },
  styles: { label: msg("Klangerkennung"), icon: "wave", hint: msg("Vom KI-Modell am Klang erkannter Stil") },
  custom: { label: msg("Eigene Regel"), icon: "edit", hint: msg("Nach einer Regel, die der Admin angelegt hat") },
};

/** One sentence for the playlist page, including detected genres in tag playlists. */
export function originText(a: AutoPlaylist): string {
  const o = ORIGINS[a.origin];
  if (!a.detected_tracks) return `${t(o.hint)}.`;
  return `${t(o.hint)}; ${tn(a.detected_tracks, "{n} Titel ohne Genre-Tag wurde per Klangerkennung zugeordnet.", "{n} Titel ohne Genre-Tag wurden per Klangerkennung zugeordnet.")}`;
}
