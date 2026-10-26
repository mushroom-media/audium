import { get, type AlbumDetail, type Track } from "./api";
import { player } from "./player.svelte";
import { toast } from "./ui.svelte";

export type RadioKind = "track" | "album" | "artist";

/** The station's own page: a temporary playlist of the mix. */
export const radioPath = (kind: RadioKind, id: number) => `/radio/${kind}/${id}`;

/** Starts at once with `first` (a station always begins with it); the player fills the station
 * up in the background while it plays (player.playRadio refills right away). */
function play(first: Track, name: string, kind: RadioKind, id: number) {
  player.playRadio([first], { kind: "Radio", name, path: radioPath(kind, id), ref: `radio:${kind}:${id}` });
  toast(`Radio: ${name}`);
}

const pick = <T>(items: T[]): T | undefined => items[Math.floor(Math.random() * items.length)];

/** Plays a station built from one track (similar tracks by audio features, or genre/year). */
export function startRadio(seed: Track) {
  play(seed, seed.title, "track", seed.id);
}

/** A station from an album or artist: similar music, about a quarter of it their own tracks. It
 * starts with one of the own tracks, picked here so it plays before the station is computed. */
export async function startGroupRadio(kind: "albums" | "artists", id: number, name: string) {
  try {
    let first: Track | undefined;
    if (kind === "albums") {
      first = pick((await get<AlbumDetail>(`/albums/${id}`)).tracks);
    } else {
      const ids = await get<number[]>("/tracks/ids", { artist_id: id });
      const one = pick(ids);
      if (one !== undefined) first = (await get<Track[]>("/tracks/by-ids", { ids: [one] }))[0];
    }
    if (!first) throw new Error("empty");
    play(first, name, kind === "albums" ? "album" : "artist", id);
  } catch {
    toast("Radio konnte nicht gestartet werden");
  }
}
