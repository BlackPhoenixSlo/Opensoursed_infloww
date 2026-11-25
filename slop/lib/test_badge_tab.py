from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from slop.actors.badge_tab import BadgeTab, classify, open_ts
from slop.lib.client import Http, Recorder

A, B = "101", "202"


class Relay:

    def __init__(self) -> None:
        self.accounts: dict[str, dict] = {}
        self.gets: list[str] = []
        self.leases: list[dict] = []
        self.lines: queue.Queue = queue.Queue()
        self.halt = threading.Event()
        relay = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a) -> None:
                pass

            def _json(self, body) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                relay.leases.append(json.loads(self.rfile.read(n) or b"{}"))
                self._json({"ok": True})

            def do_GET(self) -> None:
                path = self.path.split("?")[0]
                relay.gets.append(path)
                if path == "/admin/accounts":
                    self._json({"accounts": [{"id": a, "freshness": f} for a, f in relay.accounts.items()]})
                elif path == "/admin/accounts/roster-counts":
                    self._json({"counts": {}, "now": int(time.time() * 1000)})
                elif path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while not relay.halt.is_set():
                        try:
                            line = relay.lines.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        self.wfile.write(line.encode())
                        self.wfile.flush()
                else:
                    self.send_error(404)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self._id = 0

    def push(self, event: str, data: dict) -> None:
        self._id += 1
        self.lines.put(f"id: {self._id}\nevent: {event}\ndata: {json.dumps(data)}\n\n")

    def close(self) -> None:
        self.halt.set()
        self.srv.shutdown()


def fresh(aid: str, seq: int, v: int, n: int | None, grey: str | None = None) -> dict:
    return {"account_id": aid, "boot": 1, "seq": seq, "now": 2_000 + seq, "at": 2_000 + seq, "cycle_s": 60,
            "live": "up", "live_since": 1_000,
            "values": {"unread_total": {"n": n, "at": 2_000 + seq, "v": v, "grey": grey}}}


def ctx_for(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(fault=None, browser_fault_hits={}, app_ts_fault_files={},
                           stack=SimpleNamespace(tmp=tmp_path))


async def until(cond, timeout: float = 15.0) -> None:
    t0 = time.time()
    while not cond():
        assert time.time() - t0 < timeout, "timed out"
        await asyncio.sleep(0.05)


def test_tab_runs_the_apps_store_behind_and_circle(tmp_path):
    relay = Relay()
    relay.accounts = {A: fresh(A, 1, 1, 3), B: fresh(B, 1, 1, 9)}

    async def go():
        ctx = ctx_for(tmp_path)
        (ts,) = await open_ts(ctx)
        tab = BadgeTab(ctx, "t", [A], ts, http=Http(relay.url, Recorder(), limits=4), lease_s=0.2)
        try:
            await tab.start()
            assert tab.held(A)["n"] == 3 and tab.held(B) is None

            relay.push("creator_refreshed", {"creator_refreshed": fresh(A, 2, 2, 5), "__account_id": A})
            await until(lambda: (tab.held(A) or {}).get("n") == 5)
            relay.push("creator_refreshed", {"creator_refreshed": fresh(A, 1, 9, 99), "__account_id": A})
            relay.push("creator_refreshed", {"creator_refreshed": fresh(B, 3, 4, 1), "__account_id": B})

            relay.push("ping", {"ts": 3.0, "badge": {A: 2, B: 7}})
            await until(lambda: tab.pings == 1)
            await asyncio.sleep(0.3)
            assert tab.refetches == 0 and tab.held(A)["v"] == 2

            relay.accounts[A] = fresh(A, 3, 3, 0, grey="dead")
            relay.push("ping", {"ts": 4.0, "badge": {A: 3}})
            await until(lambda: (tab.held(A) or {}).get("v") == 3)
            assert tab.refetches == 1 and tab.behind_pings == 1
            await until(lambda: len(relay.leases) >= 2)
        finally:
            await tab.stop()
        await classify([tab], ts)
        await ts.close()
        return tab

    try:
        tab = asyncio.run(go())
    finally:
        relay.close()
    assert [s["v"] for _, s in tab.slots[A]] == [1, 2, 3]
    assert [n for _, _, n, _ in tab.served] == [3, 5, 99, 0]
    assert [src for *_, src in tab.served] == ["accounts", "sse", "sse", "accounts"]
    assert [t for t, *_ in tab.served] == [2.001, 2.002, 2.001, 2.003]
    assert [(k, n) for _, k, n in tab.observed[A]] == [("red", 3), ("red", 5), ("grey", None)]
    assert tab.red(A)[-1][1] == "grey"
    assert all(lease["account_ids"] == [A] for lease in relay.leases)
    assert relay.gets.count("/admin/accounts") == 2 and not tab.errors
