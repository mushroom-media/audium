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

export const router = $state({ route: match("/", "") });

function update() {
  router.route = match(currentPath(), window.location.search);
}

export function href(path: string): string {
  return `${basePath}${path}`;
}

export function navigate(path: string, { replace = false } = {}) {
  const url = href(path);
  if (replace) history.replaceState(null, "", url);
  else history.pushState(null, "", url);
  update();
}

export function startRouter() {
  update();
  window.addEventListener("popstate", update);
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
