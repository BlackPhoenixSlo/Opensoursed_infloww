#!/usr/bin/env python3
"""
CDP recorder — attaches to a running Chrome and writes down EVERYTHING.

Run:  ../../venv/bin/python record.py --name sales-view
Stop: touch out/<name>/STOP     (or Ctrl-C)

WHY THIS EXISTS AND A HAR DOES NOT DO IT
----------------------------------------
A .har file records the WebSocket HANDSHAKE and then nothing — the frames
themselves are not part of the HAR spec, and DevTools' "Save all as HAR" drops
them silently. Fansly's notification/typing channel IS a WebSocket, so the
capture we need for `PARITY_SPEC §5` is not expressible as a HAR at all. CDP's
`Network.webSocketFrame{Sent,Received}` is the only way to see those payloads.

So this records three streams side by side:
  ws.jsonl     every frame in both directions, with the handshake + headers
  http.jsonl   request+response pairs, bodies included, for the API hosts
  events.jsonl the raw CDP event log, as a backstop for anything we didn't
               think to parse at capture time

WHY BROWSER-LEVEL AUTO-ATTACH, NOT A PER-PAGE SESSION
-----------------------------------------------------
`Target.setAutoAttach(flatten=True)` from the BROWSER target catches pages,
iframes, dedicated workers AND service workers, and re-arms itself on each new
target. A per-page CDP session (what playwright's new_cdp_session gives you)
sees only that page — and a WS opened from a service worker, which is exactly
where a push channel likes to live, would be invisible. `waitForDebuggerOnStart`
is on so a worker cannot run a single line before Network is enabled; that is
the difference between catching the socket's opening frames and joining midway.

The output contains a LIVE SESSION TOKEN. out/ is gitignored. Do not paste
these files anywhere.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent

# Bodies are fetched only for these hosts. Everything else still gets its
# request/response METADATA recorded — we just don't pull megabytes of image
# bytes back over the debugger socket.
BODY_HOSTS = ("apiv3.fansly.com", "fansly.com", "api.klipy.com")

# Never fetch a body for these — big, binary, and we have the URL anyway.
SKIP_BODY_TYPES = {"Image", "Media", "Font", "Stylesheet", "Manifest"}


class CDP:
    """Minimal flat-protocol CDP client. One socket, many sessions."""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}

    async def send(self, method: str, params: dict | None = None,
                   session_id: str | None = None, timeout: float = 10.0):
        self._id += 1
        mid = self._id
        msg: dict = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout)
        except BaseException:
            self._pending.pop(mid, None)
            raise

    def resolve(self, msg: dict) -> bool:
        """True if `msg` was a command reply (not an event)."""
        mid = msg.get("id")
        if mid is None:
            return False
        fut = self._pending.pop(mid, None)
        if fut and not fut.done():
            if "error" in msg:
                fut.set_exception(RuntimeError(str(msg["error"])[:300]))
            else:
                fut.set_result(msg.get("result", {}))
        return True


def browser_ws_url(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
        return json.load(r)["webSocketDebuggerUrl"]


class Recorder:
    def __init__(self, outdir: Path, verbose: bool):
        self.out = outdir
        self.verbose = verbose
        self.f_ws = (outdir / "ws.jsonl").open("a", buffering=1)
        self.f_http = (outdir / "http.jsonl").open("a", buffering=1)
        self.f_ev = (outdir / "events.jsonl").open("a", buffering=1)
        self.reqs: dict[str, dict] = {}          # (session,requestId) -> request meta
        self.sockets: dict[str, dict] = {}       # (session,requestId) -> ws meta
        self.n_ws = self.n_http = self.n_ev = 0

    def write(self, fh, obj) -> None:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def close(self) -> None:
        for fh in (self.f_ws, self.f_http, self.f_ev):
            try:
                fh.close()
            except Exception:
                pass


async def enable_session(cdp: CDP, sid: str, ttype: str) -> None:
    """Turn on the domains we record, then release the target."""
    async def try_(method, params=None):
        try:
            await cdp.send(method, params, session_id=sid, timeout=5)
        except Exception:
            pass  # not every domain exists on every target type

    # 100MB of buffered bodies; the default (~10MB) evicts a busy page's
    # responses before loadingFinished fires and getResponseBody 404s.
    await try_("Network.enable", {"maxTotalBufferSize": 100_000_000,
                                  "maxResourceBufferSize": 20_000_000})
    if ttype in ("page", "iframe"):
        await try_("Page.enable")
    # Re-arm auto-attach on THIS target so nested workers/iframes are caught too.
    await try_("Target.setAutoAttach",
               {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
    await try_("Runtime.runIfWaitingForDebugger")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--name", default=time.strftime("cap-%Y%m%d-%H%M%S"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    outdir = HERE / "out" / args.name
    outdir.mkdir(parents=True, exist_ok=True)
    stop_file = outdir / "STOP"
    stop_file.unlink(missing_ok=True)

    try:
        url = browser_ws_url(args.port)
    except Exception as e:
        print(f"cannot reach Chrome CDP on :{args.port} ({e}) — run start_chrome.sh first",
              file=sys.stderr)
        return 2

    rec = Recorder(outdir, args.verbose)
    print(f"recording -> {outdir}")
    print(f"stop with: touch {stop_file}")

    async with websockets.connect(url, max_size=200 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        events: asyncio.Queue = asyncio.Queue()
        closed = asyncio.Event()

        async def reader() -> None:
            """Sole owner of ws.recv(). Command replies go to their futures;
            everything else is an event and goes on the queue. This has to run
            as its own task: `await cdp.send(...)` cannot both block on a reply
            and be the thing that reads it."""
            try:
                while True:
                    msg = json.loads(await ws.recv())
                    if not cdp.resolve(msg):
                        await events.put(msg)
            except Exception:
                closed.set()

        reader_task = asyncio.create_task(reader())
        await cdp.send("Target.setAutoAttach",
                       {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        print("attached at browser level — auto-attaching pages + workers")

        last_report = time.time()
        while True:
            if stop_file.exists():
                print("STOP file seen — finishing")
                break
            if closed.is_set() and events.empty():
                print("Chrome closed the debugger socket")
                break
            try:
                msg = await asyncio.wait_for(events.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if time.time() - last_report > 15:
                    print(f"  ... ws-frames={rec.n_ws}  http={rec.n_http}  events={rec.n_ev}")
                    last_report = time.time()
                continue
            try:
                await handle(cdp, rec, msg.get("method", ""), msg.get("params", {}),
                             msg.get("sessionId", ""))
            except Exception as e:
                print(f"  handler error on {msg.get('method')}: {e!r}"[:200])

        reader_task.cancel()

    rec.close()
    summarize(outdir)
    return 0


async def handle(cdp: CDP, rec: Recorder, method: str, params: dict, sid: str) -> None:
    key = f"{sid}:{params.get('requestId', '')}"

    # A native JS dialog BLOCKS the page until it is answered — Page.navigate
    # just hangs, which looks exactly like a slow load. Fansly raises
    # `beforeunload` ("do you really want to leave?") whenever you navigate away
    # from a composer holding unsent text, so this is reachable on any run.
    #
    # Type-aware on purpose. beforeunload/alert are safe to accept. A confirm()
    # or prompt() is NOT: auto-accepting an unknown native confirm could commit
    # a destructive action nobody reviewed. Fansly's own "Are you sure?" dialogs
    # are Angular DOM modals, not native, so a native confirm here would be
    # something unexpected — dismiss it and make noise.
    if method == "Page.javascriptDialogOpening":
        dtype = params.get("type", "")
        accept = dtype in ("beforeunload", "alert")
        try:
            await cdp.send("Page.handleJavaScriptDialog", {"accept": accept},
                           session_id=sid or None, timeout=5)
        except Exception:
            pass
        rec.write(rec.f_ev, {"t": time.time(), "ev": method, "type": dtype,
                             "message": params.get("message"), "accepted": accept})
        rec.n_ev += 1
        print(f"  !! js dialog [{dtype}] {'accepted' if accept else 'DISMISSED'}: "
              f"{str(params.get('message'))[:80]}")
        return

    if method == "Target.attachedToTarget":
        ti = params.get("targetInfo", {})
        new_sid = params.get("sessionId")
        rec.write(rec.f_ev, {"t": time.time(), "ev": method,
                             "type": ti.get("type"), "url": ti.get("url")})
        rec.n_ev += 1
        if new_sid:
            await enable_session(cdp, new_sid, ti.get("type", ""))
            if rec.verbose:
                print(f"  +target {ti.get('type')} {str(ti.get('url'))[:80]}")
        return

    # ---- WebSocket: the whole point of this tool -------------------------
    if method.startswith("Network.webSocket"):
        rec.n_ws += 1
        row = {"t": time.time(), "ev": method, "key": key}
        if method == "Network.webSocketCreated":
            row["url"] = params.get("url")
            rec.sockets[key] = {"url": params.get("url")}
            print(f"  *** WEBSOCKET OPENED: {params.get('url')}")
        elif method == "Network.webSocketWillSendHandshakeRequest":
            row["request"] = params.get("request")
        elif method == "Network.webSocketHandshakeResponseReceived":
            row["response"] = params.get("response")
        elif method in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
            resp = params.get("response", {})
            row["dir"] = "out" if method.endswith("Sent") else "in"
            row["opcode"] = resp.get("opcode")
            row["payload"] = resp.get("payloadData")
            row["url"] = (rec.sockets.get(key) or {}).get("url")
        elif method == "Network.webSocketFrameError":
            row["error"] = params.get("errorMessage")
        rec.write(rec.f_ws, row)
        return

    # ---- HTTP ------------------------------------------------------------
    if method == "Network.requestWillBeSent":
        req = params.get("request", {})
        rec.reqs[key] = {"url": req.get("url"), "method": req.get("method"),
                         "headers": req.get("headers"), "postData": req.get("postData"),
                         "type": params.get("type"), "t": time.time()}
        return

    if method == "Network.responseReceived":
        r = rec.reqs.get(key)
        if r is not None:
            resp = params.get("response", {})
            r["status"] = resp.get("status")
            r["respHeaders"] = resp.get("headers")
            r["mimeType"] = resp.get("mimeType")
            r["type"] = params.get("type") or r.get("type")
        return

    if method == "Network.loadingFinished":
        r = rec.reqs.pop(key, None)
        if r is None:
            return
        url = r.get("url") or ""
        want_body = (any(h in url for h in BODY_HOSTS)
                     and r.get("type") not in SKIP_BODY_TYPES)
        if want_body:
            try:
                res = await cdp.send("Network.getResponseBody",
                                     {"requestId": params.get("requestId")},
                                     session_id=sid or None, timeout=8)
                r["body"] = res.get("body")
                r["bodyBase64"] = res.get("base64Encoded")
            except Exception as e:
                r["bodyError"] = str(e)[:200]
        rec.write(rec.f_http, r)
        rec.n_http += 1
        if rec.verbose and "apiv3.fansly.com" in url:
            print(f"  {r.get('status')} {r.get('method')} {url[:110]}")
        return

    if method in ("Network.loadingFailed",):
        r = rec.reqs.pop(key, None)
        if r:
            r["failed"] = params.get("errorText")
            rec.write(rec.f_http, r)
            rec.n_http += 1


def summarize(outdir: Path) -> None:
    """Print what we caught, so the value of a run is visible immediately."""
    lines = []
    ws_path, http_path = outdir / "ws.jsonl", outdir / "http.jsonl"

    sockets: dict[str, int] = {}
    frames = 0
    for ln in ws_path.read_text().splitlines() if ws_path.exists() else []:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("ev") == "Network.webSocketCreated":
            sockets.setdefault(o.get("url", "?"), 0)
        if "payload" in o:
            frames += 1
            u = o.get("url") or "?"
            sockets[u] = sockets.get(u, 0) + 1

    endpoints: dict[str, int] = {}
    for ln in http_path.read_text().splitlines() if http_path.exists() else []:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        u = (o.get("url") or "").split("?")[0]
        if "apiv3.fansly.com" in u:
            endpoints[f"{o.get('method')} {u.split('apiv3.fansly.com')[-1]}"] = \
                endpoints.get(f"{o.get('method')} {u.split('apiv3.fansly.com')[-1]}", 0) + 1

    lines.append(f"\n=== capture summary: {outdir.name} ===")
    lines.append(f"websockets: {len(sockets)}   frames: {frames}")
    for u, n in sockets.items():
        lines.append(f"   {n:5d}  {u}")
    lines.append(f"\nfansly API endpoints touched: {len(endpoints)}")
    for e, n in sorted(endpoints.items(), key=lambda kv: -kv[1])[:40]:
        lines.append(f"   {n:5d}  {e}")
    text = "\n".join(lines)
    (outdir / "summary.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(0)
