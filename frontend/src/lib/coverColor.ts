// The main colour of a cover, for backgrounds made from it (radio covers). The same rule as the
// server's covers.dominant_color: the hue with the most summed chroma, kept in a range that works
// under white text. Read from the 64 px thumbnail and remembered per image.

import { coverUrl } from "./api";

const BUCKETS = 12;
const MIN_CHROMA = 30;
const MIN_SHARE = 0.05;

const known = new Map<string, Promise<string | null>>();

function hsl(h: number, s: number, l: number): string {
  return `hsl(${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%)`;
}

/** Main colour of RGBA pixel data as a CSS colour; null if the image has no clear colour. */
export function dominantColor(px: Uint8ClampedArray): string | null {
  const buckets = Array.from({ length: BUCKETS }, () => [0, 0, 0, 0]); // weight, weighted r, g, b
  let colored = 0;
  for (let i = 0; i < px.length; i += 4) {
    const [r, g, b] = [px[i], px[i + 1], px[i + 2]];
    const max = Math.max(r, g, b);
    const chroma = max - Math.min(r, g, b);
    if (chroma < MIN_CHROMA) continue; // gray pixels do not vote
    colored++;
    let h = max === r ? (g - b) / chroma : max === g ? 2 + (b - r) / chroma : 4 + (r - g) / chroma;
    h = (((h / 6) % 1) + 1) % 1;
    const bucket = buckets[Math.floor(h * BUCKETS) % BUCKETS];
    bucket[0] += chroma;
    bucket[1] += r * chroma;
    bucket[2] += g * chroma;
    bucket[3] += b * chroma;
  }
  if (colored < (px.length / 4) * MIN_SHARE) return null;
  const [w, rs, gs, bs] = buckets.reduce((a, b) => (b[0] > a[0] ? b : a));
  const [r, g, b] = [rs / w / 255, gs / w / 255, bs / w / 255];
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  let h = max === r ? (g - b) / d : max === g ? 2 + (b - r) / d : 4 + (r - g) / d;
  h = (((h / 6) % 1) + 1) % 1;
  return hsl(h, Math.min(s, 0.6), Math.min(Math.max(l, 0.35), 0.48));
}

/** A colour of the name's own, the same every time: for covers without a clear colour. */
export function nameColor(name: string): string {
  const hue = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return hsl(hue / 360, 0.45, 0.4);
}

/** Main colour of a stored cover, null if it has none or cannot be read. */
export function coverColor(hash: string): Promise<string | null> {
  let found = known.get(hash);
  if (!found) {
    found = new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = canvas.height = 32;
          const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
          ctx.drawImage(img, 0, 0, 32, 32);
          resolve(dominantColor(ctx.getImageData(0, 0, 32, 32).data));
        } catch {
          resolve(null); // a cover from another origin without CORS: no pixels to read
        }
      };
      img.onerror = () => resolve(null);
      img.src = coverUrl(hash, 64)!;
    });
    known.set(hash, found);
  }
  return found;
}
