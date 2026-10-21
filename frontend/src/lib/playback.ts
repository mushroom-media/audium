// Which stream to request for a track: the original file when this browser can play it,
// otherwise (or when the user chose a lower quality) an ffmpeg transcode.

import type { StreamQuality, Track } from "./api";

export type Format = "raw" | "opus" | "aac" | "mp3";
export type CanPlay = (mime: string) => boolean;

// codec (as reported by the scanner) -> MIME type to ask the browser about
const NATIVE: Record<string, string> = {
  mp3: "audio/mpeg",
  flac: "audio/flac",
  vorbis: 'audio/ogg; codecs="vorbis"',
  opus: 'audio/ogg; codecs="opus"',
  aac: 'audio/mp4; codecs="mp4a.40.2"',
  alac: 'audio/mp4; codecs="alac"',
  pcm: "audio/wav",
};

const KBPS: Record<Exclude<StreamQuality, "auto">, Record<Exclude<Format, "raw">, number>> = {
  high: { opus: 192, aac: 256, mp3: 256 },
  medium: { opus: 128, aac: 160, mp3: 160 },
  low: { opus: 64, aac: 96, mp3: 96 },
};

export function browserCanPlay(): CanPlay {
  const el = typeof document !== "undefined" ? document.createElement("audio") : null;
  const cache = new Map<string, boolean>();
  return (mime) => {
    if (!el) return false;
    if (!cache.has(mime)) cache.set(mime, el.canPlayType(mime) !== "");
    return cache.get(mime)!;
  };
}

export function nativeMime(track: Pick<Track, "codec">, container?: string | null): string | null {
  if (!track.codec) return null;
  if (track.codec === "pcm" && container === "aiff") return "audio/aiff";
  return NATIVE[track.codec] ?? null;
}

export function transcodeTarget(canPlay: CanPlay): Exclude<Format, "raw"> {
  if (canPlay('audio/ogg; codecs="opus"')) return "opus";
  if (canPlay("audio/aac") || canPlay("audio/mp4")) return "aac";
  return "mp3";
}

export function chooseSource(
  track: Pick<Track, "codec" | "bitrate">,
  quality: StreamQuality,
  canPlay: CanPlay,
): { format: Format; kbps?: number } {
  const mime = nativeMime(track);
  const native = mime !== null && canPlay(mime);
  const target = transcodeTarget(canPlay);
  if (quality === "auto") {
    return native ? { format: "raw" } : { format: target, kbps: KBPS.high[target] };
  }
  const kbps = KBPS[quality][target];
  // Already smaller than the requested quality: transcoding would only lose quality.
  if (native && track.bitrate && track.bitrate / 1000 <= kbps * 1.1) return { format: "raw" };
  return { format: target, kbps };
}
