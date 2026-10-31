"""
stats_sales_records.py — Sales records, split out of stats.py.

  GET /admin/stats/sales-records    → one row per credited share of a sale, as
                                       Employee reports credit it, with its
                                       Rule (JSON pages or CSV)

stats.py includes this router where the route stood (route order). The
report zone is read as `stats._report_zone` at call time (imported in the
route, no import-time cycle), so a patch on `stats` reaches this route as before
the split.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, case, cast, or_, select
from sqlalchemy.orm import aliased

import csv_export
from attribution_backfill import TRACKED_STATUSES
from auth import clamp_account_filter
from db.engine import get_session
from db.models import Action, Employee, EmployeeGroup, Fan, Transaction
from sales_attribution import CREDITED_KINDS, credit_context, credit_row
from stats_window import parse_date as _parse_date, stats_guard

router = APIRouter(dependencies=[Depends(stats_guard)])

# One Sales record, in order: the JSON row's keys and the CSV header.
SALES_RECORD_FIELDS = (
    "tx_id", "occurred_at", "employee_id", "employee_name", "account_id", "fan_id", "fan_label",
    "earnings_cents", "gross_cents", "net_cents", "kind", "rule", "assigned_by", "status",
)


# Who a `sales.reassign` action's actor reads as in "Assigned by" (ticket 34).
_REASSIGN_ACTORS = {"owner": "Owner", "master": "Master"}


def _assigned_by(rule: str, reassign_payload: str | None, override_id: int | None) -> str:
    """"Auto" for rule-based credit; for an override, who set it, read only
    from the sale's latest `sales.reassign` action (never the audit
    middleware's generic row) and only while that action's new Employee is
    still the override (`override_id`, `transactions.attributed_employee_id`),
    else "Manual": an override set before reassigns were recorded, or since
    by a writer that recorded none (the former ingest orphan sweep,
    attribution_backfill's history, filled empty overrides).

    ASSUMPTION: the Master reads as "Master", not by name: the payload names
    its actor `master:<users.id>`, and the page shows no owner names. Rung 5.
    Overturned if the Master's username should be shown."""
    if rule != "manual":
        return "Auto"
    if not reassign_payload:
        return "Manual"
    entry = json.loads(reassign_payload)
    if entry["after"]["employee_id"] != override_id:
        return "Manual"
    # The reassign route writes only `owner:<id>` and `master:<id>`.
    return _REASSIGN_ACTORS[entry["actor"].split(":", 1)[0]]


def _sales_record(r: Any, employee_id: int | None, cents: int, rule: str) -> dict[str, Any]:
    """One credited share of sale `r`: the Employee, amount and rule
    `sales_attribution.credit` gave it (`employee_name` is filled per batch,
    `_named`)."""
    return {
        "tx_id": int(r.tx_id),
        "occurred_at": r.occurred_at.isoformat() + "Z",
        "employee_id": employee_id,
        "employee_name": None,
        "account_id": r.account_id,
        "fan_id": int(r.fan_id) if r.fan_id is not None else None,
        "fan_label": r.of_display_name or (f"@{r.of_username}" if r.of_username else None),
        "earnings_cents": cents,
        "gross_cents": int(r.amount_cents),
        "net_cents": int(r.net_cents) if r.net_cents is not None else None,
        "kind": r.kind,
        "rule": rule,
        "assigned_by": _assigned_by(rule, r.reassign_payload, r.override_id),
        "status": r.status,
    }


@router.get("/admin/stats/sales-records", response_model=None)
async def sales_records(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: list[str] | None = Query(None),
    employee_id: list[int] | None = Query(None),
    group_id: int | None = Query(None),
    kind: list[str] | None = Query(None),
    assigned: str = Query("all", pattern="^(all|assigned|unassigned)$"),
    before_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Sales records (docs/spec/phase-05-remaining-parity-gaps.md, item 3):
    one row per credited share of each sale Employee reports count, newest
    first: the sale credited by its Agency's Sales Settings exactly as
    Employee reports credit it (`sales_attribution.credit`, roadmap S7), so a
    Shift schedule split is one row per Employee and a sale "Exclude welcome
    messages" drops is not listed. Each row has the credited Employee, the
    `rule` that chose it (`manual`, `message`, `converters`, `shift` or
    `unassigned`; a "No one" override is `manual` with no Employee),
    "Assigned by" ("Auto" for rule-based credit; for an override "Owner"
    or "Master" from its latest `sales.reassign` action while it still
    names the override, else "Manual"; `_assigned_by`), and
    `earnings_cents`, the share Employee reports add up (net of the fee
    under "Exclude the 20% OnlyFans fee"), beside the sale's `gross_cents`
    and OnlyFans' `net_cents`.

    Filters: `from`/`to` (bare dates in the Agency's report time zone, as
    every report), `account_id*`, `employee_id*`, `group_id` (the sales
    credited to the Employees placed in that Employee group; another
    Agency's or a missing group is 404), `kind*` and `assigned` (Infloww's three-way filter: `all`, `assigned`
    rows that credit an Employee, `unassigned` rows that credit nobody, "No one" included). JSON pages by `before_id` (the last row's `tx_id`;
    `next_before_id` is null on the last page; an id outside the requested
    Creators gives an empty page). `format=csv` streams the whole filtered
    set instead, ignoring `limit` and `before_id`, read inside the response
    generator as `/admin/paid-messages` does (messages.py): `X-Row-Count`
    carries the row cap (`csv_export.CSV_MAX_ROWS`, 50,000), an upper bound
    sent before the body rather than the exact count, and a file that hits
    the cap ends in a TRUNCATED line.

    Phase 1's Agency context answers 401 with no session (whatever
    ALLOW_ANONYMOUS_ADMIN says). Rows are the caller's own Creators
    (`clamp_account_filter`); a named Creator outside them, another Agency's
    or unknown, is 404. Under Role enforcement a chatter whose Data scope is
    not "all" sees only its own Employee's sales, or with "Self and
    subordinates" also those of the Employees in the groups below its own
    (`permissions.scoped_employee_ids`); with it off, the Employee reports
    scope holds.

    ASSUMPTION: `group_id` keeps the Employees placed in that group itself,
    not those of its sub-groups, as the Manage employees rail filters to one
    group. Rung 5. Overturned if the owner wants a group to include its
    sub-groups' sales.

    ASSUMPTION: the Data scope is read across every Agency the chatter is
    linked to, the named Creator unread, as Employee reports reads it
    (`scoped_employee_ids`). Rung 4: never wider than a stored scope.
    Needs-the-human: `scoped_employee_ids` says to revisit "if per_employee
    gains a Creator filter", and this route has one (`account_id*`); reading
    every linked Agency is only ever narrower than following the named
    Creator's Agency. Overturned if the scope should follow the named
    Creator's Agency alone.

    ASSUMPTION: a single foreign `?account_id=` is refused 403 by the account
    isolation middleware (server.py) before this route's 404 runs; spec story
    55 allows 403/404 across Agencies. Rung 1 (the gate is in the code).
    Overturned if every cross-Agency Creator id must answer 404 alone.

    ASSUMPTION: rows are ordered newest first by `occurred_at`, ties by the
    higher `tx_id`, and `before_id` resumes after that sale's place in the
    order (not `tx_id < before_id`), so the Date & time column reads in
    order. Rung 5. Overturned if a cursor must be a bare id comparison.

    ASSUMPTION: a JSON page ends on a whole sale, so a page can run past
    `limit` by the rest of a split sale's shares, and `before_id` stays a
    sale id. Rung 5. Overturned if a page must hold exactly `limit` rows."""
    import stats
    from employees import agency_contexts
    from permissions import scoped_employee_ids

    contexts = await agency_contexts()
    visible = clamp_account_filter(None) or []
    accounts = list(dict.fromkeys(account_id)) if account_id else list(visible)
    if any(a not in visible for a in accounts):
        raise HTTPException(status_code=404, detail="creator not found")
    if group_id is not None:
        async with get_session() as s:
            group = await s.get(EmployeeGroup, group_id)
        if group is None or group.agency_user_id not in {c.agency_user_id for c in contexts}:
            raise HTTPException(status_code=404, detail="group not found")
    own = await scoped_employee_ids()
    zone = await stats._report_zone(accounts[0] if account_id and len(accounts) == 1 else None)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)

    t = Transaction
    # The latest `sales.reassign` action for a manual row only; matching on
    # the sale's Creator lets ix_actions_account_at narrow the audit table.
    # ASSUMPTION: this per-row subquery scans the Creator's whole audit
    # history (only (account_id, at) is indexed), once per manual row, so a
    # 50,000-row CSV of mostly overridden sales may be slow. Rung 5: no
    # migration for an unmeasured cost. Needs-the-human: if it is slow, the
    # fix is an index on actions (action, target_id). Overturned by a
    # measured slow Sales records read or Export.
    reassign = (
        select(Action.payload_json)
        .where(Action.account_id == t.account_id, Action.action == "sales.reassign",
               Action.target_type == "transaction", Action.target_id == cast(t.id, String))
        .order_by(Action.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    q = (
        select(t.id.label("tx_id"), t.occurred_at, t.account_id, t.fan_id, t.amount_cents, t.net_cents, t.kind,
               t.status, t.message_id, t.credit_employee_id, t.credit_rule, t.credit_automation_kind,
               t.credit_sender_id, t.credit_converter_id, t.credit_converter_at,
               Fan.of_display_name, Fan.of_username,
               case((t.credit_rule == "manual", reassign), else_=None).label("reassign_payload"),
               t.attributed_employee_id.label("override_id"))
        .select_from(t)
        .outerjoin(Fan, and_(Fan.account_id == t.account_id, Fan.fan_id == t.fan_id))
        .where(t.account_id.in_(accounts), t.status.in_(TRACKED_STATUSES), t.kind.in_(CREDITED_KINDS))
    )
    if start:
        q = q.where(t.occurred_at >= start)
    if end:
        q = q.where(t.occurred_at <= end)
    if kind:
        q = q.where(t.kind.in_(kind))
    q = q.order_by(t.occurred_at.desc(), t.id.desc())
    if format != "csv" and before_id is not None:
        # The cursor sale must be one of the requested Creators', so another
        # Agency's id reveals nothing about when its sales happened.
        cursor = aliased(Transaction)
        at = (select(cursor.occurred_at)
              .where(cursor.id == before_id, cursor.account_id.in_(accounts))
              .scalar_subquery())
        q = q.where(or_(t.occurred_at < at, and_(t.occurred_at == at, t.id < before_id)))

    # The Employees a share may credit: every filter naming some, intersected.
    wanted: set[int] | None = None
    async with get_session() as s:
        ctx = await credit_context(s, accounts, start, end)
        members = None if group_id is None else set(
            (await s.execute(select(Employee.id).where(Employee.group_id == group_id))).scalars())
    for keep in (set(employee_id) if employee_id else None, members, own):
        if keep is not None:
            wanted = keep if wanted is None else wanted & keep
    if wanted is not None:
        # A share credits the sale's materialised Employee, its linked
        # message's sender (Message sender), its converter candidate (a
        # Converters window other than the default), or under Shift schedule
        # whoever was on the clock (`credit`).
        q = q.where(or_(t.credit_employee_id.in_(wanted), t.credit_sender_id.in_(wanted),
                        t.credit_converter_id.in_(wanted), t.account_id.in_(ctx.shift_accounts)))

    def _records(r: Any) -> list[dict[str, Any]]:
        """Sale `r`'s shares the filters keep, one record each."""
        return [_sales_record(r, eid, cents, rule) for eid, cents, rule in credit_row(ctx, r)
                if (wanted is None or eid in wanted)
                and assigned in ("all", "unassigned" if eid is None else "assigned")]

    names: dict[int, str | None] = {}

    async def _named(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """`recs` with their Employees' names, read for the ids not read yet."""
        if new := {r["employee_id"] for r in recs} - names.keys() - {None}:
            names.update(dict.fromkeys(new))
            async with get_session() as ns:
                names.update((await ns.execute(
                    select(Employee.id, Employee.display_name).where(Employee.id.in_(new)))).tuples().all())
        for rec in recs:
            rec["employee_name"] = names.get(rec["employee_id"])
        return recs

    if format != "csv":
        # A page ends on a whole sale: a split sale's shares are never parted.
        page: list[dict[str, Any]] = []
        more = False
        async with get_session() as s:
            async for r in await s.stream(q.execution_options(yield_per=limit + 1)):
                recs = _records(r)
                if recs and len(page) >= limit:
                    more = True
                    break
                page += recs
        return {"rows": await _named(page), "next_before_id": page[-1]["tx_id"] if more else None}

    async def _all_records(s):
        batch: list[dict[str, Any]] = []
        async for r in await s.stream(q.execution_options(yield_per=500)):
            batch += _records(r)
            if len(batch) >= 500:
                for rec in await _named(batch):
                    yield rec
                batch = []
        for rec in await _named(batch):
            yield rec

    safe = csv_export.safe_filename_part
    return csv_export.download(
        f"sales-records_{safe(from_, 'start')}_to_{safe(to, 'now')}.csv", _all_records, SALES_RECORD_FIELDS,
        lambda rec: ["" if rec[k] is None else rec[k] for k in SALES_RECORD_FIELDS],
    )
