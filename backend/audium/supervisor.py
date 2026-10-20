"""Process supervisor: one container runs the API and the workers as separate processes.

Restarts a crashed child with exponential backoff and forwards SIGTERM so every process can
finish its current batch (Docker gives 10 s before SIGKILL by default).
"""

import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field

from audium.logging import get_logger

log = get_logger(__name__)

_MAX_BACKOFF_S = 30.0
_STABLE_AFTER_S = 60.0
_SHUTDOWN_TIMEOUT_S = 8.0


@dataclass
class Child:
    name: str
    argv: list[str]
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    backoff: float = 1.0
    restart_at: float = 0.0
    restarts: int = field(default=0)


class Supervisor:
    def __init__(self, children: list[tuple[str, list[str]]]) -> None:
        self.children = [Child(name, argv) for name, argv in children]
        self.stopping = False

    def _start(self, child: Child) -> None:
        child.proc = subprocess.Popen(child.argv)
        child.started_at = time.monotonic()
        log.info("supervisor.started_child", child=child.name, pid=child.proc.pid)

    def _on_signal(self, signum, _frame) -> None:
        if not self.stopping:
            log.info("supervisor.stopping", signal=signum)
        self.stopping = True

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        for child in self.children:
            self._start(child)
        while not self.stopping:
            now = time.monotonic()
            for child in self.children:
                if child.proc is None:
                    if now >= child.restart_at:
                        self._start(child)
                    continue
                code = child.proc.poll()
                if code is None:
                    if now - child.started_at > _STABLE_AFTER_S:
                        child.backoff = 1.0
                    continue
                child.restarts += 1
                log.error("supervisor.child_exited", child=child.name, code=code, restart_in=child.backoff)
                child.proc = None
                child.restart_at = now + child.backoff
                child.backoff = min(child.backoff * 2, _MAX_BACKOFF_S)
            time.sleep(0.5)
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
        log.info("supervisor.stopped")
        return 0


def default_children() -> list[tuple[str, list[str]]]:
    py = [sys.executable, "-m", "audium"]
    return [
        ("api", [*py, "api"]),
        ("worker-scan", [*py, "worker", "--queue", "scan"]),
    ]
