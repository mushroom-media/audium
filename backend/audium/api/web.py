"""Serves the built single-page app (frontend/dist) from the same container as the API."""

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

_IMMUTABLE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-cache"

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>audium</title>
<body style="font-family:system-ui;padding:2rem;background:#111;color:#ddd">
<h1>audium</h1><p>The web interface is not built. The API is available at
<a style="color:#8cf" href="api/docs">api/docs</a>.</p></body>"""


def _index_html(web_dir: str, base_path: str) -> str | None:
    index = Path(web_dir) / "index.html"
    try:
        st = index.stat()
    except OSError:
        return None
    # Keyed by mtime/size: a rebuilt frontend is picked up without a restart.
    return _render_index(str(index), st.st_mtime_ns, st.st_size, base_path)


@lru_cache(maxsize=4)
def _render_index(index: str, _mtime_ns: int, _size: int, base_path: str) -> str:
    html = Path(index).read_text(encoding="utf-8")
    # Assets are referenced relatively; <base> makes them resolve from the app root even on
    # deep links like /albums/12, under any sub-path. The config is read by the app at startup.
    config = json.dumps({"basePath": base_path}).replace("<", "\\u003c")
    head = f'<base href="{base_path}/"><script>window.__AUDIUM__={config}</script>'
    return html.replace("<head>", "<head>" + head, 1)


def make_router(web_dir: Path, base_path: str) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    root = os.path.realpath(web_dir)

    @router.get("/{path:path}")
    def spa(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "unknown API path"}}, status_code=404)
        if path:
            candidate = os.path.realpath(os.path.join(root, path))
            if os.path.commonpath([root, candidate]) == root and os.path.isfile(candidate):
                cache = _IMMUTABLE if path.startswith("assets/") else _NO_CACHE
                return FileResponse(candidate, headers={"Cache-Control": cache})
            if path.startswith("assets/"):
                return Response(status_code=404)  # a stale asset hash must not get index.html
        html = _index_html(root, base_path)
        if html is None:
            return HTMLResponse(_NOT_BUILT)
        return HTMLResponse(html, headers={"Cache-Control": _NO_CACHE})

    return router
