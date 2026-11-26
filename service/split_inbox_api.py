from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt, StrictStr, StringConstraints
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import split_inbox
from auth import assert_account_owned
from chatters import assert_owner
from db.engine import get_session
from db.models import AccountAiConfig
from settings_api import read_blob, write_blob

log = logging.getLogger("of-relay.split_inbox_api")

router = APIRouter()


def _validate_config(cfg: dict) -> dict:
    try:
        return split_inbox.clean(cfg)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


async def _upsert(s, account_id: str, cfg: dict) -> None:
    now = datetime.utcnow()
    payload = json.dumps(cfg)
    await s.execute(
        sqlite_insert(AccountAiConfig)
        .values(account_id=account_id, utc_offset=0, split_inbox_json=payload, updated_at=now)
        .on_conflict_do_update(
            index_elements=["account_id"],
            set_={"split_inbox_json": payload, "updated_at": now})
    )


@router.get("/admin/split-inbox")
async def get_split_inbox(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    generation = split_inbox.generation(account_id)
    async with get_session() as s:
        (cfg, inherited), = (await split_inbox.resolve(s, [account_id])).values()
    config = split_inbox.heal(account_id, cfg, since=generation, inherited=inherited)
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
        async with get_session() as s:
            await _upsert(s, body.account_id, clean)
        split_inbox.remember(body.account_id, clean)
    log.info("split_inbox_saved account=%s groups=%d moves=%d bound=%d",
             body.account_id, clean["group_count"], len(clean["assignments"]), len(clean["chatter_groups"]))
    return {"account_id": body.account_id, "config": clean}


_Group = Annotated[StrictInt, Field(ge=1, le=split_inbox.MAX_GROUPS)]


class _EditBody(BaseModel):
    account_ids: list[Annotated[StrictStr, StringConstraints(min_length=1)]] = Field(min_length=1)
    group_count: _Group | None = None
    chatter_groups: dict[str, _Group | None] = {}
    assignments: dict[str, _Group] | None = None
    as_default: bool = False


async def _derive_default(s, user_id: str, configs: dict[str, dict]) -> dict:
    previous = await read_blob(s, user_id, split_inbox.DEFAULT_TAB)
    grants = await split_inbox.granted(sorted({cid for cfg in configs.values() for cid in cfg["chatter_groups"]}))
    return split_inbox.derive_default(configs, grants, split_inbox.parse(previous)["group_count"])


def _stale_group(cfg: dict, edit: dict) -> int | None:
    n = edit["group_count"] or cfg["group_count"]
    picked = [g for g in (*edit["chatter_groups"].values(), *edit["assignments"].values()) if g is not None]
    return next((g for g in picked if g > n), None)


@router.patch("/admin/split-inbox")
async def patch_split_inbox(body: _EditBody = Body(...)) -> dict[str, Any]:
    owner = assert_owner()
    ids = list(dict.fromkeys(body.account_ids))
    if body.assignments is not None and len(ids) > 1:
        raise HTTPException(422, "assignments apply to one account at a time")
    for aid in ids:
        assert_account_owned(aid)
    granted = await split_inbox.granted([cid for cid, g in body.chatter_groups.items() if g is not None])
    edits = {aid: {"group_count": body.group_count, "assignments": body.assignments or {},
                   "chatter_groups": {cid: g for cid, g in body.chatter_groups.items()
                                      if g is None or aid in granted[cid]}}
             for aid in ids}
    async with AsyncExitStack() as stack:
        for aid in sorted(ids):
            await stack.enter_async_context(split_inbox.save_lock(aid))
        if body.as_default:
            await stack.enter_async_context(split_inbox.save_lock(f"default:{owner.id}"))
        async with get_session() as s:
            current = {aid: cfg for aid, (cfg, _) in (await split_inbox.resolve(s, ids)).items()}
            for aid in ids:
                if (g := _stale_group(current[aid], edits[aid])) is not None:
                    raise HTTPException(409, f"Split Inbox changed elsewhere: Inbox {g} no longer exists. "
                                             "Review the settings and save again.")
            configs = {aid: split_inbox.apply(current[aid], edits[aid]) for aid in ids}
            default = await _derive_default(s, owner.id, configs) if body.as_default else None
            for aid, cfg in configs.items():
                await _upsert(s, aid, cfg)
            if default is not None:
                await write_blob(s, owner.id, split_inbox.DEFAULT_TAB, default)
        for aid, cfg in configs.items():
            split_inbox.remember(aid, cfg)
        if body.as_default:
            try:
                await split_inbox.default_changed(owner.id)
            except Exception:
                log.exception("split_inbox_default_refresh_failed owner=%s", owner.id)
    log.info("split_inbox_edited accounts=%d groups=%s bound=%d moves=%d default=%s",
             len(ids), body.group_count, len(body.chatter_groups), len(body.assignments or {}), body.as_default)
    return {"configs": configs}
