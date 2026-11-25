from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

import runtime_switches
from auth import assert_account_owned
from chatters import assert_owner

OFM_NEW_WRITES = "OFM_NEW_WRITES_ENABLED"

router = APIRouter()


def _view(account_id: str) -> dict[str, Any]:
    o = runtime_switches.creator_override(OFM_NEW_WRITES, account_id)
    return {"account_id": account_id, "server_on": runtime_switches.on(OFM_NEW_WRITES),
            "forced_off": o is not None, "on": runtime_switches.on(OFM_NEW_WRITES, account_id),
            # runtime_switches keeps the row's naive-UTC isoformat: send it with its Z, as iso_z does.
            "changed_by": o and o["updated_by"], "changed_at": o and o["updated_at"] and o["updated_at"] + "Z"}


@router.get("/admin/ofm-writes/{account_id}")
def get_ofm_writes_creator(account_id: str):
    """One Creator's OF Manager new writes: `server_on` (env on, not forced off box-wide), `forced_off` (this
    Creator's force-off, who and when) and `on` (both: what its probe answers)."""
    assert_account_owned(account_id)
    return _view(account_id)


@router.put("/admin/ofm-writes/{account_id}")
async def put_ofm_writes_creator(account_id: str, body: dict = Body(...)):
    """`{"forced_off": bool}`: force OFM_NEW_WRITES_ENABLED off for this Creator, or clear that (back to the box-wide
    value; never on where the env has it off). A signed-in User who holds this Creator: its Agency owner (a User
    holds only its own Agency's Creators) or the Master (holds every Creator, as on PUT /admin/of-consent). Every other
    principal is refused: a chatter / employee session 403 here, another Agency's owner 403 (assert_account_owned),
    the Master's "view as" 403 (auth.session_middleware: impersonation is read-only), an owner access token 403 (not
    on token_auth's allowlist), signed out 401."""
    assert_account_owned(account_id)
    user = assert_owner()
    want = body.get("forced_off") if isinstance(body, dict) else None
    if not isinstance(want, bool):
        raise HTTPException(status_code=422, detail="forced_off must be true or false")
    await runtime_switches.set_override(OFM_NEW_WRITES, False if want else None, by=user.username,
                                        account_id=account_id)
    return _view(account_id)
