// The persistent player. Its <audio> elements live outside the page tree, so playback
// continues while navigating. Queue logic is in queue.ts, format choice in playback.ts.
//
// Near-gapless: a second element preloads the next track shortly before the current one ends;
// on "ended" the elements swap and the already-buffered next track starts at once. That removes
// the loading gap (typically 100-500 ms over a network). Sample-exact gapless playback (live
// albums) would need Web Audio/MSE with encoder-delay trimming; see docs/decisions.md D26.
//
// Crossfade (a user setting) uses the same two elements: the spare one starts that many seconds
// before the end and both volumes cross over. Only for tracks that follow on their own, not skips.
// iOS ignores element volume, so there the tracks only overlap.

import { coverUrl, get, post, request, streamUrl, type ReplayGainMode, type StreamQuality, type Track } from "./api";
import { browserCanPlay, chooseSource, listenedStep, replayGainFactor, type Format } from "./playback";
import * as Q from "./queue";
import { closeOverlay, openOverlay, router } from "./router.svelte";

const STORAGE_KEY = "audium.player";
const MAX_STORED_TRACKS = 1000;
export const RESTART_THRESHOLD_S = 3;
// A play counts (history) after 30 s really played, or half of a shorter track.
const SCROBBLE_AFTER_S = 30;
// A radio track skipped before this ranks lower in stations like this one (backend analysis/taste.py).
const RADIO_SKIP_BEFORE_S = 30;
const PRELOAD_BEFORE_END_S = 20; // plus the crossfade length
const FADE_STEP_MS = 50;
/** A radio station starts with this many tracks and grows by as many while it plays. */
export const RADIO_BATCH = 20;
const RADIO_REFILL_AT = 5; // tracks left when the station fetches more
const RADIO_EXCLUDE = 500; // the station's latest tracks it won't repeat
// The app's phone layout (see App.svelte).
const phoneLayout = typeof matchMedia === "function" ? matchMedia("(max-width: 860px)") : null;
const POOL_BATCH = 100; // tracks a pool adds to the queue at a time (≤ the server's by-ids limit)
const POOL_REFILL_AT = 10;
const POOL_HISTORY = 500; // played tracks a pool queue keeps for "back"
const POOL_FILL_DELAY_MS = 500; // the first refill waits for the stream: on the server it would queue behind the ids

/** A whole track list played without holding it all: the query for /tracks/ids, e.g.
 * { sort: "title", q: "abba" }. The queue gets its tracks in batches while it plays, so shuffle
 * mixes the whole list, not just what was loaded. The first track starts before any of that is
 * there: the ids of a big library take a second to arrive. */
export type TrackPool = Record<string, string | number | undefined>;

type Pool = { query: TrackPool; ids: number[] | null; rest: number[] | null };

/** Everything another tab needs to carry on playing exactly here (see tabs.svelte.ts). */
export interface Snapshot {
  queue: Q.Queue;
  radio: boolean;
  source: QueueSource | null;
  pool: Pool | null;
  position: number;
  volume: number;
  muted: boolean;
  playing: boolean;
}

/** Where the queue was started from, shown in the "now playing" view. */
export interface QueueSource {
  /** What kind of thing it is, e.g. "Album" or "Playlist". */
  kind: string;
  name: string;
  /** App path to go back to it. */
  path?: string;
  /** Stored with each play so "recently played" shows the source, e.g. "album:3" (see RecentItem). */
  ref?: string;
}

class Player {
  queue = $state<Q.Queue>(Q.empty);
  playing = $state(false);
  buffering = $state(false);
  position = $state(0);
  duration = $state(0);
  volume = $state(0.8);
  muted = $state(false);
  error = $state<string | null>(null);
  /** The browser refused to start playback without a tap on this device (autoplay policy). */
  blocked = $state(false);
  /** Bumped on every seek, so the remote control can report the new position. */
  seeks = $state(0);
  #queuePanel = $state(false);
  #phone = $state(phoneLayout?.matches ?? false);
  /** The queue is shown: a side panel on wide screens, on phones a page of its own over the
   * current one (an overlay in the history, so "back" closes it). */
  get queueOpen(): boolean {
    return this.#phone ? router.overlay === "queue" : this.#queuePanel;
  }
  set queueOpen(open: boolean) {
    if (!this.#phone) this.#queuePanel = open;
    else if (open) openOverlay("queue");
    else closeOverlay("queue");
  }
  /** The full-screen "now playing" view is open (an overlay in the history as well). */
  get nowPlayingOpen(): boolean {
    return router.overlay === "nowPlaying";
  }
  set nowPlayingOpen(open: boolean) {
    if (open) openOverlay("nowPlaying");
    else closeOverlay("nowPlaying");
  }
  /** The queue is a radio station (see playRadio). */
  radio = $state(false);
  source = $state<QueueSource | null>(null);
  quality: StreamQuality = "auto";
  /** Crossfade length in seconds; 0: off (a user setting). */
  crossfade = 0;
  /** Volume levelling with the tracks' ReplayGain tags (a user setting). */
  #replayGain: ReplayGainMode = "off";

  current = $derived(Q.current(this.queue));

  #audio: HTMLAudioElement | null = null; // the element that is playing
  #spare: HTMLAudioElement | null = null; // preloads the next track
  #spareId: number | null = null;
  #spareTrack: Track | null = null;
  #spareFormat: Format = "raw";
  #canPlay = browserCanPlay();
  #format: Format = "raw";
  #offset = 0; // start offset of a transcoded stream, in seconds
  #loadedId: number | null = null;
  #fallbackTried = false;
  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  #reported = false;
  /** Seconds the current play really sounded: only while the position moves on its own, so
   * pauses, buffering and skipped parts (seeks) do not count. */
  #listened = 0;
  #lastPos: number | null = null; // position and clock at the last timeupdate; null after a seek
  #lastClock = 0;
  /** The reported play's id (from POST /history), for sending its final listened time. */
  #playId: Promise<number | null> | null = null;
  #station = 0; // counts queues started, so a late radio refill can tell it is out of date
  #refilling = false;
  #stationEnded = -1; // a station that had nothing more to add
  /** The queue walks a pool: its ids (null until fetched, e.g. after a reload) and those not
   * queued yet, in play order (null: work out from the queue once the ids are there). */
  #pool: Pool | null = null;
  #poolFill: { pool: Pool; done: Promise<void> } | null = null;
  /** The track fading out under the current one during a crossfade; `t` runs from 0 to 1. */
  #fade: { el: HTMLAudioElement; track: Track | null; start: number; ms: number; t: number; timer: ReturnType<typeof setInterval> } | null = null;

  init() {
    if (this.#audio) return;
    this.#audio = this.#wire(new Audio());
    this.#spare = this.#wire(new Audio());
    this.#restore();
    phoneLayout?.addEventListener("change", () => (this.#phone = phoneLayout.matches));
    // A tab may be closed or frozen without warning: send what has sounded so far (it only grows).
    addEventListener("pagehide", () => this.#sendListened());
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") this.#sendListened();
    });
    this.#applyVolume();
    this.#setupMediaSession();
  }

  /** Listeners for one element; events of the element that is not playing are ignored. */
  #wire(a: HTMLAudioElement): HTMLAudioElement {
    a.preload = "auto";
    const on = (type: string, fn: () => void) =>
      a.addEventListener(type, () => {
        if (a === this.#audio) fn();
      });
    on("timeupdate", () => {
      this.position = this.#offset + a.currentTime;
      this.#measure();
      this.#maybeReport();
      this.#maybePreload();
      this.#maybeCrossfade();
      this.#updatePositionState();
      this.#scheduleSave();
    });
    on("durationchange", () => this.#updateDuration());
    on("seeking", () => (this.#lastPos = null));
    on("play", () => (this.playing = true));
    on("pause", () => (this.playing = false));
    on("waiting", () => (this.buffering = true));
    on("playing", () => {
      this.buffering = false;
      this.error = null;
      this.blocked = false;
    });
    on("ended", () => {
      this.#maybeReport(true); // a track that played to the end always counts
      this.#advance(true);
    });
    on("error", () => this.#onError());
    return a;
  }

  #applyVolume() {
    const f = this.#fade;
    // Equal power: the sum stays about as loud as one track all the way through.
    const pairs: [HTMLAudioElement | null, Track | null, number][] = f
      ? [
          [this.#audio, this.current, Math.sin((f.t * Math.PI) / 2)],
          [f.el, f.track, Math.cos((f.t * Math.PI) / 2)],
        ]
      : [
          [this.#audio, this.current, 1],
          [this.#spare, this.#spareTrack, 1],
        ];
    for (const [el, track, gain] of pairs) {
      if (!el) continue;
      el.volume = Math.min(1, this.volume * replayGainFactor(track?.replaygain, this.#replayGain) * gain);
      el.muted = this.muted;
    }
  }

  setReplayGain(mode: ReplayGainMode) {
    this.#replayGain = mode;
    this.#applyVolume();
  }

  // --- starting playback -------------------------------------------------------------------

  /** `start` null: no particular track first (with `shuffle`, a random one). */
  playTracks(tracks: Track[], start: number | null = 0, shuffle = this.queue.shuffle, source: QueueSource | null = null) {
    this.radio = false;
    this.source = source;
    this.#station++;
    this.#pool = null;
    this.queue = Q.create(tracks, start, { ...this.queue, shuffle });
    this.#load(true);
  }

  /** Play a whole track list (see TrackPool) from the track `startId`; null: from a random one
   * with shuffle, else from the top. `first`: that track, when the caller has it at hand. */
  async playPool(
    query: TrackPool,
    startId: number | null = null,
    shuffle = this.queue.shuffle,
    source: QueueSource | null = null,
    first: Track | null = null,
  ) {
    const station = ++this.#station;
    let track = first;
    if (!track && startId !== null) [track = null] = await this.#fetchTracks([startId]);
    if (!track) track = await get<Track | null>("/tracks/first", { ...query, shuffle: shuffle ? 1 : undefined });
    if (station !== this.#station || !track) return;
    // The queue is just this track for a moment; the first refill brings the rest of the pool.
    // No second shuffle, but the shuffle button shows the mode.
    this.playTracks([track], 0, false, source);
    this.queue = { ...this.queue, shuffle };
    this.#pool = { query, ids: null, rest: null };
    setTimeout(() => void this.#refillPool(), POOL_FILL_DELAY_MS);
    this.#scheduleSave();
  }

  /** A radio station already has its own order, so shuffle stays off while it plays. It grows
   * while it plays (see #refillRadio); `source.ref` ("radio:album:3") says where from. */
  playRadio(tracks: Track[], source: QueueSource | null = null, start = 0) {
    this.playTracks(tracks, start, false, source);
    this.radio = true;
    this.#refillRadio();
  }

  playNext(tracks: Track[]) {
    const wasEmpty = !this.current;
    this.queue = Q.playNext(this.queue, tracks);
    if (wasEmpty) this.#load(true);
    this.#scheduleSave();
  }

  append(tracks: Track[]) {
    const wasEmpty = !this.current;
    this.queue = Q.append(this.queue, tracks);
    if (wasEmpty) this.#load(true);
    this.#scheduleSave();
  }

  /** Next after the current track and what was queued before it (swiping a track in a list). */
  enqueue(tracks: Track[]) {
    const wasEmpty = !this.current;
    this.#clearSpare(); // what comes next may have changed
    this.queue = Q.enqueue(this.queue, tracks);
    if (wasEmpty) this.#load(true);
    this.#scheduleSave();
  }

  jump(orderPos: number) {
    this.queue = Q.jump(this.queue, orderPos);
    this.#load(true);
  }

  remove(orderPos: number) {
    this.queue = Q.remove(this.queue, orderPos);
    this.#refillRadio();
    this.#scheduleSave();
  }

  // --- transport ---------------------------------------------------------------------------

  toggle() {
    const a = this.#audio;
    if (!a || !this.current) return;
    if (this.#loadedId !== this.current.id) this.#load(true, this.position);
    else if (a.paused) a.play().catch((e) => this.#playFailed(e));
    else this.pause();
  }

  play() {
    if (!this.playing) this.toggle();
  }

  pause() {
    this.#endFade();
    this.#audio?.pause();
  }

  next() {
    this.#reportSkip();
    this.#advance(false);
  }

  /** Back a track; past the first few seconds the button restarts the current one instead. */
  prev({ restart = true } = {}) {
    if (restart && this.position > RESTART_THRESHOLD_S) {
      this.seek(0);
      return;
    }
    this.queue = Q.prev(this.queue);
    this.#load(this.playing);
  }

  seek(seconds: number) {
    const a = this.#audio;
    if (!a || !this.current) return;
    const s = Math.max(0, Math.min(seconds, this.duration || seconds));
    this.#endFade();
    if (this.#format !== "raw") {
      // A transcoded stream has no byte ranges to seek in: restart ffmpeg at the new offset.
      this.#load(!a.paused, s);
    } else {
      a.currentTime = s;
    }
    this.#lastPos = null;
    this.position = s;
    this.seeks++;
  }

  setVolume(v: number) {
    this.volume = Math.max(0, Math.min(1, v));
    this.#applyVolume();
    if (this.volume > 0 && this.muted) this.setMuted(false);
    this.#scheduleSave();
  }

  setMuted(m: boolean) {
    this.muted = m;
    this.#applyVolume();
    this.#scheduleSave();
  }

  toggleShuffle() {
    if (this.radio) return;
    if (this.#pool) {
      this.queue = { ...this.queue, shuffle: !this.queue.shuffle };
      this.#reorderPool();
    } else {
      this.queue = Q.setShuffle(this.queue, !this.queue.shuffle);
    }
    this.#scheduleSave();
  }

  cycleRepeat() {
    this.queue = Q.cycleRepeat(this.queue);
    this.#scheduleSave();
  }

  // --- handing over between tabs (tabs.svelte.ts) -------------------------------------------

  snapshot(): Snapshot {
    // Without the pool's ids: copying them as a tab closes held it up for seconds. The next tab
    // fetches them again and works out what is left from the queue, as after a reload.
    return $state.snapshot({
      queue: this.queue,
      radio: this.radio,
      source: this.source,
      pool: this.#pool && { query: this.#pool.query, ids: null, rest: null },
      position: this.position,
      volume: this.volume,
      muted: this.muted,
      playing: this.playing,
    });
  }

  /** Take over another tab's player, paused at its position. */
  adopt(s: Snapshot) {
    this.release();
    this.#station++; // a refill of the old queue still under way must not land here
    this.queue = s.queue;
    this.radio = s.radio;
    this.source = s.source;
    this.#pool = s.pool;
    this.position = s.position;
    this.duration = (this.current?.duration_ms ?? 0) / 1000;
    this.volume = s.volume;
    this.muted = s.muted;
    this.#applyVolume();
    this.#scheduleSave();
  }

  /** Like after a reload: what the playing tab saved last. */
  reloadSaved() {
    this.release();
    this.#station++;
    this.#restore();
    this.#applyVolume();
  }

  /** Stop and let go of the stream, so the browser's media controls no longer point at this tab. */
  release() {
    this.#endFade();
    this.#finishPlay();
    const a = this.#audio;
    if (a) {
      a.pause();
      a.removeAttribute("src");
      a.load();
    }
    this.#clearSpare();
    this.#loadedId = null;
    this.playing = false;
    this.buffering = false;
  }

  saveNow() {
    if (this.#saveTimer) clearTimeout(this.#saveTimer);
    this.#saveTimer = null;
    this.#save();
  }

  // --- internals ---------------------------------------------------------------------------

  #advance(auto: boolean, fadeMs = 0) {
    const pool = this.#pool;
    const atEnd = this.queue.pos + 1 >= this.queue.order.length;
    // More of the pool is on its way (e.g. a skip right after starting): wait for it.
    if (atEnd && pool && (pool.rest === null || pool.rest.length) && !(auto && this.queue.repeat === "one")) {
      const station = this.#station;
      const id = this.current?.id;
      void this.#refillPool(true).then(() => {
        if (station !== this.#station || id !== this.current?.id) return;
        this.#moveOn(auto, fadeMs);
      });
      return;
    }
    this.#moveOn(auto, fadeMs);
  }

  #moveOn(auto: boolean, fadeMs: number) {
    const nextQ = Q.next(this.queue, auto);
    if (!nextQ) {
      this.#audio?.pause();
      this.#finishPlay();
      this.position = 0;
      this.queue = { ...this.queue, pos: 0 };
      this.#loadedId = null;
      return;
    }
    this.queue = nextQ;
    this.#load(auto || this.playing, 0, false, fadeMs);
  }

  async #fetchTracks(ids: number[]): Promise<Track[]> {
    return ids.length ? get<Track[]>("/tracks/by-ids", { ids }) : [];
  }

  /** The pool's ids, fetched again after a reload. */
  async #poolIds(): Promise<number[] | null> {
    const pool = this.#pool;
    if (!pool) return null;
    if (!pool.ids) {
      const ids = await get<number[]>("/tracks/ids", pool.query);
      if (pool !== this.#pool) return null;
      pool.ids = ids;
    }
    return pool.ids;
  }

  /** What is left of the pool after the first `upTo` queue entries, in the order the shuffle
   * mode says: shuffled without those, or in list order after the last of them. */
  #poolRest(ids: number[], upTo: number): number[] {
    const q = this.queue;
    const queued = q.order.slice(0, upTo).map((i) => q.tracks[i].id);
    if (q.shuffle) {
      const skip = new Set(queued);
      return Q.shuffled(ids.filter((id) => !skip.has(id)));
    }
    // The last track that belongs to the pool: anything queued by hand may not.
    let last = -1;
    for (let i = queued.length - 1; i >= 0 && last < 0; i--) last = ids.indexOf(queued[i]);
    return ids.slice(last + 1);
  }

  /** Shuffle switched on or off while a pool plays: the tracks after the current one follow the
   * new mode across the whole pool (shuffling just the loaded ones would only mix those). */
  async #reorderPool() {
    const station = this.#station;
    const pool = this.#pool;
    const shuffle = this.queue.shuffle;
    try {
      const ids = await this.#poolIds();
      const cur = this.current;
      if (!ids || !cur || !pool) return;
      const rest = this.#poolRest(ids, this.queue.pos + 1);
      const tracks = await this.#fetchTracks(rest.splice(0, POOL_BATCH));
      if (station !== this.#station || pool !== this.#pool || shuffle !== this.queue.shuffle || cur !== this.current) return;
      this.#clearSpare();
      this.queue = Q.replaceUpcoming(this.queue, tracks);
      pool.rest = rest;
      this.#scheduleSave();
    } catch {
      /* offline: the loaded tracks keep their order */
    }
  }

  /** Shortly before the queue runs out, add the pool's next tracks; with repeat all, start over. */
  #refillPool(now = false): Promise<void> {
    const pool = this.#pool;
    if (!pool) return Promise.resolve();
    if (this.#poolFill?.pool === pool) return this.#poolFill.done;
    if (!now && this.queue.order.length - this.queue.pos - 1 > POOL_REFILL_AT) return Promise.resolve();
    const done = this.#fillFrom(pool).finally(() => {
      if (this.#poolFill?.pool === pool) this.#poolFill = null;
    });
    this.#poolFill = { pool, done };
    return done;
  }

  async #fillFrom(pool: Pool) {
    let rest: number[] | null = null;
    let batch: number[] = [];
    try {
      const ids = await this.#poolIds();
      if (!ids || pool !== this.#pool) return;
      let left = pool.rest ?? this.#poolRest(ids, this.queue.order.length);
      if (!left.length && this.queue.repeat === "all") left = this.queue.shuffle ? Q.shuffled(ids) : ids.slice();
      pool.rest = rest = left;
      batch = left.splice(0, POOL_BATCH);
      const tracks = await this.#fetchTracks(batch);
      if (pool !== this.#pool || rest !== pool.rest) return; // reordered meanwhile
      this.queue = Q.trimHistory(Q.append(this.queue, tracks), POOL_HISTORY);
      this.#scheduleSave();
    } catch {
      rest?.unshift(...batch); // offline: the next track change tries again
    }
  }

  /** Shortly before a radio station runs out, add its next tracks (none it already had). */
  async #refillRadio() {
    const ref = this.radio ? this.source?.ref?.match(/^radio:(track|album|artist):(\d+)$/) : null;
    const station = this.#station;
    if (!ref || this.#refilling || this.#stationEnded === station) return;
    if (this.queue.order.length - this.queue.pos - 1 > RADIO_REFILL_AT) return;
    this.#refilling = true;
    try {
      const exclude = this.queue.tracks.slice(-RADIO_EXCLUDE).map((t) => t.id);
      const more = await get<Track[]>(`/${ref[1]}s/${ref[2]}/radio`, { limit: RADIO_BATCH, exclude });
      if (station !== this.#station) return; // something else plays by now
      const have = new Set(this.queue.tracks.map((t) => t.id));
      const fresh = more.filter((t) => !have.has(t.id));
      if (!fresh.length) {
        this.#stationEnded = station;
        return;
      }
      this.queue = Q.append(this.queue, fresh);
      this.#scheduleSave();
    } catch {
      /* offline: the next track change tries again */
    } finally {
      this.#refilling = false;
    }
  }

  #load(autoplay: boolean, startAt = 0, forceTranscode = false, fadeMs = 0) {
    const track = this.current;
    if (!this.#audio || !track) return;
    this.#endFade();
    this.#refillRadio();
    this.#refillPool();
    if (startAt === 0 && !forceTranscode && this.#swapIn(track, autoplay, fadeMs)) return;
    this.#clearSpare();
    const a = this.#audio;
    if (this.#loadedId !== track.id) {
      this.#fallbackTried = false;
      this.#finishPlay();
    } else if (startAt === 0) {
      this.#finishPlay(); // replaying the same track (repeat one) counts again
    }
    this.#lastPos = null;
    const choice = forceTranscode
      ? chooseSource({ codec: null, bitrate: null }, "auto", this.#canPlay)
      : chooseSource(track, this.quality, this.#canPlay);
    this.#format = choice.format;
    this.#loadedId = track.id;
    this.error = null;
    this.buffering = autoplay;
    if (choice.format === "raw") {
      this.#offset = 0;
      a.src = streamUrl(track.id, "raw");
      if (startAt > 0) a.addEventListener("loadedmetadata", () => (a.currentTime = startAt), { once: true });
    } else {
      this.#offset = startAt;
      a.src = streamUrl(track.id, choice.format, choice.kbps, startAt);
    }
    this.position = startAt;
    this.duration = track.duration_ms / 1000;
    this.#updateMetadata(track);
    this.#applyVolume();
    if (autoplay) a.play().catch((e) => this.#playFailed(e));
    this.#scheduleSave();
  }

  /** Start loading the next track into the spare element, shortly before this one ends. */
  #maybePreload() {
    if (this.#spareId !== null || this.#fade || !this.#spare || !this.duration || !this.playing) return;
    if (this.duration - this.position > PRELOAD_BEFORE_END_S + this.crossfade) return;
    const nextQ = Q.next(this.queue, true);
    const next = nextQ ? Q.current(nextQ) : null;
    if (!next) void this.#refillPool(); // an earlier refill failed: try again before the track ends
    if (!next || next.id === this.current?.id) return; // repeat-one restarts the same element
    const choice = chooseSource(next, this.quality, this.#canPlay);
    this.#spare.src = choice.format === "raw" ? streamUrl(next.id, "raw") : streamUrl(next.id, choice.format, choice.kbps);
    this.#spare.load();
    this.#spareId = next.id;
    this.#spareTrack = next;
    this.#spareFormat = choice.format;
    this.#applyVolume();
  }

  /** With crossfade on, start the preloaded next track that many seconds before this one ends. */
  #maybeCrossfade() {
    if (!this.crossfade || this.#fade || this.#spareId === null || !this.playing || !this.duration) return;
    const left = this.duration - this.position;
    if (left > this.crossfade || left <= 0.3) return;
    const next = this.#spareTrack;
    // A very short track never fades for more than half its length.
    const ms = Math.min(left, this.crossfade, (next?.duration_ms ?? 0) / 2000) * 1000;
    if (ms < 300) return;
    this.#maybeReport(true);
    this.#advance(true, ms);
  }

  /** Stop the track fading out, e.g. on pause, skip or seek. */
  #endFade() {
    const f = this.#fade;
    if (!f) return;
    clearInterval(f.timer);
    this.#fade = null;
    f.el.pause();
    f.el.removeAttribute("src");
    f.el.load();
    this.#applyVolume();
  }

  #clearSpare() {
    if (this.#spare && this.#spareId !== null) {
      this.#spare.removeAttribute("src");
      this.#spare.load();
    }
    this.#spareId = null;
    this.#spareTrack = null;
  }

  /** If `track` is already buffered in the spare element, make that the playing one. */
  #swapIn(track: Track, autoplay: boolean, fadeMs = 0): boolean {
    const next = this.#spare;
    const old = this.#audio;
    if (!next || !old || this.#spareId !== track.id) return false;
    const oldTrack = this.#loadedId !== null ? (this.queue.tracks.find((t) => t.id === this.#loadedId) ?? null) : null;
    this.#audio = next;
    this.#spare = old;
    this.#spareId = null;
    this.#spareTrack = null;
    this.#format = this.#spareFormat;
    this.#offset = 0;
    this.#loadedId = track.id;
    this.#fallbackTried = false;
    this.#finishPlay();
    this.error = null;
    if (fadeMs > 0 && autoplay) {
      // The old track plays on (its events are ignored now) while the volumes cross over.
      const start = performance.now();
      const timer = setInterval(() => {
        const f = this.#fade;
        if (!f) return;
        f.t = Math.min(1, (performance.now() - f.start) / f.ms);
        if (f.t >= 1) this.#endFade();
        else this.#applyVolume();
      }, FADE_STEP_MS);
      this.#fade = { el: old, track: oldTrack, start, ms: fadeMs, t: 0, timer };
    } else {
      old.pause();
      old.removeAttribute("src");
      old.load();
    }
    this.#applyVolume();
    this.position = 0;
    this.duration = track.duration_ms / 1000;
    this.#updateMetadata(track);
    if (autoplay) next.play().catch((e) => this.#playFailed(e));
    else this.playing = false;
    this.#scheduleSave();
    return true;
  }

  /** Skipping a radio track early tells the server it does not fit stations like this one. */
  #reportSkip() {
    const station = this.radio ? this.source?.ref?.match(/^radio:((?:track|album|artist):\d+)$/)?.[1] : null;
    const t = this.current;
    if (!station || !t || this.position >= RADIO_SKIP_BEFORE_S) return;
    post("/radio/skips", { track_id: t.id, station }).catch(() => {
      /* offline: best effort */
    });
  }

  /** Add the time since the last timeupdate, if it really sounded (see listenedStep). */
  #measure() {
    const now = performance.now();
    if (this.#lastPos !== null && this.playing) this.#listened += listenedStep(this.#lastPos, this.position, this.#lastClock, now);
    this.#lastPos = this.position;
    this.#lastClock = now;
  }

  #maybeReport(finished = false) {
    const t = this.current;
    if (this.#reported || !t) return;
    if (!finished) {
      const half = t.duration_ms > 0 ? (t.duration_ms / 1000) * 0.5 : SCROBBLE_AFTER_S;
      if (!this.playing || this.#listened < Math.min(SCROBBLE_AFTER_S, half)) return;
    }
    this.#reported = true;
    this.#playId = post<{ id: number }>("/history", {
      track_id: t.id,
      played_ms: Math.round(this.position * 1000),
      listened_ms: Math.round(this.#listened * 1000),
      context: this.source?.ref ?? null,
    })
      .then((r) => r.id)
      .catch(() => null); // offline or logged out: history is best effort
  }

  /** Tell the server how long the reported play really sounded so far (keepalive: also while
   * the tab closes). The server keeps the largest value, so sending it again does no harm. */
  #sendListened() {
    const req = this.#playId;
    if (!req) return;
    const listened_ms = Math.round(this.#listened * 1000);
    void req.then((id) => {
      if (id === null) return;
      request("POST", `/history/${id}/listened`, { body: { listened_ms }, keepalive: true }).catch(() => {
        /* best effort */
      });
    });
  }

  /** The current play is over (next track, skip, stop): send its final time and start afresh. */
  #finishPlay() {
    this.#sendListened();
    this.#playId = null;
    this.#reported = false;
    this.#listened = 0;
    this.#lastPos = null;
  }

  #updateDuration() {
    const a = this.#audio;
    const known = (this.current?.duration_ms ?? 0) / 1000;
    // Transcoded streams report a growing or infinite duration; the library knows better.
    this.duration = this.#format === "raw" && a && Number.isFinite(a.duration) ? a.duration : known;
  }

  #onError() {
    const a = this.#audio;
    if (!a?.src || !this.current) return;
    // The browser claimed it could play the original but cannot decode it: transcode instead.
    if (this.#format === "raw" && !this.#fallbackTried) {
      this.#fallbackTried = true;
      this.#load(true, this.position, true);
      return;
    }
    this.buffering = false;
    this.error = "Dieser Titel kann nicht abgespielt werden.";
  }

  #playFailed(e: unknown) {
    this.buffering = false;
    // Autoplay without a user gesture is blocked by browsers; just wait for a click.
    if ((e as DOMException)?.name === "NotAllowedError") this.blocked = true;
    if ((e as DOMException)?.name !== "NotAllowedError" && (e as DOMException)?.name !== "AbortError") {
      this.error = "Wiedergabe fehlgeschlagen.";
    }
  }

  // --- Media Session (lock screen, Bluetooth, media keys) ------------------------------------

  #setupMediaSession() {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      ["play", () => this.toggle()],
      ["pause", () => this.pause()],
      ["previoustrack", () => this.prev()],
      ["nexttrack", () => this.next()],
      ["seekbackward", (d) => this.seek(this.position - (d.seekOffset ?? 10))],
      ["seekforward", (d) => this.seek(this.position + (d.seekOffset ?? 10))],
      ["seekto", (d) => d.seekTime !== undefined && this.seek(d.seekTime)],
      ["stop", () => this.pause()],
    ];
    for (const [action, handler] of handlers) {
      try {
        ms.setActionHandler(action, handler);
      } catch {
        /* action not supported by this browser */
      }
    }
  }

  #updateMetadata(track: Track) {
    if (!("mediaSession" in navigator)) return;
    const art = (size: 256 | 600) => {
      const url = coverUrl(track.cover, size);
      return url ? [{ src: new URL(url, window.location.href).href, sizes: `${size}x${size}`, type: "image/webp" }] : [];
    };
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: track.artist,
      album: track.album,
      artwork: [...art(256), ...art(600)],
    });
  }

  #updatePositionState() {
    if (!("mediaSession" in navigator) || !this.duration) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: this.duration,
        position: Math.min(this.position, this.duration),
        playbackRate: 1,
      });
    } catch {
      /* invalid state while switching tracks */
    }
  }

  // --- persistence (per browser; the server-side play queue comes with phase 3) ---------------

  #scheduleSave() {
    if (this.#saveTimer) return;
    this.#saveTimer = setTimeout(() => {
      this.#saveTimer = null;
      this.#save();
    }, 1000);
  }

  #save() {
    try {
      const q = this.queue;
      // Keep the stored queue bounded: a window around the current position.
      const from = Math.max(0, q.pos - 100);
      const order = q.order.slice(from, from + MAX_STORED_TRACKS);
      const tracks = order.map((i) => q.tracks[i]);
      const data = {
        tracks,
        pos: q.pos - from,
        queuedUntil: Math.max(0, (q.queuedUntil ?? 0) - from),
        shuffle: q.shuffle,
        repeat: q.repeat,
        radio: this.radio,
        source: this.source,
        pool: this.#pool?.query ?? null,
        position: this.position,
        volume: this.volume,
        muted: this.muted,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch {
      /* storage full or unavailable (private mode) */
    }
  }

  #restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      this.volume = typeof d.volume === "number" ? d.volume : this.volume;
      this.muted = !!d.muted;
      if (Array.isArray(d.tracks) && d.tracks.length) {
        this.queue = {
          tracks: d.tracks,
          order: d.tracks.map((_: unknown, i: number) => i),
          pos: Math.min(Math.max(0, d.pos | 0), d.tracks.length - 1),
          shuffle: !!d.shuffle,
          repeat: ["off", "all", "one"].includes(d.repeat) ? d.repeat : "off",
          queuedUntil: d.queuedUntil | 0,
        };
        this.radio = !!d.radio;
        this.source = d.source && typeof d.source.name === "string" ? d.source : null;
        // The ids come again from the server once they are needed.
        this.#pool = d.pool && typeof d.pool === "object" ? { query: d.pool, ids: null, rest: null } : null;
        this.position = Number(d.position) || 0;
        this.duration = (this.current?.duration_ms ?? 0) / 1000;
      }
    } catch {
      /* ignore broken storage */
    }
  }
}

/** The player of this device. */
export const localPlayer = new Player();

/** What the remote control can steer on another device (see devices.svelte.ts). */
const REMOTE_KEYS = [
  "queue", "playing", "buffering", "position", "duration", "volume", "muted", "error", "radio", "source", "current",
  "playTracks", "playPool", "playRadio", "playNext", "append", "enqueue", "jump", "remove",
  "toggle", "next", "prev", "seek", "setVolume", "setMuted", "toggleShuffle", "cycleRepeat",
] as const;
export type Controls = Pick<Player, (typeof REMOTE_KEYS)[number]>;
const remoteKeys = new Set<PropertyKey>(REMOTE_KEYS);

/** While this device steers another one, `remote` stands in for it. */
export const control = $state({ remote: null as Controls | null });

/** What the app shows and operates: this device's player, or while controlling another device
 * that one. Lock screen, media keys and the queue panel's visibility always stay local. */
export const player: Player = new Proxy(localPlayer, {
  get(target, key) {
    const src = control.remote && remoteKeys.has(key) ? control.remote : target;
    const value = Reflect.get(src, key, src);
    return typeof value === "function" ? value.bind(src) : value;
  },
  set(target, key, value) {
    return Reflect.set(target, key, value, target);
  },
});
