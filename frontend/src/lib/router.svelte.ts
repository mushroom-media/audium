// Minimal history router. Paths are relative to the base path the backend injected.

import { basePath } from "./api";

export interface Route {
  name: string;
  params: Record<string, string>;
  query: URLSearchParams;
  path: string;
}

const patterns: [string, RegExp, string[]][] = [];

export function defineRoutes(defs: Record<string, string>) {
  patterns.length = 0;
  for (const [name, pattern] of Object.entries(defs)) {
    const keys: string[] = [];
    const re = pattern.replace(/:([a-z]+)/g, (_m, k) => {
      keys.push(k);
      return "([^/]+)";
    });
    patterns.push([name, new RegExp(`^${re}/?$`), keys]);
  }
}

function match(path: string, search: string): Route {
  for (const [name, re, keys] of patterns) {
    const m = path.match(re);
    if (m) {
      const params: Record<string, string> = {};
      keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])));
      return { name, params, query: new URLSearchParams(search), path };
    }
  }
  return { name: "notfound", params: {}, query: new URLSearchParams(search), path };
}

function currentPath(): string {
  const p = window.location.pathname;
  return (p.startsWith(basePath) ? p.slice(basePath.length) : p) || "/";
}

/** `overlay`: a full-screen view open over the page (see openOverlay). */
export const router = $state({ route: match("/", ""), depth: 0, overlay: null as string | null });

interface EntryState {
  depth?: number;
  /** Tells the history entries apart, e.g. for the scroll position each one had. */
  key?: string;
  overlay?: string;
}

const newKey = () => Math.random().toString(36).slice(2, 10);
let entryKey = "";

// Each history entry we push carries its depth, so we know whether "back" stays inside the app.
function update() {
  const state = (history.state as EntryState | null) ?? {};
  router.route = match(currentPath(), window.location.search);
  router.depth = state.depth ?? 0;
  router.overlay = state.overlay ?? null;
  entryKey = state.key ?? "";
}

export function href(path: string): string {
  return `${basePath}${path}`;
}

export function navigate(path: string, { replace = false } = {}) {
  const url = href(path);
  if (replace) history.replaceState({ depth: router.depth, key: entryKey }, "", url);
  // Leaving an overlay for a page takes its place: "back" then returns to the page under it.
  else if (router.overlay) history.replaceState({ depth: router.depth, key: newKey() }, "", url);
  else history.pushState({ depth: router.depth + 1, key: newKey() }, "", url);
  update();
}

/** Full-screen views (now playing, the queue on phones) get a history entry of their own, so
 * "back" (the system's swipe back too) closes them and leaves the page under them as it was. */
export function openOverlay(name: string) {
  if (router.overlay === name) return;
  const state: EntryState = { depth: router.depth + 1, key: entryKey, overlay: name };
  if (router.overlay) history.replaceState({ ...state, depth: router.depth }, "", window.location.href);
  else history.pushState(state, "", window.location.href);
  update();
}

export function closeOverlay(name: string) {
  if (router.overlay === name) history.back();
}

// Scroll positions per history entry: coming back to a page finds it where it was left.
const scrolls = new Map<string, number>();
const SCROLLS_KEY = "audium.scrolls";
const MAX_SCROLLS = 500;

/** `id` tells apart what scrolls on the page (and lists that should not share a position). */
export function rememberScroll(id: string, top: number) {
  const key = `${entryKey}|${id}`;
  scrolls.delete(key);
  scrolls.set(key, top);
  if (scrolls.size > MAX_SCROLLS) scrolls.delete(scrolls.keys().next().value!);
}

export function recallScroll(id: string): number {
  return scrolls.get(`${entryKey}|${id}`) ?? 0;
}

// Phones drop a page in the background without notice: the positions outlive that (per tab).
function saveScrolls() {
  try {
    sessionStorage.setItem(SCROLLS_KEY, JSON.stringify([...scrolls]));
  } catch {
    /* private mode */
  }
}

function loadScrolls() {
  try {
    for (const [key, top] of JSON.parse(sessionStorage.getItem(SCROLLS_KEY) ?? "[]")) scrolls.set(key, top);
  } catch {
    /* private mode, or nothing usable */
  }
}

// What else a page wants back with "back" (its data, a filter, a radio mix). Per history entry, so
// opening a page anew starts fresh; in memory only, and the oldest go first.
const kept = new Map<string, unknown>();
const MAX_KEPT = 50;

export function rememberEntry(id: string, value: unknown) {
  const key = `${entryKey}|${id}`;
  kept.delete(key);
  kept.set(key, value);
  if (kept.size > MAX_KEPT) kept.delete(kept.keys().next().value!);
}

export function recallEntry<T>(id: string): T | undefined {
  return kept.get(`${entryKey}|${id}`) as T | undefined;
}

/** Back to the previous page of the app, or to `fallback` when the app was opened right here. */
export function goBack(fallback: string) {
  if (router.depth > 0) history.back();
  else navigate(fallback, { replace: true });
}

export function startRouter() {
  // A reload opens the page itself, not an overlay that was open; each entry gets its key.
  const state = (history.state as EntryState | null) ?? {};
  history.replaceState({ depth: state.depth ?? 0, key: state.key ?? newKey() }, "", window.location.href);
  update();
  loadScrolls();
  window.addEventListener("popstate", update);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveScrolls();
  });
  // Intercept clicks on internal links so navigation never reloads the page (and the player).
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element).closest("a");
    if (!a || a.target || a.hasAttribute("download") || a.origin !== window.location.origin) return;
    if (!a.pathname.startsWith(basePath)) return;
    const path = a.pathname.slice(basePath.length) || "/";
    if (path.startsWith("/api/")) return;
    e.preventDefault();
    navigate(path + a.search);
  });
}
