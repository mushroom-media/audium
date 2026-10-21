// The persistent player. Its <audio> elements live outside the page tree, so playback
// continues while navigating. Queue logic is in queue.ts, format choice in playback.ts.
//
// Near-gapless: a second element preloads the next track shortly before the current one ends;
// on "ended" the elements swap and the already-buffered next track starts at once. That removes
// the loading gap (typically 100-500 ms over a network). Sample-exact gapless playback (live
// albums) would need Web Audio/MSE with encoder-delay trimming; see docs/decisions.md D26.

import { coverUrl, post, streamUrl, type StreamQuality, type Track } from "./api";
import { browserCanPlay, chooseSource, type Format } from "./playback";
import * as Q from "./queue";

const STORAGE_KEY = "audium.player";
const MAX_STORED_TRACKS = 1000;
const RESTART_THRESHOLD_S = 3;
// A play counts (history) after 30 s, or half of a shorter track.
const SCROBBLE_AFTER_S = 30;
const PRELOAD_BEFORE_END_S = 20;

class Player {
  queue = $state<Q.Queue>(Q.empty);
  playing = $state(false);
  buffering = $state(false);
  position = $state(0);
  duration = $state(0);
  volume = $state(0.8);
  muted = $state(false);
  error = $state<string | null>(null);
  queueOpen = $state(false);
  quality: StreamQuality = "auto";

  current = $derived(Q.current(this.queue));

  #audio: HTMLAudioElement | null = null; // the element that is playing
  #spare: HTMLAudioElement | null = null; // preloads the next track
  #spareId: number | null = null;
  #spareFormat: Format = "raw";
  #canPlay = browserCanPlay();
  #format: Format = "raw";
  #offset = 0; // start offset of a transcoded stream, in seconds
  #loadedId: number | null = null;
  #fallbackTried = false;
  #saveTimer: ReturnType<typeof setTimeout> | null = null;
  #reported = false;

  init() {
    if (this.#audio) return;
    this.#audio = this.#wire(new Audio());
    this.#spare = this.#wire(new Audio());
    this.#restore();
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
      this.#maybeReport();
      this.#maybePreload();
      this.#updatePositionState();
      this.#scheduleSave();
    });
    on("durationchange", () => this.#updateDuration());
    on("play", () => (this.playing = true));
    on("pause", () => (this.playing = false));
    on("waiting", () => (this.buffering = true));
    on("playing", () => {
      this.buffering = false;
      this.error = null;
    });
    on("ended", () => {
      this.#maybeReport(true); // a track that played to the end always counts
      this.#advance(true);
    });
    on("error", () => this.#onError());
    return a;
  }

  #applyVolume() {
    for (const el of [this.#audio, this.#spare]) {
      if (!el) continue;
      el.volume = this.volume;
      el.muted = this.muted;
    }
  }

  // --- starting playback -------------------------------------------------------------------

  playTracks(tracks: Track[], start = 0) {
    this.queue = Q.create(tracks, start, this.queue);
    this.#load(true);
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

  jump(orderPos: number) {
    this.queue = Q.jump(this.queue, orderPos);
    this.#load(true);
  }

  remove(orderPos: number) {
    this.queue = Q.remove(this.queue, orderPos);
    this.#scheduleSave();
  }

  // --- transport ---------------------------------------------------------------------------

  toggle() {
    const a = this.#audio;
    if (!a || !this.current) return;
    if (this.#loadedId !== this.current.id) this.#load(true, this.position);
    else if (a.paused) a.play().catch((e) => this.#playFailed(e));
    else a.pause();
  }

  next() {
    this.#advance(false);
  }

  prev() {
    if (this.position > RESTART_THRESHOLD_S) {
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
    if (this.#format !== "raw") {
      // A transcoded stream has no byte ranges to seek in: restart ffmpeg at the new offset.
      this.#load(!a.paused, s);
    } else {
      a.currentTime = s;
    }
    this.position = s;
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
    this.queue = Q.setShuffle(this.queue, !this.queue.shuffle);
    this.#scheduleSave();
  }

  cycleRepeat() {
    this.queue = Q.cycleRepeat(this.queue);
    this.#scheduleSave();
  }

  // --- internals ---------------------------------------------------------------------------

  #advance(auto: boolean) {
    const nextQ = Q.next(this.queue, auto);
    if (!nextQ) {
      this.#audio?.pause();
      this.position = 0;
      this.queue = { ...this.queue, pos: 0 };
      this.#loadedId = null;
      return;
    }
    this.queue = nextQ;
    this.#load(auto || this.playing);
  }

  #load(autoplay: boolean, startAt = 0, forceTranscode = false) {
    const track = this.current;
    if (!this.#audio || !track) return;
    if (startAt === 0 && !forceTranscode && this.#swapIn(track, autoplay)) return;
    this.#clearSpare();
    const a = this.#audio;
    if (this.#loadedId !== track.id) {
      this.#fallbackTried = false;
      this.#reported = false;
    } else if (startAt === 0) {
      this.#reported = false; // replaying the same track (repeat one) counts again
    }
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
    if (autoplay) a.play().catch((e) => this.#playFailed(e));
    this.#scheduleSave();
  }

  /** Start loading the next track into the spare element, shortly before this one ends. */
  #maybePreload() {
    if (this.#spareId !== null || !this.#spare || !this.duration || !this.playing) return;
    if (this.duration - this.position > PRELOAD_BEFORE_END_S) return;
    const nextQ = Q.next(this.queue, true);
    const next = nextQ ? Q.current(nextQ) : null;
    if (!next || next.id === this.current?.id) return; // repeat-one restarts the same element
    const choice = chooseSource(next, this.quality, this.#canPlay);
    this.#spare.src = choice.format === "raw" ? streamUrl(next.id, "raw") : streamUrl(next.id, choice.format, choice.kbps);
    this.#spare.load();
    this.#spareId = next.id;
    this.#spareFormat = choice.format;
  }

  #clearSpare() {
    if (this.#spare && this.#spareId !== null) {
      this.#spare.removeAttribute("src");
      this.#spare.load();
    }
    this.#spareId = null;
  }

  /** If `track` is already buffered in the spare element, make that the playing one. */
  #swapIn(track: Track, autoplay: boolean): boolean {
    const next = this.#spare;
    const old = this.#audio;
    if (!next || !old || this.#spareId !== track.id) return false;
    this.#audio = next;
    this.#spare = old;
    this.#spareId = null;
    this.#format = this.#spareFormat;
    this.#offset = 0;
    this.#loadedId = track.id;
    this.#fallbackTried = false;
    this.#reported = false;
    this.error = null;
    old.pause();
    old.removeAttribute("src");
    old.load();
    this.#applyVolume();
    this.position = 0;
    this.duration = track.duration_ms / 1000;
    this.#updateMetadata(track);
    if (autoplay) next.play().catch((e) => this.#playFailed(e));
    else this.playing = false;
    this.#scheduleSave();
    return true;
  }

  #maybeReport(finished = false) {
    const t = this.current;
    if (this.#reported || !t) return;
    if (!finished) {
      const half = t.duration_ms > 0 ? (t.duration_ms / 1000) * 0.5 : SCROBBLE_AFTER_S;
      if (!this.playing || this.position < Math.min(SCROBBLE_AFTER_S, half)) return;
    }
    this.#reported = true;
    post("/history", { track_id: t.id, played_ms: Math.round(this.position * 1000) }).catch(() => {
      /* offline or logged out: history is best effort */
    });
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
      ["pause", () => this.#audio?.pause()],
      ["previoustrack", () => this.prev()],
      ["nexttrack", () => this.next()],
      ["seekbackward", (d) => this.seek(this.position - (d.seekOffset ?? 10))],
      ["seekforward", (d) => this.seek(this.position + (d.seekOffset ?? 10))],
      ["seekto", (d) => d.seekTime !== undefined && this.seek(d.seekTime)],
      ["stop", () => this.#audio?.pause()],
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
        shuffle: q.shuffle,
        repeat: q.repeat,
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
        };
        this.position = Number(d.position) || 0;
        this.duration = (this.current?.duration_ms ?? 0) / 1000;
      }
    } catch {
      /* ignore broken storage */
    }
  }
}

export const player = new Player();
