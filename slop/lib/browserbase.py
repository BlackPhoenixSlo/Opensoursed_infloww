"""The outside world of the served Browserbase login (service/remote_login.py),
on loopback: Browserbase's REST API, the remote Chromium it hands out, and
OnlyFans' website. The relay's own code runs unchanged against it; the relay
hook `POST /__slop/browserbase` (lib/relay.py) points it here.

  Browserbase API  plain HTTP, `/v1/...` in Browserbase's shapes: create a
                   session (one fresh local Chromium per session, own profile,
                   CDP on a loopback port; `connectUrl` is its ws URL), the
                   session's debug URLs (the live view), release (the Chromium
                   is stopped). Every call is recorded.
  Live view        `/live/<sid>`: a page that shows the session's Chromium tab
                   (a CDP screenshot every second). Bypass, declared: not
                   Browserbase's interactive devtools page.
  The Chromium     Playwright's own Chromium, headless, `--host-resolver-rules`
                   maps onlyfans.com to the fake site and every other host to
                   NOTFOUND (nothing leaves the machine); the self-signed
                   certificate is accepted with `--ignore-certificate-errors`.
  OnlyFans' site   HTTPS on loopback, served for onlyfans.com: the login form
                   (rendered by script after load, as OF's is; "Signing in…"
                   for SIGNIN_MS after LOG IN), its 2FA prompt
                   (`input[name="code"]` in its own form with its own VERIFY
                   button, after a stale hidden code input and a decoy form
                   whose "Back to login" is the page's first submit button; a
                   sent code shows "Verifying…" with no field for VERIFY_MS,
                   then a wrong one re-renders the prompt with an error; an
                   `autosubmit` account's field sends its form itself on the
                   last digit), a hidden reCAPTCHA frame (and a hidden
                   `.cf-turnstile`) on every one of those pages, served by the
                   site itself at `/recaptcha/api2/bframe`, `auth_id` set once the right code is in, and
                   /my/chats/, whose page makes one signed /api2/v2/ request and
                   loads OF's signing module (webpack 89668) through
                   `webpackChunkof_vue` with a minimal stand-in for webpack's
                   module call; the login extension's interceptor (injected by
                   the relay, unchanged) captures both. Bypass, declared: the
                   signing material is synthetic (`signing()`): a 2313.js with
                   32 checksum terms and the sign it implies; OF's CDN serves
                   that chunk at `/static/prod/f/<rev>/2313.js` on the API
                   server (the relay's chunk URL is pointed there).
"""
from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def signing(uid: str, rev: str, time_ms: int) -> dict:
    """Synthetic OF signing material: a 2313.js whose 32 checksum terms
    `of_signer.derive_rules_from_chunk` reads, the rules behind it, and the
    sign of GET /api2/v2/users/me at `time_ms` under those rules."""
    if str(ROOT / "service") not in sys.path:
        sys.path.insert(0, str(ROOT / "service"))
    import of_signer

    bases = [10007 + 131 * k for k in range(32)]
    chunk = ("/* 2313.js (slop) */ (self.webpackChunkof_vue=self.webpackChunkof_vue||[]).push([[2313],{802313:"
             "function(e,t,n){t.A=function(W,a){return " + "".join(f"+a[{n}%W[0]](0)" for n in bases) + "}}}]);")
    rules = {"static_param": "slopStaticParam2026", "start": "41999", "end": "6a1b2c3d",
             "checksum_indexes": [n % 40 for n in bases], "checksum_constant": 2026}
    url = "https://onlyfans.com/api2/v2/users/me"
    signed = of_signer.sign(url, uid, rules, time_ms)
    return {"chunk": chunk, "rules": rules, "url": url, "rev": rev, "uid": uid,
            "x_bc": "slop-x-bc-0123456789abcdef", **signed}


def paste_curl(uid: str, rev: str, sess: str = "recaptured") -> str:
    """The Creator's browser's signed /users/me, as DevTools copies it (the login
    extension's x-relay-static-param included), under `signing`'s synthetic
    material (the chunk lib/of_wire.py serves): what the Add creator flow's
    paste-curl step posts to /admin/session/bootstrap."""
    s = signing(uid, rev, int(time.time() * 1000))
    h = {"user-id": uid, "x-bc": s["x_bc"], "x-of-rev": rev, "sign": s["sign"], "time": s["time"],
         "user-agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
         "accept": "application/json, text/plain, */*",
         "x-relay-static-param": s["rules"]["static_param"]}
    return (f"curl '{s['url']}' " + " ".join(f"-H '{k}: {v}'" for k, v in h.items())
            + f" -b 'auth_id={uid}; sess=slop{uid}{sess}'")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


_LOGIN_HTML = """<!doctype html><html><head><title>OnlyFans</title><style>
body{font-family:Helvetica,Arial,sans-serif;background:#f5f7f8;margin:0}
.box{max-width:380px;margin:80px auto;background:#fff;border-radius:8px;padding:28px;box-shadow:0 1px 4px #0002}
h1{color:#00aff0;font-size:26px;margin:0 0 18px}input{display:block;width:100%%;box-sizing:border-box;margin:8px 0;
padding:12px;border:1px solid #ccd;border-radius:6px;font-size:16px}button{width:100%%;padding:12px;border:0;
border-radius:24px;background:#00aff0;color:#fff;font-weight:700;font-size:15px;margin-top:8px}.err{color:#d33}
</style></head><body><div class=box id=app>Loading…</div>
<div style="visibility:hidden;position:absolute;top:-10000px"><iframe title="recaptcha challenge expires in two minutes"
 src="/recaptcha/api2/bframe?k=slop" width=400 height=580></iframe></div><div class=cf-turnstile style=display:none></div>
<script>
const app = document.getElementById("app");
const post = (p, b) => fetch(p, {method: "POST", body: JSON.stringify(b)}).then((r) => r.json());
const later = (ms) => new Promise((r) => setTimeout(r, ms));
function showLogin() {
  app.innerHTML = '<h1>OnlyFans</h1><form id=login><input type=text name=email placeholder=Email>' +
    '<input type=password name=password placeholder=Password><button type=submit>LOG IN</button></form>';
  document.getElementById("login").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const j = await post("/__fake/login", {email: f.email.value, password: f.password.value});
    if (!j.otp) return app.insertAdjacentHTML("beforeend", "<p class=err>Wrong email or password</p>");
    app.innerHTML = "<h1>OnlyFans</h1><p>Signing in…</p>";
    await later(%(signin_ms)d);
    showOtp("", j.autosubmit);
  };
}
function showOtp(err, autosubmit) {
  app.innerHTML = '<h1>Two-step verification</h1><p>Enter the code from your authenticator app.</p>' +
    (err ? '<p class=err>' + err + '</p>' : '') +
    '<input name=code style=display:none>' +  // a stale hidden code input, ahead of the real one
    '<form id=decoy><button type=submit>Back to login</button></form>' +  // the page's first submit button
    '<form id=otp><input name=code autocomplete=one-time-code inputmode=numeric placeholder=Code>' +
    '<button type=submit id=verify>VERIFY</button></form>';
  document.getElementById("decoy").onsubmit = (e) => { e.preventDefault(); post("/__fake/decoy", {}); };
  const form = document.getElementById("otp"), code = form.code;
  // How the code was sent: VERIFY clicked (a real click has detail >= 1), Enter in the field (the browser's
  // implicit submission clicks VERIFY with detail 0), or the field itself on its last digit.
  let via = null;
  code.addEventListener("keydown", (e) => { if (e.key === "Enter") via = "enter"; });
  document.getElementById("verify").addEventListener("click", (e) => { if (e.detail > 0) via = "click"; });
  if (autosubmit) code.addEventListener("input", () => {
    if (/^[0-9]{6,8}$/.test(code.value)) { via = "auto"; form.requestSubmit(); }
  });
  form.onsubmit = async (e) => {
    e.preventDefault();
    const sent = {code: code.value, via: via || "unknown"};
    app.innerHTML = "<h1>Two-step verification</h1><p>Verifying…</p>";  // the field is gone meanwhile
    const [j] = await Promise.all([post("/__fake/otp", sent), later(%(verify_ms)d)]);
    if (j.ok) location.href = "/"; else showOtp("Wrong code. Please try again.", autosubmit);
  };
}
if (document.cookie.includes("auth_id=")) app.innerHTML = "<h1>OnlyFans</h1><p>Home (signed in)</p>";
else setTimeout(showLogin, 400);  // OF renders its form after load
</script></body></html>"""
SIGNIN_MS = 2500  # LOG IN -> the 2FA prompt
VERIFY_MS = 1500  # a sent code -> OF's answer (the prompt again, or signed in)
_RECAPTCHA_HTML = "<!doctype html><html><body>reCAPTCHA challenge (slop, never shown)</body></html>"

_CHATS_HTML = """<!doctype html><html><head><title>Chats | OnlyFans</title></head><body><h1>Chats</h1><script>
const S = %(json)s;
fetch(S.url, {headers: {"user-id": S.uid, "x-bc": S.x_bc, "x-of-rev": S.rev, "sign": S.sign, "time": S.time}})
  .then((r) => r.text()).then(() => {
    // OF's signing module (webpack id 89668, a sha1) arrives in a chunk; webpack calls its factory, then sign() hashes
    // "static_param\\ntime\\npath\\nuser_id". This page stands in for webpack's runtime only.
    const mods = {89668: function (module) { module.exports = function sha1(input) { return "slop-sha1"; }; }};
    (self.webpackChunkof_vue = self.webpackChunkof_vue || []).push([[89668], mods]);
    const m = {exports: {}};
    mods[89668](m, m.exports, null);
    m.exports([S.rules.static_param, S.time, "/api2/v2/users/me", S.uid].join("\\n"));
  });
</script></body></html>"""

_LIVE_HTML = """<!doctype html><html><head><title>Browserbase live view (slop)</title><style>
body{margin:0;background:#111;color:#bbb;font:12px Helvetica}img{width:100%%;display:block}</style></head>
<body><div>Browserbase live view (slop stand-in) &middot; session %(sid)s</div><img id=s src="/live/%(sid)s.png">
<script>setInterval(() => { document.getElementById("s").src = "/live/%(sid)s.png?t=" + Date.now(); }, 1000);</script>
</body></html>"""


class World:
    """Fake Browserbase + fake OnlyFans for one scenario run. `accounts` maps
    each OnlyFans email to its user id; every account has `password` and takes
    the 2FA code `otp`. `chromium`: the browser binary (Playwright's)."""

    def __init__(self, tmp: Path, *, accounts: dict[str, str], otp: str, password: str, chromium: str,
                 autosubmit: frozenset[str] = frozenset(), rev: str = "202610251200-slop"):
        self.tmp = Path(tmp) / "browserbase"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.accounts, self.otp, self.password, self.chromium = accounts, otp, password, chromium
        self.autosubmit = autosubmit  # emails whose 2FA field sends its form itself on the last digit
        now = int(time.time() * 1000)
        self.signs = {uid: signing(uid, rev, now) for uid in accounts.values()}
        self.chunk = next(iter(self.signs.values()))["chunk"]  # one rev, one chunk
        self.calls: list[tuple[str, str]] = []        # Browserbase API: (method, path)
        self.logins: list[dict] = []                  # OF login form posts: {email, password_ok}
        self.otp_tries: list[str] = []                # codes OF's 2FA prompt received, in order
        self.otp_sends: list[dict] = []               # each of them: {uid, code, via: click | enter | auto}
        self.decoys = 0                               # sends of the 2FA page's decoy first form
        self.captcha_frames = 0                       # loads of the hidden reCAPTCHA frame
        self.sessions: dict[str, dict] = {}           # sid -> {proc, cdp, dir, released}
        self._lock = threading.Lock()
        self._servers: list[ThreadingHTTPServer] = []

    # ── lifecycle ──
    def __enter__(self) -> "World":
        cert, key = self.tmp / "of-cert.pem", self.tmp / "of-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(cert), "-days", "2", "-subj", "/CN=onlyfans.com",
                        "-addext", "subjectAltName=DNS:onlyfans.com"], check=True, capture_output=True)
        of = ThreadingHTTPServer(("127.0.0.1", 0), self._of_handler())
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        of.socket = tls.wrap_socket(of.socket, server_side=True)
        api = ThreadingHTTPServer(("127.0.0.1", 0), self._api_handler())
        for s in (of, api):
            s.daemon_threads = True
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self._servers.append(s)
        self.of_port, self.api_port = of.server_address[1], api.server_address[1]
        self.api = f"http://127.0.0.1:{self.api_port}/v1"
        self.chunk_url_tpl = f"http://127.0.0.1:{self.api_port}/static/prod/f/{{rev}}/2313.js"
        return self

    def __exit__(self, *_a) -> None:
        for sid in list(self.sessions):
            self._stop(sid)
        for s in self._servers:
            s.shutdown()
            s.server_close()

    # ── the remote browser ──
    def _launch(self) -> dict:
        sid = f"slopbb{len(self.sessions) + 1:02d}"
        cdp, d = _free_port(), Path(tempfile.mkdtemp(prefix=f"{sid}-", dir=self.tmp))
        proc = subprocess.Popen([
            self.chromium, "--headless=new", f"--remote-debugging-port={cdp}", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={d}", "--no-first-run", "--no-default-browser-check", "--ignore-certificate-errors",
            f"--host-resolver-rules=MAP onlyfans.com 127.0.0.1:{self.of_port}, MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            "--window-size=1280,800", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp}/json/version", timeout=2) as r:
                    ws = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:  # noqa: BLE001
                if time.time() > deadline:
                    proc.kill()
                    raise
                time.sleep(0.1)
        s = {"id": sid, "proc": proc, "cdp": cdp, "dir": d, "ws": ws, "released": False}
        self.sessions[sid] = s
        return s

    def _stop(self, sid: str) -> None:
        s = self.sessions.get(sid)
        if not s or s["proc"].poll() is not None:
            return
        s["proc"].terminate()
        try:
            s["proc"].wait(timeout=10)
        except subprocess.TimeoutExpired:
            s["proc"].kill()
        shutil.rmtree(s["dir"], ignore_errors=True)

    def _screenshot(self, sid: str) -> bytes | None:
        """The session's first tab, as a PNG (CDP Page.captureScreenshot on its own socket)."""
        from websockets.sync.client import connect
        import base64
        s = self.sessions.get(sid)
        if not s or s["proc"].poll() is not None:
            return None
        with urllib.request.urlopen(f"http://127.0.0.1:{s['cdp']}/json/list", timeout=2) as r:
            tabs = [t for t in json.loads(r.read()) if t.get("type") == "page"]
        if not tabs:
            return None
        with connect(tabs[0]["webSocketDebuggerUrl"], max_size=None, open_timeout=3) as ws:
            ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
            while True:
                msg = json.loads(ws.recv(timeout=5))
                if msg.get("id") == 1:
                    return base64.b64decode(msg["result"]["data"])

    # ── HTTP handlers ──
    def _api_handler(self):
        world = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json"
                                                            else body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                parts = path.strip("/").split("/")
                if path.startswith("/v1/"):
                    with world._lock:
                        world.calls.append(("GET", path))
                if path.startswith("/v1/sessions/") and path.endswith("/debug"):
                    sid = parts[2]
                    live = f"http://127.0.0.1:{world.api_port}/live/{sid}"
                    return self._send(200, {"debuggerFullscreenUrl": live, "debuggerUrl": live, "pages": []})
                if path.startswith("/static/prod/f/") and path.endswith("/2313.js"):
                    return self._send(200, world.chunk, "application/javascript")
                if path.startswith("/live/") and path.endswith(".png"):
                    try:
                        png = world._screenshot(parts[1][:-4])
                    except Exception:  # noqa: BLE001 — a tab mid-navigation; the next tick retries
                        png = None
                    return self._send(200, png, "image/png") if png else self._send(404, {"error": "no tab"})
                if path.startswith("/live/"):
                    return self._send(200, _LIVE_HTML % {"sid": parts[1]}, "text/html")
                self._send(404, {"error": "not found"})

            def do_POST(self):  # noqa: N802
                path = self.path.split("?")[0]
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                with world._lock:
                    world.calls.append(("POST", path))
                if self.headers.get("X-BB-API-Key") != "slop-browserbase-key":
                    return self._send(401, {"message": "Invalid API key"})
                if path == "/v1/sessions":
                    if body.get("browserSettings", {}).get("solveCaptchas") is not False:
                        return self._send(400, {"message": "slop: the relay must turn captcha solving off"})
                    s = world._launch()
                    return self._send(201, {"id": s["id"], "connectUrl": s["ws"], "status": "RUNNING"})
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[1] == "sessions" and body.get("status") == "REQUEST_RELEASE":
                    world.sessions.get(parts[2], {})["released"] = True
                    world._stop(parts[2])
                    return self._send(200, {"id": parts[2], "status": "COMPLETED"})
                self._send(404, {"error": "not found"})

        return H

    def _of_handler(self):
        world = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def _send(self, code, body, ctype="text/html", cookie=None):
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(raw)

            def _cookie(self, name):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == name:
                        return v
                return None

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                s = world.signs.get(self._cookie("auth_id") or "")
                if path in ("/", ""):
                    return self._send(200, _LOGIN_HTML % {"signin_ms": SIGNIN_MS, "verify_ms": VERIFY_MS})
                if path.startswith("/recaptcha/"):
                    with world._lock:
                        world.captcha_frames += 1
                    return self._send(200, _RECAPTCHA_HTML)
                if path.startswith("/my/chats") and s:
                    data = {k: s[k] for k in ("url", "uid", "x_bc", "rev", "sign", "time")}
                    data["rules"] = {"static_param": s["rules"]["static_param"]}
                    return self._send(200, _CHATS_HTML % {"json": json.dumps(data)})
                if path == "/api2/v2/users/me" and s:
                    return self._send(200, {"id": int(s["uid"]), "username": f"slop{s['uid']}",
                                            "name": "Slop Creator", "isAuth": True}, "application/json")
                self._send(404 if s else 401, "not found")

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/__fake/login":
                    uid = world.accounts.get(body.get("email") or "")
                    ok = bool(uid) and body.get("password") == world.password
                    with world._lock:
                        world.logins.append({"email": body.get("email"), "password_ok": ok})
                    return self._send(200, {"otp": ok, "autosubmit": body.get("email") in world.autosubmit},
                                      "application/json",
                                      cookie=f"slop_login={uid}; Domain=onlyfans.com; Path=/; Secure" if ok else None)
                if self.path == "/__fake/otp":
                    code, uid = str(body.get("code") or ""), self._cookie("slop_login")
                    with world._lock:
                        world.otp_tries.append(code)
                        world.otp_sends.append({"uid": uid, "code": code, "via": str(body.get("via"))})
                    if uid in world.signs and code == world.otp:
                        return self._send(200, {"ok": True}, "application/json",
                                          cookie=f"auth_id={uid}; Domain=onlyfans.com; Path=/; Secure")
                    return self._send(200, {"ok": False}, "application/json")
                if self.path == "/__fake/decoy":
                    with world._lock:
                        world.decoys += 1
                    return self._send(200, {"ok": True}, "application/json")
                self._send(404, "not found")

        return H
