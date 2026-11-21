"""Rollout driver, shared core: exit codes and constants, the loopback relay client, sign-in, the journal and the
per-run context. Imported by rollout.py (CLI, describe side) and rollout_fill.py (fill side); imports neither.
Standard library only; no `service/` import. See rollout.py's docstring for the modes.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse
from urllib import request as urlrequest

EXIT_DONE, EXIT_REFUSED, EXIT_PAUSED, EXIT_DEFERRED = 0, 2, 3, 4
POLL_S = 10.0                 # describe-all/status, collect/status and read-retry poll interval
REQUEST_TIMEOUT_S = 30.0
LIVEZ_TIMEOUT_S = 5.0
COOKIE = "chatterly_session"
VAULT = "/admin/vault-ai"
PLAN = f"{VAULT}/describe-all/plan"


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    """A 3xx is answered as itself, never followed: urllib would carry the session cookie to the Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


# loopback only: never through a proxy, never to a redirect's host
_OPENER = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())


class Refused(Exception):
    """Exit 2 with a one-line reason."""


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(now() if ts is None else ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_day(ts: float | None = None) -> str:
    return iso(ts)[:10]


def say(msg: str) -> None:
    print(msg, flush=True)


# ── Relay client ────────────────────────────────────────────────────────────

def check_relay(url: str) -> str:
    """The relay URL, or Refused when it is not loopback (checked before any request)."""
    u = parse.urlsplit(url)
    host = u.hostname or ""
    if u.scheme not in ("http", "https") or not host:
        raise Refused(f"relay must be an http URL on loopback, got {url!r}")
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise Refused(f"relay {host} is not loopback")
        except ValueError:
            raise Refused(f"relay {host} is not loopback") from None
    return url.rstrip("/")


class Resp:
    """One answer: `json` the parsed body (None when not JSON), `body` the raw bytes."""

    def __init__(self, status: int, js: Any, headers: Any = None, body: bytes = b"") -> None:
        self.status, self.json, self.headers, self.body = status, js, headers, body

    @property
    def ok(self) -> bool:
        return self.status == 200 and isinstance(self.json, dict)

    def error(self) -> str:
        js = self.json if isinstance(self.json, dict) else {}
        d = js.get("detail")
        if isinstance(d, dict):
            return str(d.get("error") or "")
        return str(d or js.get("error") or "")


class Relay:
    """JSON over loopback with the session cookie. Counts consecutive 5xx / transport errors (a pause rule)."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.session: str | None = None
        self.errors_in_a_row = 0
        self.last_status = 0

    def call(self, method: str, path: str, query: dict | None = None, body: Any = None,
             timeout: float = REQUEST_TIMEOUT_S) -> Resp:
        """JSON in and out."""
        r = self._send(method, path, query, body, timeout, "application/json")
        if r.status:
            try:
                r.json = json.loads(r.body) if r.body else None
            except ValueError:
                r.json = None
        return r

    def get_bytes(self, path: str, query: dict | None = None) -> Resp:
        """A GET whose answer is bytes (the contact sheet's thumbs): `Resp.body`; `Resp.json` stays None."""
        return self._send("GET", path, query, None, REQUEST_TIMEOUT_S, "*/*")

    def _send(self, method: str, path: str, query: dict | None, body: Any, timeout: float, accept: str) -> Resp:
        url = self.base + path + (("?" + parse.urlencode(query)) if query else "")
        headers = {"Accept": accept}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif method != "GET":
            data = b""
        if self.session:
            headers["Cookie"] = f"{COOKIE}={self.session}"
        req = urlrequest.Request(url, data=data, method=method, headers=headers)
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                status, raw, hdrs = r.status, r.read(), r.headers
        except urlerror.HTTPError as e:
            status, raw, hdrs = e.code, e.read(), e.headers
        except (urlerror.URLError, OSError, ValueError) as e:
            self.errors_in_a_row += 1
            self.last_status = 0
            return Resp(0, {"error": type(e).__name__})
        self.last_status = status
        self.errors_in_a_row = self.errors_in_a_row + 1 if status >= 500 else 0
        return Resp(status, None, hdrs, raw)

    def livez(self) -> dict:
        """/livez has its own pause rule: it neither counts toward nor clears the product routes' error run."""
        t0 = time.monotonic()
        kept = (self.errors_in_a_row, self.last_status)
        r = self.call("GET", "/livez", timeout=LIVEZ_TIMEOUT_S)
        self.errors_in_a_row, self.last_status = kept
        return {"status": r.status, "seconds": round(time.monotonic() - t0, 3)}


def _cookie_from(headers: Any) -> str | None:
    for v in (headers.get_all("Set-Cookie") or []) if headers is not None else []:
        c = SimpleCookie()
        try:
            c.load(v)
        except Exception:  # noqa: BLE001 — one odd header must not hide the session cookie
            continue
        if COOKIE in c and c[COOKIE].value:
            return c[COOKIE].value
    return None


def sign_in(relay: Relay, owner_ok: bool = False) -> None:
    """SFR_SESSION, else a hidden prompt on a TTY. Then `GET /auth/me` must say `is_admin`, unless the operator
    vouches (`--owner-session`) that this login owns every Creator (a stack with no Master, e.g. one agency)."""
    sess = (os.environ.get("SFR_SESSION") or "").strip()
    if not sess:
        if not sys.stdin.isatty():
            raise Refused("no session: set SFR_SESSION or run on a TTY to sign in")
        user = input("Master username: ").strip()
        r = relay.call("POST", "/auth/login", body={"username": user, "password": getpass.getpass("Password: ")})
        if r.ok and r.json.get("two_factor"):
            r = relay.call("POST", "/auth/2fa/login",
                           body={"ticket": r.json.get("ticket"), "code": getpass.getpass("2FA code: ").strip()})
        sess = _cookie_from(r.headers) if r.status == 200 else None
        if not sess:
            raise Refused(f"sign-in failed (HTTP {r.status})")
    relay.session = sess
    me = relay.call("GET", "/auth/me")
    if not (me.ok and (me.json.get("is_admin") or (owner_ok and me.json.get("user_id")))):
        raise Refused("the session is not a Master (is_admin): the roster would be partial "
                      "(--owner-session if this login owns every Creator)")


# ── Journal ─────────────────────────────────────────────────────────────────

class Journal:
    """Append-only JSON Lines, file mode 0600. Every line: t, mode, kind, creator (+ kind fields)."""

    def __init__(self, path: Path, mode: str) -> None:
        self.path, self.mode = path, mode

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for raw in self.path.read_text().splitlines():
            try:
                ln = json.loads(raw)
            except ValueError:   # a line cut by a kill mid-write
                continue
            if isinstance(ln, dict):
                out.append(ln)
        return out

    def write(self, kind: str, creator: str | None = None, **fields: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = {"t": iso(), "mode": self.mode, "kind": kind, "creator": creator, **fields}
        data = (json.dumps(line, sort_keys=True) + "\n").encode()
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":   # a line cut by a kill: never glue this one onto it
                data = b"\n" + data
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(self.path, 0o600)


# ── Shared reads ────────────────────────────────────────────────────────────

class Ctx:
    def __init__(self, args: argparse.Namespace, relay: Relay, journal: Journal) -> None:
        self.args, self.relay, self.journal = args, relay, journal
        self.live = bool(args.live)
        self.all_ok: list[dict] = []        # every Eligible Creator (unfiltered)
        self.scoped: list[dict] = []        # Eligible Creators in --creator scope
        self.skipped: list[tuple[dict, str]] = []
        self._summary: dict[str, dict] = {}

    def summary(self, cid: str) -> dict | None:
        if cid not in self._summary:
            r = self.relay.call("GET", f"{VAULT}/cache/summary", {"account_id": cid})
            if not r.ok:
                return None
            self._summary[cid] = r.json
        return self._summary[cid]

    def plan(self, cid: str, target: int) -> dict | None:
        """describe-all/plan at `target`; None on a failed read. A plan without `target_remaining` is a relay
        without Phase 1a: Refused."""
        r = self.relay.call("GET", PLAN, {"account_id": cid, "target": target})
        if not r.ok:
            return None
        if "target_remaining" not in r.json or not isinstance(r.json.get("coverage"), dict):
            raise Refused("the describe plan route has no target_remaining: the relay lacks Phase 1a")
        return r.json

    def settle_open(self, cid: str, reason: str, detail: str | None = None) -> None:
        self.journal.write("open", cid, reason=reason, **({"detail": detail} if detail else {}))
        say(f"open {cid}: {reason}{' — ' + detail if detail else ''}")
