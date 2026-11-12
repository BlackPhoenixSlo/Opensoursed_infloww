"""service/vault_jev_pass.py — the Jev v8 pass wired into the vault sweeps (one photo or video; all, no opt-in).

`vault_jev`: TypeSafe Jev + NudeNet → `ai_fields_json["_jev"]`, and with it the item's flags
(`vault_jev_flags.apply`: the only flags a photo or video gets — no qwen flags call). Runs BEFORE describe
(both sweeps and the single-item route), which both need: no feedable `_jev`, no describe. Spend sits on
the account's own `typesafe` cap row, so a Jev cap never stops a sweep (deepinfra row) — it only skips Jev for
the rest of that sweep (`Sweep`), and those photos wait for the next one.

Names are looked up per call (`vault_ai_vision` calls `vault_jev_pass.<name>`, this module calls
`vault_jev.run` / `preflight` by module attr), so test / slop-fault patches bite.
"""
from __future__ import annotations

import base64
import contextlib
import json
import logging
from datetime import datetime
from typing import Any, Collection

from sqlalchemy import select

import llm_providers
import vault_ai_vision_decide as decide
import vault_frames
import vault_jev  # module attrs `run` / `preflight` / `nudenet_ready`, looked up per call
import vault_jev_flags
import vault_jev_rules
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_jev_pass")

JEV_KEY = vault_jev_rules.JEV_KEY
CAP_SKIP = "Jev daily cap reached earlier in this sweep — Jev skipped"
DOWN_SKIP = "Jev failed {n} calls in a row earlier in this sweep — Jev skipped"
DOWN_AFTER = 3   # Jev call failures in a row that read as an outage


class Sweep:
    """One sweep's Jev state: once TypeSafe's cap trips, or `DOWN_AFTER` Jev calls fail in a row (an outage), the
    rest of the sweep skips Jev (no still / clip fetch, no reserve); those items wait for the next sweep."""

    __slots__ = ("capped", "failed_in_row")

    def __init__(self) -> None:
        self.capped = False
        self.failed_in_row = 0

    @property
    def down(self) -> bool:
        return self.failed_in_row >= DOWN_AFTER

    @property
    def skip(self) -> bool:
        return self.capped or self.down

    def note(self, res: vault_jev.JevResult) -> None:
        if res.get("status") == "capped":
            self.capped = True
        elif res.get("call_failed"):
            self.failed_in_row += 1
        elif res.get("ok"):
            self.failed_in_row = 0


def _locked(item: VaultItem) -> set[str]:
    return set(load_json(item.locked_fields_json, []) or [])


async def _stamp(account_id: str, media_id: int, res: vault_jev.JevResult) -> None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is not None:
            fields = vault_jev.merge(load_json(item.ai_fields_json, {}) or {}, res, datetime.utcnow())
            locked = _locked(item)
            fields = vault_jev_flags.apply(fields, fields.get(JEV_KEY), locked)
            item.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
            item.explicitness_tier = vault_jev_flags.column_tier(fields, item.explicitness_tier, locked)
            await s.commit()


async def _sync_flags(account_id: str, media_id: int) -> None:
    """Re-stamp a current `_jev`'s flags (and the `explicitness_tier` column) on a row that drifted from it (a
    pre-mapping row, an old qwen answer or tier). Free: no call."""
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id), with_for_update=True)
        if item is None:
            return
        fields = load_json(item.ai_fields_json, {}) or {}
        locked = _locked(item)
        new = vault_jev_flags.apply(fields, fields.get(JEV_KEY), locked)
        tier = vault_jev_flags.column_tier(new, item.explicitness_tier, locked)
        if new != fields or tier != item.explicitness_tier:
            item.ai_fields_json = json.dumps(new, ensure_ascii=False, default=str)
            item.explicitness_tier = tier
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
    """Run the Jev pass on one photo or video and merge `_jev` (+ its flags) into its blob. None when there is
    nothing to pay for (another kind, or already current — its flags re-stamped if they drifted); no TypeSafe or
    NudeNet call happens then. Readiness (NudeNet + key) is checked before the still / clip is fetched. Never
    raises for a model failure: `vault_jev.run` / `run_video` report it as the result's `status`, stamped on the
    row. A clip's frames: `vault_frames.collect_jev_video`."""
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None or item.kind not in vault_jev_rules.JEV_KINDS:
        return None
    fields = load_json(item.ai_fields_json, {}) or {}
    if vault_jev_rules.current(fields):
        if not vault_jev_flags.row_in_sync(fields, item.locked_fields_json, tier=item.explicitness_tier):
            await _sync_flags(account_id, media_id)
        return None
    if sweep is not None and sweep.skip:
        if sweep.capped:
            return {"media_id": media_id, "ok": False, "status": "jev_capped", "detail": CAP_SKIP,
                    "cost_millicents": 0}
        return {"media_id": media_id, "ok": False, "status": "jev_down",
                "detail": DOWN_SKIP.format(n=sweep.failed_in_row), "cost_millicents": 0}
    refusal = await vault_jev.preflight()
    if refusal is not None:
        await _stamp(account_id, media_id, refusal)
        return _out(media_id, refusal)
    video = item.kind == "video"
    if video:
        got = await vault_frames.collect_jev_video(account_id, item)
        have = got.frames
    else:
        got = await vault_frames.collect(account_id, item, load_json(item.raw_json, {}) or {}, want=1)
        have = got.images
    if not have:
        status = vault_frames.NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no {'frames' if video else 'still'} ({status})", "cost_millicents": 0}
    if video:
        res = await vault_jev.run_video(account_id, got.frames, src=got.src, review=got.review, nbytes=got.nbytes)
    else:
        res = await vault_jev.run(account_id, base64.b64decode(got.images[0].split(",", 1)[1]))
    if sweep is not None:
        sweep.note(res)
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
    finally:
        vault_frames.drop_lane()   # a `clip_lane` slot the pass never used: not held through the describe after


async def clips_due(account_id: str) -> set[int]:
    """The account's clips whose Jev reading is due (`clip_lane`): one read per sweep, so an item's `hold` never
    awaits the DB and the sweep starts its visits in walk order."""
    async with get_session() as s:
        rows = (await s.execute(select(VaultItem.media_id, VaultItem.ai_fields_json).where(
            VaultItem.account_id == account_id, VaultItem.kind == "video"))).all()
    return {m for m, f in rows if not vault_jev_rules.current(load_json(f, {}) or {})}


def clip_lane(due: Collection[int], media_id: int,
              sweep: Sweep | None = None) -> contextlib.AbstractAsyncContextManager[Any]:
    """A sweep's `hold` (`vault_sweep.run`): a clip in `due` (`clips_due`) takes its `admission.JEV_VIDEO` slot
    BEFORE its vision slot (`vault_frames.lane_ahead`), waiting as long as the lane is busy, so a waiting clip holds
    no vision slot and never fails "lane full" because other clips are reading. Anything else holds nothing."""
    if media_id not in due or (sweep is not None and sweep.skip):
        return contextlib.nullcontext()
    return vault_frames.lane_ahead(f"jev video media={media_id}")


async def plan() -> dict[str, Any]:
    """Whether Jev can run on this server, for the drawer's notice: NudeNet (Jev refuses without it) and the
    TypeSafe key. Without either, photos are not flagged or described (skipped, retried next sweep)."""
    ready, reason = await vault_jev.nudenet_ready()
    if ready and not llm_providers.typesafe_key():
        ready, reason = False, "TYPESAFE_API_KEY is not set on this server"
    return {"ready": ready, "reason": reason}


def keep_current(cur_json: str | None, new_json: str, locked: Collection[str] = ()) -> str:
    """`new_json` (a blob built from a row read seconds ago) with the row's CURRENT `_jev` put back, and the
    flags mapped from it when the row carries those: a Jev pass that landed while a describe / flags call was
    in flight must not be overwritten by the stale read. The mapping is redone over the new blob, so a describe's
    fresh `clothing_items` name the photo's garments (`vault_jev_flags.garments`); `locked` keys keep the new
    blob's value."""
    cur_f = load_json(cur_json, {}) or {}
    cur = cur_f.get(JEV_KEY)
    if cur is None:
        return new_json
    new = json.loads(new_json or "{}") or {}
    want = dict(new)
    want[JEV_KEY] = cur
    if cur_f.get("_flags_model") == vault_jev_flags.MODEL:
        if vault_jev_flags.reading(cur) is None:
            decide.carry_flags(want, cur_f, exact=True)
        else:
            want = vault_jev_flags.apply(want, cur, locked)
            if cur_f.get(decide.FLAGS_COPY_MARK):   # a copy's flags are still its source's
                want[decide.FLAGS_COPY_MARK] = cur_f[decide.FLAGS_COPY_MARK]
    if want == new:
        return new_json
    return json.dumps(want, ensure_ascii=False, default=str)
