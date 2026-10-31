"""service/account_config_rules.py — the Brain PUT's rules, pure.

`clean_head(cfg, allowed)` runs the checks the route needs BEFORE the
audience branch's IO; `clean_config_put(cfg, existing)` takes that head (in
`existing`, a `PutContext`) and the rest of a `PUT /admin/account-config`
body's `config`, and gives the upsert's column values. Each returns
`(value, None)` or `(None, the 422)`, so the order of 422s and side effects is
the route's as it always was. No DB, no OF, no request: what needs them (the
audience mirror row, `now`) comes in `existing`, and the route asks OF for the
account's own handle afterwards (`account_config_api._own_handle`).

ABSENT key = unchanged: `voice`, `model_notes`, the audience and cotag keys
join the values only when sent, and `nudge_config_json` never does, so an
existing row keeps them.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, NamedTuple, TypeVar

from fastapi import HTTPException

import llm_client
import media_cotag
from automations._language import norm_lang
from automations._persona import MODEL_NOTES_MAX, PERSONA_FACT_FIELDS
from automations._voice import VOICE_HER, VOICE_HIM, parse_voice
from llm_client import MODELS

# The 6 time-of-day slots, ordered — must match welcome_compose._SLOT_KEYS.
TIME_SLOTS: tuple[str, ...] = (
    "morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night",
)


def clean_text(v: Any, field: str) -> str | None:
    """A trimmed string, or None when blank (clears the column)."""
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
    """Coerce the saved reasoning effort. NULL/"" = use the model's own default.

    Validated against THE MODEL BEING SAVED, not against a union of every
    provider\'s values: the point of the dropdown is that it cannot offer an
    account a string its provider answers 400 to, and a union would put that
    string back. Refusing here is right even though llm_client drops a
    mis-fitting stored value at call time — that drop exists for config which
    was valid when written and was outlived by a model change, not as a licence
    for the editor to write nonsense in the first place.
    """
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
    # Store NULL when the pick simply IS the model's default. Sparse-means-
    # default is already how this table treats empty maps, and here it fixes a
    # real leak: GET reports the pin for an unset account, every client re-sends
    # the whole config blob on save (they must — this endpoint replaces the
    # columns it reads), so an unrelated save from the chatter or settings tab
    # would otherwise MATERIALIZE the pin into the column. That freezes the
    # account at whatever the default was that afternoon, and a later change to
    # the model's pin silently stops reaching it.
    #
    # The trade-off, stated plainly: an operator who deliberately picks the
    # value that happens to be the default is recorded as "unset", so they will
    # follow the pin if it ever moves. That is the better failure — it keeps
    # every untouched account on one number we can change in one place.
    mdl = MODELS.get(model or "")
    if mdl is not None and s == mdl.reasoning_effort:
        return None
    return s


_T = TypeVar("_T")


def _result(fn: Callable[..., _T], *args: Any) -> tuple[_T | None, HTTPException | None]:
    """`(fn(*args), None)`, or `(None, the 422 it raised)`."""
    try:
        return fn(*args), None
    except HTTPException as e:
        return None, e


class AudiencePut(NamedTuple):
    """The PUT's resolved audience branches: which keys were SENT (absent ==
    unchanged, exactly like `voice`) and the validated values."""
    mode_sent: bool
    mode: str | None           # validated, only meaningful when mode_sent
    list_sent: bool
    list_id: int | None        # FINAL local lists.id (prev when not sent)
    auto_sent: bool
    auto: bool | None


class Head(NamedTuple):
    """The checks run before the audience branch, cleaned (`clean_head`)."""
    persona: str | None
    location: str | None
    notes_sent: bool
    notes: str | None
    model: str | None
    effort: str | None
    facts: dict[str, str]
    language: str | None


class PutContext(NamedTuple):
    """What `clean_config_put` needs besides the body: the route's own facts,
    the body's `Head` and the audience branches, their IO done."""
    account_id: str
    allowed: set[str]          # the pinnable model ids (`_model_options`)
    now: datetime
    head: Head                 # `clean_head` of the same `cfg`
    audience: AudiencePut


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

    # persona_facts — the structured creator canon pinned into every chat prompt.
    # An ALLOWLIST, not a passthrough: unknown keys are dropped rather than stored,
    # because nothing downstream would ever render them and a silently-kept key
    # reads to an operator as a fact that is in play when it is not. Values are
    # coerced to trimmed strings (a list joins to "a, b") and clipped; empty
    # values are dropped so an empty dict stores NULL == "never enriched".
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

    # language: an ISO 639-1 code from the known set; anything else (incl. "en" or
    # unset) stores NULL so the code default ("en") applies.
    lang_raw = cfg.get("language")
    language = norm_lang(lang_raw)
    if lang_raw and not language:
        raise HTTPException(422, f"language {lang_raw!r} is not a supported code")
    language = language or None
    return Head(persona, location, notes_sent, notes, model, effort, facts, language)


def clean_head(cfg: Any, allowed: set[str]) -> tuple[Head | None, HTTPException | None]:
    """`(head, None)`, or `(None, the 422)` of the checks the route runs
    before the audience branch."""
    return _result(_head, cfg, allowed)


def clean_config_put(cfg: Any, existing: PutContext) -> tuple[dict[str, Any] | None,
                                                             HTTPException | None]:
    """`(vals, None)`, the upsert's values (`account_id` included), or
    `(None, the 422)`. `vals["cotag_username"]` is the folded handle as given;
    the route turns the account's own handle into NULL."""
    return _result(_clean, cfg, existing)


def _clean(cfg: Any, existing: PutContext) -> dict[str, Any]:
    head = existing.head
    language = head.language
    # voice: whose voice this account writes in. An unknown value is a 422 rather
    # than a silent fallback — a typo'd 'hom' resolving to "her" is exactly the
    # silent-wrong-gender failure the lane exists to prevent — which is why this
    # uses `parse_voice` (None == unrecognised) and not `norm_voice` (which
    # collapses everything to "her", the right rule for reads and the wrong one
    # here).
    #
    # ⚠️ An ABSENT key means UNCHANGED, not "reset to the default lane". This
    # endpoint upserts, so a key missing from `vals` is preserved on an existing
    # row — the same treatment `nudge_config_json` gets below.
    #
    # The Brain panel now has a Creator dropdown and always sends this key, so the
    # rule is belt-and-braces for that caller. It still matters for the others:
    # The starter brains carry no `voice`, so any client rebuilding a config object
    # from the defaults posts without it, and a settings-transfer import of a
    # pre-lane backup would otherwise clear a male account back to female.
    #
    # "" IS TREATED THE SAME AS ABSENT, on purpose. A blank string is what an empty
    # form field posts, not a considered choice, and the only value it could
    # possibly mean here is the default lane — which is the one outcome that must
    # never happen by accident. Clearing a male account back to female stays
    # possible and stays EXPLICIT: post the literal "her".
    aud = existing.audience

    voice_raw = cfg.get("voice")
    voice = parse_voice(voice_raw)
    voice_sent = "voice" in cfg and voice_raw not in (None, "")
    if voice_raw not in (None, "") and voice is None:
        raise HTTPException(
            422, f"voice {voice_raw!r} is not supported (expected "
                 f"{VOICE_HER!r} or {VOICE_HIM!r})")
    if language == "en":
        language = None                      # NULL == en; keeps the column sparse

    # timezone — a LEGACY IANA zone (e.g. America/Vancouver). No longer settable
    # from the Brain, and only consulted when the account has no fixed
    # `utc_offset` (rhythm.tz_offset_for); blank clears it. Kept accepted so a
    # settings-transfer of an older export still round-trips.
    tz = clean_text(cfg.get("timezone"), "timezone")
    if tz is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise HTTPException(
                422, f"timezone {tz!r} is not a known IANA zone (e.g. America/Vancouver)")

    # utc_offset — whole hours (e.g. Vancouver −6); sane range, default 0.
    utc_raw = cfg.get("utc_offset", 0)
    if isinstance(utc_raw, bool) or not isinstance(utc_raw, (int, float)):
        raise HTTPException(422, "utc_offset must be a whole number of hours")
    utc_offset = int(utc_raw)
    if not (-24 <= utc_offset <= 24):
        raise HTTPException(422, "utc_offset must be between -24 and 24 hours")

    cap_raw = cfg.get("daily_cost_cap_cents", 100)
    if isinstance(cap_raw, bool) or not isinstance(cap_raw, (int, float)) or cap_raw < 0:
        raise HTTPException(422, "daily_cost_cap_cents must be a non-negative number")
    cap = int(cap_raw)

    # model_by_purpose: {purpose: model}; each model validated against MODELS.
    # The KEY is deliberately not checked against MODEL_PURPOSES: a stored blob
    # may carry a retired purpose, and dropping it here would silently rewrite
    # settings this endpoint was only asked to round-trip. That list is what the
    # editor OFFERS, not what this column may hold.
    mbp_in = cfg.get("model_by_purpose") or {}
    if not isinstance(mbp_in, dict):
        raise HTTPException(422, "model_by_purpose must be an object")
    mbp: dict[str, str] = {}
    for purpose, mv in mbp_in.items():
        cleaned = _validate_model(mv, f"model_by_purpose.{purpose}", existing.allowed)
        if cleaned:
            mbp[str(purpose)] = cleaned

    # time_activities: keep only the 6 known slots, each a non-empty string.
    acts_in = cfg.get("time_activities") or {}
    if not isinstance(acts_in, dict):
        raise HTTPException(422, "time_activities must be an object")
    acts: dict[str, str] = {}
    for slot in TIME_SLOTS:
        s = clean_text(acts_in.get(slot), f"time_activities.{slot}")
        if s:
            acts[slot] = s

    # time_images: keep only the 6 known slots, each a media-id int.
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

    # Co-performer tag settings (media_cotag). Sparse like the audience columns:
    # each key joins the upsert only when SENT, so an older client or a
    # pre-cotag settings-transfer import can't clear them while saving
    # something else.
    cotag_video_sent = "cotag_tag_videos" in cfg
    cotag_user_sent = "cotag_username" in cfg
    cotag_username: str | None = None
    if cotag_user_sent:
        # Folded by the module that owns the concept, so what this stores is
        # byte-identical to what media_cotag's readers would fold it to anyway.
        u = media_cotag.fold_handle(
            clean_text(cfg.get("cotag_username"), "cotag_username"))
        if u and not re.fullmatch(r"[a-z0-9._-]+", u):
            raise HTTPException(
                422, "cotag_username must be an OnlyFans handle "
                     "(letters, numbers, . _ -)")
        cotag_username = u or None

    # Empty JSON maps store as NULL ("unset") so the senders' `if col:` checks
    # fall back to their legacy pickers instead of an empty-dict no-op.
    vals = {
        "account_id": existing.account_id,
        "persona": head.persona,
        "location": head.location,
        "persona_facts_json": json.dumps(head.facts) if head.facts else None,
        "language": language,
        "timezone": tz,
        "utc_offset": utc_offset,
        "daily_cost_cap_cents": cap,
        "model": head.model,
        "reasoning_effort": head.effort,
        "model_by_purpose": json.dumps(mbp) if mbp else None,
        "time_activities_json": json.dumps(acts) if acts else None,
        "time_images_json": json.dumps(imgs) if imgs else None,
        "updated_at": existing.now,
    }
    # `voice` only joins the upsert when the caller sent a REAL value, so neither a
    # missing key nor a blank field can clear the lane while saving something else.
    # NULL == "her" keeps the column sparse.
    if voice_sent:
        vals["voice"] = voice if voice == VOICE_HIM else None
    # Audience columns join the upsert only when their key was SENT (absent ==
    # unchanged — see the route's branches). NULL == off keeps the columns sparse.
    if aud.mode_sent:
        vals["audience_mode"] = None if aud.mode == "off" else aud.mode
    if aud.list_sent:
        vals["audience_list_id"] = aud.list_id
    if aud.auto_sent:
        vals["audience_auto_add"] = True if aud.auto else None
    # Model info, same sent-only rule: only Get to know fans' Model info box edits
    # it, so a client rebuilding the brain without it can't clear the note.
    if head.notes_sent:
        vals["model_notes"] = head.notes
    # Cotag columns, same sent-only rule. NULL ≡ OFF keeps the checkbox column
    # sparse — True is the only stored opt-in.
    if cotag_video_sent:
        vals["cotag_tag_videos"] = True if bool(cfg.get("cotag_tag_videos")) else None
    if cotag_user_sent:
        vals["cotag_username"] = cotag_username
    # nudge_config_json is intentionally absent → preserved on existing rows.
    return vals
