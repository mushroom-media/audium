import { get, type Track } from "./api";
import { player } from "./player.svelte";
import { toast } from "./ui.svelte";

/** Plays a station built from one track (similar tracks by audio features, or genre/year). */
export async function startRadio(seed: Track) {
  try {
    const tracks = await get<Track[]>(`/tracks/${seed.id}/radio`, { limit: 60 });
    if (player.queue.shuffle) player.toggleShuffle(); // the station already has its own order
    player.playTracks(tracks, 0);
    toast(`Radio: ${seed.title}`);
  } catch {
    toast("Radio konnte nicht gestartet werden");
  }
}
