from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Any, Awaitable, Callable, NamedTuple, TypeVar

from fastapi import HTTPException

import send_tripwire

log = logging.getLogger("send-ops")

DDL = """CREATE TABLE IF NOT EXISTS send_ops (
  account TEXT NOT NULL, op_id TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL, digest TEXT NOT NULL,
  epoch INTEGER, data_gen INTEGER,
  state TEXT NOT NULL CHECK (state IN ('claimed','sent','refused','uncertain','resolved_sent','resolved_not_sent')),
  upstream_id TEXT, result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_by TEXT, resolved_at TEXT,
  PRIMARY KEY (account, op_id))"""
_NOW = "strftime('%Y-%m-%d %H:%M:%f','now')"
T = TypeVar("T")
CAPABILITY = {"composer": "send_message", "welcome_closing_ppv": "send_message", "native_schedule": "schedule_message",
              "publish_now": "publish_schedule", "manual_mass_send": "send_mass_message",
              "manual_mass_schedule": "schedule_mass_message", "vault_send": "send_message",
              **dict.fromkeys(("mass_premade", "mass_job"), "send_mass_message")}
MANUAL = frozenset({"composer", "manual_mass_send", "manual_mass_schedule", "native_schedule", "publish_now",
                    "vault_send", "restrict_ack"})
QUEUE = frozenset({"manual_mass_send", "manual_mass_schedule", "native_schedule", "mass_job", "mass_premade"})
_HELD_IDX = "CREATE INDEX IF NOT EXISTS send_ops_uncertain ON send_ops (account, target) WHERE state='uncertain'"
NO_ANCHOR = frozenset({"autoreply", "welcome_chatter", "followup", "nudge", "purchase_followup"})

_path: str | None = None


class Sent(NamedTuple):
    result: Any
    replay: bool


class SendRefused(HTTPException):
    def __init__(self, status: int, error: str, **extra):
        super().__init__(status_code=status, detail={"error": error, **extra})


def op_id(platform: str, account: str, kind: str, target: str, anchor: str, part: int = 0) -> str:
    return hashlib.sha256("|".join(("v1", platform, str(account), kind, str(target), anchor, str(part)))
                          .encode()).hexdigest()


def digest(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _connect() -> sqlite3.Connection:
    if _path is None:
        raise sqlite3.OperationalError("send_ops store not installed")
    db = sqlite3.connect(_path, timeout=30, isolation_level=None)
    db.execute("PRAGMA synchronous=NORMAL")
    return db


def install(sync_url: str) -> int:
    global _path
    _path = sync_url.split("sqlite:///", 1)[1]
    with contextlib.closing(_connect()) as db:
        db.execute(DDL)
        db.execute(_HELD_IDX)
        return db.execute(f"UPDATE send_ops SET state='uncertain', updated_at={_NOW} WHERE state='claimed'").rowcount


def _owner_epoch(platform: str, account: str) -> int:
    import cell_mode
    epoch = os.environ.get("OI_EPOCH", "")
    if not cell_mode.owned(platform, account) or not epoch.isdigit() or int(epoch) < 1:
        raise SendRefused(409, "not_owner", account=f"{platform}:{account}")
    return int(epoch)


def _capable(account: str, kind: str) -> None:
    from platforms import refusal_for_account
    if (why := refusal_for_account(account, CAPABILITY.get(kind, "send_message"))) is not None:
        raise SendRefused(501, "capability", reason=why)


def paused() -> bool:
    path = os.environ.get("OI_CELL_SEND_PERMIT")
    if not path:
        return False
    box = os.environ.get("OI_CELL_INSTANCE", "").partition(":")[0]
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read())
        until, named = doc["until"], doc["box"]
    except (OSError, ValueError, TypeError, KeyError):
        return True
    return (not box or named != box or not isinstance(until, (int, float)) or isinstance(until, bool)
            or until <= time.time())


def check_permit() -> None:
    if paused():
        raise SendRefused(503, "writes_paused")


def is_paused_refusal(e: BaseException | None) -> bool:
    while e is not None:
        if isinstance(e, SendRefused) and isinstance(e.detail, dict) and e.detail.get("error") == "writes_paused":
            return True
        e = e.__cause__ or e.__context__
    return False


def _not_held(platform: str, account: str) -> None:
    import cell_hold
    from of_write import _RUN_WRITE
    hold = cell_hold.writes_held()
    if hold is None and _RUN_WRITE.get() is not None:
        hold = cell_hold.active(platform, account)
    if hold is not None:
        raise SendRefused(409, "cell_held", why=hold.why, account=f"{platform}:{account}")


def _claim(account: str, op: str, kind: str, target: str, dig: str, epoch: int) -> Sent | None:
    import cell_mode
    try:
        db = _connect()
    except sqlite3.Error as e:
        raise SendRefused(503, "claim_failed", op_id=op) from e
    with contextlib.closing(db):
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, digest, result FROM send_ops WHERE account=? AND op_id=?",
                             (account, op)).fetchone()
            again = row is not None and row[1] == dig and row[0] == "refused"
            if (row is None or again) and kind not in MANUAL and db.execute(
                    "SELECT 1 FROM send_ops WHERE account=? AND target=? AND state='uncertain' LIMIT 1",
                    (account, target)).fetchone():
                db.execute("ROLLBACK")
                raise SendRefused(409, "fan_held", target=target)
            if row is None:
                db.execute(f"INSERT INTO send_ops (account, op_id, kind, target, digest, epoch, data_gen, state,"
                           f" attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'claimed',0,{_NOW},{_NOW})",
                           (account, op, kind, target, dig, epoch, cell_mode.data_gen()))
            elif again:
                db.execute(f"UPDATE send_ops SET state='claimed', epoch=?, updated_at={_NOW}"
                           " WHERE account=? AND op_id=?", (epoch, account, op))
            db.execute("COMMIT")
        except sqlite3.Error as e:
            with contextlib.suppress(sqlite3.Error):
                db.execute("ROLLBACK")
            raise SendRefused(503, "claim_failed", op_id=op) from e
    if row is None or again:
        return None
    state, have, result = row
    if have != dig:
        raise SendRefused(409, "op_conflict", op_id=op)
    if state in ("sent", "resolved_sent"):
        return Sent(json.loads(result) if result else None, True)
    raise SendRefused(409, "op_pending" if state == "claimed" else "op_uncertain", op_id=op, state=state)


def _finish(account: str, op: str, state: str, budget: send_tripwire.Budget, result: Any = None) -> None:
    head = result[0] if isinstance(result, (list, tuple)) and result else result
    upstream = head.get("id") if isinstance(head, dict) else None
    try:
        with contextlib.closing(_connect()) as db:
            db.execute(f"UPDATE send_ops SET state=?, upstream_id=?, result=?, attempts=attempts+?, updated_at={_NOW}"
                       " WHERE account=? AND op_id=? AND state='claimed'",
                       (state, None if upstream is None else str(upstream),
                        None if result is None else json.dumps(result, default=str), budget.sent, account, op))
    except sqlite3.Error:
        log.exception("send_ops: op %s stays claimed (boot turns it uncertain); its %s mark failed", op, state)


def _uncertain(e: Exception, op: str) -> HTTPException:
    if isinstance(e, HTTPException):
        detail = e.detail if isinstance(e.detail, dict) else {"upstream_body": e.detail}
        return HTTPException(status_code=e.status_code, headers=e.headers,
                             detail={**detail, "op_state": "uncertain", "op_id": op})
    return HTTPException(status_code=502, detail={"upstream_status": "uncertain", "op_state": "uncertain",
                                                  "op_id": op})


def pre_wire(e: BaseException | None) -> bool:
    import of_pacing
    import proxies
    from of_client import OFDeniedError
    known = (OFDeniedError, of_pacing.SendDispatchExpired, send_tripwire.UnclaimedSend, proxies.NoProxyRefused,
             proxies.EgressRefused)
    while e is not None:
        if isinstance(e, known):
            return True
        e = e.__cause__
    return False


def anchor(request) -> str | None:
    return request.headers.get("x-op-id") if os.environ.get("OI_CELL_MAP") else None


def part(headers) -> int:
    raw = headers.get("x-op-part") or "0"
    if not raw.isdigit():
        raise SendRefused(400, "bad_op_part")
    return int(raw)


class Claim:
    __slots__ = ("account", "op", "budget", "wire_state", "result")

    def __init__(self, account: str, op: str):
        self.account, self.op, self.budget = account, op, send_tripwire.Budget(op)
        self.wire_state, self.result = "unsent", None

    def _failed(self, e: Exception) -> Exception:
        self.wire_state = "failed"
        if self.budget.upstream_refused() if self.budget.sent else pre_wire(e):
            _finish(self.account, self.op, "refused", self.budget)
            return e
        _finish(self.account, self.op, "uncertain", self.budget)
        return _uncertain(e, self.op)

    def wire(self, send_fn: Callable[[], Any]) -> Any:
        token = send_tripwire.claim.set(self.budget)
        try:
            self.result = send_fn()
        except Exception as e:
            if (out := self._failed(e)) is e:
                raise
            raise out from e
        finally:
            send_tripwire.claim.reset(token)
        self.wire_state = "ok"
        return self.result

    async def awire(self, send_fn: Callable[[], Awaitable[Any]]) -> Any:
        token = send_tripwire.claim.set(self.budget)
        try:
            self.result = await send_fn()
        except Exception as e:
            if (out := self._failed(e)) is e:
                raise
            raise out from e
        finally:
            send_tripwire.claim.reset(token)
        self.wire_state = "ok"
        return self.result

    def done(self, result: Any) -> None:
        _finish(self.account, self.op, "sent", self.budget, result)

    def abort(self) -> None:
        if self.wire_state == "ok":
            self.done(self.result)
        elif self.wire_state == "unsent":
            _finish(self.account, self.op, "refused", self.budget)


def begin(platform: str, account: str, op: str, kind: str, target: str, dig: str) -> Claim | Sent:
    account, target = str(account), str(target)
    epoch = _owner_epoch(platform, account)
    _capable(account, kind)
    check_permit()
    _not_held(platform, account)
    if (replay := _claim(account, op, kind, target, dig, epoch)) is not None:
        log.info("send_ops: replay %s op=%s account=%s target=%s", kind, op, account, target)
        return replay
    return Claim(account, op)


def dispatch(platform: str, account: str, op: str, kind: str, target: str, dig: str,
             send_fn: Callable[[], Any]) -> Sent:
    claim = begin(platform, account, op, kind, target, dig)
    if isinstance(claim, Sent):
        return claim
    result = claim.wire(send_fn)
    claim.done(result)
    return Sent(result, False)


def uncertain(account: str) -> list[dict]:
    with contextlib.closing(_connect()) as db:
        rows = db.execute("SELECT op_id, kind, target, created_at, attempts FROM send_ops"
                          " WHERE account=? AND state='uncertain' ORDER BY created_at", (str(account),)).fetchall()
    return [{"op_id": op, "kind": kind, "target": target, "created_at": at, "attempts": n}
            for op, kind, target, at, n in rows]


def in_flight() -> dict[str, int]:
    with contextlib.closing(_connect()) as db:
        got = dict(db.execute("SELECT state, COUNT(*) FROM send_ops WHERE state IN ('claimed','uncertain')"
                              " GROUP BY state").fetchall())
    return {"claimed": got.get("claimed", 0), "uncertain": got.get("uncertain", 0)}


def resolve(account: str, op: str, sent: bool, by: str) -> bool:
    with contextlib.closing(_connect()) as db:
        return db.execute(f"UPDATE send_ops SET state=?, resolved_by=?, resolved_at={_NOW}, updated_at={_NOW}"
                          " WHERE account=? AND op_id=? AND state='uncertain'",
                          ("resolved_sent" if sent else "resolved_not_sent", by, str(account), op)).rowcount == 1


async def adispatch(platform: str, account: str, op: str, kind: str, target: str, dig: str,
                    send_fn: Callable[[], Awaitable[Any]]) -> Sent:
    claim = await asyncio.to_thread(begin, platform, account, op, kind, target, dig)
    if isinstance(claim, Sent):
        return claim
    result = await claim.awire(send_fn)
    await asyncio.to_thread(claim.done, result)
    return Sent(result, False)


def cells() -> bool:
    return bool(os.environ.get("OI_CELL_MAP"))


def _automated_op(account: str, kind: str, target: Any, anchor: Any, part: int,
                  body: Any) -> tuple[str, str, str, str]:
    if kind in NO_ANCHOR or anchor in (None, ""):
        raise SendRefused(409, "no_anchor", kind=kind)
    import accounts
    platform, anchor, target = accounts.get_platform(account), str(anchor), str(target)
    return (platform, op_id(platform, account, kind, target, anchor, part), target,
            digest({"kind": kind, "anchor": anchor, "part": part} if body is None else body))


async def automated(account: Any, kind: str, target: Any, anchor: Any,
                    send_fn: Callable[[], Awaitable[T]], *, part: int = 0, body: Any = None,
                    revive: Callable[[Any], T] | None = None) -> T:
    if not cells():
        return await send_fn()
    platform, op, target, dig = _automated_op(str(account), kind, target, anchor, part, body)
    sent = await adispatch(platform, str(account), op, kind, target, dig, send_fn)
    return revive(sent.result) if sent.replay and revive else sent.result


def automated_sync(account: Any, kind: str, target: Any, anchor: Any,
                   send_fn: Callable[[], T], *, part: int = 0, body: Any = None,
                   revive: Callable[[Any], T] | None = None) -> T:
    if not cells():
        return send_fn()
    platform, op, target, dig = _automated_op(str(account), kind, target, anchor, part, body)
    sent = dispatch(platform, str(account), op, kind, target, dig, send_fn)
    return revive(sent.result) if sent.replay and revive else sent.result
