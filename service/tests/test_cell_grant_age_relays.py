from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import actor_token  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
NOVA_A, NOVA_B = "900539700124344320", "900539700124344321"
KEY = "cell-s02-copy-credential-grant-age-0123456789"
MAX_AGE = 8
AGED = b'{"detail":{"error":"grant_age_exceeded"}}'


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _q(path: str, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as db, db:
        return db.execute(sql, args).fetchall()


def _wait(pred, limit: float) -> float:
    t0 = time.monotonic()
    while not pred():
        assert time.monotonic() - t0 < limit, "timed out"
        time.sleep(0.02)
    return time.monotonic() - t0


def _ask(port: int, method: str, path: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _jar(**c: str) -> dict:
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in c.items() if v)}


def _set_cookies(h) -> dict[str, str]:
    out = {}
    for v in h.get_all("set-cookie") or []:
        name, _, rest = v.partition("=")
        out[name] = rest.split(";", 1)[0]
    return out


class _Relay:
    def __init__(self, root: Path, sid: str, role: str, placement: Path, extra: dict):
        self.work, self.port = root / sid, _port()
        (self.work / "home").mkdir(parents=True)
        self.db = str(self.work / "relay.db")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.work / "home"),
                    "TMPDIR": str(self.work), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
                    "ALLOW_ANONYMOUS_ADMIN": "0", "DATABASE_URL": f"sqlite+aiosqlite:///{self.db}",
                    "CHATTERLY_DB_URL": f"sqlite:///{self.db}", "SESSION_SECRET": "cell-age-session",
                    "CHATTER_SESSION_SECRET": "cell-age-chatter", "ADMIN_PASSWORD": "cell-age-admin",
                    "VAPID_KEY_FILE": str(self.work / "vapid.pem"), "OI_CELL_MAP": str(placement),
                    "OI_CELL_ID": sid, "OI_CELL_ROLE": role, "OI_EPOCH": "1", "OI_CELL_MAX_GRANT_AGE_S": str(MAX_AGE),
                    **extra}
        self.proc = self.log = None

    def start(self) -> None:
        self.log = open(self.work / "relay.log", "ab")
        self.proc = subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app", "--host",
                                      "127.0.0.1", "--port", str(self.port)], cwd=SERVICE, env=self.env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 240
        while True:
            assert self.proc.poll() is None, self.text()[-3000:]
            with contextlib.suppress(OSError):
                if _ask(self.port, "GET", "/livez")[0] == 200:
                    return
            assert time.monotonic() < deadline, f"{self.work.name} never answered /livez"
            time.sleep(0.3)

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()
        self.proc = None

    def text(self) -> str:
        return (self.work / "relay.log").read_text(errors="replace")


class _Link:
    def __init__(self, target: int):
        self.target, self.port = target, _port()
        self.lock, self.socks, self.srv, self.closed = threading.Lock(), [], None, True

    def heal(self) -> None:
        self.srv = socket.create_server(("127.0.0.1", self.port), reuse_port=False)
        self.closed = False
        threading.Thread(target=self._accept, args=(self.srv,), daemon=True).start()

    def cut(self) -> None:
        with self.lock:
            self.closed = True
            with contextlib.suppress(OSError):
                self.srv.shutdown(socket.SHUT_RDWR)
            self.srv.close()
            for s in self.socks:
                with contextlib.suppress(OSError):
                    s.shutdown(socket.SHUT_RDWR)
                s.close()
            self.socks.clear()

    def _accept(self, srv) -> None:
        while True:
            try:
                a, _ = srv.accept()
            except OSError:
                return
            try:
                b = socket.create_connection(("127.0.0.1", self.target))
            except OSError:
                a.close()
                continue
            with self.lock:
                if self.closed:
                    a.close()
                    b.close()
                    continue
                self.socks += [a, b]
            for x, y in ((a, b), (b, a)):
                threading.Thread(target=self._pipe, args=(x, y), daemon=True).start()

    @staticmethod
    def _pipe(x, y) -> None:
        with contextlib.suppress(OSError):
            while chunk := x.recv(65536):
                y.sendall(chunk)
        with contextlib.suppress(OSError):
            y.shutdown(socket.SHUT_WR)


class _Stream:
    def __init__(self, port: int, tok: str):
        self.status, self.ended_at = None, None
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        self.conn.request("GET", "/events?scope=all&lease=1", headers=_jar(oi_actor=tok))
        r = self.conn.getresponse()
        self.status = r.status
        threading.Thread(target=self._drain, args=(r,), daemon=True).start()

    def _drain(self, r) -> None:
        with contextlib.suppress(OSError, http.client.HTTPException):
            while r.readline():
                pass
        self.ended_at = time.monotonic()


@contextlib.contextmanager
def _fleet(cell_env: dict | None = None):
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = root / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "x", "role": "control", "state": "live"},
                      "s02": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{NOVA_A}": "s02", f"onlyfans:{NOVA_B}": "s02"}}))
        pub = actor_token.new_key(root / "keys")
        ctl = _Relay(root, "s01", "control", placement, {
            "OI_ACCOUNTS": "", "OI_CELL_COPY_KEYS": f"s02:{hashlib.sha256(KEY.encode()).hexdigest()}",
            "OI_CELL_ACTOR_KEY_FILE": str(root / "keys/actor_ed25519.pem")})
        link = _Link(ctl.port)
        cell = _Relay(root, "s02", "data", placement, {
            "OI_ACCOUNTS": f"onlyfans:{NOVA_A},onlyfans:{NOVA_B}", "OI_CELL_COPY_KEY": KEY,
            "OI_CELL_CONTROL_URL": f"http://127.0.0.1:{link.port}", "OI_CELL_ACTOR_PUBKEY": pub,
            **{k: v.format(root=root) for k, v in (cell_env or {}).items()}})
        try:
            yield ctl, cell, link, root
        finally:
            cell.stop()
            ctl.stop()
            with contextlib.suppress(Exception):
                link.cut()


def _forge(root: Path, claims: dict) -> str:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key((root / "keys/actor_ed25519.pem").read_bytes(), password=None)
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    return f"{actor_token._b64(payload)}.{actor_token._b64(key.sign(payload))}"


def _read(cell: _Relay, tok: str, account: str = NOVA_A):
    st, _h, raw = _ask(cell.port, "GET", f"/admin/chats/recent?account_id={account}&limit=5", _jar(oi_actor=tok))
    return st, raw


def _key_read(cell: _Relay, key: str):
    st, _h, raw = _ask(cell.port, "GET", "/admin/accounts", {"Authorization": f"Bearer {key}"})
    return st, raw


def _synced(ctl: _Relay, cell: _Relay, limit: float = 10) -> float:
    gen = _q(ctl.db, "SELECT grant_gen FROM agency_copy_version")[0][0]
    return _wait(lambda: _q(cell.db, "SELECT grant_gen FROM cell_meta")[0][0] == gen, limit)


def _renew(ctl: _Relay, session: str) -> str:
    st, h, raw = _ask(ctl.port, "POST", "/auth/actor", _jar(chatterly_session=session))
    assert st == 200, (st, raw[:300])
    return _set_cookies(h)["oi_actor"]


def case_grant_age_cold_boot_revoke_partition_and_outage() -> None:
    with _fleet() as (ctl, cell, link, root):
        cell.start()
        now = int(time.time())
        cold = _forge(root, {"v": 1, "kind": "user", "id": 1, "eff_id": 1, "ro": False, "agency": "acme",
                             "iat": now, "exp": now + 600, "ggen": 0})
        assert _read(cell, cold) == (503, AGED), ("fresh Cell with no confirmed copy", _read(cell, cold))
        assert _key_read(cell, "oi_owner_unknown") == (503, AGED), "owner key on a fresh Cell"
        assert _ask(cell.port, "GET", "/livez")[0] == 200
        st, _h, raw = _ask(cell.port, "GET", f"/admin/chats/recent?account_id={NOVA_A}&limit=5")
        assert st == 401, ("no credential still meets the sign-in gate, not the age gate", st, raw[:120])

        ctl.start()
        link.heal()
        st, h, raw = _ask(ctl.port, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
        assert st == 200, (st, raw[:300])
        owner, session = json.loads(raw)["user_id"], _set_cookies(h)["chatterly_session"]
        _q(ctl.db, "INSERT INTO accounts (id, is_active_default) VALUES (?, 1), (?, 1)", (NOVA_A, NOVA_B))
        _q(ctl.db, "INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?), (?, ?)",
           (owner, NOVA_A, owner, NOVA_B))
        st, _h, raw = _ask(ctl.port, "POST", "/admin/owner-tokens", _jar(chatterly_session=session),
                           {"name": "outage probe", "days": 365})
        assert st == 200, (st, raw[:300])
        key = json.loads(raw)["token"]
        _synced(ctl, cell)
        _wait(lambda: _read(cell, cold)[0] != 503, 10)
        tok = _renew(ctl, session)
        assert _read(cell, tok)[0] == 200 and _read(cell, tok, NOVA_B)[0] == 200, _read(cell, tok)
        assert _key_read(cell, key)[0] == 200, _key_read(cell, key)
        cl = json.loads(actor_token._unb64(tok.split(".")[0]))
        expired = _forge(root, {**cl, "iat": now - 2000, "exp": now - 1100})
        st, raw = _read(cell, expired)
        assert (st, json.loads(raw)["detail"]["error"]) == (401, "actor_expired"), "expiry with a current copy: renew"

        path = f"/admin/users/{owner}/accounts/{NOVA_B}"
        body = {"admin_password": "cell-age-admin"}
        st, _h, raw = _ask(cell.port, "DELETE", path, _jar(oi_actor=tok), body)
        assert st == 403 and json.loads(raw)["detail"]["error"] == "agency_write_on_data_cell", (st, raw)
        st, _h, raw = _ask(ctl.port, "DELETE", path, {
            **_jar(chatterly_session=session), "X-Cell-Expect": "s02.1",
        }, body)
        assert st == 409 and json.loads(raw)["detail"]["error"] == "not_owner", (st, raw)
        streams = [_Stream(cell.port, tok) for _ in range(3)]
        assert all(s.status == 200 for s in streams), [s.status for s in streams]
        stop = threading.Event()
        late: list[_Stream] = []

        def _register_during_apply() -> None:
            while not stop.is_set():
                with contextlib.suppress(OSError, http.client.HTTPException):
                    late.append(_Stream(cell.port, tok))
                time.sleep(0.02)
        racers = [threading.Thread(target=_register_during_apply, daemon=True) for _ in range(4)]
        for r in racers:
            r.start()
        time.sleep(0.3)
        t0 = time.monotonic()
        st, _h, raw = _ask(ctl.port, "DELETE", path, _jar(chatterly_session=session), body)
        assert st == 200, (st, raw)
        assert _q(ctl.db, "SELECT 1 FROM user_accounts WHERE account_id = ?", (NOVA_B,)) == []
        _wait(lambda: _read(cell, tok)[0] == 401, 5)
        refused = time.monotonic() - t0
        assert refused <= 1.0, f"connected Cell refused the revoked token after {refused:.2f} s"
        _wait(lambda: all(s.ended_at for s in streams), 5)
        ended = max(s.ended_at for s in streams) - t0
        assert ended <= 1.0, f"open streams ended {ended:.2f} s after the revoke"
        time.sleep(0.5)
        stop.set()
        for r in racers:
            r.join(10)
        assert late, "no stream registered during the apply"
        _wait(lambda: all(s.ended_at or s.status != 200 for s in late), 5)
        print(f"[measured] revoke refused {refused:.2f} s, streams ended {ended:.2f} s, "
              f"{len(late)} racing registrations all ended or refused", flush=True)
        tok = _renew(ctl, session)
        assert _read(cell, tok, NOVA_B)[0] == 403, "revoked grant still readable"

        link.cut()
        t0 = time.monotonic()
        _q(ctl.db, "DELETE FROM user_accounts WHERE account_id = ?", (NOVA_A,))
        time.sleep(MAX_AGE / 4)
        assert _read(cell, tok)[0] == 200, ("partitioned Cell before its Grant age", _read(cell, tok))
        _wait(lambda: _read(cell, tok) == (503, AGED), MAX_AGE + 3)
        print(f"[measured] partitioned Cell refused after {time.monotonic() - t0:.1f} s (max {MAX_AGE})", flush=True)
        link.heal()
        _wait(lambda: _read(cell, tok)[0] == 401, MAX_AGE)
        _q(ctl.db, "INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?)", (owner, NOVA_A))
        _synced(ctl, cell)
        tok = _renew(ctl, session)
        assert _read(cell, tok)[0] == 200

        stream = _Stream(cell.port, tok)
        assert stream.status == 200
        ctl.stop()
        t0 = time.monotonic()
        time.sleep(MAX_AGE / 4)
        assert _read(cell, tok)[0] == 200 and _key_read(cell, key)[0] == 200, "control down briefly: chatting goes on"
        assert stream.ended_at is None, "stream ended while the copy was still young"
        _wait(lambda: _key_read(cell, key) == (503, AGED), MAX_AGE + 3)
        _wait(lambda: stream.ended_at is not None, 3)
        assert _read(cell, tok) == (503, AGED) and _ask(cell.port, "GET", "/livez")[0] == 200
        assert "GRANT AGE EXCEEDED" in cell.text()
        print(f"[measured] control down: owner key 503 after {time.monotonic() - t0:.1f} s", flush=True)

        cell.stop()
        cell.start()
        assert _key_read(cell, key) == (503, AGED), "restart must count the age from the saved confirm, not boot"
        cell.stop()
        young = 40
        stamp = time.time() - 20
        _q(cell.db, "UPDATE cell_meta SET confirmed_at = ?",
           (datetime.fromtimestamp(stamp, timezone.utc).replace(tzinfo=None).isoformat(),))
        cell.env["OI_CELL_MAX_GRANT_AGE_S"] = str(young)
        cell.start()
        assert _key_read(cell, key)[0] == 200, "restart with a young saved confirm serves while control is down"
        _wait(lambda: _key_read(cell, key) == (503, AGED), young)
        off = time.time() - (stamp + young)
        assert -1.5 <= off <= 2.5, f"aged {off:+.1f} s from saved confirm + max, not from boot"
        print(f"[measured] restarted Cell aged {off:+.1f} s from saved confirmed_at + max", flush=True)
        ctl.start()
        _wait(lambda: _key_read(cell, key)[0] == 200, 20)
        assert _read(cell, tok)[0] == 200, "token with a current copy reads again"
        assert "control confirmed the Agency copy again" in cell.text()


def case_lapsed_send_permit_reads_go_on_writes_paused() -> None:
    with _fleet({"OI_CELL_SEND_PERMIT": "{root}/run/send_permit", "OI_CELL_INSTANCE": "b1:2"}) as (ctl, cell, link, root):
        ctl.start()
        link.heal()
        cell.start()
        st, h, raw = _ask(ctl.port, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
        assert st == 200, (st, raw[:300])
        owner, session = json.loads(raw)["user_id"], _set_cookies(h)["chatterly_session"]
        _q(ctl.db, "INSERT INTO accounts (id, is_active_default) VALUES (?, 1)", (NOVA_A,))
        _q(ctl.db, "INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?)", (owner, NOVA_A))
        _synced(ctl, cell)
        tok = _renew(ctl, session)
        _wait(lambda: _read(cell, tok)[0] == 200, 10)
        stream = _Stream(cell.port, tok)
        cl = json.loads(actor_token._unb64(tok.split(".")[0]))
        now = int(time.time())
        expired = _forge(root, {**cl, "iat": now - 2000, "exp": now - 1100})
        like = lambda: _ask(cell.port, "POST", "/api/of/v2/messages/7/like",  # noqa: E731
                            {**_jar(oi_actor=tok), "X-Account-Id": NOVA_A})
        st, _h, raw = like()
        assert stream.status == 200 and (st, json.loads(raw)["detail"]["error"]) == (503, "writes_paused"), (st, raw)
        assert json.loads(_read(cell, expired)[1])["detail"]["error"] == "actor_expired", "expired Grant still refused"
        assert stream.ended_at is None, "lapsed permit ended the live stream"
        permit = root / "run/send_permit"
        permit.parent.mkdir()
        permit.write_text(json.dumps({"lease_id": 1, "box": "b1", "until": time.time() + 600}))
        st, _h, raw = like()
        assert b"writes_paused" not in raw, ("fresh permit still paused", st, raw[:200])
        print(f"[measured] lapsed permit: read 200, stream 200, like 503 writes_paused; fresh permit like {st}",
              flush=True)


def case_grant_check_in_process() -> None:
    import agency_copy
    saved = agency_copy._held
    try:
        actor_token.DATA = True
        claims = type("C", (), {"ggen": 5})()
        agency_copy._held = (time.time(), 5)
        assert actor_token.stream_refusal(claims) is None and not agency_copy.aged()
        agency_copy._held = (time.time(), 6)
        st = actor_token.stream_refusal(claims)
        assert st is not None and st.status_code == 401 and b"actor_stale" in st.body, "stream older than the copy"
        agency_copy._held = (time.time() - 10_000, 5)
        assert agency_copy.aged(), "aged copy"
        agency_copy._held = (None, None)
        assert agency_copy.aged(), "no confirmed copy is past the max"
    finally:
        agency_copy._held = saved
        actor_token.DATA = False


_harness.run()
