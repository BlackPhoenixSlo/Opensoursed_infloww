from __future__ import annotations

import json

from sqlalchemy import select

from db.engine import get_session
from db.models import Fan
from jsonsafe import load_dict


def fan_state(fan: Fan | None, key: str) -> dict:
    value = _fan_state_all(fan).get(key)
    return value if isinstance(value, dict) else {}


def _fan_state_all(fan: Fan | None) -> dict:
    return load_dict(fan.custom_fields) if fan else {}


# No commit: callers stamp cooldowns in the same transaction as the VaultSend rows so the two cannot diverge.
def put_fan_state(fan: Fan, key: str, value: dict | None) -> None:
    cf = _fan_state_all(fan)
    if value is None:
        cf.pop(key, None)
    else:
        cf[key] = value
    fan.custom_fields = json.dumps(cf)


# Re-reads the blob in-session so a sibling automation's key written since the caller loaded the Fan survives.
async def set_fan_state(account_id: str, fan_id: int, key: str,
                        value: dict | None) -> None:
    async with get_session() as s:
        fan = (await s.execute(select(Fan).where(
            Fan.account_id == str(account_id),
            Fan.fan_id == int(fan_id)))).scalar_one_or_none()
        if fan is None:
            return
        put_fan_state(fan, key, value)
        await s.commit()
