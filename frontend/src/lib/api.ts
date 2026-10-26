// Typed client for the audium REST API (see /api/docs for the full schema).

import { germanMessage } from "./errors";

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
    throw new ApiError(0, "unreachable", "Server nicht erreichbar. Stimmt die Adresse?");
  }
  if (health.server !== "audium") throw new ApiError(0, "not_audium", "Das ist kein audium-Server.");
  saveConnection({ server: base, token: null });
  const res = await post<{ token: string; user: User }>("/auth/app-login", { username, password, device });
  saveConnection({ server: base, token: res.token });
  await refreshMediaToken();
  return res.user;
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
  album: string;
  album_id: number;
  track_no: number | null;
  disc_no: number | null;
  year: number | null;
  duration_ms: number;
  codec: string | null;
  bitrate: number | null;
  cover: string | null;
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
  tracks: Track[];
}

/** GET /stats: plays in a period and the most played tracks, albums and artists. */
export interface Stats {
  since: number | null;
  plays: number;
  /** Sum of the played tracks' lengths (an estimate: plays count from 30 s on). */
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
  cover: string | null;
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
}

export type Theme = "system" | "dark" | "light";
export type StreamQuality = "auto" | "high" | "medium" | "low";

export interface UserSettings {
  theme: Theme;
  stream_quality: StreamQuality;
  shortcuts: "on" | "off";
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
  options: { params?: Params; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  // A Blob (an image upload) is sent as it is, everything else as JSON.
  const file = options.body instanceof Blob ? options.body : null;
  const res = await fetch(`${apiBase()}${path}${query(options.params)}`, {
    method,
    // Apps: the token, never cookies (the server allows the apps' origin only without them).
    credentials: usesToken() ? "omit" : "same-origin",
    signal: options.signal,
    headers: {
      "X-Requested-With": "audium",
      ...(usesToken() ? { Authorization: `Bearer ${connection!.token}` } : {}),
      ...(options.body !== undefined ? { "Content-Type": file ? file.type || "application/octet-stream" : "application/json" } : {}),
    },
    body: file ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  });
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? (typeof data?.detail === "string" ? data.detail : message);
      if (res.status === 422 && Array.isArray(data?.detail)) message = "Ungültige Eingabe.";
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, code, germanMessage(message), Number(res.headers.get("Retry-After")) || undefined, message);
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
  value: string | number | [number, number];
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
  generator: "tag" | "rule" | "cluster" | "sound" | "custom";
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

export interface AutoItem {
  reason: string | null;
  track: Track;
}

export interface AnalysisStatus {
  backend: string;
  tracks: number;
  analyzed: number;
  failed: number;
  pending: number;
  /** Tracks with a sound fingerprint (used by radio and similar tracks). */
  fingerprints: number;
  /** Tracks with at least one detected style. */
  styles: number;
}
