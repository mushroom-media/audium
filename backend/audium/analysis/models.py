"""Pre-trained Essentia models, downloaded into /data/models on first use.

The models are licensed CC BY-NC-SA 4.0 (non-commercial), so audium does not ship them. The
download sends no user data, only the file requests. Files are checked against fixed SHA-256
sums; put them into the models folder by hand to avoid the download
(AUDIUM_ANALYSIS_DOWNLOAD_MODELS=false).
"""

import hashlib
import os
import urllib.request
from pathlib import Path

from audium.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://essentia.upf.edu/models/"
EFFNET = "discogs-effnet-bs64-1.pb"
STYLE_HEAD = "genre_discogs400-discogs-effnet-1.pb"
STYLE_LABELS = "genre_discogs400-discogs-effnet-1.json"
# file -> (path below BASE_URL, sha256)
FILES = {
    EFFNET: (
        "feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb",
        "3ed9af50d5367c0b9c795b294b00e7599e4943244f4cbd376869f3bfc87721b1",
    ),
    STYLE_HEAD: (
        "classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1.pb",
        "3885ba078a35249af94b8e5e4247689afac40deca4401a4bc888daf5a579c01c",
    ),
    STYLE_LABELS: (
        "classification-heads/genre_discogs400/genre_discogs400-discogs-effnet-1.json",
        "2d367319d9b782ffa10f69abf0e805b3ac4e10899025e5bdbaceda3919b243e0",
    ),
}
_TIMEOUT_S = 60


def present(models_dir: Path) -> bool:
    return all((models_dir / name).is_file() for name in FILES)


def ensure(models_dir: Path, download: bool) -> bool:
    """True if all model files are there, downloading missing ones if allowed. Never raises."""
    if present(models_dir):
        return True
    if not download:
        return False
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        for name, (path, sha256) in FILES.items():
            if not (models_dir / name).is_file():
                _download(BASE_URL + path, models_dir / name, sha256)
    except Exception as exc:
        log.warning("models.download_failed", error=f"{type(exc).__name__}: {exc}")
        return False
    return True


def _download(url: str, target: Path, sha256: str) -> None:
    log.info("models.download", url=url)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as resp, part.open("wb") as out:  # noqa: S310
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise ValueError(f"checksum mismatch for {target.name}")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
