"""A Web Push service at its wire, on loopback (`PushWire`): what the relay's push_send POSTs to
(FCM / Mozilla / Apple stand-in). A stdlib `ThreadingHTTPServer` in the harness process, a thread
per request, like lib/of_wire.py, and NOT a `/__slop` route in the relay: a relay posting to its own
loop would hide loop stalls in the frame -> push number.

  POST /push/<sub>   one push to device `sub` (registered with `device(sub, priv, auth)`: the real
                     P-256 private key + 16-byte auth secret the device PUT the public halves of).
                     Recorded (`records`, one dict per request: sub, t_recv epoch s, status, headers,
                     body length, vapid verdict, plaintext JSON or decrypt error), then answered:
                     403 when the VAPID header is invalid, else what the sub is armed with, else 201.

VAPID check (RFC 8292): `Authorization: vapid t=<JWT>, k=<b64url raw P-256 key>`; the JWT is ES256
and verifies under k; k == `vapid_key` (set from the relay's GET /push/key, when known); aud == this
endpoint's origin; sub = mailto: with a non-empty host that is not localhost / loopback; exp in the
future and <= 24 h ahead. Decryption: aes128gcm (RFC 8291) with the device's private key + auth
secret (http_ece), so a body encrypted to the wrong keys is a decrypt error, never a pass.

`arm(sub, status=410)`: every request to it answers 410 (gone). `arm(sub, status=429, once=True)`: the
next one answers 429 (Retry-After 1), then normal. `arm(sub, latency_s=x)`: each answer after x s.
Declared: the real services' other behaviour (TTL storage, collapse, quotas) is not modelled; latency
0 unless armed (a guess: FCM answers in ~50-150 ms from a server).
"""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address

MAX_EXP_S = 24 * 3600


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class _Arm:
    status: int | None = None
    once: bool = False
    latency_s: float = 0.0


@dataclass
class Device:
    priv: object  # cryptography EllipticCurvePrivateKey
    auth: bytes
    arm: _Arm = field(default_factory=_Arm)


def _loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def check_vapid(header: str | None, origin: str, want_key: str | None, now: float) -> tuple[bool, str, dict]:
    """(ok, why, claims) for one Authorization header."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    if not header or not header.lower().startswith("vapid "):
        return False, "no vapid Authorization", {}
    parts = dict(p.strip().split("=", 1) for p in header[6:].split(",") if "=" in p)
    t, k = parts.get("t"), parts.get("k")
    if not t or not k:
        return False, "t= or k= missing", {}
    try:
        h64, c64, s64 = t.split(".")
        hdr, claims, sig = json.loads(unb64(h64)), json.loads(unb64(c64)), unb64(s64)
    except (ValueError, TypeError):
        return False, "JWT unparseable", {}
    if hdr.get("alg") != "ES256" or len(sig) != 64:
        return False, f"alg {hdr.get('alg')} / sig {len(sig)} bytes", claims
    if want_key is not None and k != want_key:
        return False, "k is not the relay's /push/key", claims
    try:
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(k))
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        pub.verify(der, f"{h64}.{c64}".encode(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):
        return False, "signature does not verify under k", claims
    if claims.get("aud") != origin:
        return False, f"aud {claims.get('aud')!r} != {origin!r}", claims
    sub = claims.get("sub")
    host = sub[7:].rpartition("@")[2].strip().lower().rstrip(".") if isinstance(sub, str) and sub.startswith("mailto:") \
        and "@" in sub else ""
    if not host or _loopback(host):
        return False, f"sub {sub!r} not mailto: with a public host", claims
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= now or exp - now > MAX_EXP_S:
        return False, f"exp {exp!r} not within (now, now + 24 h]", claims
    return True, "", claims


class PushWire:
    """`with PushWire() as wire:` serves on 127.0.0.1:<free port>; `wire.origin`, `wire.endpoint(sub)`."""

    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}
        self.records: list[dict] = []
        self.vapid_key: str | None = None
        self._lock = threading.Lock()
        self._jwt_ok: dict[tuple[str, str | None], tuple[bool, str, dict]] = {}
        wire = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                wire._handle(self)

            def log_message(self, *a):
                pass

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._srv.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self._srv.server_address[1]}"

    def __enter__(self) -> "PushWire":
        threading.Thread(target=self._srv.serve_forever, daemon=True, name="push-wire").start()
        return self

    def __exit__(self, *exc) -> None:
        self._srv.shutdown()
        self._srv.server_close()

    def endpoint(self, sub: str) -> str:
        return f"{self.origin}/push/{sub}"

    def device(self, sub: str, priv, auth: bytes) -> None:
        with self._lock:
            self.devices[sub] = Device(priv, auth)

    def arm(self, sub: str, *, status: int | None = None, once: bool = False, latency_s: float = 0.0) -> None:
        with self._lock:
            self.devices[sub].arm = _Arm(status, once, latency_s)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.records)

    def last_recv(self) -> float:
        with self._lock:
            return self.records[-1]["t_recv"] if self.records else 0.0

    def _vapid(self, header: str | None, now: float) -> tuple[bool, str, dict]:
        key = (header or "", self.vapid_key)
        hit = self._jwt_ok.get(key)
        if hit is None or (hit[0] and hit[2].get("exp", 0) <= now):
            hit = check_vapid(header, self.origin, self.vapid_key, now)
            if len(self._jwt_ok) > 1000:
                self._jwt_ok.clear()
            self._jwt_ok[key] = hit
        return hit

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        import http_ece

        t_recv = time.time()
        body = h.rfile.read(int(h.headers.get("content-length") or 0))
        sub = h.path[len("/push/"):] if h.path.startswith("/push/") else None
        rec = {"sub": sub, "t_recv": t_recv, "path": h.path, "len": len(body),
               "headers": {k: h.headers.get(k) for k in ("ttl", "urgency", "content-encoding", "content-type")}}
        ok, why, claims = self._vapid(h.headers.get("authorization"), t_recv)
        rec["vapid"] = {"ok": ok, "why": why, "aud": claims.get("aud"), "sub": claims.get("sub"),
                        "exp_in_s": (claims.get("exp") - t_recv) if isinstance(claims.get("exp"), int) else None}
        with self._lock:
            dev = self.devices.get(sub or "")
            arm = dev.arm if dev else None
            status = 404 if dev is None else 403 if not ok else arm.status or 201
            if dev is not None and ok and arm.status and arm.once:
                dev.arm = _Arm(latency_s=arm.latency_s)
        if dev is not None:
            try:
                rec["plain"] = json.loads(http_ece.decrypt(body, private_key=dev.priv, auth_secret=dev.auth,
                                                           version="aes128gcm"))
            except Exception as e:  # noqa: BLE001 — a body that does not decrypt is the finding
                rec["plain"], rec["decrypt_error"] = None, f"{type(e).__name__}: {e}"[:200]
        if arm is not None and arm.latency_s:
            time.sleep(arm.latency_s)
        rec["status"] = status
        with self._lock:
            self.records.append(rec)
        h.send_response(status)
        if status == 429:
            h.send_header("Retry-After", "1")
        h.send_header("Content-Length", "0")
        h.end_headers()
