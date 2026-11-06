"""OnlyFans' media CDN at its wire, for the chat media flow (scenarios/2026-11-02-img-chat-media.py): lib/relay.py
loads this part (`OF` joins `_OfflineOF`'s bases; `wire` runs at the end of its `_wire`).

Inert unless the run wrote `$DEMO_SHOTS_TMP/of-cdn.json` (the scenario does, through `arm_run` below) AND then armed
it: without the file `POST /__slop/img/arm` is a 409 that changes nothing, and nothing else here runs, so every
other scenario's relay is untouched (`OF.http` / `OF.timeout_s` re-raise the client build error, as
`_OfflineOF.__getattr__` did before this part existed: unarmed, nothing here can reach curl).

  arm_run(http, tmp, assets, latency_s, pictures=False)  (harness side) writes `of-cdn.json` {latency_s, pictures,
       assets: {"host/path": size}}, POSTs the arm hook and answers its body. `pictures`: every asset's bytes are a
       real picture (`picture_bytes`, a small PNG; size ignored) so a browser draws it and vault_stills keeps it.
  POST /__slop/img/arm   (loopback; 409 without the file or under SLOP_LIVE=1)
       1. The fake CDN: a loopback ThreadingHTTPServer in the relay process (a thread per request). Per request,
          after `latency_s`: a seeded asset's bytes (`asset_bytes`, deterministic per host+path) with
          Content-Length; on a signed host (any but public.onlyfans.com) a URL without Policy + Signature +
          Key-Pair-Id, whose Policy's `exp` is past, or whose Policy names an `AWS:SourceIp` other than the
          request's egress, is 403 AccessDenied (CloudFront's answer; the Policy is CloudFront's custom one,
          `policy_b64` / `policy_exp` / `policy_ip`); an unseeded path 404. A `.mp4` key's bytes are a real
          12 s clip (`video_bytes`, ffmpeg testsrc 64x64 at 1 fps, size ignored), so /img/scrub's ffmpeg slices it.
          A `Range: bytes=` header (one spec) gets that slice: 206 + Content-Range (416 past the end).
       2. curl_cffi at its wire: `relay._guard_curl_cffi()` first (curl_cffi goes past relay_guarded's socket guard;
          it refuses every non-loopback host from now on), then `curl_cffi.requests.Session.request` wrapped so a
          URL on a seeded CDN host (the assets' hosts) is sent to the fake instead (path + query kept, the original
          host in `X-Slop-Cdn-Host`, the egress in `X-Slop-Egress`: "127.0.0.1:<port>" of the proxy the call
          names (its `proxies`, else the session's), else "direct"; and the session's cookies that curl would
          have sent to that host as a `Cookie` header, since curl matches its jar against the loopback host
          otherwise). Every other URL is unchanged.
          Both `/img` lanes go through it: the signed hosts on the Creator's `client.http` (this part's
          `OF.http`), the direct ones on `img_api._DIRECT_HTTP` (a bare curl_cffi Session, measured in source).
       3. `img_api._IMG_CACHE_DIR` (a module global read at call time) re-pointed to `$DEMO_SHOTS_TMP/img-cache`:
          the default `/tmp/of-relay-img-cache` is the laptop's shared dir, never read or written here.
       Answers {port, cache_dir}.
  GET /__slop/img/calls?since=N&until=M  {calls}: every request the fake got, in arrival order, [N:M].
  GET /__slop/img/stats                  {n}: calls so far.

Record per call: i, t (arrival, epoch s), key ("host/path"), host, path, range, egress, cookie (a Cookie header came),
auth_id (its auth_id cookie), of_headers (user-id / x-bc / app-token / sign sent), ua, status, inflight (requests
in the fake at arrival, this one included: its max over calls is the fake's peak concurrency), bytes. A call
leaves `inflight` just before its last byte is written (a non-200: before its status line), so a relay slot can
never be released while the fake still counts its call.

`OF` (joins `_OfflineOF`): a Creator with no session in a slop run gets, once armed, `http` = one curl_cffi Session
per Creator (impersonate as of_client, the cookies an OFClient replays: synthetic `auth_id` = the Creator's id and
`sess`, on `.onlyfans.com`; and `creator_headers(id)`, synthetic stand-ins for the account's pinned User-Agent,
user-id, x-bc and app-token, so a check can tell an account's request from `_DIRECT_HTTP`'s) and `timeout_s` =
of_client.DEFAULT_TIMEOUT_S, so `/img`'s signed-host path runs `_get_client(request).http` unchanged.

Bypasses (declared): the CDN is a loopback fake inside the relay process (shares its GIL); the bytes are seeded
noise in a 1x1 JPEG's comment segments (`asset_bytes`: the browser decodes one grey pixel, the relay nothing);
`latency_s` per request is a guess at OF's CDN through a proxy;
the Signature is never verified, only the Policy's expiry and SourceIp; the egress is the proxy curl was told to
use (a header the wrap adds), not the peer address the fake sees; `pictures` serves a PNG as image/jpeg (browsers
sniff); one-spec Range answered as CloudFront does (206 + Content-Range, 416 past the end), no CDN 5xx; the session cookies and headers are synthetic (session-level here, where
of_client sets them per request).
"""

import base64
import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CFG_FILE = "of-cdn.json"  # in $DEMO_SHOTS_TMP
ORIG_HOST = "X-Slop-Cdn-Host"
EGRESS = "X-Slop-Egress"
ACCOUNT_HEADERS = ("user-id", "x-bc", "app-token")  # the OF account headers `creator_headers` sets
OF_HEADERS = (*ACCOUNT_HEADERS, "sign")  # recorded per call (`of_headers`)
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"assets": {}, "hosts": set(), "latency_s": 0.0, "pictures": False}
_state = {"port": None, "armed": False, "inflight": 0}
_bytes: dict[str, bytes] = {}
_sessions: dict[str, object] = {}
_relay = None  # lib/relay.py's namespace (wire)


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


# A 1x1 grey JPEG (PIL, quality 50): asset_bytes pads it with COM segments, so a browser decodes the whole body.
_JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBk"
    "eFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAABAAED"
    "ASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKB"
    "kaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQF"
    "BgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX"
    "2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooA/9k=")


def asset_bytes(key: str, size: int) -> bytes:
    """The CDN's bytes for asset `key` ("host/path"): exactly `size`, deterministic (harness and fake agree): a 1x1
    JPEG whose COM segments carry seeded noise (bare noise below its size). Not bare noise: Chromium cancels an
    image whose first chunk will not decode, so over a capped line only ~1.5 KB of it crossed (measured 2026-11-05:
    12 noise tiles of 100 KB in 435 ms at 1.6 Mbit/s, these in 6285 ms)."""
    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    pad = size - len(_JPEG_1PX)
    if pad < 4:
        return rng.randbytes(size)
    out = [b"\xff\xd8"]
    while pad:
        n = min(pad, 65_537)  # a COM segment: FF FE, a 2-byte length (itself included, <= 65535), then the data
        if pad - n in (1, 2, 3):
            n = pad - 4
        out.append(b"\xff\xfe" + (n - 2).to_bytes(2, "big") + rng.randbytes(n - 4))
        pad -= n
    out.append(_JPEG_1PX[2:])
    return b"".join(out)


def picture_bytes(key: str) -> bytes:
    """A real picture for asset `key`: a 16x16 PNG in one colour from the key (harness and fake agree)."""
    import struct
    import zlib
    rgb = hashlib.sha256(key.encode()).digest()[:3]
    raw = b"".join(b"\x00" + rgb * 16 for _ in range(16))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def signed(host: str) -> bool:
    """OF's signed hosts: every seeded media host but the unsigned one (seed/chat_media.py's DIRECT_HOST, one of
    img_api._DIRECT_CDN_HOST's)."""
    return host != "public.onlyfans.com"


def creator_headers(account_id: str) -> dict[str, str]:
    """The Creator's synthetic account headers on its fake session (module docstring: `OF`)."""
    vals = (str(account_id), f"slop-bc-{account_id}", "slop-app-token")
    return {"User-Agent": f"SlopCreatorUA/{account_id}", **dict(zip(ACCOUNT_HEADERS, vals, strict=True))}


async def arm_run(http, tmp: Path, assets: dict, latency_s: float, pictures: bool = False) -> dict:
    """Harness side: `assets` {"host/path": {size, ...}} into the config file, then the arm hook."""
    (Path(tmp) / CFG_FILE).write_text(json.dumps({
        "latency_s": latency_s, "pictures": pictures, "assets": {k: a["size"] for k, a in assets.items()}}))
    r = await http.post("/__slop/img/arm")
    if r.status_code != 200:
        raise RuntimeError(f"slop: img arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


class OF:
    """`_OfflineOF`'s media client: armed, the Creator's curl_cffi session; unarmed, the build error as before."""

    @property
    def http(self):
        if not _state["armed"]:
            raise self._err
        return _session(self.account_id)

    @property
    def timeout_s(self):
        if not _state["armed"]:
            raise self._err
        from of_client import DEFAULT_TIMEOUT_S
        return DEFAULT_TIMEOUT_S


def _session(account_id: str):
    with _lock:
        s = _sessions.get(account_id)
        if s is None:
            from curl_cffi import requests as cffi
            from of_client import IMPERSONATE
            s = cffi.Session(impersonate=IMPERSONATE, headers=creator_headers(account_id))
            s.cookies.set("auth_id", str(account_id), domain=".onlyfans.com", path="/")
            s.cookies.set("sess", f"slop-sess-{account_id}", domain=".onlyfans.com", path="/")
            _sessions[account_id] = s
    return s


def _record(**rec) -> dict:
    with _lock:
        _state["inflight"] += 1
        rec = {"i": len(_calls), "t": time.time(), "inflight": _state["inflight"], **rec}
        _calls.append(rec)
    return rec


def _leave() -> None:
    with _lock:
        _state["inflight"] -= 1


def video_bytes() -> bytes:
    """A 12 s 64x64 clip at 1 fps (ffmpeg testsrc: a counter that changes every second), H.264 mp4."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=12:size=64x64:rate=1",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True, timeout=60)
        return out.read_bytes()


def _body(key: str, size: int) -> bytes:
    with _lock:
        b = _bytes.get(key)
    if b is None:
        b = video_bytes() if key.endswith(".mp4") else picture_bytes(key) if _cfg["pictures"] else asset_bytes(key, size)
        with _lock:
            _bytes[key] = b
    return b


def _range(h: str | None, n: int):
    """CloudFront's answer to one `Range: bytes=` spec on an n-byte object: (first, last), "unsatisfiable", or None
    (no / unparsable header: the whole object, 200)."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (h or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    if not m.group(1):
        return (max(0, n - int(m.group(2))), n - 1) if int(m.group(2)) else "unsatisfiable"
    a = int(m.group(1))
    if a >= n:
        return "unsatisfiable"
    return a, min(n - 1, int(m.group(2))) if m.group(2) else n - 1


def policy_b64(policy: dict) -> str:
    """A custom Policy as CloudFront puts it in a URL: base64 with `+=/` as `-_~`."""
    raw = base64.b64encode(json.dumps(policy, separators=(",", ":")).encode()).decode()
    return raw.translate(str.maketrans("+=/", "-_~"))


def policy_exp(policy: str) -> float:
    """A CloudFront custom Policy's expiry (`Statement[0].Condition.DateLessThan["AWS:EpochTime"]`, epoch s)."""
    raw = policy.translate(str.maketrans("-_~", "+=/"))
    doc = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)).decode())
    return float(doc["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"])


def policy_ip(policy: str) -> str | None:
    """A CloudFront custom Policy's `IpAddress.AWS:SourceIp`, or None when it names none."""
    raw = policy.translate(str.maketrans("-_~", "+=/"))
    doc = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)).decode())
    return (doc["Statement"][0]["Condition"].get("IpAddress") or {}).get("AWS:SourceIp")


def _denied(q: dict, egress: str) -> bool:
    """CloudFront's check, as far as this fake makes it: the three params present, the Policy's expiry ahead and
    its SourceIp (when it names one) the request's egress."""
    if not all(q.get(k) for k in ("Policy", "Signature", "Key-Pair-Id")):
        return True
    try:
        exp, ip = policy_exp(q["Policy"][0]), policy_ip(q["Policy"][0])
    except Exception:  # noqa: BLE001 — a Policy the fake cannot read is denied, as by CloudFront
        return True
    return exp < time.time() or (ip is not None and ip != egress)


def _serve() -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p = urlsplit(self.path)
            host = (self.headers.get(ORIG_HOST) or "").lower()
            key = f"{host}{p.path}"
            q = parse_qs(p.query)
            cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("cookie") or "").split(";") if "=" in c)
            egress = self.headers.get(EGRESS) or "direct"
            rec = _record(key=key, host=host, path=p.path, range=self.headers.get("range"), egress=egress,
                          cookie="cookie" in self.headers, auth_id=cookies.get("auth_id"),
                          ua=self.headers.get("user-agent"), of_headers=[h for h in OF_HEADERS if h in self.headers],
                          status=None, bytes=0)
            left = []

            def leave() -> None:  # once per call, whichever path gets here first
                if not left:
                    left.append(True)
                    _leave()

            try:
                time.sleep(_cfg["latency_s"])
                asset = _cfg["assets"].get(key)
                if asset is None:
                    status, body, ct = 404, b"<Error><Code>NoSuchKey</Code></Error>", "application/xml"
                elif signed(host) and _denied(q, egress):
                    status, body, ct = 403, b"<Error><Code>AccessDenied</Code></Error>", "application/xml"
                else:
                    status, body = 200, _body(key, int(asset))
                    ct = "video/mp4" if key.endswith(".mp4") else "image/jpeg"
                part = _range(self.headers.get("range"), len(body)) if status == 200 else None
                if part == "unsatisfiable":
                    status, part, body = 416, f"bytes */{len(body)}", b""
                elif part:
                    a, b = part
                    status, part, body = 206, f"bytes {a}-{b}/{len(body)}", body[a:b + 1]
                rec.update(status=status, bytes=len(body))
                if status not in (200, 206):  # the relay drops its slot on the status line alone
                    leave()
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                if part:
                    self.send_header("Content-Range", part)
                self.end_headers()
                if not body:
                    return
                self.wfile.write(body[:-1])
                leave()  # before the last byte: the relay cannot finish (and free its slot) before this
                self.wfile.write(body[-1:])
            except (BrokenPipeError, ConnectionResetError):
                rec["status"] = rec["status"] or 499
            finally:
                leave()

        def log_message(self, *_a):
            pass

    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 256  # listen() backlog (socketserver: 5); a class attr, read by server_activate

    srv = Srv(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, name="slop-fake-of-cdn", daemon=True).start()
    return srv.server_address[1]


def _domain_match(host: str, domain: str) -> bool:
    d = domain.lstrip(".").lower()
    return host == d or host.endswith("." + d)


def _route_curl() -> None:
    """curl_cffi's Session.request: a seeded CDN host goes to the fake (docstring 2). Idempotent."""
    from cffi_wrap import path_query, wrap_request

    def to_fake(session, p, k):
        host = (p.hostname or "").lower()
        if not (_state["port"] and host in _cfg["hosts"]):
            return None
        hdrs = dict(k.pop("headers", None) or {})
        hdrs[ORIG_HOST] = host
        px = k.get("proxies") or getattr(session, "proxies", None) or {}
        pu = urlsplit(str(px.get("https") or px.get("http") or ""))
        hdrs[EGRESS] = f"{pu.hostname}:{pu.port}" if pu.hostname else "direct"
        jar = "; ".join(f"{c.name}={c.value}" for c in session.cookies.jar if _domain_match(host, c.domain))
        if jar:
            hdrs["Cookie"] = jar
        k["headers"] = hdrs
        return f"http://127.0.0.1:{_state['port']}" + path_query(p)

    # The guard sits under it: `_guard_curl_cffi` stays idempotent.
    wrap_request(to_fake, "__slop_img__")


def _arm() -> dict:
    import img_api

    d = json.loads(_file().read_text())
    with _lock:
        assets = d.get("assets") or {}
        _cfg.update(assets=assets, hosts={k.split("/", 1)[0] for k in assets},
                    latency_s=float(d.get("latency_s") or 0), pictures=bool(d.get("pictures")))
    cache = Path(os.environ["DEMO_SHOTS_TMP"]) / "img-cache"
    cache.mkdir(parents=True, exist_ok=True)
    img_api._IMG_CACHE_DIR = cache
    _relay._guard_curl_cffi()
    _route_curl()
    if _state["port"] is None:
        _state["port"] = _serve()
    _state["armed"] = True
    return {"port": _state["port"], "cache_dir": str(cache)}


def wire(app, loopback, relay) -> None:
    global _relay
    from fastapi import Request
    from fastapi.responses import JSONResponse

    _relay = relay

    async def arm(request: Request):
        loopback(request)
        if not _on() or os.environ.get("SLOP_LIVE") == "1":
            return JSONResponse({"error": f"slop: no $DEMO_SHOTS_TMP/{CFG_FILE} (or SLOP_LIVE=1): not armed"},
                                status_code=409)
        return _arm()

    async def calls(request: Request, since: int = 0, until: int | None = None) -> dict:
        loopback(request)
        with _lock:
            return {"calls": [dict(c) for c in _calls[since:until]]}

    async def stats(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {"n": len(_calls)}

    app.add_api_route("/__slop/img/arm", arm, methods=["POST"])
    app.add_api_route("/__slop/img/calls", calls, methods=["GET"])
    app.add_api_route("/__slop/img/stats", stats, methods=["GET"])
