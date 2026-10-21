#!/usr/bin/env python3
"""OF restrict with a clean inbox exit + durable count exclusion.

Restricting a user on OF from our UI (chat ⋯ menu) must:
  1. send one "." first + mark the chat read (best-effort), so the thread
     stops counting as unread/owe-reply instead of sitting flagged forever;
  2. restrict on OF (the only step allowed to fail the request);
  3. write skip_list(reason='of_restricted') — the durable registry that
     (a) hard-skips them in every automation (HARD_SKIP_REASONS) and
     (b) excludes them from the roster-badge fold + annotated /chats rows;
  4. hide the chat on OF LAST (best-effort) — hidden threads leave the inbox
     until the fan's next inbound, and the "." send would re-surface a chat
     hidden any earlier.

These cases pin the dot → mark-read → restrict → hide ordering + ack dedupe,
the registry lifecycle (including that the muted-creator scrape cannot demote
an 'of_restricted' row), the fold
exclusion, and the serve-time `withUser.isRestricted` annotation (copy, never
the shared cached window).

Run:  ./venv/bin/python service/tests/test_of_restrict.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import server  # noqa: E402
from automations._common import (  # noqa: E402
    HARD_SKIP_REASONS,
    OF_RESTRICTED_REASON,
    load_hard_skip_ids,
    load_of_restricted_ids,
    mark_muted_creator_skip,
    set_of_restricted_skip,
)
from db.engine import get_session  # noqa: E402
from db.models import SkipList  # noqa: E402

AID = "acct-restrict"
FAN = 4242


class _FakeClient:
    def __init__(self, events: list[tuple], *, hide_fails=False):
        self.calls: list[tuple] = []
        self._events = events
        self._hide_fails = hide_fails

    def _rec(self, kind, user_id):
        self.calls.append((kind, int(user_id)))
        self._events.append((kind, int(user_id)))

    def restrict_user(self, user_id):
        self._rec("restrict", user_id)
        return {"isRestricted": True}

    def unrestrict_user(self, user_id):
        self._rec("unrestrict", user_id)
        return {"isRestricted": False}

    def hide_chat(self, chat_id):
        if self._hide_fails:
            raise RuntimeError("hide blew up")
        self._rec("hide", chat_id)
        return {"ok": True}

    def unhide_chat(self, chat_id):
        self._rec("unhide", chat_id)
        return {"ok": True}


async def _reason(fan_id: int) -> str | None:
    from sqlalchemy import select
    async with get_session() as s:
        return (await s.execute(
            select(SkipList.reason).where(
                SkipList.account_id == AID, SkipList.fan_id == fan_id)
        )).scalar_one_or_none()


class _Ctx:
    """Patch the restrict endpoint's collaborators; record the ack calls.
    `events` interleaves ack/mark-read with the OF-client calls so cases can
    pin the full dot → mark-read → restrict → hide ordering."""

    def __init__(self, *, ack_send_fails=False, hide_fails=False):
        self.events: list[tuple] = []
        self.client = _FakeClient(self.events, hide_fails=hide_fails)
        self.acks: list[tuple] = []
        self.mark_reads: list[int] = []
        self._ack_send_fails = ack_send_fails
        self._orig = {}

    def __enter__(self):
        async def _fake_send(request, chat_id, body):
            if self._ack_send_fails:
                raise RuntimeError("cannot message this user")
            self.acks.append((int(chat_id), body.text))
            self.events.append(("ack", int(chat_id)))
            return {"id": 1, "text": body.text}

        async def _fake_mark_read(chat_id):
            self.mark_reads.append(int(chat_id))
            self.events.append(("mark_read", int(chat_id)))
            return {"ok": True}

        self._orig = {
            "_resolve_account_id": server._resolve_account_id,
            "_get_client": server._get_client,
            "send_message": server.send_message,
            "of_mark_chat_read": server.of_mark_chat_read,
        }
        server._resolve_account_id = lambda _req=None: AID
        server._get_client = lambda: self.client
        server.send_message = _fake_send
        server.of_mark_chat_read = _fake_mark_read
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(server, name, fn)
        return False


async def case_restrict_acks_then_restricts_then_hides():
    async with get_session() as s:
        from sqlalchemy import delete
        await s.execute(delete(SkipList).where(SkipList.account_id == AID))
    with _Ctx() as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] and out["acked"] and out["hidden"], out
    assert ctx.acks == [(FAN, ".")], ctx.acks
    assert ctx.mark_reads == [FAN], ctx.mark_reads
    # Full ordering: the dot must land BEFORE the hide (a send re-surfaces a
    # hidden chat), and the hide is the last step of the clean exit.
    assert ctx.events == [
        ("ack", FAN), ("mark_read", FAN), ("restrict", FAN), ("hide", FAN),
    ], ctx.events
    assert await _reason(FAN) == OF_RESTRICTED_REASON
    # HARD skip: every load_hard_skip_ids consumer now excludes this fan.
    assert OF_RESTRICTED_REASON in HARD_SKIP_REASONS
    assert FAN in await load_hard_skip_ids(AID)


async def case_second_restrict_does_not_resend_ack():
    """The '.' is a one-time courtesy — a re-click (or a stale menu) must not
    message the creator again. The hide re-fires though (idempotent, and the
    chat may have re-surfaced since)."""
    with _Ctx() as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["acked"] is False and out["hidden"], out
    assert ctx.acks == [] and ctx.mark_reads == [], (ctx.acks, ctx.mark_reads)
    assert ctx.client.calls == [("restrict", FAN), ("hide", FAN)], ctx.client.calls


async def case_ack_failure_still_restricts():
    """A creator we can no longer message (or any OF blip on the send) must not
    block the restrict — the ack is best-effort by design."""
    await set_of_restricted_skip(AID, FAN, False)
    with _Ctx(ack_send_fails=True) as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] and out["acked"] is False, out
    # mark-read still attempted independently of the failed send.
    assert ctx.mark_reads == [FAN], ctx.mark_reads
    assert ctx.client.calls == [("restrict", FAN), ("hide", FAN)], ctx.client.calls
    assert await _reason(FAN) == OF_RESTRICTED_REASON


async def case_hide_failure_still_restricts_and_hide_is_optional():
    """The hide is best-effort like the ack — an OF blip on /chats/{id}/hide
    must not fail an already-applied restrict (the response just reports
    hidden=False). And ?hide=false skips the call entirely."""
    await set_of_restricted_skip(AID, FAN, False)
    with _Ctx(hide_fails=True) as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] and out["hidden"] is False, out
    assert ctx.client.calls == [("restrict", FAN)], ctx.client.calls
    assert await _reason(FAN) == OF_RESTRICTED_REASON

    await set_of_restricted_skip(AID, FAN, False)
    with _Ctx() as ctx:
        out = await server.of_restrict_user(FAN, request=None, hide=False)
    assert out["ok"] and out["hidden"] is False, out
    assert ctx.client.calls == [("restrict", FAN)], ctx.client.calls


async def case_registry_survives_muted_scrape():
    """The muted-creator scrape reconcile may not demote 'of_restricted' —
    skip_list is one row per fan, and losing the reason silently drops the fan
    back into the unread counts."""
    await mark_muted_creator_skip(AID, FAN)
    assert await _reason(FAN) == OF_RESTRICTED_REASON, "muted scrape demoted the row"
    # ...but a plain fan without the OF row still gets muted_creator as before.
    await mark_muted_creator_skip(AID, FAN + 1)
    assert await _reason(FAN + 1) == "muted_creator"


async def case_unrestrict_clears_only_own_row():
    with _Ctx() as ctx:
        out = await server.of_unrestrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] is False, out
    # Symmetric un-hide so the thread is visible again immediately.
    assert ctx.client.calls == [("unrestrict", FAN), ("unhide", FAN)], ctx.client.calls
    assert await _reason(FAN) is None
    assert await load_of_restricted_ids(AID) == set()
    # set_of_restricted_skip(False) must not touch other reasons.
    assert await _reason(FAN + 1) == "muted_creator"


async def case_roster_fold_excludes_restricted():
    """Restricted creators count as NEITHER blue nor orange — but still occupy
    a window slot (their row is visible in the list), preserving badge≡page
    parity. Exclusion works off the registry set AND off an OF-truth
    `withUser.isRestricted` when a payload carries it."""
    me = "999"
    rows = [
        # registry-excluded: unread → would have been blue
        {"withUser": {"id": 1}, "unreadMessagesCount": 3,
         "lastMessage": {"fromUser": {"id": 1}}},
        # registry-excluded: read + fan-last → would have been orange
        {"withUser": {"id": 2}, "unreadMessagesCount": 0,
         "lastMessage": {"fromUser": {"id": 2}}},
        # OF-stamped restricted → excluded even when not in the registry
        {"withUser": {"id": 3, "isRestricted": True}, "unreadMessagesCount": 1,
         "lastMessage": {"fromUser": {"id": 3}}},
        # normal unread → blue
        {"withUser": {"id": 4}, "unreadMessagesCount": 1,
         "lastMessage": {"fromUser": {"id": 4}}},
        # normal owe-reply → orange
        {"withUser": {"id": 5}, "unreadMessagesCount": 0,
         "lastMessage": {"fromUser": {"id": 5}}},
    ]
    out = server._roster_counts_from_rows(rows, me, exclude={1, 2})
    assert out == {"unread": 1, "owe_reply": 1}, out
    # Sanity: without the registry set, fans 1+2 count again — but the
    # OF-stamped row (fan 3) stays excluded unconditionally.
    base = server._roster_counts_from_rows(rows, me)
    assert base == {"unread": 2, "owe_reply": 2}, base


async def case_chats_rows_annotated_from_registry():
    """/chats serve-time stamp: registry fans get withUser.isRestricted=true on
    a COPY — the shared cached window object must stay untouched (a stale stamp
    baked into the cache would outlive an unrestrict)."""
    await set_of_restricted_skip(AID, 7, True)
    try:
        cached = {"list": [
            {"withUser": {"id": 7}, "unreadMessagesCount": 1},
            {"withUser": {"id": 8}, "unreadMessagesCount": 0},
        ], "hasMore": False}
        out = await server._annotate_chat_rows(AID, cached)
        assert out["list"][0]["withUser"]["isRestricted"] is True, out
        assert "isRestricted" not in out["list"][1]["withUser"], out
        assert "isRestricted" not in cached["list"][0]["withUser"], \
            "annotation mutated the shared cached window"
        # Empty registry → the exact same object back, zero copying.
        await set_of_restricted_skip(AID, 7, False)
        assert await server._annotate_chat_rows(AID, cached) is cached
    finally:
        await set_of_restricted_skip(AID, 7, False)


_harness.run(
    case_restrict_acks_then_restricts_then_hides,
    case_second_restrict_does_not_resend_ack,
    case_ack_failure_still_restricts,
    case_hide_failure_still_restricts_and_hide_is_optional,
    case_registry_survives_muted_scrape,
    case_unrestrict_clears_only_own_row,
    case_roster_fold_excludes_restricted,
    case_chats_rows_annotated_from_registry,
)
