"""sales_amend — the owner's amends to who a sale credits (Sales records'
Reassign; roadmap W6 6.5, Infloww's `/amend/employee/transactions`).

  POST /admin/ingest/transactions/{id}/attribute  {employee_id}
       → {id, account_id, kind, amount_cents, attributed_employee_id}: one sale.
  POST /admin/ingest/transactions/attribute
       {employee_id, tx_ids[1..500]}  or  {employee_id, clock_event_id}
       → {updated, attributed_employee_id, tx_ids, skipped_split}: a batch,
       every sale or none (any refusal writes nothing). With `clock_event_id`
       the sales are that Clock event's (`sales_attribution.event_sales`: the shares
       credited to its Employee inside its time on a Creator, the Timesheet's
       rule), so Shift records' "Reassign sales" moves one shift's sales; a
       sale split with other Employees (Shift schedule) is left as it is and
       counted in `skipped_split`, so their shares stay theirs.

`employee_id` is an Employee id (the override `transactions.attributed_employee_id`
names it), `"no_one"` (the override `sales_attribution.NO_ONE`: credited to
nobody, whatever the rules say) or null (the override cleared, so the Sales
Settings rules credit the sale again). Owner or Master sessions only (a
chatter 403, no session 401); a sale outside the caller's Creators is 404;
an Employee outside a sale's Agency is 400. Each sale's write adds one
`sales.reassign` action in the same commit (`reassign`).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select, update

from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from auth import _actor_account_ids
from clock_api import _sweep_callers_agencies
from db.engine import get_session
from db.models import Action, ClockEvent, Employee, Transaction, UserAccount
from employees import owner_context
from sales_attribution import NO_ONE, event_sales
from shifts_api import _own_row

router = APIRouter(tags=["sales"])
log = logging.getLogger("of-relay")

MAX_BATCH = 500
_MISSING = object()


def parse_employee(payload: dict[str, Any]) -> int | None:
    """The body's `employee_id`: an int, `NO_ONE` for "no_one", None to clear."""
    raw = payload.get("employee_id", _MISSING)
    if raw is _MISSING:
        raise HTTPException(status_code=400, detail='employee_id required (an id, "no_one" or null)')
    if raw is None:
        return None
    if raw == "no_one":
        return NO_ONE
    try:
        employee_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='employee_id must be an int, "no_one" or null') from None
    if employee_id == NO_ONE or isinstance(raw, bool):
        raise HTTPException(status_code=400, detail='employee_id must be an int, "no_one" or null')
    return employee_id


async def reassign(s, ctx, tx_ids: list[int], employee_id: int | None) -> list[Any]:
    """Set the override of every sale in `tx_ids` to `employee_id` (see
    `parse_employee`) in session `s`, each with its `sales.reassign` action,
    or refuse before writing anything. Returns the sales' rows (id, kind,
    account_id, amount_cents) in `tx_ids` order.

    Each action's payload holds the actor (`owner:<id>` or `master:<id>`),
    the old and new override `employee_id` (`NO_ONE` for "No one") and
    `shown_before`, the Employee the attribution view credited at write time
    (null for nobody).

    ASSUMPTION: the old and new `employee_id` (`before`, `after`) are the
    override column's (`attributed_employee_id`), the value this route
    writes, so clearing an override records `after: null` even where the
    Rule then credits someone; beside them `shown_before` holds the Employee
    the attribution view credited at write time (what the Sales records row
    showed; null for an unassigned sale or one the view does not carry), so
    the change is traceable either way. Rung 5. Overturned if the audit
    should also record the Employee the view credits after the write.

    ASSUMPTION: for the Master the sale's Agency is any owner holding its
    Creator in `user_accounts`; for an owner it is that owner's own Agency.
    Rung 1 (Employees belong to one owner, `employees.user_id`; the Master's
    Creators are every Agency's, auth._master_account_ids). Overturned if a
    Creator shared by two Agencies should accept either's Employees from an
    owner session."""

    t = Transaction
    found = {r.id: r for r in (await s.execute(
        select(t.id, t.kind, t.account_id, t.amount_cents, t.attributed_employee_id,
               # The view's answer, materialised on the row (tx_rollup.py), for a sale the view carries.
               t.credit_employee_id,
               (t.status.in_(TRACKED_STATUSES) & t.kind.in_(REVENUE_KINDS)).label("in_view"))
        .where(t.id.in_(tx_ids))
    )).all()}
    owned = _actor_account_ids() or ()
    if any(tid not in found or found[tid].account_id not in owned for tid in tx_ids):
        raise HTTPException(status_code=404, detail="sale not found")

    if employee_id not in (None, NO_ONE):
        # An owner's Creators are its own `user_accounts` rows
        # (auth.AuthedUser.account_ids), so the 404 above already proves it
        # holds these: its Agency is itself. Only the Master, whose Creators
        # are every Agency's, needs each Creator's holders looked up.
        agency_of: dict[str, set[str]] = {}
        for aid in {found[tid].account_id for tid in tx_ids}:
            agency_of[aid] = {ctx.agency_user_id} if not ctx.is_master else set((await s.execute(
                select(UserAccount.user_id).where(UserAccount.account_id == aid))).scalars().all())
        home = (await s.execute(select(Employee.user_id).where(Employee.id == employee_id))).scalar()
        if home is None or any(home not in agencies for agencies in agency_of.values()):
            raise HTTPException(status_code=400, detail="employee not in this sale's agency")

    await s.execute(update(t).where(t.id.in_(tx_ids)).values(attributed_employee_id=employee_id))
    actor = f"{'master' if ctx.is_master else 'owner'}:{ctx.agency_user_id}"
    now = datetime.utcnow()
    for tid in tx_ids:
        tx = found[tid]
        shown_before = (tx.credit_employee_id or None) if tx.in_view else None
        s.add(Action(
            employee_id=None,
            account_id=tx.account_id,
            action="sales.reassign",
            target_type="transaction",
            target_id=str(tid),
            payload_json=json.dumps({"actor": actor,
                                     "before": {"employee_id": tx.attributed_employee_id},
                                     "after": {"employee_id": employee_id},
                                     "shown_before": {"employee_id": shown_before}}),
            at=now,
        ))
    return [found[tid] for tid in tx_ids]


@router.post("/admin/ingest/transactions/attribute")
async def reassign_batch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Reassign many sales at once: `tx_ids` (Sales records' batch select) or
    one Clock event's sales (`clock_event_id`, Shift records), to an
    Employee, "no_one" or null (see the module docstring). The Auto
    clock-out sweep runs before a Clock event is read, so an overdue open
    event's sales stop at its auto clock-out, as Shift records show them.

    ASSUMPTION: a Clock event's sales are read when the request runs, so a
    sale whose credit the write moves away from the event's Employee is no
    longer that event's; repeating the request then finds fewer (or none)
    and answers `updated: 0`, never an error. Rung 5. Overturned if Shift
    records should remember which sales a shift once had.

    ASSUMPTION: a split sale (Shift schedule credits its shares to several
    Employees on the clock) is skipped by a Clock event's reassign, since an
    override moves the whole sale and would take the other Employees' shares
    too; Sales records' `tx_ids` batch still moves a split sale the owner
    picked. Owner decision (W6 review). Overturned if a shift's reassign
    should move only its own share."""

    ctx = await owner_context(None, "only the agency owner reassigns a sale")
    employee_id = parse_employee(payload)
    has_ids, has_event = "tx_ids" in payload, "clock_event_id" in payload
    if has_ids == has_event:
        raise HTTPException(status_code=400, detail="send tx_ids or clock_event_id")
    split: set[int] = set()
    if has_event:
        await _sweep_callers_agencies()
    async with get_session() as s:
        if has_event:
            ev = await _own_row(s, ctx, ClockEvent, str(payload["clock_event_id"]), "clock event")
            shares = (await event_sales(s, [ev], datetime.utcnow()))[ev.id]
            split = {c.tx_id for c in shares if c.split}
            tx_ids = [tid for tid in dict.fromkeys(c.tx_id for c in shares) if tid not in split]
        else:
            raw = payload["tx_ids"]
            if (not isinstance(raw, list) or not raw or len(raw) > MAX_BATCH
                    or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw)):
                raise HTTPException(status_code=400, detail=f"tx_ids: 1 to {MAX_BATCH} sale ids")
            tx_ids = list(dict.fromkeys(raw))
        if tx_ids:
            await reassign(s, ctx, tx_ids, employee_id)
    return {"updated": len(tx_ids), "attributed_employee_id": employee_id, "tx_ids": tx_ids,
            "skipped_split": len(split)}


@router.post("/admin/ingest/transactions/{tx_id}/attribute")
async def reassign_one(tx_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Manually assign, set to "No one", or clear the employee one sale
    counts toward (Sales records' Reassign, the orphan lists). Pass
    `{"employee_id": <int>}` to assign, `{"employee_id": "no_one"}` for "No
    one" or `{"employee_id": null}` to clear; the override wins over the
    Sales Settings rules.

    Reassign (docs/spec/phase-05-remaining-parity-gaps.md, item 3; ticket
    34): an owner session or the Master only (a chatter 403, even under Role
    enforcement; no session 401); a sale outside the caller's Creators is
    404; an Employee outside the sale's Agency (an owner of its Creator, and
    the caller's own Agency for an owner session) is 400. The write adds one
    `sales.reassign` action in the same commit (`reassign`); the audit
    middleware's generic row is still written, and Sales records' "Assigned
    by" reads only `sales.reassign` rows."""

    ctx = await owner_context(None, "only the agency owner reassigns a sale")
    employee_id = parse_employee(payload)
    async with get_session() as s:
        [tx] = await reassign(s, ctx, [tx_id], employee_id)
    log.info("admin_ingest_tx_attribute tx=%d employee=%s kind=%s account=%s amount=%d",
             tx_id, employee_id, tx.kind, tx.account_id, tx.amount_cents)
    return {
        "id": tx_id,
        "account_id": tx.account_id,
        "kind": tx.kind,
        "amount_cents": int(tx.amount_cents or 0),
        "attributed_employee_id": employee_id,
    }
