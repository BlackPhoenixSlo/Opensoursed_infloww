"""Signed OF calls ride the client's ManagedSession, bounded per account.

Real OFClient + ManagedSession + a private Registry against a local fake OF:
the per-client SIGNED_SLOTS bound (handles and connections), one connection
for sequential calls, the idle sweep, the shutdown stop/drain, delta-only
cookie writes, the busy timeout, and retire-on-evict (signed refused with
OFSessionRetired at both of _signed_slot's checks, raw ok).

Run: venv/bin/python service/tests/test_of_signed_session_pool.py
"""
import _harness  # isolated test DB before any service import

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(key, None)
os.environ["OF_CALL_STATS_PATH"] = ""

LOCK = threading.Lock()
WIRE: list[tuple[str, str, int]] = []  # (path, Cookie header, client port)
HOLD = {"started": threading.Semaphore(0), "release": threading.Event()}
SLOTS = 8  # OFClient.SIGNED_SLOTS, spelled out so a reverted build fails on behaviour


class FakeOF(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        with LOCK:
            WIRE.append((path, self.headers.get("Cookie", ""), self.client_address[1]))
        body, extra = b"{}", []
        if path.startswith("/hash"):
            body = b"HASH"
        elif path == "/api2/v2/slow":
            time.sleep(0.02)
        elif path == "/api2/v2/hold":
            HOLD["started"].release()
            HOLD["release"].wait(5)  # bounded: a broken build fails, never hangs
        elif path == "/api2/v2/setcf":
            extra.append(("Set-Cookie", "__cf_bm=v2; Path=/"))
        self.send_response(200)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


SRV = ThreadingHTTPServer(("127.0.0.1", 0), FakeOF)
SRV.daemon_threads = True
threading.Thread(target=SRV.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{SRV.server_port}"
os.environ["OF_API_ORIGIN"] = URL  # x-hash warm-up hits the fake too

import client_pool  # noqa: E402
import of_write  # noqa: E402
from curl_cffi.requests.exceptions import SessionClosed  # noqa: E402
from of_client import OFClient, OFSessionRetired, OFSignedPoolBusy  # noqa: E402
from of_managed_session import Unsupported  # noqa: E402
from of_session_registry import Registry  # noqa: E402


def reset():
    with LOCK:
        WIRE.clear()
    HOLD["started"] = threading.Semaphore(0)
    HOLD["release"] = threading.Event()


def make_client(reg, cookies=()):
    """A real OFClient whose ManagedSession registers with `reg`."""
    with patch.object(Registry, "_instance", reg):
        return OFClient(dict(
            headers=dict(user_id="101", x_bc="local", x_of_rev="local", user_agent="local"),
            signing=dict(signed_ok_at=1, rules=dict(
                static_param="local", start="a", end="b",
                checksum_indexes=[0], checksum_constant=1)),
            cookies=list(cookies),
        ))


def wait_holds(n):
    for _ in range(n):
        assert HOLD["started"].acquire(timeout=5), "hold call never reached fake OF"


def hits(path):
    with LOCK:
        return [w for w in WIRE if w[0] == path]


def case_concurrent_signed_calls_bounded_then_swept():
    reset()
    reg = Registry(age=30, interval=0.05)
    c = make_client(reg)  # cold: the x-hash warm-up races too
    errors = []

    def worker(_):
        for _ in range(8):
            try:
                assert c.get(URL + "/api2/v2/slow").status_code == 200
            except BaseException as e:  # noqa: BLE001
                errors.append(repr(e))

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(16)))
        assert not errors, errors[:3]  # no Unsupported("reentrant request"), no busy
        assert len(hits("/api2/v2/slow")) == 128
        peers = {w[2] for w in WIRE}
        slots = len(c.http._slots)
        print(f"  16x8 signed: slots={slots} connections={len(peers)} x-hash={len(hits('/hash/'))}")
        assert slots <= SLOTS, slots
        assert len(peers) <= SLOTS, len(peers)
        assert slots >= 2, "concurrent calls really used several handles"
        reg.age = 0.2  # the sweep: every idle handle closes, its record stays EMPTY
        until = time.monotonic() + 5
        while any(s.curl is not None for s in c.http._slots) and time.monotonic() < until:
            time.sleep(0.05)
        assert all(s.curl is None and s.state == "EMPTY" for s in c.http._slots), \
            [(s.state, bool(s.curl)) for s in c.http._slots]
        assert c.get(URL + "/api2/v2/slow").status_code == 200  # a swept client still calls
    finally:
        reg.drain()


def case_sequential_signed_calls_reuse_one_connection():
    reset()
    reg = Registry()
    c = make_client(reg)
    try:
        for _ in range(20):
            assert c.get(URL + "/api2/v2/slow").status_code == 200
        peers = {w[2] for w in WIRE}  # x-hash warm-up + 20 signed GETs
        print(f"  20 sequential signed: connections={len(peers)} slots={len(c.http._slots)}")
        assert len(peers) == 1, peers
        assert len(c.http._slots) == 1, len(c.http._slots)
    finally:
        reg.drain()


def case_shutdown_refuses_signed_and_drain_waits_for_one():
    reset()
    reg = Registry()
    c = make_client(reg)
    done = []
    held = threading.Thread(target=lambda: done.append(c.get(URL + "/api2/v2/hold").status_code))
    drainer = threading.Thread(target=reg.drain)
    try:
        assert c.get(URL + "/api2/v2/slow").status_code == 200
        held.start()
        wait_holds(1)
        reg.stop_admission()  # server.py shutdown, after the business drains
        sent = len(WIRE)
        t0 = time.monotonic()
        try:
            c.get(URL + "/api2/v2/slow")
        except Unsupported:
            pass
        else:
            raise AssertionError("signed GET admitted after stop_admission")
        assert time.monotonic() - t0 < 0.3 and len(WIRE) == sent, "refusal retried or sent"
        drainer.start()
        drainer.join(0.3)
        assert drainer.is_alive(), "drain returned with a signed call in flight"
        HOLD["release"].set()
        drainer.join(5)
        held.join(5)
        assert not drainer.is_alive() and done == [200], done
        try:
            c.get(URL + "/api2/v2/slow")
        except (SessionClosed, Unsupported):
            pass
        else:
            raise AssertionError("signed GET admitted after drain")
    finally:
        HOLD["release"].set()
        held.join(5)
        if drainer.ident:
            drainer.join(5)
        else:
            reg.drain()


def case_inflight_signed_call_keeps_newer_cf_cookie():
    reset()
    reg = Registry()
    c = make_client(reg, cookies=[dict(name="__cf_bm", value="v1", domain="127.0.0.1", path="/")])
    slow = []
    held = threading.Thread(target=lambda: slow.append(c.get(URL + "/api2/v2/hold").status_code))
    try:
        assert c.get(URL + "/api2/v2/slow").status_code == 200
        held.start()
        wait_holds(1)
        assert "__cf_bm=v1" in hits("/api2/v2/hold")[0][1]
        assert c.get(URL + "/api2/v2/setcf").status_code == 200
        assert c.http.cookies.get("__cf_bm") == "v2"
        HOLD["release"].set()  # the call that went out with v1 finishes after v2 landed
        held.join(5)
        assert slow == [200], slow
        jar = c.http.cookies.get("__cf_bm")
        c.get(URL + "/api2/v2/slow")
        sent = hits("/api2/v2/slow")[-1][1]
        print(f"  after in-flight v1 call: jar={jar} next request Cookie={sent!r}")
        assert jar == "v2" and "__cf_bm=v2" in sent, (jar, sent)
    finally:
        HOLD["release"].set()
        held.join(5)
        reg.drain()


def case_busy_when_every_slot_held():
    reset()
    reg = Registry()
    c = make_client(reg)
    c.SIGNED_WAIT_S = 0.1
    results = []
    holders = [threading.Thread(target=lambda: results.append(c.get(URL + "/api2/v2/hold").status_code))
               for _ in range(SLOTS)]
    try:
        assert c.get(URL + "/api2/v2/slow").status_code == 200
        for t in holders:
            t.start()
        wait_holds(SLOTS)
        sent = len(WIRE)
        t0 = time.monotonic()
        try:
            c.get(URL + "/api2/v2/slow")
        except OFSignedPoolBusy as e:
            assert not of_write._may_have_sent(e)
        else:
            raise AssertionError("9th signed call admitted past SIGNED_SLOTS")
        waited = time.monotonic() - t0
        assert 0.09 <= waited < 1 and len(WIRE) == sent, (waited, len(WIRE) - sent)
        HOLD["release"].set()
        for t in holders:
            t.join(5)
        assert results == [200] * SLOTS, results
        assert c.get(URL + "/api2/v2/slow").status_code == 200  # no slot leaked by the refusal
    finally:
        HOLD["release"].set()
        for t in holders:
            if t.ident:
                t.join(5)
        reg.drain()


def case_evicted_client_refuses_signed_keeps_raw():
    reset()
    reg = Registry()
    a, b = make_client(reg), make_client(reg)
    saved = dict(client_pool._POOL)
    inflight = []
    held = threading.Thread(target=lambda: inflight.append(a.get(URL + "/api2/v2/hold").status_code))
    try:
        assert a.get(URL + "/api2/v2/slow").status_code == 200
        assert b.get(URL + "/api2/v2/slow").status_code == 200
        client_pool._POOL.clear()
        client_pool._POOL.update({"a": a, "b": b})
        held.start()
        wait_holds(1)
        client_pool.evict("a")
        try:
            a.get(URL + "/api2/v2/slow")
        except OFSessionRetired as e:  # server._proxy re-runs a GET on it
            assert "retired" in str(e), e
        else:
            raise AssertionError("evicted client admitted a signed call")
        assert a.http.get(URL + "/raw").status_code == 200  # raw media calls keep working
        HOLD["release"].set()
        held.join(5)
        assert inflight == [200], inflight  # in flight at evict: finishes
        assert b.get(URL + "/api2/v2/slow").status_code == 200  # other account untouched
        client_pool.evict()
        try:
            b.get(URL + "/api2/v2/slow")
        except OFSessionRetired as e:  # server._proxy re-runs a GET on it
            assert "retired" in str(e), e
        else:
            raise AssertionError("evict() left a client admitting signed calls")
    finally:
        HOLD["release"].set()
        held.join(5)
        client_pool._POOL.clear()
        client_pool._POOL.update(saved)
        reg.drain()


def case_evict_refuses_a_slot_waiter_at_once():
    """Codex review: with every slot held, evict must refuse a waiter now, not after SIGNED_WAIT_S."""
    reset()
    reg = Registry()
    c = make_client(reg)
    c.SIGNED_WAIT_S = 30
    holders = [threading.Thread(target=lambda: c.get(URL + "/api2/v2/hold")) for _ in range(SLOTS)]
    out = {}

    def waiter():
        t0 = time.monotonic()
        try:
            c.get(URL + "/api2/v2/slow")
            out["err"] = None
        except OFSessionRetired as e:
            out["err"] = str(e)
        out["s"] = time.monotonic() - t0

    w = threading.Thread(target=waiter)
    try:
        assert c.get(URL + "/api2/v2/slow").status_code == 200
        for t in holders:
            t.start()
        wait_holds(SLOTS)
        w.start()
        time.sleep(0.3)
        c.close_signed_sessions()
        w.join(5)
        assert out.get("err") and "retired" in out["err"] and out["s"] < 1.5, out
    finally:
        HOLD["release"].set()
        for t in holders + [w]:
            if t.ident:
                t.join(5)
        reg.drain()


def case_evict_between_acquire_and_send_refuses():
    """An evict landing after the slot is taken: OFSessionRetired, and nothing sent."""
    reset()
    reg = Registry()
    c = make_client(reg)

    class _EvictedOnAcquire:
        def acquire(self, timeout=None):
            c.close_signed_sessions()
            return True

        def release(self):
            pass

    c._signed_slots = _EvictedOnAcquire()
    try:
        c.get(URL + "/api2/v2/slow")
    except OFSessionRetired as e:
        assert "retired" in str(e), e
    else:
        raise AssertionError("a client retired after acquire sent its signed call")
    finally:
        reg.drain()
    assert not hits("/api2/v2/slow"), hits("/api2/v2/slow")


if __name__ == "__main__":
    try:
        _harness.run()
    finally:
        SRV.shutdown()
        SRV.server_close()
