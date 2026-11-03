// Stands in for the player while it plays somewhere else: on another device (devices.svelte.ts)
// or in another tab of this browser (tabs.svelte.ts). Shows that player's state and sends it
// commands; play/pause, volume and seeking show at once, before the player reports back.

import type { Track } from "./api";
import type { Args, Mirror, PlayerStatus } from "./playerLink";
import type { Controls, QueueSource, TrackPool } from "./player.svelte";
import * as Q from "./queue";

const VOLUME_SEND_MS = 120;

export interface Link {
  mirror(): Mirror | undefined;
  send(action: string, args: Args): void;
}

/** What this side asked for and shows already, before the player reports it. */
type Wish = { playing?: boolean; volume?: number; muted?: boolean; position?: number };

export class RemotePlayer implements Controls {
  protected link: Link;
  #clock = $state(performance.now());
  #ticker: ReturnType<typeof setInterval>;
  #wish = $state<Wish & { at: number }>({ at: 0 });
  #volumeTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(link: Link) {
    this.link = link;
    this.#ticker = setInterval(() => (this.#clock = performance.now()), 500);
  }

  dispose() {
    clearInterval(this.#ticker);
    clearTimeout(this.#volumeTimer);
  }

  get #s(): PlayerStatus | null {
    return this.link.mirror()?.status ?? null;
  }
  get #received(): number {
    return this.link.mirror()?.received ?? 0;
  }
  /** A wish of ours counts until the player reported after it. */
  #wished<K extends keyof Wish>(key: K): Wish[K] {
    return this.#wish[key] !== undefined && this.#wish.at > this.#received ? this.#wish[key] : undefined;
  }
  #want(w: Wish) {
    this.#wish = { ...(this.#wish.at > this.#received ? this.#wish : {}), ...w, at: performance.now() };
  }

  protected send(action: string, args: Args = {}) {
    this.link.send(action, args);
  }

  get playing() {
    return this.#wished("playing") ?? this.#s?.playing ?? false;
  }
  get buffering() {
    return this.#s?.buffering ?? false;
  }
  get duration() {
    return this.#s?.duration ?? 0;
  }
  get position() {
    const wished = this.#wished("position");
    if (wished !== undefined) return wished;
    const s = this.#s;
    if (!s) return 0;
    if (!s.playing || s.buffering) return s.position;
    const moved = (this.#clock - (this.#received || this.#clock)) / 1000;
    return Math.min(s.duration || Infinity, s.position + Math.max(0, moved));
  }
  get volume() {
    return this.#wished("volume") ?? this.#s?.volume ?? 1;
  }
  get muted() {
    return this.#wished("muted") ?? this.#s?.muted ?? false;
  }
  get error() {
    return this.#s?.error ?? null;
  }
  get radio() {
    return this.#s?.radio ?? false;
  }
  get source() {
    return this.#s?.source ?? null;
  }
  get current() {
    return this.#s?.track ?? null;
  }
  /** The window of the queue the player sent; positions in it are relative to its offset. */
  get queue(): Q.Queue {
    const s = this.#s;
    const w = this.link.mirror()?.queue;
    if (!s) return Q.empty;
    if (!w || !w.tracks.length) return { ...Q.empty, shuffle: s.shuffle, repeat: s.repeat };
    const pos = s.pos - w.offset;
    return {
      tracks: w.tracks,
      order: w.tracks.map((_, i) => i),
      pos: pos >= 0 && pos < w.tracks.length ? pos : -1,
      shuffle: s.shuffle,
      repeat: s.repeat,
    };
  }
  /** Where the queue window starts in the player's play order. */
  protected offset() {
    return this.link.mirror()?.queue?.offset ?? 0;
  }

  playTracks(tracks: Track[], start: number | null = 0, shuffle = this.queue.shuffle, source: QueueSource | null = null) {
    this.send("play_tracks", { tracks, start, shuffle, source });
  }
  async playPool(query: TrackPool, startId: number | null = null, shuffle = this.queue.shuffle, source: QueueSource | null = null, _first: Track | null = null) {
    this.send("play_pool", { query, start_id: startId, shuffle, source });
  }
  playRadio(tracks: Track[], source: QueueSource | null = null, start = 0) {
    this.send("play_radio", { tracks, source, start });
  }
  playNext(tracks: Track[]) {
    this.send("play_next", { tracks });
  }
  append(tracks: Track[]) {
    this.send("append", { tracks });
  }
  enqueue(tracks: Track[]) {
    this.send("enqueue", { tracks });
  }
  jump(orderPos: number) {
    this.send("jump", { pos: this.offset() + orderPos });
  }
  remove(orderPos: number) {
    this.send("remove", { pos: this.offset() + orderPos });
  }
  toggle() {
    if (!this.current) return;
    this.#want({ playing: !this.playing });
    this.send("toggle");
  }
  next() {
    this.send("next");
  }
  prev({ restart = true } = {}) {
    this.send("prev", { restart });
  }
  seek(seconds: number) {
    const s = Math.max(0, Math.min(seconds, this.duration || seconds));
    this.#want({ position: s });
    this.send("seek", { s });
  }
  setVolume(v: number) {
    const volume = Math.max(0, Math.min(1, v));
    this.#want(volume > 0 && this.muted ? { volume, muted: false } : { volume });
    // A dragged slider sends a value now and then, not one per pixel.
    if (this.#volumeTimer) return;
    this.#volumeTimer = setTimeout(() => {
      this.#volumeTimer = undefined;
      this.send("volume", { v: this.volume });
    }, VOLUME_SEND_MS);
  }
  setMuted(m: boolean) {
    this.#want({ muted: m });
    this.send("mute", { m });
  }
  toggleShuffle() {
    if (this.radio) return;
    this.send("shuffle", { on: !this.queue.shuffle });
  }
  cycleRepeat() {
    this.send("repeat");
  }
}
