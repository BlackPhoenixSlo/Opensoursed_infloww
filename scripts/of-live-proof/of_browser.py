"""of_browser: the capture browser (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md, "The capture
browser"; ticket 07).

Playwright Chromium signed in as the Proof Creator from the session read at runtime from the run's temp copy: its
cookies, plus every stored localStorage key and `bcTokenSha` = the session's `x-bc`, seeded by an init script before
the first page load (D26: a cookie copy without `bcTokenSha` made OnlyFans answer `isAuth:false` and killed the
stored session). A route on every request asks the Live guard (`Guard`, the Relay's `/__proof/decide`, so one
`decide`, one wire log, one Undo log) before it leaves: a refused one is aborted and recorded, a read or allowed write
is fetched by the route itself (`route.fetch`, no redirect followed) and its completion logged (`/__proof/done`). A
redirect is never followed below the route (Chromium would follow it after `continue_` unseen, a 307 re-sending a
POST): each hop is decided again before it is fetched, and a navigation's redirect becomes a fresh navigation that
comes back through the route. Then, before any step:

  1. the session probe (the Relay's signed, uncached `/users/me`) must answer 200 right after the first load; an
     OnlyFans "Wrong user" (code 301) raises `SessionDead` at once, never retried;
  2. OnlyFans's own `GET /api2/v2/users/me` in this browser must name the run's single Creator (story 54).

Fake mode (FakeOF serves no OnlyFans web app): the fake's origin is decided as the onlyfans.com host, and the
harness serves a loopback drill page there (`DRILL_PATH`, fulfilled in the route, never reaching FakeOF) whose
`fetch` sends one step's request; the route signs each forwarded request with FakeOF's rules, as OnlyFans's web app
signs its own. ASSUMPTION: the harness signing for the page in fake mode is the stand-in for OnlyFans's own client
signing (rung 5: FakeOF refuses unsigned calls); overturned by a FakeOF-served web shell that signs itself.

OAuth hand-off (story 17): while `click_hand_off` runs, a navigation to OnlyFans's page (a new tab) is recorded in
`hand_offs` and aborted, never loaded. In fake mode only the fake origin ever leaves the browser.

Reader and UI undo: the drill page's `send` is the only executor built; OnlyFans-side reads stay the driver's signed
`of_get`, and a UI undo through OnlyFans's own page waits for the first proof whose undo has no Relay route (YAGNI).

Live mode is wired (`fake_sign=None`, no resolver map) but never exercised here: `--of live` stays refused until
ticket 09. ASSUMPTION: OnlyFans accepts forwarded requests sent by `route.fetch` (Playwright's driver, not Chromium's
own network stack) under a Chromium user agent; D26 shows OF kills a session on browser anomalies, so the attended
live run measures this before any capture step (rung 4); overturned by a dead session → forward with
`route.continue_()` and re-decide redirects another way. A `fetch` step is fake-only; live capture steps are clicks on onlyfans.com.

The session's values never leave memory: never printed, never in a wire line (no header is logged), never in a raw
capture (session-bearing headers dropped). `session_leaks` greps the evidence folder and the run's output for them.
`exchanges` (capture-browser.jsonl) keep each response's status, headers and top-level keys; only a write's full
response is held, in `raw`, for its raw capture.

The app browser (prove.py's, `AppBrowser`) lives here too: the Chromium that drives the Relay's app, its Mirror frame
and settle helpers, and the `("dom", ...)` step's snapshot (`_dom_snapshot`, ticket 95).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from capture_record import _AUTH_NAMES
from proof_core import READS, fill_text, log_body, redact_query, redact_url

DRILL_PATH = "/__ofm/capture-drill"
LIVE_START = "https://onlyfans.com/"
ME_PATH = "/api2/v2/users/me"
MIN_SECRET = 8   # shorter values ("1", "true", FakeOF's `soak` cookie) are too common to grep for
IDENTITY_COOKIES = ("auth_id", "user_id")   # the Creator's id: in every report, never a credential
MAX_HOPS = 10
_HOP_DROP = ("content-encoding", "content-length", "transfer-encoding")   # route.fetch hands back the decoded body
VIEWPORT = {"width": 1440, "height": 900}

DRILL_HTML = """<!doctype html><html><head><meta charset="utf-8"><link rel="icon" href="data:,">
<title>Capture browser drill (loopback, fake mode)</title></head>
<body style="font:14px system-ui;margin:24px"><h1>Capture browser drill</h1>
<p>Loopback page the harness serves on FakeOF's origin; each step's request goes through the Live guard.</p>
<p><a id="ofm-hand-off" href="/my/settings/account" target="_blank" rel="noopener">Connect (OAuth hand-off)</a></p>
<pre id="log"></pre>
<script>
window.__ofmSeedAtLoad = localStorage.getItem('bcTokenSha') !== null;
const log = (s) => { document.getElementById('log').textContent += s + '\\n'; };
window.ofmSend = async (method, path, body) => {
  try {
    const r = await fetch(path, {method, headers: body == null ? {} : {'content-type': 'application/json'},
                                 body: body == null ? undefined : JSON.stringify(body)});
    log(method + ' ' + path + ' -> ' + r.status);
    return r.status;
  } catch (e) {
    log(method + ' ' + path + ' -> aborted');
    return 'aborted';
  }
};
fetch('/api2/v2/users/me');   // the web app's own identity read on load
</script></body></html>"""


class CaptureBrowserStop(RuntimeError):
    """The capture browser stops before any step (identity, seed or probe)."""


class SessionDead(CaptureBrowserStop):
    """OnlyFans answered "Wrong user" (code 301): the session is dead; the run stops at once and never retries."""


# ── pure parts ──

def load_session(session_dir) -> dict:
    """The account dir's current session (`latest.json` -> `session_<ts>.json`, service/accounts.py,
    service/session_bootstrap.py `persist_session`): {user_id, x_bc, user_agent, cookies, local_storage}."""
    d = Path(session_dir)
    s = json.loads((d / json.loads((d / "latest.json").read_text())["session"]).read_text())
    h = s.get("headers") or {}
    return {"user_id": str(h.get("user_id") or ""), "x_bc": str(h.get("x_bc") or ""),
            "user_agent": h.get("user_agent"), "cookies": list(s.get("cookies") or []),
            "local_storage": dict(s.get("local_storage") or {})}


def seed_items(session: dict) -> dict:
    """localStorage to seed before the first load: every stored key, then `bcTokenSha` = the session's x-bc (D26)."""
    items = {str(k): v if isinstance(v, str) else json.dumps(v) for k, v in session["local_storage"].items()}
    if session["x_bc"]:
        items["bcTokenSha"] = session["x_bc"]
    return items


def seed_script(items: dict, hosts: tuple) -> str:
    """An init script (it runs before any page script) setting each key on the OnlyFans origin only, when absent."""
    return ("(() => { const h = location.hostname; "
            f"if (!{json.dumps(list(hosts))}.some(x => h === x || h.endsWith('.' + x))) return; "
            f"const items = {json.dumps(items)}; "
            "for (const [k, v] of Object.entries(items)) { try { if (localStorage.getItem(k) === null) "
            "localStorage.setItem(k, v); } catch (e) {} } })();")


def cookie_rows(rows, fake_origin: str | None) -> list:
    """Playwright `add_cookies` rows from the session's cookie rows; in fake mode bound to the fake's origin."""
    out = []
    for r in rows:
        if not r.get("name"):
            continue
        if fake_origin:
            out.append({"name": r["name"], "value": str(r.get("value", "")), "url": fake_origin})
            continue
        c = {k: r[k] for k in ("name", "value", "domain", "path", "expires", "httpOnly", "secure") if k in r}
        if r.get("sameSite") in ("Strict", "Lax", "None"):
            c["sameSite"] = r["sameSite"]
        if isinstance(c.get("expires"), (int, float)) and c["expires"] < 0:
            del c["expires"]
        c.setdefault("path", "/")
        out.append(c)
    return out


def session_secrets(session: dict) -> list:
    """The session's credential values to grep for: cookie values, x-bc and stored localStorage values. Identity
    values (the `auth_id` / `user_id` cookies, the session's user id: the Creator's id) are no credential and are in
    every report, so they are left out."""
    vals = [str(c.get("value") or "") for c in session["cookies"] if c.get("name") not in IDENTITY_COOKIES]
    vals += [session["x_bc"]] + [v if isinstance(v, str) else json.dumps(v) for v in session["local_storage"].values()]
    return sorted({v for v in vals if len(v) >= MIN_SECRET} - {session["user_id"]})


def session_leaks(texts: dict, secrets) -> list:
    """Each named text (an evidence file, the run's output) holding a session value: named, the value never shown."""
    return [f"{name}: holds a session value" for name, text in texts.items()
            if any(s in text for s in secrets)]


def evidence_texts(folder: Path) -> dict:
    return {str(p.relative_to(folder)): p.read_bytes().decode("utf-8", "replace")
            for p in sorted(folder.rglob("*")) if p.is_file()}


def of_error_code(body):
    """OnlyFans's error code in an answer: its own `{"error": {"code"}}` (or a top-level `code`), or the same inside
    the Relay's 502 `{"detail": {"upstream_body": "<OnlyFans's text>"}}` (service/server.py `_proxy`); else None."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and "upstream_body" in detail:
        body = log_body(detail["upstream_body"]) if isinstance(detail["upstream_body"], str) else detail["upstream_body"]
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    return err.get("code") if isinstance(err, dict) else body.get("code")


def probe_verdict(status, body, creator: str) -> tuple:
    """The post-first-load session probe: ("ok", ""), ("dead", why) on a non-200 answer carrying OnlyFans's "Wrong
    user" (error code 301), or ("fail", why) on any other answer."""
    text = body if isinstance(body, str) else json.dumps(body, default=str)
    if status != 200 and of_error_code(body) == 301:
        return "dead", f'OnlyFans answered "Wrong user" (code 301) to the signed /users/me probe ({status})'
    if status != 200:
        return "fail", f"session probe answered {status}: {text[:200]}"
    me = body if isinstance(body, dict) else {}
    if str(me.get("id")) != str(creator):
        return "fail", f"session probe named {me.get('id')!r}, not the run's Creator {creator}"
    return "ok", ""


def identity_problem(me, creator: str) -> str | None:
    """Story 54: OnlyFans's own /users/me in the capture browser must name the run's single Creator."""
    if me is None:
        return "the capture browser saw no OnlyFans GET /api2/v2/users/me answer"
    got = me.get("id") if isinstance(me, dict) else None
    return None if str(got) == str(creator) else f"OnlyFans's /users/me in the capture browser named {got!r}, " \
                                                 f"not the run's Creator {creator}"


def fetch_problems(method: str, path: str, expect: str, status, lines) -> list:
    """One `fetch` step's outcome against its expectation. `lines`: the step's wire lines from the capture browser.
    "sent": forwarded and answered; any other expect is the Live guard class that must have aborted it."""
    what = f"{method.upper()} {path}"
    refused = [e for e in lines if e.get("verdict") == "refused"]
    if expect == "sent":
        if status == "aborted" or refused or not lines:
            why = "; ".join(f"{e.get('class')}: {e.get('reason', '')}" for e in refused) or f"status {status}"
            return [f"capture browser: {what} was to be sent, not aborted ({why})"]
        return []
    if status != "aborted":
        return [f"capture browser: {what} left the browser ({status}); expected aborted as {expect}"]
    if not any(e.get("class") == expect for e in refused):
        got = [e.get("class") for e in lines]
        return [f"capture browser: {what} aborted without a {expect} wire line (lines: {got})"]
    return []


def hand_off_problems(hand_offs, window) -> list:
    """Story 17: an OAuth hand-off proof's click opened OnlyFans's page, recorded and aborted, and nothing wrote."""
    out = [] if hand_offs else ["OAuth hand-off: no navigation to OnlyFans's page was recorded and aborted"]
    return out + [f"OAuth hand-off sent a write: {e['method']} {e['path']}" for e in window
                  if e["method"] not in READS and e.get("verdict") != "refused"]


def _plain_headers(h: dict) -> dict:
    """Headers kept in a raw capture: every one but cookies and auth/session headers (capture_record's names)."""
    return {k: v for k, v in h.items() if k.lower() not in _AUTH_NAMES}


# ── the guard over the Relay ──

class RelayGuard:
    """The Live guard as the capture browser's route calls it: the Relay's `/__proof/decide` and `/__proof/done`
    (relay_live.py), through `call(method, route, data) -> (status, body)` (prove.py `_relay_client`)."""

    def __init__(self, call):
        self.call = call

    def intent(self, method: str, url: str, body) -> dict:
        status, raw = self.call("POST", "/__proof/decide", {"method": method, "url": url, "body": body})
        if status != 200:
            # fail closed: the request is aborted when the guard cannot answer
            return {"seq": None, "verdict": "refused", "class": "guard_error", "reason": f"decide answered {status}",
                    "capture": ""}
        return json.loads(raw)

    def done(self, seq, status, of_id=None) -> None:
        if seq is not None:
            self.call("POST", "/__proof/done", {"seq": seq, "status": status, "of_id": of_id})


# ── the browser ──

class CaptureBrowser:
    """One Chromium context signed in as the Proof Creator. `open()` loads the first page, probes the session and
    checks the identity; `send()` plays one fake-mode `fetch` step; `exchanges` holds every request the route saw."""

    def __init__(self, pw, session: dict, guard, *, creator: str, fake_origin: str | None = None,
                 fake_sign=None, probe=None, launch_args=()):
        self.session, self.guard, self.creator, self.probe = session, guard, str(creator), probe
        self.fake_origin, self.fake_sign = fake_origin, fake_sign
        self.fake_netloc = urlsplit(fake_origin).netloc if fake_origin else None
        self.hosts = ("onlyfans.com",) + ((urlsplit(fake_origin).hostname,) if fake_origin else ())
        self.start = f"{fake_origin}{DRILL_PATH}" if fake_origin else LIVE_START
        self.exchanges: list = []
        self.raw: dict = {}         # wire seq -> a forwarded write's full response, for its raw capture only
        self.hand_offs: list = []   # aborted navigations to OnlyFans's page while `hand_off` is set
        self.hand_off = False
        self.me = None
        self.browser = pw.chromium.launch(args=list(launch_args))
        self.ctx = self.browser.new_context(viewport=VIEWPORT, service_workers="block", timezone_id="UTC",
                                            locale="en-US", **({"user_agent": session["user_agent"]}
                                                               if session.get("user_agent") else {}))
        # D26: localStorage (bcTokenSha = x-bc, every stored key) before the first page load, then the cookies
        self.ctx.add_init_script(seed_script(seed_items(session), self.hosts))
        rows = cookie_rows(session["cookies"], fake_origin)
        if rows:
            self.ctx.add_cookies(rows)
        self.ctx.route("**/*", self._route)
        self.ctx.route_web_socket("**/*", self._ws)
        self.page = None

    # route ──
    def _of(self, netloc: str, host: str) -> bool:
        return netloc == self.fake_netloc or host == "onlyfans.com" or host.endswith(".onlyfans.com")

    def _abort(self, route, url: str, cls: str, **kw):
        x = {"method": kw.pop("method", "GET"), "url": redact_url(url)[:300], "class": cls, "aborted": True, **kw}
        self.exchanges.append(x)
        route.abort("blockedbyclient")
        return x

    def _route(self, route, request):
        u = urlsplit(request.url)
        if u.scheme in ("data", "blob"):
            return route.continue_()
        if self.fake_origin and f"{u.scheme}://{u.netloc}" == self.fake_origin and u.path == DRILL_PATH:
            return route.fulfill(status=200, content_type="text/html", body=DRILL_HTML)   # the harness's page
        if self.hand_off and request.is_navigation_request() and self._of(u.netloc, u.hostname or ""):
            # story 17: an OAuth hand-off's new tab on OnlyFans's page is recorded and aborted, never loaded
            self.hand_offs.append(self._abort(route, request.url, "oauth", method=request.method, path=u.path,
                                              navigation=True))
            return None
        body = log_body(request.post_data_buffer)   # a binary upload: logged by size, never decoded
        url, method, post = request.url, request.method, request.post_data_buffer
        for _ in range(MAX_HOPS):
            u = urlsplit(url)
            if self.fake_origin and u.netloc != self.fake_netloc:
                # fake mode: nothing but the fake origin ever leaves, whatever the guard would say
                return self._abort(route, url, "offhost", method=method)
            headers = None   # fake mode: signed as OnlyFans's web app signs its own calls (FakeOF's rules)
            if self.fake_sign:
                headers = {**request.headers, **self.fake_sign(u.path + (f"?{u.query}" if u.query else ""))}
            v = self.guard.intent(method, url, body)
            ex = {"seq": v.get("seq"), "method": method, "url": redact_url(url), "path": u.path,
                  "query": redact_query(u.query),
                  "headers": _plain_headers(headers or request.headers), "body": body, "verdict": v["verdict"],
                  "class": v["class"], "reason": v.get("reason", ""), "aborted": v["verdict"] == "refused",
                  "capture": v.get("capture", ""), "status": None, "response": None}
            self.exchanges.append(ex)
            if ex["aborted"]:
                return route.abort("blockedbyclient")
            try:
                resp = route.fetch(url=url, method=method, headers=headers, post_data=post, max_redirects=0)
            except Exception as e:  # noqa: BLE001  (no reply: a write's row stays pending, never retried)
                ex["status"] = f"failed: {type(e).__name__}"
                self.guard.done(ex["seq"], ex["status"])
                return route.abort("failed")
            self._done(ex, resp)
            loc = resp.headers.get("location")
            if not (300 <= resp.status < 400 and loc):
                return route.fulfill(response=resp, headers={k: v for k, v in resp.headers.items()
                                                             if k.lower() not in _HOP_DROP})
            url = urljoin(url, loc)
            if request.is_navigation_request():   # a fresh navigation: its request comes back through this route
                return route.fulfill(status=200, content_type="text/html",
                                     body=f"<script>location.replace({json.dumps(url).replace('<', chr(92) + 'u003c')})</script>")
            if resp.status == 303 or (resp.status in (301, 302) and method == "POST"):   # fetch spec: becomes a GET
                method, post, body = "GET", None, None
        return self._abort(route, url, "redirect_loop", method=method)

    def _done(self, ex: dict, resp) -> None:
        """One forwarded hop's answer: its wire line completed (and an allowed write's OnlyFans id), the exchange
        keeping the response's keys only; OnlyFans's own /users/me answer is the identity check's."""
        ex["status"] = resp.status
        try:
            body = log_body(resp.text())
        except Exception:  # noqa: BLE001  (a body that is not text: status only)
            body = None
        ex["response"] = {"status": resp.status, "headers": _plain_headers(resp.headers),
                          "keys": sorted(body) if isinstance(body, dict) else None}
        of_id = None
        if ex["method"] not in READS:
            self.raw[ex["seq"]] = {"status": resp.status, "headers": ex["response"]["headers"], "body": body}
            if isinstance(body, dict) and body.get("id") is not None:
                of_id = str(body["id"])
        if ex["method"] == "GET" and ex["path"] == ME_PATH and resp.status == 200 and isinstance(body, dict):
            self.me = body
        self.guard.done(ex["seq"], resp.status, of_id)

    def _ws(self, ws):
        u = urlsplit(ws.url)
        if self.fake_origin and u.netloc != self.fake_netloc:
            self.exchanges.append({"method": "GET", "url": redact_url(ws.url)[:300], "class": "offhost",
                                   "aborted": True})
            return ws.close()
        v = self.guard.intent("GET", ws.url, None)   # another host is refused (host) and logged by the guard
        if v["verdict"] == "refused":
            return ws.close()
        self.guard.done(v.get("seq"), 101)
        ws.connect_to_server()

    # steps ──
    def open(self) -> dict:
        """First load, then the seed check, the session probe and the identity check; raises before any step."""
        self.page = self.ctx.new_page()
        self.page.goto(self.start, wait_until="load", timeout=120_000)
        seeded = self.page.evaluate("(k) => localStorage.getItem('bcTokenSha') === k", self.session["x_bc"]) \
            if self.session["x_bc"] else False
        if not seeded:
            raise CaptureBrowserStop("localStorage bcTokenSha was not the session's x-bc after the first load")
        out = {"seeded": True}
        if self.probe is not None:
            status, body = self.probe()   # once: a dead session is never probed again
            verdict, why = probe_verdict(status, body, self.creator)
            out["probe"] = status
            if verdict == "dead":
                raise SessionDead(why)
            if verdict != "ok":
                raise CaptureBrowserStop(why)
        end = time.time() + 30
        while self.me is None and time.time() < end:
            self.page.wait_for_timeout(100)
        why = identity_problem(self.me, self.creator)
        if why:
            raise CaptureBrowserStop(why)
        out["me"] = str(self.me.get("id"))
        return out

    def send(self, method: str, path: str, body=None):
        """One fake-mode `fetch` step from the drill page: the request's status, or "aborted"."""
        if not self.fake_origin:
            raise RuntimeError("a fetch step runs only on the fake-mode drill page; live capture plays clicks")
        return self.page.evaluate("([m, p, b]) => window.ofmSend(m, p, b)", [method.upper(), path, body])

    def click_hand_off(self, selector: str, timeout_s: float = 30) -> int:
        """Click an OAuth hand-off on the drill page; returns how many navigations were recorded and aborted."""
        n0, self.hand_off = len(self.hand_offs), True
        try:
            self.page.locator(selector).first.click(timeout=30_000)
            end = time.time() + timeout_s
            while len(self.hand_offs) == n0 and time.time() < end:
                self.page.wait_for_timeout(100)
            self.page.wait_for_timeout(300)
        finally:
            self.hand_off = False
            for pg in self.ctx.pages:
                if pg is not self.page:
                    pg.close()
        return len(self.hand_offs) - n0

    def offhost(self) -> list:
        return [x for x in self.exchanges if x.get("class") == "offhost"]

    def close(self) -> None:
        self.browser.close()


# ── the app browser (prove.py): loopback only; the Mirror frames it drives and what it reads off them ──

LAUNCH_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"]
FAKE_MEDIA_ARGS = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


class AppBrowser:
    """The app browser (prove.py): loopback only. Every other origin (HTTP or WebSocket) is aborted and recorded."""

    def __init__(self, pw, stack, evidence: Path):   # stack: prove.Stack
        self.allowed = (stack.app, stack.relay)
        self.route_hook = stack.app_route   # ticket 97: an app-side fault's route hook (fake_layer.AppFault.hook) or None
        self.offhost_log = evidence / "app-offhost.jsonl"
        self.offhost_log.touch()
        # Record video and Record voice record from Chromium's synthetic camera and microphone, granted without a
        # prompt (headless has no device; Phase 2 ticket 131's Record proofs).
        self.browser = pw.chromium.launch(args=[*LAUNCH_ARGS, *FAKE_MEDIA_ARGS])
        self.ctx = self._context()
        self.errors: list | None = None
        self.writes: list | None = None
        self.responses: list | None = None   # every app-browser answer in a proof's window, for `Proof.check`
        self.ctx.on("response", self._response)
        self.ctx.on("request", self._request)

    def _context(self, **extra):
        ctx = self.browser.new_context(viewport=VIEWPORT, service_workers="block", timezone_id="UTC",
                                       locale="en-US", permissions=["camera", "microphone"], **extra)
        ctx.route("**/*", self._route)
        ctx.route_web_socket("**/*", self._ws)
        return ctx

    def fresh_context(self):
        """Ticket 67: a context with this one's cookies and localStorage (sign-in, scope) and the same loopback guard,
        but none of its IndexedDB, so the app shows OnlyFans as it is now, not its cached React Query snapshot (a
        change the app did not make itself shows only after that snapshot goes stale). The caller closes it."""
        return self._context(storage_state=self.ctx.storage_state())

    def _offhost(self, url: str, via: str) -> None:
        with open(self.offhost_log, "a") as f:
            f.write(json.dumps({"t": time.time(), "via": via, "url": redact_url(url)[:300]}) + "\n")

    def _route(self, route, request):
        u = urlsplit(request.url)
        if u.scheme in ("data", "blob"):
            return route.continue_()
        if f"{u.scheme}://{u.netloc}" not in self.allowed:
            self._offhost(request.url, "http")
            return route.abort()
        if self.route_hook and self.route_hook(route, request):
            return None
        return route.continue_()

    def _ws(self, ws):
        u = urlsplit(ws.url)
        if f"{'https' if u.scheme == 'wss' else 'http'}://{u.netloc}" not in self.allowed:
            self._offhost(ws.url, "websocket")
            return ws.close()
        ws.connect_to_server()

    def _response(self, resp):
        if self.errors is None:
            return
        self.responses.append({"url": resp.url, "status": resp.status, "cache": resp.headers.get("x-img-cache")})
        path = urlsplit(resp.url).path
        if path.startswith("/api/") and resp.status >= 400:
            self.errors.append((resp.request.method, path, resp.status))

    def _request(self, req):
        path = urlsplit(req.url).path
        if self.writes is not None and req.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/"):
            self.writes.append((req.method, path, req.headers.get("x-account-id")))

    def offhost(self) -> list:
        return [json.loads(x) for x in self.offhost_log.read_text().splitlines() if x.strip()]


def dedupe_media(media: list) -> list:
    """Ticket 97: `media` with each vault id once (a claim object kept as is), in order."""
    seen, out = set(), []
    for m in media:
        if isinstance(m, int):
            if m in seen:
                continue
            seen.add(m)
        out.append(m)
    return out


def _mirror_frame(page, proof_page: str, timeout_s: float = 90):
    want = f"/of-mirror/pages/{proof_page}.html"
    end = time.time() + timeout_s
    while time.time() < end:
        for fr in page.frames:
            if urlsplit(fr.url).path == want:
                return fr
        page.wait_for_timeout(250)
    raise RuntimeError(f"no Mirror frame {want} on {page.url}")


def _wait_text(fr, sel: str, want: str, marker: str, proof_fan) -> None:
    """Wait for `want` in `sel`'s text, `{marker}` / `{fan}` filled (`fill_text`); a `{fan}` with no Proof fan is
    refused (it would wait for any text)."""
    if "{fan}" in want and not proof_fan:
        raise ValueError(f"wait for {want!r}: no Proof fan to fill {{fan}}")
    fr.wait_for_function("([s, w]) => (document.querySelector(s)?.textContent || '').includes(w)",
                         arg=[sel, fill_text(want, marker, proof_fan)], polling=50, timeout=30_000)


class _Parked(Exception):
    """A proof parked before it wrote anything (ticket 96: its `precheck` on the before read; ticket 100: a ("call", fn)
    step's `park`): the reason is kept."""


def _call_ctx(page, fr, shown, stack, call, creator, marker, proof_fan, shots, res, proof_id, extra=None) -> dict:
    """Ticket 100: what a ("call", fn) trigger step is given. `call(method, route, data=None)` is the Relay as the
    scoped Creator -> (status, body bytes); `reload()` reopens the shown Mirror page and returns its frame;
    `read_id(key, of_id, source)` registers an id read off a created one with the Relay (`/__proof/read-id`, ticket
    131: the Relay reads it itself) -> problems; `park(why)` parks the proof before it writes anything; `shot(name)`
    keeps a screenshot as evidence; `of_get` is the driver's signed OnlyFans-side read; `of` the stack's mode (live |
    fake, never defaulted); `record` is kept in the result. `extra`: the driver's own (ticket 99: `settle()` undoes
    and closes the rows written so far, so a proof goes on in phases; `fan_visible_spent()` the proof ids of every
    fan-visible attempt in the Undo log)."""
    def reload():
        page.goto(f"{stack.app}/of-manager/{shown.replace('/index', '')}", wait_until="load", timeout=180_000)
        return _mirror_frame(page, shown)

    def park(why):
        raise _Parked(why)

    def shot(name):
        page.screenshot(path=str(shots / f"{name}.png"))
        res["screens"].append(f"{proof_id}/{name}.png")

    def read_id(key, of_id, source):
        status, _ = call("POST", "/__proof/read-id", {"key": key, "of_id": str(of_id), "source": str(source)},
                         account=creator)
        return [] if status == 200 else [f"the Relay refused read id {key}={of_id}: {status}"]

    return {"call": lambda method, route, data=None: call(method, route, data, account=creator), "page": page,
            "frame": fr, "reload": reload, "read_id": read_id, "park": park, "shot": shot, "marker": marker,
            "proof_fan": proof_fan, "of_get": stack.of_get, "of": stack.of, "record": res.setdefault("record", {}),
            **(extra or {})}


# ticket 95: `("dom", container, items, fields)`. `fields` is ((key, sub), ...): `sub` a selector inside the item
# ("" the item itself) whose text is read, `sub@attr` its attribute, `sub@*` how many match. Hidden items (the
# generator's examples, display:none) are skipped; each item also lists its <img>s. Shown items come in document
# order (ticket 96 reads an order from them).
_DOM_JS = """([items, fields]) => [...document.querySelectorAll(items)].filter((e) => e.getClientRects().length)
  .map((e) => {
    const out = {};
    for (const [key, sub] of fields) {
      const at = sub.lastIndexOf("@");
      const sel = at < 0 ? sub : sub.slice(0, at), attr = at < 0 ? "" : sub.slice(at + 1);
      if (attr === "*") { out[key] = sel ? e.querySelectorAll(sel).length : 1; continue; }
      const el = sel ? e.querySelector(sel) : e;
      out[key] = !el ? null : attr ? el.getAttribute(attr) : (el.textContent || "").replace(/\\s+/g, " ").trim();
    }
    out._imgs = [...(e.matches("img") ? [e] : []), ...e.querySelectorAll("img")]
      .map((i) => ({src: i.currentSrc || i.src, complete: i.complete, width: i.naturalWidth}));
    return out;
  })"""


def _dom_snapshot(page, fr, shown: str, container: str, items: str, fields) -> dict:
    """The container visible, up to 15 s for the page's reads to land (ticket 96: a list a read reorders), then up to
    15 s for a first shown item (none: an empty list, the check's to judge) and up to 15 s for its pictures to settle;
    then every shown item's `fields`."""
    fr.locator(container).first.wait_for(state="visible", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001  (an open event stream keeps the network busy)
        pass
    for js in ("s => [...document.querySelectorAll(s)].some((e) => e.getClientRects().length)",
               "s => [...document.querySelectorAll(s)].every((e) => [...e.querySelectorAll('img')]"
               ".every((i) => i.complete))"):
        try:
            fr.wait_for_function(js, arg=items, polling=100, timeout=15_000)
        except Exception:  # noqa: BLE001  (an empty list or a picture that never loads is the check's to report)
            pass
    return {"page": shown, "items_selector": items,
            "items": fr.evaluate(_DOM_JS, [items, [list(f) for f in fields]])}
