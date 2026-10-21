// The current user's own data: playlists they can see, favorites, and live updates (SSE).

import { basePath, del, get, post, put, type Playlist, type Track } from "./api";

export const mine = $state({
  playlists: [] as Playlist[],
  favoriteTracks: new Set<number>(),
  /** Latest version the server announced per playlist id; pages reload when it is newer. */
  changed: {} as Record<number, number>,
  /** Bumped when the server asks for a full resync (missed too many events). */
  resync: 0,
  connected: false,
});

export const editable = () => mine.playlists.filter((p) => p.role !== "viewer");

export async function loadPlaylists() {
  mine.playlists = await get<Playlist[]>("/playlists");
}

export async function loadFavorites() {
  const r = await get<{ ids: number[] }>("/favorites/track/ids");
  mine.favoriteTracks = new Set(r.ids);
}

export function isFavorite(trackId: number): boolean {
  return mine.favoriteTracks.has(trackId);
}

export async function toggleFavorite(track: Track) {
  const on = !mine.favoriteTracks.has(track.id);
  // Optimistic: the heart flips at once, and flips back if the server says no.
  const next = new Set(mine.favoriteTracks);
  if (on) next.add(track.id);
  else next.delete(track.id);
  mine.favoriteTracks = next;
  try {
    if (on) await put(`/favorites/track/${track.id}`);
    else await del(`/favorites/track/${track.id}`);
  } catch (e) {
    await loadFavorites();
    throw e;
  }
}

export async function createPlaylist(name: string, trackIds: number[] = []): Promise<Playlist> {
  const pl = await post<Playlist>("/playlists", { name, track_ids: trackIds });
  await loadPlaylists();
  return pl;
}

export async function addToPlaylist(playlistId: number, trackIds: number[]) {
  await post(`/playlists/${playlistId}/items`, { track_ids: trackIds });
}

// --- live updates ----------------------------------------------------------------------------

let source: EventSource | null = null;
let reloadTimer: ReturnType<typeof setTimeout> | undefined;

function scheduleReload() {
  // Several events in a burst (e.g. adding an album) cause one reload.
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(() => loadPlaylists().catch(() => {}), 300);
}

export function connectEvents() {
  if (source) return;
  // EventSource reconnects by itself and sends Last-Event-ID; the server replays what we missed.
  source = new EventSource(`${basePath}/api/v1/events`);
  source.addEventListener("open", () => (mine.connected = true));
  source.addEventListener("error", () => (mine.connected = false));
  source.addEventListener("playlist", (e) => {
    const data = JSON.parse((e as MessageEvent).data) as { playlist_id: number; type: string; version: number };
    mine.changed = { ...mine.changed, [data.playlist_id]: Math.max(mine.changed[data.playlist_id] ?? 0, data.version) };
    scheduleReload();
  });
  source.addEventListener("resync", () => {
    mine.resync++;
    scheduleReload();
  });
}

export function disconnectEvents() {
  source?.close();
  source = null;
  mine.connected = false;
}

export async function loadMine() {
  await Promise.all([loadPlaylists(), loadFavorites()]);
  connectEvents();
}
