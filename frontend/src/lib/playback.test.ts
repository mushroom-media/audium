import { describe, expect, it } from "vitest";
import { listenedStep, replayGainFactor } from "./playback";

const rg = (track_gain: number | null, album_gain: number | null = null, track_peak: number | null = null, album_peak: number | null = null) => ({
  track_gain,
  album_gain,
  track_peak,
  album_peak,
});

describe("replayGainFactor", () => {
  it("leaves the volume alone when off or without tags", () => {
    expect(replayGainFactor(rg(-6), "off")).toBe(1);
    expect(replayGainFactor(null, "track")).toBe(1);
    expect(replayGainFactor(undefined, "album")).toBe(1);
    expect(replayGainFactor(rg(null), "track")).toBe(1);
  });

  it("turns decibels into a factor", () => {
    expect(replayGainFactor(rg(-6), "track")).toBeCloseTo(0.501, 3);
    expect(replayGainFactor(rg(-20), "track")).toBeCloseTo(0.1, 5);
  });

  it("picks the track or album value, falling back to the other", () => {
    expect(replayGainFactor(rg(-6, -12), "album")).toBeCloseTo(0.251, 3);
    expect(replayGainFactor(rg(-6, -12), "track")).toBeCloseTo(0.501, 3);
    expect(replayGainFactor(rg(null, -12), "track")).toBeCloseTo(0.251, 3);
    expect(replayGainFactor(rg(-6, null), "album")).toBeCloseTo(0.501, 3);
  });

  it("never amplifies and never clips", () => {
    expect(replayGainFactor(rg(4), "track")).toBe(1);
    expect(replayGainFactor(rg(-1, null, 1.25), "track")).toBeCloseTo(0.8, 5); // the peak limits it
  });
});

describe("listenedStep", () => {
  it("counts the time that really played", () => {
    expect(listenedStep(10, 10.25, 1000, 1250)).toBeCloseTo(0.25);
  });
  it("counts no skipped part: a seek forward moves the position further than the clock", () => {
    expect(listenedStep(10, 120, 1000, 1250)).toBeCloseTo(0.25);
  });
  it("counts nothing while buffering or paused, or for a seek back", () => {
    expect(listenedStep(10, 10, 1000, 61000)).toBe(0);
    expect(listenedStep(100, 5, 1000, 1250)).toBe(0);
  });
});
