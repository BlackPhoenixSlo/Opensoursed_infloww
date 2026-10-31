#!/usr/bin/env python3
"""Roster-strip badge counts (GET /admin/accounts/roster-counts).

The badge reads OF's LIVE chat list — the same source the chat-list header reads
— so the per-model badge can never disagree with what you see when you open that
model. These cases pin:

  • `_compute_roster_count_of` — blue = OF's native `filter=unread`; orange =
    READ conversations where the fan spoke last (`lastMessage.fromUser != me`),
    deduped across pages, disjoint from blue.
  • `reconcile_chats_from_of` — still pulls OF read-state + last-message direction
    into the local mirror on every inbox /chats load (used elsewhere; the badge no
    longer depends on it, but the inbox does).

Why NOT a local-DB aggregate (the prior implementation): local `chats` is not a
faithful mirror of OF — it accumulates phantom/old rows (Ava: ~290 local vs OF's
~106) and `unread_count` drifts (WS only increments it), so a local scan read 3
"unread" for a model OF reports as 0. Only OF's payload reproduces the header.

Run:  ./venv/bin/python service/tests/test_roster_counts.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from datetime import datetime  # noqa: E402

import server  # noqa: E402
import accounts_admin_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Message  # noqa: E402


_TS = datetime(2026, 6, 21, 12, 0, 0)


# ── Fake OF client: paginates a flat most-recent-first chat list by offset/limit
#    with hasMore (OF caps each page at ~10 regardless of `limit`).
class _FakeClient:
    def __init__(self, me: int, recent: list[dict]):
        self.user_id = me
        self._recent = recent

    def list_chats(self, *, limit=10, offset=0, order="recent", filter=None, **_kw):
        page = self._recent[offset:offset + limit]
        return {"list": page, "hasMore": offset + limit < len(self._recent)}


def _chat(fan_id: int, *, unread: int = 0, last_from: int | None = None) -> dict:
    """An OF /chats item. `last_from` defaults to the fan (fan spoke last)."""
    return {
        "withUser": {"id": fan_id},
        "unreadMessagesCount": unread,
        "lastMessage": {"fromUser": {"id": fan_id if last_from is None else last_from}},
    }


async def case_compute_roster_count_from_of():
    me = 999
    # Most-recent window. blue = unreadMessagesCount>0 (the inbox's own unread
    # signal, NOT a separate filter=unread call); orange = read + fan spoke last.
    recent = [
        _chat(1, unread=2, last_from=1),     # unread → BLUE, must NOT also be orange
        _chat(2, unread=0, last_from=2),     # read, fan spoke last → ORANGE
        _chat(3, unread=0, last_from=me),    # WE replied last → neither color
        _chat(4, unread=0, last_from=4),     # read, fan spoke last → ORANGE
        _chat(2, unread=0, last_from=2),     # duplicate of fan 2 → not double-counted
    ]

    fake = _FakeClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", "acct-of")
    try:
        out = await accounts_admin_api._compute_roster_count_of("acct-of")
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", "acct-of")

    assert out == {"unread": 1, "owe_reply": 2}, out


async def case_roster_count_caps_at_window():
    """The scan stops at _ROSTER_SCAN_MAX conversations (the inbox's first page),
    not the whole history — a deep scan over-counted owe-reply (All-icon read 11
    where the unified header showed 5-6)."""
    me = 5
    cap = server._ROSTER_SCAN_MAX
    # Twice the cap in read fan-spoke-last chats, all unique → orange clamps to cap.
    recent = [_chat(1000 + i, unread=0, last_from=1000 + i) for i in range(cap * 2)]

    fake = _FakeClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", "acct-cap")
    try:
        out = await accounts_admin_api._compute_roster_count_of("acct-cap")
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", "acct-cap")

    assert out == {"unread": 0, "owe_reply": cap}, out


async def case_reconcile_pulls_of_read_state_into_local():
    from messages import reconcile_chats_from_of

    AID2 = "acct-2"
    async with get_session() as s:
        s.add(Account(id=AID2, nickname="Acct 2"))
        # Simulate the bug's starting state: WS inflated unread_count on a chat
        # that OF actually considers READ, and the fan spoke last.
        s.add(Message(account_id=AID2, fan_id=10, message_id=1001,
                      direction="in", body="hey", created_at=_TS))
        s.add(Chat(account_id=AID2, fan_id=10, last_message_id=1001, unread_count=7))
        await s.commit()

    # OF's truth: that chat is read (unreadMessagesCount 0), fan still spoke last.
    of_payload = [{
        "withUser": {"id": 10},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1001, "fromUser": {"id": 10},
                        "text": "hey", "createdAt": "2026-06-21T12:00:00+00:00"},
    }, {
        # A genuinely-unread chat from OF (new inbound).
        "withUser": {"id": 11},
        "unreadMessagesCount": 2,
        "lastMessage": {"id": 1101, "fromUser": {"id": 11},
                        "text": "hi", "createdAt": "2026-06-21T12:05:00+00:00"},
    }, {
        # A chat we replied to ON OF WEB — WS skipped the outbound, so locally we'd
        # still think the fan spoke last. OF's lastMessage is OURS (id == account).
        "withUser": {"id": 12},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1201, "fromUser": {"id": int(AID2) if AID2.isdigit() else 0},
                        "text": "ttyl", "createdAt": "2026-06-21T12:06:00+00:00"},
    }]
    # Use a numeric account so the "we sent it" direction check works.
    AID_NUM = "999"
    async with get_session() as s:
        s.add(Account(id=AID_NUM, nickname="Acct num"))
        s.add(Message(account_id=AID_NUM, fan_id=12, message_id=1200,
                      direction="in", body="u there", created_at=_TS))
        s.add(Chat(account_id=AID_NUM, fan_id=12, last_message_id=1200, unread_count=5))
        await s.commit()
    of_for_num = [{
        "withUser": {"id": 12},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1201, "fromUser": {"id": 999},
                        "text": "ttyl", "createdAt": "2026-06-21T12:06:00+00:00"},
    }]

    n = await reconcile_chats_from_of(AID2, of_payload[:2])
    assert n == 2, n
    async with get_session() as s:
        assert (await s.get(Chat, (AID2, 10))).unread_count == 0, "OF-read chat zeroed"
        assert (await s.get(Chat, (AID2, 11))).unread_count == 2, "OF-unread mirrored"

    # The OF-web-reply case: reconcile advances last_message_id to OUR outbound,
    # persists its direction, so it drops off owe-reply.
    await reconcile_chats_from_of(AID_NUM, of_for_num)
    async with get_session() as s:
        ch = await s.get(Chat, (AID_NUM, 12))
        assert ch.unread_count == 0 and ch.last_message_id == 1201, ch.last_message_id
        m = await s.get(Message, (AID_NUM, 12, 1201))
        assert m is not None and m.direction == "out", "outbound reply persisted"


async def case_roster_bust_recomputes_only_target():
    """`?bust=<aid>` force-recomputes ONE model, leaving the rest on cache.

    Cache-hit is observable as a fetcher (`_compute_roster_count_of`) call: a warm
    read makes zero calls, a busted read makes exactly one — and only for the
    target, so a swap/hover never triggers a full-strip rescan. A `bust` for an
    account the principal doesn't own is ignored (no cross-tenant eviction)."""

    class _User:
        account_ids = ["acct-x", "acct-y"]

    class _Resp:
        def __init__(self):
            self.headers: dict[str, str] = {}

    calls: list[str] = []

    async def _fake_compute(aid: str, *, bypass: bool = False) -> dict[str, int]:
        calls.append(aid)
        return {"unread": 1, "owe_reply": 0}

    orig_user = server._get_request_user
    orig_compute = accounts_admin_api._compute_roster_count_of
    server._get_request_user = lambda: _User()
    accounts_admin_api._compute_roster_count_of = _fake_compute
    # Start from a clean cache so the first read is a guaranteed cold miss.
    server.relay_cache.invalidate("roster_count", "acct-x")
    server.relay_cache.invalidate("roster_count", "acct-y")
    try:
        # 1. Cold: both models computed once.
        r_cold = await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        assert sorted(calls) == ["acct-x", "acct-y"], calls
        assert set(r_cold["counts"]) == {"acct-x", "acct-y"}, r_cold

        # 2. Warm: served entirely from cache — no new fetcher calls.
        await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        assert len(calls) == 2, f"warm read recomputed: {calls}"

        # 3. Bust the target: exactly one recompute, only acct-x — and the
        #    response carries ONLY the target, so no other (cold) model can be
        #    re-read off the back of a swap/hover/read.
        r_bust = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust="acct-x")
        assert calls[2:] == ["acct-x"], f"bust rescanned more than target: {calls[2:]}"
        assert set(r_bust["counts"]) == {"acct-x"}, r_bust

        # 4. Bust a foreign id (not owned): ignored — falls through to the full
        #    map (both cached), so nothing recomputed and no foreign eviction.
        r_foreign = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust="acct-z")
        assert calls[3:] == [], f"foreign bust evicted/recomputed: {calls[3:]}"
        assert set(r_foreign["counts"]) == {"acct-x", "acct-y"}, r_foreign
    finally:
        server._get_request_user = orig_user
        accounts_admin_api._compute_roster_count_of = orig_compute
        server.relay_cache.invalidate("roster_count", "acct-x")
        server.relay_cache.invalidate("roster_count", "acct-y")


async def case_assemble_tops_up_past_of_page_cap():
    """OF caps /chats at ~10 rows regardless of `limit` — a limit=25 page must
    be assembled by looping on hasMore and advancing by rows RECEIVED, or the
    frontend's offset math (next offset = 25) skips ranks ~10-24 forever: an
    unread fan there was badge-visible but list-unreachable ("badge 3, list 2")."""
    me = 7

    class _CappedClient(_FakeClient):
        """OF-faithful: never returns more than 10 rows however big `limit` is."""
        def list_chats(self, *, limit=10, offset=0, order="recent", filter=None, **_kw):
            return super().list_chats(
                limit=min(int(limit), 10), offset=offset, order=order, filter=filter,
            )

    recent = [_chat(2000 + i, unread=(1 if i % 5 == 0 else 0)) for i in range(40)]
    fake = _CappedClient(me, recent)

    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    rows = page["list"]
    assert len(rows) == 25, f"top-up assembled {len(rows)} rows, wanted 25"
    assert page["hasMore"] is True, page
    # Rows are the TOP 25 in order — no rank skipped, none duplicated.
    got = [r["withUser"]["id"] for r in rows]
    assert got == [2000 + i for i in range(25)], got[:30]


async def case_assemble_empty_page_ends_pagination():
    """An empty OF read means end-of-data and must carry OF's hasMore=false —
    NOT the loop's True initializer. Returning hasMore=true for an empty page
    (empty inbox, zero-match filter, offset past end) gets cached for the full
    TTL and feeds the frontend's owe-reply scan / infinite scroll a 'more
    available' lie it can never satisfy — an unbounded loadMore loop that
    hammers OF at a new offset per round-trip."""
    fake = _FakeClient(1, [])  # empty inbox
    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    assert page == {"list": [], "hasMore": False}, page

    # Offset past the end of a non-empty inbox: same contract.
    fake2 = _FakeClient(1, [_chat(1)])
    page2 = server._assemble_chats_page(fake2, limit=25, offset=25, order="recent")
    assert page2 == {"list": [], "hasMore": False}, page2


async def case_assemble_dup_only_page_breaks():
    """A page of only already-seen fans (OF offset clamp / heavy rank churn)
    must break the loop, not spin it forever inside the per-account lane."""
    class _StuckClient:
        """OF pathologically serves the SAME page whatever the offset is."""
        def __init__(self):
            self.calls = 0
            self._page = [_chat(4000 + i) for i in range(10)]

        def list_chats(self, **_kw):
            self.calls += 1
            return {"list": list(self._page), "hasMore": True}

    fake = _StuckClient()
    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    assert len(page["list"]) == 10, len(page["list"])
    assert fake.calls == 2, f"dup-only page should stop after 2 reads, made {fake.calls}"


async def case_bust_rewarms_shared_list_window():
    """The badge↔list bridge: a bypass (?bust) recompute re-reads OF ONCE and
    leaves the window cached under the exact "list_chats" key the inbox list
    endpoint reads (PAGE_SIZE 25, offset 0, plain recent view) — so the list
    refetch the frontend chains after a bust is a warm hit of the same rows the
    badge counted, and a warm-window badge recompute costs zero OF calls."""
    me = 3
    AID = "acct-bridge"
    recent = [_chat(3000 + i, unread=(1 if i < 3 else 0)) for i in range(8)]

    class _CountingClient(_FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.calls = 0

        def list_chats(self, **kw):
            self.calls += 1
            return super().list_chats(**kw)

    fake = _CountingClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", AID)
    server.relay_cache.invalidate("roster_count", AID)
    try:
        # Bust path: live read + counts from the same rows.
        out = await accounts_admin_api._compute_roster_count_of(AID, bypass=True)
        assert out == {"unread": 3, "owe_reply": 5}, out
        assert fake.calls == 1, f"bypass read OF {fake.calls}x, wanted 1"

        # Badge recompute off the warm window: zero further OF calls.
        out2 = await accounts_admin_api._compute_roster_count_of(AID)
        assert out2 == out, out2
        assert fake.calls == 1, f"warm-window recompute hit OF: {fake.calls}"

        # The inbox list endpoint's exact cache key is warm: a read through it
        # must be served without invoking its fetcher.
        def _must_not_fetch():
            raise AssertionError("list endpoint fetcher ran — window not shared")
        resp = await server.relay_cache.get_or_fetch(
            "list_chats", AID,
            (server._ROSTER_SCAN_MAX, 0, "recent", None, None, None),
            ttl_seconds=server._LIST_CHATS_TTL, fetcher=_must_not_fetch,
        )
        got = [r["withUser"]["id"] for r in (resp.get("list") or [])]
        assert got == [3000 + i for i in range(8)], got

        # Freshness contract: a window OLDER than _ROSTER_WINDOW_MAX_AGE_S must
        # not be folded from — the recompute escalates to a live OF re-read
        # (which also rewarms the window for the list). Simulate age by
        # back-dating the stamp; the cached entry itself is still valid.
        server._chats_window_fetched_at[AID] = (
            server._time_mod.monotonic() - server._ROSTER_WINDOW_MAX_AGE_S - 1
        )
        out3 = await accounts_admin_api._compute_roster_count_of(AID)
        assert out3 == out, out3
        assert fake.calls == 2, f"aged window must force a live re-read: {fake.calls}"
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", AID)
        server.relay_cache.invalidate("roster_count", AID)
        server._chats_window_fetched_at.pop(AID, None)


async def case_ws_kept_window_is_folded_past_300s_within_its_list_ttl():
    """Mirror-first (09 B10): while the account's WS has stayed connected since
    the window was read, a window past the badge's 300 s age (still inside the
    600 s list TTL) is folded with zero OF calls. A pump that is down, or that
    reconnected after the read (frames in the gap were missed), escalates to the
    live re-read."""
    import of_ws

    me = 4
    AID = "acct-ws-kept"
    recent = [_chat(5000 + i, unread=(1 if i < 2 else 0)) for i in range(6)]

    class _CountingClient(_FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.calls = 0

        def list_chats(self, **kw):
            self.calls += 1
            return super().list_chats(**kw)

    class _Pump:
        connected_at: float | None = None

    fake = _CountingClient(me, recent)
    pump = _Pump()
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", AID)
    try:
        pump.connected_at = server._time_mod.monotonic()
        of_ws.register_pump(AID, pump)
        await accounts_admin_api._compute_roster_count_of(AID)  # cold: one live read
        assert fake.calls == 1, fake.calls
        aged = server._time_mod.monotonic() - server._ROSTER_WINDOW_MAX_AGE_S - 1

        # Connected before the read and still up: the aged window is folded.
        pump.connected_at = aged - 1
        server._chats_window_fetched_at[AID] = aged
        out = await accounts_admin_api._compute_roster_count_of(AID)
        assert out == {"unread": 2, "owe_reply": 4}, out
        assert fake.calls == 1, f"a WS-kept window re-read OF: {fake.calls}"

        # Reconnected after the read: the gap may have missed frames.
        pump.connected_at = aged + 1
        server._chats_window_fetched_at[AID] = aged
        await accounts_admin_api._compute_roster_count_of(AID)
        assert fake.calls == 2, f"a window older than the socket must re-read: {fake.calls}"

        # Pump down: the age rule as before.
        of_ws.unregister_pump(AID)
        server._chats_window_fetched_at[AID] = aged
        await accounts_admin_api._compute_roster_count_of(AID)
        assert fake.calls == 3, f"no pump, aged window must re-read: {fake.calls}"
    finally:
        of_ws.unregister_pump(AID)
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", AID)
        server._chats_window_fetched_at.pop(AID, None)


_harness.run(
    case_ws_kept_window_is_folded_past_300s_within_its_list_ttl,
    case_compute_roster_count_from_of,
    case_roster_count_caps_at_window,
    case_reconcile_pulls_of_read_state_into_local,
    case_roster_bust_recomputes_only_target,
    case_assemble_tops_up_past_of_page_cap,
    case_assemble_empty_page_ends_pagination,
    case_assemble_dup_only_page_breaks,
    case_bust_rewarms_shared_list_window,
)
