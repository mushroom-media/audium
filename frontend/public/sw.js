// audium service worker.
//
// - App shell (index + hashed assets): cache-first for assets (their names change with every
//   build), network-first for the page itself with the cached copy as offline fallback.
// - Covers: cache-first, limited to MAX_COVERS entries (their URLs never change content).
// - Everything else under /api (data, streams, events) always goes to the network: no stale
//   library data, no audio stored behind the user's back.

const VERSION = "audium-v1";
const SHELL = `${VERSION}-shell`;
const COVERS = `${VERSION}-covers`;
const MAX_COVERS = 1500;

const scope = new URL(self.registration.scope);
const base = scope.pathname.replace(/\/$/, "");

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((c) => c.addAll([`${base}/`, `${base}/manifest.webmanifest`, `${base}/favicon.svg`]))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trimCovers() {
  const cache = await caches.open(COVERS);
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_COVERS))) await cache.delete(k);
}

async function cacheFirst(cacheName, request) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) {
    cache.put(request, res.clone());
    if (cacheName === COVERS) trimCovers();
  }
  return res;
}

async function page(request) {
  try {
    const res = await fetch(request);
    if (res.ok) (await caches.open(SHELL)).put(`${base}/`, res.clone());
    return res;
  } catch {
    // Offline: the app shell still starts (and says that the server is unreachable).
    return (await caches.match(`${base}/`)) ?? Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(base + "/")) return;
  const path = url.pathname.slice(base.length);
  if (path.startsWith("/api/v1/covers/")) {
    event.respondWith(cacheFirst(COVERS, req));
  } else if (path.startsWith("/api/")) {
    return; // data, streams and live events: network only
  } else if (path.startsWith("/assets/")) {
    event.respondWith(cacheFirst(SHELL, req));
  } else if (req.mode === "navigate") {
    event.respondWith(page(req));
  }
});
