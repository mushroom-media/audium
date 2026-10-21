"""On-the-fly transcoding with ffmpeg, streamed to the client while it is produced.

The output never sits in memory as a whole: ffmpeg writes to a pipe, chunks go straight to the
socket. When the client goes away (skip, seek, closed tab) the generator is cancelled and the
ffmpeg process is killed.
"""

import asyncio
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass

from audium.logging import get_logger

log = get_logger(__name__)

_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Target:
    name: str
    media_type: str
    codec_args: tuple[str, ...]
    default_kbps: int


TARGETS = {
    # Ogg/Opus: best quality per bit; Chrome, Firefox, Edge, Safari 17+
    "opus": Target("opus", "audio/ogg", ("-c:a", "libopus", "-ar", "48000", "-f", "ogg"), 128),
    # AAC in ADTS: plays everywhere, including older Safari/iOS
    "aac": Target("aac", "audio/aac", ("-c:a", "aac", "-f", "adts"), 192),
    "mp3": Target("mp3", "audio/mpeg", ("-c:a", "libmp3lame", "-f", "mp3"), 256),
}
MIN_KBPS, MAX_KBPS = 32, 320


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def build_command(path: str, target: Target, kbps: int, start_s: float) -> list[str]:
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]  # before -i: fast input seeking
    cmd += [
        "-i", path,
        "-map", "0:a:0", "-vn", "-sn", "-dn",  # first audio stream only (no embedded cover "video")
        "-map_metadata", "-1",
        *target.codec_args,
        "-b:a", f"{kbps}k",
        "pipe:1",
    ]  # fmt: skip
    return cmd


class Transcoder:
    """Limits concurrent ffmpeg processes; a Raspberry Pi manages a handful at most."""

    def __init__(self, max_concurrent: int) -> None:
        self._slots = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent

    def busy(self) -> bool:
        return self._slots.locked()

    async def stream(self, path: str, target: Target, kbps: int, start_s: float) -> AsyncIterator[bytes]:
        async with self._slots:
            proc = await asyncio.create_subprocess_exec(
                *build_command(path, target, kbps, start_s),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                while True:
                    chunk = await proc.stdout.read(_CHUNK)
                    if not chunk:
                        break
                    yield chunk
                code = await proc.wait()
                if code != 0:
                    err = (await proc.stderr.read()).decode(errors="replace")[-500:]
                    log.warning("transcode.failed", path=path, code=code, error=err.strip())
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
