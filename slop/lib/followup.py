"""The follow-up world and tick the three follow-up scenarios share
(scenarios/2026-10-30-followup-drip.py, -run-slot-pool.py, -dispatch-plan.py).

`setup`: the profile's world (ctx.world) plus seed/followup_drip.py, the agency's (fake) DeepSeek
key and the account DM rate raised to DM_PER_MIN through the real Concurrency panel route. `tick`:
one `POST /__slop/run-automation` (kind `send_followup`, the product's `run_once` under the run-slot
pool) with `payload`: `with_image: false`, so the vault is never read, and `limit` = fans per
Creator, so the 200-fan sweep ceiling never thins a tick. `refuse_live`: SLOP_LIVE=1 would spend on the real
DeepSeek, so every check SKIPs.
"""
from __future__ import annotations

import os
import time

from slop.seed import followup_drip

DM_PER_MIN = 600


def refuse_live(ctx, names) -> bool:
    if os.environ.get("SLOP_LIVE") != "1":
        return False
    for n in names:
        ctx.skip(n, "SLOP_LIVE=1 would call the paid DeepSeek API; this scenario runs on the fake only")
    return True


def payload(ctx) -> dict:
    return {"with_image": False, "limit": int(ctx.world.size["fans_per_creator"])}


async def setup(ctx, profile: str) -> dict:
    """-> the drip seed's result (seed/followup_drip.py); the world is ctx.world."""
    w = await ctx.build(profile)
    drip = followup_drip.seed(w, w.data["fans"], w.data["threads"], frac=float(ctx.param("followup_frac", 1.0)))
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepseek": "slop-fake-deepseek"})
    ctx.metric("agency_deepseek_key", {"status": r.status_code})
    r = await ctx.owner.post("/lanes-panel/config", json={"values": {"OF_DM_PER_MIN": DM_PER_MIN}})
    ctx.metric("dm_per_min", {"set": DM_PER_MIN, "status": r.status_code})
    return drip


async def tick(ctx, aid: str) -> dict:
    """-> {aid, status, ms, res, slot}: `res` always a dict, the run's result (else the hook's whole answer,
    its `error` included); `slot` the hook's stamps (None when it did not answer)."""
    t = time.perf_counter()
    r = await ctx.owner.post("/__slop/run-automation", timeout=900, json={
        "account_id": aid, "kind": "send_followup", "payload": payload(ctx)})
    body = r.json() if r.status_code < 300 else {"error": r.text[:300]}
    return {"aid": aid, "status": r.status_code, "ms": (time.perf_counter() - t) * 1000,
            "res": body.get("result") if isinstance(body.get("result"), dict) else body,
            "slot": body.get("slot")}
