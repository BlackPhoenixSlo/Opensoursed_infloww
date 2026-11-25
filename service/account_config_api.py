from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import audience_include
import llm_client
import media_cotag
from auth import assert_account_owned, get_request_user
from chatters import get_request_chatter
from automations._common import (
    DEFAULT_MODEL, MODEL_PURPOSES, PURPOSE_DEFAULT_MODELS, purpose_default)
from automations._persona import (MODEL_NOTES_TEMPLATE, PERSONA_FACT_FIELDS,
                                  PERSONA_FACTS_OPERATOR_ONLY)
from brain_defaults import brain_defaults
from db.engine import get_session
from db.models import AccountAiConfig, List as ListModel
from llm_client import MODELS
from sqlalchemy import select

log = logging.getLogger("of-relay.account_config_api")

router = APIRouter()

from account_config_rules import TIME_SLOTS, clean_text  # noqa: E402
import account_config_rules as rules  # noqa: E402
from automations._language import KNOWN_LANGS, LANG_DISPLAY, norm_lang  # noqa: E402
from automations._voice import (  # noqa: E402
    VOICE_HER, VOICE_HIM, fact_labels, fact_placeholders, norm_voice)
LANGUAGES: tuple[dict, ...] = tuple(
    {"code": c, "label": LANG_DISPLAY.get(c, c)} for c in KNOWN_LANGS
)



def _model_options() -> list[str]:
    """The LLM model ids the account may pick."""
    return list(MODELS.keys())


# Laned: labels come from `_voice.fact_labels`; a female label on a male account makes the operator write female canon into his prompt.
def _persona_fact_meta(voice: object) -> list[dict[str, Any]]:
    # Slots the enrich pass may not propose: what she will and won't do on camera is a business decision.
    operator_only = PERSONA_FACTS_OPERATOR_ONLY
    # Placeholders are indexed, not .get: falling through to the other lane's text reached his boxes with her copy.
    labels, placeholders = fact_labels(voice), fact_placeholders(voice)
    return [{"key": k, "label": labels.get(k, label),
             "operator_only": k in operator_only, "placeholder": placeholders[k]}
            for k, label in PERSONA_FACT_FIELDS]


def _parse_obj(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def _effective_effort(row: AccountAiConfig | None) -> str:
    if row is None:
        return ""
    # Show the effort the account actually runs, not blank: a blank box invites saving a downgrade nobody chose.
    saved = (getattr(row, "reasoning_effort", None) or "").strip()
    if saved:
        return saved
    mdl = MODELS.get(row.model or DEFAULT_MODEL)
    return mdl.reasoning_effort if mdl else ""


def _serialize(row: AccountAiConfig | None) -> dict[str, Any]:
    return {
        "persona": row.persona if row else None,
        "location": row.location if row else None,
        "persona_facts": (_parse_obj(row.persona_facts_json) if row else {}),
        "model_notes": getattr(row, "model_notes", None) if row else None,
        "language": (norm_lang(row.language) or "en") if row else "en",
        "voice": (norm_voice(row.voice) if row else VOICE_HER),
        "timezone": row.timezone if row else None,
        "utc_offset": row.utc_offset if row else 0,
        "daily_cost_cap_cents": row.daily_cost_cap_cents if row else 100,
        "model": row.model if row else None,
        "model_by_purpose": _parse_obj(row.model_by_purpose) if row else {},
        "reasoning_effort": _effective_effort(row),
        "time_activities": _parse_obj(row.time_activities_json) if row else {},
        "time_images": _parse_obj(row.time_images_json) if row else {},
        "audience_mode": audience_include.norm_audience_mode(
            getattr(row, "audience_mode", None) if row else None),
        "audience_list_id": getattr(row, "audience_list_id", None) if row else None,
        "audience_auto_add": bool(getattr(row, "audience_auto_add", None)) if row else False,
        # Co-tag: NULL video rule = OFF (collab-account opt-in); NULL username = "No co-creator tag".
        "cotag_tag_videos": bool(getattr(row, "cotag_tag_videos", None)) if row else False,
        "cotag_username": getattr(row, "cotag_username", None) if row else None,
    }


def _own_handle(account_id: str) -> str:
    import automation_executor as ax

    try:
        me = ax._make_client(account_id).me() or {}
    except Exception:
        log.warning("cotag: /users/me failed (account=%s) — saving the handle "
                    "as given", account_id, exc_info=True)
        return ""
    return media_cotag.fold_handle(me.get("username"))


async def _audience_status(account_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    list_id = cfg.get("audience_list_id")
    out: dict[str, Any] = {
        "mode": cfg.get("audience_mode") or "off",
        "auto_add": bool(cfg.get("audience_auto_add")),
        "list_id": list_id,
        "of_list_id": None,
        "list_name": None,
        "member_count": 0,
        "synced_at": None,
        "snapshot_age_s": None,
        "truncated": False,
        "paused": False,
        "baseline_ready": False,
        "pending_first_sync": False,
        "healthy": True,
        "effective_mode": cfg.get("audience_mode") or "off",
    }
    if out["mode"] == "off":
        return out
    pol = await audience_include.automation_audience(account_id)
    out.update(effective_mode=pol.mode, healthy=pol.healthy, paused=pol.paused,
               pending_first_sync=(pol.reason == "pending_first_sync"),
               reason=pol.reason, member_count=len(pol.member_ids),
               of_list_id=pol.of_list_id)
    async with get_session() as s:
        row = await s.get(ListModel, int(list_id)) if list_id is not None else None
        if row is not None and row.account_id == str(account_id):
            meta = audience_include._parse_sync_meta(row.sync_meta_json)
            out.update(list_name=row.name,
                       synced_at=row.synced_at.isoformat() if row.synced_at else None,
                       truncated=bool(meta.get("truncated")),
                       baseline_ready=bool(meta.get("baseline_ready")))
            if row.synced_at is not None:
                out["snapshot_age_s"] = max(
                    0, int((datetime.utcnow() - row.synced_at).total_seconds()))
    return out


@router.get("/admin/account-config")
async def get_account_config(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        row = await s.get(AccountAiConfig, account_id)
    cfg = _serialize(row)
    audience = await _audience_status(account_id, cfg)
    cfg["audience_of_list_id"] = audience.get("of_list_id")
    brains = {v: brain_defaults(v) for v in (VOICE_HER, VOICE_HIM)}
    canon = {v: _persona_fact_meta(v) for v in (VOICE_HER, VOICE_HIM)}
    return {
        "account_id": account_id,
        "config": cfg,
        # The starter brain (no images), RESOLVED for this account's lane. The
        # editor seeds a blank account from this and the "Reset to defaults"
        # button refills from it — so every model has a worked example to show,
        # not an empty form.
        #
        # It served the Ava capture unconditionally, three lines under a
        # `_serialize` that already reports the voice correctly. Reset is the
        # sharp end: BrainPanel's `defaultsWithImages` preserves `voice` across a
        # refill but copies the persona and the six time-of-day lines wholesale,
        # so one click turned a male account into a 22-year-old woman with the
        # right value still in the voice dropdown. 8000186 was seeded that way
        # and ran her yoga/beach/cat lines under a red-pill-dom persona.
        "defaults": brains[cfg["voice"]],
        # Both lanes, because "Reset to defaults" must follow the CREATOR DROPDOWN,
        # not the stored column. The dropdown writes local form state; the column
        # only moves on Save. So switching to Male and pressing Reset — the exact
        # flow the male starter brain was built for — refilled with Ava, and the
        # panel had no way to know better: the lane had already been resolved away
        # server-side. The singular above stays for the readers that have no
        # dropdown (the blank-account seed, the chat drawer's canon list), which
        # genuinely want the stored lane.
        # Both lanes: Reset follows the Creator dropdown (local state until Save), not the stored column.
        "defaults_by_voice": brains,
        "slots": list(TIME_SLOTS),
        "model_options": _model_options(),
        "default_model": DEFAULT_MODEL,
        "effort_options": llm_client.effort_options_by_model(),
        "purposes": list(MODEL_PURPOSES),
        # RESOLVED, not raw: resolve_model falls back to DEFAULT_MODEL when a pinned id left llm_client.MODELS; the editor shows what the next call runs.
        "purpose_defaults": {
            p: await purpose_default(account_id, p) for p in PURPOSE_DEFAULT_MODELS
        },
        "languages": list(LANGUAGES),
        "persona_fact_fields": canon[cfg["voice"]],
        "persona_fact_fields_by_voice": canon,
        "model_notes_template": MODEL_NOTES_TEMPLATE,
        "audience": audience,
        # Outside `config`, so a Save never echoes it.
        "ai_spend_today": await llm_client.spend_today(account_id),
    }


class _ConfigBody(BaseModel):
    account_id: str
    config: dict


async def _audience_put_branches(cfg: dict, account_id: str) -> rules.AudiencePut:
    mode_raw = cfg.get("audience_mode")
    mode_sent = "audience_mode" in cfg and mode_raw not in (None, "")
    mode: str | None = None
    if mode_sent:
        mode = str(mode_raw).strip().lower()
        if mode not in audience_include.AUDIENCE_MODES:
            raise HTTPException(
                422, f"audience_mode {mode_raw!r} is not one of off/shadow/enforce")
    list_sent = "audience_of_list_id" in cfg
    of_list_id: int | None = None
    if list_sent and cfg.get("audience_of_list_id") not in (None, "", 0):
        try:
            of_list_id = int(cfg.get("audience_of_list_id"))
        except (TypeError, ValueError):
            raise HTTPException(422, "audience_of_list_id must be an OF list id")
    auto_sent = "audience_auto_add" in cfg
    auto = bool(cfg.get("audience_auto_add")) if auto_sent else None

    async with get_session() as s:
        prev = await s.get(AccountAiConfig, account_id)
    prev_mode = audience_include.norm_audience_mode(
        getattr(prev, "audience_mode", None) if prev else None)
    prev_list = getattr(prev, "audience_list_id", None) if prev else None
    final_mode = mode if mode_sent else prev_mode

    if mode_sent and mode == "enforce" and prev_mode not in ("shadow", "enforce"):
        if not cfg.get("audience_enforce_override"):
            raise HTTPException(
                422, "audience_mode: shadow before enforce — run shadow first "
                     "(or send audience_enforce_override=true; it is logged)")
        log.warning("audience DIRECT-TO-ENFORCE override account=%s (no shadow week)",
                    account_id)

    list_id = prev_list
    if list_sent:
        if of_list_id is None:
            list_id = None
        else:
            name = clean_text(cfg.get("audience_list_name"),
                               "audience_list_name") or f"OF list {of_list_id}"
            async with get_session() as s:
                mirror = (await s.execute(
                    select(ListModel).where(
                        ListModel.account_id == str(account_id),
                        ListModel.kind == audience_include.AUDIENCE_INCLUDE_KIND,
                        ListModel.of_list_id == of_list_id,
                    )
                )).scalars().first()
                if mirror is None:
                    mirror = ListModel(
                        account_id=str(account_id), of_list_id=of_list_id,
                        name=name, kind=audience_include.AUDIENCE_INCLUDE_KIND,
                        is_system=True)
                    s.add(mirror)
                    await s.flush()
                elif name and mirror.name != name:
                    mirror.name = name
                list_id = int(mirror.id)
    if final_mode != "off" and list_id is None:
        raise HTTPException(
            422, "audience_mode needs a folder — pick one (audience_of_list_id) "
                 "before leaving off")
    return rules.AudiencePut(mode_sent, mode, list_sent, list_id, auto_sent, auto)


@router.put("/admin/account-config")
async def put_account_config(body: _ConfigBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    cfg = body.config
    allowed = set(_model_options())
    head, err = rules.clean_head(cfg, allowed)
    if err is not None:
        raise err
    # Checks above run first: the audience branch reads (and may create) the mirror list row, so a refused body touches nothing.
    aud = await _audience_put_branches(cfg, body.account_id)
    async with get_session() as s:
        stored_cap = await s.scalar(select(AccountAiConfig.daily_cost_cap_cents).where(
            AccountAiConfig.account_id == body.account_id))
    # A Chatter may save the brain but never move the owner's daily AI spend cap.
    cap_locked = get_request_user() is None and get_request_chatter() is not None
    vals, err = rules.clean_config_put(
        cfg, rules.PutContext(body.account_id, allowed, datetime.utcnow(), head, aud,
                              stored_cap, cap_locked))
    if err is not None:
        raise err
    # An account is never on its own tagged-friend list: tagging itself is NULL (asks OF, so only after every check passed).
    own = vals.get("cotag_username")
    if own and own == await asyncio.to_thread(_own_handle, body.account_id):
        vals["cotag_username"] = None
    set_ = {k: v for k, v in vals.items() if k != "account_id"}
    async with get_session() as s:
        await s.execute(
            sqlite_insert(AccountAiConfig)
            .values(**vals)
            .on_conflict_do_update(index_elements=["account_id"], set_=set_)
        )
        row = await s.get(AccountAiConfig, body.account_id)

    # media_cotag caches its Brain read 60s and the tag id 1h; reset only this account (the panel sends these keys on every save).
    if vals.keys() & {"cotag_tag_videos", "cotag_username"}:
        media_cotag.forget_account_cfg(body.account_id)

    log.info("account_config_saved account=%s model=%s slots=%d imgs=%d",
             body.account_id, vals["model"],
             len(json.loads(vals["time_activities_json"] or "{}")),
             len(json.loads(vals["time_images_json"] or "{}")))
    out_cfg = _serialize(row)
    audience = await _audience_status(body.account_id, out_cfg)
    out_cfg["audience_of_list_id"] = audience.get("of_list_id")
    return {"account_id": body.account_id, "config": out_cfg,
            "audience": audience}
