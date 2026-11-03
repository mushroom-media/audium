"""Process supervisor: one container runs the API and the workers as separate processes.

Restarts a crashed child with exponential backoff and forwards SIGTERM so every process can
finish its current batch (Docker gives 10 s before SIGKILL by default).

With a startup page (audium.startup) the API process gets the listening socket and goes first:
the workers start once it serves (at the latest after _WORKER_GRACE_S), so that their imports
(TensorFlow in the analysis worker) and first jobs do not slow down the API on a small server.
"""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from audium.logging import get_logger
from audium.startup import LISTEN_FD_ENV, READY_FD_ENV, StartupPage

log = get_logger(__name__)

_MAX_BACKOFF_S = 30.0
_STABLE_AFTER_S = 60.0
_SHUTDOWN_TIMEOUT_S = 8.0
_WORKER_GRACE_S = 30.0


@dataclass
class Child:
    name: str
    argv: list[str]
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    backoff: float = 1.0
    restart_at: float = 0.0
    restarts: int = field(default=0)
    serves_http: bool = False
    started_once: bool = False


class Supervisor:
    def __init__(self, children: list[tuple[str, list[str]]], startup: StartupPage | None = None) -> None:
        self.children = [Child(name, argv, serves_http=name == "api") for name, argv in children]
        self.startup = startup
        self.stopping = False

    def _start(self, child: Child) -> None:
        if child.serves_http and self.startup is not None:
            ready_r, ready_w = os.pipe()
            listen_fd = self.startup.fileno()
            env = {**os.environ, LISTEN_FD_ENV: str(listen_fd), READY_FD_ENV: str(ready_w)}
            try:
                child.proc = subprocess.Popen(child.argv, env=env, pass_fds=(listen_fd, ready_w))
            except BaseException:
                os.close(ready_r)
                raise
            finally:
                os.close(ready_w)
            self.startup.expect(ready_r)
        else:
            child.proc = subprocess.Popen(child.argv)
        child.started_at = time.monotonic()
        child.started_once = True
        log.info("supervisor.started_child", child=child.name, pid=child.proc.pid)

    def _workers_may_start(self, began: float) -> bool:
        if self.startup is None or self.startup.api_ready:
            return True
        return time.monotonic() - began >= _WORKER_GRACE_S

    def _on_signal(self, signum, _frame) -> None:
        if not self.stopping:
            log.info("supervisor.stopping", signal=signum)
        self.stopping = True

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        began = time.monotonic()
        while not self.stopping:
            now = time.monotonic()
            workers_may_start = self._workers_may_start(began)
            for child in self.children:
                if child.proc is None:
                    if not (child.started_once or child.serves_http or workers_may_start):
                        continue
                    if now >= child.restart_at:
                        self._start(child)
                    continue
                code = child.proc.poll()
                if code is None:
                    if now - child.started_at > _STABLE_AFTER_S:
                        child.backoff = 1.0
                    continue
                child.restarts += 1
                if child.serves_http and self.startup is not None:
                    self.startup.api_down()
                log.error("supervisor.child_exited", child=child.name, code=code, restart_in=child.backoff)
                child.proc = None
                child.restart_at = now + child.backoff
                child.backoff = min(child.backoff * 2, _MAX_BACKOFF_S)
            time.sleep(0.2)
        return self._shutdown()

    def _shutdown(self) -> int:
        running = [c for c in self.children if c.proc and c.proc.poll() is None]
        for c in running:
            c.proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT_S
        for c in running:
            try:
                c.proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                log.warning("supervisor.kill", child=c.name)
                c.proc.kill()
        if self.startup is not None:
            self.startup.close()
        log.info("supervisor.stopped")
        return 0


def default_children() -> list[tuple[str, list[str]]]:
    py = [sys.executable, "-m", "audium"]
    return [
        ("api", [*py, "api"]),
        ("worker-scan", [*py, "worker", "--queue", "scan"]),
        ("worker-analysis", [*py, "worker", "--queue", "analysis"]),
    ]
