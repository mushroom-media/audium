// Several tabs of audium in one browser are one player. One tab, the leader, owns the player and
// plays; the others show its state and steer it, like a remote control without the server
// (a BroadcastChannel). Towards the server and other devices the browser is one device.
//
// Starting playback in another tab moves the player there ("takeover"): the click happened in
// that tab, so the browser lets it play (autoplay rules are per tab). The leader hands over its
// exact state and becomes a follower. Pause, skip, seek and volume just go to the leader.
//
// No Web Locks: they exist only on HTTPS, and audium often runs on plain http in the home
// network. Instead the leader sends a heartbeat; when it closes it says goodbye (with its state),
// and when it falls silent the followers elect a new one. Should two tabs both lead (e.g. both
// started at once), the one that plays stays, otherwise the newer one.

import { localPlayer, type Snapshot } from "./player.svelte";
import { playerStatus, queueWindow, runCommand, watchPlayer, type Args, type Mirror, type PlayerStatus, type QueueWindow } from "./playerLink";
import { RemotePlayer } from "./remotePlayer.svelte";

const HEARTBEAT_MS = 1000;
const LEADER_TIMEOUT_MS = 3500;
const STARTUP_WAIT_MS = 400;
const TAKEOVER_WAIT_MS = 300;
const STATE_DELAY_MS = 50;

export type Role = "pending" | "leader" | "follower";

type Msg =
  | { t: "hello"; from: string }
  | { t: "alive"; from: string; since: number; playing: boolean }
  | { t: "state"; from: string; since: number; status: PlayerStatus; queue: QueueWindow; target: string | null }
  | { t: "cmd"; action: string; args: Args }
  | { t: "takeover"; from: string }
  | { t: "release"; to: string; snapshot: Snapshot }
  | { t: "bye"; from: string; snapshot: Snapshot }
  | { t: "target"; id: string | null };

export const tabs = $state({
  role: "pending" as Role,
  /** The leader's player, as followers see it. */
  mirror: null as Mirror | null,
});

const tabId = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `t${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("audium.tabs") : null;

let since = 0; // when this tab became the leader
let leader: { id: string; seen: number } | null = null;
let heartbeat: ReturnType<typeof setInterval> | undefined;
let stateTimer: ReturnType<typeof setTimeout> | undefined;
let electionTimer: ReturnType<typeof setTimeout> | undefined;
let releaseWait: ((s: Snapshot | null) => void) | null = null;
let goodbye: Snapshot | null = null; // what the last leader left when it closed

// --- hooks for the device remote control (devices.svelte.ts) and the event connection ---------

const roleListeners = new Set<(role: Role, was: Role) => void>();
export const onRole = (fn: (role: Role, was: Role) => void) => roleListeners.add(fn);

/** The device this browser steers: shared by all its tabs. */
export const targetSync = {
  get: (): string | null => null,
  set: (_id: string | null): void => {},
};

let readyResolve: () => void;
/** Settles once this tab knows whether it leads. */
export const ready = new Promise<void>((r) => (readyResolve = r));

// --- messages -------------------------------------------------------------------------------------

function send(m: Msg) {
  channel?.postMessage(m);
}

/** The leader tells the followers what it plays (a little later, so a burst of changes is one message). */
function sendState() {
  clearTimeout(stateTimer);
  stateTimer = setTimeout(() => {
    if (tabs.role !== "leader") return;
    const state = $state.snapshot({ status: playerStatus(), queue: queueWindow() });
    send({ t: "state", from: tabId, since, ...state, target: targetSync.get() });
  }, STATE_DELAY_MS);
}

/** Tells the other tabs which device this browser steers now. */
export function shareTarget(id: string | null) {
  send({ t: "target", id });
}

/** A follower's command for the leader's player. */
export function sendToLeader(action: string, args: Args) {
  send({ t: "cmd", action, args: $state.snapshot(args) as Args });
}

function handle(m: Msg) {
  switch (m.t) {
    case "hello":
      if (tabs.role === "leader") sendState();
      return;
    case "alive":
      return seeLeader(m.from, m.since, m.playing);
    case "state":
      seeLeader(m.from, m.since, m.status.playing);
      if (tabs.role === "follower") {
        tabs.mirror = { status: m.status, queue: m.queue, received: performance.now() };
        if (m.target !== targetSync.get()) targetSync.set(m.target);
      }
      return;
    case "cmd":
      if (tabs.role === "leader") runCommand(m);
      return;
    case "takeover":
      if (tabs.role !== "leader") return;
      localPlayer.saveNow();
      send({ t: "release", to: m.from, snapshot: localPlayer.snapshot() });
      become("follower");
      return;
    case "release":
      if (m.to === tabId) releaseWait?.(m.snapshot);
      return;
    case "bye":
      if (leader?.id !== m.from) return;
      leader = null;
      goodbye = m.snapshot;
      elect();
      return;
    case "target":
      if (m.id !== targetSync.get()) targetSync.set(m.id);
      return;
  }
}

/** Another tab leads. If this one does too, one of them gives way. */
function seeLeader(id: string, theirSince: number, playing: boolean) {
  if (tabs.role === "leader") {
    const mine = [localPlayer.playing ? 1 : 0, since, tabId] as const;
    const theirs = [playing ? 1 : 0, theirSince, id] as const;
    const theyWin = theirs[0] !== mine[0] ? theirs[0] > mine[0] : theirs[1] !== mine[1] ? theirs[1] > mine[1] : theirs[2] > mine[2];
    if (!theyWin) {
      sendState(); // so they notice and give way
      return;
    }
    become("follower");
  }
  leader = { id, seen: Date.now() };
  clearTimeout(electionTimer);
  if (tabs.role === "pending") become("follower");
}

/** No leader any more: after a short random wait (so not all at once), the first one takes over. */
function elect() {
  clearTimeout(electionTimer);
  electionTimer = setTimeout(() => {
    if (tabs.role === "follower" && !leader) become("leader", { snapshot: goodbye, resume: true });
  }, Math.random() * 200);
}

// --- roles ----------------------------------------------------------------------------------------

/** `snapshot`: the state to carry on with (else what was saved last); `resume`: keep playing if
 * the old leader did. */
function become(role: Role, { snapshot = null, resume = false }: { snapshot?: Snapshot | null; resume?: boolean } = {}) {
  const was = tabs.role;
  if (was === role) return;
  tabs.role = role;
  if (role === "leader") {
    since = Date.now();
    leader = null;
    if (was === "follower") {
      const last = tabs.mirror?.status;
      if (snapshot) localPlayer.adopt(snapshot);
      else localPlayer.reloadSaved();
      if (!snapshot && last && last.track?.id === localPlayer.current?.id) localPlayer.position = last.position;
      if (resume && (snapshot ? snapshot.playing : last?.playing)) localPlayer.play();
    }
    goodbye = null;
    tabs.mirror = null;
    heartbeat = setInterval(() => send({ t: "alive", from: tabId, since, playing: localPlayer.playing }), HEARTBEAT_MS);
    sendState();
  } else {
    clearInterval(heartbeat);
    if (was === "leader") localPlayer.release();
  }
  readyResolve();
  for (const fn of roleListeners) fn(role, was);
}

/** Move the player into this tab, with the leader's exact state; then this tab plays. */
export async function takeover(): Promise<void> {
  if (tabs.role === "leader") return;
  const snapshot = await new Promise<Snapshot | null>((resolve) => {
    releaseWait = resolve;
    send({ t: "takeover", from: tabId });
    setTimeout(() => resolve(null), TAKEOVER_WAIT_MS);
  });
  releaseWait = null;
  become("leader", { snapshot });
}

export function startTabs() {
  if (!channel) {
    become("leader");
    return;
  }
  channel.onmessage = (e: MessageEvent<Msg>) => handle(e.data);
  const greet = () => {
    send({ t: "hello", from: tabId });
    setTimeout(() => tabs.role === "pending" && become("leader"), STARTUP_WAIT_MS);
  };
  greet();
  // Closing (or leaving for the back/forward cache): hand the state to the others.
  window.addEventListener("pagehide", () => {
    if (tabs.role !== "leader") return;
    localPlayer.saveNow();
    send({ t: "bye", from: tabId, snapshot: localPlayer.snapshot() });
  });
  // Back from the cache: the others went on without this tab.
  window.addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    if (tabs.role === "leader") {
      clearInterval(heartbeat);
      localPlayer.release();
    }
    tabs.role = "pending";
    greet();
  });
  // A silent leader is gone (closed without goodbye, crashed).
  setInterval(() => {
    if (tabs.role === "follower" && (!leader || Date.now() - leader.seen > LEADER_TIMEOUT_MS)) {
      leader = null;
      elect();
    }
  }, 1000);
  $effect.root(() => {
    $effect(() => {
      watchPlayer();
      if (tabs.role === "leader") sendState();
    });
    $effect(() => {
      // Playback started here before the role was settled: this tab plays, so it leads.
      if (localPlayer.playing && tabs.role === "pending") become("leader");
    });
  });
}

// --- the followers' stand-in for the player -------------------------------------------------------

/** Follows the leader tab. Starting playback moves the player here first (see takeover), the
 * rest goes to the leader. */
export class TabRemote extends RemotePlayer {
  constructor() {
    super({ mirror: () => tabs.mirror ?? undefined, send: sendToLeader });
  }

  #here(fn: () => void) {
    takeover().then(fn);
  }

  playTracks(...args: Parameters<RemotePlayer["playTracks"]>) {
    const [tracks, start = 0, shuffle = this.queue.shuffle, source = null] = args;
    this.#here(() => localPlayer.playTracks(tracks, start, shuffle, source));
  }
  async playPool(...args: Parameters<RemotePlayer["playPool"]>) {
    const [query, startId = null, shuffle = this.queue.shuffle, source = null, first = null] = args;
    this.#here(() => localPlayer.playPool(query, startId, shuffle, source, first).catch(() => {}));
  }
  playRadio(...args: Parameters<RemotePlayer["playRadio"]>) {
    this.#here(() => localPlayer.playRadio(...args));
  }
  jump(orderPos: number) {
    // The handed-over queue has the leader's play order, so its positions hold.
    const pos = this.offset() + orderPos;
    this.#here(() => localPlayer.jump(pos));
  }
  toggle() {
    if (!this.current) return;
    if (this.playing) super.toggle();
    else this.#here(() => localPlayer.play());
  }
  playNext(tracks: Parameters<RemotePlayer["playNext"]>[0]) {
    if (this.current) super.playNext(tracks);
    else this.#here(() => localPlayer.playNext(tracks));
  }
  append(tracks: Parameters<RemotePlayer["append"]>[0]) {
    if (this.current) super.append(tracks);
    else this.#here(() => localPlayer.append(tracks));
  }
  enqueue(tracks: Parameters<RemotePlayer["enqueue"]>[0]) {
    if (this.current) super.enqueue(tracks);
    else this.#here(() => localPlayer.enqueue(tracks));
  }
}
