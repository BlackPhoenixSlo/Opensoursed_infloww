from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import socket  # noqa: E402

import actor_token  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
NOVA_A, NOVA_B = "900548100671225001", "900548100671225002"
KEY = "cell-s02-copy-credential-actor-0123456789"
SHARE = "cell-actor-share-token-0123456789"


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _q(path: str, sql: str, args=()):
    with contextlib.closing(sqlite3.connect(path, timeout=30)) as db:
        return db.execute(sql, args).fetchall()


def _wait(pred, limit: float = 10.0) -> None:
    t0 = time.monotonic()
    while not pred():
        assert time.monotonic() - t0 < limit, "timed out"
        time.sleep(0.02)


def _placement(root: Path) -> Path:
    p = root / "placement.json"
    p.write_text(json.dumps({
        "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
        "min_cell_proto": 1,
        "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "x", "role": "control", "state": "live"},
                  "s02": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"}},
        "accounts": {f"onlyfans:{NOVA_A}": "s02", f"onlyfans:{NOVA_B}": "s02"}}))
    return p


def _env(work: Path, sid: str, role: str, placement: Path, extra: dict) -> dict:
    db = work / "relay.db"
    # One SESSION_SECRET for both on purpose: a data Cell must still ignore control's session cookie.
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(work / "home"), "TMPDIR": str(work),
            "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "", "ALLOW_ANONYMOUS_ADMIN": "0",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "CHATTERLY_DB_URL": f"sqlite:///{db}",
            "SESSION_SECRET": "cell-actor-session", "CHATTER_SESSION_SECRET": "cell-actor-chatter",
            "ADMIN_PASSWORD": "cell-actor-admin", "VAPID_KEY_FILE": str(work / "vapid.pem"),
            "OI_CELL_MAP": str(placement), "OI_CELL_ID": sid, "OI_CELL_ROLE": role, "OI_EPOCH": "1", **extra}


def _boot(root: Path, sid: str, role: str, placement: Path, extra: dict, port: int):
    work = root / sid
    (work / "home").mkdir(parents=True, exist_ok=True)
    log = open(work / "relay.log", "ab")
    return subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=SERVICE, env=_env(work, sid, role, placement, extra),
                            stdout=log, stderr=subprocess.STDOUT), log


@contextlib.contextmanager
def _cells():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = _placement(root)
        pub = actor_token.new_key(root / "keys")
        ports = {"s01": _port(), "s02": _port()}
        extra = {
            "s01": {"OI_ACCOUNTS": "", "OI_CELL_COPY_KEYS": f"s02:{hashlib.sha256(KEY.encode()).hexdigest()}",
                    "OI_CELL_ACTOR_KEY_FILE": str(root / "keys/actor_ed25519.pem")},
            "s02": {"OI_ACCOUNTS": f"onlyfans:{NOVA_A},onlyfans:{NOVA_B}", "OI_CELL_COPY_KEY": KEY,
                    "OI_CELL_CONTROL_URL": f"http://127.0.0.1:{ports['s01']}", "OI_CELL_ACTOR_PUBKEY": pub,
                    "SHARE_TOKEN": SHARE}}
        roles = {"s01": "control", "s02": "data"}
        procs = {}

        def up(sid: str) -> None:
            procs[sid] = _boot(root, sid, roles[sid], placement, extra[sid], ports[sid])

        def live(sid: str) -> None:
            deadline = time.monotonic() + 240
            while True:
                assert procs[sid][0].poll() is None, (root / sid / "relay.log").read_text()[-3000:]
                with contextlib.suppress(OSError):
                    if _ask_h(ports[sid], "GET", "/livez")[0] == 200:
                        return
                assert time.monotonic() < deadline, "relay never answered /livez"
                time.sleep(0.5)

        def stop(sid: str) -> None:
            p, log = procs.pop(sid)
            p.terminate()
            try:
                p.wait(30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            log.close()

        def restart(sid: str, between):
            stop(sid)
            got = between()
            up(sid)
            live(sid)
            return got

        try:
            for sid in roles:
                up(sid)
            for sid in roles:
                live(sid)
            yield ports, {sid: str(root / sid / "relay.db") for sid in ports}, root, placement, restart
        finally:
            for sid in list(procs):
                stop(sid)


def _cookies(headers_list) -> dict[str, str]:
    out = {}
    for v in headers_list:
        name, _, rest = v.partition("=")
        out[name] = rest.split(";", 1)[0]
    return out


def _set_cookies(h) -> dict[str, str]:
    return _cookies(h.get_all("set-cookie") or [])


def _jar(**c: str) -> dict:
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in c.items() if v)}


def _ask_h(port: int, method: str, path: str, headers: dict | None = None, body: dict | None = None):
    import urllib.error
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _err(raw: bytes):
    try:
        d = json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        return raw[:120].decode(errors="replace")
    return d.get("error") if isinstance(d, dict) else d


def _renew(ctl: int, cookies: dict) -> str:
    st, h, raw = _ask_h(ctl, "POST", "/auth/actor", _jar(**cookies))
    assert st == 200, (st, raw[:300])
    tok = _set_cookies(h)["oi_actor"]
    assert tok, "renewal set no oi_actor"
    return tok


def _read(cell: int, tok: str | None, account: str = NOVA_A, **cookies: str):
    st, _h, raw = _ask_h(cell, "GET", f"/admin/chats/recent?account_id={account}&limit=5",
                         _jar(oi_actor=tok or "", **cookies))
    return st, _err(raw) if st != 200 else None


def _forge(root: Path, claims: dict) -> str:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key((root / "keys/actor_ed25519.pem").read_bytes(), password=None)
    payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    return f"{actor_token._b64(payload)}.{actor_token._b64(key.sign(payload))}"


def _claims(tok: str) -> dict:
    return json.loads(actor_token._unb64(tok.split(".")[0]))


def case_one_sign_in_on_control_reads_on_the_data_cell() -> None:
    with _cells() as (port, db, root, placement, _restart):
        ctl, cell = port["s01"], port["s02"]
        st, h, raw = _ask_h(ctl, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
        assert st == 200, (st, raw[:300])
        owner = json.loads(raw)["user_id"]
        session = _set_cookies(h)["chatterly_session"]
        with contextlib.closing(sqlite3.connect(db["s01"], timeout=30)) as c, c:
            c.executemany("INSERT INTO accounts (id, is_active_default) VALUES (?, 1)", [(NOVA_A,), (NOVA_B,)])
            c.executemany("INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?)",
                          [(owner, NOVA_A), (owner, NOVA_B)])
        gen = _q(db["s01"], "SELECT grant_gen FROM agency_copy_version")[0][0]
        _wait(lambda: _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0] == gen)

        assert _read(cell, None)[0] == 401, "no cookie stops at the share-token gate, as today"
        assert _read(cell, None, chatterly_session=session) == (401, "actor_missing"), \
            ("data Cell honoured control's session cookie", _read(cell, None, chatterly_session=session))
        tok = _renew(ctl, {"chatterly_session": session})
        cl = _claims(tok)
        assert cl["kind"] == "user" and cl["id"] == owner == cl["eff_id"] and cl["ro"] is False, cl
        assert cl["agency"] == "acme" and cl["exp"] - cl["iat"] <= 900 and cl["ggen"] == gen, cl
        with contextlib.closing(sqlite3.connect(db["s02"], timeout=30)) as c, c:
            c.execute(
                "INSERT INTO priority_mass_runs (id, account_id, status, text, media_json, previews_json, "
                "price_cents, locked_text, audience_json, created_at) VALUES (41, ?, 'running', '', '[]', "
                "'[]', 0, 0, '{}', CURRENT_TIMESTAMP)", (NOVA_B,))
            c.execute(
                "INSERT INTO transactions (id, account_id, kind, amount_cents, currency, occurred_at, ingested_at) "
                "VALUES (42, ?, 'tip', 100, 'USD', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (NOVA_B,))
        headers = _jar(oi_actor=tok)
        scoped_sale = f"/admin/ingest/transactions/42/attribute?account_id={NOVA_A}"
        st, _h, raw = _ask_h(cell, "POST", scoped_sale, headers, {"employee_id": "no_one"})
        assert st == 404, (st, raw[:300])
        scoped_run = f"/admin/priority-mass/runs/41/cancel?account_id={NOVA_A}"
        st, _h, raw = _ask_h(cell, "POST", scoped_run, headers)
        assert st == 404, (st, raw[:300])
        st, _h, raw = _ask_h(cell, "POST", f"/admin/priority-mass/runs?account_id={NOVA_A}", headers,
                             {"account_id": NOVA_B, "text": "scoped create", "user_lists": ["fans"]})
        assert (st, _err(raw)) == (400, "account_conflict"), (st, raw[:300])
        assert _q(db["s02"], "SELECT id FROM priority_mass_runs") == [(41,)]
        assert _q(db["s02"], "SELECT id FROM scheduled_jobs WHERE kind = 'priority_mass'") == []
        assert _q(db["s02"], "SELECT status FROM priority_mass_runs WHERE id=41") == [("running",)]
        assert _q(db["s02"], "SELECT attributed_employee_id FROM transactions WHERE id=42") == [(None,)]
        assert _read(cell, tok) == (200, None), _read(cell, tok)
        st, _h, raw = _ask_h(ctl, "GET", "/auth/me", _jar(oi_actor=tok))
        assert st == 200 and json.loads(raw) is None, ("Control requires a user session", st, raw[:200])

        st, _h, raw = _ask_h(ctl, "POST", "/auth/actor", _jar(oi_actor=tok))
        assert (st, _err(raw)) == (401, "session_required"), "a token alone must not renew itself"
        st, _h, _raw = _ask_h(cell, "POST", "/auth/actor", _jar(chatterly_session=session, oi_actor=tok))
        assert st == 404, ("a data Cell must not mint", st)

        now = int(time.time())
        expired = _forge(root, {**cl, "iat": now - 2000, "exp": now - 1100})
        assert _read(cell, expired) == (401, "actor_expired"), _read(cell, expired)
        import urllib.request
        issued = int(time.time())
        short = _forge(root, {**cl, "iat": issued, "exp": issued + 3})
        req = urllib.request.Request(f"http://127.0.0.1:{cell}/events", headers=_jar(oi_actor=short))
        with urllib.request.urlopen(req, timeout=5) as stream:
            assert stream.status == 200 and stream.readline().startswith(b":")
            stream.read()
            assert time.time() >= issued + 3
        too_long = _forge(root, {**cl, "iat": now, "exp": now + 3600})
        assert _read(cell, too_long) == (401, "actor_invalid")
        other = _forge(root, {**cl, "agency": "other"})
        assert _read(cell, other) == (401, "actor_invalid")
        tampered = tok.split(".")[0][:-2] + "AA." + tok.split(".")[1]
        assert _read(cell, tampered) == (401, "actor_invalid")
        ahead = _forge(root, {**cl, "ggen": gen + 5})
        assert _read(cell, ahead) == (200, None), "a token newer than the Cell's copy is identity, not grants"

        with contextlib.closing(sqlite3.connect(db["s01"], timeout=30)) as c, c:
            c.execute("DELETE FROM user_accounts WHERE account_id = ?", (NOVA_B,))
        gen2 = _q(db["s01"], "SELECT grant_gen FROM agency_copy_version")[0][0]
        assert gen2 > gen
        _wait(lambda: _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0] == gen2)
        assert _read(cell, tok) == (401, "actor_stale"), _read(cell, tok)
        tok2 = _renew(ctl, {"chatterly_session": session})
        assert _read(cell, tok2) == (200, None)
        assert _read(cell, tok2, NOVA_B)[0] == 403, "revoked grant still readable"
        st, _h, raw = _ask_h(cell, "GET", "/admin/chats/recent?limit=5", _jar(oi_actor=tok2))
        assert st == 200, (st, raw[:200])
        assert json.loads(raw)["partial"] == [f"onlyfans:{NOVA_A}"], raw[:200]

        st, _h, raw = _ask_h(cell, "GET", f"/admin/chats/recent?account_id={NOVA_A}&limit=5")
        assert (st, _err(raw)) == (401, "actor_missing"), (st, raw[:80])
        st, _h, _raw = _ask_h(cell, "GET", f"/admin/chats/recent?account_id={NOVA_A}&limit=5&t={SHARE}")
        assert st == 401, "share token alone is not a principal (anonymous off)"

        st, h, _raw = _ask_h(ctl, "POST", "/auth/logout", _jar(chatterly_session=session, oi_actor=tok2))
        assert st == 200 and _set_cookies(h).get("oi_actor") == '""', h.get_all("set-cookie")


def case_chatter_and_impersonation_tokens() -> None:
    with _cells() as (port, db, root, placement, _restart):
        ctl, cell = port["s01"], port["s02"]
        st, h, raw = _ask_h(ctl, "POST", "/auth/register", body={"username": "acmeowner", "password": "Owner-Pw-77"})
        owner, session = json.loads(raw)["user_id"], _set_cookies(h)["chatterly_session"]
        st, h, raw = _ask_h(ctl, "POST", "/auth/register", body={"username": "acmeboss", "password": "Founder-Pw-77"})
        assert st == 200, (st, raw[:300])
        founder = _set_cookies(h)["chatterly_session"]
        with contextlib.closing(sqlite3.connect(db["s01"], timeout=30)) as c, c:
            c.executemany("INSERT INTO accounts (id, is_active_default) VALUES (?, 1)", [(NOVA_A,), (NOVA_B,)])
            c.executemany("INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?)",
                          [(owner, NOVA_A), (owner, NOVA_B)])
        st, _h, raw = _ask_h(ctl, "POST", "/admin/chatters/invite", _jar(chatterly_session=session))
        assert st == 200, (st, raw[:300])
        invite = json.loads(raw)["token"]
        st, h, raw = _ask_h(ctl, "POST", f"/chatter/register?token={invite}",
                            body={"username": "ann", "password": "Chatter-Pw-77"})
        assert st == 200, (st, raw[:300])
        chatter_id = json.loads(raw)["chatter_id"]
        chatter = _set_cookies(h)["chatterly_chatter_session"]
        st, _h, raw = _ask_h(ctl, "PUT", f"/admin/chatters/{chatter_id}/account-access",
                             _jar(chatterly_session=session), {"account_ids": [NOVA_A]})
        assert st == 200, (st, raw[:300])
        gen = _q(db["s01"], "SELECT grant_gen FROM agency_copy_version")[0][0]
        _wait(lambda: _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0] == gen)

        ctok = _renew(ctl, {"chatterly_chatter_session": chatter})
        assert _claims(ctok)["kind"] == "chatter" and _claims(ctok)["id"] == chatter_id
        assert _read(cell, ctok) == (200, None), _read(cell, ctok)
        assert _read(cell, ctok, NOVA_B)[0] == 403, "chatter restriction not applied on the data Cell"
        st, _h, raw = _ask_h(ctl, "GET", "/chatter/me", _jar(oi_actor=ctok))
        assert st == 200 and json.loads(raw)["chatter_id"] == chatter_id, (st, raw[:200])
        st, _h, raw = _ask_h(ctl, "GET", "/auth/cells", _jar(oi_actor=ctok))
        got = json.loads(raw)
        assert st == 200 and got["actor"] == f"chatter:{chatter_id}" and got["placement_gen"] == 1, (st, raw[:300])
        assert got["grant_gen"] == gen and got["cells"] == ["s02"] and got["control"] == "s01", got
        assert got["accounts"] == [{"platform": "onlyfans", "account_id": NOVA_A, "cell": "s02"}], got
        st, _h, raw = _ask_h(ctl, "GET", "/auth/cells", _jar(chatterly_session=session))
        got = json.loads(raw)
        assert st == 200 and got["actor"] == f"user:{owner}" and got["cells"] == ["s02"], (st, raw[:300])
        assert sorted(a["account_id"] for a in got["accounts"]) == sorted([NOVA_A, NOVA_B]), got
        doc = json.loads(placement.read_bytes())
        doc["accounts"][f"fansly:{NOVA_B}"] = doc["accounts"].pop(f"onlyfans:{NOVA_B}")
        placement.write_text(json.dumps(doc))
        st, _h, raw = _ask_h(ctl, "GET", "/auth/cells", _jar(chatterly_session=session))
        assert st == 200, (st, raw[:300])
        assert {"platform": "fansly", "account_id": NOVA_B, "cell": "s02"} in json.loads(raw)["accounts"]
        doc["accounts"][f"onlyfans:{NOVA_B}"] = doc["accounts"].pop(f"fansly:{NOVA_B}")
        placement.write_text(json.dumps(doc))
        assert _ask_h(ctl, "GET", "/auth/cells")[0] == 401
        assert _ask_h(cell, "GET", "/auth/cells", _jar(oi_actor=ctok))[0] == 404, "a data Cell must not answer"
        st, h, _raw = _ask_h(ctl, "POST", "/chatter/logout", _jar(chatterly_chatter_session=chatter, oi_actor=ctok))
        assert st == 200 and _set_cookies(h).get("oi_actor") == '""', "chatter logout left oi_actor"

        st, h, raw = _ask_h(ctl, "POST", "/admin/impersonate", _jar(chatterly_session=founder),
                            {"user_id": owner, "admin_password": "cell-actor-admin"})
        assert st == 200 and _set_cookies(h).get("oi_actor") == '""', (st, raw[:200])
        imp = _set_cookies(h)["chatterly_impersonate"]
        itok = _renew(ctl, {"chatterly_session": founder, "chatterly_impersonate": imp})
        cl = _claims(itok)
        assert cl["ro"] is True and cl["eff_id"] == owner and cl["id"] != owner, cl
        assert _read(cell, itok) == (200, None), "impersonated read on the data Cell"
        st, _h, raw = _ask_h(cell, "PATCH", f"/admin/accounts/{NOVA_A}", _jar(oi_actor=itok), {"color": "#123456"})
        assert st == 403 and b"read-only while impersonating" in raw, (st, raw[:200])
        st, _h, raw = _ask_h(ctl, "GET", "/auth/me", _jar(chatterly_session=founder, chatterly_impersonate=imp, oi_actor=itok))
        assert json.loads(raw)["impersonating"] is not None, raw[:200]
        st, h, _raw = _ask_h(ctl, "DELETE", "/admin/impersonate", _jar(chatterly_session=founder,
                                                                         chatterly_impersonate=imp))
        assert st == 200 and _set_cookies(h).get("oi_actor") == '""', "impersonate stop left the read-only token"


def _backup(src: str, dst: str) -> None:
    with contextlib.closing(sqlite3.connect(src, timeout=30)) as a, contextlib.closing(sqlite3.connect(dst)) as b:
        a.backup(b)


def _restore_control(db: str, backup: str) -> int:
    for tail in ("-wal", "-shm"):
        Path(db + tail).unlink(missing_ok=True)
    _backup(backup, db)
    out = subprocess.run([sys.executable, "agency_copy.py", "--bump-epoch", db], cwd=SERVICE, check=True,
                         capture_output=True, text=True).stdout
    return int(out.split()[-1])


def _sse_status(cell: int, tok: str) -> int:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{cell}/events",
                                                           headers=_jar(oi_actor=tok)), timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def case_older_control_restore_keeps_owner_rows_and_denies_access() -> None:
    with _cells() as (port, db, root, placement, restart):
        ctl, cell = port["s01"], port["s02"]
        old, newer = str(root / "control-old.db"), str(root / "control-newer.db")
        _backup(db["s01"], old)
        st, h, raw = _ask_h(ctl, "POST", "/auth/register", body={"username": "lateowner", "password": "Owner-Pw-77"})
        assert st == 200, (st, raw[:300])
        owner, session = json.loads(raw)["user_id"], _set_cookies(h)["chatterly_session"]
        with contextlib.closing(sqlite3.connect(db["s01"], timeout=30)) as c, c:
            c.execute("INSERT INTO accounts (id, is_active_default) VALUES (?, 1)", (NOVA_A,))
            c.execute("INSERT INTO user_accounts (user_id, account_id) VALUES (?, ?)", (owner, NOVA_A))
        gen = _q(db["s01"], "SELECT grant_gen FROM agency_copy_version")[0][0]
        _wait(lambda: _q(db["s02"], "SELECT grant_gen FROM cell_meta")[0][0] == gen)
        with contextlib.closing(sqlite3.connect(db["s02"], timeout=30)) as c, c:
            c.execute("INSERT INTO agency_notifications (agency_user_id, kind, text, created_at)"
                      " VALUES (?, 'creator', 'Nova expired', '2026-11-27')", (owner,))
        tok = _renew(ctl, {"chatterly_session": session})
        assert _read(cell, tok) == (200, None) and _sse_status(cell, tok) == 200
        _backup(db["s01"], newer)

        epoch = restart("s01", lambda: _restore_control(db["s01"], old))
        _wait(lambda: _q(db["s02"], "SELECT copy_epoch FROM cell_meta")[0][0] == epoch, 30)
        assert _q(db["s01"], "SELECT 1 FROM users WHERE id = ?", (owner,)) == [], "restore kept the owner"
        assert _q(db["s02"], "SELECT 1 FROM users WHERE id = ?", (owner,)) == [(1,)]
        assert _q(db["s02"], "SELECT text FROM agency_notifications WHERE agency_user_id = ?", (owner,)) == [
            ("Nova expired",)], "Cell-local CASCADE child deleted by the older copy"
        assert _q(db["s02"], "SELECT user_id FROM agency_copy_missing_owners") == [(owner,)]
        assert _read(cell, tok) == (401, "actor_revoked"), _read(cell, tok)
        assert _sse_status(cell, tok) == 401
        st, h, _raw = _ask_h(cell, "POST", "/auth/sign-in", body={"username": "lateowner", "password": "Owner-Pw-77"})
        assert st != 200 and not _set_cookies(h), ("signed in on the data Cell", st)
        st, h, _raw = _ask_h(ctl, "POST", "/auth/sign-in", body={"username": "lateowner", "password": "Owner-Pw-77"})
        assert st != 200 and not _set_cookies(h).get("chatterly_session"), ("signed in on the restored Control", st)
        lines = [ln for ln in (root / "s02/relay.log").read_text().splitlines() if "agency_copy_owner_missing" in ln]
        assert len(lines) == 1 and f"owner={owner} copy={epoch}." in lines[0], lines

        epoch = restart("s01", lambda: _restore_control(db["s01"], newer))
        _wait(lambda: _q(db["s02"], "SELECT copy_epoch FROM cell_meta")[0][0] == epoch, 30)
        assert _q(db["s02"], "SELECT user_id FROM agency_copy_missing_owners") == []
        assert _read(cell, tok) == (200, None), _read(cell, tok)
        assert _sse_status(cell, tok) == 200
        assert _q(db["s02"], "SELECT text FROM agency_notifications WHERE agency_user_id = ?", (owner,)) == [
            ("Nova expired",)]
        lines = [ln for ln in (root / "s02/relay.log").read_text().splitlines() if "agency_copy_owner_missing" in ln]
        assert len(lines) == 1, lines


def case_data_cell_holding_the_private_key_refuses_to_start() -> None:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = _placement(root)
        actor_token.new_key(root / "keys")
        p, log = _boot(root, "s02", "data", placement, {
            "OI_ACCOUNTS": f"onlyfans:{NOVA_A}", "OI_CELL_ACTOR_KEY_FILE": str(root / "keys/actor_ed25519.pem")},
            _port())
        try:
            assert p.wait(120) != 0
        finally:
            log.close()
        assert "only the Control cell may hold the Actor token private key" in (root / "s02/relay.log").read_text()


_harness.run()
