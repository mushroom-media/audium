"""One cover per genre and style playlist, made once and kept.

The image is a blurred collage of the first album covers in the playlist (one cover blurred if
there are fewer than four, a plain colour without any) under a diagonal gradient in its own main
colour. It goes into the cover store like any other cover and is remembered by playlist key in
auto_playlist_covers, so it stays the same when the playlist's tracks change from run to run.
A new one is made only when there is none yet or its files are gone.

Discover, the start page, the playlist page and Subsonic's coverArt all show it, because it is
the playlist's `cover_hash`.
"""

import colorsys
import io
import zlib
from collections.abc import Iterable

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from sqlalchemy import Connection, select, update

from audium.db.dialect import insert_for
from audium.db.engine import Database
from audium.db.schema import auto_playlist_covers, auto_playlist_items, auto_playlists, covers, tracks
from audium.logging import get_logger
from audium.scanner.covers import CoverStore, dominant_color
from audium.util import now_ms

log = get_logger(__name__)

# Playlists of one musical direction: broad genre, genre, genre x decade, detected style.
PREFIXES = ("family:", "genre:", "genre-decade:", "style:")
SIZE = 600
_TILES = 4  # covers in the collage (2x2)
_SCAN_ITEMS = 60  # items looked at to find that many distinct covers
_BLUR_AT = 160  # the collage is blurred this small and scaled up: soft and cheap
_BLUR_RADIUS = 18
_GRADIENT_ALPHA = 0.5


def is_genre_key(key: str) -> bool:
    return key.startswith(PREFIXES)


def stored(conn: Connection, key: str) -> str | None:
    return conn.execute(select(auto_playlist_covers.c.hash).where(auto_playlist_covers.c.key == key)).scalar()


def _key_hue(key: str) -> float:
    return (zlib.crc32(key.encode()) % 360) / 360


def _hex_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _hls(h: float, lightness: float, s: float) -> np.ndarray:
    return np.array(colorsys.hls_to_rgb(h % 1, lightness, s)) * 255


def _collage(images: list[Image.Image]) -> Image.Image:
    if len(images) >= _TILES:
        half = SIZE // 2
        canvas = Image.new("RGB", (SIZE, SIZE))
        for i, img in enumerate(images[:_TILES]):
            canvas.paste(img.resize((half, half), Image.Resampling.BILINEAR), ((i % 2) * half, (i // 2) * half))
        return canvas
    return images[0].resize((SIZE, SIZE), Image.Resampling.BILINEAR)


def render(key: str, images: list[Image.Image]) -> bytes:
    """The cover as PNG bytes. `images`: album covers of the playlist, in playlist order."""
    images = [img.convert("RGB") for img in images]
    if images:
        small = _collage(images).resize((_BLUR_AT, _BLUR_AT), Image.Resampling.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(_BLUR_RADIUS))
        base = ImageEnhance.Color(small.resize((SIZE, SIZE), Image.Resampling.BICUBIC)).enhance(1.35)
        main = dominant_color(base)
    else:
        base, main = None, ""
    # The gradient runs from the main colour (or one of the key's own) to a darker, shifted hue.
    if main:
        h, _, _ = colorsys.rgb_to_hls(*(v / 255 for v in _hex_rgb(main)))
    else:
        h = _key_hue(key)
    start, end = _hls(h, 0.5, 0.6), _hls(h + 0.11, 0.22, 0.6)
    # Its direction comes from the key, so a genre and its broad genre differ even when they
    # start with the same albums.
    angle = 2 * np.pi * _key_hue(key)
    ramp = np.linspace(-1, 1, SIZE)
    t = ramp[None, :] * np.cos(angle) + ramp[:, None] * np.sin(angle)
    t = ((t - t.min()) / (t.max() - t.min()))[..., None]  # 0 .. 1 along the direction
    gradient = start * (1 - t) + end * t
    if base is None:
        pixels = gradient
    else:
        pixels = np.asarray(base, dtype=np.float64) * (1 - _GRADIENT_ALPHA) + gradient * _GRADIENT_ALPHA
    out = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def _sources(conn: Connection, playlist_id: int) -> list[str]:
    """The first distinct album covers among the playlist's tracks."""
    hashes: list[str] = []
    rows = conn.execute(
        select(covers.c.hash)
        .select_from(auto_playlist_items)
        .join(tracks, tracks.c.id == auto_playlist_items.c.track_id)
        .join(covers, covers.c.id == tracks.c.cover_id)
        .where(auto_playlist_items.c.auto_playlist_id == playlist_id)
        .order_by(auto_playlist_items.c.rank)
        .limit(_SCAN_ITEMS)
    ).scalars()
    for digest in rows:
        if digest not in hashes:
            hashes.append(digest)
            if len(hashes) == _TILES:
                break
    return hashes


def _todo(conn: Connection, store: CoverStore) -> list[tuple[str, list[str]]]:
    """Genre playlists without a usable cover yet: (key, album covers to make it from)."""
    rows = conn.execute(
        select(auto_playlists.c.id, auto_playlists.c.key, auto_playlist_covers.c.hash)
        .outerjoin(auto_playlist_covers, auto_playlist_covers.c.key == auto_playlists.c.key)
        .where(auto_playlists.c.status != "dismissed")
    ).all()
    return [
        (r.key, _sources(conn, r.id))
        for r in rows
        if is_genre_key(r.key) and (r.hash is None or not store.exists(r.hash))
    ]


def _make(store: CoverStore, todo: Iterable[tuple[str, list[str]]]) -> dict[str, str]:
    made = {}
    for key, sources in todo:
        images = []
        for digest in sources:
            try:
                with Image.open(store.path(digest, 256)) as img:
                    images.append(img.copy())
            except (OSError, ValueError, SyntaxError):
                continue  # a thumbnail that went missing: the collage does without it
        result = store.ingest(render(key, images))
        if result is not None:
            made[key] = result[0]
    return made


def _save(conn: Connection, made: dict[str, str]) -> None:
    ts = now_ms()
    for key, digest in made.items():
        stmt = insert_for(conn, auto_playlist_covers).values(key=key, hash=digest, created_at=ts)
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[auto_playlist_covers.c.key], set_={"hash": digest, "created_at": ts}
            )
        )


def _link(conn: Connection) -> None:
    """Every genre playlist shows its stored cover."""
    for key, digest in conn.execute(select(auto_playlist_covers.c.key, auto_playlist_covers.c.hash)):
        conn.execute(
            update(auto_playlists)
            .where(auto_playlists.c.key == key, auto_playlists.c.cover_hash.is_distinct_from(digest))
            .values(cover_hash=digest)
        )


def refresh(conn: Connection, store: CoverStore) -> int:
    """Make the missing covers and link them, in one transaction. Returns how many were made."""
    made = _make(store, _todo(conn, store))
    _save(conn, made)
    _link(conn)
    return len(made)


def refresh_in(db: Database, store: CoverStore) -> int:
    """Like refresh, but the images are made outside of any write transaction."""
    with db.read() as conn:
        todo = _todo(conn, store)
    made = _make(store, todo)
    with db.write() as conn:
        _save(conn, made)
        _link(conn)
    if made:
        log.info("genre_covers.made", count=len(made))
    return len(made)
