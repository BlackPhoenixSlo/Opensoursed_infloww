from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Collection

from sqlalchemy import select

import tenant_keys
import vault_ai_vision_decide as decide
import vault_frames
import vault_jev
import vault_jev_flags
import vault_jev_manual
import vault_jev_rules
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_jev_pass")

JEV_KEY = vault_jev_rules.JEV_KEY
CAP_SKIP = "Jev daily cap reached earlier in this sweep — Jev skipped"
DOWN_AFTER = 3
# A clip whose frame sources fail briefly is held (not read) and retried at RETRY_BACKOFF_S x 2^(n-1); the RETRY_MAXth visit reads what it got or gives up.
RETRY_MAX = 3
RETRY_BACKOFF_S = 6 * 3600
HELD = vault_jev_rules.HELD
GAVE_UP = vault_jev_rules.GAVE_UP
RETRY_WAIT = vault_jev_rules.RETRY_WAIT


class Sweep:

    __slots__ = ("capped", "failed_in_row", "warned", "last_error")

    def __init__(self) -> None:
        self.capped = False
        self.failed_in_row = 0
        self.warned = False
        self.last_error = ""

    @property
    def down(self) -> bool:
        return self.failed_in_row >= DOWN_AFTER

    @property
    def skip(self) -> bool:
        return self.capped or self.down

    def note(self, res: vault_jev.JevResult) -> None:
        import vault_sweep

        if res.get("status") == "capped":
            self.capped = True
        elif res.get("call_failed") and res.get("status") not in vault_sweep.NEUTRAL:
            self.failed_in_row += 1
            self.last_error = str(res.get("detail") or "")[:200]
        elif res.get("ok"):
            self.failed_in_row = 0


async def fatal(account_id: str, res: dict[str, Any] | None, sweep: Sweep | None) -> None:
    import vault_sweep
    status = (res or {}).get("status")
    if status in vault_jev.KEY_ERROR_KIND:
        raise await vault_jev.key_error(account_id, status)
    if sweep is None:
        return
    if status == "no_nudenet":
        raise vault_sweep.SweepStop("Stopped: the NudeNet model is not installed on this server, so Jev can't read "
                                    "photos.", "Ask the server admin to set NUDENET_640M_PATH, then press again.")


def down_stop(sweep: Sweep, spent: int = 0) -> Exception:
    import vault_sweep
    why = f" Last error: {sweep.last_error}." if sweep.last_error else ""
    return vault_sweep.SweepStop(f"Stopped: Jev (TypeSafe) failed {sweep.failed_in_row} calls in a row.{why}",
                                 "Try again later; if it keeps failing, check the TypeSafe key in Settings › AI keys.",
                                 jev_cost_millicents=spent)


def _locked(item: VaultItem) -> set[str]:
    return set(load_json(item.locked_fields_json, []) or [])


def held_blob(old: Any, n: int, detail: str, at: str, *, terminal: bool) -> dict[str, Any]:
    if terminal:
        return {"v": vault_jev_rules.VERSION, "status": GAVE_UP, "kind": "video", "vv": vault_jev_rules.VIDEO_VERSION,
                "lane5": "review", "read_lane5": None, "state": {}, "frames": [], "src": "", "review": HELD,
                "retries": n, "error": detail[:200], "at": at, "failed_at": at, vault_jev_rules.GAVE_UP_MARK: True}
    old = old if isinstance(old, dict) else {}
    b = {**old, "v": old.get("v", vault_jev_rules.VERSION), "status": "fetch_failed", "error": detail[:200],
         "failed_at": at, "retries": n, "review": HELD}
    if old.get("lane5") != "$100":
        b.update(lane5="review", read_lane5=vault_jev_rules.read_lane(old))
    return b


def retry_due(jev: Any, now: datetime) -> bool:
    if not isinstance(jev, dict) or "retries" not in jev or not jev.get("failed_at"):
        return True
    try:
        n = max(1, int(jev.get("retries") or 1))
        at = datetime.fromisoformat(str(jev.get("failed_at")))
    except (TypeError, ValueError):
        return True
    return now >= at + timedelta(seconds=RETRY_BACKOFF_S * 2 ** (n - 1))


def sweep_due(fields: dict[str, Any] | None, now: datetime) -> bool:
    f = fields or {}
    return (not vault_jev_rules.ai_read(f) and not vault_jev_rules.retries_spent(f)
            and retry_due(f.get(JEV_KEY), now))


def _picks(item: VaultItem, fields: dict[str, Any]) -> None:
    picks = vault_jev_manual.stored(item.operator_overrides_json)
    if picks and JEV_KEY in fields:
        j = vault_jev_manual.overlay(fields[JEV_KEY], picks, vault_jev_manual.kind_of(fields[JEV_KEY], item.kind))
        if j is not None:
            fields[JEV_KEY] = j


async def _hold(account_id: str, media_id: int, n: int, detail: str, *, terminal: bool) -> None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id), with_for_update=True)
        if item is None:
            return
        fields = load_json(item.ai_fields_json, {}) or {}
        held = held_blob(fields.get(JEV_KEY), n, detail, datetime.utcnow().isoformat(), terminal=terminal)
        fields[JEV_KEY] = vault_jev_rules.keep_reject(fields, held)
        _picks(item, fields)
        item.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
        if fields[JEV_KEY].get("lane5") == "review" and vault_jev_flags.TIER_COLUMN not in _locked(item):
            item.explicitness_tier = None
        await s.commit()


async def _stamp(account_id: str, media_id: int, res: vault_jev.JevResult) -> None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is not None:
            fields = vault_jev.merge(load_json(item.ai_fields_json, {}) or {}, res, datetime.utcnow())
            _picks(item, fields)
            locked = _locked(item)
            fields = vault_jev_flags.apply(fields, fields.get(JEV_KEY), locked)
            item.ai_fields_json = json.dumps(fields, ensure_ascii=False, default=str)
            item.explicitness_tier = vault_jev_flags.column_tier(fields, item.explicitness_tier, locked)
            await s.commit()


async def _sync_flags(account_id: str, media_id: int) -> None:
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
    status = vault_jev_rules.JEV_CAPPED if res.get("status") == "capped" else res.get("status")
    out = {"media_id": media_id, "ok": bool(res.get("ok")), "status": status,
           "cost_millicents": int(res.get("cost_millicents") or 0)}
    if res.get("ok"):
        out["lane5"] = res["blob"]["lane5"]
    elif res.get("detail"):
        out["detail"] = str(res["detail"])[:300]
        if res.get("status") == "capped":
            out["notice"] = str(res["detail"])[:200]
    return out


# One Jev pass per item at a time in this process: a waiting caller re-reads the row and finds it current instead of paying twice.
_inflight: dict[tuple[str, int], list[Any]] = {}


async def one(account_id: str, media_id: int, *,
              sweep: Sweep | None = None) -> dict[str, Any] | None:
    key = (account_id, int(media_id))
    slot = _inflight.setdefault(key, [asyncio.Lock(), 0, None])
    slot[1] += 1
    try:
        async with slot[0]:
            if slot[2] is not None:
                return {**slot[2], "cost_millicents": 0}
            called: list[dict[str, Any]] = []
            try:
                return await _one(account_id, media_id, sweep=sweep, called=called)
            finally:
                if called and not called[0]["ok"] and slot[1] > 1:
                    slot[2] = called[0]
    finally:
        slot[1] -= 1
        if not slot[1]:
            _inflight.pop(key, None)


async def _one(account_id: str, media_id: int, *, sweep: Sweep | None = None,
               called: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None or item.kind not in vault_jev_rules.JEV_KINDS:
        return None
    if item.removed_at is not None:
        return {"media_id": media_id, "ok": False, "status": "gone", "cost_millicents": 0,
                "detail": "removed from OF since the sweep picked it — not read"}
    fields = load_json(item.ai_fields_json, {}) or {}
    if vault_jev_rules.ai_read(fields):
        if not vault_jev_flags.row_in_sync(fields, item.locked_fields_json, tier=item.explicitness_tier):
            await _sync_flags(account_id, media_id)
        return None
    prev = fields.get(JEV_KEY) if isinstance(fields.get(JEV_KEY), dict) else {}
    if sweep is not None:
        if reason := vault_jev_rules.stop_reason(fields):
            return {"media_id": media_id, "ok": False, "status": reason, "cost_millicents": 0,
                    "detail": vault_jev_rules.STOP_DETAILS[reason]}
        if not retry_due(prev, datetime.utcnow()):
            return {"media_id": media_id, "ok": False, "status": RETRY_WAIT, "cost_millicents": 0,
                    "detail": f"clip sources failed briefly: retry {int(prev.get('retries') or 0) + 1}/{RETRY_MAX} "
                              "waits out its backoff"}
    if sweep is not None and sweep.capped:
        return {"media_id": media_id, "ok": False, "status": vault_jev_rules.JEV_CAPPED, "detail": CAP_SKIP,
                "notice": CAP_SKIP, "cost_millicents": 0}
    if sweep is not None and sweep.down:
        raise down_stop(sweep)
    refusal = await vault_jev.preflight(account_id)
    if refusal is not None:
        if sweep is None or not sweep.warned:
            log.warning("vault_jev skipped status=%s account=%s", refusal.get("status"), account_id)
            if sweep is not None:
                sweep.warned = True
        await _stamp(account_id, media_id, refusal)
        return _out(media_id, refusal)
    video = item.kind == "video"
    if video:
        got = await vault_frames.collect_jev_video(account_id, item)
        have = got.frames
    else:
        got = await vault_frames.collect(account_id, item, load_json(item.raw_json, {}) or {}, want=1)
        have = got.images
    if video and got.transient:
        n = int(prev.get("retries") or 0) + 1
        if n < RETRY_MAX or not have:
            why = got.detail or f"clip sources failed briefly ({got.review or got.src})"
            await _hold(account_id, media_id, n, why, terminal=n >= RETRY_MAX)
            return {"media_id": media_id, "ok": False, "status": "fetch_failed", "cost_millicents": 0,
                    "detail": f"{why}: " + (f"gave up after {n}, review" if n >= RETRY_MAX
                                            else f"retry {n}/{RETRY_MAX} after its backoff")}
    if not have:
        status = vault_frames.NO_IMAGE_STATUS.get(got.reason, "fetch_failed")
        return {"media_id": media_id, "ok": False, "status": status,
                "detail": got.detail or f"no {'frames' if video else 'still'} ({status})", "cost_millicents": 0}
    if video:
        res = await vault_jev.run_video(account_id, got.frames, src=got.src, review=got.review, nbytes=got.nbytes)
    else:
        res = await vault_jev.run(account_id, base64.b64decode(got.images[0].split(",", 1)[1]))
    if called is not None:
        called.append(_out(media_id, res))
    if sweep is not None:
        sweep.note(res)
    await _stamp(account_id, media_id, res)
    if sweep is not None and sweep.down:
        raise down_stop(sweep, int(res.get("cost_millicents") or 0))
    return _out(media_id, res)


async def safe(account_id: str, media_id: int, *,
               sweep: Sweep | None = None) -> dict[str, Any] | None:
    import vault_sweep
    try:
        return await one(account_id, media_id, sweep=sweep)
    except vault_sweep.SweepStop:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("jev pass failed media=%s account=%s", media_id, account_id)
        return {"media_id": media_id, "ok": False, "status": "error",
                "detail": f"{type(e).__name__}: {e}"[:200], "cost_millicents": 0}
    finally:
        vault_frames.drop_lane()


async def checked(account_id: str, media_id: int, *, sweep: Sweep | None = None) -> dict[str, Any] | None:
    res = await safe(account_id, media_id, sweep=sweep)
    await fatal(account_id, res, sweep)
    return res


async def clips_due(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(select(VaultItem.media_id, VaultItem.ai_fields_json).where(
            VaultItem.account_id == account_id, VaultItem.kind == "video"))).all()
    now = datetime.utcnow()
    return {m for m, f in rows if sweep_due(load_json(f, {}) or {}, now)}


def clip_lane(due: Collection[int], media_id: int,
              sweep: Sweep | None = None) -> contextlib.AbstractAsyncContextManager[Any]:
    if media_id not in due or (sweep is not None and sweep.skip):
        return contextlib.nullcontext()
    return vault_frames.lane_ahead(f"jev video media={media_id}")


async def plan(account_id: str | None = None) -> dict[str, Any]:
    ready, reason = await vault_jev.nudenet_ready()
    if ready and not await tenant_keys.typesafe_key_for(account_id):
        ready, reason = False, "no TypeSafe key: add one in Settings → AI keys"
    return {"ready": ready, "reason": reason}


def keep_current(cur_json: str | None, new_json: str, locked: Collection[str] = ()) -> str:
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
            if cur_f.get(decide.FLAGS_COPY_MARK):
                want[decide.FLAGS_COPY_MARK] = cur_f[decide.FLAGS_COPY_MARK]
    if want == new:
        return new_json
    return json.dumps(want, ensure_ascii=False, default=str)
