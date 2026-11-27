"""`gate.py watch`: the watchdog beside `gate.py run`, with its own deny-writes backstop."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.parse
from pathlib import Path

from blank import blank_web_pages
from gate import (API_ORIGIN, STALE_AFTER, WATCH_POLL, Conn, _worker_fetch_runs_in_parent_page,
                  apply_verdict, arm_stub, auto_attach, connect, decide, gate_alive,
                  is_stale, known_identities, log_event, read_beat, read_ports, redact_path, request_line,
                  session_dir, write_json)


class Backstop:
    # Chrome chains both Fetch interceptors last-enabled first; shared workers resume on the first resume.

    def __init__(self, root: Path, port: int):
        self.root, self.port = root, port
        self.conn: Conn | None = None
        self.by_tid: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.deny_all = False
        self.trip_reason: str | None = None
        self.session: str | None = None
        self.api_origin = API_ORIGIN
        self.tasks: set = set()

    @property
    def sdir(self) -> Path | None:
        return session_dir(self.root, self.session) if self.session else None

    def on_event(self, msg: dict) -> None:
        handler = {"Target.attachedToTarget": self.arm, "Target.detachedFromTarget": self.detached,
                   "Fetch.requestPaused": self.paused}.get(msg.get("method", ""))
        if handler:
            t = asyncio.create_task(handler(msg.get("sessionId"), msg.get("params") or {}))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)

    async def arm(self, _parent, p: dict) -> None:
        sid, info = p["sessionId"], p["targetInfo"]
        ttype = info.get("type", "")
        send = self.conn.send
        try:
            try:
                await send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, sid)
            except RuntimeError as e:
                if not _worker_fetch_runs_in_parent_page(ttype, e):
                    raise
            await arm_stub(send, sid, ttype)
            await auto_attach(send, sid)
        except Exception as e:
            blanking = self.deny_all
            self.deny_all = True
            self.trip_reason = self.trip_reason or f"backstop arming a {ttype} target failed ({type(e).__name__})"
            if not blanking:
                try:
                    await send("Target.closeTarget", {"targetId": info["targetId"]}, timeout=3)
                except Exception:
                    pass
            return
        self.types[sid] = ttype
        self.by_tid[info["targetId"]] = sid
        try:
            await send("Runtime.runIfWaitingForDebugger", {}, sid, timeout=3)
        except Exception:
            pass

    async def detached(self, _parent, p: dict) -> None:
        sid = p.get("sessionId")
        self.types.pop(sid, None)
        for tid, s in list(self.by_tid.items()):
            if s == sid:
                self.by_tid.pop(tid, None)

    async def paused(self, sid, p: dict) -> None:
        rid, req = p["requestId"], p.get("request") or {}
        v = decide(req.get("method", ""), req.get("url", ""), p.get("resourceType", ""),
                   self.deny_all, self.api_origin)
        await apply_verdict(self.conn, sid, rid, req, v)
        if v.halt:
            self.deny_all = True
            self.trip_reason = self.trip_reason or f"watchdog backstop: {v.reason}"
        sdir = self.sdir
        if v.action == "continue" or sdir is None:
            return
        ids = known_identities(self.root)
        line = request_line(time.time(), self.session, self.types.get(sid, "?"), req,
                            p.get("resourceType", ""), v, ids)
        with (sdir / "gate.jsonl").open("a") as f:
            f.write(json.dumps({**line, "by": "watchdog"}, ensure_ascii=False) + "\n")
        if v.halt and not (sdir / "HALT").exists():
            s = urllib.parse.urlsplit(req.get("url", ""))
            (sdir / "HALT").write_text(f"watchdog backstop: {v.reason} {s.hostname or s.scheme}"
                                       f"{redact_path(s.path, ids)}\n")

    async def start(self) -> Conn:
        self.conn = await connect(self.port, self.on_event)
        await self.conn.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                                      "flatten": True})
        return self.conn


async def watch(port: int, root: Path) -> int:
    backstop = Backstop(root, port)
    conn = await backstop.start()
    by_tid = backstop.by_tid
    seen = None
    tripped = halt_seen = gate_seen = lock_seen = False
    reported: set = set()
    ports_seen_at = None
    start = time.time()
    while True:
        now = time.time()
        ports = read_ports(root, port)
        if ports is None or (seen and ports.get("session") != seen):
            if seen:
                print("watchdog: session closed", flush=True)
                return 0
            if now - start > 60:
                print("watchdog: no gate session appeared", flush=True)
                return 2
            await asyncio.sleep(WATCH_POLL)
            continue
        if seen is None:
            seen = backstop.session = ports["session"]
            backstop.api_origin = (ports.get("api_origin") or API_ORIGIN).rstrip("/")
        sdir = session_dir(root, seen)
        ports_seen_at = ports_seen_at or now
        halt_seen = halt_seen or (sdir / "HALT").exists()
        backstop.deny_all = backstop.deny_all or halt_seen
        write_json(sdir / "watchdog.heartbeat", {"ts": now, "halt_seen": halt_seen})
        gate_ts = read_beat(sdir / "heartbeat")[0]
        gate_seen = gate_seen or gate_ts is not None
        alive = gate_alive(sdir)
        lock_seen = lock_seen or alive
        stopping = (sdir / "STOP").exists()
        gone = lock_seen and not alive
        if (not tripped and not stopping and not halt_seen
                and (backstop.trip_reason or gone
                     or ((gate_seen or now - ports_seen_at > 5) and is_stale(gate_ts, now, STALE_AFTER)))):
            tripped = True
            backstop.deny_all = True
            reason = backstop.trip_reason or ("gate process gone" if gone else
                                              "gate heartbeat stale" if gate_seen else "gate heartbeat never seen")
            (sdir / "WATCHDOG_TRIP").write_text(reason + "\n")
            print(f"WATCHDOG_TRIP: {reason}", flush=True)
        if tripped or halt_seen:
            try:
                _, unconfirmed = await blank_web_pages(conn, by_tid, close_others=tripped)
            except Exception as e:
                unconfirmed = [f"blank failed ({type(e).__name__})"]
            unconfirmed = [t for t in unconfirmed if t not in reported]
            if unconfirmed:
                reported.update(unconfirmed)
                log_event(sdir, seen, "blank_unconfirmed", targets=unconfirmed, by="watchdog")
                print(f"watchdog: blanked without a confirmed crash: {unconfirmed}", flush=True)
        if conn.closed.is_set():
            print("watchdog: Chrome gone", flush=True)
            return 4
        await asyncio.sleep(WATCH_POLL)
