"""ASGI middleware that makes the frequent cheap requests cheaper (pure ASGI, see main.CsrfGuard)."""

import os
import re
import time

from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse

from audium.api.deps import SESSION_COOKIE
from audium.api.library import COVER_CACHE
from audium.config import Settings
from audium.db.engine import Database
from audium.scanner.covers import SIZES, CoverStore
from audium.services import auth as auth_service

_SESSION_KNOWN_S = 30
_MAX_SESSIONS = 1024
_COVER_PATH = re.compile(r"/api/v1/covers/([0-9a-f]{32})/(\d+)")
_COMPRESSED = re.compile(r"/(assets|api/v1)/")
# Audio is compressed already and needs its byte ranges, covers too; events must not be held back.
_NOT_COMPRESSED = re.compile(r"(/stream|/events|/covers/.*)$")
_GZIP_MIN_BYTES = 1024
_GZIP_LEVEL = 4


class Compress:
    """Gzip for the JSON of the API and the built app, nothing else."""

    def __init__(self, app) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=_GZIP_MIN_BYTES, compresslevel=_GZIP_LEVEL)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and _COMPRESSED.search(path) and not _NOT_COMPRESSED.search(path):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


class CoverShortcut:
    """The covers of a page are dozens of requests at once. Routing and dependencies cost more than
    the file, and every request would look up its session, in the queue with all other database
    reads. So a browser session that was valid a moment ago gets the file straight away. Everything
    else (a first request, app tokens, unknown covers) goes the normal way through api/library.py.
    A logged-out session can see covers for _SESSION_KNOWN_S more; they are not secret enough to
    look that up every time."""

    def __init__(self, app, settings: Settings, db: Database) -> None:
        self.app = app
        self.db = db
        self.store = CoverStore(settings.covers_dir)
        self.base_path = settings.base_path
        self.known: dict[str, float] = {}

    def _session_ok(self, token: str) -> bool:
        with self.db.read() as conn:
            return auth_service.resolve_session(conn, token) is not None

    async def _known(self, token: str) -> bool:
        now = time.monotonic()
        if self.known.get(token, 0) > now:
            return True
        if not await run_in_threadpool(self._session_ok, token):
            return False
        if len(self.known) >= _MAX_SESSIONS:
            self.known.clear()
        self.known[token] = now + _SESSION_KNOWN_S
        return True

    async def __call__(self, scope, receive, send):
        match = _COVER_PATH.fullmatch(scope["path"].removeprefix(self.base_path)) if scope["type"] == "http" else None
        if match and int(match[2]) in SIZES and scope["method"] == "GET":
            token = Request(scope).cookies.get(SESSION_COOKIE)
            if token and await self._known(token):
                path = self.store.path(match[1], int(match[2]))
                try:
                    stat = await run_in_threadpool(os.stat, path)
                except OSError:
                    stat = None  # the normal way tells the error
                if stat is not None:
                    headers = {"Cache-Control": COVER_CACHE, "ETag": f'"{match[1]}-{match[2]}"'}
                    response = FileResponse(path, stat_result=stat, media_type="image/webp", headers=headers)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
