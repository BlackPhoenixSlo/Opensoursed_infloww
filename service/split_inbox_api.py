from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import split_inbox
from auth import assert_account_owned
from chatters import assert_owner
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger("of-relay.split_inbox_api")

router = APIRouter()


def _validate_config(cfg: dict) -> dict:
    try:
        return split_inbox.clean(cfg)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/admin/split-inbox")
async def get_split_inbox(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    generation = split_inbox.generation(account_id)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
    config = split_inbox.heal(
        account_id, split_inbox.parse(row.split_inbox_json if row is not None else None), since=generation,
    )
    chatter_id = split_inbox.acting_chatter_id()
    if chatter_id is None:
        return {"account_id": account_id, "config": config, "my_group": None}
    return {"account_id": account_id,
            "config": {k: v for k, v in config.items() if k != "chatter_groups"},
            "my_group": split_inbox.bound_group(config, chatter_id)}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/split-inbox")
async def put_split_inbox(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_owner()
    assert_account_owned(body.account_id)
    clean = _validate_config(body.config)
    async with split_inbox.save_lock(body.account_id):
        now = datetime.utcnow()
        payload = json.dumps(clean)
        async with get_session() as s:
            await s.execute(
                sqlite_insert(AccountAiConfig)
                .values(account_id=body.account_id, utc_offset=0,
                        split_inbox_json=payload, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id"],
                    set_={"split_inbox_json": payload, "updated_at": now})
            )
        split_inbox.remember(body.account_id, clean)
    log.info("split_inbox_saved account=%s groups=%d moves=%d bound=%d",
             body.account_id, clean["group_count"], len(clean["assignments"]), len(clean["chatter_groups"]))
    return {"account_id": body.account_id, "config": clean}
