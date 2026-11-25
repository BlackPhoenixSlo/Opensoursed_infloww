import base64
from functools import cache
import hashlib
import json
import os
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CFG_FILE = "of-cdn.json"
ORIG_HOST = "X-Slop-Cdn-Host"
EGRESS = "X-Slop-Egress"
ACCOUNT_HEADERS = ("user-id", "x-bc", "app-token")
OF_HEADERS = (*ACCOUNT_HEADERS, "sign")
_lock = threading.Lock()
_calls: list[dict] = []
_cfg: dict = {"assets": {}, "hosts": set(), "latency_s": 0.0, "pictures": False, "mp4_sizes": {}, "stall": {},
              "mp4_frames": {}}
_state = {"port": None, "armed": False, "inflight": 0}
_bytes: dict[str, bytes] = {}
_sessions: dict[str, object] = {}
_relay = None


def _file() -> Path:
    return Path(os.environ.get("DEMO_SHOTS_TMP", "")) / CFG_FILE


def _on() -> bool:
    return bool(os.environ.get("DEMO_SHOTS_TMP")) and _file().is_file()


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
    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    # not bare noise: Chromium cancels an image whose first chunk will not decode (measured: capped line delivered ~1.5 KB)
    pad = size - len(_JPEG_1PX)
    if pad < 4:
        return rng.randbytes(size)
    out = [b"\xff\xd8"]
    while pad:
        n = min(pad, 65_537)
        if pad - n in (1, 2, 3):
            n = pad - 4
        out.append(b"\xff\xfe" + (n - 2).to_bytes(2, "big") + rng.randbytes(n - 4))
        pad -= n
    out.append(_JPEG_1PX[2:])
    return b"".join(out)


def picture_bytes(key: str) -> bytes:
    import struct
    import zlib
    rgb = hashlib.sha256(key.encode()).digest()[:3]
    raw = b"".join(b"\x00" + rgb * 16 for _ in range(16))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def signed(host: str) -> bool:
    return host != "public.onlyfans.com"


def creator_headers(account_id: str) -> dict[str, str]:
    vals = (str(account_id), f"slop-bc-{account_id}", "slop-app-token")
    return {"User-Agent": f"SlopCreatorUA/{account_id}", **dict(zip(ACCOUNT_HEADERS, vals, strict=True))}


async def arm_run(http, tmp: Path, assets: dict, latency_s: float, pictures: bool = False,
                  mp4_sizes: dict | None = None, stall: dict | None = None, mp4_frames: dict | None = None) -> dict:
    (Path(tmp) / CFG_FILE).write_text(json.dumps({
        "latency_s": latency_s, "pictures": pictures, "assets": {k: a["size"] for k, a in assets.items()},
        "mp4_sizes": mp4_sizes or {}, "stall": stall or {}, "mp4_frames": mp4_frames or {}}))
    r = await http.post("/__slop/img/arm")
    if r.status_code != 200:
        raise RuntimeError(f"slop: img arm hook answered {r.status_code}: {r.text[:200]}")
    return r.json()


class OF:

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


@cache
def video_bytes() -> bytes:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=12:size=64x64:rate=1",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True, timeout=60)
        return out.read_bytes()


@cache
def colour_clip(w: int, h: int, rgb: tuple) -> bytes:
    import subprocess
    import tempfile

    from PIL import Image
    # 4 fps: at 1 fps ffmpeg's accurate seek to i + 0.5 s drops frame i and returns the next (measured)
    raw = b"".join(Image.new("RGB", (w, h), tuple(c)).tobytes() for c in rgb for _ in range(4))
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "4",
                        "-i", "-", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                       input=raw, check=True, timeout=60)
        return out.read_bytes()


def padded_mp4(clip: bytes, size: int) -> bytes:
    pad = size - len(clip)
    return clip if pad < 8 else clip + pad.to_bytes(4, "big") + b"free" + bytes(pad - 8)


def _body(key: str, size: int) -> bytes:
    with _lock:
        b = _bytes.get(key)
        big = _cfg["mp4_sizes"].get(key)
        fr = _cfg["mp4_frames"].get(key)
    if b is None:
        if key.endswith(".mp4"):
            clip = colour_clip(*fr["size"], tuple(tuple(c) for c in fr["rgb"])) if fr else video_bytes()
            b = padded_mp4(clip, int(big)) if big else clip
        else:
            b = picture_bytes(key) if _cfg["pictures"] else asset_bytes(key, size)
        with _lock:
            _bytes[key] = b
    return b


UNSATISFIABLE_RANGE = (-1, -1)


def _range(h: str | None, n: int) -> tuple[int, int] | None:
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (h or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    if not m.group(1):
        return (max(0, n - int(m.group(2))), n - 1) if int(m.group(2)) else UNSATISFIABLE_RANGE
    a = int(m.group(1))
    if a >= n:
        return UNSATISFIABLE_RANGE
    return a, min(n - 1, int(m.group(2))) if m.group(2) else n - 1


def policy_b64(policy: dict) -> str:
    raw = base64.b64encode(json.dumps(policy, separators=(",", ":")).encode()).decode()
    return raw.translate(str.maketrans("+=/", "-_~"))


def _policy_doc(policy: str) -> dict:
    raw = policy.translate(str.maketrans("-_~", "+=/"))
    return json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)).decode())


def policy_exp(policy: str) -> float:
    doc = _policy_doc(policy)
    return float(doc["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"])


def policy_ip(policy: str) -> str | None:
    doc = _policy_doc(policy)
    return (doc["Statement"][0]["Condition"].get("IpAddress") or {}).get("AWS:SourceIp")


def _denied(q: dict, egress: str) -> bool:
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

            # runs before the last byte so a relay slot is never freed while the fake still counts the request
            def leave() -> None:
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
                range_header = None
                if part == UNSATISFIABLE_RANGE:
                    status, range_header, body = 416, f"bytes */{len(body)}", b""
                elif part is not None:
                    a, b = part
                    status, range_header, body = 206, f"bytes {a}-{b}/{len(body)}", body[a:b + 1]
                rec.update(status=status, bytes=len(body))
                if status not in (200, 206):
                    leave()
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                if range_header:
                    self.send_header("Content-Range", range_header)
                self.end_headers()
                if not body:
                    return
                st = _cfg["stall"].get(key) if status == 200 else None
                if st:
                    k = max(0, min(int(st.get("after", 0)), len(body) - 1))
                    rec.update(stalled=True, status=499)
                    self.wfile.write(body[:k])
                    self.wfile.flush()
                    time.sleep(float(st.get("hold_s", 45)))
                    body = body[k:]
                self.wfile.write(body[:-1])
                leave()
                self.wfile.write(body[-1:])
                if st:
                    rec["status"] = 200
            except (BrokenPipeError, ConnectionResetError):
                rec["status"] = rec["status"] or 499
            finally:
                leave()

        def log_message(self, *_a):
            pass

    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        # listen() backlog; socketserver default is 5
        request_queue_size = 256

    srv = Srv(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, name="slop-fake-of-cdn", daemon=True).start()
    return srv.server_address[1]


def _domain_match(host: str, domain: str) -> bool:
    d = domain.lstrip(".").lower()
    return host == d or host.endswith("." + d)


def _route_curl() -> None:
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

    wrap_request(to_fake, "__slop_img__")


def _arm() -> dict:
    import img_api

    d = json.loads(_file().read_text())
    with _lock:
        assets = d.get("assets") or {}
        big = d.get("mp4_sizes") or {}
        frames = d.get("mp4_frames") or {}
        for k in set(big) | set(_cfg["mp4_sizes"]) | set(frames) | set(_cfg["mp4_frames"]):
            _bytes.pop(k, None)
        _cfg.update(assets=assets, hosts={k.split("/", 1)[0] for k in assets}, mp4_sizes=big, mp4_frames=frames,
                    latency_s=float(d.get("latency_s") or 0), pictures=bool(d.get("pictures")),
                    stall=d.get("stall") or {})
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
