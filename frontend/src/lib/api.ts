import type { Lang } from "./i18n.svelte";
// Typed client for the audium REST API (see /api/docs for the full schema).

import { uiMessage } from "./errors";
import { t } from "./i18n.svelte";
import { linkDown, linkUp } from "./link.svelte";

declare global {
  interface Window {
    __AUDIUM__?: { basePath: string };
  }
}

export const basePath: string = (typeof window !== "undefined" && window.__AUDIUM__?.basePath) || "";

// --- connection ----------------------------------------------------------------------------
//
// The web UI is served by the server itself: relative URLs, the session cookie. The apps (the
// same code in a Tauri shell, built with VITE_AUDIUM_APP=1) run on another origin: they connect
// to a server the user enters, log in for a bearer token, and authenticate stream, cover and
// event URLs with a short-lived media token (those cannot send headers). Everything that talks
// to the server goes through the functions below, so the pages do not care which of both it is.

/** Built as an app: no server of its own, the user connects to one. */
export const isApp = import.meta.env.VITE_AUDIUM_APP === "1";

export interface Connection {
  /** e.g. "https://music.example.org" or "http://192.168.1.5:8091/audium" (no trailing slash) */
  server: string;
  token: string | null;
}

const CONNECTION_KEY = "audium.connection";
const MEDIA_REFRESH_BEFORE_MS = 60 * 60 * 1000;

function loadConnection(): Connection | null {
  try {
    const c = JSON.parse(localStorage.getItem(CONNECTION_KEY) ?? "null");
    return c && typeof c.server === "string" ? { server: c.server, token: typeof c.token === "string" ? c.token : null } : null;
  } catch {
    return null;
  }
}

let connection: Connection | null = typeof localStorage !== "undefined" ? loadConnection() : null;
let mediaToken: string | null = null;
let mediaTimer: ReturnType<typeof setTimeout> | undefined;

function saveConnection(c: Connection | null) {
  connection = c;
  try {
    if (c) localStorage.setItem(CONNECTION_KEY, JSON.stringify(c));
    else localStorage.removeItem(CONNECTION_KEY);
  } catch {
    /* private mode */
  }
}

/** The server an app is connected to (logged in or not). */
export function currentConnection(): Readonly<Connection> | null {
  return connection;
}

/** The server's address for people (e.g. for app setup or invite links). */
export function serverUrl(): string {
  return connection?.server ?? `${location.origin}${basePath}`;
}

const apiBase = () => `${connection?.server ?? basePath}/api/v1`;
const usesToken = () => !!connection?.token;

/** Normalizes what a person types: adds http(s), drops trailing slashes. */
export function normalizeServer(input: string): string {
  let s = input.trim().replace(/\/+$/, "");
  if (s && !/^https?:\/\//i.test(s)) s = (/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(s) ? "http://" : "https://") + s;
  return s;
}

/** Checks that `server` is an audium server and logs in there; the app then talks to it. */
export async function connectServer(server: string, username: string, password: string, device?: string) {
  const base = normalizeServer(server);
  let health: { server?: string };
  try {
    const res = await fetch(`${base}/api/health`, { credentials: "omit" });
    health = await res.json();
  } catch {
    throw new ApiError(0, "unreachable", t("Server nicht erreichbar. Stimmt die Adresse?"));
  }
  if (health.server !== "audium") throw new ApiError(0, "not_audium", t("Das ist kein audium-Server."));
  saveConnection({ server: base, token: null });
  const res = await post<{ token: string; user: User }>("/auth/app-login", { username, password, device });
  saveConnection({ server: base, token: res.token });
  await refreshMediaToken();
  return res.user;
}

/** Whether the server answers and is ready (see link.svelte.ts). */
export async function ping(): Promise<boolean> {
  try {
    const res = await fetch(`${connection?.server ?? basePath}/api/health`, { credentials: "omit", cache: "no-store" });
    return res.ok; // not yet while it starts (503): the pages would load too early
  } catch {
    return false;
  }
}

/** Logged out in the app: forget the token (the server address stays for the next login). */
export function forgetToken() {
  if (connection) saveConnection({ ...connection, token: null });
  mediaToken = null;
  clearTimeout(mediaTimer);
}

/** Media token for stream, cover and event URLs of an app; renewed before it expires. */
export async function refreshMediaToken() {
  clearTimeout(mediaTimer);
  if (!usesToken()) return;
  const mt = await get<{ token: string; expires_at: number }>("/auth/media-token");
  mediaToken = mt.token;
  const delay = Math.max(60_000, mt.expires_at - Date.now() - MEDIA_REFRESH_BEFORE_MS);
  mediaTimer = setTimeout(() => refreshMediaToken().catch(() => {}), delay);
}

/** A URL of a media endpoint, with the media token when the app uses one. */
function mediaUrl(path: string, params?: Params): string {
  return `${apiBase()}${path}${query({ ...params, mt: usesToken() ? mediaToken : undefined })}`;
}

/** `device`: this player takes part in the remote control (see devices.svelte.ts). */
export function eventsUrl(device?: Params): string {
  return mediaUrl("/events", device);
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number | null;
}

export interface Track {
  id: number;
  title: string;
  artist: string;
  artist_id: number;
  /** Main artists first, then guests; missing in queues saved before it existed. */
  artists?: { id: number; name: string }[];
  album: string;
  album_id: number;
  track_no: number | null;
  disc_no: number | null;
  year: number | null;
  duration_ms: number;
  codec: string | null;
  bitrate: number | null;
  cover: string | null;
  /** From the tags; missing in queues saved before it existed. */
  replaygain?: ReplayGain | null;
  /** Admins only, in radio stations and similar tracks: why the track is in there. */
  reason?: string | null;
}

/** Everything known about one track (GET /tracks/{id}/info), for the "Info" dialog. */
export interface TrackInfo {
  track: Track & {
    path: string;
    size: number;
    container: string | null;
    sample_rate: number | null;
    bit_depth: number | null;
    channels: number | null;
    date: string | null;
    genre: string | null;
    mb_recording_id: string | null;
    added_at: number;
    replaygain: ReplayGain;
  };
  genres: { name: string; detected: boolean; weight: number }[];
  styles: { name: string; parent: string; prob: number }[];
  styles_unclear: boolean;
  analysis: null | {
    status: "ok" | "failed";
    analyzed_at: number;
    sound: boolean;
    bpm: number | null;
    key: string | null;
    loudness: number | null;
    energy: number | null;
    danceability: number | null;
    brightness: number | null;
    dynamics: number | null;
    mood_happy: number | null;
    mood_sad: number | null;
    mood_aggressive: number | null;
    mood_relaxed: number | null;
  };
  plays: number;
  last_played: number | null;
  favorite: boolean;
}

export interface ReplayGain {
  track_gain: number | null;
  track_peak: number | null;
  album_gain: number | null;
  album_peak: number | null;
}

export interface Album {
  id: number;
  title: string;
  artist: string;
  artist_id: number;
  year: number | null;
  track_count: number;
  duration_ms: number;
  compilation: boolean;
  added_at: number;
  cover: string | null;
}

export interface AlbumDetail extends Album {
  /** Main color of the cover ("#rrggbb"), set by the scanner; null without a clear color. */
  cover_color: string | null;
  tracks: Track[];
  /** Only for albums with more than one disc; title from the disc's folder ("CD2 - Bonus" -> "Bonus"). */
  discs: { disc_no: number; title: string | null }[];
}

/** GET /stats: plays in a period and the most played tracks, albums and artists. */
export interface Stats {
  since: number | null;
  plays: number;
  /** Time the plays really sounded (no pauses or skipped parts); older plays and those of apps
   * count with the track's length. Plays count from 30 s on. */
  listening_ms: number;
  tracks: { track: Track; plays: number; listening_ms: number }[];
  albums: { album: Album; plays: number; listening_ms: number }[];
  /** Ranked by listening time. */
  artists: { artist: Artist; plays: number; listening_ms: number }[];
}

/** An entry of "recently played": where tracks were played from. */
export interface RecentItem {
  type: "album" | "playlist" | "auto" | "favorites" | "radio";
  id: number | null;
  /** For radios: what the station started from. */
  radio_of: "track" | "album" | "artist" | null;
  name: string;
  subtitle: string | null;
  cover: string | null;
  cover_preset: number | null;
}

export interface Artist {
  id: number;
  name: string;
  album_count: number;
  track_count: number;
  /** As the user wants artists shown (own picture, maybe the newest album cover). */
  cover: string | null;
  /** Own picture, else the newest album cover, whatever the setting: for radios. */
  fallback_cover?: string | null;
}

/** A-Z index entry: where entries with this initial start in an alphabetical list. */
export interface Letter {
  letter: string;
  offset: number;
}

export interface SearchResult {
  tracks: Track[];
  albums: Album[];
  artists: Artist[];
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  /** A name from AVATAR_COLORS (lib/avatar.ts); null: the accent color. */
  avatar_color?: string | null;
}

export type Theme = "system" | "dark" | "light";
export type StreamQuality = "auto" | "high" | "medium" | "low";

export type ReplayGainMode = "off" | "track" | "album";
export type LibraryTab = "tracks" | "albums" | "artists";
export type TrackSort = "title" | "added" | "year";
export type AlbumSort = "title" | "artist" | "year" | "added";
export type ArtistRole = "album" | "all";

export interface UserSettings {
  /** "server": the server language (language_default). */
  language: "server" | Lang;
  /** What "server" means right now (read-only). */
  language_default: Lang;
  theme: Theme;
  stream_quality: StreamQuality;
  shortcuts: "on" | "off";
  /** Plain ←/→ seek 10 seconds; off by default (Shift+←/→ skip tracks either way). */
  seek_keys: "off" | "on";
  replay_gain: ReplayGainMode;
  /** Crossfade between tracks that follow each other on their own, over crossfade_s seconds (1-12). */
  crossfade: "off" | "on";
  crossfade_s: number;
  /** How lively the cover backdrop in "now playing" moves: 0 still, 25 the slow base pace, 50 twice, 100 four times as fast. */
  backdrop_motion: number;
  /** "last": the tab open last time on this device. */
  library_tab: "last" | LibraryTab;
  track_sort: TrackSort;
  album_sort: AlbumSort;
  artist_role: ArtistRole;
  /** Artists without their own picture show the newest album cover; "server": the admin's choice. */
  artist_images: "server" | "on" | "off";
  /** What "server" means right now (read-only). */
  artist_images_default: "on" | "off";
  /** The admin left the Subsonic API on (read-only). */
  subsonic_api: "on" | "off";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter?: number,
    /** The server's original (English) message. */
    public serverMessage = message,
  ) {
    super(message);
  }
}

/** Called on 401 so the app can show the login screen. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Params = Record<string, string | number | boolean | readonly number[] | null | undefined>;

function query(params?: Params): string {
  if (!params) return "";
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) for (const item of v) q.append(k, String(item)); // ?k=1&k=2
    else if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function request<T>(
  method: string,
  path: string,
  // keepalive: the request outlives the page (sent while the tab closes).
  options: { params?: Params; body?: unknown; signal?: AbortSignal; keepalive?: boolean } = {},
): Promise<T> {
  // A Blob (an image upload) is sent as it is, everything else as JSON.
  const file = options.body instanceof Blob ? options.body : null;
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}${query(options.params)}`, {
      method,
      // Apps: the token, never cookies (the server allows the apps' origin only without them).
      credentials: usesToken() ? "omit" : "same-origin",
      signal: options.signal,
      keepalive: options.keepalive,
      headers: {
        "X-Requested-With": "audium",
        ...(usesToken() ? { Authorization: `Bearer ${connection!.token}` } : {}),
        ...(options.body !== undefined ? { "Content-Type": file ? file.type || "application/octet-stream" : "application/json" } : {}),
      },
      body: file ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
    });
  } catch (e) {
    // No answer at all (not an error status): the server is out of reach. Cancelled requests say nothing.
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    linkDown();
    throw new ApiError(0, "unreachable", t("Keine Verbindung zum Server."));
  }
  // 502/504: a reverse proxy (or the dev server) answers for a server that does not.
  if (res.status === 502 || res.status === 504) {
    linkDown();
    throw new ApiError(0, "unreachable", t("Keine Verbindung zum Server."));
  }
  if (res.status !== 503) linkUp(); // 503: audium is starting, not back yet
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? (typeof data?.detail === "string" ? data.detail : message);
      if (res.status === 422 && Array.isArray(data?.detail)) message = t("Ungültige Eingabe.");
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, code, uiMessage(message), Number(res.headers.get("Retry-After")) || undefined, message);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const get = <T>(path: string, params?: Params, signal?: AbortSignal) =>
  request<T>("GET", path, { params, signal });
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, { body: body ?? {} });
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, { body });

export function coverUrl(hash: string | null, size: 64 | 256 | 600 = 256): string | null {
  return hash ? mediaUrl(`/covers/${hash}/${size}`) : null;
}

export function streamUrl(trackId: number, format: "raw" | "opus" | "aac" | "mp3", kbps?: number, start = 0) {
  return mediaUrl(`/tracks/${trackId}/stream`, {
    format,
    bitrate: format === "raw" ? undefined : kbps,
    t: start > 0 ? start.toFixed(2) : undefined,
  });
}

export interface UserRef {
  id: number;
  username: string;
  display_name: string;
}

export type PlaylistRole = "owner" | "editor" | "viewer";

export interface Playlist {
  id: number;
  name: string;
  description: string | null;
  visibility: "private" | "users";
  kind: string;
  rule: Rule | null;
  /** Ordinary playlist made with "fill automatically": its filters, to fill it anew. */
  fill_rule: Rule | null;
  owner: UserRef;
  role: PlaylistRole;
  version: number;
  item_count: number;
  duration_ms: number;
  cover: string | null;
  /** Built-in design (see coverPresets.ts); takes precedence over `cover`. */
  cover_preset: number | null;
  cover_source: "auto" | "preset" | "upload";
  created_at: number;
  updated_at: number;
}

export interface PlaylistItem {
  item_id: number;
  added_by: number | null;
  added_at: number;
  /** Picked automatically (smart playlist, "fill automatically", saved auto-playlist), not by hand. */
  auto: boolean;
  available: boolean;
  track: Track;
}

export interface Share {
  user: UserRef;
  role: "viewer" | "editor";
}

export const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, { body: body ?? {} });
export const del = <T>(path: string) => request<T>("DELETE", path);

export interface RuleCondition {
  field: string;
  op: string;
  value: string | number | [number, number] | string[];
}

export interface Rule {
  match: "all" | "any";
  conditions: RuleCondition[];
  limit: number;
  order: string;
}

export interface RuleField {
  name: string;
  label: string;
  kind: "number" | "text" | "enum" | "scale";
  ops: string[];
  options: string[];
  needs_analysis: boolean;
  unit: string;
}

export interface AutoPlaylist {
  id: number;
  key: string;
  generator: "family" | "tag" | "rule" | "cluster" | "sound" | "custom";
  /** tags: genre/year tags · features: measured tempo, energy … · styles: sound recognition · custom: own rule */
  origin: "tags" | "features" | "styles" | "custom";
  /** Genre playlists: tracks in there by a detected genre (they had no genre tag). */
  detected_tracks: number | null;
  name: string;
  description: string | null;
  track_count: number;
  duration_ms: number;
  cover: string | null;
  generated_at: number | null;
  rule: Rule | null;
  status?: "suggested" | "published" | "dismissed" | null;
  access?: "all" | "restricted" | "admin_only" | null;
  user_ids?: number[] | null;
}

/** A broad genre on the Discover page (Rock = Rock, Alternative, Punk, …). */
export interface GenreFamily {
  name: string;
  /** All tracks of the family. */
  playlist: AutoPlaylist;
  /** Its genre playlists, biggest first. */
  genres: AutoPlaylist[];
  /** Your plays in it over the last 90 days (the order of the tiles). */
  plays: number;
}

export interface GenreOverview {
  families: GenreFamily[];
  /** Genre playlists that belong to no family. */
  others: AutoPlaylist[];
}

/** "Wieder reinhören": an album or artist you have not played for a while. */
export interface Rediscover {
  type: "album" | "artist";
  id: number;
  name: string;
  subtitle: string | null;
  cover: string | null;
  last_played: number;
}

export interface AutoItem {
  reason: string | null;
  track: Track;
}

export interface AnalysisStatus {
  backend: string;
  /** Why it may not run now: paused by the admin, or outside the time window. */
  waiting: "paused" | "window" | null;
  /** CPU cores of the server. */
  cpus: number;
  /** Processes for the setting "default" (AUDIUM_ANALYSIS_WORKERS). */
  workers_default: number;
  /** HH:MM on the server's clock (the time window uses it). */
  server_time: string;
  tracks: number;
  analyzed: number;
  failed: number;
  pending: number;
  /** Tracks with a sound fingerprint (used by radio and similar tracks). */
  fingerprints: number;
  /** Tracks with at least one detected style. */
  styles: number;
}
