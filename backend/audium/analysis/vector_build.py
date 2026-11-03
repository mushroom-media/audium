"""Builds the vector files of analysis/similarity.py in a process of its own, so that the API keeps
answering meanwhile: `python -m audium.analysis.vector_build <directory> <features|embeddings>...`.
Started by the API (VectorIndex); the database URL comes in the environment."""

import ctypes
import os
import signal
import sys
from pathlib import Path

from audium.analysis.similarity import VECTOR_DB_ENV, build_files
from audium.db.engine import Database

_PR_SET_PDEATHSIG = 1


def _die_with_parent() -> None:
    """An API that is killed gets restarted and starts its own build: this one must not stay behind."""
    if sys.platform == "linux":
        ctypes.CDLL(None).prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)


def main(argv: list[str]) -> None:
    _die_with_parent()
    # Background work must never compete with playback or the UI.
    if hasattr(os, "nice"):
        os.nice(19)
    db = Database(os.environ[VECTOR_DB_ENV])
    try:
        build_files(db, Path(argv[0]), argv[1:])
    finally:
        db.dispose()


if __name__ == "__main__":
    main(sys.argv[1:])
