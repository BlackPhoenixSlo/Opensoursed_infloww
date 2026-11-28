from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

import fansly_shim as shim
from fansly_client import FanslyAPIError
from stateful_fake import StatefulFansly, Unmodelled

HERE = Path(__file__).resolve().parent
FIXTURE = json.loads((HERE / "fixtures" / "broadcast.json").read_text())
FEEDS = FIXTURE["feeds"]
RECIPES = HERE / "capture" / "RECIPES.md"
STATS = "/message/broadcast/stats"
QUEUE = "/message/broadcast/scheduled"
SCHEDULED = FIXTURE["scheduled"]
PENDING = [
    {"id": "900000000000004950", "text": "Good morning loves", "scheduledDate": "2026-11-30T08:00:00+00:00"},
    {"id": "900000000000004953", "text": "Cyber Monday bundle", "scheduledDate": "2026-12-01T09:30:00+00:00"},
    {"id": "900000000000004955", "text": "Flash sale Friday", "scheduledDate": "2026-12-04T18:00:00+00:00"},
]
POSTS = {"scheduledPosts": [{"postId": "900000000000004960", "status": 1, "scheduledFor": 1796025600000,
                             "postTemplate": {"content": "a scheduled post"}}]}
POSTS_OUT = ('{"list": [{"id": "900000000000004960", "type": "post", "publishDateTime": '
             '"2026-11-30T08:00:00+00:00", "entity": {"id": "900000000000004960", "text": "a scheduled post"}}], '
             '"hasMore": false}')
START, END = "2026-11-10 00:00:00", "2026-11-20 00:00:00"
WIDE = {"start_date": "2026-01-01 00:00:00", "end_date": "2026-12-31 23:59:59"}
WINDOW = {"start_date": START, "end_date": END}
ROW_KEYS = {"id", "text", "rawText", "date", "sentCount", "viewedCount", "isFree", "isTip", "isCanceled",
            "canUnsend", "unsendSeconds", "mediaCount", "media", "previews"}


def _id(n: int) -> str:
    return f"9000000000000048{n}"


class _Feed(shim.FanslyShimClient):
    def __init__(self, pages: dict):
        self.pages, self.calls = pages, []

    def _request(self, method, path, *, params=None, **_kw):
        self.calls.append((method, path, dict(params or {})))
        assert (method, path) == ("GET", STATS), (method, path)
        return copy.deepcopy(self.pages[params["before"]])


class _Queue(shim.FanslyShimClient):
    def __init__(self, replies: dict):
        self.replies, self.calls = replies, []

    def _request(self, method, path, *, params=None, **_kw):
        self.calls.append((method, path, params))
        assert method == "GET" and path in self.replies, (method, path)
        return copy.deepcopy(self.replies[path])


def _queue(scheduled, **kw):
    feed = _Queue({QUEUE: scheduled})
    return feed, feed.scheduled_messages(**kw)


def _cursors(feed: _Feed) -> list[str]:
    return [p["before"] for _m, _p, p in feed.calls]


def _walk(pages: dict, **kw):
    feed = _Feed(pages)
    return feed, feed.engagement_messages("group", **{**WINDOW, **kw})


def _ids(got: dict) -> list[str]:
    return [r["id"] for r in got["items"]]


def _raises(fn, cls) -> bool:
    try:
        fn()
    except cls:
        return True
    return False


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        if "broadcast" in record.getMessage():
            self.lines.append(record.getMessage())


def main() -> int:
    fails: list[str] = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    walk = FEEDS["walk"]
    lines = _Lines()
    shim.log.addHandler(lines)
    shim.log.setLevel(logging.INFO)
    feed, got = _walk(walk)
    shim.log.removeHandler(lines)
    check(feed.calls == [("GET", STATS, {"before": "0", "limit": "24"}),
                         ("GET", STATS, {"before": _id(28), "limit": "24"}),
                         ("GET", STATS, {"before": _id(24), "limit": "24"})],
          f"walk: before=0, then each raw page's last id, limit 24, no date params; the short first page "
          f"must not stop it and the third page's first row older than the start must: {feed.calls}")
    check(_ids(got) == [_id(29), _id(26), _id(25), _id(24)],
          f"walk: window keeps type-3 text rows only, newest first: {_ids(got)}")
    check((got["hasMore"], got["incomplete"]) == (False, False), f"date-stopped walk is complete: {got}")
    check(got["items"][0] == {
        "id": _id(29), "text": "Weekend Sale is LIVE", "rawText": "Weekend Sale is LIVE",
        "date": "2026-11-19T18:30:00+00:00", "sentCount": 10, "viewedCount": 4, "isFree": True,
        "isTip": False, "isCanceled": False, "canUnsend": False, "unsendSeconds": 0, "mediaCount": 0,
        "media": [], "previews": []}, f"row: observed fields only, tip and total ignored: {got['items'][0]}")
    check(all(set(r) == ROW_KEYS for r in got["items"]), f"row keys: {[sorted(r) for r in got['items']]}")
    check(len(lines.lines) == 1 and all(f"{k}={n}" in lines.lines[0]
                                        for k, n in (("type", 1), ("attachments", 1), ("window", 2))),
          f"one counted skip line per walk: {lines.lines}")

    feed, got = _walk(walk, **WIDE)
    check(_cursors(feed) == ["0", _id(28), _id(24), _id(22)] and (got["hasMore"], got["incomplete"]) == (False, False),
          f"empty page ends the walk complete: {_cursors(feed)} {got['hasMore']} {got['incomplete']}")
    check(_ids(got) == [_id(n) for n in (30, 29, 26, 25, 24, 23, 22)], f"wide window rows: {_ids(got)}")

    feed, got = _walk(walk, offset=1, limit=2)
    check(_ids(got) == [_id(26), _id(25)] and got["hasMore"] is True and got["incomplete"] is False,
          f"offset/limit slice the eligible rows; one more eligible row means hasMore: {got}")
    check(_cursors(feed) == ["0", _id(28)], f"walk stops once offset+limit+1 rows are held: {_cursors(feed)}")
    _, got = _walk(walk, offset=3, limit=2)
    check(_ids(got) == [_id(24)] and got["hasMore"] is False, f"last slice has no more: {got}")

    _, got = _walk(walk, query="weekend")
    check(_ids(got) == [_id(29)] and got["hasMore"] is False, f"query is a case-insensitive substring: {got}")
    _, got = _walk(walk, query="TWIN")
    check(_ids(got) == [_id(25), _id(24)], f"query matches every row holding it: {_ids(got)}")
    _, got = _walk(walk, query="twin", offset=1, limit=1)
    check(_ids(got) == [_id(24)] and got["hasMore"] is False, f"query filters before offset/limit: {got}")

    a, b = _ids(_walk(walk)[1])[2:4]
    check(isinstance(a, str) and isinstance(b, str) and a != b and int(a) - int(b) == 1
          and int(b) > 2 ** 53 and float(a) == float(b),
          f"adjacent ids above 2^53 stay distinct strings though their floats collide: {a!r} {b!r}")

    feed, got = _walk(FEEDS["stalled"], **WIDE)
    check(_cursors(feed) == ["0", _id(11)] and (got["hasMore"], got["incomplete"]) == (True, True),
          f"repeated non-empty cursor: incomplete and hasMore: {_cursors(feed)} {got}")
    check(_ids(got) == [_id(12), _id(11)], f"a repeated page adds no duplicate row: {_ids(got)}")

    feed, got = _walk(FEEDS["empty"])
    check(got == {"items": [], "hasMore": False, "incomplete": False} and len(feed.calls) == 1,
          f"empty first page: complete and empty: {got} {feed.calls}")

    check(_raises(lambda: _walk(FEEDS["malformed"]), FanslyAPIError), "a page without messages must raise")
    bad = {"0": {"messages": [{**walk["0"]["messages"][1], "id": "not-an-id"}]}}
    check(_raises(lambda: _walk(bad), FanslyAPIError), "a row without a digit id must raise")
    good = walk["0"]["messages"][1]
    for stats in ({"total": 12, "read": 4}, {"total": 12, "delivered": 10, "read": "4.0"}, None):
        bad = {"0": {"messages": [{**good, "stats": stats}]}}
        check(_raises(lambda: _walk(bad), FanslyAPIError), f"stats without exact delivered/read must raise: {stats}")
    for when in (True, "1763577000", None):
        bad = {"0": {"messages": [{**good, "createdAt": when}]}}
        check(_raises(lambda: _walk(bad), FanslyAPIError), f"a non-numeric createdAt must raise: {when!r}")

    row = walk["0"]["messages"][1]
    ids = [str(10 ** 18 - n) for n in range(30)]
    endless = {cursor: {"messages": [{**row, "id": nxt}]} for cursor, nxt in zip(["0", *ids], ids)}
    feed, got = _walk(endless)
    check(len(feed.calls) == 20 and len(got["items"]) == 20 and (got["hasMore"], got["incomplete"]) == (True, True),
          f"20th page caps the walk: incomplete and hasMore: {len(feed.calls)} calls, {got['hasMore']} {got['incomplete']}")

    feed = _Feed(walk)
    check(_raises(lambda: feed.engagement_messages("direct", **WINDOW), shim.FanslyBlocked) and feed.calls == [],
          "the direct feed stays Blocked before any request")
    feed = _Feed(walk)
    check(feed.mass_message_history(**WINDOW, limit=2, offset=1) == _walk(walk, limit=2, offset=1)[1]
          and _cursors(feed) == ["0", _id(28)], "history delegates to the group feed")

    headings = {line.strip() for line in RECIPES.read_text().splitlines() if line.startswith("#")}
    check("Capture session 1126" in FIXTURE["_source"]
          and "### Broadcast schedule / queue / history / cancel (§6.6) — W" in headings
          and "### Broadcast schedule / queue / history / cancel (§6.6) — W" in FIXTURE["_source"],
          f"fixture _source names the Capture session 1126 RECIPES section: {FIXTURE['_source']}")

    fake = StatefulFansly()
    c = fake.client()
    got = c.mass_message_history(**WINDOW)
    check(_ids(got) == [_id(29), _id(26), _id(25), _id(24)], f"stateful fake answers from the fixture: {_ids(got)}")
    check([(m, p, q) for m, p, _b, q in fake.calls] == [("GET", STATS, {"before": b, "limit": "24"})
                                                        for b in ("0", _id(28), _id(24))] and not fake.unmodelled,
          f"stateful fake sees the captured stats GETs: {fake.calls} {fake.unmodelled}")
    check(_raises(lambda: c._request("GET", STATS, params={"before": "0", "limit": "24", "startDate": START}),
                  Unmodelled), "a date param on the stats GET is not captured and must raise")

    lines = _Lines()
    shim.log.addHandler(lines)
    feed, got = _queue(SCHEDULED)
    shim.log.removeHandler(lines)
    check(feed.calls == [("GET", QUEUE, None)], f"queue: one bare GET of the scheduled broadcasts: {feed.calls}")
    check(got == {"list": PENDING, "hasMore": False},
          f"queue: pending rows only, string id, template text, ISO date, soonest first: {got}")
    check(len(lines.lines) == 1 and all(f"{k}={n}" in lines.lines[0] for k, n in (("status", 2), ("row", 1))),
          f"one counted skip line per queue read: {lines.lines}")
    _, got = _queue(SCHEDULED, limit=2)
    check(got == {"list": PENDING[:2], "hasMore": True}, f"queue: limit slices, an eligible row past it is more: {got}")
    _, got = _queue(SCHEDULED, limit=1, offset=1)
    check(got == {"list": PENDING[1:2], "hasMore": True}, f"queue: offset slices the eligible rows: {got}")
    _, got = _queue(SCHEDULED, limit=2, offset=1)
    check(got == {"list": PENDING[1:], "hasMore": False}, f"queue: skipped rows never count toward more: {got}")
    _, got = _queue(SCHEDULED, limit=5, offset=3)
    check(got == {"list": [], "hasMore": False}, f"queue: an offset past the eligible rows is empty: {got}")
    _, got = _queue({"scheduledBroadcastMessages": [], "groups": []})
    check(got == {"list": [], "hasMore": False}, f"queue: the captured empty queue reads empty: {got}")

    pending = SCHEDULED["scheduledBroadcastMessages"][-1]
    for bad in ({"messageTemplate": {"content": "an object, not a JSON string"}},
                {"messageTemplate": '"a JSON string that is not an object"'}, {"messageTemplate": None},
                {"status": "1"}, {"status": None}, {"id": None}, {"id": "not-an-id"},
                {"scheduledFor": "1796025600000"}, {"scheduledFor": None}):
        _, got = _queue({"scheduledBroadcastMessages": [{**pending, **bad}], "groups": []})
        check(got == {"list": [], "hasMore": False}, f"queue: a row with {bad} is skipped: {got}")
    _, got = _queue({"scheduledBroadcastMessages": ["not a row", pending], "groups": []})
    check(got == {"list": PENDING[:1], "hasMore": False}, f"queue: a non-object row is skipped: {got}")
    lines = _Lines()
    shim.log.addHandler(lines)
    _, got = _queue({"scheduledBroadcastMessages": [{**pending, "status": True}, {**pending, "status": 1.0},
                                                    "not a row", {**pending, "id": None}], "groups": []})
    shim.log.removeHandler(lines)
    check(got == {"list": [], "hasMore": False} and len(lines.lines) == 1
          and all(f"{k}={n}" in lines.lines[0] for k, n in (("status", 2), ("row", 2))),
          f"queue: status True and 1.0 skip as status, a non-object or bad row as row: {got} {lines.lines}")
    for page in ({"groups": []}, {"scheduledBroadcastMessages": None}, None, []):
        check(_raises(lambda: _queue(page), FanslyAPIError), f"queue: a malformed answer must raise: {page!r}")

    feed = _Queue({QUEUE: SCHEDULED, "/post/scheduled": POSTS})
    out = feed.schedules()
    check(json.dumps(out) == POSTS_OUT and feed.calls == [("GET", "/post/scheduled", None)],
          f"schedules() is unchanged with scheduled broadcasts present and never reads them: {out} {feed.calls}")

    fake = StatefulFansly()
    got = fake.client().scheduled_messages()
    check(got == {"list": PENDING, "hasMore": False} and not fake.unmodelled
          and [(m, p, q) for m, p, _b, q in fake.calls] == [("GET", QUEUE, {})],
          f"stateful fake answers the queue GET from the fixture: {got} {fake.calls} {fake.unmodelled}")
    check(_raises(lambda: fake.client()._request("GET", QUEUE, params={"limit": "10"}), Unmodelled),
          "a param on the queue GET is not captured and must raise")

    if fails:
        print("FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print("broadcast reads: walk, stops, slicing, skips, string ids, the scheduled queue and the stateful fake hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
