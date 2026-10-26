// Play queue as pure functions: easy to test, and the player just stores the latest state.
//
// `tracks` keeps insertion order; `order` is the play order (indices into `tracks`);
// `pos` points into `order`. Shuffling only rewrites `order`, so turning it off restores
// the original sequence.

import type { Track } from "./api";

export type Repeat = "off" | "all" | "one";

export interface Queue {
  tracks: Track[];
  order: number[];
  pos: number;
  shuffle: boolean;
  repeat: Repeat;
}

export type Rng = () => number;

export const empty: Queue = { tracks: [], order: [], pos: -1, shuffle: false, repeat: "off" };

export function shuffled<T>(items: T[], rng: Rng = Math.random): T[] {
  const a = items.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function identity(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

/** `start`: the track to play first; null = none chosen (with shuffle, the first one is random too). */
export function create(tracks: Track[], start: number | null, prev: Queue = empty, rng: Rng = Math.random): Queue {
  if (!tracks.length) return { ...empty, shuffle: prev.shuffle, repeat: prev.repeat };
  const s = Math.min(Math.max(start ?? 0, 0), tracks.length - 1);
  if (!prev.shuffle) return { tracks, order: identity(tracks.length), pos: s, shuffle: false, repeat: prev.repeat };
  if (start === null) return { tracks, order: shuffled(identity(tracks.length), rng), pos: 0, shuffle: true, repeat: prev.repeat };
  // The chosen track plays first, the rest in random order.
  const rest = shuffled(identity(tracks.length).filter((i) => i !== s), rng);
  return { tracks, order: [s, ...rest], pos: 0, shuffle: true, repeat: prev.repeat };
}

export function current(q: Queue): Track | null {
  return q.pos >= 0 && q.pos < q.order.length ? q.tracks[q.order[q.pos]] : null;
}

/** The queue after the current track; null when playback should stop. `auto`: the track ended
 * by itself (repeat-one replays it; a manual "next" always moves on). */
export function next(q: Queue, auto: boolean): Queue | null {
  if (!q.order.length) return null;
  if (auto && q.repeat === "one") return { ...q };
  if (q.pos + 1 < q.order.length) return { ...q, pos: q.pos + 1 };
  if (q.repeat === "all" || (!auto && q.repeat === "one")) return { ...q, pos: 0 };
  return null;
}

export function prev(q: Queue): Queue {
  if (q.pos > 0) return { ...q, pos: q.pos - 1 };
  if (q.repeat === "all" && q.order.length) return { ...q, pos: q.order.length - 1 };
  return { ...q };
}

export function setShuffle(q: Queue, on: boolean, rng: Rng = Math.random): Queue {
  if (on === q.shuffle) return q;
  if (!q.order.length) return { ...q, shuffle: on };
  const cur = q.order[q.pos];
  if (on) {
    const rest = shuffled(identity(q.tracks.length).filter((i) => i !== cur), rng);
    return { ...q, order: [cur, ...rest], pos: 0, shuffle: true };
  }
  return { ...q, order: identity(q.tracks.length), pos: cur, shuffle: false };
}

export function cycleRepeat(q: Queue): Queue {
  const nextMode: Record<Repeat, Repeat> = { off: "all", all: "one", one: "off" };
  return { ...q, repeat: nextMode[q.repeat] };
}

/** Insert right after the current track ("play next"). */
export function playNext(q: Queue, add: Track[]): Queue {
  if (!q.order.length) return create(add, 0, q);
  const base = q.tracks.length;
  const ids = add.map((_, i) => base + i);
  const order = [...q.order.slice(0, q.pos + 1), ...ids, ...q.order.slice(q.pos + 1)];
  return { ...q, tracks: [...q.tracks, ...add], order };
}

export function append(q: Queue, add: Track[]): Queue {
  if (!q.order.length) return create(add, 0, q);
  const base = q.tracks.length;
  return { ...q, tracks: [...q.tracks, ...add], order: [...q.order, ...add.map((_, i) => base + i)] };
}

export function jump(q: Queue, orderPos: number): Queue {
  if (orderPos < 0 || orderPos >= q.order.length) return q;
  return { ...q, pos: orderPos };
}

/** Remove the entry at `orderPos` from the play order (not the current one). */
export function remove(q: Queue, orderPos: number): Queue {
  if (orderPos === q.pos || orderPos < 0 || orderPos >= q.order.length) return q;
  const order = q.order.filter((_, i) => i !== orderPos);
  return { ...q, order, pos: orderPos < q.pos ? q.pos - 1 : q.pos };
}

/** Keep what has played and the current track, replace everything after it with `add`. */
export function replaceUpcoming(q: Queue, add: Track[]): Queue {
  if (!q.order.length) return create(add, 0, q);
  const kept = q.order.slice(0, q.pos + 1).map((i) => q.tracks[i]);
  const tracks = [...kept, ...add];
  return { ...q, tracks, order: identity(tracks.length), pos: q.pos };
}

/** Forget all but the last `keep` played tracks, so a queue that keeps growing stays bounded. */
export function trimHistory(q: Queue, keep: number): Queue {
  const from = q.pos - keep;
  if (from <= 0) return q;
  const order = q.order.slice(from);
  return { ...q, tracks: order.map((i) => q.tracks[i]), order: identity(order.length), pos: q.pos - from };
}

export function upcoming(q: Queue): { track: Track; orderPos: number }[] {
  return q.order.slice(q.pos + 1).map((idx, i) => ({ track: q.tracks[idx], orderPos: q.pos + 1 + i }));
}
