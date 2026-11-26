// Whether the server answers. Every request reports here (api.ts): a request that fails at the
// network level (no answer at all, not an error status) means the server is out of reach, any
// answer means it is back. While it is out of reach the shell shows a notice instead of looking
// broken, and a ping looks for the server every few seconds.

import { ping } from "./api";

export const link = $state({
  offline: false,
  /** Counts the returns of the server: the page in view is rebuilt, so it loads what it missed. */
  epoch: 0,
});

const PING_MS = 5000;
let pingTimer: ReturnType<typeof setInterval> | undefined;

export function linkDown() {
  if (link.offline) return;
  link.offline = true;
  pingTimer = setInterval(() => {
    ping().then((ok) => ok && linkUp());
  }, PING_MS);
}

export function linkUp() {
  if (!link.offline) return;
  link.offline = false;
  link.epoch++;
  clearInterval(pingTimer);
}

/** The system's own view: no network at all (cable out, Wi-Fi off). Not reliable for "online". */
export function watchLink() {
  window.addEventListener("offline", linkDown);
  window.addEventListener("online", () => ping().then((ok) => ok && linkUp()));
}
