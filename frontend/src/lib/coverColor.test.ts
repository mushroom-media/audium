import { describe, expect, it } from "vitest";
import { dominantColor, nameColor } from "./coverColor";

function pixels(...colors: [number, number, number, number][]): Uint8ClampedArray {
  // [r, g, b, count]
  const out: number[] = [];
  for (const [r, g, b, n] of colors) for (let i = 0; i < n; i++) out.push(r, g, b, 255);
  return new Uint8ClampedArray(out);
}

describe("dominantColor", () => {
  it("picks the strongest hue, not the most common gray", () => {
    const c = dominantColor(pixels([200, 30, 30, 30], [120, 120, 120, 70]));
    expect(c).toMatch(/^hsl\((0|360) /);
  });

  it("keeps the colour dark enough for white text", () => {
    const c = dominantColor(pixels([255, 240, 120, 100]))!;
    const l = Number(c.match(/(\d+)%\)$/)![1]);
    expect(l).toBeLessThanOrEqual(48);
  });

  it("has no colour for black and white covers", () => {
    expect(dominantColor(pixels([0, 0, 0, 50], [250, 250, 250, 50]))).toBeNull();
  });
});

describe("nameColor", () => {
  it("is the same for a name every time and differs between names", () => {
    expect(nameColor("Radiohead")).toBe(nameColor("Radiohead"));
    expect(nameColor("Radiohead")).not.toBe(nameColor("Portishead"));
  });
});
