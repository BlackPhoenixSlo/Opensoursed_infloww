"""service/full_ai_api.py — the Full AI Chatter page's read: one Creator's
live, Shadow and Test chat Decision rows of today (`ai_decisions`, automations/full_ai_chat.py).

  GET /admin/full-ai/today?account_id=
      → {since, counts: {route: n for every Route, zeros included},
         jev_failed, rows: [{id, created_at, fan_id, fan_name, route, heat,
                             row, jev_ms, jev_failed, test}]}
      newest first, at most `ROWS` rows: live and Shadow rows and the Test chat's Turns (mode test, both
      sides; `test: true`, no fan name: the page shows "Test chat"), counted alike. `since` is midnight
      of today in the Agency's report zone (`stats._report_zone`; UTC without
      one). A row is Jev-failed when its `jev_error` is set.

  GET /admin/full-ai/revenue?account_id=
      → {live_since, note, arms: {arm: {fans, in_window, complete, cents, cents_per_fan}},
         routes: [{route, offers, bought, cents}]}   full_ai_revenue.revenue: Enrolment derived (his
      first inbound at / after the Creator's first live row), 14-day cleared money per enrolled
      Fan, live priced Offers per Route. No holdout gate yet: one group `all`, `note` "no holdout:
      not a comparison". Reads only, settles nothing; live rows only.

  GET /admin/full-ai/mode?account_id=
      → {mode: "off" | "shadow" | "live", off_switch, blockers}   the Mode control (ticket 74, spec
      04a). `live` = an enabled `full_ai_chat` rule with `trigger_json.mode` "live"
      (`full_ai_live.live_rule`); `shadow` = enabled without it (a legacy rule: "records only"); else
      `off`. `off_switch` = FULL_AI_CHAT_OFF is set (it wins over Mode: nothing sends). `blockers` =
      why Live would be refused now (`live_blockers`), empty when it may go Live.
  PUT /admin/full-ai/mode {account_id, mode: "off" | "live"}   → the GET shape after the write.
      `live`: 409 naming the blockers, else the Creator's one `full_ai_chat` rule (created or the
      legacy one updated in place) enabled with `trigger_json` {"every_seconds": 300, "mode": "live"},
      and the waiting-chats catch-up (`full_ai_catchup.start`) started on `catchup_minutes` (default now, +5, +15, then every 25 min).
      `off`: the catch-up stopped, every rule of the kind disabled, trigger {"every_seconds": 300}, every
      pending job of the kind cancelled ("rule switched off"). `shadow` or anything else: 422. A failed blocker read
      answers one blocker (Live refused), never an error. The shared rule routes never
      turn this kind on (`automation_rules_api._refuse_config_route_kind`): this route is the only way
      Live is set.

  POST /admin/full-ai/test/photo {account_id, image (data URL), text?}
      → {desc, thumb, outcome, model, ms}   his one attached image, described ONCE for both
      sides (`inbound_describe.describe_upload`, purpose `full_ai_test_photo`, the account's own
      DeepInfra key) when either side's `describe_fan_photos` is on (else outcome "off", desc
      null); `thumb` a small JPEG. 415 / 413 not a JPG / PNG / GIF / WebP image or over 20 MB
      (bio pages' limits), 424 no DeepInfra key (server.py's key notice), 429 on the cost cap;
      a failed or refused description is outcome "none" / "failed" and desc null. Stores
      nothing: the client sends it back as each side's turn `photo`. A duplicate POST (same image
      and text) while one runs shares its call and answer. Same gates as the turn.
  POST /admin/full-ai/test/turn {account_id, pair, side: "checkpoint"|"draft", n, text, photo?}
      → {row_id, route, heat, route_row, dropped, parts, writer, attempts, wait_s, status, fan_info,
         offer}
      `offer` (03b): `full_ai_test.offer_of` of the row: a sell_now Offer (priced), a tease's Pick
      (kind `tease`, price null) or a make_right Free item (kind `free`, price 0); null on any
      other Route, on a Refusal or a dropped PPV. The session read's rows carry it too. `caption`
      {writer: caption|chat, model, outcome, ms, attempts} only with `caption_writer` "caption" on
      a PPV Turn (full_ai_turn._caption).
      One Test chat Turn (automations/full_ai_turn.py, Mode test): `n` is the client's Turn
      number for the side's session; any `n` but 1 + the session's row count, a replay of a
      recorded Turn, or the same Turn while it still runs (no paid call) is 409 {row_id | null}.
      The owner, or a member whose role grants the page (the `full_ai_chat` opt-in gate); a
      folder-limited chatter with the grant sees every folder's picks here (owner 11-15: access
      is taken away with the page permission, not per folder).
      `photo` (the photo route's reply) makes `text` optional; it lands on the row as
      `reply_json.fan_photo`, and as `photo` (+ `read`: this side read the description) on the
      answer and the session read's row.
  GET /admin/full-ai/test/session?account_id=&pair=
      → {rows: [...]} both sides' rows, oldest first.
  POST /admin/full-ai/test/settle {account_id, pair, side: "checkpoint"|"draft", row_id,
                                   outcome: "bought"|"declined"}
      → {row_id, outcome}   fake Buy / Decline (03b): that test row's `outcome`, `outcome_at`,
      `join_src='test'` only (full_ai_test.settle). 404 {detail: "not_this_session"} (no such row
      in that side's session) | 409 {detail: "already_settled", outcome} (the stored one, never
      flipped) | 422 {detail: "not_a_priced_offer"} (a chat row, tease or Free item) | 422 {detail:
      "already_owned"} (a Buy of media he already owns in that session: the other row of a haggle
      chain, bought, or a Free item) | 403 not your account. Same gates as the turn.
  POST /admin/full-ai/prepare-content {account_id}      → {run_id, steps, started_at, finished_at}
  GET  /admin/full-ai/prepare-content/status?account_id= → the same shape (full_ai_prepare)
      the owner's press only; a running run is returned as is. Chatters are refused
      before the handler (`chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`).

  GET /admin/full-ai/rules?mode=test|shadow   (default test)
      → full_ai_rules.rules(mode): the AI rules page's (/ai-rules) read-only diagram of the Turn
      (steps, every prompt and Jev question off the live constants, routes, stored keys). No
      Creator data: signed in only (401 without), the page's role grant is the middleware's
      (permissions.PAGE_MAP["/ai-rules"]).

Guards: the account's owner (`assert_account_owned`); the page's role grant
is the middleware's (permissions.PAGE_MAP["/full-ai-chatter"]). The page's
Mode control is PUT /admin/full-ai/mode (`full_ai_chat` in OPT_IN_KINDS); it and the test
turn take the same gate (`require_opt_in_kind`: the owner or a granted member).

  POST /admin/full-ai/persona/draft {account_id, current_text}
      → {text, age, city, name, images_used, images_described, need_describe,
         notes} — the Model info draft from her images (full_ai_persona.py,
      spec phase-03c Solution 1). Owner only (`/full-ai-chatter` is outside
      OPT_IN_PAGES, so every chatter is refused). Under 3 safe lines it first runs
      the vault describe on up to 6 newest blank photos (`fill_gap`, ticket 54);
      those describe fields + tier and llm_client's grok_calls rows are its only
      writes, the persona is never saved. No line after that → need_describe and
      no text call. 429 on the cost cap, 502 on a bad reply.

  GET  /admin/full-ai/config?account_id=           → {checkpoint, previous, draft, rev, errors, writer_models, writer_providers,
                                                      provider_labels, reference, limits}
  PUT  /admin/full-ai/config/draft {account_id, draft, rev}
  PUT  /admin/full-ai/config/checkpoint {account_id, checkpoint, rev}   the checkpoint JSON typed in; the old
      checkpoint becomes `previous` (Roll back undoes it), the draft stays
  POST /admin/full-ai/config/save {account_id, rev}
  POST /admin/full-ai/config/rollback {account_id, rev}
      → each the GET shape after the write. 422 {errors: ["<key>: <why>"]} on field errors,
      nothing to save or nothing to roll back to; 409 {detail, rev} when `rev` is not the
      stored one (someone stored meanwhile: reload); 409 {detail} when the Creator is Live and the
      new checkpoint has no Fans list (D61 holds while Live). Full AI Chat's config
      (`account_ai_config.full_ai_config_json`, automations/full_ai_config.py): the checkpoint
      drives Shadow and the Test chat's checkpoint side, the stored draft only its draft side.
      `errors` is the stored draft's; `writer_models` the models a `writers` entry may name (the page's
      Writer select); `writer_providers` {model: provider} for those and every saved / draft Writer (the LLM keys
      row names the providers the Writers run on); `provider_labels` {provider: name} (`_KEY_LABELS`, that row's names); `reference` every key's {key, default, allowed, about, page} (`full_ai_config.reference`, the
      JSON modal's "All settings" table); `limits` the controls' constants (`full_ai_config.limits`). Writes take
      the `full_ai_chat` opt-in gate (as the test turn) and touch nothing but that column; the GET follows the page grant.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal, get_args

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import full_ai_persona
import full_ai_prepare
import full_ai_revenue
import inbound_describe
import llm_client
import runtime_switches
import tenant_keys
from auth import assert_account_owned, require_actor_account_ids
from automation_registry import kind_family
from automations import (
    full_ai_catchup, full_ai_config, full_ai_live, full_ai_photo, full_ai_rules, full_ai_test, full_ai_turn,
)
from automations.full_ai_owner_io import OFF_SWITCH
from automations.full_ai_writers import PURPOSE as WRITER_PURPOSE
from automations._model_pick import resolve_model_and_fallback
from automations._persona import MODEL_NOTES_MAX
from automations.full_ai_chat import MODE as SHADOW
from automations.full_ai_decide import Route
from db.engine import get_session
from db.models import AccountAiConfig, AiDecision, AutomationRule, Fan, ScheduledJob
from isotime import iso_z
from llm_client import LLMCapExceeded, LLMConfigError, LLMError, LLMKeyError, chat
from permissions import require_opt_in_kind, require_opt_in_page
from vault_ai_api import assert_owner_scope

ROUTES: tuple[str, ...] = get_args(Route)
ROWS = 50
KIND = full_ai_live.KIND
OFF_TRIGGER = {"every_seconds": 300}
LIVE_TRIGGER = {**OFF_TRIGGER, "mode": full_ai_live.MODE}
NO_FANS_LIST = "No Fans list: pick an Include or Exclude list under Fans, then Save"
# A key's provider as Settings → AI keys names it (llm_client's map lacks the two Writer-only providers).
_KEY_LABELS = {"nanogpt": "NanoGPT", "openrouter": "OpenRouter", **llm_client.PROVIDER_LABELS}

router = APIRouter()
log = logging.getLogger("of-relay.full_ai_api")


async def _since(account_id: str) -> datetime:
    """Today's midnight in the report zone, as naive UTC (the rows' clock)."""
    import stats  # stats imports half the service; the zone reader is all this needs
    zone = await stats._report_zone(account_id) or timezone.utc
    midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/admin/full-ai/rules")
async def full_ai_rules_read(mode: Literal["test", "shadow", "live"] = Query("test")) -> dict[str, Any]:
    require_actor_account_ids()
    return full_ai_rules.rules(mode)


@router.get("/admin/full-ai/today")
async def full_ai_today(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    since = await _since(account_id)
    today = (AiDecision.account_id == account_id, AiDecision.mode.in_((SHADOW, full_ai_test.MODE, full_ai_live.MODE)),
             AiDecision.created_at >= since)
    async with get_session() as s:
        counts, jev_failed = dict.fromkeys(ROUTES, 0), 0
        for route, n, failed in (await s.execute(
                select(AiDecision.route, func.count(), func.count(AiDecision.jev_error))
                .where(*today).group_by(AiDecision.route))).all():
            counts[route] = n
            jev_failed += failed
        rows = (await s.execute(
            select(AiDecision, Fan.of_display_name, Fan.of_username)
            .outerjoin(Fan, and_(Fan.account_id == AiDecision.account_id, Fan.fan_id == AiDecision.fan_id))
            .where(*today)
            .order_by(AiDecision.created_at.desc(), AiDecision.id.desc())
            .limit(ROWS))).all()
    return {
        "since": iso_z(since),
        "counts": counts,
        "jev_failed": jev_failed,
        "rows": [{
            "id": d.id, "created_at": iso_z(d.created_at), "fan_id": str(d.fan_id),
            "fan_name": None if d.mode == full_ai_test.MODE else display or username or None, "route": d.route, "heat": d.heat,
            "row": d.route_row, "jev_ms": d.jev_ms, "jev_failed": d.jev_error is not None,
            "test": d.mode == full_ai_test.MODE, "live": d.mode == full_ai_live.MODE,
        } for d, display, username in rows],
    }


@router.get("/admin/full-ai/revenue")
async def full_ai_revenue_read(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    return await full_ai_revenue.revenue(account_id)


async def live_blockers(account_id: str) -> list[str]:
    """Why this Creator may not go Live now (empty = it may), read off the saved checkpoint (what a
    live Turn runs): a Fans list (D61: an include or an exclude list), a usable key for every Writer
    in the chain (the same policy as the call, `llm_client.llm_key_available`) and Jev's TypeSafe
    key (`tenant_keys.typesafe_key_for`). Reads only."""
    cfg = (await full_ai_turn.stored_config(account_id))["checkpoint"]
    out: list[str] = []
    if not full_ai_config.has_fans_list(cfg):
        out.append(NO_FANS_LIST)
    by_provider: dict[str, list[str]] = {}
    for w in cfg["writers"]:
        if (m := full_ai_config.MODELS.get(w)) is not None:
            by_provider.setdefault(m.provider, []).append(w)
    for prov, writers in sorted(by_provider.items()):
        if not await llm_client.llm_key_available(account_id, prov, WRITER_PURPOSE):
            many = len(writers) > 1
            out.append(f"No {_KEY_LABELS.get(prov, prov)} key for Writer{'s' * many} {', '.join(writers)}: add one in "
                       f"Settings → AI keys, or untick {'them' if many else 'it'} under Writers and Save")
    if not await tenant_keys.typesafe_key_for(account_id):
        out.append("No TypeSafe key (the Router)")
    return out


async def _blockers(account_id: str) -> list[str]:
    """`live_blockers`, never raising: a failed read is one blocker (Live refused, Off unaffected)."""
    try:
        return await live_blockers(account_id)
    except Exception:
        log.exception("full_ai_mode_blockers_failed account=%s", account_id)
        return ["Couldn't check the keys and the Fans list. Reload to try again"]


async def _mode(account_id: str) -> dict[str, Any]:
    async with get_session() as s:
        enabled = (await s.execute(select(func.count()).where(
            AutomationRule.account_id == str(account_id), AutomationRule.kind.in_(kind_family(KIND)),
            AutomationRule.is_enabled.is_(True)))).scalar_one()
    mode = "live" if await full_ai_live.live_rule(account_id) is not None else "shadow" if enabled else "off"
    return {"mode": mode, "off_switch": runtime_switches.on(OFF_SWITCH), "blockers": await _blockers(account_id)}


class ModeWrite(BaseModel):
    account_id: str
    mode: Literal["off", "live"]   # Shadow is not settable (owner 2026-11-15: no Shadow stage)


@router.get("/admin/full-ai/mode")
async def full_ai_mode_read(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    return await _mode(account_id)


@router.put("/admin/full-ai/mode")
async def full_ai_mode_write(body: ModeWrite) -> dict[str, Any]:
    from automation_rules_api import ensure_kind_rule   # it imports the catalog and half the routes
    aid = body.account_id
    assert_account_owned(aid)
    await require_opt_in_kind(KIND, aid)
    if body.mode == "live":
        if blockers := await _blockers(aid):
            raise HTTPException(409, "Can't go Live: " + "; ".join(blockers))
        async with get_session() as s:
            action = await ensure_kind_rule(s, aid, KIND, enable=True, trigger=LIVE_TRIGGER)
        full_ai_catchup.start(aid)     # Fans already waiting: passes on `catchup_minutes` (default 0/5/15, then 25)
    else:
        full_ai_catchup.stop(aid)
        async with get_session() as s:
            action = await ensure_kind_rule(s, aid, KIND, enable=False)
            family = kind_family(KIND)
            await s.execute(update(AutomationRule).where(
                AutomationRule.account_id == aid, AutomationRule.kind.in_(family))
                .values(trigger_json=json.dumps(OFF_TRIGGER)))
            # Hook jobs carry their rule in the payload only: cancel every pending job of the kind, so
            # Off then Live inside the reply wait never runs a reply queued before Off.
            await s.execute(update(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind.in_(family), ScheduledJob.status == "pending")
                .values(status="cancelled", last_error="rule switched off"))
    log.info("full_ai_mode_set account=%s mode=%s action=%s", aid, body.mode, action)
    return await _mode(aid)


class _TestSide(BaseModel):
    account_id: str
    # The session key's stem: no ":" (the trigger key's separator).
    pair: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    side: Literal["checkpoint", "draft"]


class TestPhotoRead(BaseModel):
    """The photo route's reply, sent back with each side's turn."""
    desc: str | None = Field(None, max_length=inbound_describe._DESC_CLIP)
    thumb: str = Field(max_length=200_000, pattern=r"^data:image/jpeg;base64,")
    outcome: str = Field(max_length=16)
    model: str | None = Field(None, max_length=64)
    ms: int | None = None


class TestTurn(_TestSide):
    n: int = Field(ge=1)
    text: str = Field("", max_length=2000)
    photo: TestPhotoRead | None = None

    @model_validator(mode="after")
    def _said_something(self):
        if not self.text and self.photo is None:
            raise ValueError("text or photo is required")
        return self


class TestPhoto(BaseModel):
    account_id: str
    image: str = Field(max_length=full_ai_photo.MAX_UPLOAD * 4 // 3 + 64)
    text: str = Field("", max_length=2000)
    # The session: a side whose dare stands (`full_ai_test.dared_of`) reads the photo with the key off.
    pair: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _conflict(row_id: int | None) -> JSONResponse:
    return JSONResponse(status_code=409, content={"row_id": row_id})


# Test Turns running now (process-local), by (account, pair, side, n): a duplicate POST of a Turn
# still running makes no paid call (Jev, Writers); it waits for the running one to finish, then is
# 409, so the client's session reload finds the stored row (a retry after a dropped response).
_turns_running: set[tuple[str, str, str, int]] = set()


@router.post("/admin/full-ai/test/turn")
async def full_ai_test_turn(body: TestTurn):
    assert_account_owned(body.account_id)
    await require_opt_in_kind("full_ai_chat", body.account_id)
    claim = (body.account_id, body.pair, body.side, body.n)
    if claim in _turns_running:         # check → add with no await between: atomic on the loop
        while claim in _turns_running:  # ends: the running Turn is bounded by turn_bound_s
            await asyncio.sleep(0.2)
        return _conflict(None)
    _turns_running.add(claim)
    try:
        facts = await full_ai_turn.load_turn_facts(
            body.account_id, body.pair, body.text, "test", side=body.side,
            photo=body.photo.model_dump() if body.photo else None)
        full_ai_test.expect_n(facts, body.n)
        res = await full_ai_turn.run_turn(facts)
    except full_ai_test.Conflict as e:
        return _conflict(e.row_id)
    except Exception:
        log.warning("full_ai_test_failed account=%s", body.account_id, exc_info=True)
        raise
    finally:
        _turns_running.discard(claim)
    d = res.decision
    out = {"row_id": res.row_id, "route": d.route, "heat": d.heat, "route_row": d.row,
           "dropped": list(d.dropped), "parts": res.parts, "writer": res.writer, "attempts": res.attempts,
           "wait_s": res.wait_s, "status": res.status, "fan_info": facts.fan_info,
           "offer": res.offer}          # 03b: Offer / tease Pick / Free item; null otherwise, on a Refusal or a drop
    if res.caption is not None:     # `caption_writer` "caption" on a PPV Turn: who wrote the caption
        out["caption"] = res.caption
    out.update({k: v for k, v in (("scene", res.scene), ("price", res.price)) if v})   # sext scene
    if res.heat_check:              # the Heat check on a sext reply (spec 06)
        out["heat_check"] = res.heat_check
    if res.dropped_reason:          # the reply chain dropped her text (empty | banned)
        out["dropped_reason"] = res.dropped_reason
    if facts.photo is not None:
        out["photo"] = facts.photo     # his photo as this side read it
    return out


# Photo descriptions running now (process-local), by (account, sha256 of the image, text): a
# duplicate POST (double click, client retry) while the first runs makes no paid call; it awaits
# the same description (or its error). Dropped when it ends: no cache after.
_photos_running: dict[tuple[str, str, str], asyncio.Task] = {}


async def _describe_photo(account_id: str, still, text: str) -> dict[str, Any]:
    """The photo route's description fields (`desc`, `outcome`, `model`, `ms`)."""
    t0 = time.perf_counter()
    try:
        desc, model = await inbound_describe.describe_upload(account_id, still, his_words=text)
        outcome = "described" if desc else "none"
    except LLMKeyError:
        raise  # server.py's 424 key notice; before LLMConfigError, which it subclasses
    except LLMCapExceeded as e:
        raise HTTPException(status_code=429, detail="Today's AI limit for this creator is reached.") from e
    except LLMConfigError:
        log.warning("full_ai_test_photo config account=%s", account_id, exc_info=True)
        desc, model, outcome = None, None, "failed"
    return {"desc": desc, "outcome": outcome, "model": model, "ms": int((time.perf_counter() - t0) * 1000)}


def _photo_done(key: tuple[str, str, str], task: asyncio.Task) -> None:
    _photos_running.pop(key, None)
    if not task.cancelled():
        task.exception()    # retrieved: no "never retrieved" warning when every caller has gone


@router.post("/admin/full-ai/test/photo")
async def full_ai_test_photo(body: TestPhoto):
    assert_account_owned(body.account_id)
    await require_opt_in_kind("full_ai_chat", body.account_id)
    try:
        still, thumb = full_ai_photo.upload_still(body.image)
    except full_ai_photo.Refused as e:
        raise HTTPException(status_code=e.status, detail=e.msg) from e
    cfg = await full_ai_turn.stored_config(body.account_id)
    out: dict[str, Any] = {"desc": None, "thumb": thumb, "outcome": "off", "model": None, "ms": None}
    on = any(cfg[side][full_ai_photo.KEY] for side in full_ai_test.SIDES)
    if not on and body.pair:
        for side in full_ai_test.SIDES:
            if full_ai_test.dared_of(await full_ai_test.session_rows(body.account_id, body.pair, side)):
                on = True
                break
    if not on:
        return out
    key = (body.account_id, hashlib.sha256(body.image.encode()).hexdigest(), body.text)
    task = _photos_running.get(key)
    if task is None:                    # get → add with no await between: atomic on the loop
        task = asyncio.ensure_future(_describe_photo(body.account_id, still, body.text))
        _photos_running[key] = task
        task.add_done_callback(lambda t: _photo_done(key, t))
    return {**out, **await asyncio.shield(task)}   # a dropped caller leaves it running for the rest


class TestSettle(_TestSide):
    row_id: int
    outcome: Literal["bought", "declined"]


_UNSETTLED = {"not_this_session": 404, "already_settled": 409, "not_a_priced_offer": 422, "already_owned": 422}


@router.post("/admin/full-ai/test/settle")
async def full_ai_test_settle(body: TestSettle):
    assert_account_owned(body.account_id)
    await require_opt_in_kind("full_ai_chat", body.account_id)
    try:
        await full_ai_test.settle(body.account_id, body.pair, body.side, body.row_id, body.outcome)
    except full_ai_test.Unsettled as e:
        content = {"detail": e.reason} | ({"outcome": e.outcome} if e.outcome else {})
        return JSONResponse(status_code=_UNSETTLED[e.reason], content=content)
    return {"row_id": body.row_id, "outcome": body.outcome}


@router.get("/admin/full-ai/test/session")
async def full_ai_test_session(account_id: str = Query(...),
                               pair: str = Query(..., min_length=1, max_length=64)) -> dict[str, Any]:
    assert_account_owned(account_id)
    return {"rows": [full_ai_test.session_row(r) for r in await full_ai_test.session_rows(account_id, pair)]}


async def _prepare_guard(account_id: str) -> None:
    assert_account_owned(account_id)
    await assert_owner_scope(account_id)


@router.post("/admin/full-ai/prepare-content")
async def prepare_content_start(payload: dict = Body(...)) -> dict[str, Any]:
    account_id = str(payload.get("account_id") or "")
    await _prepare_guard(account_id)
    return await full_ai_prepare.start(account_id)


@router.get("/admin/full-ai/prepare-content/status")
async def prepare_content_status(account_id: str = Query(...)) -> dict[str, Any]:
    await _prepare_guard(account_id)
    return full_ai_prepare.view(account_id)


class PersonaDraftBody(BaseModel):
    account_id: str
    current_text: str = Field("", max_length=MODEL_NOTES_MAX)


@router.post("/admin/full-ai/persona/draft")
async def full_ai_persona_draft(body: PersonaDraftBody) -> dict[str, Any]:
    aid = body.account_id
    assert_account_owned(aid)
    await require_opt_in_page("/full-ai-chatter", aid)
    got = await full_ai_persona.inputs(aid)
    described = await full_ai_persona.fill_gap(aid, got.used)
    if described:
        got = await full_ai_persona.inputs(aid)
    out: dict[str, Any] = {"text": "", "age": None, "city": None, "name": got.name,
                           "images_used": got.used, "images_described": described,
                           "need_describe": not got.descs, "notes": []}
    if not got.descs:
        return out
    model, _ = await resolve_model_and_fallback(aid, "full_ai_persona")
    try:
        res = await chat(
            model=model, purpose="full_ai_persona", account_id=aid, temperature=0.4,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": full_ai_persona.persona_draft_system(got.voice)},
                      {"role": "user", "content": full_ai_persona.persona_draft_user(got)}])
    except LLMKeyError:
        raise  # server.py's 424 key notice; before LLMError, which it subclasses
    except LLMCapExceeded as e:
        raise HTTPException(status_code=429, detail="Today's AI limit for this creator is reached.") from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail="The AI provider failed. Try again.") from e
    if not isinstance(res.parsed, dict):
        raise HTTPException(status_code=502, detail="Persona draft: the model returned no usable JSON.")
    draft = full_ai_persona.compose(got, res.parsed, body.current_text)
    return {**out, "text": draft.text, "age": draft.age, "city": draft.city, "notes": draft.notes}


# ── Config: checkpoint, previous, draft, rev ──────────────────────────

# The models a Writer may be (`full_ai_config._writers_error`'s rule), for the page's Writer select.
WRITER_MODELS: list[str] = full_ai_config.WRITER_MODELS


def _config_view(cfg: dict) -> dict[str, Any]:
    models = {*WRITER_MODELS, *cfg["checkpoint"].get("writers", []), *cfg["draft"].get("writers", [])}
    return {**cfg, "errors": full_ai_config.validate(cfg["draft"]), "writer_models": WRITER_MODELS,
            "writer_providers": {w: m.provider for w in sorted(models) if (m := full_ai_config.MODELS.get(w))},
            "provider_labels": _KEY_LABELS,
            "reference": full_ai_config.reference(), "limits": full_ai_config.limits()}


@router.get("/admin/full-ai/config")
async def full_ai_config_get(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    return _config_view(await full_ai_turn.stored_config(account_id))


async def _config_write(account_id: str, step: Callable[[dict | None], dict[str, Any]]
                        ) -> JSONResponse | dict[str, Any]:
    """Owner-only: `step(stored)` gives the next blob, stored only if the column still holds
    what was read (compare-and-swap, so two tabs never both win)."""
    assert_account_owned(account_id)
    await require_opt_in_kind("full_ai_chat", account_id)
    live = await full_ai_live.live_rule(account_id) is not None
    col = AccountAiConfig.full_ai_config_json
    async with get_session() as s:
        found = (await s.execute(select(col).where(AccountAiConfig.account_id == account_id))).first()
        raw = found[0] if found else None
        try:
            new = step(json.loads(raw) if raw else None)
        except full_ai_config.Invalid as e:
            return JSONResponse(status_code=422, content={"errors": e.errors})
        except full_ai_config.StaleRev as e:
            return _stale(e.rev)
        if live and not full_ai_config.has_fans_list(new["checkpoint"]):   # D61 holds while Live, not only at the flip
            return JSONResponse(status_code=409, content={
                "detail": "Live needs a Fans list: keep an include or exclude list, or set Off first."})
        blob = json.dumps(new)
        if found is None:       # no row yet: a racing insert makes this one stale
            done = await s.execute(sqlite_insert(AccountAiConfig).values(
                account_id=account_id, full_ai_config_json=blob)
                .on_conflict_do_nothing(index_elements=["account_id"]))
        else:
            done = await s.execute(update(AccountAiConfig).where(
                AccountAiConfig.account_id == account_id, col.is_(None) if raw is None else col == raw)
                .values(full_ai_config_json=blob))
    if done.rowcount != 1:
        return _stale((await full_ai_turn.stored_config(account_id))["rev"])
    return _config_view(new)


def _stale(rev: int) -> JSONResponse:
    return JSONResponse(status_code=409, content={
        "detail": "Someone saved this config meanwhile. Reload.", "rev": rev})


class ConfigDraftBody(BaseModel):
    account_id: str
    draft: dict[str, Any]
    rev: int


class ConfigCheckpointBody(BaseModel):
    account_id: str
    checkpoint: dict[str, Any]
    rev: int


class ConfigRevBody(BaseModel):
    account_id: str
    rev: int


@router.put("/admin/full-ai/config/draft")
async def full_ai_config_put_draft(body: ConfigDraftBody):
    return await _config_write(body.account_id,
                               lambda st: full_ai_config.put_draft(st, body.draft, body.rev))


@router.put("/admin/full-ai/config/checkpoint")
async def full_ai_config_put_checkpoint(body: ConfigCheckpointBody):
    return await _config_write(body.account_id,
                               lambda st: full_ai_config.put_checkpoint(st, body.checkpoint, body.rev))


@router.post("/admin/full-ai/config/save")
async def full_ai_config_save(body: ConfigRevBody):
    return await _config_write(body.account_id, lambda st: full_ai_config.save(st, body.rev))


@router.post("/admin/full-ai/config/rollback")
async def full_ai_config_rollback(body: ConfigRevBody):
    return await _config_write(body.account_id, lambda st: full_ai_config.rollback(st, body.rev))
