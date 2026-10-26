// Remote control between one user's own players (backend: api/devices.py).
//
// Every browser with audium open is a device: its leading tab (tabs.svelte.ts) joins with its
// event connection (see mine.svelte.ts), reports what it plays, and carries out commands that
// arrive over that connection. Another device can steer it: then `control.remote`
// (player.svelte.ts) is a RemotePlayer, and the player bar, "now playing" and the queue show and
// operate that device. It is a remote control only: this device's own playback just carries on,
// and nothing plays on both at once.

import { del, get, isApp, post, put } from "./api";
import { control, localPlayer } from "./player.svelte";
import { playerStatus, queueWindow, runCommand, watchPlayer, WINDOW_SIZE, type PlayerStatus, type QueueWindow } from "./playerLink";
import { RemotePlayer } from "./remotePlayer.svelte";
import { onRole, shareTarget, TabRemote, tabs, targetSync } from "./tabs.svelte";
import { toast } from "./ui.svelte";

export interface Device {
  id: string;
  name: string;
  kind: "desktop" | "phone" | "tablet" | "other";
  online: boolean;
  since: number;
  status: PlayerStatus | null;
  controllers: { id: string; name: string }[];
  queue?: QueueWindow | null;
  /** When the status arrived here (performance.now()), to move the position on. */
  received?: number;
}

export const devices = $state({
  list: [] as Device[],
  /** The device this one steers, if any. */
  target: null as string | null,
  /** The device picker is open. */
  picker: false,
});

// --- this device ------------------------------------------------------------------------------

function newId(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `d${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
}

/** Per browser (its tabs are one player, see tabs.svelte.ts). */
export const deviceId: string = (() => {
  try {
    const id = localStorage.getItem("audium.device") || newId();
    localStorage.setItem("audium.device", id);
    return id;
  } catch {
    return newId();
  }
})();

function deviceName(): string {
  const ua = navigator.userAgent;
  const browser =
    /Edg\//.test(ua) ? "Edge"
    : /OPR\//.test(ua) ? "Opera"
    : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : "Browser";
  const os =
    /iPhone/.test(ua) ? "iPhone"
    : /iPad/.test(ua) ? "iPad"
    : /Android/.test(ua) ? "Android"
    : /Windows/.test(ua) ? "Windows"
    : /Mac OS X/.test(ua) ? "Mac"
    : /Linux/.test(ua) ? "Linux"
    : "";
  const what = isApp ? "audium-App" : browser;
  return os ? `${what} auf ${os}` : what;
}

function deviceKind(): Device["kind"] {
  const ua = navigator.userAgent;
  if (/iPad|Tablet/.test(ua) || (/Android/.test(ua) && !/Mobile/.test(ua))) return "tablet";
  if (/Mobi|iPhone|Android/.test(ua)) return "phone";
  return "desktop";
}

/** Query parameters that make the event connection the device: only the leading tab's. */
export const deviceParams = () => (tabs.role === "leader" ? { device: deviceId, name: deviceName(), kind: deviceKind() } : undefined);

export const self = () => devices.list.find((d) => d.id === deviceId);
export const others = () => devices.list.filter((d) => d.id !== deviceId);

// --- device list --------------------------------------------------------------------------------

function upsert(d: Device, queue?: QueueWindow | null) {
  const i = devices.list.findIndex((x) => x.id === d.id);
  const old = i >= 0 ? devices.list[i] : undefined;
  const next: Device = {
    ...d,
    queue: queue !== undefined ? queue : (d.queue ?? old?.queue ?? null),
    // Only a new status moves the starting point of the position (a controller change does not).
    received: old && JSON.stringify(d.status) === JSON.stringify(old.status) ? old.received : performance.now(),
  };
  if (i >= 0) devices.list[i] = next;
  else devices.list.push(next);
}

async function loadDevices() {
  try {
    const list = await get<Device[]>("/devices");
    const now = performance.now();
    devices.list = list.map((d) => ({ ...d, received: now }));
    if (devices.target && !list.some((d) => d.id === devices.target)) stopControl("Das Gerät ist nicht mehr verbunden");
  } catch {
    /* offline: the next connection tries again */
  }
}

/** Wires the device events into the app's event connection. */
export function wireDevices(source: EventSource) {
  source.addEventListener("open", () => {
    loadDevices();
    sentQueue = null;
    report();
  });
  source.addEventListener("resync", () => loadDevices());
  source.addEventListener("device", (e) => upsert(JSON.parse((e as MessageEvent).data)));
  source.addEventListener("device-queue", (e) => {
    const { id, queue } = JSON.parse((e as MessageEvent).data) as { id: string; queue: QueueWindow };
    const d = devices.list.find((x) => x.id === id);
    if (d) d.queue = queue;
  });
  source.addEventListener("device-gone", (e) => {
    const { id } = JSON.parse((e as MessageEvent).data) as { id: string };
    const name = devices.list.find((d) => d.id === id)?.name;
    devices.list = devices.list.filter((d) => d.id !== id);
    if (devices.target === id) stopControl(`Verbindung zu ${name ?? "dem Gerät"} getrennt`);
  });
  source.addEventListener("command", (e) => {
    // While the player moves between tabs both may be connected; only the leader plays.
    if (tabs.role === "leader") runCommand(JSON.parse((e as MessageEvent).data));
  });
  startReporting();
}

export function unwireDevices() {
  stopReporting?.();
  stopReporting = null;
  stopControl();
  devices.list = [];
}

// --- reporting this device's state (leading tab only) --------------------------------------------

const REPORT_DELAY_MS = 150;
const CONTROLLED_REFRESH_MS = 15_000; // position refresh while someone watches

let stopReporting: (() => void) | null = null;
let reportTimer: ReturnType<typeof setTimeout> | undefined;
let sentQueue: { tracks: unknown; order: unknown; offset: number } | null = null;

/** The queue window, when the queue changed since the last report or the current track nears
 * the edge of the window that was sent. */
function changedQueue(): QueueWindow | undefined {
  const q = localPlayer.queue;
  const s = sentQueue;
  const rel = q.pos - (s?.offset ?? 0);
  const inside = s && ((rel >= 10 && rel < WINDOW_SIZE - 20) || (s.offset === 0 && rel < 10));
  if (s && s.tracks === q.tracks && s.order === q.order && inside) return undefined;
  const w = queueWindow();
  sentQueue = { tracks: q.tracks, order: q.order, offset: w.offset };
  return w;
}

function report() {
  clearTimeout(reportTimer);
  reportTimer = setTimeout(() => {
    if (tabs.role !== "leader") return;
    const status = $state.snapshot(playerStatus());
    const queue = changedQueue();
    put(`/devices/${deviceId}/state`, { status, queue: queue && $state.snapshot(queue) }).catch(() => {
      sentQueue = null; // send it again next time
    });
  }, REPORT_DELAY_MS);
}

function startReporting() {
  if (stopReporting) return;
  let refresh: ReturnType<typeof setInterval> | undefined;
  stopReporting = $effect.root(() => {
    $effect(() => {
      watchPlayer();
      if (tabs.role === "leader") report();
    });
    $effect(() => {
      // Someone steers this device: keep its position fresh (a stalled stream drifts).
      if (tabs.role !== "leader" || !self()?.controllers.length) return;
      refresh = setInterval(() => report(), CONTROLLED_REFRESH_MS);
      return () => clearInterval(refresh);
    });
  });
}

// --- who stands in for the player ----------------------------------------------------------------

/** The steered device; else, in a tab that does not lead, the leading tab; else nobody. */
function updateRemote() {
  const want = devices.target ? `device:${devices.target}` : tabs.role === "follower" ? "tab" : null;
  if (want === remoteKey) return;
  (control.remote as RemotePlayer | null)?.dispose();
  remoteKey = want;
  control.remote = !want ? null : want === "tab" ? new TabRemote() : new RemotePlayer(deviceLink(devices.target!));
}
let remoteKey: string | null = null;

function deviceLink(id: string) {
  return {
    mirror: () => devices.list.find((d) => d.id === id),
    send: (action: string, args: Record<string, unknown>) =>
      post(`/devices/${id}/commands`, { action, args, from: deviceId }).catch(() => toast("Das Gerät ist nicht erreichbar")),
  };
}

onRole(() => updateRemote());
// All tabs of this browser steer the same device.
targetSync.get = () => devices.target;
targetSync.set = (id) => {
  devices.target = id;
  updateRemote();
};

// --- steering another device -------------------------------------------------------------------

/** Steer another device of this user from here (all tabs of this browser). */
export async function controlDevice(id: string) {
  if (id === deviceId) return stopControl();
  try {
    const d = await put<Device>(`/devices/${id}/control`, { from: deviceId });
    const old = devices.target;
    if (old && old !== id) del(`/devices/${old}/control/${deviceId}`).catch(() => {});
    upsert(d, d.queue ?? null);
    devices.target = id;
    updateRemote();
    shareTarget(id);
  } catch {
    toast("Das Gerät ist nicht mehr verbunden");
    loadDevices();
  }
}

/** Back to this browser's own player. */
export function stopControl(message?: string) {
  const id = devices.target;
  if (!id) return;
  devices.target = null;
  updateRemote();
  shareTarget(null);
  del(`/devices/${id}/control/${deviceId}`).catch(() => {});
  if (message) toast(message);
}

/** The device this one steers. */
export const target = () => (devices.target ? devices.list.find((d) => d.id === devices.target) : undefined);
