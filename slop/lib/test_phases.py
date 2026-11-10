import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from slop.lib import stack


class _Ready(BaseHTTPRequestHandler):
    codes: list[int] = []
    delay = 0.0  # seconds before answering

    def do_GET(self):  # noqa: N802
        time.sleep(self.delay)
        self.send_response(self.codes.pop(0) if len(self.codes) > 1 else self.codes[0])
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_a):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Ready)
    srv.daemon_threads = True  # a delayed answer must not hold shutdown
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _bare_stack(tmp_path):
    """A Stack for its readiness wait only (no relay, no temp dirs)."""
    s = object.__new__(stack.Stack)
    s._lock, s.logdir, s.waits = None, tmp_path, []
    return s


@pytest.mark.parametrize("codes,polls", [([200], 1), ([503, 404], 2)])  # no sleep = 1 poll; one 5xx = one sleep
def test_readiness_wait_records_seconds_and_polls(server, tmp_path, codes, polls):
    _Ready.codes = list(codes)
    s = _bare_stack(tmp_path)
    s.wait_ready("relay", f"http://127.0.0.1:{server.server_port}/livez", 10, SimpleNamespace(poll=lambda: None))
    (w,) = s.waits
    assert (w["name"], w["polls"]) == ("relay", polls) and 0.1 * (polls - 1) <= w["seconds"] < polls + 1


def test_second_poll_comes_well_under_a_second(server, tmp_path):
    _Ready.codes = [503, 503, 200]  # 5xx = not ready yet; the 3rd answer is ready
    s = _bare_stack(tmp_path)
    s.wait_ready("relay", f"http://127.0.0.1:{server.server_port}/livez", 10, SimpleNamespace(poll=lambda: None))
    (w,) = s.waits
    assert w["polls"] == 3 and w["seconds"] < 1.0  # was >= 2 s with a fixed 1 s poll


def test_a_slow_request_does_not_overrun_the_budget(server, tmp_path, monkeypatch):
    _Ready.codes = [200]
    monkeypatch.setattr(_Ready, "delay", 5)
    s = _bare_stack(tmp_path)
    t0 = time.monotonic()
    with pytest.raises(SystemExit, match="not ready .* after 1s"):
        s.wait_ready("relay", f"http://127.0.0.1:{server.server_port}/livez", 1, SimpleNamespace(poll=lambda: None))
    assert time.monotonic() - t0 < 2  # the request timeout is capped at what is left of the 1 s budget
    assert s.waits[0]["polls"] == 1


def test_failed_readiness_wait_is_recorded_too(tmp_path):
    s = _bare_stack(tmp_path)
    with pytest.raises(SystemExit, match="exited during startup"):
        s.wait_ready("next dev", "http://127.0.0.1:9/login", 10, SimpleNamespace(poll=lambda: 1))
    assert s.waits == [{"name": "next dev", "seconds": s.waits[0]["seconds"], "polls": 0}]
