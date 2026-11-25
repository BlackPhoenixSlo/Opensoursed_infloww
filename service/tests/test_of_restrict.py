#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import server  # noqa: E402
import accounts_admin_api  # noqa: E402
import unread_total_decide  # noqa: E402
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
    # hide last: the "." send would re-surface a chat hidden earlier
    assert ctx.events == [
        ("ack", FAN), ("mark_read", FAN), ("restrict", FAN), ("hide", FAN),
    ], ctx.events
    assert await _reason(FAN) == OF_RESTRICTED_REASON
    assert OF_RESTRICTED_REASON in HARD_SKIP_REASONS
    assert FAN in await load_hard_skip_ids(AID)


async def case_second_restrict_does_not_resend_ack():
    with _Ctx() as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["acked"] is False and out["hidden"], out
    assert ctx.acks == [] and ctx.mark_reads == [], (ctx.acks, ctx.mark_reads)
    assert ctx.client.calls == [("restrict", FAN), ("hide", FAN)], ctx.client.calls


async def case_ack_failure_still_restricts():
    await set_of_restricted_skip(AID, FAN, False)
    with _Ctx(ack_send_fails=True) as ctx:
        out = await server.of_restrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] and out["acked"] is False, out
    assert ctx.mark_reads == [FAN], ctx.mark_reads
    assert ctx.client.calls == [("restrict", FAN), ("hide", FAN)], ctx.client.calls
    assert await _reason(FAN) == OF_RESTRICTED_REASON


async def case_hide_failure_still_restricts_and_hide_is_optional():
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
    await mark_muted_creator_skip(AID, FAN)
    assert await _reason(FAN) == OF_RESTRICTED_REASON, "muted scrape demoted the row"
    await mark_muted_creator_skip(AID, FAN + 1)
    assert await _reason(FAN + 1) == "muted_creator"


async def case_unrestrict_clears_only_own_row():
    with _Ctx() as ctx:
        out = await server.of_unrestrict_user(FAN, request=None)
    assert out["ok"] and out["restricted"] is False, out
    assert ctx.client.calls == [("unrestrict", FAN), ("unhide", FAN)], ctx.client.calls
    assert await _reason(FAN) is None
    assert await load_of_restricted_ids(AID) == set()
    assert await _reason(FAN + 1) == "muted_creator"


async def case_roster_fold_excludes_restricted():
    me = "999"
    rows = [
        {"withUser": {"id": 1}, "unreadMessagesCount": 3,
         "lastMessage": {"fromUser": {"id": 1}}},
        {"withUser": {"id": 2}, "unreadMessagesCount": 0, "isMutedNotifications": False,
         "lastMessage": {"fromUser": {"id": 2}}},
        {"withUser": {"id": 3, "isRestricted": True}, "unreadMessagesCount": 1,
         "lastMessage": {"fromUser": {"id": 3}}},
        {"withUser": {"id": 4}, "unreadMessagesCount": 1,
         "lastMessage": {"fromUser": {"id": 4}}},
        {"withUser": {"id": 5}, "unreadMessagesCount": 0, "isMutedNotifications": False,
         "lastMessage": {"fromUser": {"id": 5}}},
    ]
    out = accounts_admin_api._roster_counts_from_rows(rows, exclude={1, 2})
    assert out == {"unread": 2}, out
    assert unread_total_decide.amber_count(rows, me, {1, 2}, None) == 1
    base = accounts_admin_api._roster_counts_from_rows(rows)
    assert base == {"unread": 3}, base
    assert unread_total_decide.amber_count(rows, me, set(), None) == 2


async def case_chats_rows_annotated_from_registry():
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
