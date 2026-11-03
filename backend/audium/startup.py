"""Startup page: while the API process does not serve yet (migrations, imports, a restart after a
crash), the supervisor answers on the port itself with a small "audium is starting" page that
reloads once the API is up, instead of the browser showing a connection error.

The supervisor owns the listening socket and passes it to the API process (uvicorn serves on the
inherited fd), so the port is never closed. The API process reports through a pipe once it accepts
connections; from then on the placeholder stays out of the way until the API process exits.
"""

import json
import os
import select
import socket
import threading
import time

from audium.logging import get_logger

log = get_logger(__name__)

LISTEN_FD_ENV = "AUDIUM_LISTEN_FD"
READY_FD_ENV = "AUDIUM_READY_FD"
_RETRY_AFTER_S = 2


class StartupPage:
    def __init__(self, host: str, port: int, base_path: str) -> None:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.sock = socket.create_server((host, port), family=family, backlog=2048)
        # Shared with the API process, which (asyncio) makes it non-blocking anyway: a connection
        # the API took first must not leave accept() hanging here.
        self.sock.setblocking(False)
        self.base_path = base_path
        self.started_at = time.monotonic()
        self.api_ready = False
        self._ready_r: int | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._serve, name="startup-page", daemon=True)
        self._thread.start()

    def fileno(self) -> int:
        return self.sock.fileno()

    def expect(self, ready_r: int) -> None:
        """A new API process was started; it writes to the other end of this pipe once it serves."""
        with self._lock:
            self._close_ready()
            self._ready_r = ready_r
            self.api_ready = False

    def api_down(self) -> None:
        with self._lock:
            self._close_ready()
            self.api_ready = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._close_ready()
        self.sock.close()

    def _close_ready(self) -> None:
        if self._ready_r is not None:
            os.close(self._ready_r)
            self._ready_r = None

    def _serve(self) -> None:
        while not self._closed:
            if self.api_ready:
                time.sleep(0.2)
                continue
            with self._lock:
                ready_r = self._ready_r
            fds = [self.sock] if ready_r is None else [self.sock, ready_r]
            try:
                readable, _, _ = select.select(fds, [], [], 0.5)
                if ready_r is not None and ready_r in readable:
                    self._on_ready_pipe(ready_r)
                elif self.sock in readable:
                    self._answer_one()
            except (OSError, ValueError):  # fd closed meanwhile (api_down, close)
                continue

    def _on_ready_pipe(self, ready_r: int) -> None:
        data = os.read(ready_r, 1)
        with self._lock:
            if ready_r != self._ready_r:
                return
            self._close_ready()
            if data:  # empty: the process exited before serving; the supervisor restarts it
                self.api_ready = True
                log.info("startup.api_ready", seconds=round(time.monotonic() - self.started_at, 1))

    def _answer_one(self) -> None:
        try:
            conn, _addr = self.sock.accept()
        except BlockingIOError:
            return  # the API process took it
        with conn:
            conn.settimeout(2)
            try:
                path = _request_path(conn)
                conn.sendall(self._response(path))
            except OSError:
                pass

    def _response(self, path: str) -> bytes:
        rel = path.removeprefix(self.base_path)
        if rel.startswith(("/api/", "/rest/")):
            body = json.dumps({"error": {"code": "starting", "message": "audium is starting"}}).encode()
            ctype = "application/json"
        else:
            body = _PAGE.replace("__BASE__", json.dumps(self.base_path)).encode()
            ctype = "text/html; charset=utf-8"
        head = (
            "HTTP/1.1 503 Service Unavailable\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Retry-After: {_RETRY_AFTER_S}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n\r\n"
        )
        return head.encode() + body


def _request_path(conn: socket.socket) -> str:
    data = b""
    while b"\r\n" not in data and len(data) < 8192:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    parts = data.split(b"\r\n", 1)[0].split(b" ")
    return parts[1].decode("latin-1").split("?", 1)[0] if len(parts) >= 2 else "/"


_PAGE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>audium startet …</title>
<style>
  :root { --bg: #111214; --fg: #e8e3d9; --accent: #e9b872; }
  @media (prefers-color-scheme: light) {
    :root { --bg: #f6f4ef; --fg: #1d1c1a; --accent: #b06d10; }
  }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--fg);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    display: grid; place-items: center; text-align: center;
  }
  .bars { display: flex; gap: 7px; align-items: center; height: 56px; margin: 0 auto 20px; width: max-content; }
  .bars span {
    width: 8px; height: 100%; border-radius: 4px; background: var(--accent);
    animation: eq 1s ease-in-out infinite; transform-origin: center;
  }
  .bars span:nth-child(2) { animation-delay: -.25s; }
  .bars span:nth-child(3) { animation-delay: -.5s; }
  .bars span:nth-child(4) { animation-delay: -.75s; }
  @keyframes eq { 0%, 100% { transform: scaleY(.25); } 50% { transform: scaleY(1); } }
  @media (prefers-reduced-motion: reduce) { .bars span { animation-duration: 3s; } }
  h1 { font-size: 20px; font-weight: 600; margin: 0; }
</style>
</head>
<body>
<main>
  <div class="bars" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
  <h1>audium startet …</h1>
</main>
<script>
  const base = __BASE__;
  async function poll() {
    try {
      const res = await fetch(base + "/api/health", { cache: "no-store" });
      if (res.ok) { location.reload(); return; }
    } catch (e) {}
    setTimeout(poll, 1000);
  }
  setTimeout(poll, 1000);
</script>
</body>
</html>
"""
