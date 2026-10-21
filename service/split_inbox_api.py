"""service/split_inbox_api.py — read/write account_ai_config.split_inbox_json.

Split Inbox divides one Creator's Fans into 1 to 9 groups (ADR-0004). The split
is stored per Creator on the relay so every Employee on every device reads the
same groups. Groups bind to no Employee and grant no permissions, so the store
holds only the count and the explicit moves; every other Fan's group is
computed in the app.

  GET /admin/split-inbox?account_id=   → {account_id, config}
       An unset Creator reads {group_count: 1, assignments: {}}. Open to
       chatters, who filter by group.
  PUT /admin/split-inbox               → upsert, returns {account_id, config}
       Owner-only: a chatter session gets 403, an anonymous one 401. Concurrent
       saves are last-write-wins.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from auth import assert_account_owned
from chatters import assert_owner
from db.engine import get_session
from db.models import AccountAiConfig

log = logging.getLogger("of-relay.split_inbox_api")

router = APIRouter()

MAX_GROUPS = 9


def _unset() -> dict[str, Any]:
    return {"group_count": 1, "assignments": {}}


def _is_int(v: Any) -> bool:
    # bool is an int subclass in Python; JSON true is not a group.
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_config(cfg: dict) -> dict:
    """422 on a bad count or non-object assignments. Keys are coerced to
    strings, entries outside 1..group_count are dropped, and unknown keys are
    dropped, so the store can hold no Employee binding (story 54)."""
    n = cfg.get("group_count")
    if not _is_int(n) or not 1 <= n <= MAX_GROUPS:
        raise HTTPException(422, f"group_count must be an integer from 1 to {MAX_GROUPS}")
    raw = cfg.get("assignments")
    if not isinstance(raw, dict):
        raise HTTPException(422, "assignments must be an object")
    assignments = {str(fan): g for fan, g in raw.items() if _is_int(g) and 1 <= g <= n}
    return {"group_count": n, "assignments": assignments}


@router.get("/admin/split-inbox")
async def get_split_inbox(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
    config = _unset()
    if row is not None and row.split_inbox_json:
        try:
            config = _validate_config(json.loads(row.split_inbox_json))
        except Exception:
            config = _unset()
    return {"account_id": account_id, "config": config}


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


@router.put("/admin/split-inbox")
async def put_split_inbox(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_owner()
    assert_account_owned(body.account_id)
    clean = _validate_config(body.config)
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
    log.info("split_inbox_saved account=%s groups=%d moves=%d",
             body.account_id, clean["group_count"], len(clean["assignments"]))
    return {"account_id": body.account_id, "config": clean}
