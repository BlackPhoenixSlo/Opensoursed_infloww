from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from db.models import Account, Chat, Fan, Message, PriorityMassRun, Transaction, User, UserAccount  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
REGISTRY = SERVICE / "sessions" / "accounts"
NOVA_A, NOVA_B = "900539700124344320", "900539700124344321"
MOVED_ID = "876543210"
FANS = ("900539700124344320", "900539700124344321")
MSGS = ("900539700124344520", "900539700124344521")
OWNER, PASSWORD = "cell_owner", "cell-owner-pw"
OWNER_ID = uuid.uuid4().hex


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ask(port: int, method: str, path: str, headers: dict | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _error(raw: bytes) -> str | None:
    try:
        detail = json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        return None
    return detail.get("error") if isinstance(detail, dict) else None


class _Bare(str):
    pass


def _exact(raw: bytes):
    return json.loads(raw, parse_int=_Bare, parse_float=_Bare)


class _Cell:
    def __init__(self, sid: str, aid: str, epoch: int, root: Path, placement: Path, pub: str):
        self.sid, self.aid = sid, aid
        self.work = root / sid
        (self.work / "home").mkdir(parents=True)
        self.db = self.work / "relay.db"
        self.port = _port()
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.work / "home"),
                    "TMPDIR": str(self.work), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
                    "DATABASE_URL": f"sqlite+aiosqlite:///{self.db}", "CHATTERLY_DB_URL": f"sqlite:///{self.db}",
                    "SESSION_SECRET": "cell-test-session", "CHATTER_SESSION_SECRET": "cell-test-chatter",
                    "ADMIN_PASSWORD": "cell-test-admin", "VAPID_KEY_FILE": str(self.work / "vapid.pem"),
                    "OI_CELL_MAP": str(placement), "OI_CELL_ID": sid, "OI_CELL_ROLE": "data",
                    "OI_ACCOUNTS": f"onlyfans:{aid}", "OI_EPOCH": str(epoch), "OI_CELL_ACTOR_PUBKEY": pub}
        self.proc = self.log = None

    def start(self) -> None:
        self.log = open(self.work / "relay.log", "ab")
        self.proc = subprocess.Popen(["nice", "-n", "10", sys.executable, "-m", "uvicorn", "server:app",
                                      "--host", "127.0.0.1", "--port", str(self.port)],
                                     cwd=SERVICE, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)

    def wait(self) -> None:
        deadline = time.monotonic() + 240
        while True:
            assert self.proc.poll() is None, (self.work / "relay.log").read_text()[-3000:]
            try:
                if _ask(self.port, "GET", "/livez")[0] == 200:
                    return
            except OSError:
                pass
            assert time.monotonic() < deadline, f"{self.sid} never answered /livez"
            time.sleep(0.5)

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

    def orm(self) -> Session:
        return Session(create_engine(f"sqlite:///{self.db}"))

    def sql(self, q: str, *args):
        with contextlib.closing(sqlite3.connect(self.db)) as c, c:
            return c.execute(q, args).fetchall()


@contextlib.contextmanager
def _two_cells():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        placement = root / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s02": {"box": "b1", "epoch": 3, "relay": "x", "role": "data", "state": "live"},
                      "s03": {"box": "b1", "epoch": 1, "relay": "y", "role": "data", "state": "live"}},
            "accounts": {f"onlyfans:{NOVA_A}": "s02", f"onlyfans:{NOVA_B}": "s03"}}))
        import actor_token
        pub = actor_token.new_key(root / "actor")
        cells = {"s02": _Cell("s02", NOVA_A, 3, root, placement, pub),
                 "s03": _Cell("s03", NOVA_B, 1, root, placement, pub)}
        try:
            for c in cells.values():
                c.start()
            for c in cells.values():
                c.wait()
            yield cells, root / "actor"
        finally:
            for c in cells.values():
                c.stop()


@contextlib.contextmanager
def _scheduled_sends_registry():
    others = [p.name for p in REGISTRY.iterdir() if p.name not in (NOVA_A, NOVA_B, MOVED_ID)] if REGISTRY.is_dir() else []
    if others:
        print(f"[skip] scheduled-sends resolves X-Account-Id in {REGISTRY}, which holds other Creators: not touched")
        yield False
        return
    made = []
    try:
        for aid in (NOVA_A, NOVA_B, MOVED_ID):
            d = REGISTRY / aid
            if not d.exists():
                d.mkdir(parents=True)
                made.append(d)
                (d / "meta.json").write_text(json.dumps({"id": aid, "nickname": f"Nova {aid[-3:]}",
                                                         "platform": "onlyfans"}))
        yield True
    finally:
        for d in made:
            shutil.rmtree(d, ignore_errors=True)


def _seed(cells: dict[str, _Cell]) -> None:
    now = datetime.utcnow()
    for c in cells.values():
        with c.orm() as s, s.begin():
            s.execute(text("UPDATE agency_copy_gate SET open = 1"))
            s.add(User(id=OWNER_ID, username=OWNER, password=PASSWORD))
            for aid in (NOVA_A, NOVA_B):
                s.add(Account(id=aid, nickname=f"Nova {aid[-3:]}", color="#aaaaaa"))
            s.flush()
            for aid in (NOVA_A, NOVA_B):
                s.add(UserAccount(user_id=OWNER_ID, account_id=aid))
            s.flush()
            s.execute(text("UPDATE agency_copy_gate SET open = 0"))
            s.execute(text("UPDATE cell_meta SET grant_gen = 1, confirmed_at = :at"), {"at": now.isoformat()})
        with c.orm() as s, s.begin():
            s.add(Transaction(id=1, account_id=c.aid, kind="tip", amount_cents=500, currency="USD", occurred_at=now))
            s.add(PriorityMassRun(id=1, account_id=c.aid, status="running", text="hi", created_at=now))
    a = cells["s02"]
    with a.orm() as s, s.begin():
        s.add(Transaction(id=2, account_id=NOVA_B, kind="tip", amount_cents=700, currency="USD", occurred_at=now))
        s.add(PriorityMassRun(id=2, account_id=NOVA_B, status="running", text="stray", created_at=now))
        for i, (fid, mid) in enumerate(zip(FANS, MSGS)):
            s.add(Fan(account_id=NOVA_A, fan_id=int(fid), of_username=f"fan{i}"))
            s.add(Chat(account_id=NOVA_A, fan_id=int(fid), last_message_id=int(mid),
                       last_message_at=now - timedelta(minutes=i), last_message_preview=f"m{i}"))
            s.add(Message(account_id=NOVA_A, fan_id=int(FANS[0]), message_id=int(mid), direction="in",
                          sender_name="fan", body=f"m{i}", created_at=now - timedelta(minutes=i)))


def _actor_cookie(key_dir: Path) -> str:
    import actor_token
    old = {k: os.environ.get(k) for k in ("OI_CELL_ROLE", "OI_CELL_ACTOR_KEY_FILE", "OI_CELL_ACTOR_PUBKEY")}
    os.environ.update({"OI_CELL_ROLE": "control", "OI_CELL_ACTOR_KEY_FILE": str(key_dir / "actor_ed25519.pem")})
    os.environ.pop("OI_CELL_ACTOR_PUBKEY", None)
    try:
        actor_token.configure("acme")
        return f"{actor_token.COOKIE}={actor_token.mint('user', OWNER_ID, ggen=1)}"
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def _not_owner(st, raw, label):
    assert st == 409 and _error(raw) == "not_owner", (label, st, raw[:300])


def _amendments(a: _Cell, b: _Cell, auth: dict) -> None:
    at = lambda c, i: c.sql("SELECT attributed_employee_id FROM transactions WHERE id = ?", i)[0][0]  # noqa: E731
    hdr = lambda aid: {**auth, "X-Account-Id": aid}  # noqa: E731
    one, batch = "/admin/ingest/transactions/1/attribute", "/admin/ingest/transactions/attribute"

    st, _h, raw = _ask(a.port, "POST", f"{one}?account_id={NOVA_A}", hdr(NOVA_A),
                       {"employee_id": "no_one", "account_id": NOVA_A})
    assert st == 200 and json.loads(raw)["account_id"] == NOVA_A, ("single via A", st, raw[:300])
    assert (at(a, 1), at(b, 1)) == (0, None), "single: only A's tx 1"

    st, _h, raw = _ask(b.port, "POST", batch, hdr(NOVA_B), {"employee_id": "no_one", "tx_ids": [1], "account_id": NOVA_B})
    assert st == 200 and json.loads(raw)["updated"] == 1, ("batch via B", st, raw[:300])
    st, _h, raw = _ask(a.port, "POST", batch, hdr(NOVA_A), {"employee_id": None, "tx_ids": [1], "account_id": NOVA_A})
    assert st == 200 and json.loads(raw)["tx_ids"] == [1], ("batch via A", st, raw[:300])
    assert (at(a, 1), at(b, 1)) == (None, 0), "batch: each Cell's tx 1 moved only by its own call"

    for path, body in (("/admin/ingest/transactions/2/attribute", {"employee_id": "no_one", "account_id": NOVA_A}),
                       (batch, {"employee_id": "no_one", "tx_ids": [1, 2], "account_id": NOVA_A})):
        st, _h, raw = _ask(a.port, "POST", path, hdr(NOVA_A), body)
        assert st == 404 and json.loads(raw)["detail"] == "sale not found", ("another Creator's tx id", path, st, raw)
    assert (at(a, 1), at(a, 2)) == (None, None), "a 404 batch writes nothing"

    st, _h, raw = _ask(a.port, "POST", batch, hdr(NOVA_B), {"employee_id": "no_one", "tx_ids": [1], "account_id": NOVA_B})
    _not_owner(st, raw, "B's account named at A")
    st, _h, raw = _ask(a.port, "POST", one, auth, {"employee_id": "no_one", "account_id": NOVA_B})
    _not_owner(st, raw, "B's account in the body only, at A")
    assert at(b, 1) == 0 and at(a, 1) is None


def _mass_runs(a: _Cell, b: _Cell, auth: dict) -> None:
    status = lambda c, i: c.sql("SELECT status FROM priority_mass_runs WHERE id = ?", i)[0][0]  # noqa: E731
    st, _h, raw = _ask(a.port, "POST", "/admin/priority-mass/runs/2/cancel", {**auth, "X-Account-Id": NOVA_A})
    assert st == 404, ("run 2 at A is B's", st, raw[:300])
    st, _h, raw = _ask(a.port, "POST", "/admin/priority-mass/runs/2/resume", {**auth, "X-Account-Id": NOVA_A})
    assert st == 404, ("resume run 2 at A is B's", st, raw[:300])
    _not_owner(*_ask(a.port, "POST", "/admin/priority-mass/runs/1/cancel", {**auth, "X-Account-Id": NOVA_B})[::2],
               "cancel naming B at A")
    _not_owner(*_ask(a.port, "GET", f"/admin/chats/recent?account_id={NOVA_B}", auth)[::2], "signed-in GET naming B by query at A")
    st, _h, raw = _ask(a.port, "POST", "/admin/priority-mass/runs/1/cancel", {**auth, "X-Account-Id": NOVA_A})
    assert st == 200 and json.loads(raw)["status"] == "cancelled" and json.loads(raw)["account_id"] == NOVA_A, \
        ("cancel A's run 1", st, raw[:300])
    assert (status(a, 1), status(a, 2), status(b, 1)) == ("cancelled", "running", "running"), "only A's run 1"


def _big_ids(a: _Cell, auth: dict, registry: bool) -> None:
    hdr = {**auth, "X-Account-Id": NOVA_A}

    def distinct(raw: bytes, ids, label):
        for i in ids:
            assert i.encode() in raw, (label, i, raw[:400])
        assert ids[0] != ids[1] and len({*ids}) == 2

    st, _h, raw = _ask(a.port, "GET", f"/admin/chats/recent?account_id={NOVA_A}", auth)
    assert st == 200, ("chats/recent", st, raw[:300])
    distinct(raw, FANS, "inbox fan ids")
    distinct(raw, MSGS, "inbox message ids")
    rows = _exact(raw)["list"]
    got = {(r["withUser"]["id"], r["lastMessage"]["id"]) for r in rows}
    assert got == set(zip(FANS, MSGS)), ("inbox pairs", got)
    assert not any(isinstance(v, _Bare) for pair in got for v in pair), ("inbox ids are JSON strings", got)

    st, _h, raw = _ask(a.port, "GET", f"/admin/messages/{NOVA_A}/{FANS[0]}", auth)
    assert st == 200, ("thread", st, raw[:300])
    distinct(raw, MSGS, "thread message ids")
    msgs = _exact(raw)["messages"]
    assert [(m["fan_id"], m["message_id"]) for m in msgs] == [(FANS[0], MSGS[1]), (FANS[0], MSGS[0])], msgs
    assert not any(isinstance(m[k], _Bare) for m in msgs for k in ("fan_id", "message_id")), ("thread ids", msgs)

    if not registry:
        return
    run_at = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for fid in FANS:
        st, _h, raw = _ask(a.port, "POST", "/api/of/v2/scheduled-sends", hdr,
                           {"fan_id": fid, "run_at": run_at, "text": f"later {fid[-3:]}"})
        assert st == 200 and fid.encode() in raw, ("send form create", fid, st, raw[:300])
        got = _exact(raw)["fan_id"]
        assert got == fid and not isinstance(got, _Bare), ("create echoes the fan id as a JSON string", raw)
    st, _h, raw = _ask(a.port, "GET", "/api/of/v2/scheduled-sends", hdr)
    assert st == 200, ("scheduled-sends list", st, raw[:300])
    distinct(raw, FANS, "scheduled-send rows")
    listed = [r["fan_id"] for r in _exact(raw)["list"]]
    assert sorted(listed) == list(FANS) and not any(isinstance(f, _Bare) for f in listed), raw
    st, _h, raw = _ask(a.port, "GET", f"/api/of/v2/scheduled-sends?fan_id={FANS[1]}", hdr)
    assert [r["fan_id"] for r in _exact(raw)["list"]] == [FANS[1]], ("filter by the adjacent id", raw)
    stored = {json.loads(p)["fan_id"] for (p,) in a.sql("SELECT payload_json FROM scheduled_jobs WHERE kind = 'scheduled_send'")}
    assert stored == {int(f) for f in FANS}, stored


def _leases(a: _Cell, b: _Cell, auth: dict) -> None:
    body = {"tab": "t1", "account_ids": [NOVA_A, NOVA_B], "selected": None, "opened": False}
    for c, other in ((a, b), (b, a)):
        st, _h, raw = _ask(c.port, "POST", "/admin/view-lease", {**auth, "X-Account-Id": c.aid}, body)
        assert st == 200 and json.loads(raw)["leased"] == [c.aid], (c.sid, st, raw[:300])
        st, _h, raw = _ask(c.port, "POST", "/admin/view-lease", {**auth, "X-Account-Id": c.aid}, body)
        assert st == 200 and json.loads(raw)["leased"] == [c.aid], ("repeat post is idempotent", c.sid, raw[:300])
        _not_owner(*_ask(c.port, "POST", "/admin/view-lease", {**auth, "X-Account-Id": other.aid}, body)[::2],
                   f"lease naming the other Creator at {c.sid}")
    st, _h, raw = _ask(a.port, "POST", "/admin/view-lease", auth, {**body, "selected": NOVA_B})
    assert st == 200 and json.loads(raw)["leased"] == [NOVA_A], ("no header: still only A's Creator", raw[:300])


def _gen_bump(b: _Cell, auth: dict) -> None:
    hdr = {**auth, "X-Account-Id": NOVA_B}
    write = ("POST", "/admin/ingest/transactions/attribute")
    st, h, _raw = _ask(b.port, "GET", f"/admin/chats/recent?account_id={NOVA_B}", auth)
    assert st == 200 and h.get("x-cell-gen") == "1", ("tab reads gen 1", st, h)
    b.stop()
    b.sql("UPDATE cell_meta SET data_gen = 2")
    b.start()
    b.wait()
    st, h, raw = _ask(b.port, *write, {**hdr, "X-Cell-Gen": "1"},
                      {"employee_id": None, "tx_ids": [1], "account_id": NOVA_B})
    assert st == 409 and _error(raw) == "stale_cell_gen", ("old tab write", st, raw[:300])
    assert h.get("x-cell-gen") == "2" and json.loads(raw)["detail"]["cell_gen"] == 2, ("new gen on the refusal", h, raw)
    assert b.sql("SELECT attributed_employee_id FROM transactions WHERE id = 1")[0][0] == 0, "refused write wrote"
    st, h, raw = _ask(b.port, *write, {**hdr, "X-Cell-Gen": "2"},
                      {"employee_id": None, "tx_ids": [1], "account_id": NOVA_B})
    assert st == 200 and h.get("x-cell-gen") == "2", ("refetched tab writes", st, raw[:300])
    assert b.sql("SELECT attributed_employee_id FROM transactions WHERE id = 1")[0][0] is None


def case_app_calls_on_two_cells() -> None:
    with _scheduled_sends_registry() as registry, _two_cells() as (cells, key_dir):
        a, b = cells["s02"], cells["s03"]
        _seed(cells)
        for c in cells.values():
            c.stop()
            c.start()
        for c in cells.values():
            c.wait()
        auth = {"Cookie": _actor_cookie(key_dir)}
        _amendments(a, b, auth)
        _mass_runs(a, b, auth)
        if registry:
            _not_owner(*_ask(a.port, "GET", f"/admin/fans/{MOVED_ID}/by-ids", auth)[::2], "moved Creator path")
            st, _h, raw = _ask(a.port, "POST", f"/admin/ingest/transactions/{MOVED_ID}/attribute", auth,
                               {"employee_id": "no_one", "account_id": MOVED_ID})
            assert st == 403 and raw == b"not your account", (st, raw[:300])
        _big_ids(a, auth, registry)
        _leases(a, b, auth)
        _gen_bump(b, auth)


_harness.run()
