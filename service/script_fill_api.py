"""service/script_fill_api.py — Fill one Growth > Scripts Sequence with the Creator's own vault media
(docs/spec/phase-01-fill-engine-and-describe-target.md, sub-phase 1b; ADR-0045, ADR-0046).

  POST /admin/saved-replies/fill/plan?account_id=   {sequence}               -> 200 FillPlan
  POST /admin/saved-replies/fill/apply?account_id=  {sequence, fingerprint?} -> 200 {status, plan, applied, undo}
                                                                              | 409 {error: stale, plan}
  POST /admin/saved-replies/fill/undo?account_id=   {sequence, undo: [UndoEntry]} -> 200 {undone, kept}

`script_fill_decide` decides; this module loads, gates and writes. Every route: `account_id` required and
non-empty (400 `account_id_required`), then `assert_account_owned` (403), then `assert_owner_scope`
(403 `folder_not_allowed`: Fill needs Whole-vault access). `sequence` is the `script_id`; no rows -> 404
`sequence_not_found`; vault unreadable (`full_ai_sell.load_rows` Refusal) -> 503 `inventory_unknown`, nothing
written. Every non-`ok` status is a 200 with zero writes. Role enforcement maps the routes to the Scripts page
(`/admin/saved-replies/` prefix); `permissions` only gains `route_refusal`, the middleware's decision
factored out unchanged so the blocked sentence below reads the same rule.

Inputs `script_fill_decide.plan_over_vault` gets (it gates, builds Shoots and plans): the Sequence rows; the
Creator's live vault (`load_rows` rows stamped with `account_id`, `review_state`, `operator_overrides_json`,
laid over by `script_fill_decide.effective`), its dupe sets and prints; every live media id; media on the
Creator's other Sequences (`script_fill_decide.sequence_media_ids`); the Creator's `standard_folders` switch;
coverage (`vault_ai_vision.describe_coverage` at `DESCRIBE_TARGET`); the blocked sentence; and
`template_prices` (below).

Blocked sentence, first that applies: the caller's role would refuse describe-all
(`permissions.route_refusal`, the role middleware's own decision) -> "no Vault Pro access"; then the describe
plan route's own sentences: missing vision key / spent Describe cap (`vault_ai_vision._vision_budget`), then
Jev not ready (`vault_jev_pass.plan`).
ASSUMPTION: "no Vault Pro access" follows the role middleware's own decision for POST describe-all (its
opt-in branch, then `require_permission`, which reads `granted_pages` and also a stored-false action key)
rather than `granted_pages` alone as the spec words it, so the sentence appears exactly when describe-all
would 403 (rung 3, the spec's stated intent). `/growth/vault-pro` is not in `OPT_IN_PAGES` today. Overturned
if the owner wants an action-key denial to leave `can_describe` true.

Template prices: {script_step: highest saved price > 0 at that step} of the same-named Sequence on ONE other
Creator of the same Agency — a Creator of the Agency the caller acts in for this Creator (`agency_context`:
an owner its own Agency, a chatter the house tie-break; never a second owner's Creators), and one the caller
holds. Several have it: the one with the most priced steps, then the lowest account id.
ASSUMPTION: a caller whose Agency does not hold this Creator (the Master; an anonymous caller under
`ALLOW_ANONYMOUS_ADMIN`) borrows from the Creator's first
owner by id (the `_sorted_holder_owner_ids` tie-break), so one Agency still lends (rung 3). Overturned if the
Master should borrow nothing.
ASSUMPTION: one source Creator (not a per-step mix) so the borrowed prices climb as that Creator's do, and
"most priced steps, then lowest account id" picks it (rung 5). Overturned if the owner names another rule.
ASSUMPTION: a step whose Options carry several prices lends the highest (rung 6). Overturned with the above.

Apply (write path): the describe block and the acting Agency are read before the write lock (the describe
block can change a status between `not_enough_content` and `no_fit`, never a write, and is not
fingerprinted). Then one `immediate_session`: the Sequence rows, the other Sequences' media, the template
prices and the vault's live `vault_items` columns are read on the locked session, `full_ai_sell.load_rows`
and `vault_settings.load` on their own (neither takes a session; BEGIN IMMEDIATE bars every other writer, WAL
readers see the last commit), `script_fill_decide.plan_over_vault` re-runs, the fingerprint is compared, and
only empty media-Role Options are written (`media_json` as house VaultMedia `{id, type, files:{thumb:{url}}}`
with previews first, `previews_json`, `price_cents` where Fill set it,
`updated_at`), then `sync_sequences` and commit. `plan` is synchronous over the whole vault, so both routes
run it with `asyncio.to_thread` (the house pattern for blocking work, e.g. `vault_dupes.find_duplicates`):
the event loop stays free while it runs. Only the pure plan moves; every session is opened, used and
committed on the loop's task (the sessions are aiosqlite-backed `AsyncSession`s bound to the loop's engine,
so they cannot be moved into a thread), and the thread touches no session. The Python a vault load leaves
(`_load_vault`'s row merge) stays on the loop, short next to the plan.
ASSUMPTION: `load_rows`' and `vault_settings.load`'s own pool checkouts stay inside the lock (moving them onto
the locked session means changing `full_ai_sell`, `vault_scripts`, `vault_dupes`, `vault_folder_prices` and
`vault_settings`, outside this ticket; reading them before the lock would let a vault change land between the
read and the write). Under pool pressure each can wait up to `db.engine.SPILL_AFTER_S` (2 s); the lock-hold
bar is measured without it. Overturned if a contended lock-hold measure goes over 2,000 ms: then those
loaders take a session.
Plan gate: one plan at a time per process (`_plan_gate`, a Semaphore(1)). The plan route holds it from its
first load to the end of its `to_thread`; apply takes it BEFORE `immediate_session` and holds it until the
transaction ends, so no other plan loads or computes while the write lock is held. Order is always gate, then
write lock; the plan route never takes the write lock, so the two cannot deadlock. Undo computes no plan and
takes no gate. The gate is per running loop (house pattern: `vault_stills._fetch_slot`, `admission`), which is
per process under uvicorn's one loop.
ASSUMPTION: plan requests queue behind one another (and an apply behind queued plans) rather than run side by
side (coordinator ruling). Overturned if plan p95 wait becomes user-visible.
ASSUMPTION: the plan route's gate also covers its loads, not only its `to_thread` as ruled: with the gate
around `to_thread` alone, plans never computed at once yet the hold beside 4 plans measured median 4.7 s / max
6.3 s on 12k items (the other plans' vault loads run Python on the loop between apply's awaits); with the loads
inside, max 1.8 s (test_script_fill_lock_hold.py). Rung 1 against the ruling's means, kept to its end (no plan
work under the write lock). Overturned if the loads move off the loop.
ASSUMPTION: a plan request cancelled mid-compute releases the gate while its thread finishes (the thread holds no
session and writes nothing), so one more plan may compute beside it for that tail (rung 5). Overturned if
cancelled plans show up next to lock holds over the bar.
ASSUMPTION: the describe block is read outside the lock (coordinator ruling: keep the write transaction
short); the spec's Write path lists coverage inside. Overturned if a status must follow a describe that lands
between the read and the lock.

Undo: one `immediate_session`; a reserved FM Sequence name (`is_reserved_name`) keeps every entry as
`reserved` and writes nothing (Fill never touches one, so neither does its undo). Otherwise per entry
`script_fill_decide.undo_check` against the row as it is now (another account's row reads as missing); `ok`
rows get media and previews emptied, price 0 only when `price_set`, `updated_at` bumped; the rest are
reported `{id, reason}`.
ASSUMPTION: undo also answers 404 `sequence_not_found` when the Sequence has no rows left (spec Contracts:
"All three Fill routes"), so a whole-Sequence rename after a Fill is a 404, not a per-row `moved`. Overturned
if the button needs the per-row report there.
"""
from __future__ import annotations

import asyncio
import json
import weakref
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

import permissions
import script_fill_decide as decide
import vault_ai_vision
import vault_jev_pass
import vault_settings
from agency_context import agency_context
from auth import assert_account_owned, require_actor_account_ids
from automations import full_ai_sell as fs
from automations._reserved_scripts import is_reserved_name
from db.engine import get_session
from db.models import SavedReply, UserAccount, VaultItem
from db.of_writer import immediate_session
from saved_replies_api import IDS_MAX, IN_CHUNK, sync_sequences
from vault_ai_api import assert_owner_scope

router = APIRouter(prefix="/admin/saved-replies", tags=["scripts"])

NO_VAULT_PRO = "no Vault Pro access"
_DESCRIBE_ALL = "/admin/vault-ai/describe-all"


class _PlanBody(BaseModel):
    sequence: str


class _ApplyBody(_PlanBody):
    fingerprint: str | None = None


class _UndoEntry(BaseModel):
    id: int
    media_ids: list[int] = Field(default_factory=list)
    previews: list[int] = Field(default_factory=list)
    price_cents: int = 0          # the row's price after apply, always compared
    price_set: bool = False       # Fill wrote that price: undo zeroes it only then


class _UndoBody(_PlanBody):
    undo: list[_UndoEntry] = Field(..., max_length=IDS_MAX)


# ── Gate ──────────────────────────────────────────────────────────────

async def _gate(account_id: str) -> str:
    account_id = (account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)
    return account_id


async def _vault_pro_denied(account_id: str) -> bool:
    """The caller's enforced role would refuse POST describe-all for `account_id`: the role middleware's own
    decision (`permissions.route_refusal`; owners and enforcement off: never). A refusal that is not a 403
    (an Agency context's 503) is raised, not read as no access."""
    pages = permissions.route_pages(_DESCRIBE_ALL, "POST") or ()
    refusal, _ = await permissions.route_refusal(pages, "POST", _DESCRIBE_ALL, [account_id])
    if refusal is not None and refusal.status_code != 403:
        raise refusal
    return refusal is not None


async def _blocked_reason(account_id: str) -> str | None:
    if await _vault_pro_denied(account_id):
        return NO_VAULT_PRO
    budget = await vault_ai_vision._vision_budget(account_id)
    if budget.get("blocked_reason"):
        return str(budget["blocked_reason"])
    jev = await vault_jev_pass.plan(account_id)
    if not jev.get("ready"):
        return str(jev.get("reason") or "Jev is not ready")
    return None


async def _describe_inputs(account_id: str) -> tuple[dict[str, Any], str | None]:
    return (await vault_ai_vision.describe_coverage(account_id, decide.DESCRIBE_TARGET),
            await _blocked_reason(account_id))


# ── Plan gate ─────────────────────────────────────────────────────────

# Per loop: the test harness runs each case (and TestClient each request) on its own loop, and a Semaphore that
# has parked a waiter belongs to that loop. Weak keys, so a finished loop takes its gate with it.
_PLAN_GATES: "weakref.WeakKeyDictionary[Any, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _plan_gate() -> asyncio.Semaphore:
    """One plan computation at a time (module docstring › Plan gate)."""
    loop = asyncio.get_running_loop()
    gate = _PLAN_GATES.get(loop)
    if gate is None:                          # no await between check and set
        gate = _PLAN_GATES[loop] = asyncio.Semaphore(1)
    return gate


# ── Loaders ───────────────────────────────────────────────────────────

def _row_dict(r: SavedReply) -> dict[str, Any]:
    return {"id": r.id, "script_id": r.script_id, "script_step": r.script_step, "text": r.text,
            "notes": r.notes, "price_cents": r.price_cents or 0, "media_json": r.media_json,
            "previews_json": r.previews_json}


async def _sequence(s: Any, account_id: str, sequence: str) -> list[SavedReply]:
    rows = (await s.execute(select(SavedReply).where(SavedReply.account_id == account_id,
                                                      SavedReply.script_id == sequence)
                            .order_by(SavedReply.id))).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "sequence_not_found"})
    return list(rows)


async def _used_ids(s: Any, account_id: str, sequence: str) -> set[int]:
    """Media (and previews) on the Creator's other Sequences."""
    got = (await s.execute(select(SavedReply.media_json, SavedReply.previews_json).where(
        SavedReply.account_id == account_id, SavedReply.script_id.is_not(None),
        SavedReply.script_id != sequence))).all()
    return decide.sequence_media_ids(r._mapping for r in got)


async def _agency(account_id: str) -> str | None:
    """users.id of the Agency the caller acts in for `account_id` (`agency_context`; a chatter's Mirror
    Employee is created on first use, as on every chatter route that resolves one); None for an anonymous
    caller (`ALLOW_ANONYMOUS_ADMIN`, unclamped)."""
    if require_actor_account_ids() is None:
        return None
    return (await agency_context(account_id=account_id)).agency_user_id


async def _template_prices(s: Any, account_id: str, sequence: str, agency: str | None) -> dict[int, int]:
    """{step: cents} from one other Creator of `agency` (module docstring)."""
    owners = sorted((await s.execute(select(UserAccount.user_id).where(
        UserAccount.account_id == account_id))).scalars().all())
    if not owners:
        return {}
    owner = agency if agency in owners else owners[0]
    siblings = set((await s.execute(select(UserAccount.account_id).where(
        UserAccount.user_id == owner, UserAccount.account_id != account_id))).scalars().all())
    held = require_actor_account_ids()
    if held is not None:
        siblings &= set(held)
    if not siblings:
        return {}
    by: dict[str, dict[int, int]] = {}
    for acct, step, cents in (await s.execute(select(
            SavedReply.account_id, SavedReply.script_step, SavedReply.price_cents).where(
            SavedReply.account_id.in_(sorted(siblings)), SavedReply.script_id == sequence,
            SavedReply.script_step.is_not(None), SavedReply.price_cents > 0))).all():
        steps = by.setdefault(str(acct), {})
        steps[int(step)] = max(steps.get(int(step), 0), int(cents))
    if not by:
        return {}
    pick = min(by, key=lambda a: (-len(by[a]), a))
    return by[pick]


class _Vault:
    """The Creator's live vault as Fill reads it."""

    def __init__(self, items: list[dict[str, Any]], groups: list[list[int]], prints: dict[int, Any],
                 live: dict[int, tuple[str, str | None]], standard_folders: bool) -> None:
        self.items, self.groups, self.prints = items, groups, prints
        self.live = live                      # {media_id: (kind, thumb_url)} of every live row
        self.standard_folders = standard_folders


async def _load_vault(account_id: str, s: Any = None) -> _Vault:
    """The vault `plan` reads. The live `vault_items` columns are read on `s` when given (apply: the locked
    session), else on a session of their own opened after `load_rows` (plan: no checkout held while
    `load_rows` takes its own). `load_rows` and `vault_settings.load` open their own sessions (they take none)."""
    got = await fs.load_rows(account_id)
    if isinstance(got, fs.Refusal):
        raise HTTPException(status_code=503, detail={"error": "inventory_unknown"})
    rows, groups, prints = got
    query = (select(VaultItem.media_id, VaultItem.review_state, VaultItem.operator_overrides_json,
                    VaultItem.kind, VaultItem.thumb_url)
             .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)))
    if s is None:
        async with get_session() as own:
            got_live = (await own.execute(query)).all()
    else:
        got_live = (await s.execute(query)).all()
    extra = {int(m): (rs, ov, kind, thumb) for m, rs, ov, kind, thumb in got_live}
    standard = bool((await vault_settings.load(account_id)).get("standard_folders"))
    items = []
    for r in rows:
        if int(r["media_id"]) not in extra:
            continue                          # no live vault_items row read: not in Fill's vault (closed)
        rs, ov, _kind, _thumb = extra[int(r["media_id"])]
        items.append(decide.effective({**r, "account_id": account_id, "review_state": rs,
                                       "operator_overrides_json": ov}))
    live = {m: (kind, thumb) for m, (_rs, _ov, kind, thumb) in extra.items()}
    return _Vault(items, [[int(m) for m in g] for g in groups], prints, live, standard)


def _vault_media(mid: int, vault: _Vault) -> dict[str, Any]:
    kind, thumb = vault.live[mid]             # KeyError inside the write transaction: rollback
    entry: dict[str, Any] = {"id": mid, "type": kind}
    if thumb:
        entry["files"] = {"thumb": {"url": thumb}}
    return entry


# ── Routes ────────────────────────────────────────────────────────────

@router.post("/fill/plan")
async def fill_plan(body: _PlanBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """The read-only Fill plan of one Sequence (spec › Contracts FillPlan). Writes nothing."""
    account_id = await _gate(account_id)
    agency = await _agency(account_id)
    cov, blocked = await _describe_inputs(account_id)   # outside the gate, as apply: no vault-row work in it
    async with _plan_gate():                  # loads too: their row work runs on the loop (module docstring)
        async with get_session() as s:
            rows = [_row_dict(r) for r in await _sequence(s, account_id, body.sequence)]
            used = await _used_ids(s, account_id, body.sequence)
            template = await _template_prices(s, account_id, body.sequence, agency)
        vault = await _load_vault(account_id)
        return await asyncio.to_thread(
            decide.plan_over_vault, rows, vault.items, used, vault.groups, vault.prints, cov, blocked,
            account_id=account_id, standard_folders=vault.standard_folders, live_ids=set(vault.live),
            template_prices=template)


@router.post("/fill/apply")
async def fill_apply(body: _ApplyBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """Re-derive the plan and write it inside one write transaction (module docstring). 409 `stale` with the
    fresh plan when `fingerprint` is given and differs; every non-`ok` status writes nothing."""
    account_id = await _gate(account_id)
    cov, blocked = await _describe_inputs(account_id)
    agency = await _agency(account_id)
    async with _plan_gate(), immediate_session() as s:   # gate first, released after the transaction ends
        recs = await _sequence(s, account_id, body.sequence)
        rows = [_row_dict(r) for r in recs]
        used = await _used_ids(s, account_id, body.sequence)
        template = await _template_prices(s, account_id, body.sequence, agency)
        vault = await _load_vault(account_id, s)
        plan = await asyncio.to_thread(
            decide.plan_over_vault, rows, vault.items, used, vault.groups, vault.prints, cov, blocked,
            account_id=account_id, standard_folders=vault.standard_folders, live_ids=set(vault.live),
            template_prices=template)
        if body.fingerprint and body.fingerprint != plan["fingerprint"]:
            raise HTTPException(status_code=409, detail={"error": "stale", "plan": plan})
        if plan["status"] != "ok":
            return {"status": plan["status"], "plan": plan, "applied": [], "undo": []}
        writes = decide.writes(plan["options"])
        by_id = {r.id: r for r in recs}
        now = datetime.utcnow()
        undo = []
        for w in writes:
            rec = by_id[w["id"]]
            rec.media_json = json.dumps([_vault_media(m, vault) for m in w["media"]])
            rec.previews_json = json.dumps(list(w["previews"]))
            if w["price_cents"] is not None:
                rec.price_cents = int(w["price_cents"])
            rec.updated_at = now
            undo.append({"id": w["id"], "media_ids": list(w["media"]), "previews": list(w["previews"]),
                         "price_cents": int(rec.price_cents or 0), "price_set": w["price_cents"] is not None})
        await sync_sequences(s, account_id, {body.sequence})
    written = {w["id"] for w in writes}
    return {"status": "ok", "plan": plan, "applied": [o for o in plan["options"] if o["id"] in written],
            "undo": undo}


@router.post("/fill/undo")
async def fill_undo(body: _UndoBody = Body(...), account_id: str = Query("")) -> dict[str, Any]:
    """Empty each row that still holds exactly its Undo entry's media, previews and price in this Sequence;
    report the rest per row (`edited`, `moved`, `missing`)."""
    account_id = await _gate(account_id)
    undone: list[int] = []
    kept: list[dict[str, Any]] = []
    async with immediate_session() as s:
        await _sequence(s, account_id, body.sequence)
        if is_reserved_name(body.sequence):   # FM Sequence: every entry kept, nothing written (module docstring)
            return {"undone": [], "kept": [{"id": e.id, "reason": "reserved"} for e in body.undo]}
        ids = sorted({e.id for e in body.undo})
        rows: dict[int, SavedReply] = {}
        for at in range(0, len(ids), IN_CHUNK):
            rows.update({r.id: r for r in (await s.execute(select(SavedReply).where(
                SavedReply.account_id == account_id, SavedReply.id.in_(ids[at:at + IN_CHUNK])))).scalars()})
        now = datetime.utcnow()
        for e in body.undo:
            rec = rows.get(e.id)
            verdict = decide.undo_check(_row_dict(rec) if rec is not None else None, e.model_dump(),
                                        body.sequence)
            if verdict != "ok":
                kept.append({"id": e.id, "reason": verdict})
                continue
            rec.media_json = "[]"
            rec.previews_json = "[]"
            if e.price_set:
                rec.price_cents = 0
            rec.updated_at = now
            undone.append(e.id)
        if undone:
            await sync_sequences(s, account_id, {body.sequence})
    return {"undone": undone, "kept": kept}
