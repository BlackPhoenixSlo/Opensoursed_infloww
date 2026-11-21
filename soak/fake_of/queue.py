"""The message queue of the fake OnlyFans (Phase 6 ticket 100: the Send now proof).

Mounted from app.py:
  POST   /messages/queue                  queue a message: `scheduledDate` (scheduled) or `isPublishedWithPeriod`
                                          (saved for later) queues it; neither sends it at once (service/of_sends.py
                                          `schedule_mass_message`, `send_mass_message`). Answers the queued item.
  GET    /messages/queue/{id}             the queued item with its audience (`userIds`; `userLists` only when it has
                                          lists), as `?format=scheduled` answers (of_reads `queued_message`)
  GET    /schedules                       the queued items still waiting and the dated scheduled posts (posts.py), as
                                          schedule items wrapping their entity, whose `publishDateTime` day in
                                          `filter[timeZone]` is in `filter[publishDate]`..`filter[publishDateEnd]`;
                                          `{list, syncInProcess}`, `limit`/`offset` ignored, no `hasMore`
                                          (service/of_reads.py `schedules`)
  PUT    /schedules/{id}/publish          Send now: the item leaves the queue and its message lands in each of its
                                          `userIds` Fans' chats (of_sends `publish_schedule`); a scheduled post's
                                          schedule item: Publish now (ticket 99, posts.py `publish`)
  DELETE /messages/queue/{id}             cancel a waiting item, or unsend a released one from every chat
                                          (of_sends `cancel_scheduled`)
  DELETE /messages/{id}                   unsend one chat message the Creator sent (of_sends `unsend_message`)

Shapes start from the captured fixtures queue-edit-message.json (the queued item) and
queue-schedules-message-day.json (the schedule item); ids, text, dates and audience replaced. A schedule item's id
differs from its entity's, as OF's do. A released message is a chat message of its own id carrying `isFromQueue` and
`queueId` (render.message). ASSUMPTION: the publish and unsend answers are `{"success": true}`: neither answer is
captured (the queue unsend's is, in .scratch/ofm-not-yet/captures/messages--save-for-later.json, as `{success}`);
overturned by their Request captures (ticket 12). Lists are kept, never expanded: no proof sends one (the Live guard
refuses it).

Measured for GET /schedules (ticket 136, docs/of-manager/captures/queue--scheduled-post-endpoint.json): the date range
is honoured, offset is ignored, limit=1 and limit=100 both returned every row in range, the answer is
{list, syncInProcess} with no hasMore. NOT measured, so each is an ASSUMPTION (rung 5: the simplest reading of the
capture), with the live read that would overturn it:
- both ends of the range are inclusive; overturned by a read with publishDate = publishDateEnd = a post's own day that
  comes back empty (or a post on publishDateEnd's day missing).
- a row's day is its `publishDateTime` in `filter[timeZone]`; overturned by a read naming a far-off zone (e.g.
  Pacific/Kiritimati) for a post near midnight UTC whose day does not shift.
- `limit` is fully ignored, not applied per day (the capture had one post per day, so the two were not separated);
  overturned by limit=1 over a range with two posts on the same day that returns one.
- a missing `filter[publishDate]`/`filter[publishDateEnd]` leaves that end open, and rows come by `publishDateTime`,
  earliest first (the Queue page always sends all three filters); overturned by a read without them, or out of order.
- a malformed date or an unknown time zone answers 400 (OF's error envelope), so a reader bug such as a literal `{tz}`
  fails in fake mode too; overturned by a live read where OF accepts one.
"""
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
    scheduled_at: datetime | None          # None: saved for later
    created_at: datetime
    state: str = "queued"                  # queued | released | canceled
    sent: list[int] = field(default_factory=list)   # chat message ids it became

    @property
    def id(self) -> int:
        return ids.queue_id(self.n)

    @property
    def schedule(self) -> int:
        return ids.schedule_id(self.n)


def items(fake) -> dict[int, Item]:
    """The fake's queue, by queue id (kept on the FakeOF object, like automations' page price)."""
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
    """The queued item as GET /messages/queue/{id}?format=scheduled answers it."""
    d = render._tpl("queue-edit-message.json")
    d.pop("_source", None)
    d.pop("fromUser", None)   # the Creator's own profile: not modelled here
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
    """The item as one row of GET /schedules: a schedule item (its own id) wrapping the queue entity."""
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
            # Not World.creator_send: a queued send does not mark the chat read, so the unsend leaves it as it was.
            m = fake.world._append(fid, True, it.text, price=it.price)
            m.queue_id = it.id   # render.message: isFromQueue, queueId
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
        _release(fake, it)   # no date and not saved for later: OF's send-now path
    return ok(req, entity(it))


async def _queued(fake, req: Request, ok, qid: str) -> Response:
    it = items(fake).get(int(qid))
    if it is None or it.state == "canceled":
        return _error(req, ok, 404, "Message not found")
    return ok(req, entity(it))


async def _schedules(fake, req: Request, ok) -> Response:
    from soak.fake_of import posts as _posts   # ticket 97: scheduled posts are schedule items too
    try:   # ticket 136: the filters as posts.py's docstring reads them; `limit`/`offset` ignored (measured)
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
        from soak.fake_of import posts as _posts   # ticket 99: a scheduled post's schedule item (Publish now)
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
    for mid in it.sent:   # released: unsent from every chat (no time window)
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
