"""service/unconfirmed_sends_api.py — the Creator's funnel / follow-up steps that
may not have sent (send_marker_decide), and the user's Retry.

At-most-once: a step killed mid-send is never auto-resent (PPV above all); it is
listed here and only the user retries it.

  GET  /admin/unconfirmed-sends?account_id=        pure read: the marked rows
       → {"rows": [{kind, fan_id, mass_run_id, step, step_label, since,
                    last_error, state: UNCONFIRMED | IN_FLIGHT}]}
  POST /admin/unconfirmed-sends/retry?account_id=  {kind, fan_id, mass_run_id?}
       no such row for this Creator → 404; else that sender's settle runs first,
       then: not marked (it landed) → {"status": "already_sent"}; IN_FLIGHT → 409;
       else the marker is cleared (funnel: pending, due now) → {"status": "retried"}
       and the next tick sends it once (normal lease / cooldown). A row that
       changed under the clear is re-read: unmarked → already_sent, else 409.

Guards: the account's owner (`assert_account_owned`) and the Auto Funnel page
(`require_opt_in_page`; follow-ups have no page of their own). The rows, the
settle and the clear are each sender's (`marked_sends`, `read_marker`,
`settle_landed`, `retry_clear`): house-funnel rows only, never a row without a funnel.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from auth import assert_account_owned
from automations import reply_mass_funnel as rmf
from automations import send_followup as sf
from automations import send_marker_decide as smd
from isotime import iso_z
from permissions import require_opt_in_page

_AUTO_FUNNEL = "/growth/auto-funnel"
_SENDERS = {"funnel": rmf, "followup": sf}

router = APIRouter()


async def _guard(account_id: str) -> None:
    assert_account_owned(account_id)
    await require_opt_in_page(_AUTO_FUNNEL, account_id)


def _row_state(marker, now: datetime) -> str:
    """NONE for no row too."""
    if marker is None:
        return smd.NONE
    return smd.marker_state(marker.sending_at, marker.unconfirmed_at, smd.BOOT_TS, now)


@router.get("/admin/unconfirmed-sends")
async def list_unconfirmed_sends(account_id: str = Query(...)) -> dict[str, Any]:
    await _guard(account_id)
    now = datetime.utcnow()
    return {"rows": [
        {"kind": kind, "fan_id": str(m["fan_id"]), "mass_run_id": m["mass_run_id"],
         "step": m["step"], "step_label": f"STEP {m['step']}", "since": iso_z(m["sending_at"]),
         "last_error": m["last_error"],
         "state": smd.marker_state(m["sending_at"], m["unconfirmed_at"], smd.BOOT_TS, now)}
        for kind, sender in _SENDERS.items() for m in await sender.marked_sends(account_id)
    ]}


class RetryBody(BaseModel):
    kind: Literal["funnel", "followup"]
    fan_id: int
    mass_run_id: int | None = None


@router.post("/admin/unconfirmed-sends/retry")
async def retry_unconfirmed_send(account_id: str = Query(...),
                                 body: RetryBody = Body(...)) -> dict[str, Any]:
    await _guard(account_id)
    if body.kind == "funnel" and body.mass_run_id is None:
        raise HTTPException(422, "mass_run_id is required for a funnel row")
    sender, key = _SENDERS[body.kind], (account_id, body.fan_id, body.mass_run_id)
    if await sender.read_marker(*key) is None:
        raise HTTPException(404, "no such row for this Creator")
    now = datetime.utcnow()
    # The tick's own settle first: a step that landed is saved as sent, not re-sent.
    await sender.settle_landed(account_id, smd.BOOT_TS, now)
    marker = await sender.read_marker(*key)
    state = _row_state(marker, now)
    if state == smd.UNCONFIRMED and await sender.retry_clear(*key, marker.sending_at, now):
        return {"status": "retried"}
    if state == smd.UNCONFIRMED:   # changed under the clear (a settle, a Retry, an attempt)
        state = _row_state(await sender.read_marker(*key), now)
    if state == smd.NONE:
        return {"status": "already_sent"}
    raise HTTPException(409, "still sending")
