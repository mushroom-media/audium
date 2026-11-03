import json
import os
import socket
import time
import urllib.error
import urllib.request

import pytest

from audium.startup import StartupPage


@pytest.fixture
def page():
    p = StartupPage("127.0.0.1", 0, "/audium")
    yield p
    p.close()


def _get(page: StartupPage, path: str) -> urllib.error.HTTPError:
    port = page.sock.getsockname()[1]
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)  # noqa: S310
    return exc.value


def _wait_for(cond) -> None:
    deadline = time.monotonic() + 3
    while not cond():
        assert time.monotonic() < deadline
        time.sleep(0.02)


def test_page_while_starting(page):
    err = _get(page, "/audium/library?x=1")
    assert err.code == 503
    assert err.headers["Retry-After"] == "2"
    body = err.read().decode()
    assert "audium startet" in body
    assert 'const base = "/audium";' in body


def test_api_paths_get_json(page):
    err = _get(page, "/audium/api/health")
    assert err.code == 503
    assert json.loads(err.read())["error"]["code"] == "starting"


def test_steps_aside_once_the_api_serves(page):
    ready_r, ready_w = os.pipe()
    page.expect(ready_r)
    os.write(ready_w, b"1")
    os.close(ready_w)
    _wait_for(lambda: page.api_ready)
    # Connections now wait for the API process instead of getting the placeholder.
    port = page.sock.getsockname()[1]
    with socket.create_connection(("127.0.0.1", port), timeout=1) as conn:
        conn.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        with pytest.raises(TimeoutError):
            conn.recv(1)
    page.api_down()
    assert not page.api_ready
    assert _get(page, "/").code == 503


def test_api_exit_before_serving_keeps_the_page(page):
    ready_r, ready_w = os.pipe()
    page.expect(ready_r)
    os.close(ready_w)  # EOF without the ready byte
    time.sleep(0.3)
    assert not page.api_ready
    assert _get(page, "/").code == 503
