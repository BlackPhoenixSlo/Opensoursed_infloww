"""Signed OF transport reuses a bounded number of live TCP connections across threads."""
import concurrent.futures
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curl_cffi import requests  # noqa: E402
import client_pool  # noqa: E402
from of_client import OFAPIError, OFClient, _SignedSessionPool  # noqa: E402


def case_signed_connections_reused_across_worker_threads():
    lock = threading.Lock()
    peers = set()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            assert "sess=fixture" in self.headers.get("Cookie", "")
            with lock:
                peers.add(self.client_address[1])
            time.sleep(0.03)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    client = OFClient.__new__(OFClient)
    client.http = requests.Session()
    client.http.cookies.set("sess", "fixture")
    client._signed_pool_lock = threading.Lock()
    client._signed_pool = None
    client._signed_retired = False
    url = f"http://127.0.0.1:{srv.server_port}/"
    try:
        def fetch(_):
            with client._signed_session() as session:
                return session.get(url, timeout=5).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as workers:
            assert list(workers.map(fetch, range(32))) == [200] * 32
        assert len(peers) <= _SignedSessionPool.SIZE, (len(peers), _SignedSessionPool.SIZE)
        assert len(peers) >= 2, peers  # concurrent calls really used multiple handles
    finally:
        if client._signed_pool is not None:
            client.close_signed_sessions()
        client.http.close()
        srv.shutdown()
        srv.server_close()


def case_fifo_timeout_and_retirement():
    source = requests.Session()
    pool = _SignedSessionPool(source)
    try:
        with pool.lease():
            raise RuntimeError("failed signed call")
    except RuntimeError:
        pass
    assert len(pool._available) == pool.SIZE
    leases = [pool.lease() for _ in range(pool.SIZE)]
    borrowed = [lease.__enter__() for lease in leases]
    seen = []
    reacquired = None

    def waiter(n):
        with pool.lease():
            seen.append(n)

    threads = []
    try:
        for n in (1, 2):
            thread = threading.Thread(target=waiter, args=(n,))
            thread.start()
            threads.append(thread)
            until = time.monotonic() + 2
            while time.monotonic() < until:
                with pool._ready:
                    if len(pool._waiters) == n:
                        break
                time.sleep(0.005)
            else:
                raise AssertionError("waiter did not queue")
        leases[0].__exit__(None, None, None)
        leases.pop(0)
        threads[0].join(2)
        threads[1].join(2)
        assert seen == [1, 2], seen

        reacquired = pool.lease()
        reacquired.__enter__()
        pool.WAIT_S = 0.02
        try:
            with pool.lease():
                raise AssertionError("all handles remain borrowed")
        except OFAPIError as exc:
            assert "busy" in str(exc)
        with pool._ready:
            assert not pool._waiters

        leases[0].__exit__(None, None, None)
        leases.pop(0)
        idle = list(pool._available)
        pool.close()
        assert len(idle) == 1 and idle[0]._closed
        assert not borrowed[2]._closed
        try:
            with pool.lease():
                raise AssertionError("retired pool admitted a call")
        except OFAPIError as exc:
            assert "retired" in str(exc)
    finally:
        for lease in leases:
            lease.__exit__(None, None, None)
        if reacquired is not None:
            reacquired.__exit__(None, None, None)
        for thread in threads:
            thread.join(2)
        pool.close()
        source.close()
    assert all(s._closed for s in borrowed)


def case_account_jars_and_evict_are_isolated():
    first = requests.Session()
    second = requests.Session()
    first.cookies.set("sess", "first")
    second.cookies.set("sess", "second")
    a = _SignedSessionPool(first)
    b = _SignedSessionPool(second)

    class Pooled:
        def __init__(self, pool):
            self.pool = pool

        def close_signed_sessions(self):
            self.pool.close()

    saved = dict(client_pool._POOL)
    try:
        client_pool._POOL.clear()
        client_pool._POOL.update({"a": Pooled(a), "b": Pooled(b)})
        with a.lease() as sa, b.lease() as sb:
            assert sa.cookies.jar is first.cookies.jar
            assert sb.cookies.jar is second.cookies.jar
            assert sa.cookies.jar is not sb.cookies.jar
            first.cookies.set("cf_clearance", "rotated")
            assert sa.cookies.get("cf_clearance") == "rotated"
            assert sb.cookies.get("cf_clearance") is None
        client_pool.evict("a")
        assert a._closed and not b._closed
        with b.lease() as sb:
            assert sb.cookies.get("sess") == "second"
        client_pool.evict()
        assert b._closed
    finally:
        a.close()
        b.close()
        first.close()
        second.close()
        client_pool._POOL.clear()
        client_pool._POOL.update(saved)


def case_retired_client_cannot_lazily_open_new_handles():
    client = OFClient.__new__(OFClient)
    client.http = requests.Session()
    client._signed_pool_lock = threading.Lock()
    client._signed_pool = None
    client._signed_retired = False
    try:
        client.close_signed_sessions()
        try:
            with client._signed_session():
                raise AssertionError("retired client admitted a call")
        except OFAPIError as exc:
            assert "retired" in str(exc)
        assert client._signed_pool is None
    finally:
        client.http.close()


if __name__ == "__main__":
    case_signed_connections_reused_across_worker_threads()
    case_fifo_timeout_and_retirement()
    case_account_jars_and_evict_are_isolated()
    case_retired_client_cannot_lazily_open_new_handles()
    print("signed session pool: live connection bound passed")
