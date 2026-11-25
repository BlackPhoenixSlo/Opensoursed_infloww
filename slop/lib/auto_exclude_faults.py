from __future__ import annotations

NO_EXCLUDED_SENT = ("AE_NO_EXCLUDED_SENT: no send reached a fan of its guard (bar ids OF refused to list, "
                    "and an OF-side drop until the next refresh ended)")
SEND_LATENCY = ("AE_SEND_LATENCY: big-list enqueue -> OF accept p95 within budget and <= control p95 x 1.5 + 2 s "
                "while the refresh runs")
CONVERGES = ("AE_CONVERGES: after quiet the big list == the newest guard (bar refused), no stale member past "
             "20k, its refresh crawl read > 20k")
SINGLE_FLIGHT = "AE_SINGLE_FLIGHT: at most one background refresh per Creator at a time, and one ran"
EXTERNAL_READD = ("AE_EXTERNAL_READD: guard ids dropped on OF's side are re-added by the next background "
                  "refresh, members again at its end")
SMALL_EXACT = "AE_SMALL_EXACT: the control Creator's list (<20k) == its guard after every send, never refreshed"
MANUAL_NO_EXCLUDED_SENT = ("AE_MANUAL_NO_EXCLUDED_SENT: no composer blast (POST /api/of/v2/messages/queue) reached "
                           "a fan it excluded or of its guard, racing automation sends and the refresh")


def _refresh_blocks_send() -> None:
    import contextlib
    import contextvars

    import audiences

    inline = contextvars.ContextVar("slop_ae_inline", default=False)
    pending: dict = {}
    real_ensure, real_lock = audiences.ensure_exclude_list, audiences.broadcast_lock

    def schedule(account_id, client):
        pending[str(account_id)] = client

    # the inline send already holds broadcast_lock and it is not reentrant: its holds take none
    def broadcast_lock(account_id):
        return contextlib.nullcontext() if inline.get() else real_lock(account_id)

    async def ensure_exclude_list(account_id, ids, *, client=None):
        lid = await real_ensure(account_id, ids, client=client)
        c = pending.pop(str(account_id), None)
        if c is not None:
            tok = inline.set(True)
            try:
                await audiences._refresh_auto_exclude(str(account_id), c)
            finally:
                inline.reset(tok)
        return lid

    audiences._schedule_auto_exclude_refresh = schedule
    audiences.broadcast_lock = broadcast_lock
    audiences.ensure_exclude_list = ensure_exclude_list


def _remove_unlocked() -> None:
    import contextlib
    import contextvars

    import audiences
    import auto_exclude_decide

    began = contextvars.ContextVar("slop_ae_guard_at_begin", default=None)
    real_refresh, real_lock = audiences._refresh_auto_exclude, audiences.broadcast_lock
    real_next = auto_exclude_decide.next_batch

    async def _refresh_auto_exclude(account_id, client, *a, **kw):
        m = audiences._ae_mirrors.get(str(account_id))
        tok = began.set(m.guard if m is not None else frozenset())
        try:
            return await real_refresh(account_id, client, *a, **kw)
        finally:
            began.reset(tok)

    def broadcast_lock(account_id):
        return contextlib.nullcontext() if began.get() is not None else real_lock(account_id)

    def next_batch(members, guard, n, skip):
        g = began.get()
        return real_next(set(members), guard if g is None else g, n, skip)

    audiences._refresh_auto_exclude = _refresh_auto_exclude
    audiences.broadcast_lock = broadcast_lock
    auto_exclude_decide.next_batch = next_batch


def _refresh_skips_readd() -> None:
    import auto_exclude_decide

    real = auto_exclude_decide.next_batch

    def next_batch(members, guard, n, skip):
        return real(members, guard, n, set(skip) | (set(guard) - set(members)))

    auto_exclude_decide.next_batch = next_batch


def _readds_whole_guard() -> None:
    import audiences

    real = audiences._add_missing_blocking

    def _add_missing_blocking(client, list_id, members, ids):
        if not any(m.members is members for m in list(audiences._ae_mirrors.values())):
            return real(client, list_id, members, ids)
        added: set = set()
        try:
            return real(client, list_id, added, ids)
        finally:
            members |= added

    audiences._add_missing_blocking = _add_missing_blocking


def _manual_lock_early() -> None:
    import contextlib

    import mass_queue_api

    real = mass_queue_api._exclude_list_held

    @contextlib.asynccontextmanager
    async def _exclude_list_held(*a, **kw):
        async with real(*a, **kw) as lid:
            pass
        yield lid

    mass_queue_api._exclude_list_held = _exclude_list_held


def register(Fault) -> dict:
    return {
        "auto-exclude-refresh-blocks-send": Fault(_refresh_blocks_send, (SEND_LATENCY,)),
        "auto-exclude-remove-unlocked": Fault(_remove_unlocked, (NO_EXCLUDED_SENT,)),
        "auto-exclude-refresh-skips-readd": Fault(_refresh_skips_readd, (EXTERNAL_READD,)),
        "auto-exclude-readds-whole-guard": Fault(_readds_whole_guard, (SEND_LATENCY,)),
        "auto-exclude-manual-lock-early": Fault(_manual_lock_early, (MANUAL_NO_EXCLUDED_SENT,)),
    }
