"""service/vault_jev_pass.py — the Jev v8 pass wired into the vault sweeps (one photo, opt-in per account).

`vault_jev`: TypeSafe Jev + NudeNet → `ai_fields_json["_jev"]`. Runs BEFORE describe (both sweeps and the
single-item route) and before the qwen flags call (flags sweep); clips keep the qwen path only. Spend sits on
the account's own `typesafe` cap row, so a Jev cap never stops a sweep (deepinfra row) — it only skips Jev for
the rest of that sweep (`Sweep`).

Names are looked up per call (`vault_ai_vision` calls `vault_jev_pass.<name>`, this module calls `enabled` /
`vault_jev.run` by global name), so test / slop-fault patches on this module bite.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

import llm_providers
import vault_frames
import vault_jev  # module attrs `run` / `preflight` / `nudenet_ready`, looked up per call
import vault_jev_rules
from db.engine import get_session
from db.models import AccountAiConfig, VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_jev_pass")

JEV_KEY = "_jev"
CAP_SKIP = "Jev daily cap reached earlier in this sweep — Jev skipped"


class Sweep:
    """One sweep's Jev state: once TypeSafe's cap trips, the rest of the sweep skips Jev (no still fetch,
    no reserve) while describe / qwen flags carry on."""

    __slots__ = ("capped",)

    def __init__(self) -> None:
        self.capped = False


async def enabled(account_id: str) -> bool:
    async with get_session() as s:
        return bool(await s.scalar(select(AccountAiConfig.vault_jev_enabled).where(
            AccountAiConfig.account_id == account_id)))


async def _stamp(account_id: str, media_id: int, res: vault_jev.JevResult) -> None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is not None:
            fields = vault_jev.merge(load_json(item.ai_fields_json, {}) or {}, res, datetime.utcnow())
            item.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
            await s.commit()


def _out(media_id: int, res: vault_jev.JevResult) -> dict[str, Any]:
    status = "jev_capped" if res.get("status") == "capped" else res.get("status")  # never a sweep stop
    out = {"media_id": media_id, "ok": bool(res.get("ok")), "status": status,
           "cost_millicents": int(res.get("cost_millicents") or 0)}
    if res.get("ok"):
        out["lane5"] = res["blob"]["lane5"]
    elif res.get("detail"):
        out["detail"] = str(res["detail"])[:300]
    return out


async def one(account_id: str, media_id: int, *,
              sweep: Sweep | None = None) -> dict[str, Any] | None:
    """Run the Jev pass on one photo and merge `_jev` into its blob. None when there is nothing to do
    (setting off, not a photo, already current) — no TypeSafe or NudeNet call happens then. Readiness
    (NudeNet + key) is checked before the still is fetched. Never raises for a model failure: `vault_jev.run`
    reports it as the result's `status`, stamped on the row."""
    if not await enabled(account_id):
        return None
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None or item.kind != "photo":
        return None
    if vault_jev_rules.current(load_json(item.ai_fields_json, {}) or {}):
        return None
    if sweep is not None and sweep.capped:
        return {"media_id": media_id, "ok": False, "status": "jev_capped", "detail": CAP_SKIP,
                "cost_millicents": 0}
    refusal = await vault_jev.preflight()
    if refusal is not None:
        await _stamp(account_id, media_id, refusal)
        return _out(media_id, refusal)
    got = await vault_frames.collect(account_id, item, load_json(item.raw_json, {}) or {}, want=1)
    if not got.images:
        status = vault_frames.NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no still ({status})", "cost_millicents": 0}
    data = base64.b64decode(got.images[0].split(",", 1)[1])
    res = await vault_jev.run(account_id, data)
    if res.get("status") == "capped" and sweep is not None:
        sweep.capped = True
    await _stamp(account_id, media_id, res)
    return _out(media_id, res)


async def safe(account_id: str, media_id: int, *,
               sweep: Sweep | None = None) -> dict[str, Any] | None:
    """`one` that never takes the pass after it down with it."""
    try:
        return await one(account_id, media_id, sweep=sweep)
    except Exception as e:  # noqa: BLE001
        log.exception("jev pass failed media=%s account=%s", media_id, account_id)
        return {"media_id": media_id, "ok": False, "status": "error",
                "detail": f"{type(e).__name__}: {e}"[:200], "cost_millicents": 0}


async def plan(account_id: str) -> dict[str, Any]:
    """The Jev toggle's state for the drawer: on/off, and whether NudeNet can run here (Jev refuses
    without it). Only loads NudeNet when on; no thread once it is loaded."""
    if not await enabled(account_id):
        return {"enabled": False, "ready": False, "reason": ""}
    ready, reason = await vault_jev.nudenet_ready()
    if ready and not llm_providers.typesafe_key():
        ready, reason = False, "TYPESAFE_API_KEY is not set on this server"
    return {"enabled": True, "ready": ready, "reason": reason}


def keep_current(cur_json: str | None, new_json: str) -> str:
    """`new_json` (a blob built from a row read seconds ago) with the row's CURRENT `_jev` put back: a Jev
    pass that landed while a describe / flags call was in flight must not be overwritten by the stale read."""
    cur = (load_json(cur_json, {}) or {}).get(JEV_KEY)
    if cur is None:
        return new_json
    new = json.loads(new_json or "{}") or {}
    if new.get(JEV_KEY) == cur:
        return new_json
    new[JEV_KEY] = cur
    return json.dumps(new, ensure_ascii=False, default=str)

