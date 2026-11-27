from __future__ import annotations

import asyncio
import json
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

import blank
import gate
from gate import (Conn, _refuse, audit, browser_id, connect, do_stop, read_jsonl,
                  http_targets, read_ports, session_dir, unblanked_refusal, write_json)

ON_OPEN_FAKES = 5
UNLOAD_KINDS = ("beacon", "keepalive", "plain", "later")
FRESH_REALM_KINDS = ("beacon", "keepalive")

SELFTEST_PAGE = """<!doctype html><meta charset=utf-8><title>gate self-test</title><script>
window.selftest = {
  async get(u) { try { const r = await fetch(u); return 'status:' + r.status } catch (e) { return 'rejected' } },
  async post(u) { try { const r = await fetch(u, {method: 'POST', body: 'x'}); return 'status:' + r.status }
                  catch (e) { return 'rejected' } },
  workerPost(u) { return new Promise(res => { const w = new Worker('/t/worker.js');
    w.onmessage = e => res(e.data); w.onerror = () => res('worker-error'); w.postMessage(u);
    setTimeout(() => res('timeout'), 5000) }) },
  startPosting(u) { window.__n = 0; window.__iv = setInterval(() => { window.__n++;
    fetch(u, {method: 'POST', headers: {'content-type': 'application/json'}, body: '{"statusId":1}'})
      .catch(() => {}) }, 100); return 'started' },
  async registerSw() { await navigator.serviceWorker.register('/sw/sw.js'); await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise(r => {
      navigator.serviceWorker.addEventListener('controllerchange', r, {once: true}); setTimeout(r, 5000) });
    return !!navigator.serviceWorker.controller },
  async swPost(u) { const reg = await navigator.serviceWorker.getRegistration('/sw/');
    if (!reg || !reg.active) return 'no-sw';
    return new Promise(res => { navigator.serviceWorker.addEventListener('message', e => res(e.data), {once: true});
      navigator.serviceWorker.startMessages(); reg.active.postMessage(u); setTimeout(() => res('timeout'), 5000) }) },
  async unregisterSw() { for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();
    return 'ok' },
  ws(u) { return new Promise(res => { let s; try { s = new WebSocket(u) } catch (e) { return res('threw') }
    s.onopen = () => res('open'); s.onclose = e => res('closed:' + e.code); setTimeout(() => res('timeout'), 3000) }) },
  armUnload(u) { addEventListener('pagehide', () => { navigator.sendBeacon(u + '/beacon', 'b');
    fetch(u + '/keepalive', {method: 'POST', body: 'k', keepalive: true}).catch(() => {});
    fetch(u + '/plain', {method: 'POST', body: 'p'}).catch(() => {});
    try { self.fetchLater && fetchLater(u + '/later', {method: 'POST', body: 'l'}) } catch (e) {} });
    return self.fetchLater ? 'armed' : 'armed-no-fetchlater' },
  armUnloadFrame(u) { const f = document.createElement('iframe'); document.documentElement.appendChild(f);
    return selftest.armFreshRealm(u, f.contentWindow) },
  armUnloadPopup(u) { const w = window.open('about:blank'); return w ? selftest.armFreshRealm(u, w) : 'no-popup' },
  armFreshRealm(u, w) { const o = location.origin, nav = w.navigator, f = w.fetch;
    addEventListener('pagehide', () => {
      try { nav.sendBeacon(o + u + '/beacon', 'b') } catch (e) {}
      try { f.call(w, o + u + '/keepalive', {method: 'POST', body: 'k', keepalive: true}).catch(() => {}) } catch (e) {} });
    return 'armed' },
  blobWs(u) { return new Promise(res => {
    const w = new Worker(URL.createObjectURL(new Blob([BLOB_WS], {type: 'text/javascript'})));
    w.onmessage = e => res(e.data); w.onerror = () => res('worker-error'); w.postMessage(u);
    setTimeout(() => res('timeout'), 5000) }) },
};
const BLOB_WS = `onmessage = e => { let s; try { s = new WebSocket(e.data) } catch (x) { return postMessage('threw') }
  s.onopen = () => postMessage('open'); s.onclose = c => postMessage('closed:' + c.code) };`;
</script><p>gate self-test</p>"""

SELFTEST_WORKER = """onmessage = async e => {
  try { const r = await fetch(e.data, {method: 'POST', body: 'w'}); postMessage('status:' + r.status) }
  catch (err) { postMessage('rejected') } };"""

SELFTEST_SW = """self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
self.addEventListener('message', e => e.waitUntil((String(e.data).startsWith('ws:')
  ? new Promise(res => { let s; try { s = new WebSocket(e.data) } catch (x) { return res('threw') }
      s.onopen = () => res('open'); s.onclose = c => res('closed:' + c.code); setTimeout(() => res('timeout'), 3000) })
  : fetch(e.data, {method: 'POST', body: 's'}).then(r => 'status:' + r.status, () => 'rejected'))
    .then(v => e.source.postMessage(v))));"""


class LogServer:
    def __init__(self, log_path: Path):
        self.entries: list[tuple[float, str, str]] = []
        self.lock = threading.Lock()
        self.log_f = log_path.open("w", buffering=1)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _any(self):
                n = int(self.headers.get("content-length") or 0)
                if n:
                    self.rfile.read(n)
                with outer.lock:
                    outer.entries.append((time.time(), self.command, self.path))
                    outer.log_f.write(json.dumps({"ts": round(time.time(), 3), "method": self.command,
                                                  "path": self.path}) + "\n")
                p = self.path.split("?")[0]
                body, ctype = b"ok", "text/plain"
                if p in ("/t/page.html", "/sw/page.html"):
                    body, ctype = SELFTEST_PAGE.encode(), "text/html"
                elif p == "/t/worker.js":
                    body, ctype = SELFTEST_WORKER.encode(), "text/javascript"
                elif p == "/sw/sw.js":
                    body, ctype = SELFTEST_SW.encode(), "text/javascript"
                elif p.startswith("/api/"):
                    body, ctype = b'{"success":true}', "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_HEAD = do_OPTIONS = do_DELETE = _any

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def count(self, method: str, needle: str, since: float = 0.0) -> int:
        with self.lock:
            return sum(1 for ts, m, p in self.entries if m == method and needle in p and ts >= since)

    def close(self) -> None:
        self.httpd.shutdown()
        self.log_f.close()


class Tab:
    def __init__(self, port: int, target_id: str):
        self.port = port
        self.target_id = target_id
        self.conn: Conn | None = None

    async def open(self):
        self.conn = Conn(await websockets.connect(
            f"ws://127.0.0.1:{self.port}/devtools/page/{self.target_id}", max_size=50_000_000,
            ping_interval=None))
        return self

    async def call(self, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        return await self.conn.send(method, params, timeout=timeout)

    async def ev(self, expr: str, timeout: float = 15.0, gesture: bool = False):
        try:
            r = await self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                     "awaitPromise": True, "userGesture": gesture}, timeout)
        except RuntimeError as e:
            if "navigated or closed" in str(e) or "Target crashed" in str(e):
                return "blanked-before-reply"
            raise
        if r.get("exceptionDetails"):
            return "exception"
        return r.get("result", {}).get("value")

    async def ready(self, timeout: float = 10.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if await self.ev("document.readyState === 'complete' && !!window.selftest", 3) is True:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.1)
        return False

    async def goto(self, url: str) -> bool:
        await self.call("Page.navigate", {"url": url})
        return await self.ready()

    def url(self) -> str:
        return next((t.get("url", "") for t in http_targets(self.port)
                     if t.get("id") == self.target_id), "")


class GateRun:
    def __init__(self, port: int, root: Path, origin: str, log):
        self.port, self.root, self.origin, self.log = port, root, origin, log
        self.gate = self.watch = None
        self.session = None

    async def __aenter__(self):
        base = [sys.executable, str(Path(gate.__file__).resolve())]
        common = ["--port", str(self.port), "--root", str(self.root)]
        self.watch = subprocess.Popen(base + ["watch"] + common, stdout=self.log, stderr=self.log)
        self.gate = subprocess.Popen(base + ["run"] + common + ["--api-origin", self.origin],
                                     stdout=self.log, stderr=self.log)
        end = time.time() + 30
        while time.time() < end:
            p = read_ports(self.root, self.port)
            if p and p.get("armed"):
                self.session = p["session"]
                return self
            if self.gate.poll() is not None:
                break
            await asyncio.sleep(0.1)
        await self.__aexit__(None, None, None)
        raise RuntimeError("gate did not arm")

    @property
    def sdir(self) -> Path:
        return session_dir(self.root, self.session)

    def lines(self, **match) -> list[dict]:
        return [ln for ln in read_jsonl(self.sdir / "gate.jsonl")
                if all(str(ln.get(k, "")).startswith(v) for k, v in match.items())]

    async def __aexit__(self, *exc):
        await do_stop(self.port, self.root)
        for p in (self.gate, self.watch):
            if p is None:
                continue
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        return False


async def _arm_fresh_realms(tab: Tab, prefix: str) -> dict:
    return {"frame": await tab.ev(f"selftest.armUnloadFrame('{prefix}-frame')"),
            "popup": await tab.ev(f"selftest.armUnloadPopup('{prefix}-popup')", gesture=True)}


def _fresh_realm_posts(server: LogServer, prefix: str) -> dict:
    return {src: {k: server.count("POST", f"{prefix}-{src}/{k}") for k in FRESH_REALM_KINDS}
            for src in ("frame", "popup")}


async def _close_popups(conn, opener: str) -> None:
    for t in (await conn.send("Target.getTargets"))["targetInfos"]:
        if t.get("openerId") == opener and t.get("type") == "page":
            try:
                await conn.send("Target.closeTarget", {"targetId": t["targetId"]}, timeout=3)
            except Exception:
                pass


def _refused(page_result) -> bool:
    return page_result in ("rejected", "blanked-before-reply")


def _case(name: str, ok: bool, **detail) -> dict:
    return {"name": name, "pass": bool(ok), "detail": detail}


def _by(lines: list[dict]) -> dict:
    return dict(Counter(ln.get("by", "gate") for ln in lines))


def _sockets_held(results: dict, server: LogServer, g: GateRun, *needles: str) -> dict:
    handshakes = {n: server.count("GET", n) for n in needles}
    gate_handshakes = len(g.lines(event="ws_handshake"))
    return {"pass": not any(handshakes.values()) and not gate_handshakes, "pages": results,
            "server_handshakes": handshakes, "gate_handshakes": gate_handshakes,
            "gate_created": len(g.lines(event="ws_created"))}


async def _wait(pred, timeout: float, step: float = 0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()


async def selftest(port: int, root: Path) -> int:
    bid = browser_id(port)
    if r := unblanked_refusal(http_targets(port)):
        return _refuse(r)
    if read_ports(root, port) is not None:
        return _refuse(f"ports/{port}.json exists: a gate session is open on :{port}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "selftest.json").unlink(missing_ok=True)
    server = LogServer(root / "selftest-server.jsonl")
    origin = f"http://127.0.0.1:{server.port}"
    ws_url = f"ws://127.0.0.1:{server.port}/ws?case=ws"
    log = (root / "selftest.log").open("a", buffering=1)
    conn = await connect(port)
    created: list[str] = []
    cases: list[dict] = []

    async def new_tab(path: str) -> Tab:
        tid = (await conn.send("Target.createTarget", {"url": origin + path}))["targetId"]
        created.append(tid)
        tab = await Tab(port, tid).open()
        await tab.ready()
        return tab

    try:
        tab = await new_tab("/t/page.html")
        swtab = await new_tab("/sw/page.html")
        controlled_before = await swtab.ev("selftest.registerSw()")

        r = await tab.ev("selftest.post('/sink?case=negative')")
        utab = await new_tab("/t/page.html")
        unload_armed = await utab.ev("selftest.armUnload('/unload-control')")
        fresh_armed = await _arm_fresh_realms(utab, "/unload-control")
        await conn.send("Target.closeTarget", {"targetId": utab.target_id}, timeout=3)
        await asyncio.sleep(1.0)
        await _close_popups(conn, utab.target_id)
        landed = server.count("POST", "case=negative")
        unload = {"armed": unload_armed,
                  "server_posts": {k: server.count("POST", f"/unload-control/{k}") for k in UNLOAD_KINDS},
                  "fresh_realms": {"armed": fresh_armed, "server_posts": _fresh_realm_posts(server, "/unload-control")}}
        unload_ok = (unload["server_posts"]["beacon"] >= 1 and unload["server_posts"]["keepalive"] >= 1
                     and all(n >= 1 for src in unload["fresh_realms"]["server_posts"].values()
                             for n in src.values()))
        cases.append(_case("negative_control", landed >= 1 and r == "status:200" and unload_ok,
                           page=r, server_posts=landed, unload_beacons={"pass": unload_ok, **unload}))

        async with GateRun(port, root, origin, log) as g:
            await tab.ready()
            r = await tab.ev("selftest.get('/probe?case=get')")
            got = server.count("GET", "case=get")
            logged = len(g.lines(decision="continued", path="/probe"))
            fake_pages = [await tab.ev("selftest.post('/api/v1/message/ack')") for _ in range(ON_OPEN_FAKES)]
            await asyncio.sleep(0.3)
            fake_lines = g.lines(decision="faked", path="/api/v1/message/ack")
            fake_posts = server.count("POST", "/api/v1/message/ack")
            fakes_ok = (fake_pages == ["status:200"] * ON_OPEN_FAKES and fake_posts == 0
                        and len(fake_lines) == ON_OPEN_FAKES)
            utab = await new_tab("/t/page.html")
            unload_armed = await utab.ev("selftest.armUnload('/unload')")
            fresh_armed = await _arm_fresh_realms(utab, "/unload")
            sockets = {"page": await tab.ev(f"selftest.ws('{ws_url}-page')"),
                       "blob_worker": await tab.ev(f"selftest.blobWs('{ws_url}-blob')"),
                       "tab_opened_after_arming": await utab.ev(f"selftest.ws('{ws_url}-newtab')")}
            sockets_ok = _sockets_held(sockets, server, g, "case=ws-page", "case=ws-blob", "case=ws-newtab")
            cases.append(_case("get_continued", got >= 1 and r == "status:200" and logged >= 1 and fakes_ok
                               and sockets_ok["pass"],
                               page=r, server_gets=got, gate_continued=logged,
                               on_open_fakes={"pass": fakes_ok, "pages": fake_pages, "server_posts": fake_posts,
                                              "faked_lines": len(fake_lines), "decided_by": _by(fake_lines)},
                               sockets=sockets_ok, session=g.session))
            r = await tab.ev("selftest.post('/sink?case=post')")
            halted = await _wait(lambda: (g.sdir / "HALT").exists(), 3)
            blanked = await _wait(lambda: tab.url() == "about:blank", 3 + blank.CRASH_WAIT)
            unload_blanked = await _wait(lambda: utab.url() == "about:blank", 3)
            await conn.send("Target.closeTarget", {"targetId": utab.target_id}, timeout=3)
            await asyncio.sleep(1.0)
            await _close_popups(conn, utab.target_id)
            landed = server.count("POST", "case=post")
            denied = g.lines(decision="halted", path="/sink")
            unload = {"armed": unload_armed, "blanked": unload_blanked,
                      "server_posts": {k: server.count("POST", f"/unload/{k}") for k in UNLOAD_KINDS},
                      "gate_lines": {k: len(g.lines(path=f"/unload/{k}")) for k in UNLOAD_KINDS},
                      "fresh_realms": {"armed": fresh_armed, "server_posts": _fresh_realm_posts(server, "/unload")}}
            unload["pass"] = (unload_armed.startswith("armed") and unload_blanked
                              and not any(unload["server_posts"].values())
                              and fresh_armed == {"frame": "armed", "popup": "armed"}
                              and not any(n for src in unload["fresh_realms"]["server_posts"].values()
                                          for n in src.values()))
            cases.append(_case("post_denied", landed == 0 and _refused(r) and len(denied) >= 1 and halted
                               and blanked and unload["pass"], page=r, server_posts=landed,
                               gate_halted_lines=len(denied), decided_by=_by(denied), halted=halted,
                               blanked=blanked, unload_beacons=unload, session=g.session))

        sub = {}
        await tab.goto(origin + "/t/page.html")
        async with GateRun(port, root, origin, log) as g:
            await tab.ready()
            r = await tab.ev("selftest.workerPost('/sink?case=worker')")
            halted = await _wait(lambda: (g.sdir / "HALT").exists(), 3)
            await asyncio.sleep(0.5)
            landed = server.count("POST", "case=worker")
            denied = g.lines(decision="halted", path="/sink")
            sub["dedicated_worker"] = {"pass": landed == 0 and _refused(r) and len(denied) >= 1 and halted,
                                       "page": r, "server_posts": landed, "gate_halted_lines": len(denied),
                                       "decided_by": _by(denied), "halted": halted,
                                       "target_types": sorted({ln.get("target_type") for ln in denied})}
        await swtab.goto(origin + "/sw/page.html")
        async with GateRun(port, root, origin, log) as g:
            await swtab.ready()
            sw_sockets = _sockets_held({"service_worker": await swtab.ev(f"selftest.swPost('{ws_url}-sw')")},
                                       server, g, "case=ws-sw")
            r = await swtab.ev("selftest.swPost('/sink?case=sw')")
            halted = await _wait(lambda: (g.sdir / "HALT").exists(), 3)
            await asyncio.sleep(0.5)
            landed = server.count("POST", "case=sw")
            denied = g.lines(decision="halted", path="/sink")
            sw_denied = [ln for ln in denied if ln.get("target_type") == "service_worker"]
            sub["service_worker"] = {"pass": landed == 0 and _refused(r) and len(sw_denied) >= 1 and halted
                                     and controlled_before is True and sw_sockets["pass"],
                                     "sockets": sw_sockets,
                                     "page": r, "server_posts": landed, "gate_halted_lines": len(denied),
                                     "service_worker_halted_lines": len(sw_denied),
                                     "decided_by": _by(denied), "halted": halted,
                                     "registered_before_arming": controlled_before}
        cases.append(_case("worker_post_denied", all(s["pass"] for s in sub.values()), **sub))

        await tab.goto(origin + "/t/page.html")
        async with GateRun(port, root, origin, log) as g:
            await tab.ready()
            await tab.ev("selftest.startPosting('/api/v1/status')")
            faked = await _wait(lambda: len(g.lines(decision="faked")) >= 3, 5)
            before = server.count("POST", "/api/v1/status")
            t_kill = time.time()
            g.gate.send_signal(signal.SIGKILL)
            g.gate.wait()
            tripped = await _wait(lambda: (g.sdir / "WATCHDOG_TRIP").exists(), 6)
            blanked = await _wait(lambda: tab.url() == "about:blank", 4 + blank.CRASH_WAIT)
            t_blank = time.time()
            await asyncio.sleep(1.0)
            after = server.count("POST", "/api/v1/status", since=t_kill)
            res = audit(g.sdir, time.time())
            fakes = g.lines(decision="faked")
            cases.append(_case("gate_sigkill_watchdog",
                               faked and before == 0 and after == 0 and tripped and blanked
                               and not res.passed,
                               fakes_before_kill=sum(1 for ln in fakes if ln.get("ts", 0) < t_kill),
                               decided_by=_by(fakes), server_posts_before=before,
                               server_posts_after_kill=after, tripped=tripped, blanked=blanked,
                               blank_after_s=round(t_blank - t_kill, 2), audit_passed=res.passed,
                               session=g.session))
    except Exception as e:
        cases.append(_case("harness_error", False, error=f"{type(e).__name__}: {str(e)[:200]}"))
    finally:
        try:
            if read_ports(root, port) is not None:
                await do_stop(port, root)
        except Exception:
            pass
        try:
            sw = Tab(port, created[1]) if len(created) > 1 else None
            if sw:
                await sw.open()
                await sw.goto(origin + "/sw/page.html")
                await sw.ev("selftest.unregisterSw()")
        except Exception:
            pass
        for tid in created:
            try:
                await conn.send("Target.closeTarget", {"targetId": tid}, timeout=3)
            except Exception:
                pass
        server.close()
        log.close()
    want = ["negative_control", "get_continued", "post_denied", "worker_post_denied", "gate_sigkill_watchdog"]
    names = [c["name"] for c in cases]
    passed = names == want and all(c["pass"] for c in cases)
    write_json(root / "selftest.json", {"ts": time.time(), "port": port, "browser_id": bid,
                                        "api_origin": origin, "pass": passed, "cases": cases})
    for c in cases:
        print(f"  {'pass' if c['pass'] else 'FAIL'} {c['name']}")
    missing = [n for n in want if n not in names]
    if missing:
        print(f"  missing cases: {', '.join(missing)}")
    print(f"self-test {'PASS' if passed else 'FAIL'}: {sum(c['pass'] for c in cases)}/{len(want)} cases")
    return 0 if passed else 1
