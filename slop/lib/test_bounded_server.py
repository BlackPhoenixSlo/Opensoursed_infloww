import threading
import time
from http.server import BaseHTTPRequestHandler

from slop.lib.bounded_server import BoundedHTTPServer, _Pool


def test_server_close_stops_workers():
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            pass

    names = []
    for _ in range(4):
        server = BoundedHTTPServer(("127.0.0.1", 0), Handler)
        server.pool.submit(lambda: None)
        names.extend(t.name for t in server.pool.threads)
        server.server_close()
    assert not any(t.name in names for t in threading.enumerate())


def test_pool_close_uses_one_deadline_for_busy_workers():
    pool = _Pool(5, "busy-pool")
    hold = threading.Event()
    ready = threading.Barrier(6)
    def work():
        ready.wait()
        hold.wait(3)
    for _ in range(5):
        pool.submit(work)
    ready.wait(timeout=2)
    start = time.monotonic()
    pool.close()
    took = time.monotonic() - start
    hold.set()
    for t in pool.threads:
        t.join(timeout=2)
    assert took < 1.5


def test_idle_close_s_closes_a_parked_keepalive_and_the_client_reconnects():
    import http.client

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    server = BoundedHTTPServer(("127.0.0.1", 0), Handler)
    server.idle_close_s = 0.3
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        c.request("GET", "/")
        assert c.getresponse().read() == b"ok"
        deadline = time.monotonic() + 3
        while server.idle_closed == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.idle_closed == 1
        c.close()
        c.request("GET", "/")  # a fresh connection still answers
        assert c.getresponse().read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()
