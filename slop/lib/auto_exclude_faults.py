"""Auto_Exclude past the 20k backstop: break-it-once faults (scenarios/2026-11-03-auto-exclude-25k.py).
lib/faults.py merges `register(Fault)` into FAULTS. Each patches the product function whose bug
class it names (service/audiences.py, service/auto_exclude_decide.py, service/mass_queue_api.py), by
module attribute, inside the throwaway relay. The check names live here and the scenario imports
them, so a target can never name a check that does not exist.
"""
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
    """The send awaits the full refresh inline: a send that would schedule the background refresh
    runs it inside `ensure_exclude_list`, under the caller's `broadcast_lock` (its holds then take
    no lock of their own: the send already holds it, and the lock is not reentrant). Everything else
    is the product's."""
    import contextlib
    import contextvars

    import audiences

    inline = contextvars.ContextVar("slop_ae_inline", default=False)
    pending: dict = {}
    real_ensure, real_lock = audiences.ensure_exclude_list, audiences.broadcast_lock

    def schedule(account_id, client):
        pending[str(account_id)] = client

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
    """The refresh runs outside `broadcast_lock` and batches against the guard it read when it
    began, never re-checked against the newest one: a stale member a send has just guarded again
    (and so did not re-add: the mirror holds it) is removed between that send's sync and its OF
    POST. The crawl, the batch rule and the mirror updates are the product's (the batch rule reads a
    copy of the mirror: unlocked, a send's add may grow it mid-read)."""
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
    """auto_exclude_decide.next_batch never answers adds: the refresh only removes, so a guard id
    dropped on OF's side is not put back by it."""
    import auto_exclude_decide

    real = auto_exclude_decide.next_batch

    def next_batch(members, guard, n, skip):
        return real(members, guard, n, set(skip) | (set(guard) - set(members)))

    auto_exclude_decide.next_batch = next_batch


def _readds_whole_guard() -> None:
    """A big-list send re-asserts every guard id one by one (today's past-the-backstop cost)
    instead of only the ids its mirror lacks: `audiences._add_missing_blocking` is handed an empty
    member set when it is a mirror's (the confirmed adds still join the mirror). Small lists (a
    crawled member set) are the product's."""
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
    """The composer route's pre-fix hold (service/mass_queue_api.py before W24): `broadcast_lock`
    around `ensure_exclude_list` only, released before the route's `mass_runs` mint and OF POST, so an
    automation send's sync or a refresh batch can rewrite Auto_Exclude before OF reads the blast's
    `excludedLists`. Wraps the seam `mass_queue_api._exclude_list_held` (looked up per call): the real
    sync, its lock released before the route's block runs."""
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
        # slop/run auto-exclude-25k --break (the scenario's FAULT)
        "auto-exclude-refresh-blocks-send": Fault(_refresh_blocks_send, (SEND_LATENCY,)),
        # slop/run auto-exclude-25k --break --fault=auto-exclude-remove-unlocked --baseline=...
        "auto-exclude-remove-unlocked": Fault(_remove_unlocked, (NO_EXCLUDED_SENT,)),
        # slop/run auto-exclude-25k --break --fault=auto-exclude-refresh-skips-readd --baseline=...
        "auto-exclude-refresh-skips-readd": Fault(_refresh_skips_readd, (EXTERNAL_READD,)),
        # slop/run auto-exclude-25k --break --fault=auto-exclude-readds-whole-guard --baseline=...
        "auto-exclude-readds-whole-guard": Fault(_readds_whole_guard, (SEND_LATENCY,)),
        # slop/run auto-exclude-25k --break --fault=auto-exclude-manual-lock-early --baseline=...
        "auto-exclude-manual-lock-early": Fault(_manual_lock_early, (MANUAL_NO_EXCLUDED_SENT,)),
    }
