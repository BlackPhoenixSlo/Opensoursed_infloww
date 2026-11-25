from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, NamedTuple, TypeVar

from fastapi import HTTPException

import llm_client
import media_cotag
from automations._language import norm_lang
from automations._model_pick import model_fits
from automations._persona import MODEL_NOTES_MAX, PERSONA_FACT_FIELDS
from automations._voice import VOICE_HER, VOICE_HIM, parse_voice
from llm_client import MODELS

# Per-provider daily cap upper bound on edit ($100); a stored cap above it may be echoed back unchanged so Save never 422s.
MAX_DAILY_COST_CAP_CENTS = 10_000

# Must match welcome_compose._SLOT_KEYS.
TIME_SLOTS: tuple[str, ...] = (
    "morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night",
)


def clean_text(v: Any, field: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise HTTPException(422, f"{field} must be text")
    s = v.strip()
    return s or None


def _validate_model(v: Any, field: str, allowed: set[str]) -> str | None:
    s = clean_text(v, field)
    if s is None:
        return None
    if allowed and s not in allowed:
        raise HTTPException(422, f"{field} {s!r} is not a known model ({', '.join(sorted(allowed))})")
    return s


def _validate_effort(v: Any, model: str | None) -> str | None:
    # Validated against the model being saved, not a union of providers' values.
    s = clean_text(v, "reasoning_effort")
    if s is None:
        return None
    allowed = llm_client.effort_options(model or "")
    if not allowed:
        raise HTTPException(
            422, f"model {model or '(none)'!r} takes no reasoning effort — "
                 f"leave reasoning_effort empty")
    if s not in allowed:
        raise HTTPException(
            422, f"reasoning_effort {s!r} is not valid for model "
                 f"{model or '(none)'!r} ({', '.join(allowed)})")
    # Store NULL when the pick is the model's default: clients re-send the whole config, so else an unrelated save freezes the pin into the column.
    mdl = MODELS.get(model or "")
    if mdl is not None and s == mdl.reasoning_effort:
        return None
    return s


_T = TypeVar("_T")


def _result(fn: Callable[..., _T], *args: Any) -> tuple[_T | None, HTTPException | None]:
    try:
        return fn(*args), None
    except HTTPException as e:
        return None, e


class AudiencePut(NamedTuple):
    mode_sent: bool
    mode: str | None
    list_sent: bool
    list_id: int | None
    auto_sent: bool
    auto: bool | None


class Head(NamedTuple):
    persona: str | None
    location: str | None
    notes_sent: bool
    notes: str | None
    model: str | None
    effort: str | None
    facts: dict[str, str]
    language: str | None


class PutContext(NamedTuple):
    account_id: str
    allowed: set[str]
    now: datetime
    head: Head
    audience: AudiencePut
    stored_cap: int | None = None
    # Chatter's PUT: the cap is the owner's money, a sent value is ignored.
    cap_locked: bool = False


def _head(cfg: Any, allowed: set[str]) -> Head:
    if not isinstance(cfg, dict):
        raise HTTPException(422, "config must be an object")
    persona = clean_text(cfg.get("persona"), "persona")
    location = clean_text(cfg.get("location"), "location")
    notes_sent = "model_notes" in cfg
    notes = clean_text(cfg.get("model_notes"), "model_notes")
    if notes is not None and len(notes) > MODEL_NOTES_MAX:
        raise HTTPException(422, f"model_notes must be at most {MODEL_NOTES_MAX} characters")
    model = _validate_model(cfg.get("model"), "model", allowed)
    effort = _validate_effort(cfg.get("reasoning_effort"), model)

    # Allowlist, not passthrough: unknown keys dropped so a kept key never reads as a fact in play.
    facts_raw = cfg.get("persona_facts") or {}
    if not isinstance(facts_raw, dict):
        raise HTTPException(422, "persona_facts must be an object")
    facts: dict[str, str] = {}
    for key, _label in PERSONA_FACT_FIELDS:
        val = facts_raw.get(key)
        if isinstance(val, (list, tuple)):
            val = ", ".join(str(v).strip() for v in val if str(v).strip())
        elif isinstance(val, bool) or val is None:
            val = "" if val is None else str(val)
        val = str(val).strip()
        if val:
            facts[key] = val[:240]

    lang_raw = cfg.get("language")
    language = norm_lang(lang_raw)
    if lang_raw and not language:
        raise HTTPException(422, f"language {lang_raw!r} is not a supported code")
    language = language or None
    return Head(persona, location, notes_sent, notes, model, effort, facts, language)


def clean_head(cfg: Any, allowed: set[str]) -> tuple[Head | None, HTTPException | None]:
    return _result(_head, cfg, allowed)


def clean_config_put(cfg: Any, existing: PutContext) -> tuple[dict[str, Any] | None,
                                                             HTTPException | None]:
    return _result(_clean, cfg, existing)


def _clean(cfg: Any, existing: PutContext) -> dict[str, Any]:
    head = existing.head
    language = head.language
    aud = existing.audience

    voice_raw = cfg.get("voice")
    voice = parse_voice(voice_raw)
    # Absent or "" = unchanged, never reset to the default lane; unknown value 422s (parse_voice, not norm_voice) to avoid silent wrong gender.
    voice_sent = "voice" in cfg and voice_raw not in (None, "")
    if voice_raw not in (None, "") and voice is None:
        raise HTTPException(
            422, f"voice {voice_raw!r} is not supported (expected "
                 f"{VOICE_HER!r} or {VOICE_HIM!r})")
    if language == "en":
        language = None

    tz = clean_text(cfg.get("timezone"), "timezone")
    if tz is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise HTTPException(
                422, f"timezone {tz!r} is not a known IANA zone (e.g. America/Vancouver)")

    utc_raw = cfg.get("utc_offset", 0)
    if isinstance(utc_raw, bool) or not isinstance(utc_raw, (int, float)):
        raise HTTPException(422, "utc_offset must be a whole number of hours")
    utc_offset = int(utc_raw)
    if not (-24 <= utc_offset <= 24):
        raise HTTPException(422, "utc_offset must be between -24 and 24 hours")

    # Sent-only: a rebuilt config must not reset a raised cap to the $1 default. 0 = every AI call refused.
    cap_sent = "daily_cost_cap_cents" in cfg and not existing.cap_locked
    cap = 0
    if cap_sent:
        cap_raw = cfg.get("daily_cost_cap_cents")
        if isinstance(cap_raw, bool) or not isinstance(cap_raw, (int, float)) or cap_raw < 0:
            raise HTTPException(422, "daily_cost_cap_cents must be a non-negative number")
        cap = int(cap_raw)
        if cap > MAX_DAILY_COST_CAP_CENTS and cap != existing.stored_cap:
            raise HTTPException(
                422, f"daily_cost_cap_cents must be at most {MAX_DAILY_COST_CAP_CENTS} "
                     f"(${MAX_DAILY_COST_CAP_CENTS // 100}/day)")

    # Keys deliberately not checked against MODEL_PURPOSES: a stored blob may carry a retired purpose that must round-trip.
    mbp_in = cfg.get("model_by_purpose") or {}
    if not isinstance(mbp_in, dict):
        raise HTTPException(422, "model_by_purpose must be an object")
    mbp: dict[str, str] = {}
    for purpose, mv in mbp_in.items():
        cleaned = _validate_model(mv, f"model_by_purpose.{purpose}", existing.allowed)
        if cleaned and cleaned in MODELS and not model_fits(cleaned, str(purpose)):
            raise HTTPException(422, f"model_by_purpose.{purpose} {cleaned!r} cannot "
                                     f"return JSON, which this purpose needs")
        if cleaned:
            mbp[str(purpose)] = cleaned

    acts_in = cfg.get("time_activities") or {}
    if not isinstance(acts_in, dict):
        raise HTTPException(422, "time_activities must be an object")
    acts: dict[str, str] = {}
    for slot in TIME_SLOTS:
        s = clean_text(acts_in.get(slot), f"time_activities.{slot}")
        if s:
            acts[slot] = s

    imgs_in = cfg.get("time_images") or {}
    if not isinstance(imgs_in, dict):
        raise HTTPException(422, "time_images must be an object")
    imgs: dict[str, int] = {}
    for slot in TIME_SLOTS:
        v = imgs_in.get(slot)
        if v in (None, "", 0):
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise HTTPException(422, f"time_images.{slot} must be a media id")
        try:
            imgs[slot] = int(v)
        except (TypeError, ValueError):
            raise HTTPException(422, f"time_images.{slot} must be a media id")

    # Sent-only so an older client or settings import can't clear them.
    cotag_video_sent = "cotag_tag_videos" in cfg
    cotag_user_sent = "cotag_username" in cfg
    cotag_username: str | None = None
    if cotag_user_sent:
        u = media_cotag.fold_handle(
            clean_text(cfg.get("cotag_username"), "cotag_username"))
        if u and not re.fullmatch(r"[a-z0-9._-]+", u):
            raise HTTPException(
                422, "cotag_username must be an OnlyFans handle "
                     "(letters, numbers, . _ -)")
        cotag_username = u or None

    # Empty JSON maps store NULL so senders' `if col:` fall back to their legacy pickers.
    vals = {
        "account_id": existing.account_id,
        "persona": head.persona,
        "location": head.location,
        "persona_facts_json": json.dumps(head.facts) if head.facts else None,
        "language": language,
        "timezone": tz,
        "utc_offset": utc_offset,
        "model": head.model,
        "reasoning_effort": head.effort,
        "model_by_purpose": json.dumps(mbp) if mbp else None,
        "time_activities_json": json.dumps(acts) if acts else None,
        "time_images_json": json.dumps(imgs) if imgs else None,
        "updated_at": existing.now,
    }
    if voice_sent:
        vals["voice"] = voice if voice == VOICE_HIM else None
    if cap_sent:
        vals["daily_cost_cap_cents"] = cap
    if aud.mode_sent:
        vals["audience_mode"] = None if aud.mode == "off" else aud.mode
    if aud.list_sent:
        vals["audience_list_id"] = aud.list_id
    if aud.auto_sent:
        vals["audience_auto_add"] = True if aud.auto else None
    if head.notes_sent:
        vals["model_notes"] = head.notes
    if cotag_video_sent:
        vals["cotag_tag_videos"] = True if bool(cfg.get("cotag_tag_videos")) else None
    if cotag_user_sent:
        vals["cotag_username"] = cotag_username
    return vals
