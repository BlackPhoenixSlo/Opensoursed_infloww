from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select

from attribution import _BLAST_COPY_SLACK, _norm_body
from db.engine import get_session
from db.models import MassRun, Message
from messages import _queue_id_of

# Copied from Fastt's ai_chatter._BROADCAST_MIN_FANS.
_BROADCAST_MIN_FANS = 5
# Max gap between two fans' rows of one OF queue to still count as one mass's copies.
_QUEUE_SLACK = timedelta(hours=24)


class OutRow(NamedTuple):
    fan_id: int
    created_at: datetime
    body: str | None
    raw_json: str | None
    automation_kind: str | None
    mass_run_id: int | None
    funnel_step: int | None
    sent_by_employee_id: int | None
    is_unsent: bool


_OUT_COLS = (Message.fan_id, Message.created_at, Message.body, Message.raw_json,
             Message.automation_kind, Message.mass_run_id, Message.funnel_step,
             Message.sent_by_employee_id, Message.is_unsent)


def mass_at():
    return func.coalesce(MassRun.sent_at, MassRun.started_at)


class CopyRules:

    def __init__(self, account_id: str, automation_emp_id: int | None):
        self.account_id = str(account_id)
        self.automation_emp_id = automation_emp_id
        self._bodies: frozenset[str] | None = None
        self._masses: tuple[datetime, dict[str, list[datetime]]] | None = None
        self._queues: tuple[datetime, datetime, set[int]] | None = None
        self._queue_asked: dict[int, bool] = {}

    @classmethod
    async def load(cls, account_id: str) -> "CopyRules":
        try:
            from employees import get_automation_employee_id
            emp = await get_automation_employee_id()
        except LookupError:
            emp = None
        return cls(account_id, emp)

    async def broadcast_bodies(self) -> frozenset[str]:
        if self._bodies is None:
            async with get_session() as s:
                rows = (await s.execute(
                    select(Message.fan_id, Message.body, Message.automation_kind,
                           Message.mass_run_id, Message.sent_by_employee_id).where(
                        Message.account_id == self.account_id, Message.direction == "out",
                        Message.is_unsent.is_(False), Message.funnel_step.is_(None),
                        (Message.automation_kind.is_(None)
                         | Message.mass_run_id.is_not(None))))).all()
            fans: dict[str, set[int]] = {}
            for fan_id, body, kind, mass_run_id, emp in rows:
                if _named_human(kind, mass_run_id, emp, self.automation_emp_id):
                    continue
                key = _norm_body(body)
                if key:
                    fans.setdefault(key, set()).add(int(fan_id))
            self._bodies = frozenset(k for k, f in fans.items()
                                     if len(f) >= _BROADCAST_MIN_FANS)
        return self._bodies

    async def shared_queue(self, qid: int, at: datetime) -> bool:
        if self._queues is None:
            self._queues = await self._read_queues()
        read_at, scan_from, shared = self._queues
        if qid in shared:
            return True
        if at <= read_at and at >= scan_from + _QUEUE_SLACK:
            return False
        if qid not in self._queue_asked:
            self._queue_asked[qid] = await self._ask_queue(qid, at)
        return self._queue_asked[qid]

    async def _read_queues(self) -> tuple[datetime, datetime, set[int]]:
        from db.models import MassBroadcastCache
        read_at = datetime.utcnow()
        scan_from = read_at - 2 * _QUEUE_SLACK
        q = func.json_extract(Message.raw_json, "$.queueId")
        async with get_session() as s:
            ledger = (await s.execute(
                select(MassRun.queue_id).where(MassRun.account_id == self.account_id,
                                               MassRun.queue_id.is_not(None)))).scalars().all()
            cache = (await s.execute(
                select(MassBroadcastCache.queue_id).where(
                    MassBroadcastCache.account_id == self.account_id))).scalars().all()
            rows = (await s.execute(
                select(q).where(Message.account_id == self.account_id,
                                Message.direction == "out", Message.created_at > scan_from,
                                Message.raw_json.like('%"queueId"%'))
                .group_by(q).having(func.count(func.distinct(Message.fan_id)) >= 2)
            )).scalars().all()
        shared = {int(x) for x in (*ledger, *cache) if x is not None}
        for x in rows:
            try:
                shared.add(int(x))
            except (TypeError, ValueError):
                continue
        return read_at, scan_from, shared

    async def _ask_queue(self, qid: int, at: datetime) -> bool:
        q = func.json_extract(Message.raw_json, "$.queueId")
        async with get_session() as s:
            fans = (await s.execute(
                select(func.count(func.distinct(Message.fan_id))).where(
                    Message.account_id == self.account_id, Message.direction == "out",
                    Message.created_at >= at - _QUEUE_SLACK,
                    Message.created_at <= at + _QUEUE_SLACK,
                    Message.raw_json.like(f"%{int(qid)}%"),
                    q.in_((int(qid), str(int(qid))))))).scalar_one()
        return int(fans or 0) >= 2

    async def matches_a_mass(self, key: str, at: datetime) -> bool:
        if self._masses is None or at > self._masses[0]:
            read_at = max(datetime.utcnow(), at)
            sent = mass_at()
            async with get_session() as s:
                rows = (await s.execute(
                    select(MassRun.body, sent).where(
                        MassRun.account_id == self.account_id,
                        MassRun.body.is_not(None), sent.is_not(None)))).all()
            masses: dict[str, list[datetime]] = {}
            for body, sent_at in rows:
                k = _norm_body(body)
                if k:
                    masses.setdefault(k, []).append(sent_at)
            self._masses = read_at, masses
        return any(abs(t - at) <= _BLAST_COPY_SLACK for t in self._masses[1].get(key, ()))


def _named_human(automation_kind: str | None, mass_run_id: int | None,
                 sent_by_employee_id: int | None, emp: int | None) -> bool:
    return (mass_run_id is None and automation_kind is None
            and sent_by_employee_id is not None
            and (emp is None or int(sent_by_employee_id) != int(emp)))


def _row_is_named_human(row: OutRow, rules: CopyRules) -> bool:
    return _named_human(row.automation_kind, row.mass_run_id, row.sent_by_employee_id,
                        rules.automation_emp_id)


async def is_broadcast_copy(row: OutRow, rules: CopyRules) -> bool:
    if row.mass_run_id is not None:
        return row.funnel_step is None
    if row.automation_kind is not None or _row_is_named_human(row, rules):
        return False
    qid = _queue_id_of(row.raw_json)
    if qid is not None and await rules.shared_queue(qid, row.created_at):
        return True
    key = _norm_body(row.body)
    if not key:
        return False
    if await rules.matches_a_mass(key, row.created_at):
        return True
    return key in await rules.broadcast_bodies()


async def is_manual_outbound(row: OutRow, rules: CopyRules) -> bool:
    if row.is_unsent or row.mass_run_id is not None or row.automation_kind is not None:
        return False
    if row.sent_by_employee_id is not None:
        return _row_is_named_human(row, rules)
    return not await is_broadcast_copy(row, rules)


async def _outbound(account_id: str, fan_id: int, since: datetime) -> list[OutRow]:
    async with get_session() as s:
        rows = (await s.execute(
            select(*_OUT_COLS).where(
                Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                Message.direction == "out", Message.created_at > since,
                Message.mass_run_id.is_(None)))).all()
    return [OutRow._make(r) for r in rows]


async def manual_outbound_since(account_id: str, fan_id: int, since: datetime,
                                rules: CopyRules | None = None) -> bool:
    rules = rules or await CopyRules.load(account_id)
    for row in await _outbound(account_id, fan_id, since):
        if await is_manual_outbound(row, rules):
            return True
    return False
