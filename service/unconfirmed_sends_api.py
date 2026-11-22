"""service/unconfirmed_sends_api.py — the Creator's funnel / follow-up steps that
may not have sent (send_marker_decide), and the user's Retry.

At-most-once: a step killed mid-send is never auto-resent (PPV above all); it is
listed here and only the user retries it.

  GET  /admin/unconfirmed-sends?account_id=        pure read: the marked rows
       → {"rows": [{kind, fan_id, mass_run_id, step, step_label, since,
                    last_error, state: UNCONFIRMED | IN_FLIGHT, hint}]}
       hint: {message_id, at, text} of the first untagged outbound message to that
       fan since the mark (local DB only; a hint for the user, never proof), else null.
  POST /admin/unconfirmed-sends/retry?account_id=  {kind, fan_id, mass_run_id?, since}
       the user's Retry on the row listed at `since`: no such row for this
       Creator → 404; else that sender's settle runs first, then: not marked (it
       landed) → {"status": "already_sent"}; IN_FLIGHT → 409; marked by another
       attempt (a stale tab after an earlier Retry) → 409, nothing cleared; else
       the marker is cleared (funnel: pending, due now) → {"status": "retried"}
       and the next tick sends it once (normal lease / cooldown). A row that
       changed under the clear is re-read: unmarked → already_sent, else 409.
  POST /admin/unconfirmed-sends/dismiss?account_id= {kind, fan_id, mass_run_id?,
                                                      hint_message_id?, since}
       the user's "It went through" on the row listed at `since`: no such row → 404;
       not marked → already_sent when that attempt was saved as sent, else 409 (a
       Retry cleared it for a resend); marked by another attempt → 409;
       IN_FLIGHT → 409; else the step is saved as sent exactly as a confirmed
       landing (the settle's replay, no landed check) → {"status": "dismissed"}
       and is never re-sent; the hint row the user saw (`hint_message_id`, still
       untagged) gets the step's tags, as a confirmed send's row has them, so the
       funnel's next step waits for a reply after it. A row the replay can't save (a shortened funnel, a bad
       ctx) or that changed under it is re-read: unmarked → as above, else 409.

Guards: the account's owner (`assert_account_owned`) and the Auto Funnel page
(`require_opt_in_page`; follow-ups have no page of their own). The rows, the
settle and the clear are each sender's (`marked_sends`, `read_marker`,
`settle_landed`, `retry_clear`, `dismiss_sent`): house-funnel rows only, never a row without a funnel.
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
from automations import send_marker_store as smst
from isotime import iso_z, parse_iso
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


async def _hint(account_id: str, m: dict) -> dict | None:
    if m["sending_at"] is None:
        return None
    hit = await smst.untagged_out(account_id, m["fan_id"], smd.lookup_since(m["sending_at"]))
    return None if hit is None else {"message_id": str(hit[0]), "at": iso_z(hit[1]),
                                     "text": (hit[2] or "")[:60]}


@router.get("/admin/unconfirmed-sends")
async def list_unconfirmed_sends(account_id: str = Query(...)) -> dict[str, Any]:
    await _guard(account_id)
    now = datetime.utcnow()
    return {"rows": [
        {"kind": kind, "fan_id": str(m["fan_id"]), "mass_run_id": m["mass_run_id"],
         "step": m["step"], "step_label": f"STEP {m['step']}", "since": iso_z(m["sending_at"]),
         "last_error": m["last_error"],
         "state": smd.marker_state(m["sending_at"], m["unconfirmed_at"], smd.BOOT_TS, now),
         "hint": await _hint(account_id, m)}
        for kind, sender in _SENDERS.items() for m in await sender.marked_sends(account_id)
    ]}


class RetryBody(BaseModel):
    kind: Literal["funnel", "followup"]
    fan_id: int
    mass_run_id: int | None = None
    since: str   # the listed row's `since`: a newer attempt on the row is not this one


class DismissBody(RetryBody):
    hint_message_id: int | None = None


def _since(body: RetryBody) -> datetime:
    since = parse_iso(body.since)
    if since is None:
        raise HTTPException(422, "since must be an ISO time")
    return since


async def _row_of(account_id: str, body: RetryBody):
    """Guarded: (sender, key) of this Creator's row; 422 / 404 otherwise."""
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
    since = _since(body)
    sender, key = await _row_of(account_id, body)
    now = datetime.utcnow()
    # The tick's own settle first: a step that landed is saved as sent, not re-sent.
    await sender.settle_landed(account_id, smd.BOOT_TS, now)
    marker = await sender.read_marker(*key)
    state = _row_state(marker, now)
    if state == smd.UNCONFIRMED and since != marker.sending_at:
        raise HTTPException(409, "this row changed since it was listed: refresh")
    if state == smd.UNCONFIRMED and await sender.retry_clear(*key, marker.sending_at, now):
        return {"status": "retried"}
    if state == smd.UNCONFIRMED:   # changed under the clear (a settle, a Retry, an attempt)
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
    if state == smd.UNCONFIRMED:   # changed under it, or a step it can't save as sent
        state = _row_state(await sender.read_marker(*key), now)
        if state == smd.UNCONFIRMED:
            raise HTTPException(409, "this step can't be saved as sent (its funnel changed): use Retry")
    # Unmarked: saved as sent (a settle, an earlier dismiss) only if THAT attempt
    # was; else a Retry cleared it for a resend, or a live finish saved it after
    # it was listed: either way the row changed.
    if state == smd.NONE and await sender.attempt_saved(*key, since):
        return {"status": "already_sent"}
    if state == smd.NONE:
        raise HTTPException(409, "this row changed since it was listed: refresh")
    raise HTTPException(409, "still sending")
