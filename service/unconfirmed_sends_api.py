from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from auth import assert_account_owned
from automations import reply_mass_funnel as rmf
from automations import send_followup as sf
from automations import send_marker_decide as smd
from automations import send_marker_store as smst
from isotime import iso_z, parse_iso
from permissions import require_opt_in_page

_AUTO_FUNNEL = "/growth/auto-funnel"
_SENDERS = {"funnel": rmf, "followup": sf}

router = APIRouter()
cell_router = APIRouter()


async def _guard(account_id: str) -> None:
    assert_account_owned(account_id)
    await require_opt_in_page(_AUTO_FUNNEL, account_id)


def _row_state(marker, now: datetime) -> str:
    if marker is None:
        return smd.NONE
    return smd.marker_state(marker.sending_at, marker.unconfirmed_at, smd.BOOT_TS, now)


def _cells() -> bool:
    return bool(os.environ.get("OI_CELL_MAP"))


def _retry_allowed() -> bool:
    return not _cells()


def _op_rows(account_id: str) -> list[dict[str, Any]]:
    import send_ops
    return [{"kind": r["kind"], "op_id": r["op_id"], "fan_id": r["target"],
             "since": iso_z(parse_iso(r["created_at"])), "state": smd.UNCONFIRMED, "retry_allowed": False,
             "link": "queue" if r["kind"] in send_ops.QUEUE else "chat"}
            for r in send_ops.uncertain(account_id)]


async def _hint(account_id: str, m: dict) -> dict | None:
    if m["sending_at"] is None:
        return None
    hit = await smst.untagged_out(account_id, m["fan_id"], smd.lookup_since(m["sending_at"]))
    return None if hit is None else {"message_id": str(hit[0]), "at": iso_z(hit[1]),
                                     "text": (hit[2] or "")[:60]}


async def _marked_rows(account_id: str) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    return [
        {"kind": kind, "fan_id": str(m["fan_id"]), "mass_run_id": m["mass_run_id"],
         "step": m["step"], "step_label": f"STEP {m['step']}", "since": iso_z(m["sending_at"]),
         "last_error": m["last_error"],
         "state": smd.marker_state(m["sending_at"], m["unconfirmed_at"], smd.BOOT_TS, now),
         "hint": await _hint(account_id, m)}
        for kind, sender in _SENDERS.items() for m in await sender.marked_sends(account_id)
    ]


@router.get("/admin/unconfirmed-sends")
async def list_unconfirmed_sends(account_id: str = Query(...)) -> dict[str, Any]:
    await _guard(account_id)
    rows = await _marked_rows(account_id)
    if not _cells():
        return {"rows": rows}
    return {"rows": [*({**r, "retry_allowed": _retry_allowed()} for r in rows), *_op_rows(account_id)]}


class RetryBody(BaseModel):
    kind: Literal["funnel", "followup"]
    fan_id: int
    mass_run_id: int | None = None
    since: str


class DismissBody(RetryBody):
    hint_message_id: int | None = None


def _since(body: RetryBody) -> datetime:
    since = parse_iso(body.since)
    if since is None:
        raise HTTPException(422, "since must be an ISO time")
    return since


async def _row_of(account_id: str, body: RetryBody):
    await _guard(account_id)
    if body.kind == "funnel" and body.mass_run_id is None:
        raise HTTPException(422, "mass_run_id is required for a funnel row")
    sender, key = _SENDERS[body.kind], (account_id, body.fan_id, body.mass_run_id)
    if await sender.read_marker(*key) is None:
        raise HTTPException(404, "no such row for this Creator")
    return sender, key


@router.post("/admin/unconfirmed-sends/retry")
async def retry_unconfirmed_send(account_id: str = Query(...),
                                 body: RetryBody = Body(...)) -> dict[str, Any]:
    if not _retry_allowed():
        await _guard(account_id)
        raise HTTPException(409, {"error": "retry_off_cell_mode"})
    since = _since(body)
    sender, key = await _row_of(account_id, body)
    now = datetime.utcnow()
    # At-most-once: a step killed mid-send is never auto-resent (PPV above all); the tick's settle runs first so a step that landed is saved as sent, not re-sent.
    await sender.settle_landed(account_id, smd.BOOT_TS, now)
    marker = await sender.read_marker(*key)
    state = _row_state(marker, now)
    if state == smd.UNCONFIRMED and since != marker.sending_at:
        raise HTTPException(409, "this row changed since it was listed: refresh")
    if state == smd.UNCONFIRMED and await sender.retry_clear(*key, marker.sending_at, now):
        return {"status": "retried"}
    if state == smd.UNCONFIRMED:
        state = _row_state(await sender.read_marker(*key), now)
    if state == smd.NONE:
        return {"status": "already_sent"}
    raise HTTPException(409, "still sending")


@router.post("/admin/unconfirmed-sends/dismiss")
async def dismiss_unconfirmed_send(account_id: str = Query(...),
                                   body: DismissBody = Body(...)) -> dict[str, Any]:
    since = _since(body)
    sender, key = await _row_of(account_id, body)
    now = datetime.utcnow()
    marker = await sender.read_marker(*key)
    state = _row_state(marker, now)
    if state == smd.UNCONFIRMED and since != marker.sending_at:
        raise HTTPException(409, "this row changed since it was listed: refresh")
    if state == smd.UNCONFIRMED and await sender.dismiss_sent(
            *key, marker.sending_at, now, body.hint_message_id):
        return {"status": "dismissed"}
    if state == smd.UNCONFIRMED:
        state = _row_state(await sender.read_marker(*key), now)
        if state == smd.UNCONFIRMED:
            raise HTTPException(409, "this step can't be saved as sent (its funnel changed): use Retry")
    if state == smd.NONE and await sender.attempt_saved(*key, since):
        return {"status": "already_sent"}
    if state == smd.NONE:
        raise HTTPException(409, "this row changed since it was listed: refresh")
    raise HTTPException(409, "still sending")


class ResolveBody(BaseModel):
    op_id: str
    outcome: Literal["was_sent", "not_sent"]


@cell_router.post("/admin/unconfirmed-sends/resolve")
async def resolve_unconfirmed_send(account_id: str = Query(...),
                                   body: ResolveBody = Body(...)) -> dict[str, Any]:
    await _guard(account_id)
    import send_ops
    from chatters import current_actor
    actor = current_actor()
    by = "unknown" if actor is None else f"{actor.kind}:{actor.username}"
    if not send_ops.resolve(account_id, body.op_id, body.outcome == "was_sent", by):
        raise HTTPException(404, "no such row for this Creator")
    return {"status": body.outcome}
