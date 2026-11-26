from __future__ import annotations

import inspect
import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from unittest.mock import patch

import _harness
from _of_fixtures import VaultOF

CUTS = ("pre_write", "accepted", "after_update")
STEPS = ("first", "tick", "retry", "resend")
GOLDEN = Path(__file__).with_name("test_send_ops_kill.golden.json")

_ids = iter(range(9_700_000_000_001, 9_800_000_000_000))


class Killed(BaseException):
    pass


class Wire:
    def __init__(self, cut: str, pre_probe: Callable[[], bool] | None):
        self.cut, self.pre_probe = cut, pre_probe
        self.armed = cut in ("pre_write", "accepted")
        self.accepts: list[tuple[str, Any]] = []
        self.killed_at: str | None = None
        self.pre_seen = False
        self.before_accept = None

    def hit(self, op: str, target: Any = None) -> dict:
        if self.armed and self.cut == "pre_write":
            self.armed, self.killed_at = False, "pre_write"
            self.pre_seen = bool(self.pre_probe and self.pre_probe())
            raise Killed()
        if not self.accepts and self.before_accept:
            self.before_accept()
        self.accepts.append((op, target))
        if self.armed and self.cut == "accepted":
            self.armed, self.killed_at = False, "accepted"
            raise Killed()
        return {"id": next(_ids), "text": "", "success": True,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}

    def of_client(self, account_id: str, reads: Callable[[str, str], Any] | None = None):
        from of_client import OFClient
        c = object.__new__(OFClient)
        c.account_id = account_id
        wire = self

        def request_json(method, path, **kw):
            p = str(path)
            if _is_send(method, p):
                return wire.hit(f"{method} {p.split('/api2/v2')[-1]}", kw.get("json_body"))
            return reads(method, p) if reads else {}
        c.request_json = request_json
        c.post_json = lambda path, **kw: request_json("POST", path, **kw)
        c.put_json = lambda path, **kw: request_json("PUT", path, **kw)
        c.get_json = lambda path, **kw: request_json("GET", path, **kw)
        c.delete_json = lambda path, **kw: request_json("DELETE", path, **kw)
        return c


def _is_send(method: str, path: str) -> bool:
    tail = path.split("/api2/v2")[-1].split("?")[0]
    if method == "POST" and (tail.startswith("/chats/") and tail.endswith("/messages")
                             or tail == "/messages/queue"):
        return True
    return method == "PUT" and tail.startswith("/schedules/") and tail.endswith("/publish")


class WireOF(VaultOF):
    def __init__(self, wire: Wire, account_id: str = ""):
        super().__init__()
        self.wire, self.account_id = wire, account_id

    def send_message(self, chat_id, text, **kw) -> dict:
        res = self.wire.hit("send_message", int(chat_id))
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {**res, "text": text}

    def schedule_message(self, chat_id, text, **kw) -> dict:
        return self.wire.hit("schedule_message", int(chat_id))

    def schedule_mass_message(self, **kw) -> dict:
        return self.wire.hit("schedule_mass_message")

    def send_mass_message(self, text, **kw) -> dict:
        return self.wire.hit("send_mass_message")

    def publish_schedule(self, schedule_id) -> dict:
        return self.wire.hit("publish_schedule", schedule_id)

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}


@dataclass
class Driver:
    """One send kind. `first` makes exactly one intended send. `tick` is what the relay does on
    its own after a restart; `resend` repeats the same user request (None: no such request).
    A cut a kind cannot reach is a string: why it is n/a."""
    kind: str
    setup: Callable[[str, Wire], Awaitable[Any]]
    first: Callable[[Any], Awaitable[Any]]
    tick: Callable[[Any], Awaitable[Any]]
    resend: Callable[[Any], Awaitable[Any]] | None
    pre_write: Callable[[Any], bool] | str
    post_update: Callable[[Any], bool | Awaitable[bool]] | str


async def seed_account(aid: str, **ai_cfg) -> None:
    from db.engine import get_session
    from db.models import Account, AccountAiConfig

    async with get_session() as session:
        if await session.get(Account, aid) is None:
            session.add(Account(id=aid, nickname=aid))
        if ai_cfg:
            session.add(AccountAiConfig(account_id=aid, utc_offset=0, **ai_cfg))


def _install(ctx):
    import automation_executor as ax

    if "of" not in ctx:
        return nullcontext()

    def client(account_id):
        assert account_id == ctx["aid"], account_id
        return ctx["of"]

    return patch.object(ax, "_make_client", client)


def db_row(sql: str, args: tuple = ()):
    with sqlite3.connect(str(_harness.DB_PATH)) as c:
        return c.execute(sql, args).fetchone()


async def restart(account_id: str) -> None:
    import automation_executor as ax
    import mass_queue_api
    import sends_inflight
    from automations import send_marker_decide as smd
    smd.BOOT_TS = datetime.utcnow()
    mass_queue_api._send_keys.clear()
    with sends_inflight._lock:
        sends_inflight._open.clear()
    await ax._reconcile_orphans()
    import dm_rate
    dm_rate._reset()


def let_time_pass(account_id: str) -> None:
    past = (datetime.utcnow() - timedelta(minutes=1)).isoformat(sep=" ")
    with sqlite3.connect(str(_harness.DB_PATH)) as c:
        c.execute("DELETE FROM fan_lease WHERE account_id=?", (account_id,))
        c.execute("UPDATE fans SET automation_paused_until=NULL WHERE account_id=?", (account_id,))
        for table, col in (("funnel_state", "next_check_at"),):
            try:
                c.execute(f"UPDATE {table} SET {col}=?", (past,))
            except sqlite3.OperationalError:
                pass


async def _maybe(fn, ctx):
    try:
        out = fn(ctx)
        if inspect.isawaitable(out):
            await out
    except Killed:
        return True
    return False


@contextmanager
def _cut_after_update(wire, probe):
    import atomic_json
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

    commit = AsyncSession.commit
    execute = AsyncConnection.execute
    write = atomic_json.write_atomic

    def armed():
        return bool(wire.accepts) and wire.killed_at is None

    def cut(reached):
        assert isinstance(reached, bool), type(reached)
        if reached:
            wire.killed_at = "after_update"
            raise Killed()

    async def check():
        if armed():
            reached = probe()
            cut(await reached if inspect.isawaitable(reached) else reached)

    async def commit_and_cut(session):
        await commit(session)
        await check()

    async def execute_and_cut(conn, statement, *args, **kwargs):
        result = await execute(conn, statement, *args, **kwargs)
        if getattr(statement, "text", None) == "COMMIT":
            await check()
        return result

    def write_and_cut(*args, **kwargs):
        write(*args, **kwargs)
        if armed():
            reached = probe()
            if inspect.iscoroutine(reached):
                reached.close()
            cut(reached)

    with (patch.object(AsyncSession, "commit", commit_and_cut),
          patch.object(AsyncConnection, "execute", execute_and_cut),
          patch.object(atomic_json, "write_atomic", write_and_cut)):
        yield


@contextmanager
def _operator(account_id):
    import auth

    token = auth._request_user.set(auth.AuthedUser("u_kill", "kill_owner", frozenset({account_id})))
    try:
        yield
    finally:
        auth._request_user.reset(token)


async def _retry_all(account_id: str) -> tuple[int, list[str]]:
    import unconfirmed_sends_api as usa
    from fastapi import HTTPException

    n, refused = 0, []
    with _operator(account_id):
        try:
            rows = (await usa.list_unconfirmed_sends(account_id=account_id))["rows"]
        except HTTPException as error:
            return n, [f"list:{error.status_code}"]
        for r in rows:
            try:
                await usa.retry_unconfirmed_send(account_id=account_id, body=usa.RetryBody(
                    kind=r["kind"], fan_id=int(r["fan_id"]), mass_run_id=r["mass_run_id"],
                    since=r["since"]))
                n += 1
            except HTTPException as error:
                refused.append(f"{r['kind']}:{error.status_code}")
    return n, sorted(refused)


async def _operator_state(account_id: str) -> dict:
    import unconfirmed_sends_api as usa
    from fastapi import HTTPException

    with _operator(account_id):
        try:
            rows = (await usa.list_unconfirmed_sends(account_id=account_id))["rows"]
            unconfirmed = sorted([r["kind"], r["fan_id"], r["step"], r["state"], bool(r["hint"])] for r in rows)
        except HTTPException as error:
            unconfirmed = error.status_code
    with sqlite3.connect(_harness.DB_PATH) as conn:
        statuses = {
            table: [r[0] for r in conn.execute(
                f"SELECT status FROM {_quote(table)} WHERE account_id=? ORDER BY status", (account_id,))]
            for table, columns in _account_tables(conn) if "status" in columns
        }
    return {k: v for k, v in (statuses | {"unconfirmed": unconfirmed}).items() if v}


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _account_tables(conn):
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        columns = [name for (name,) in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))]
        if "account_id" in columns:
            yield table, columns


def _durable_send_state(account_id: str) -> tuple:
    with sqlite3.connect(_harness.DB_PATH) as conn:
        return tuple(tuple(conn.execute(
            f"SELECT * FROM {_quote(table)} WHERE account_id=? ORDER BY {', '.join(map(str, range(1, len(columns) + 1)))}",
            (account_id,))) for table, columns in _account_tables(conn))


async def run_cell(d: Driver, cut: str) -> dict:
    aid = f"sk_{d.kind}_{cut}"
    pre_probe, pre_na = (None, d.pre_write) if isinstance(d.pre_write, str) else (d.pre_write, None)
    post_probe, post_na = (None, d.post_update) if isinstance(d.post_update, str) else (d.post_update, None)

    def pre():
        return pre_probe(ctx) if pre_probe else _durable_send_state(aid) != initial

    wire = Wire(cut, pre)
    ctx = await d.setup(aid, wire)
    initial = _durable_send_state(aid) if cut == "pre_write" and pre_na else None
    before_accept = []
    if cut == "after_update" and post_na:
        wire.before_accept = lambda: before_accept.append(_durable_send_state(aid))
    by: dict[str, int] = {}

    async def step(name: str, fn) -> None:
        before = len(wire.accepts)
        with _install(ctx):
            await fn()
        by[name] = len(wire.accepts) - before

    async def _first():
        if cut == "after_update" and post_probe:
            with _cut_after_update(wire, lambda: post_probe(ctx)):
                interrupted = await _maybe(d.first, ctx)
            assert interrupted and wire.killed_at == cut, f"{d.kind}: durable update did not interrupt first send"
        else:
            await _maybe(d.first, ctx)
    await step("first", _first)

    if cut == "pre_write":
        if pre_na:
            assert wire.killed_at == cut, f"{d.kind}: n/a pre-send probe did not run"
            assert not wire.pre_seen, f"{d.kind}: n/a claim stale before send"
            mark = f"n/a: {pre_na}"
        elif wire.killed_at == "pre_write" and wire.pre_seen:
            mark = "reached"
        else:
            mark = (f"unreached: killed_at={wire.killed_at} pre_write_seen={wire.pre_seen}")
    elif cut == "accepted":
        mark = "reached" if wire.killed_at == "accepted" else f"unreached: killed_at={wire.killed_at}"
    else:
        if post_na:
            assert before_accept == [_durable_send_state(aid)], f"{d.kind}: n/a claim stale after send"
            mark = f"n/a: {post_na}"
        else:
            mark = "reached" if len(wire.accepts) == 1 else f"unreached: accepts={len(wire.accepts)}"

    await restart(aid)
    restarted = await _operator_state(aid)

    async def _tick():
        let_time_pass(aid)
        await _maybe(d.tick, ctx)
    await step("tick", _tick)
    ticked = await _operator_state(aid)

    refused: list[str] = []

    async def _retry():
        count, errors = await _retry_all(aid)
        refused.extend(errors)
        if count:
            let_time_pass(aid)
            await _maybe(d.tick, ctx)
    await step("retry", _retry)

    async def _resend():
        if d.resend is not None:
            await _maybe(d.resend, ctx)
    await step("resend", _resend)

    return {"mark": mark, "accepts": len(wire.accepts), "by": by, "restart": restarted, "tick": ticked, "retry_refused": refused}


def golden() -> dict:
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


def writing() -> bool:
    return os.environ.get("SEND_KILL_GOLDEN") == "write"


def selected(kind: str) -> bool:
    only = os.environ.get("SEND_KILL_KINDS")
    return not only or kind in only.split(",")


def unknown_kinds(known: set[str]) -> list[str]:
    only = os.environ.get("SEND_KILL_KINDS")
    return sorted(set(only.split(",")) - known) if only else []


def check_kind(d: Driver, got: dict[str, dict], store: dict) -> None:
    bad = [f"{c}: {r['mark']}" for c, r in got.items()
           if not (r["mark"] == "reached" or r["mark"].startswith("n/a: "))]
    assert not bad, f"{d.kind} cells neither reached nor n/a: {bad}"
    if writing():
        store[d.kind] = got
        return
    if os.environ.get("SEND_KILL_GOLDEN") == "print":
        print(f"SEND_KILL {d.kind} {json.dumps(got)}")
        return
    want = golden().get(d.kind)
    assert want == got, f"{d.kind} golden mismatch\n want {want}\n got  {got}"


def write_golden(store: dict) -> None:
    if not writing() or not store:
        return
    merged = {**golden(), **store}
    lines = [f' "{k}": {{\n' + ",\n".join(f'  "{c}": {json.dumps(v[c])}' for c in CUTS) + "\n }"
             for k, v in sorted(merged.items())]
    GOLDEN.write_text("{\n" + ",\n".join(lines) + "\n}\n")
