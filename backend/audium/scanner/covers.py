"""Cover images, stored once per distinct image as WebP thumbnails.

Layout: <data>/covers/<hash[:2]>/<hash>_<size>.webp, hash = xxh3-128 of the original bytes.
JPEG copies (<hash>_<size>.jpg) appear next to them when a client that cannot show WebP asks.
Because the hash is part of the URL, responses can be cached forever (immutable).
"""

import io
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from pathlib import Path

import xxhash
from PIL import Image, ImageOps

SIZES = (64, 256, 600)
_WEBP_QUALITY = 80
_WEBP_METHOD = 2  # 0 (fast) .. 6 (small); 2 is ~2.5x faster than the default 4 for a few % more bytes
_JPEG_QUALITY = 85
_MAX_PIXELS = 80_000_000  # ~9000x9000; larger "covers" are almost certainly not covers
_MEMO_LIMIT = 100_000

CoverResult = tuple[str, int, int] | None  # (hash, width, height), None = not a usable image


def hash_bytes(data: bytes) -> str:
    return xxhash.xxh3_128_hexdigest(data)


def render(root: str, data: bytes) -> CoverResult:
    """Write all thumbnail sizes of one image (skipped if they exist). Module-level so the
    scanner can run it in its reader processes; WebP encoding holds the GIL."""
    store_root = Path(root)
    digest = hash_bytes(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > _MAX_PIXELS:
                return None
            width, height = img.size
            if all(_path(store_root, digest, s).exists() for s in SIZES):
                return digest, width, height
            img.draft("RGB", (SIZES[-1], SIZES[-1]))  # JPEG: decode at reduced scale, still >= 600 px
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA" if _has_alpha(img) else "RGB")
            (store_root / digest[:2]).mkdir(parents=True, exist_ok=True)
            # Largest first; each smaller size is derived from the previous one (cheaper).
            for size in sorted(SIZES, reverse=True):
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
                _write_atomic(_path(store_root, digest, size), img)
            return digest, width, height
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        return None


def _path(root: Path, digest: str, size: int) -> Path:
    return root / digest[:2] / f"{digest}_{size}.webp"


def _write_atomic(target: Path, img: Image.Image) -> None:
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            img.save(f, "WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


class CoverStore:
    """Remembers which images were already processed, so the ~10 tracks of an album that embed
    the same picture cost one render. Thread-safe."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._done: dict[str, CoverResult] = {}
        self._pending: dict[str, threading.Event] = {}

    hash_bytes = staticmethod(hash_bytes)

    def path(self, digest: str, size: int) -> Path:
        return _path(self.root, digest, size)

    def exists(self, digest: str) -> bool:
        return all(self.path(digest, s).exists() for s in SIZES)

    def _remember(self, digest: str, result: CoverResult) -> None:
        if len(self._done) >= _MEMO_LIMIT:
            self._done.clear()
        self._done[digest] = result

    def ingest(self, data: bytes) -> CoverResult:
        """Process one image in this thread; concurrent calls for the same image wait for
        the first one instead of rendering it again."""
        digest = hash_bytes(data)
        while True:
            with self._lock:
                if digest in self._done:
                    return self._done[digest]
                waiting = self._pending.get(digest)
                if waiting is None:
                    self._pending[digest] = threading.Event()
                    break
            waiting.wait()
        result = None
        try:
            result = render(str(self.root), data)
        finally:
            with self._lock:
                self._remember(digest, result)
                self._pending.pop(digest).set()
        return result

    def ingest_many(self, images: Iterable[bytes | None], mapper: Callable = map) -> list[CoverResult]:
        """Process a batch: each distinct new image is rendered once via `mapper`
        (e.g. a process pool's map), the rest is answered from memory."""
        images = list(images)
        digests = [hash_bytes(d) if d else None for d in images]
        known: dict[str, CoverResult] = {}
        todo: dict[str, bytes] = {}
        with self._lock:
            for digest, data in zip(digests, images, strict=True):
                if digest is None:
                    continue
                if digest in self._done:
                    known[digest] = self._done[digest]
                else:
                    todo.setdefault(digest, data)
        if todo:
            rendered = list(mapper(render, [str(self.root)] * len(todo), list(todo.values())))
            with self._lock:
                for digest, result in zip(todo, rendered, strict=True):
                    self._remember(digest, result)
                    known[digest] = result
        return [known[d] if d else None for d in digests]

    def jpeg_path(self, digest: str, size: int) -> Path:
        return self.root / digest[:2] / f"{digest}_{size}.jpg"

    def jpeg(self, digest: str, size: int) -> Path | None:
        """A JPEG copy of a thumbnail, for clients that cannot show WebP (some Subsonic apps).
        Made from the WebP thumbnail on first request and kept next to it."""
        target = self.jpeg_path(digest, size)
        if target.is_file():
            return target
        source = self.path(digest, size)
        try:
            with Image.open(source) as img:
                rgb = img.convert("RGB")  # JPEG has no alpha
            fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    rgb.save(f, "JPEG", quality=_JPEG_QUALITY)
                os.replace(tmp, target)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except (OSError, ValueError, SyntaxError):
            return None
        return target

    def delete(self, digest: str) -> None:
        with self._lock:
            self._done.pop(digest, None)
        for size in SIZES:
            self.path(digest, size).unlink(missing_ok=True)
            self.jpeg_path(digest, size).unlink(missing_ok=True)
