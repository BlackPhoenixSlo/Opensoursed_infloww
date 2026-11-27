#!/usr/bin/env python3
"""Capture gate for a read-only Fansly Mirror capture (ADR-0065).

Every process here runs at nice 10 (each subcommand lowers its own priority to 10
if started higher, and children inherit it).

  gate.py blank    --port P            crash then empty every web tab of that Chrome
  gate.py selftest --port P [--root R] five-case proof on localhost; writes R/selftest.json
  gate.py run      --port P [--root R] [--fan-account-id ID]
  gate.py watch    --port P [--root R] the watchdog; run beside `run`
  gate.py stop     --port P [--root R] blank, then close the session with `stopped`
  gate.py audit    --session ID [--root R]
  gate.py manifest [--root R]           R/manifest.json from audited sessions' saves
  gate.py plan     --check              validate mirror_plan.json against ticket 01

Port 9222 (an unrelated Chrome) is refused by every subcommand that touches Chrome.
Output names roles and counts, never identity values.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import websockets

from blank import TARGET_END, _is_web, blank_web_pages
from record import CDP, browser_ws_url

DEFAULT_ROOT = Path.home() / "Downloads" / "fansly-live-capture"
API_ORIGIN = "https://apiv3.fansly.com"
REFUSED_PORT = 9222
SELFTEST_SESSION_PREFIX = "selftest-"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BEAT_EVERY = 0.5
STALE_AFTER = 2.0
WATCH_POLL = 0.25
WATCHDOG_WAIT = 30.0
BLANK_EXIT_WAIT = 90.0
WORKER_TYPES = frozenset({"worker", "service_worker", "shared_worker"})
WEB_TYPES = frozenset({"page", "iframe"}) | WORKER_TYPES

OK = '{"success":true}'


def _status_body() -> str:
    now = int(time.time() * 1000)
    return json.dumps({"success": True, "response": {
        "accountId": "0", "statusId": 1, "lastSeenAt": now, "updatedAt": now}},
        separators=(",", ":"))


ON_OPEN = {
    "/api/v1/message/ack": (lambda: OK, "recorded"),
    "/api/v1/status": (_status_body, "recorded"),
    "/api/v1/it/pis": (lambda: OK, "unverified"),
    "/api/v1/notifications/ack": (lambda: OK, "unverified"),
    "/api/v1/mediastory/view": (lambda: OK, "unverified"),
}

TELEMETRY = {
    ("api-iam.intercom.io", "/messenger/web/ping"),
    ("g2ytx5gg.messenger.intercom-chat.com", "/messenger/web/ping"),
    ("metrics.fansly.com", "/event/track/v1/"),
}

WS_STUB = """
  if (g.WebSocket && !g.WebSocket.__gateStub) {
    class GateClosedSocket extends g.EventTarget {
      constructor(url) {
        super();
        this.url = String(url); this.readyState = 3; this.protocol = ''; this.extensions = '';
        this.bufferedAmount = 0; this.binaryType = 'blob';
        this.onopen = null; this.onmessage = null; this.onerror = null; this.onclose = null;
        g.setTimeout(() => {
          const ev = new g.CloseEvent('close', {code: 1006, reason: '', wasClean: false});
          if (typeof this.onclose === 'function') this.onclose(ev);
          this.dispatchEvent(ev);
        }, 0);
      }
      send() {}
      close() {}
    }
    Object.assign(GateClosedSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3, __gateStub: true});
    g.WebSocket = GateClosedSocket;
  }"""

KEEPALIVE_STUB = """
  if (!g.__gateKeepalive) {
    g.__gateKeepalive = true;
    if (g.Navigator && g.Navigator.prototype.sendBeacon) g.Navigator.prototype.sendBeacon = function sendBeacon() { return false };
    if (g.fetchLater) g.fetchLater = function fetchLater() { throw new TypeError('fetchLater is off under the gate') };
    const f = g.fetch;
    if (f) g.fetch = function fetch(input, init) {
      if (init && init.keepalive) init = Object.assign({}, init, {keepalive: false});
      if (g.Request && input instanceof g.Request && input.keepalive) input = new g.Request(input, {keepalive: false});
      return f.call(g, input, init);
    };
  }"""

POPUP_STUB = """
  if (g.open && !g.open.__gateStub) {
    const realOpen = g.open;
    g.open = function open(...a) {
      const w = realOpen.apply(this, a);
      try { if (w) arm(w) } catch (e) {}
      return w;
    };
    g.open.__gateStub = true;
  }"""

STUBS = "(() => { const arm = g => {" + WS_STUB + KEEPALIVE_STUB + POPUP_STUB + "\n}; arm(self); })();"


@dataclass
class Verdict:
    action: str
    reason: str
    halt: bool = False
    body: str | None = None
    provenance: str | None = None
    decision: str = ""
    status: int = 200


@dataclass
class AuditResult:
    passed: bool
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"passed": self.passed, "failures": self.failures,
                "warnings": self.warnings, "counts": self.counts}


def _origin(url: str) -> str:
    s = urllib.parse.urlsplit(url)
    return f"{s.scheme}://{s.netloc}".lower()


def on_open_reply(method: str, url: str, api_origin: str):
    if method.upper() != "POST" or _origin(url) != api_origin.rstrip("/").lower():
        return None
    hit = ON_OPEN.get(urllib.parse.urlsplit(url).path)
    if hit is None:
        return None
    make, provenance = hit
    return make(), provenance


def _is_waf_host(host: str) -> bool:
    return host == "awswaf.com" or host.endswith(".awswaf.com")


def decide(method: str, url: str, resource_type: str, halted: bool, api_origin: str) -> Verdict:
    m = method.upper()
    if halted:
        return Verdict("fail", "halted", decision="denied")
    if m in SAFE_METHODS:
        return Verdict("continue", "read", decision="continued")
    if m == "POST":
        fake = on_open_reply(m, url, api_origin)
        if fake is not None:
            return Verdict("fulfill", "on-open", body=fake[0], provenance=fake[1], decision="faked")
        s = urllib.parse.urlsplit(url)
        host = (s.hostname or "").lower()
        if s.scheme == "https" and (host, s.path) in TELEMETRY:
            return Verdict("fulfill", "telemetry", body="", provenance="telemetry", decision="faked",
                           status=204)
        if _is_waf_host(host):
            return Verdict("continue", "waf", decision="waf")
    return Verdict("fail", f"write {m}", halt=True, decision="halted")


def _usernames(identities) -> set[str]:
    out = set()
    for i in identities or ():
        name = i.get("username") if isinstance(i, dict) else i
        if name:
            out.add(str(name).casefold())
    return out


def redact_path(path: str, identities) -> str:
    names = _usernames(identities)
    segs = []
    for seg in path.split("/"):
        plain = urllib.parse.unquote(seg)
        if plain and plain.casefold() in names:
            segs.append("{username}")
        elif re.fullmatch(r"\d{9,}", plain):
            segs.append("{id}")
        else:
            segs.append(seg)
    return "/".join(segs)


def is_stale(beat, now: float, max_age: float) -> bool:
    return beat is None or now - beat > max_age


def selftest_binds(selftest, browser_id: str):
    if not selftest:
        return "no self-test on record: run gate.py selftest on this port first"
    if not selftest.get("pass"):
        return "the last self-test did not pass: re-run gate.py selftest"
    if selftest.get("browser_id") != browser_id:
        return "the self-test is from another Chrome launch: re-run gate.py selftest"
    return None


def unblanked_refusal(targets):
    if any(_is_fansly(t.get("url", "")) for t in targets):
        return "a Fansly tab is open in this Chrome: run gate.py blank first"
    return None


def request_line(ts: float, session: str, target_type: str, request: dict,
                 resource_type: str, verdict: Verdict, identities) -> dict:
    s = urllib.parse.urlsplit(request.get("url", ""))
    web = s.scheme in ("http", "https", "ws", "wss")
    line = {
        "ts": round(ts, 3), "session": session, "target_type": target_type,
        "method": str(request.get("method", "")).upper(),
        "host": (s.hostname or "") if web else s.scheme,
        "path": redact_path(s.path, identities) if web else "",
        "query_keys": sorted({k for k, _ in urllib.parse.parse_qsl(s.query, keep_blank_values=True)})
        if web else [],
        "resource_type": resource_type, "decision": verdict.decision, "reason": verdict.reason,
    }
    if verdict.provenance:
        line["provenance"] = verdict.provenance
    return line


def unread_from_groups(body: dict):
    if not isinstance(body, dict) or not body.get("success"):
        return None
    resp = body.get("response") or {}
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, list):
        return None
    return {str(g.get("groupId")): int(g.get("unreadCount") or 0)
            for g in data if isinstance(g, dict) and g.get("groupId")}


def _identity(role: str, acct: dict) -> dict:
    return {"role": role, "username": str(acct.get("username") or ""),
            "displayName": str(acct.get("displayName") or ""), "accountId": str(acct.get("id") or "")}


def identity_from_me(body: dict):
    acct = ((body or {}).get("response") or {}).get("account") if isinstance(body, dict) else None
    return _identity("creator", acct) if isinstance(acct, dict) and acct.get("id") else None


def identity_from_accounts(body: dict, fan_id):
    if not fan_id or not isinstance(body, dict):
        return None
    for acct in body.get("response") or []:
        if isinstance(acct, dict) and str(acct.get("id")) == str(fan_id):
            return _identity("fan", acct)
    return None


def value_shape(v):
    if isinstance(v, dict):
        return {k: value_shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [value_shape(v[0])] if v else []
    if v is None:
        return "null"
    return {bool: "bool", int: "int", float: "float", str: "str"}.get(type(v), type(v).__name__)


def read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for ln in path.read_text().splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def _next_saved_page(session: Path, after: float):
    pages = session.parent.parent / "pages"
    best = None
    if pages.is_dir():
        for meta in pages.rglob("*.meta.json"):
            try:
                m = json.loads(meta.read_text())
            except ValueError:
                continue
            if m.get("session") != session.name:
                continue
            t = float(m.get("saved_at") or meta.stat().st_mtime)
            if t > after and (best is None or t < best[0]):
                best = (t, str(meta.relative_to(pages))[: -len(".meta.json")])
    return best[1] if best else None


def audit(session: Path, now: float) -> AuditResult:
    failures, warnings = [], []
    counts = Counter()
    stopped = False
    unverified: dict[str, float] = {}
    for ln in read_jsonl(session / "gate.jsonl"):
        ev = ln.get("event")
        if ev:
            counts[f"event_{ev}"] += 1
            stopped = stopped or ev == "stopped"
            continue
        d = ln.get("decision", "")
        counts[d] += 1
        if d == "continued" and str(ln.get("method", "")).upper() not in SAFE_METHODS:
            counts["continued_writes"] += 1
        if d == "faked" and ln.get("provenance") == "unverified":
            p = ln.get("path", "")
            unverified[p] = min(unverified.get(p, ln.get("ts", 0)), ln.get("ts", 0))
    counts.setdefault("continued_writes", 0)
    counts.setdefault("waf", 0)
    if counts["continued_writes"]:
        failures.append(f"{counts['continued_writes']} continued request(s) outside GET/HEAD/OPTIONS")
    if counts["event_ws_frame_sent"]:
        failures.append(f"{counts['event_ws_frame_sent']} socket frame(s) sent after arming")
    if counts["event_ws_created"]:
        failures.append(f"{counts['event_ws_created']} socket(s) created after arming")
    if counts["event_ws_handshake"]:
        failures.append(f"{counts['event_ws_handshake']} socket handshake(s) completed after arming")
    if counts["event_blank_unconfirmed"]:
        failures.append(f"{counts['event_blank_unconfirmed']} blank(s) left a target without a confirmed crash")
    if (session / "HALT").exists() or counts["event_halt"]:
        failures.append("session halted")
    if (session / "WATCHDOG_TRIP").exists():
        failures.append("watchdog tripped")
    if not stopped:
        failures.append("no stopped event: session was not closed by gate.py stop")
    obs = read_jsonl(session / "unread.jsonl")
    counts["groups_observations"] = len(obs)
    if len(obs) < 2:
        failures.append(f"{len(obs)} /messaging/groups observation(s); need at least 2")
    else:
        first, last, seen = {}, {}, {}
        for o in obs:
            for g, n in (o.get("groups") or {}).items():
                first.setdefault(g, n)
                last[g] = n
                seen[g] = seen.get(g, 0) + 1
        both = {g for g, k in seen.items() if k >= 2}
        dropped = sum(1 for g in both if last[g] < first[g])
        rose = sum(1 for g in both if last[g] > first[g])
        counts["groups_compared"] = len(both)
        if not both:
            failures.append("no thread was seen in two /messaging/groups observations")
        if dropped:
            failures.append(f"unread count dropped in {dropped} group(s)")
        if rose:
            warnings.append(f"unread count rose in {rose} group(s) (fan activity)")
    for path, ts in sorted(unverified.items()):
        page = _next_saved_page(session, ts)
        where = f"check the screenshot of page {page}" if page else "no page was saved after it"
        warnings.append(f"unverified fake {path} fired; {where}")
    return AuditResult(not failures, failures, warnings, dict(counts))


def ports_path(root: Path, port: int) -> Path:
    return root / "ports" / f"{port}.json"


def session_dir(root: Path, session: str) -> Path:
    return root / "sessions" / session


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=None))
    os.replace(tmp, path)


def read_ports(root: Path, port: int):
    return read_json(ports_path(root, port))


def read_beat(path: Path):
    b = read_json(path)
    return (b.get("ts"), b) if isinstance(b, dict) else (None, {})


def known_identities(root: Path) -> list:
    out = []
    for f in (root / "sessions").glob("*/identities.json"):
        data = read_json(f)
        if isinstance(data, list):
            out.extend(i for i in data if isinstance(i, dict))
    return out


def gate_alive(sdir: Path) -> bool:
    try:
        fd = os.open(sdir / "gate.lock", os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _is_fansly(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == "fansly.com" or host.endswith(".fansly.com")


def _is_loopback(origin: str) -> bool:
    return (urllib.parse.urlsplit(origin).hostname or "") in ("127.0.0.1", "localhost", "::1")


def browser_id(port: int) -> str:
    return browser_ws_url(port).rstrip("/").rsplit("/", 1)[-1]


def http_targets(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        return json.load(r)


def ensure_nice() -> None:
    try:
        if os.getpriority(os.PRIO_PROCESS, 0) < 10:
            os.setpriority(os.PRIO_PROCESS, 0, 10)
    except OSError:
        pass


class Conn:
    def __init__(self, ws, on_event=None):
        self.ws = ws
        self.cdp = CDP(ws)
        self.on_event = on_event
        self.closed = asyncio.Event()
        self.seq = 0
        self.ended: dict[str, dict[str, int]] = {k: {} for k in TARGET_END.values()}
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                kind = TARGET_END.get(msg.get("method", ""))
                if kind:
                    self.seq += 1
                    self.ended[kind][(msg.get("params") or {}).get("targetId")] = self.seq
                if not self.cdp.resolve(msg) and self.on_event:
                    self.on_event(msg)
        except Exception:
            pass
        finally:
            self.closed.set()

    async def send(self, method, params=None, session_id=None, timeout=10.0):
        return await self.cdp.send(method, params, session_id=session_id, timeout=timeout)


async def connect(port: int, on_event=None) -> Conn:
    ws = await websockets.connect(browser_ws_url(port), max_size=200 * 1024 * 1024,
                                  ping_interval=None)
    conn = Conn(ws, on_event)
    try:
        await conn.send("Target.setDiscoverTargets", {"discover": True}, timeout=5)
    except Exception:
        await ws.close()
        raise
    return conn


async def arm_stub(send, sid, ttype: str) -> None:
    if ttype in ("page", "iframe"):
        await send("Page.enable", {}, sid)
        await send("Page.addScriptToEvaluateOnNewDocument", {"source": STUBS, "runImmediately": True}, sid)
    elif ttype in WORKER_TYPES:
        await send("Runtime.evaluate", {"expression": STUBS}, sid, timeout=3)


def _worker_fetch_runs_in_parent_page(ttype: str, err: Exception) -> bool:
    return ttype == "worker" and "-32601" in str(err)


async def auto_attach(send, sid) -> None:
    await send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                        "flatten": True}, sid, timeout=3)


async def apply_verdict(conn: Conn, sid, rid: str, req: dict, v: Verdict) -> None:
    try:
        if v.action == "continue":
            await conn.send("Fetch.continueRequest", {"requestId": rid}, sid)
        elif v.action == "fulfill":
            headers = [{"name": "Content-Type", "value": "application/json"}]
            origin = next((val for k, val in (req.get("headers") or {}).items() if k.lower() == "origin"), None)
            if origin:
                headers += [{"name": "Access-Control-Allow-Origin", "value": origin},
                            {"name": "Access-Control-Allow-Credentials", "value": "true"}]
            await conn.send("Fetch.fulfillRequest", {
                "requestId": rid, "responseCode": v.status, "responseHeaders": headers,
                "body": base64.b64encode(v.body.encode()).decode()}, sid)
        else:
            await conn.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, sid)
    except Exception:
        pass


def _refuse(msg: str, code: int = 2) -> int:
    print(f"refused: {msg}", file=sys.stderr)
    return code


class Gate:
    def __init__(self, args, root: Path, session: str, bid: str, api_origin: str):
        self.args = args
        self.root = root
        self.session = session
        self.sdir = session_dir(root, session)
        self.sdir.mkdir(parents=True, exist_ok=True)
        self.browser_id = bid
        self.api_origin = api_origin.rstrip("/")
        self.fan_id = args.fan_account_id
        self.sessions: dict[str, dict] = {}
        self.by_target: dict[str, str] = {}
        self.by_tid: dict[str, str] = {}
        self.halted = False
        self.blank_done = asyncio.Event()
        self.armed_at: float | None = None
        self.counts = Counter()
        self.tasks: set = set()
        self.found: dict[str, dict] = {}
        self.identities = known_identities(root)
        self.log_f = (self.sdir / "gate.jsonl").open("a", buffering=1)
        self.conn: Conn | None = None
        api = self.api_origin
        self.patterns = [{"urlPattern": "*", "requestStage": "Request"}] + [
            {"urlPattern": f"{api}{p}", "requestStage": "Response"}
            for p in ("/api/v1/account/me*", "/api/v1/account?ids=*", "/api/v1/messaging/groups*")]

    def log(self, obj: dict) -> None:
        self.log_f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def event(self, name: str, **kw) -> None:
        self.log({"ts": round(time.time(), 3), "session": self.session, "event": name, **kw})

    def on_event(self, msg: dict) -> None:
        method = msg.get("method", "")
        handler = {
            "Target.attachedToTarget": self.arm,
            "Target.detachedFromTarget": self.detached,
            "Fetch.requestPaused": self.paused,
            "Network.webSocketCreated": self.ws_created,
            "Network.webSocketHandshakeResponseReceived": self.ws_handshake,
            "Network.webSocketFrameSent": self.ws_frame,
        }.get(method)
        if handler:
            t = asyncio.create_task(handler(msg.get("sessionId"), msg.get("params") or {}))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)

    async def arm(self, _parent, p: dict) -> None:
        sid = p["sessionId"]
        info = p["targetInfo"]
        ttype = info.get("type", "")
        send = self.conn.send
        try:
            try:
                await send("Fetch.enable", {"patterns": self.patterns}, sid)
            except RuntimeError as e:
                if not _worker_fetch_runs_in_parent_page(ttype, e):
                    raise
            page_like = ttype in ("page", "iframe")
            await send("Network.enable", {}, sid, timeout=10 if page_like else 3)
            if page_like:
                await send("Network.setBypassServiceWorker", {"bypass": True}, sid)
            await arm_stub(send, sid, ttype)
            await auto_attach(send, sid)
        except Exception as e:
            self.event("arm_failed", target_type=ttype, error=str(e)[:160])
            if not self.halted:
                try:
                    await send("Target.closeTarget", {"targetId": info["targetId"]}, timeout=3)
                except Exception:
                    pass
            await self.halt(f"arming a {ttype} target failed ({type(e).__name__})")
            return
        self.sessions[sid] = {"type": ttype, "target_id": info["targetId"]}
        self.by_tid[info["targetId"]] = sid
        if ttype == "page":
            self.by_target[info["targetId"]] = sid
        self.counts["armed_targets"] += 1
        try:
            await send("Runtime.runIfWaitingForDebugger", {}, sid, timeout=3)
        except Exception:
            pass

    async def detached(self, _parent, p: dict) -> None:
        s = self.sessions.pop(p.get("sessionId", ""), None)
        for m in (self.by_target, self.by_tid):
            if s and m.get(s["target_id"]) == p.get("sessionId"):
                m.pop(s["target_id"], None)

    async def paused(self, sid, p: dict) -> None:
        rid = p["requestId"]
        req = p.get("request") or {}
        if "responseStatusCode" in p or "responseErrorReason" in p:
            try:
                await self.read_response(sid, rid, req.get("url", ""))
            finally:
                try:
                    await self.conn.send("Fetch.continueRequest", {"requestId": rid}, sid)
                except Exception:
                    pass
            return
        ttype = self.sessions.get(sid, {}).get("type", "?")
        v = decide(req.get("method", ""), req.get("url", ""), p.get("resourceType", ""),
                   self.halted, self.api_origin)
        self.counts[v.decision] += 1
        self.log(request_line(time.time(), self.session, ttype, req, p.get("resourceType", ""),
                              v, self.identities + list(self.found.values())))
        await apply_verdict(self.conn, sid, rid, req, v)
        if v.halt:
            s = urllib.parse.urlsplit(req.get("url", ""))
            path = redact_path(s.path, self.identities + list(self.found.values()))
            await self.halt(f"{v.reason} {s.hostname or s.scheme}{path}")

    async def read_response(self, sid, rid: str, url: str) -> None:
        try:
            r = await self.conn.send("Fetch.getResponseBody", {"requestId": rid}, sid)
            raw = r.get("body", "")
            if r.get("base64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8", "replace")
            body = json.loads(raw)
        except Exception:
            return
        path = urllib.parse.urlsplit(url).path
        if path == "/api/v1/messaging/groups":
            groups = unread_from_groups(body)
            if groups is not None:
                with (self.sdir / "unread.jsonl").open("a") as f:
                    f.write(json.dumps({"ts": round(time.time(), 3), "groups": groups}) + "\n")
                self.counts["groups_observations"] += 1
        elif path == "/api/v1/account/me":
            ident = identity_from_me(body)
            if ident:
                self.found["creator"] = ident
                write_json(self.sdir / "account-me.shape.json",
                           value_shape((body.get("response") or {}).get("account")))
                self._write_identities()
        elif path == "/api/v1/account":
            ident = identity_from_accounts(body, self.fan_id)
            if ident:
                self.found["fan"] = ident
                self._write_identities()

    def _write_identities(self) -> None:
        write_json(self.sdir / "identities.json", list(self.found.values()))

    async def ws_created(self, sid, p: dict) -> None:
        self.event("ws_created", host=urllib.parse.urlsplit(p.get("url", "")).hostname or "")
        if self.armed_at is not None:
            await self.halt("socket created after arming")

    async def ws_handshake(self, sid, p: dict) -> None:
        self.event("ws_handshake")
        if self.armed_at is not None:
            await self.halt("socket handshake after arming")

    async def ws_frame(self, sid, p: dict) -> None:
        self.event("ws_frame_sent")
        if self.armed_at is not None:
            await self.halt("socket frame sent after arming")

    async def halt(self, reason: str) -> None:
        if self.halted:
            return
        self.halted = True
        (self.sdir / "HALT").write_text(reason + "\n")
        self.event("halt", reason=reason)
        print(f"HALT: {reason}", flush=True)
        try:
            n, unconfirmed = await blank_web_pages(self.conn, self.by_tid)
            self.event("blanked", tabs=n)
        except Exception as e:
            unconfirmed = [f"blank failed ({type(e).__name__})"]
        finally:
            self.blank_done.set()
        if unconfirmed:
            self.event("blank_unconfirmed", targets=unconfirmed)
            print(f"HALT: blanked without a confirmed crash: {unconfirmed}", flush=True)

    async def wait_blank(self) -> None:
        if not self.halted:
            return
        try:
            await asyncio.wait_for(self.blank_done.wait(), BLANK_EXIT_WAIT)
        except TimeoutError:
            self.event("blank_unconfirmed", targets=["blank still running at exit"])

    async def beat(self) -> None:
        while True:
            write_json(self.sdir / "heartbeat", {"ts": time.time()})
            await asyncio.sleep(BEAT_EVERY)

    async def wait_armed(self, expect: set, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            armed = {s["target_id"] for s in self.sessions.values()}
            if expect <= armed:
                return True
            await asyncio.sleep(0.05)
        return False

    async def run(self) -> int:
        port = self.args.port
        self.lock_f = (self.sdir / "gate.lock").open("w")
        fcntl.flock(self.lock_f, fcntl.LOCK_EX)
        write_json(ports_path(self.root, port), {
            "session": self.session, "armed": False, "capture_target_id": None,
            "browser_id": self.browser_id, "api_origin": self.api_origin, "gate_pid": os.getpid()})
        beat = asyncio.create_task(self.beat())
        self.conn = await connect(port, self.on_event)
        send = self.conn.send
        snapshot = (await send("Target.getTargets"))["targetInfos"]
        expect = {t["targetId"] for t in snapshot if t.get("type") in WEB_TYPES}
        await send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                            "flatten": True})
        if not await self.wait_armed(expect, 10.0):
            await self.halt("not every existing target armed within 10 s")
        if not self.halted:
            self.armed_at = time.time()
            self.event("armed", targets=len(self.sessions))
            reloaded = 0
            for tid, sid in list(self.by_target.items()):
                url = next((t.get("url", "") for t in snapshot if t["targetId"] == tid), "")
                if _is_web(url):
                    try:
                        await send("Page.reload", {}, sid, timeout=5)
                    except Exception as e:
                        await self.halt(f"reloading a page after arming failed ({type(e).__name__})")
                        break
                    reloaded += 1
            self.event("reloaded", count=reloaded)
        wd_path = self.sdir / "watchdog.heartbeat"
        end = time.time() + WATCHDOG_WAIT
        while not self.halted and is_stale(read_beat(wd_path)[0], time.time(), STALE_AFTER):
            if time.time() > end:
                self.event("watchdog_stale")
                await self.halt("watchdog heartbeat never seen")
                break
            await asyncio.sleep(0.1)
        if not self.halted:
            pages = [t for t in (await send("Target.getTargets"))["targetInfos"] if t["type"] == "page"]
            cap = next((t for t in pages if _is_web(t.get("url", ""))), pages[0] if pages else None)
            write_json(ports_path(self.root, port), {
                "session": self.session, "armed": True,
                "capture_target_id": cap["targetId"] if cap else None,
                "browser_id": self.browser_id, "api_origin": self.api_origin,
                "gate_pid": os.getpid()})
            print(f"armed session {self.session}: {self.counts['armed_targets']} targets", flush=True)
        code = 0
        while True:
            if (self.sdir / "STOP").exists():
                self.event("stopped")
                break
            if (self.sdir / "HALT").exists() and not self.halted:
                await self.halt("HALT marker written outside the gate")
            wd_ts, wd = read_beat(wd_path)
            if not self.halted and is_stale(wd_ts, time.time(), STALE_AFTER):
                self.event("watchdog_stale")
                await self.halt("watchdog heartbeat stale")
            if self.halted and wd.get("halt_seen"):
                code = 3
                break
            if self.conn.closed.is_set():
                self.event("chrome_gone")
                code = 4
                break
            await asyncio.sleep(BEAT_EVERY)
        await self.wait_blank()
        beat.cancel()
        c = self.counts
        print(f"session {self.session} ended: continued {c['continued']} faked {c['faked']} "
              f"waf {c['waf']} denied {c['denied'] + c['halted']} "
              f"groups observations {c['groups_observations']} identities {len(self.found)}", flush=True)
        self.log_f.close()
        return code


def cmd_run(args, root: Path) -> int:
    api = args.api_origin or API_ORIGIN
    selftest_mode = api.rstrip("/") != API_ORIGIN
    if selftest_mode and not _is_loopback(api):
        return _refuse("--api-origin is only for the self-test's loopback server")
    st = None if selftest_mode else read_json(root / "selftest.json")
    try:
        bid, unreachable = browser_id(args.port), None
    except Exception as e:
        bid, unreachable = None, f"cannot reach Chrome CDP on :{args.port} ({type(e).__name__})"
    if not selftest_mode and (r := selftest_binds(st, bid)):
        return _refuse(r if bid else f"{r}; {unreachable}")
    if bid is None:
        return _refuse(unreachable)
    if r := unblanked_refusal(http_targets(args.port)):
        return _refuse(r)
    existing = read_ports(root, args.port)
    if existing is not None:
        return _refuse(f"ports/{args.port}.json exists (session {existing.get('session')}): "
                       "run gate.py stop first")
    prefix = SELFTEST_SESSION_PREFIX if selftest_mode else ""
    session = f"{prefix}{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}"
    return asyncio.run(Gate(args, root, session, bid, api).run())


async def _blank(port: int) -> tuple[int, list]:
    conn = await connect(port)
    try:
        return await blank_web_pages(conn, {}, close_others=True)
    finally:
        await conn.ws.close()


def log_event(sdir: Path, session: str, name: str, **kw) -> None:
    with (sdir / "gate.jsonl").open("a") as f:
        f.write(json.dumps({"ts": round(time.time(), 3), "session": session, "event": name, **kw}) + "\n")


async def do_stop(port: int, root: Path) -> tuple[str | None, int, list]:
    ports = read_ports(root, port)
    n, unconfirmed = await _blank(port)
    if ports is None:
        return None, n, unconfirmed
    sdir = session_dir(root, ports["session"])
    if unconfirmed:
        log_event(sdir, ports["session"], "blank_unconfirmed", targets=unconfirmed, by="stop")
    (sdir / "STOP").write_text("stop\n")
    end = time.time() + (5.0 if gate_alive(sdir) else 0.0)
    while True:
        if any(ln.get("event") == "stopped" for ln in read_jsonl(sdir / "gate.jsonl")[-5:]):
            break
        if time.time() >= end:
            log_event(sdir, ports["session"], "stopped", reason="gate not running")
            break
        await asyncio.sleep(0.1)
    ports_path(root, port).unlink(missing_ok=True)
    return ports["session"], n, unconfirmed


def cmd_audit(args, root: Path) -> int:
    sdir = session_dir(root, args.session)
    if not sdir.is_dir():
        return _refuse(f"no session {args.session} under the root", 1)
    res = audit(sdir, time.time())
    write_json(sdir / "audit.json", {"session": args.session, "ts": time.time(), **res.as_dict()})
    print(f"audit {args.session}: {'PASS' if res.passed else 'FAIL'} "
          + " ".join(f"{k}={v}" for k, v in sorted(res.counts.items())))
    for f in res.failures:
        print(f"  fail: {f}")
    for w in res.warnings:
        print(f"  warn: {w}")
    return 0 if res.passed else 1


def _unconfirmed_refusal(unconfirmed: list) -> int:
    if not unconfirmed:
        return 0
    print(f"REFUSED: blanked {len(unconfirmed)} target(s) without a confirmed renderer crash: {unconfirmed}",
          file=sys.stderr)
    return 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "watch", "selftest", "blank", "stop"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, required=True)
        p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        if name == "run":
            p.add_argument("--fan-account-id")
            p.add_argument("--api-origin", help=argparse.SUPPRESS)
    p = sub.add_parser("audit")
    p.add_argument("--session", required=True)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    for name in ("manifest", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        p.add_argument("--plan", type=Path, help="default: mirror_plan.json beside gate.py")
        if name == "plan":
            p.add_argument("--check", action="store_true", required=True)
    args = ap.parse_args(argv)
    ensure_nice()
    root = args.root.expanduser()
    if getattr(args, "port", None) == REFUSED_PORT:
        return _refuse(f"port {REFUSED_PORT} is the unrelated Chrome; never touched")
    if args.cmd == "run":
        return cmd_run(args, root)
    if args.cmd == "audit":
        return cmd_audit(args, root)
    if args.cmd in ("manifest", "plan"):
        import mirror
        return mirror.cmd_manifest(args, root) if args.cmd == "manifest" else mirror.cmd_plan(args)
    if args.cmd == "watch":
        from watch import watch
        return asyncio.run(watch(args.port, root))
    if args.cmd == "blank":
        n, unconfirmed = asyncio.run(_blank(args.port))
        print(f"blanked {n} web tab(s)")
        return _unconfirmed_refusal(unconfirmed) or 0
    if args.cmd == "stop":
        session, n, unconfirmed = asyncio.run(do_stop(args.port, root))
        if session is None:
            print(f"no gate session on :{args.port}; blanked {n} web tab(s)")
            return _unconfirmed_refusal(unconfirmed) or 1
        print(f"stopped session {session}; blanked {n} web tab(s)")
        return _unconfirmed_refusal(unconfirmed) or 0
    if args.cmd == "selftest":
        from selftest import selftest
        return asyncio.run(selftest(args.port, root))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
