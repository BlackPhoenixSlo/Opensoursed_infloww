#!/usr/bin/env python3
"""Mark read through the relay clears the local unread only for what the platform took (W30-mu #1, #2).

The routes (server.of_mark_chat_read / of_mark_all_chats_read) once zeroed `chats.unread_count` BEFORE the platform
write: an OF raise, a Fansly ack Fansly refused, a Fansly unread scan that failed (read as "nothing unread") or a
mark-all capped at `_MARK_ALL_CAP` still cleared the badge, answered 200 and (mark-all) announced `fan_id: "all"`.
Now: the real Fansly shim behind a fake wire (`_request`), real `chats` rows in the temp DB; a write not (fully)
taken answers 502, leaves every unacked row's unread as it was and announces nothing for it; a partial mark-all
clears and announces only the fans it acked.

Run: ./venv/bin/python service/tests/test_mark_read_landed.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402

from sqlalchemy import select  # noqa: E402

import events  # noqa: E402
import read_flip  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Fan  # noqa: E402
from fansly_shim import FanslyAPIError, FanslyShimClient  # noqa: E402

AID, ME = "8803101", "777"
FANS = (5101, 5102, 5103)


class _Shim(FanslyShimClient):
    """The real shim; only the wire (`_request`) is faked. `groups`: [(fan, unreadCount)]; `scan_fail`: fans whose
    /message read raises; `unread_n`: fan messages per thread (newest first, `<fan>-0` newest); `ack_fail`:
    /message/ack raises; `read_n`: how many of the newest are already read (acked before)."""

    def __init__(self, *, groups=(), scan_fail=(), unread_n=1, ack_fail=False, read_n=0):  # noqa: D107
        class _S:
            account_id = ME
        self.session = _S()
        self._fan_to_group.update({str(f): f"g{f}" for f in FANS})   # what a list_chats pass fills
        self.groups, self.scan_fail, self.unread_n, self.ack_fail = list(groups), set(scan_fail), unread_n, ack_fail
        self.acked: list[str] = [f"{f}-{i}" for f in FANS for i in range(read_n)]

    def _request(self, method, path, *, params=None, json_body=None, **_kw):
        if path == "/messaging/groups":
            return {"data": [{"groupId": f"g{f}", "partnerAccountId": str(f), "unreadCount": u}
                             for f, u in self.groups]}
        if path == "/message":    # newest first, `limit` per page, `before` an id: older than it; acked = read
            fan = int(params["groupId"][1:])
            if fan in self.scan_fail:
                raise FanslyAPIError("GET /message -> 500")
            ids = [f"{fan}-{i}" for i in range(self.unread_n)]
            start = ids.index(params["before"]) + 1 if params.get("before") else 0
            return {"messages": [{"id": m, "senderId": str(fan),
                                  "interactions": [{"userId": ME, "readAt": int(m in self.acked)}]}
                                 for m in ids[start:start + int(params["limit"])]]}
        if path == "/message/ack":
            if self.ack_fail:
                raise FanslyAPIError("POST /message/ack -> 400 code=99")
            self.acked.extend(json_body["messageIds"])
            return {"success": True}
        raise AssertionError(f"unexpected {method} {path}")


class _OFRaises:
    def mark_chat_read(self, _chat_id):
        raise RuntimeError("OF 500 on mark-as-read")


async def _seed() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="mr", color="#aaaaaa"))
            await s.flush()
        for f in FANS:
            row = await s.get(Chat, (AID, f))
            if row is None:
                s.add(Chat(account_id=AID, fan_id=f, unread_count=3))
            else:
                row.unread_count = 3
        await s.commit()


async def _unread() -> dict[int, int]:
    async with get_session() as s:
        rows = (await s.execute(select(Chat.fan_id, Chat.unread_count).where(Chat.account_id == AID))).all()
    return {int(f): int(n) for f, n in rows}


def _run(route, *args, client):
    """(answer or HTTPException, unread per fan after, chat_read_changed fan ids published)."""
    published: list = []
    orig = (server._get_client, server._resolve_account_id, events.publish)
    server._get_client = lambda *_a, **_k: client
    server._resolve_account_id = lambda *_a: AID
    events.publish = published.append

    async def go():
        await _seed()
        try:
            out = await route(*args)
        except Exception as e:  # noqa: BLE001 — the 502 under test, or _proxy's translation of a raise
            out = e
        return out, await _unread()
    try:
        out, unread = asyncio.run(go())
    finally:
        server._get_client, server._resolve_account_id, events.publish = orig
    flips = [e["chat_read_changed"]["fan_id"] for e in published if "chat_read_changed" in e]
    return out, unread, flips


def _status(out) -> int:
    return out.status_code if isinstance(out, server.HTTPException) else 200 if not isinstance(out, Exception) else -1


UNTOUCHED = {f: 3 for f in FANS}
_PAST_SCAN = FanslyShimClient._ACK_PAGE * FanslyShimClient._ACK_SCAN_PAGES + 1


def case_of_raise_leaves_the_row_unread():
    out, unread, flips = _run(server.of_mark_chat_read, FANS[0], client=_OFRaises())
    assert isinstance(out, Exception) and unread == UNTOUCHED and flips == [], (out, unread, flips)


def case_fansly_single_read_not_landed_answers_502_and_keeps_the_row():
    for shim, reason in ((_Shim(ack_fail=True), "ack_rejected"),
                         (_Shim(scan_fail={FANS[0]}), "scan_failed"),          # once read as "nothing unread": 200
                         (_Shim(unread_n=_PAST_SCAN), "partial")):              # a backlog past the scan
        out, unread, flips = _run(server.of_mark_chat_read, FANS[0], client=shim)
        assert _status(out) == 502 and out.detail["upstream_status"] == reason, (reason, out)
        assert unread == UNTOUCHED and flips == [], (reason, unread, flips)


def case_fansly_backlog_past_one_page_is_acked_whole_or_not_at_all():
    """W30-mu #40: 51 unread once acked the newest 50 and answered partial; the retry's first page (now all read)
    read as "nothing unread" and answered success with 1 still unread. Now the scan pages back (`before`) and acks
    the whole backlog in one go; past `_ACK_SCAN_PAGES` it acks nothing, so a retry never reads our own acks as
    the fan's history being read."""
    shim = _Shim(unread_n=FanslyShimClient._ACK_PAGE + 1)
    answers = [shim.mark_chat_read(FANS[0]) for _ in range(2)]
    unacked = {f"{FANS[0]}-{i}" for i in range(shim.unread_n)} - set(shim.acked)
    assert not (answers[-1] == {"success": True} and unacked), (answers, sorted(unacked))
    assert answers[0] == {"success": True} and not unacked, (answers, sorted(unacked))
    big = _Shim(unread_n=_PAST_SCAN)
    assert big.mark_chat_read(FANS[0]) == {"success": False, "reason": "partial"} and big.acked == [], big.acked
    many = _Shim(groups=[(FANS[0], 1)], unread_n=_PAST_SCAN)
    out = many.mark_all_chats_read()
    assert out == {"success": True, "partial": True, "acked_fan_ids": []} and many.acked == [], (out, many.acked)


def _all_read(shim: _Shim) -> bool:
    return {f"{FANS[0]}-{i}" for i in range(shim.unread_n)} <= set(shim.acked)


def case_fansly_newest_page_read_with_an_older_unread_is_acked_through_both_routes():
    """W30-mu #40 (reopened, D2): the newest 50 already read and one older unread once answered success with
    nothing acked (a read message ended the scan). The scan now runs to the thread's end and acks the old one;
    the row clears and the flip goes out, single and mark-all alike."""
    page = FanslyShimClient._ACK_PAGE
    shim = _Shim(unread_n=page + 1, read_n=page)
    out, unread, flips = _run(server.of_mark_chat_read, FANS[0], client=shim)
    assert out == {"success": True} and _all_read(shim), (out, sorted(set(shim.acked)))
    assert unread == {**UNTOUCHED, FANS[0]: 0} and flips == [FANS[0]], (unread, flips)
    bulk = _Shim(groups=[(FANS[0], 1)], unread_n=page + 1, read_n=page)
    out, unread, flips = _run(server.of_mark_all_chats_read, client=bulk)
    assert out == {"success": True} and _all_read(bulk), (out, sorted(set(bulk.acked)))
    assert unread == {f: 0 for f in FANS} and flips == ["all"], (unread, flips)


def case_fansly_only_the_oldest_unread_at_the_scan_edge():
    """D2 at the edge of `_ACK_SCAN_PAGES` (200 messages), only the oldest unread: 199 reaches the end (acked,
    success); 200 fills the window without reaching the end and holds unread (partial, nothing acked, row
    kept); 201's unread lies past the window, none in it (success, nothing acked: the documented limit)."""
    edge = FanslyShimClient._ACK_PAGE * FanslyShimClient._ACK_SCAN_PAGES
    for n, want, acks, row in ((edge - 1, 200, True, 0), (edge, 502, False, 3), (edge + 1, 200, False, 0)):
        shim = _Shim(unread_n=n, read_n=n - 1)
        before = len(shim.acked)
        out, unread, flips = _run(server.of_mark_chat_read, FANS[0], client=shim)
        assert _status(out) == want and (len(shim.acked) > before) == acks, (n, out, len(shim.acked) - before)
        assert unread == {**UNTOUCHED, FANS[0]: row} and flips == ([FANS[0]] if row == 0 else []), (n, unread)
        if want == 502:
            assert out.detail["upstream_status"] == "partial", (n, out.detail)


def case_fansly_single_read_landed_clears_its_row():
    out, unread, flips = _run(server.of_mark_chat_read, FANS[0], client=_Shim())
    assert out == {"success": True} and unread == {**UNTOUCHED, FANS[0]: 0} and flips == [FANS[0]], (out, unread)


def case_fansly_mark_all_whole():
    shim = _Shim(groups=[(f, 1) for f in FANS])
    out, unread, flips = _run(server.of_mark_all_chats_read, client=shim)
    assert out == {"success": True} and unread == {f: 0 for f in FANS} and flips == ["all"], (out, unread, flips)


def case_fansly_mark_all_capped_clears_only_the_acked_fans():
    shim = _Shim(groups=[(f, 1) for f in FANS])
    shim._MARK_ALL_CAP = 2
    out, unread, flips = _run(server.of_mark_all_chats_read, client=shim)
    assert _status(out) == 502 and out.detail["upstream_status"] == "partial", out
    assert out.detail["upstream_body"]["acked_fan_ids"] == [str(f) for f in FANS[:2]], out.detail
    assert unread == {FANS[0]: 0, FANS[1]: 0, FANS[2]: 3} and flips == list(FANS[:2]), (unread, flips)


def case_fansly_partial_mark_all_names_snowflakes_as_strings():
    """W30-mu #41: a fan id past 2^53 as a JSON number reaches the browser rounded (JS doubles), so the app saw
    an acked fan as failed. The shim's `acked_fan_ids` are strings; the relay's per-fan flip carries the string."""
    big = 900604711209099264
    shim = _Shim(groups=[(big, 1), (FANS[0], 1)])
    shim._MARK_ALL_CAP = 1
    out = shim.mark_all_chats_read()
    assert out["acked_fan_ids"] == [str(big)], out
    published: list = []
    orig = events.publish
    events.publish = published.append
    try:
        asyncio.run(read_flip.after_write(AID, None, 0, out, at=1))
    finally:
        events.publish = orig
    assert [e["chat_read_changed"]["fan_id"] for e in published] == [str(big)], published


def case_a_dm_newer_than_the_flip_keeps_its_row_unread():
    """W30-mu #42: the local zero once ran after the write landed with no fence, so a fan DM that committed while
    the write was in flight (its +1 already in `chats.unread_count`) was cleared. Now a row whose fan's last
    inbound message (`fans.last_message_received_at`) is newer than the flip's pre-write `at` keeps its unread,
    for one fan and for a whole mark-all."""
    from datetime import datetime, timedelta
    at = 1_790_000_000_000
    cut = datetime.utcfromtimestamp(at / 1000)

    async def go(fan_id):
        await _seed()
        async with get_session() as s:
            for f, when in ((FANS[0], cut + timedelta(seconds=1)), (FANS[1], cut - timedelta(seconds=1))):
                row = await s.get(Fan, (AID, f)) or Fan(account_id=AID, fan_id=f)
                row.last_message_received_at = when
                s.add(row)
            await s.commit()
        await read_flip.after_write(AID, fan_id, 0, {"success": True}, at=at)
        return await _unread()
    orig = events.publish
    events.publish = lambda _e: None
    try:
        assert asyncio.run(go(FANS[0])) == UNTOUCHED, "the newer DM's row was cleared"
        assert asyncio.run(go(FANS[1])) == {**UNTOUCHED, FANS[1]: 0}
        assert asyncio.run(go(None)) == {FANS[0]: 3, FANS[1]: 0, FANS[2]: 0}
    finally:
        events.publish = orig


def case_fansly_mark_all_scan_failure_keeps_that_fan():
    shim = _Shim(groups=[(f, 1) for f in FANS], scan_fail={FANS[1]})
    out, unread, flips = _run(server.of_mark_all_chats_read, client=shim)
    assert _status(out) == 502 and out.detail["upstream_status"] == "partial", out
    assert unread == {FANS[0]: 0, FANS[1]: 3, FANS[2]: 0} and flips == [FANS[0], FANS[2]], (unread, flips)
    assert f"{FANS[1]}-0" not in shim.acked, shim.acked


def case_fansly_mark_all_rejected_ack_keeps_every_row():
    shim = _Shim(groups=[(f, 1) for f in FANS], ack_fail=True)
    out, unread, flips = _run(server.of_mark_all_chats_read, client=shim)
    assert _status(out) == 502 and out.detail["upstream_status"] == "ack_rejected", out
    assert unread == UNTOUCHED and flips == [], (unread, flips)


_harness.run()
