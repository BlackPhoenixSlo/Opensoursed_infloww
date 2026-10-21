"""service/priority_mass_api.py — Smart Messages' Priority mass message runs.

The routes behind the "Priority mass message" card and the "Priority mass
messages" list (automations/priority_mass sends them):

  POST /admin/priority-mass/runs
       {account_id, text, media_files, previews, price, locked_text,
        user_lists, excluded_user_lists}                   → the run
       Validates, refuses a listed Sensitive word (the Agency's list, the
       composers' matcher) or a blocking banned word, makes the run `resolving`
       and queues its first leg, which freezes the audience. The same message
       to the same Creator launched again inside `_REPEAT_S` is refused 409 (a
       double click). `user_lists` holds "fans", "following" or OF list ids;
       `excluded_user_lists` OF list ids.
  GET  /admin/priority-mass/runs?account_id=               → {runs: [...]}
       Newest first, each with its recipients counted per status and `stalled`
       (live, but no leg queued or running: the chain died; Resume restarts it).
  POST /admin/priority-mass/runs/{id}/cancel               → the run
       Live runs only: the run turns `cancelled` and its pending fans `skipped`.
       A send already in flight may still land.
  POST /admin/priority-mass/runs/{id}/resume               → the run
       Queues the next leg of a stalled run.

Every route checks the Creator is the caller's (`assert_account_owned`).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select, update

import automation_executor as ax
from auth import assert_account_owned
from automations import priority_mass as pm
from automations._wordfilter import banned_hit_summary, filter_banned, load_banned_words
from db.engine import get_session
from db.models import PriorityMassRecipient, PriorityMassRun, ScheduledJob, SensitiveWord
from employees import agency_contexts, json_object, resolve_outbound_employee_id

log = logging.getLogger("of-relay.priority_mass_api")

router = APIRouter(prefix="/admin/priority-mass")

_TEXT_MAX = 2000
_MEDIA_MAX = 20
_PRICE_MIN, _PRICE_MAX = 3, 200     # OF's priced-message floor and $200 PPV ceiling
_REPEAT_S = 120
_LIST_LIMIT = 50
# The composers' "Please check the contents of the messages" (app/lib/sensitiveWords.ts).
SENSITIVE_BLOCK_MESSAGE = "Please check the contents of the messages"


def sensitive_hits(text: str, words: list[str]) -> list[str]:
    """The listed words in `text`, as app/lib/sensitiveWords.ts matches them:
    case-insensitive, only between boundaries (no letter or digit beside it, so
    "ass" never trips on "class"), a phrase across any run of whitespace."""
    hits: list[str] = []
    for w in words:
        parts = [re.escape(p) for p in str(w).split()]
        if parts and re.search(r"(?<![^\W_])" + r"\s+".join(parts) + r"(?![^\W_])",
                               text, re.IGNORECASE):
            hits.append(w)
    return hits


async def _sensitive_words(account_id: str) -> list[str]:
    agencies = [c.agency_user_id for c in await agency_contexts(account_id=account_id)]
    async with get_session() as s:
        return list((await s.execute(select(SensitiveWord.word).where(
            SensitiveWord.agency_user_id.in_(agencies)))).scalars())


def _id_list(v: Any, field: str) -> list[int]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise HTTPException(422, f"{field} must be a list")
    out: list[int] = []
    for x in v:
        if isinstance(x, bool) or not (isinstance(x, int) or (isinstance(x, str) and x.isdigit())):
            raise HTTPException(422, f"{field} holds ids only")
        if int(x) <= 0:
            raise HTTPException(422, f"{field} holds ids only")
        out.append(int(x))
    return list(dict.fromkeys(out))


def _validate(body: dict) -> dict:
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise HTTPException(422, "account_id is required")
    text = body.get("text", "")
    if not isinstance(text, str):
        raise HTTPException(422, "text must be a string")
    text = text.strip()
    if len(text) > _TEXT_MAX:
        raise HTTPException(422, f"text is at most {_TEXT_MAX} characters")
    media = _id_list(body.get("media_files"), "media_files")
    if len(media) > _MEDIA_MAX:
        raise HTTPException(422, f"at most {_MEDIA_MAX} media")
    previews = _id_list(body.get("previews"), "previews")
    if not set(previews) <= set(media):
        raise HTTPException(422, "previews must be attached media")
    if not text and not media:
        raise HTTPException(422, "add a text or media")
    price = body.get("price", 0) or 0
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise HTTPException(422, "price must be a number")
    if price and not _PRICE_MIN <= price <= _PRICE_MAX:
        raise HTTPException(422, f"price is 0 or ${_PRICE_MIN} to ${_PRICE_MAX}")
    if price and not media:
        raise HTTPException(422, "a priced message needs media")
    user_lists = body.get("user_lists")
    if not isinstance(user_lists, list) or not user_lists:
        raise HTTPException(422, "pick at least one list to include")
    lists: list[str] = []
    for x in user_lists:
        name = str(x).strip().lower() if isinstance(x, (str, int)) and not isinstance(x, bool) else ""
        if name not in ("fans", "following") and not name.isdigit():
            raise HTTPException(422, 'user_lists holds "fans", "following" or list ids')
        lists.append(name)
    excluded = _id_list(body.get("excluded_user_lists"), "excluded_user_lists")
    locked = body.get("locked_text", False)
    if not isinstance(locked, bool):
        raise HTTPException(422, "locked_text must be true or false")
    return {"account_id": account_id, "text": text, "media": media, "previews": previews,
            "price_cents": int(round(float(price) * 100)), "locked_text": bool(locked and price),
            "audience": {"user_lists": list(dict.fromkeys(lists)),
                         "excluded_user_lists": excluded}}


async def _stalled(runs: list[PriorityMassRun]) -> set[int]:
    live = [r for r in runs if r.status in pm.LIVE]
    if not live:
        return set()
    async with get_session() as s:
        queued = set((await s.execute(select(ScheduledJob.payload_json).where(
            ScheduledJob.kind == pm.KIND,
            ScheduledJob.account_id.in_({r.account_id for r in live}),
            ScheduledJob.status.in_(["pending", "running"])))).scalars())
    return {r.id for r in live if pm.leg_payload(r.id) not in queued}


async def _public(runs: list[PriorityMassRun]) -> list[dict[str, Any]]:
    counts = await pm.counts([r.id for r in runs])
    stalled = await _stalled(runs)
    out = []
    for r in runs:
        c = counts.get(r.id, {})
        out.append({
            "id": r.id, "account_id": r.account_id, "status": r.status,
            "text": r.text, "media_count": len(pm._ids(r.media_json)),
            "price": r.price_cents / 100, "created_at": r.created_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "last_error": r.last_error, "resolved": r.resolved_count,
            "excluded": r.excluded_count, "capped": r.capped_count,
            "total": sum(c.values()), "counts": c, "stalled": r.id in stalled,
        })
    return out


async def _get_run(run_id: int) -> PriorityMassRun:
    async with get_session() as s:
        row = await s.get(PriorityMassRun, int(run_id))
        if row is not None:
            s.expunge(row)
    if row is None:
        raise HTTPException(404, "no such run")
    assert_account_owned(row.account_id)
    return row


@router.post("/runs")
async def create_run(request: Request) -> dict[str, Any]:
    body = await json_object(request, 422)
    v = _validate(body)
    aid = v["account_id"]
    assert_account_owned(aid)
    if v["text"]:
        if sensitive_hits(v["text"], await _sensitive_words(aid)):
            raise HTTPException(422, SENSITIVE_BLOCK_MESSAGE)
        words, mode = await load_banned_words(aid)
        scanned, hits = filter_banned([v["text"]], words, mode)
        if scanned is None:
            raise HTTPException(422, f"banned word: {', '.join(banned_hit_summary(hits))}")
    employee_id = await resolve_outbound_employee_id(request, aid)
    media_json = json.dumps(v["media"])
    async with get_session() as s:
        repeat = (await s.execute(select(PriorityMassRun.id).where(
            PriorityMassRun.account_id == aid, PriorityMassRun.text == v["text"],
            PriorityMassRun.media_json == media_json,
            PriorityMassRun.status.in_(pm.LIVE),
            PriorityMassRun.created_at >= datetime.utcnow() - timedelta(seconds=_REPEAT_S),
        ).limit(1))).first()
        if repeat is not None:
            raise HTTPException(409, "this message is already being sent")
        row = PriorityMassRun(
            account_id=aid, created_by_employee_id=employee_id, status=pm.RESOLVING,
            text=v["text"], media_json=media_json, previews_json=json.dumps(v["previews"]),
            price_cents=v["price_cents"], locked_text=v["locked_text"],
            audience_json=json.dumps(v["audience"]), created_at=datetime.utcnow())
        s.add(row)
        await s.flush()
        run_id = int(row.id)
        # The first leg commits with the run: no run is ever left without one.
        await ax.enqueue_job(aid, pm.KIND, payload={"run_id": run_id}, session=s)
    log.info("priority_mass_created run=%s account=%s lists=%s price_cents=%s media=%d",
             run_id, aid, v["audience"]["user_lists"], v["price_cents"], len(v["media"]))
    return (await _public([await _get_run(run_id)]))[0]


@router.get("/runs")
async def list_runs(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        runs = list((await s.execute(select(PriorityMassRun).where(
            PriorityMassRun.account_id == account_id)
            .order_by(PriorityMassRun.created_at.desc(), PriorityMassRun.id.desc())
            .limit(_LIST_LIMIT))).scalars())
        s.expunge_all()
    return {"runs": await _public(runs), "max_recipients": pm.MAX_RECIPIENTS,
            "hourly_rate": pm.HOURLY_RATE}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int) -> dict[str, Any]:
    row = await _get_run(run_id)
    if not await pm._set_status(row.id, pm.CANCELLED):
        raise HTTPException(409, f"the run is {row.status}")
    async with get_session() as s:
        await s.execute(update(PriorityMassRecipient).where(
            PriorityMassRecipient.run_id == row.id,
            PriorityMassRecipient.status == pm.PENDING,
        ).values(status=pm.SKIPPED, reason="cancelled", updated_at=datetime.utcnow()))
    log.info("priority_mass_cancelled run=%s account=%s", row.id, row.account_id)
    return (await _public([await _get_run(run_id)]))[0]


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: int) -> dict[str, Any]:
    row = await _get_run(run_id)
    if row.status not in pm.LIVE:
        raise HTTPException(409, f"the run is {row.status}")
    await pm.ensure_leg(row.account_id, row.id, include_running=True)
    return (await _public([row]))[0]
