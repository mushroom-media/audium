import { describe, expect, it } from "vitest";
import type { Track } from "./api";
import { chooseSource } from "./playback";
import * as Q from "./queue";

const t = (id: number, extra: Partial<Track> = {}): Track => ({
  id,
  title: `T${id}`,
  artist: "A",
  artist_id: 1,
  album: "B",
  album_id: 1,
  track_no: id,
  disc_no: 1,
  year: 2000,
  duration_ms: 1000,
  codec: "mp3",
  bitrate: 320000,
  cover: null,
  ...extra,
});
const tracks = [t(1), t(2), t(3), t(4), t(5)];
const ids = (q: Q.Queue) => q.order.map((i) => q.tracks[i].id);
let seed = 1;
const rng = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;

describe("queue", () => {
  it("plays from the chosen track and stops at the end", () => {
    let q: Q.Queue | null = Q.create(tracks, 3);
    expect(Q.current(q)!.id).toBe(4);
    q = Q.next(q, true)!;
    expect(Q.current(q)!.id).toBe(5);
    expect(Q.next(q, true)).toBeNull();
  });

  it("repeat all wraps, repeat one replays only when the track ends", () => {
    let q = Q.create(tracks, 4);
    q = { ...q, repeat: "all" };
    expect(Q.current(Q.next(q, true)!)!.id).toBe(1);
    q = { ...q, repeat: "one" };
    expect(Q.current(Q.next(q, true)!)!.id).toBe(5);
    expect(Q.current(Q.next(q, false)!)!.id).toBe(1); // manual next leaves the track
    expect(Q.cycleRepeat(Q.cycleRepeat(Q.cycleRepeat(q))).repeat).toBe("one");
  });

  it("shuffle keeps the current track first and restores order when turned off", () => {
    let q = Q.create(tracks, 2);
    q = Q.setShuffle(q, true, rng);
    expect(Q.current(q)!.id).toBe(3);
    expect([...ids(q)].sort()).toEqual([1, 2, 3, 4, 5]);
    q = Q.next(q, true)!;
    const playing = Q.current(q)!.id;
    q = Q.setShuffle(q, false);
    expect(ids(q)).toEqual([1, 2, 3, 4, 5]);
    expect(Q.current(q)!.id).toBe(playing);
  });

  it("starting a new list while shuffle is on shuffles it", () => {
    const q = Q.create(tracks, 0, { ...Q.empty, shuffle: true }, rng);
    expect(q.shuffle).toBe(true);
    expect(Q.current(q)!.id).toBe(1);
    expect(q.order.length).toBe(5);
  });

  it("shuffling a whole list picks the first track at random too", () => {
    const firsts = new Set<number>();
    for (let i = 0; i < 20; i++) {
      const q = Q.create(tracks, null, { ...Q.empty, shuffle: true }, rng);
      expect([...ids(q)].sort()).toEqual([1, 2, 3, 4, 5]);
      firsts.add(Q.current(q)!.id);
    }
    expect(firsts.size).toBeGreaterThan(1);
    expect(Q.current(Q.create(tracks, null))!.id).toBe(1); // without shuffle: from the top
  });

  it("play next, append, jump and remove", () => {
    let q = Q.create(tracks.slice(0, 3), 0);
    q = Q.playNext(q, [t(9)]);
    expect(ids(q)).toEqual([1, 9, 2, 3]);
    q = Q.append(q, [t(8)]);
    expect(ids(q)).toEqual([1, 9, 2, 3, 8]);
    q = Q.jump(q, 3);
    expect(Q.current(q)!.id).toBe(3);
    q = Q.remove(q, 1);
    expect(ids(q)).toEqual([1, 2, 3, 8]);
    expect(Q.current(q)!.id).toBe(3);
    expect(Q.remove(q, q.pos)).toBe(q); // the playing track stays
    expect(Q.upcoming(q).map((u) => u.track.id)).toEqual([8]);
  });

  it("queued tracks wait right after the current one, first in, first out", () => {
    let q = Q.create(tracks, 0);
    q = Q.enqueue(q, [t(8)]);
    q = Q.enqueue(q, [t(9)]);
    expect(ids(q)).toEqual([1, 8, 9, 2, 3, 4, 5]);
    // Playing on: the next one still comes before the rest of the list
    q = Q.next(q, false)!;
    q = Q.enqueue(q, [t(7)]);
    expect(ids(q)).toEqual([1, 8, 9, 7, 2, 3, 4, 5]);
    // Past all of them, a new one is next again
    q = Q.jump(q, 4);
    q = Q.enqueue(q, [t(6)]);
    expect(ids(q)).toEqual([1, 8, 9, 7, 2, 6, 3, 4, 5]);
    // Stepping back does not put the new one in front of what is queued
    q = Q.prev(q);
    q = Q.enqueue(q, [t(10)]);
    expect(ids(q)).toEqual([1, 8, 9, 7, 2, 6, 10, 3, 4, 5]);
    expect(Q.enqueue(Q.empty, [t(1)]).pos).toBe(0);
  });

  it("removing, playing next and jumping back keep the queued block right", () => {
    let q = Q.enqueue(Q.enqueue(Q.create(tracks, 0), [t(8)]), [t(9)]);
    q = Q.remove(q, 1);
    q = Q.enqueue(q, [t(7)]);
    expect(ids(q)).toEqual([1, 9, 7, 2, 3, 4, 5]);
    q = Q.playNext(q, [t(6)]);
    q = Q.enqueue(q, [t(10)]);
    expect(ids(q)).toEqual([1, 6, 9, 7, 10, 2, 3, 4, 5]);
    q = Q.jump(q, 7);
    q = Q.jump(q, 0); // from here on nothing counts as queued any more
    q = Q.enqueue(q, [t(11)]);
    expect(ids(q)).toEqual([1, 11, 6, 9, 7, 10, 2, 3, 4, 5]);
  });

  it("repeat all starting over forgets the queued block", () => {
    let q: Q.Queue = { ...Q.enqueue(Q.create(tracks.slice(0, 2), 1), [t(8)]), repeat: "all" };
    q = Q.next(Q.next(q, false)!, false)!;
    expect(Q.current(q)!.id).toBe(1);
    expect(ids(Q.enqueue(q, [t(9)]))).toEqual([1, 9, 2, 8]);
  });

  it("shuffle and the pool's reorder keep queued tracks next", () => {
    let q = Q.enqueue(Q.enqueue(Q.create(tracks, 1), [t(8)]), [t(9)]);
    q = Q.setShuffle(q, true, rng);
    expect(ids(q).slice(0, 3)).toEqual([2, 8, 9]);
    q = Q.enqueue(q, [t(7)]);
    expect(ids(q).slice(0, 4)).toEqual([2, 8, 9, 7]);
    q = Q.setShuffle(q, false);
    expect(ids(q)).toEqual([1, 2, 8, 9, 7, 3, 4, 5]);
    expect(Q.current(q)!.id).toBe(2);
    expect(ids(Q.replaceUpcoming(q, [t(6)]))).toEqual([1, 2, 8, 9, 7, 6]);
    expect(Q.replaceUpcoming(q, [t(6)]).pos).toBe(1);
    expect(ids(Q.enqueue(Q.replaceUpcoming(q, [t(6)]), [t(5)]))).toEqual([1, 2, 8, 9, 7, 5, 6]);
  });

  it("forgetting history moves the queued block along", () => {
    let q = Q.enqueue(Q.create(tracks, 3), [t(8)]);
    q = Q.trimHistory(q, 1);
    q = Q.enqueue(q, [t(9)]);
    expect(ids(q)).toEqual([3, 4, 8, 9, 5]);
  });

  it("prev at the start stays, with repeat all it wraps", () => {
    const q = Q.create(tracks, 0);
    expect(Q.prev(q).pos).toBe(0);
    expect(Q.prev({ ...q, repeat: "all" }).pos).toBe(4);
  });
  it("replaceUpcoming keeps the played tracks and the current one", () => {
    let q = Q.jump(Q.create(tracks, 0), 2);
    q = Q.replaceUpcoming(q, [t(9), t(8)]);
    expect(ids(q)).toEqual([1, 2, 3, 9, 8]);
    expect(Q.current(q)!.id).toBe(3);
  });

  it("trimHistory drops old played tracks only", () => {
    const q = Q.trimHistory(Q.jump(Q.create(tracks, 0), 3), 1);
    expect(ids(q)).toEqual([3, 4, 5]);
    expect(Q.current(q)!.id).toBe(4);
    expect(Q.trimHistory(q, 5)).toBe(q);
  });
});

describe("chooseSource", () => {
  const chrome = (mime: string) => !mime.includes("alac") && !mime.includes("aiff");
  const oldSafari = (mime: string) => !mime.includes("ogg");

  it("plays originals the browser supports, transcodes the rest", () => {
    expect(chooseSource(t(1, { codec: "flac" }), "auto", chrome)).toEqual({ format: "raw" });
    expect(chooseSource(t(1, { codec: "wma" }), "auto", chrome)).toEqual({ format: "opus", kbps: 192 });
    expect(chooseSource(t(1, { codec: "ape" }), "auto", oldSafari)).toEqual({ format: "aac", kbps: 256 });
    expect(chooseSource(t(1, { codec: "alac" }), "auto", chrome).format).toBe("opus");
    expect(chooseSource(t(1, { codec: null }), "auto", chrome).format).toBe("opus");
  });

  it("lower qualities transcode, unless the original is already small", () => {
    expect(chooseSource(t(1, { codec: "flac", bitrate: 900000 }), "low", chrome)).toEqual({ format: "opus", kbps: 64 });
    expect(chooseSource(t(1, { codec: "mp3", bitrate: 128000 }), "medium", chrome)).toEqual({ format: "raw" });
    expect(chooseSource(t(1, { codec: "mp3", bitrate: 320000 }), "medium", chrome)).toEqual({ format: "opus", kbps: 128 });
  });
});
