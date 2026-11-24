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
import vault_jev  # module attrs `run` / `preflight` / `nudenet_ready`, looked up per call
import vault_jev_flags
import vault_jev_manual
import vault_jev_rules
from db.engine import get_session
from db.models import VaultItem
from jsonsafe import load_json

log = logging.getLogger("of-relay.vault_jev_pass")

JEV_KEY = vault_jev_rules.JEV_KEY
CAP_SKIP = "Jev daily cap reached earlier in this sweep — Jev skipped"
DOWN_AFTER = 3   # Jev call failures in a row that read as an outage
# A clip whose sources failed briefly (`vault_frames.JevFrames.transient`: frames read after a failed source, or none,
# a failed re-sign included) is not read: `_jev` is held (`held_blob`: review, not current), its count in
# `_jev.retries`, its time in `failed_at`. A sweep retries it only RETRY_BACKOFF_S x 2^(n-1) after the nth hold
# (`retry_due`; before that the visit is `RETRY_WAIT`, no fetch — persisted in the blob, so a restart keeps it). The
# RETRY_MAXth such visit reads the frames it got (their `review` reading stands) or, with none, gives up
# (`vault_jev_rules.GAVE_UP`): a clip that always fails stops costing a download a sweep, and no sweep reselects it.
# A single item's route (no `Sweep`: the operator asked) skips the backoff and re-reads a gave-up clip once.
RETRY_MAX = 3
RETRY_BACKOFF_S = 6 * 3600
HELD = vault_jev_rules.HELD
GAVE_UP = vault_jev_rules.GAVE_UP   # also the visit status (`vault_sweep.NEUTRAL`)
RETRY_WAIT = vault_jev_rules.RETRY_WAIT   # a held clip inside its backoff (`vault_sweep.NEUTRAL`)


class Sweep:
    """One sweep's Jev state: once TypeSafe's cap trips the rest of the sweep skips Jev (`jev_capped`, neutral for
    the breaker: no still / clip fetch, no reserve; those items wait for the next sweep); once `DOWN_AFTER` Jev calls
    fail in a row (an outage) `_one` stops the sweep (`down_stop`) on that visit and any later one that needs a call.
    `warned`: the sweep already logged a refusal (`no_key` / `no_nudenet`): one line a sweep, not one an item."""

    __slots__ = ("capped", "failed_in_row", "warned", "last_error")

    def __init__(self) -> None:
        self.capped = False
        self.failed_in_row = 0
        self.warned = False
        self.last_error = ""   # the last failed call's detail (`down_stop` names it)

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
    """Raise when `safe`'s result means no item can be read: a key status (`vault_jev.KEY_ERROR_KIND`) is an
    `LLMKeyError` everywhere (a single item's route answers 424); inside a sweep (`sweep` given) NudeNet missing is a
    `vault_sweep.SweepStop` (a Jev outage is `_one`'s, on the visits that need a call). Called by `checked` right
    after `safe`, so the row is stamped and the proxy-health log line written first. Else returns."""
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
    """The `vault_sweep.SweepStop` of a sweep whose Jev calls failed `DOWN_AFTER` times in a row (an outage);
    `spent`: the stopping visit's own call cost (millicents), counted in the sweep's progress (W30 C6)."""
    import vault_sweep
    why = f" Last error: {sweep.last_error}." if sweep.last_error else ""
    return vault_sweep.SweepStop(f"Stopped: Jev (TypeSafe) failed {sweep.failed_in_row} calls in a row.{why}",
                                 "Try again later; if it keeps failing, check the TypeSafe key in Settings › AI keys.",
                                 jev_cost_millicents=spent)


def _locked(item: VaultItem) -> set[str]:
    return set(load_json(item.locked_fields_json, []) or [])


def held_blob(old: Any, n: int, detail: str, at: str, *, terminal: bool) -> dict[str, Any]:
    """The `_jev` of a clip whose sources failed briefly `n` times (`RETRY_MAX`). Its last reading's fields are kept
    but read as unknown: `lane5` "review" (its lane kept as `read_lane5`; a $100 stays) and `review` fetch_failed, so
    the pack picker never prices it free and `vault_ai_brief` keeps its stale flags out of every free lane. `status`
    fetch_failed: not current, retried after its backoff (`retry_due`). `terminal`: status GAVE_UP
    (`vault_jev_rules.gave_up`), review, no answers and no lane it read, so the sweeps stop fetching the clip."""
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
    """A held clip's (`held_blob`) next retry is due: RETRY_BACKOFF_S x 2^(n-1) after its nth hold (`failed_at`).
    Read off `retries` + `failed_at`, which an operator pick or a failed re-read keeps (status / review may change:
    W30 C2); a reading replaces the blob. Anything else (no hold, an unreadable stamp) is due."""
    if not isinstance(jev, dict) or "retries" not in jev or not jev.get("failed_at"):
        return True
    try:
        n = max(1, int(jev.get("retries") or 1))
        at = datetime.fromisoformat(str(jev.get("failed_at")))
    except (TypeError, ValueError):
        return True
    return now >= at + timedelta(seconds=RETRY_BACKOFF_S * 2 ** (n - 1))


def sweep_due(fields: dict[str, Any] | None, now: datetime) -> bool:
    """A sweep's Jev work on this row: not AI-read yet, not given up on (`vault_jev_rules.retries_spent`), past any
    retry backoff (`retry_due`). The one "due" every sweep reads (`one`, `clips_due`, the flags todo). W30 R7."""
    f = fields or {}
    return (not vault_jev_rules.ai_read(f) and not vault_jev_rules.retries_spent(f)
            and retry_due(f.get(JEV_KEY), now))


def _picks(item: VaultItem, fields: dict[str, Any]) -> None:
    """Lay the operator's Jev picks (`vault_jev_manual`) over the `_jev` just written, so a re-read keeps them."""
    picks = vault_jev_manual.stored(item.operator_overrides_json)
    if picks and JEV_KEY in fields:
        j = vault_jev_manual.overlay(fields[JEV_KEY], picks, vault_jev_manual.kind_of(fields[JEV_KEY], item.kind))
        if j is not None:
            fields[JEV_KEY] = j


async def _hold(account_id: str, media_id: int, n: int, detail: str, *, terminal: bool) -> None:
    """Stamp `held_blob`; the `explicitness_tier` column unknown (None) unless operator-locked or $100, until a
    retry reads the clip."""
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
    status = vault_jev_rules.JEV_CAPPED if res.get("status") == "capped" else res.get("status")  # never a sweep stop
    out = {"media_id": media_id, "ok": bool(res.get("ok")), "status": status,
           "cost_millicents": int(res.get("cost_millicents") or 0)}
    if res.get("ok"):
        out["lane5"] = res["blob"]["lane5"]
    elif res.get("detail"):
        out["detail"] = str(res["detail"])[:300]
        if res.get("status") == "capped":
            out["notice"] = str(res["detail"])[:200]   # the sweep-wide line (`vault_sweep.run`)
    return out


# (account, media) → [lock, users, failed result]: one Jev pass per item at a time in this process (W30 F23). The
# describe and the flags sweep both visit an item; the second waits, then re-reads the row and finds it current (no
# second payment) — or, when the pass it waited on made a Jev call that failed (the sweep stopping on it included),
# takes that result with no spend of its own instead of paying again (W30 C3). A visit that made no call (capped,
# not due, gave up, refused, no frames) hands nothing on: the waiter runs its own checks (W30 D2).
_inflight: dict[tuple[str, int], list[Any]] = {}


async def one(account_id: str, media_id: int, *,
              sweep: Sweep | None = None) -> dict[str, Any] | None:
    """`_one` under the item's in-process lock (`_inflight`): a caller that waited re-checks the row first, or takes
    the failed Jev call of the pass it waited on (its `cost_millicents` 0: the spend is counted once)."""
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
            finally:   # a caller waits: hand it a failed call, also when that call stopped the sweep (raised)
                if called and not called[0]["ok"] and slot[1] > 1:
                    slot[2] = called[0]
    finally:
        slot[1] -= 1
        if not slot[1]:
            _inflight.pop(key, None)


async def _one(account_id: str, media_id: int, *, sweep: Sweep | None = None,
               called: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Run the Jev pass on one photo or video and merge `_jev` (+ its flags) into its blob. None when there is
    nothing to pay for (another kind, or already AI-read, `vault_jev_rules.ai_read` — its flags re-stamped if they drifted); no TypeSafe or
    NudeNet call happens then. Readiness (NudeNet + key) is checked before the still / clip is fetched. Never
    raises for a model failure: `vault_jev.run` / `run_video` report it as the result's `status`, stamped on the
    row; an item removed from OF is `gone` (neutral), unread. A clip's frames: `vault_frames.collect_jev_video`;
    frames read after a brief source failure: `RETRY_MAX`.
    A refusal (`no_key` / `no_nudenet`) logs one line per `sweep` (per call without one). `called` gets the
    result of a Jev call made (before a `down_stop` raises), for `one`'s waiter."""
    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
    if item is None or item.kind not in vault_jev_rules.JEV_KINDS:
        return None
    if item.removed_at is not None:   # OF deleted it after a sweep picked it (#948): no fetch, no call (W30 C5)
        return {"media_id": media_id, "ok": False, "status": "gone", "cost_millicents": 0,
                "detail": "removed from OF since the sweep picked it — not read"}
    fields = load_json(item.ai_fields_json, {}) or {}
    if vault_jev_rules.ai_read(fields):   # picks alone (no reading) still scan
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
    if sweep is not None and sweep.down:   # an outage already: this item needs a call, so no fetch, no call
        raise down_stop(sweep)
    refusal = await vault_jev.preflight(account_id)
    if refusal is not None:
        if sweep is None or not sweep.warned:   # proxy-health `vault_jev_errors` alerts on it
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
    if sweep is not None and sweep.down:   # this call made the outage: the row is stamped, the sweep stops
        raise down_stop(sweep, int(res.get("cost_millicents") or 0))
    return _out(media_id, res)


async def safe(account_id: str, media_id: int, *,
               sweep: Sweep | None = None) -> dict[str, Any] | None:
    """`one` that never takes the pass after it down with it (a `SweepStop` is the sweep's, it passes)."""
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
        vault_frames.drop_lane()   # a `clip_lane` slot the pass never used: not held through the describe after


async def checked(account_id: str, media_id: int, *, sweep: Sweep | None = None) -> dict[str, Any] | None:
    """The one entry point the sweeps / routes call: `safe` (row stamped, log written), then `fatal` (a key /
    server cause raises). `safe` looked up per call, so patches bite. W30 F20."""
    res = await safe(account_id, media_id, sweep=sweep)
    await fatal(account_id, res, sweep)
    return res


async def clips_due(account_id: str) -> set[int]:
    """The account's clips whose Jev reading is due (`clip_lane`): one read per sweep, so an item's `hold` never
    awaits the DB and the sweep starts its visits in walk order."""
    async with get_session() as s:
        rows = (await s.execute(select(VaultItem.media_id, VaultItem.ai_fields_json).where(
            VaultItem.account_id == account_id, VaultItem.kind == "video"))).all()
    now = datetime.utcnow()
    return {m for m, f in rows if sweep_due(load_json(f, {}) or {}, now)}


def clip_lane(due: Collection[int], media_id: int,
              sweep: Sweep | None = None) -> contextlib.AbstractAsyncContextManager[Any]:
    """A sweep's `hold` (`vault_sweep.run`): a clip in `due` (`clips_due`) takes its `admission.JEV_VIDEO` slot
    BEFORE its vision slot (`vault_frames.lane_ahead`), waiting as long as the lane is busy, so a waiting clip holds
    no vision slot and never fails "lane full" because other clips are reading. Anything else holds nothing."""
    if media_id not in due or (sweep is not None and sweep.skip):
        return contextlib.nullcontext()
    return vault_frames.lane_ahead(f"jev video media={media_id}")


async def plan(account_id: str | None = None) -> dict[str, Any]:
    """Whether Jev can run for `account_id`, for the drawer's notice: NudeNet (Jev refuses without it) and a
    TypeSafe key (its agency's, else the server's). Without either, photos are not flagged or described (skipped,
    retried next sweep)."""
    ready, reason = await vault_jev.nudenet_ready()
    if ready and not await tenant_keys.typesafe_key_for(account_id):
        ready, reason = False, "no TypeSafe key: add one in Settings → AI keys"
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
