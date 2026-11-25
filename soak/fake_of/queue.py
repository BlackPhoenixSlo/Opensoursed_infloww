from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from starlette.requests import Request
from starlette.responses import Response

from soak import ids
from soak.fake_of import render
from soak.world import iso, now_utc


@dataclass
class Item:
    n: int
    text: str
    price: float
    user_ids: list[int]
    user_lists: list[Any]
    scheduled_at: datetime | None
    created_at: datetime
    state: str = "queued"
    sent: list[int] = field(default_factory=list)

    @property
    def id(self) -> int:
        return ids.queue_id(self.n)

    @property
    def schedule(self) -> int:
        return ids.schedule_id(self.n)


def items(fake) -> dict[int, Item]:
    return fake.__dict__.setdefault("_soak_queue", {})


def released(fake, qid: int) -> bool:
    it = items(fake).get(qid)
    return it is not None and it.state == "released"


def _when(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def entity(it: Item) -> dict[str, Any]:
    d = render._tpl("queue-edit-message.json")
    d.pop("_source", None)
    d.pop("fromUser", None)
    d.update({
        "id": it.id, "text": it.text, "rawText": it.text, "price": it.price, "isFree": it.price <= 0,
        "createdAt": iso(it.created_at), "changedAt": iso(it.created_at),
        "scheduledAt": iso(it.scheduled_at) if it.scheduled_at else None,
        "userIds": [str(u) for u in it.user_ids],
    })
    if it.user_lists:
        d["userLists"] = list(it.user_lists)
    return d


def schedule_item(it: Item) -> dict[str, Any]:
    d = render._tpl("queue-schedules-message-day.json", "list", 0)
    e = d["entity"]
    e.update({k: v for k, v in entity(it).items() if k in e})
    e.update(queueId=it.id, isFromQueue=True, userIds=[str(u) for u in it.user_ids])
    d.update({"id": it.schedule, "publishDateTime": iso(it.scheduled_at) if it.scheduled_at else None,
              "createdDateTime": iso(it.created_at), "entity": e})
    return d


def _release(fake, it: Item) -> None:
    for fid in it.user_ids:
        if fid in fake.world.threads:
            m = fake.world._append(fid, True, it.text, price=it.price)
            m.queue_id = it.id
            it.sent.append(m.id)
    it.state = "released"


def _unsend(fake, mid: int) -> bool:
    for t in fake.world.threads.values():
        for i, m in enumerate(t):
            if m.id == mid and m.from_creator:
                del t[i]
                return True
    return False


def _error(req: Request, ok, status: int, message: str) -> Response:
    return ok(req, {"error": {"code": 0, "message": message}}, status)


async def _queue(fake, req: Request, ok) -> Response:
    body = await req.json()
    if not isinstance(body, dict):
        return _error(req, ok, 400, "Bad request")
    users = [int(u) for u in body.get("userIds") or []]
    if any(u not in fake.world.threads for u in users):
        return _error(req, ok, 400, "User not found")
    if not users and not body.get("userLists"):
        return _error(req, ok, 400, "No recipients")
    q = items(fake)
    it = Item(n=len(q) + 1, text=str(body.get("text") or ""), price=float(body.get("price") or 0),
              user_ids=users, user_lists=list(body.get("userLists") or []),
              scheduled_at=_when(body.get("scheduledDate")), created_at=now_utc())
    q[it.id] = it
    if it.scheduled_at is None and not body.get("isPublishedWithPeriod"):
        _release(fake, it)
    return ok(req, entity(it))


async def _queued(fake, req: Request, ok, qid: str) -> Response:
    it = items(fake).get(int(qid))
    if it is None or it.state == "canceled":
        return _error(req, ok, 404, "Message not found")
    return ok(req, entity(it))


async def _schedules(fake, req: Request, ok) -> Response:
    from soak.fake_of import posts as _posts
    try:
        within = _posts.schedule_filter(req.query_params)
    except ValueError:
        return _error(req, ok, 400, "Invalid filter")
    rows = [schedule_item(it) for it in items(fake).values()
            if it.state == "queued" and it.scheduled_at is not None and within(it.scheduled_at)]
    rows += _posts.schedule_rows(fake, within)
    rows.sort(key=lambda r: r["publishDateTime"])
    d = render._tpl("queue-schedules-message-day.json")
    d.pop("_source", None)
    d["list"] = rows
    return ok(req, d)


async def _publish(fake, req: Request, ok, sid: str) -> Response:
    it = next((x for x in items(fake).values() if x.schedule == int(sid)), None)
    if it is None:
        from soak.fake_of import posts as _posts
        if _posts.publish(fake, int(sid)):
            return ok(req, {"success": True})
    if it is None or it.state != "queued":
        return _error(req, ok, 404, "Schedule not found")
    _release(fake, it)
    return ok(req, {"success": True})


async def _cancel(fake, req: Request, ok, qid: str) -> Response:
    it = items(fake).get(int(qid))
    if it is None or it.state == "canceled":
        return _error(req, ok, 404, "Message not found")
    for mid in it.sent:
        _unsend(fake, mid)
    it.state = "canceled"
    return ok(req, {"success": True})


async def _unsend_one(fake, req: Request, ok, mid: str) -> Response:
    if not _unsend(fake, int(mid)):
        return _error(req, ok, 404, "Message not found")
    return ok(req, {"success": True})


ROUTES = [
    ("POST", re.compile(r"/api2/v2/messages/queue"), _queue),
    ("GET", re.compile(r"/api2/v2/messages/queue/(\d+)"), _queued),
    ("DELETE", re.compile(r"/api2/v2/messages/queue/(\d+)"), _cancel),
    ("DELETE", re.compile(r"/api2/v2/messages/(\d+)"), _unsend_one),
    ("GET", re.compile(r"/api2/v2/schedules"), _schedules),
    ("PUT", re.compile(r"/api2/v2/schedules/(\d+)/publish"), _publish),
]
