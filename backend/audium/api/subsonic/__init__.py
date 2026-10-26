"""Subsonic / OpenSubsonic API under /rest for third-party apps (plan: docs/subsonic.md).

Another set of routers over the same services as /api/v1; no domain logic here.
"""

# Importing the endpoint modules registers their handlers.
from audium.api.subsonic import (  # noqa: F401
    annotation,
    browsing,
    lists,
    media,
    playlists,
    queue,
    search,
    system,
    unsupported,
)
from audium.api.subsonic.routing import make_router

__all__ = ["make_router"]
