"""Smart Lists' break-it-once faults (scenarios/2026-11-01-smart-lists-50k.py): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist.
"""
from __future__ import annotations

ORACLE = ("every rule row (one per operator, each threshold with a fan exactly on it, `between` with fans "
          "on both bounds, AND, OR, empty): preview.count == len(resolve) == the harness Creator-scoped SQL oracle, "
          "same fan set, with a fan on two Creators answered differently by their own facts")
CAP = ("activation storm (cap + N concurrent activates): exactly cap answered 2xx, the rest 409, never more "
       "than SMART_LIST_MAX_ACTIVE lists active; then a deactivate frees one slot a 409'd list takes")

ACTIVATE_PATH = "/admin/smart-lists/{list_id}/activate"
HOLD_S = 0.05   # the fault's gap between the count read and the write
# What the real activate handler references that `racy` does not (the in-UPDATE quota, the syncing
# 409, the log line). Anything else differing means the handler changed: the fork is stale (INFRA).
_RACY_OMITS = {"scalar_subquery", "sync_state", "log", "info"}
_QUOTA_MARKER = "active < cap"   # the real handler's quota, inside its UPDATE's WHERE


def _between_exclusive_bound() -> None:
    """`between` drops both bounds: lo < x < hi instead of lo <= x <= hi (smart_list_rules._num_cmp, which
    `_eval_rule` looks up per call for every money / v1 numeric rule). Every other operator answers as
    before, so only a rule row whose fans sit exactly on a bound can see it."""
    import smart_list_rules

    real = smart_list_rules._num_cmp

    def exclusive(a, op, b):
        if op == "between":
            lo, hi = b
            return float(lo) < a < float(hi)
        return real(a, op, b)

    smart_list_rules._num_cmp = exclusive


def _cap_read_then_write() -> None:
    """The quota as a read-then-write: activate counts the Creator's active lists in one statement, awaits
    (HOLD_S, any await between them does), then flips is_active without the count in the UPDATE. Concurrent
    activations all read the same count, so more than the cap win. The route's endpoint is swapped on the
    app's own APIRoute (`dependant.call`, read per request by FastAPI's handler); everything else
    (ownership, the sync lock, ensure_kind_rule, _queue_sync, the answer) is the product's own code.
    Drift guard: the real handler must still hold the in-UPDATE quota and reference nothing `racy` does
    not beyond _RACY_OMITS, else SystemExit (INFRA): a changed handler would make `racy` a stale fork."""
    import asyncio
    import inspect

    from fastapi import HTTPException
    from fastapi.routing import APIRoute
    from sqlalchemy import func, select, update

    import server
    import smart_lists_api as m
    from db.engine import get_session
    from db.models import SmartList

    async def racy(list_id: int):
        from automation_rules_api import ensure_kind_rule
        async with get_session() as s:
            row = await m._owned_row(s, list_id)
            if not row.is_active:
                cap = m._max_active()
                active = (await s.execute(
                    select(func.count()).select_from(SmartList)
                    .where(SmartList.account_id == row.account_id, SmartList.is_active.is_(True)))).scalar_one()
                await asyncio.sleep(HOLD_S)
                if active >= cap:
                    raise HTTPException(409, f"a maximum of {cap} smart lists can be active")
                res = await s.execute(update(SmartList).where(SmartList.id == list_id, m._NOT_SYNCING)
                                      .values(is_active=True, sync_error=None))
                if res.rowcount != 1:
                    raise HTTPException(409, m._LOCKED)
                await s.refresh(row)
            await ensure_kind_rule(s, row.account_id, m.SYNC_KIND, enable=True)
            await m._queue_sync(s, row.account_id)
            await s.flush()
            out = m._serialize(row)
        m._wake()
        return out

    real = inspect.unwrap(m.activate_smart_list)
    omits = set(real.__code__.co_names) - set(racy.__code__.co_names) - set(racy.__code__.co_freevars)
    if _QUOTA_MARKER not in inspect.getsource(real) or omits != _RACY_OMITS:
        raise SystemExit(f"slop: smart-list-cap-read-then-write: smart_lists_api.activate_smart_list changed "
                         f"(quota marker {_QUOTA_MARKER!r} present: {_QUOTA_MARKER in inspect.getsource(real)}; "
                         f"names racy lacks {sorted(omits)}, expected {sorted(_RACY_OMITS)}): re-fork `racy`")
    hits = [r for r in server.app.routes
            if isinstance(r, APIRoute) and r.path == ACTIVATE_PATH and "POST" in r.methods]
    if len(hits) != 1:
        raise SystemExit(f"slop: smart-list-cap-read-then-write found {len(hits)} POST {ACTIVATE_PATH} routes")
    hits[0].dependant.call = racy


def _ledger_org_leak() -> None:
    """Creator-scope ledger facts summed over the whole agency (smart_lists_api._ledger_facts, looked up
    per call by `_load_normalised_fans`): every creator-scope money rule is asked as org scope and the
    answers filed back under the creator keys. A fan with ledger rows on one Creator only answers as
    before, so only a fan on two of the owner's Creators can see it."""
    import smart_lists_api as m

    real = m._ledger_facts

    async def leaky(s, account_id, rules, now):
        org = [dict(r, scope="org") if (r.get("scope") or "creator") == "creator" else r for r in rules]
        out = await real(s, account_id, org, now)
        return {fid: {k.replace(":org", ":creator"): v for k, v in facts.items()} for fid, facts in out.items()}

    m._ledger_facts = leaky


def _projection_drops_column() -> None:
    """The loader's Fan projection (smart_lists_api._FAN_COLS, read per call by `_load_normalised_fans`)
    still yields a `last_message_sent_at` key but selects a literal NULL for it: every fan reads as never
    messaged, so the ORACLE rows on that date (within_last / more_than) answer empty. Dropping the column
    instead would raise on attribute access (a 5xx the stock check sees too)."""
    from sqlalchemy import literal

    import smart_lists_api as m

    cols = [c for c in m._FAN_COLS if getattr(c, "key", None) != "last_message_sent_at"]
    if len(cols) != len(m._FAN_COLS) - 1:
        raise SystemExit("slop: smart-list-projection-drops-column: no last_message_sent_at in _FAN_COLS")
    m._FAN_COLS = (*cols, literal(None).label("last_message_sent_at"))


def register(Fault) -> dict:
    return {
        # slop/run smart-lists-50k --break (the scenario's FAULT)
        "smart-list-between-exclusive-bound": Fault(_between_exclusive_bound, (ORACLE,)),
        # slop/run smart-lists-50k --break --fault=smart-list-cap-read-then-write
        "smart-list-cap-read-then-write": Fault(_cap_read_then_write, (CAP,)),
        # slop/run smart-lists-50k --break --fault=smart-list-ledger-org-leak
        "smart-list-ledger-org-leak": Fault(_ledger_org_leak, (ORACLE,)),
        # slop/run smart-lists-50k --break --fault=smart-list-projection-drops-column
        "smart-list-projection-drops-column": Fault(_projection_drops_column, (ORACLE,)),
    }
