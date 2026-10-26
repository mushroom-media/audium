// What a player tells those who steer it, and the commands it takes from them. Shared by the
// remote control between devices (devices.svelte.ts) and between tabs (tabs.svelte.ts).

import type { Track } from "./api";
import { localPlayer, type QueueSource, type TrackPool } from "./player.svelte";
import type * as Q from "./queue";

export interface PlayerStatus {
  playing: boolean;
  buffering: boolean;
  position: number;
  duration: number;
  volume: number;
  muted: boolean;
  error: string | null;
  blocked: boolean;
  radio: boolean;
  shuffle: boolean;
  repeat: Q.Repeat;
  pos: number;
  length: number;
  source: QueueSource | null;
  track: Track | null;
}

/** Part of the queue around the current track, in play order, starting at `offset`. */
export interface QueueWindow {
  offset: number;
  tracks: Track[];
}

/** What a steering side shows: the status, the queue window and when the status arrived
 * (performance.now() of the receiving side, to move the position on while it plays). */
export interface Mirror {
  status: PlayerStatus | null;
  queue?: QueueWindow | null;
  received?: number;
}

const WINDOW_BEFORE = 50;
export const WINDOW_SIZE = 300;

export function playerStatus(): PlayerStatus {
  const p = localPlayer;
  return {
    playing: p.playing,
    buffering: p.buffering,
    position: Math.max(0, p.position),
    duration: Math.max(0, p.duration),
    volume: p.volume,
    muted: p.muted,
    error: p.error,
    blocked: p.blocked,
    radio: p.radio,
    shuffle: p.queue.shuffle,
    repeat: p.queue.repeat,
    pos: Math.max(0, p.queue.pos),
    length: p.queue.order.length,
    source: p.source,
    track: p.current,
  };
}

export function queueWindow(): QueueWindow {
  const q = localPlayer.queue;
  const offset = Math.max(0, q.pos - WINDOW_BEFORE);
  return { offset, tracks: q.order.slice(offset, offset + WINDOW_SIZE).map((i) => q.tracks[i]) };
}

/** Reads everything a steering side shows, so an effect around it reruns on each change. The
 * position only on seeks: it moves on by itself while playing. */
export function watchPlayer() {
  const p = localPlayer;
  void [p.playing, p.buffering, p.duration, p.volume, p.muted, p.error, p.blocked, p.radio, p.source, p.queue, p.seeks];
}

// --- carrying out commands ----------------------------------------------------------------------

export type Args = Record<string, unknown>;

const num = (v: unknown, fallback = 0) => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const tracksOf = (v: unknown) => (Array.isArray(v) ? (v as Track[]).filter((t) => t && typeof t.id === "number") : []);
const sourceOf = (v: unknown) => (v && typeof v === "object" && typeof (v as QueueSource).name === "string" ? (v as QueueSource) : null);
const shuffleOf = (v: unknown) => (typeof v === "boolean" ? v : localPlayer.queue.shuffle);

export function runCommand({ action, args }: { action: string; args: Args }) {
  const p = localPlayer;
  switch (action) {
    case "toggle": return p.toggle();
    case "play": return p.play();
    case "pause": return p.pause();
    case "next": return p.next();
    case "prev": return p.prev({ restart: args.restart !== false });
    case "seek": return p.seek(num(args.s));
    case "volume": return p.setVolume(num(args.v, p.volume));
    case "mute": return p.setMuted(!!args.m);
    case "shuffle":
      if (typeof args.on !== "boolean" || args.on !== p.queue.shuffle) p.toggleShuffle();
      return;
    case "repeat":
      // Without a mode: the next one, like the button.
      if (typeof args.mode !== "string") return p.cycleRepeat();
      for (let i = 0; i < 3 && p.queue.repeat !== args.mode; i++) p.cycleRepeat();
      return;
    case "jump": return p.jump(num(args.pos));
    case "remove": return p.remove(num(args.pos));
    case "play_tracks": {
      const start = args.start === null ? null : num(args.start);
      return p.playTracks(tracksOf(args.tracks), start, shuffleOf(args.shuffle), sourceOf(args.source));
    }
    case "play_pool":
      if (args.query && typeof args.query === "object") {
        const startId = typeof args.start_id === "number" ? args.start_id : null;
        p.playPool(args.query as TrackPool, startId, shuffleOf(args.shuffle), sourceOf(args.source)).catch(() => {});
      }
      return;
    case "play_radio": return p.playRadio(tracksOf(args.tracks), sourceOf(args.source), num(args.start));
    case "play_next": return p.playNext(tracksOf(args.tracks));
    case "append": return p.append(tracksOf(args.tracks));
  }
}
