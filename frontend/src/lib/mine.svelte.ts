// The current user's own data: playlists they can see, favorites, and live updates (SSE).

import { currentConnection, del, eventsUrl, get, post, put, refreshMediaToken, type Playlist, type Track } from "./api";
import { deviceParams, unwireDevices, wireDevices } from "./devices.svelte";
import { onRole, ready } from "./tabs.svelte";
import { promptText } from "./ui.svelte";

export const mine = $state({
  playlists: [] as Playlist[],
  favoriteTracks: new Set<number>(),
  favoriteAlbums: new Set<number>(),
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

export type FavoriteKind = "track" | "album";
const FAVORITE_SET = { track: "favoriteTracks", album: "favoriteAlbums" } as const;

export async function loadFavorites() {
  const [t, a] = await Promise.all([
    get<{ ids: number[] }>("/favorites/track/ids"),
    get<{ ids: number[] }>("/favorites/album/ids"),
  ]);
  mine.favoriteTracks = new Set(t.ids);
  mine.favoriteAlbums = new Set(a.ids);
}

export function isFavorite(trackId: number): boolean {
  return mine.favoriteTracks.has(trackId);
}

export const toggleFavorite = (track: Track) => toggleFavoriteOf("track", track.id);

export async function toggleFavoriteOf(kind: FavoriteKind, id: number) {
  const key = FAVORITE_SET[kind];
  const on = !mine[key].has(id);
  // Optimistic: the heart flips at once, and flips back if the server says no.
  const next = new Set(mine[key]);
  if (on) next.add(id);
  else next.delete(id);
  mine[key] = next;
  try {
    if (on) await put(`/favorites/${kind}/${id}`);
    else await del(`/favorites/${kind}/${id}`);
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

let wanted = false;

export function connectEvents() {
  wanted = true;
  if (source) return;
  // First settle whether this tab leads: only the leading tab is the device (tabs.svelte.ts).
  ready.then(() => wanted && !source && open());
}

// The player moved into this tab or out of it: connect again, as the device or not.
onRole((role, was) => {
  if (!source || role === "pending" || was === "pending") return;
  source.close();
  source = null;
  open();
  scheduleReload(); // nothing is missed in between
});

function open() {
  // EventSource reconnects by itself and sends Last-Event-ID; the server replays what we missed.
  // In the leading tab it also makes this browser a device of the remote control (devices.svelte.ts).
  source = new EventSource(eventsUrl(deviceParams()));
  wireDevices(source);
  source.addEventListener("open", () => (mine.connected = true));
  source.addEventListener("error", () => {
    mine.connected = false;
    // Closed for good (e.g. the media token of an app expired): start over with a fresh URL.
    if (source?.readyState === EventSource.CLOSED && currentConnection()?.token) {
      source = null;
      setTimeout(() => refreshMediaToken().then(connectEvents, () => {}), 5000);
    }
  });
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
  wanted = false;
  unwireDevices();
  source?.close();
  source = null;
  mine.connected = false;
}

export async function loadMine() {
  await Promise.all([loadPlaylists(), loadFavorites()]);
  connectEvents();
}

/** "New playlist" from anywhere (sidebar on desktop, start page on phones). */
export async function newPlaylistFlow(): Promise<Playlist | null> {
  const name = await promptText("Neue Playlist", "", "Erstellen");
  return name ? createPlaylist(name) : null;
}
