// Typed client for the audium REST API (see /api/docs for the full schema).

declare global {
  interface Window {
    __AUDIUM__?: { basePath: string };
  }
}

export const basePath: string = (typeof window !== "undefined" && window.__AUDIUM__?.basePath) || "";
const API = `${basePath}/api/v1`;

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

export interface Artist {
  id: number;
  name: string;
  album_count: number;
  track_count: number;
  cover: string | null;
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
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}

/** Called on 401 so the app can show the login screen. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Params = Record<string, string | number | boolean | null | undefined>;

function query(params?: Params): string {
  if (!params) return "";
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function request<T>(
  method: string,
  path: string,
  options: { params?: Params; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const res = await fetch(`${API}${path}${query(options.params)}`, {
    method,
    credentials: "same-origin",
    signal: options.signal,
    headers: {
      "X-Requested-With": "audium",
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? (typeof data?.detail === "string" ? data.detail : message);
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, code, message, Number(res.headers.get("Retry-After")) || undefined);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const get = <T>(path: string, params?: Params, signal?: AbortSignal) =>
  request<T>("GET", path, { params, signal });
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, { body: body ?? {} });
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, { body });

export function coverUrl(hash: string | null, size: 64 | 256 | 600 = 256): string | null {
  return hash ? `${API}/covers/${hash}/${size}` : null;
}

export function streamUrl(trackId: number, format: "raw" | "opus" | "aac" | "mp3", kbps?: number, start = 0) {
  return `${API}/tracks/${trackId}/stream${query({
    format,
    bitrate: format === "raw" ? undefined : kbps,
    t: start > 0 ? start.toFixed(2) : undefined,
  })}`;
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
  owner: UserRef;
  role: PlaylistRole;
  version: number;
  item_count: number;
  duration_ms: number;
  cover: string | null;
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
