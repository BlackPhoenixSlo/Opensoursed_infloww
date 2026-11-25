from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
from isotime import parse_iso
import llm_client
import of_write
import run_slot
from ._markers import strip_asides
from ._model_wait import freed_chat
from . import rhythm
from . import _voice
from . import send_marker_decide as smd
from . import send_marker_store as smst
from .send_followup_decide import (
    _STEP_THRESHOLDS_H, Complete, Cooldown, Effect, Entry, Resume, Save, Seen, Send, Sent, Tick,
    Wait, _resolve_step_thresholds, decide,
)
from attribution import write_outbound_attribution
from audiences import contact_guard_excludes, resolve_window_hours
from automation_registry import register
from ._common import (
    apply_word_restriction, bool_knob, load_strip_emojis,
    quarantine_if_undeliverable, resolve_fan_name,
    resolve_model, send_dropping_bad_media, skip_unreachable_fan, strip_emojis,
)
from db.engine import get_session
from db.models import (
    AccountAiConfig,
    Blacklist,
    Fan,
    FanProfile,
    FollowupState,
    Message,
    SkipList,
)
from llm_client import LLMCapExceeded

log = logging.getLogger("of-relay.automation.send_followup")

_DEFAULT_MODEL = "deepseek-v4-flash"
_PURPOSE = "followup"
_TEMPERATURE = 0.9

_ELIGIBLE_MIN_SPEND_CENTS = 100  # ≥ $1 lifetime spend
_DEFAULT_FAN_LIMIT = 200

_GUARD_DEFAULT_H = 12

_STEP_USER_INSTRUCTIONS = {
    1: ("Write a short, light, flirty message: a casual question-and-tease OR a "
        "simple personal question based on their profile. Keep it 1-3 lines, "
        "conversational texting style, real emojis, no markdown. Don't be needy "
        "or mention that they haven't replied — be natural, like you just "
        "thought of them."),
    2: ("Write a more personal question-and-tease that references ONE specific "
        "detail from their profile info. Keep it 1-3 lines, flirty but genuine. "
        "Real emojis, no markdown. Don't mention the silence — just reach out "
        "naturally, like you remembered something about them."),
    3: ("This is the FINAL follow-up. Write a warm, slightly playful "
        "question-and-tease with a hint of FOMO — something new, exclusive, or "
        "that you're specifically thinking of them. Keep it 1-3 lines, real "
        "emojis, no markdown. After this you stop messaging until they reply."),
}



def _model_hour(utc_offset: float | int | None) -> int:
    try:
        off = float(utc_offset)
    except (TypeError, ValueError):
        off = 0.0
    return (datetime.utcnow() + timedelta(hours=off)).hour


def _model_clock(utc_offset: float | int | None) -> str:
    try:
        off = float(utc_offset)
    except (TypeError, ValueError):
        off = 0.0
    local = datetime.utcnow() + timedelta(hours=off)
    return local.strftime("%A, %B %d — %I:%M %p")


def _time_activity(hour: int, acts: dict) -> tuple[str, str]:
    if 5 <= hour < 9:
        return ("morning", acts.get("morning_1", ""))
    if 9 <= hour < 12:
        return ("morning", acts.get("morning_2", ""))
    if 12 <= hour < 15:
        return ("afternoon", acts.get("afternoon_1", ""))
    if 15 <= hour < 18:
        return ("afternoon", acts.get("afternoon_2", ""))
    if 18 <= hour < 21:
        return ("evening", acts.get("evening", ""))
    return ("night", acts.get("night", ""))


def _photo_index(hour: int) -> int:
    if 5 <= hour < 9:
        return 0
    if 9 <= hour < 12:
        return 1
    if 12 <= hour < 15:
        return 2
    if 15 <= hour < 18:
        return 3
    if 18 <= hour < 21:
        return 4
    return 5


_SLOT_KEYS = ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")


def _slot_key(hour: int) -> str:
    return _SLOT_KEYS[_photo_index(hour)]


def _slot_image_id(cfg: dict, hour: int) -> int | None:
    imgs = cfg.get("time_images") or {}
    val = imgs.get(_slot_key(hour))
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _compose_system(cfg: dict, tod: str, activity: str, clock: str,
                    fan_name: str, fan_bio: str) -> str:
    v = cfg.get("_voice") or _voice.HER
    persona = (cfg.get("persona")
               or "You are a warm, flirty OnlyFans creator re-engaging a fan "
                  "who has gone quiet.").strip()
    parts = [persona]
    location = (cfg.get("location") or "").strip()
    if location:
        parts.append(f"You are based in {location}.")
    if clock:
        where = f" in {location}" if location else ""
        parts.append(f"Right now it is {clock} ({tod}{where}).")
    if activity:
        parts.append(f"You are currently {activity}. "
                     f"You may reference this naturally.")
    who = []
    if fan_name:
        who.append(f"The fan's name/handle is {fan_name}.")
    if fan_bio:
        who.append(f"What you know about him: {fan_bio}")
    if who:
        parts.append(" ".join(who))
    parts.append(
        "Write ONE re-engagement DM (1-3 lines, casual texting tone, real emojis, "
        "no markdown). Use the fan's first name naturally if it's a real name. "
        "Never mention that they haven't replied or that it's been a while, and "
        "never sound desperate or needy. Output only the message text — no "
        "surrounding quotes, no preamble."
    )
    parts.append(v.live_proof)
    return "\n\n".join(parts) + v.emoji_vocab


def _compose_user(step: int, fan_name: str, silence_hours: float,
                  fan_address: str = "babe") -> str:
    name = (fan_name or "").strip() or fan_address
    header = (f"Fan first name: {name}\n"
              f"Hours of silence: ~{silence_hours:.0f}h\n"
              f"Follow-up step: {step} of 3\n\n")
    return header + _STEP_USER_INSTRUCTIONS[step]



async def _load_ai_config(account_id: str) -> dict:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
        if cfg is None:
            return {}
        acts: dict = {}
        if cfg.time_activities_json:
            try:
                acts = json.loads(cfg.time_activities_json) or {}
            except Exception:
                acts = {}
        imgs: dict = {}
        if cfg.time_images_json:
            try:
                imgs = json.loads(cfg.time_images_json) or {}
            except Exception:
                imgs = {}
        return {
            "persona": cfg.persona,
            "tz_hours": rhythm.tz_hours_for(getattr(cfg, "timezone", None),
                                            cfg.utc_offset),
            "location": cfg.location,
            "time_activities": acts,
            "time_images": imgs,
            "model": cfg.model,
            "_voice": _voice.blocks(getattr(cfg, "voice", None)),
        }




async def _load_blacklist() -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(select(Blacklist.fan_id))).all()
    return {int(r[0]) for r in rows}


async def _load_skip_list(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(SkipList.account_id == str(account_id)))).all()
    return {int(r[0]) for r in rows}


async def _load_eligible_fans(account_id: str, limit: int) -> list[dict]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id, Fan.of_display_name, Fan.real_name,
                   Fan.generated_nickname, Fan.custom_nickname,
                   Fan.home_country, Fan.home_city)
            .where(
                Fan.account_id == account_id,
                Fan.lifetime_spend_cents >= _ELIGIBLE_MIN_SPEND_CENTS,
                (Fan.total_likes.is_(None)) | (Fan.total_likes >= 1),
            )
            .order_by(Fan.lifetime_spend_cents.desc())
            .limit(limit)
        )).all()
    return [
        {"fan_id": int(r.fan_id), "name": resolve_fan_name(r)}
        for r in rows
    ]


async def _load_last_message_times(
    account_id: str, fan_ids: list[int]
) -> dict[int, dict[str, datetime | None]]:
    out: dict[int, dict[str, datetime | None]] = {
        fid: {"in": None, "out": None} for fid in fan_ids
    }
    if not fan_ids:
        return out
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.direction, func.max(Message.created_at))
            .where(
                Message.account_id == account_id,
                Message.fan_id.in_(fan_ids),
                Message.direction.in_(("in", "out")),
            )
            .group_by(Message.fan_id, Message.direction)
        )).all()
    for fid, direction, ts in rows:
        slot = out.get(int(fid))
        if slot is not None:
            slot[direction] = ts
    return out


def _fan_message_times_stmt(account_id: str, fan_id: int):
    def latest(direction: str):
        return (select(func.max(Message.created_at))
                .where(Message.account_id == account_id,
                       Message.fan_id == fan_id,
                       Message.direction == direction)
                .scalar_subquery())
    return select(latest("in"), latest("out"))


async def _load_fan_message_times(
    account_id: str, fan_id: int
) -> dict[str, datetime | None]:
    async with get_session() as s:
        last_in, last_out = (await s.execute(
            _fan_message_times_stmt(account_id, fan_id))).one()
    return {"in": last_in, "out": last_out}


async def _load_state(account_id: str) -> dict[int, Entry]:
    async with get_session() as s:
        rows = (await s.execute(
            select(FollowupState).where(FollowupState.account_id == account_id)
        )).scalars().all()
    return {int(r.fan_id): Entry.from_row(r) for r in rows}


async def _load_bios(account_id: str, fan_ids: list[int]) -> dict[int, str]:
    if not fan_ids:
        return {}
    async with get_session() as s:
        rows = (await s.execute(
            select(FanProfile.fan_id, FanProfile.short_bio, FanProfile.bullet_points).where(
                FanProfile.account_id == account_id,
                FanProfile.fan_id.in_(fan_ids),
            )
        )).all()
    out: dict[int, str] = {}
    for fid, bio, bullets in rows:
        chunk = "\n".join(p.strip() for p in (bullets, bio) if p and p.strip())
        if chunk:
            out[int(fid)] = chunk
    return out


def _entry_values(e: Entry, now: datetime) -> dict:
    return dict(
        phase=e.phase,
        cycle=e.cycle,
        silence_started_at=e.silence_started_at,
        fan_last_reply_at=e.fan_last_reply_at,
        cooldown_until=e.cooldown_until,
        messages_sent=json.dumps(e.messages_sent, default=str),
        completed=(e.phase == "completed"),
        sending_at=e.sending_at,
        sending_ctx=json.dumps(e.sending_ctx) if e.sending_ctx is not None else None,
        unconfirmed_at=e.unconfirmed_at,
        updated_at=now,
    )


async def _save_entry(account_id: str, fan_id: int, e: Entry, now: datetime) -> None:
    update = _entry_values(e, now)
    async with get_session() as s:
        await s.execute(
            sqlite_insert(FollowupState)
            .values(account_id=str(account_id), fan_id=int(fan_id), **update)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=update
            )
        )



def _keys(account_id: str, fan_id: int) -> dict:
    return {"account_id": str(account_id), "fan_id": int(fan_id)}


async def _replay_landed(account_id: str, r: FollowupState, now: datetime, *,
                         confirmed: bool = False) -> bool:
    e = Entry.from_row(r)
    step = (e.sending_ctx or {}).get("step")
    if step not in _STEP_THRESHOLDS_H:
        return False
    if not confirmed and not await smst.landed(
            account_id, r.fan_id, smd.lookup_since(e.sending_at), _PURPOSE):
        return False
    e2, _fx = decide(e, Sent(int(step), e.sending_at), _STEP_THRESHOLDS_H)
    return await smst.clear(FollowupState, _keys(account_id, r.fan_id),
                            if_sending_at=e.sending_at, **_entry_values(e2, now))


async def settle_landed(account_id: str, boot_ts: datetime, now: datetime) -> None:
    await smst.settle(
        await smst.marked_rows(FollowupState, FollowupState.account_id == str(account_id)),
        lambda r: _replay_landed(account_id, r, now), boot_ts, now)



async def marked_sends(account_id: str) -> list[dict]:
    out = []
    for r in await smst.marked_rows(FollowupState, FollowupState.account_id == str(account_id)):
        step = (Entry.from_row(r).sending_ctx or {}).get("step")
        out.append({"fan_id": int(r.fan_id), "mass_run_id": None,
                    "step": step if isinstance(step, int) else 0, "sending_at": r.sending_at,
                    "unconfirmed_at": r.unconfirmed_at, "last_error": None})
    return out


async def read_marker(account_id: str, fan_id: int, mass_run_id: int | None = None):
    return await smst.read(FollowupState, _keys(account_id, fan_id))


async def retry_clear(account_id: str, fan_id: int, mass_run_id: int | None,
                      sending_at: datetime, now: datetime) -> bool:
    return await smst.clear(FollowupState, _keys(account_id, fan_id), if_sending_at=sending_at,
                            updated_at=now)


async def dismiss_sent(account_id: str, fan_id: int, mass_run_id: int | None,
                       sending_at: datetime, now: datetime,
                       hint_message_id: int | None = None) -> bool:
    rows = await smst.marked_rows(FollowupState, FollowupState.account_id == str(account_id),
                                  FollowupState.fan_id == int(fan_id),
                                  FollowupState.sending_at == sending_at)
    if not rows or not await _replay_landed(account_id, rows[0], now, confirmed=True):
        return False
    if hint_message_id is not None:
        await smst.tag_out(account_id, fan_id, smd.lookup_since(sending_at), hint_message_id,
                           _PURPOSE)
    return True


async def attempt_saved(account_id: str, fan_id: int, mass_run_id: int | None,
                        since: datetime) -> bool:
    async with get_session() as s:
        r = await s.get(FollowupState, (str(account_id), int(fan_id)))
    try:
        sent = json.loads(r.messages_sent or "{}") if r is not None else {}
    except ValueError:
        return False
    return any(parse_iso(str(v)) == since for v in (sent.values() if isinstance(sent, dict) else ()))



# Never fall through to arbitrary folders (Streams/Posts would DM the wrong media).
_IMAGE_FOLDER_NAMES = ("bot", "welcome script", "welcome")


def _bot_folder_media_id(client, hour: int) -> int | None:
    try:
        lists = client.vault_lists(view="main", limit=100)
    except Exception:
        log.debug("send_followup vault_lists failed", exc_info=True)
        return None
    folders = lists.get("list") if isinstance(lists, dict) else lists
    by_name: dict[str, int] = {}
    for f in (folders or []):
        if isinstance(f, dict) and f.get("id") is not None:
            by_name.setdefault(str(f.get("name", "")).strip().lower(), f.get("id"))

    for nm in _IMAGE_FOLDER_NAMES:
        folder_id = by_name.get(nm)
        if folder_id is None:
            continue
        try:
            media = client.vault_media(list_id=int(folder_id), type="photo", limit=50)
        except Exception:
            log.debug("send_followup vault_media failed folder=%s", folder_id, exc_info=True)
            continue
        items = media.get("list") if isinstance(media, dict) else media
        items = [it for it in (items or []) if isinstance(it, dict) and it.get("id")]
        if not items:
            continue
        idx = min(_photo_index(hour), len(items) - 1)
        try:
            return int(items[idx]["id"])
        except (TypeError, ValueError, KeyError):
            continue
    return None



async def preview_compose(
    account_id: str, *, fan_id: int | None = None, test_name: str | None = None,
    step: int | None = None, model: str | None = None,
) -> dict:
    cfg = await _load_ai_config(account_id)
    strip_emoji_on = await load_strip_emojis(account_id)
    hour = _model_hour(cfg.get("tz_hours"))
    tod, activity = _time_activity(hour, cfg.get("time_activities") or {})
    clock = _model_clock(cfg.get("tz_hours"))

    try:
        step = int(step) if step is not None else 1
    except (TypeError, ValueError):
        step = 1
    step = min(3, max(1, step))

    name = (test_name or "").strip()
    bio = ""
    if fan_id is not None:
        async with get_session() as s:
            row = (await s.execute(
                select(Fan.of_display_name, Fan.of_username).where(
                    Fan.account_id == str(account_id),
                    Fan.fan_id == int(fan_id),
                )
            )).first()
        if row and not name:
            name = (row[0] or row[1] or "").strip()
        bio = (await _load_bios(account_id, [int(fan_id)])).get(int(fan_id), "")
    if not name:
        name = "babe"

    silence_hours = float(_STEP_THRESHOLDS_H[step])
    model = model or await resolve_model(account_id, _PURPOSE, None)
    res = await llm_client.chat(
        model=model,
        messages=[
            {"role": "system", "content": _compose_system(
                cfg, tod, activity, clock, name, bio)},
            {"role": "user", "content": _compose_user(
                step, name, silence_hours,
                (cfg.get("_voice") or _voice.HER).fan_address)},
        ],
        purpose=_PURPOSE,
        account_id=account_id,
        fan_id=int(fan_id) if fan_id is not None else 0,
        temperature=_TEMPERATURE,
    )
    text = apply_word_restriction(strip_asides(getattr(res, "content", "") or ""))
    if strip_emoji_on:
        text = strip_emojis(text)
    return {"text": text, "image": _slot_image_id(cfg, hour),
            "name": name, "slot": _slot_key(hour), "step": step}



@register("send_followup")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    dry_run = bool(payload.get("dry_run"))
    with_image = bool_knob(payload, "with_image", True)
    limit = int(payload.get("limit") or _DEFAULT_FAN_LIMIT)

    cfg = await _load_ai_config(account_id)
    strip_emoji_on = await load_strip_emojis(account_id)
    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    thresholds = _resolve_step_thresholds(payload)
    hour = _model_hour(cfg.get("tz_hours"))
    tod, activity = _time_activity(hour, cfg.get("time_activities") or {})
    clock = _model_clock(cfg.get("tz_hours"))

    now = datetime.utcnow()
    if not dry_run:
        # Send once: a nudge a dead attempt landed is saved as sent, never re-sent.
        await settle_landed(account_id, smd.BOOT_TS, now)
    state = await _load_state(account_id)

    fx: Counter = Counter()

    async def _perform(fid: int, e: Entry, effects: list[Effect]) -> Send | None:
        fx.update(effects)
        due = None
        for eff in effects:
            if isinstance(eff, Save):
                await _save_entry(account_id, fid, e, now)
            elif isinstance(eff, Resume):
                state[fid] = e
            elif isinstance(eff, Send):
                due = eff
        return due

    for fid, e in list(state.items()):
        await _perform(fid, *decide(e, Tick(now), thresholds))

    provider = llm_client.MODELS[model].provider
    if not await llm_client.llm_key_available(account_id, provider, _PURPOSE):
        return {"no_llm_key": provider, "transitioned": fx[Resume()], "followups_sent": 0}

    blacklist = await _load_blacklist()
    skip_ids = await _load_skip_list(account_id)
    eligible = [f for f in await _load_eligible_fans(account_id, limit)
                if f["fan_id"] not in blacklist and f["fan_id"] not in skip_ids]

    import audience_include as _audiences
    audience_stats: dict = {}
    _kept = set(await _audiences.filter_candidates(
        account_id, [f["fan_id"] for f in eligible], kind="send_followup",
        stats=audience_stats))
    eligible = [f for f in eligible if f["fan_id"] in _kept]
    eligible_ids = [f["fan_id"] for f in eligible]

    msg_times = await _load_last_message_times(account_id, eligible_ids)
    bios = await _load_bios(account_id, eligible_ids)

    # Nudges stamp only NudgeState, not messages, so the messages-table reads miss them; the contact guard sees them.
    guard_h = resolve_window_hours(payload.get("exclude_replied_hours"), _GUARD_DEFAULT_H)
    guard_ids: set[int] = set()
    if guard_h > 0:
        guard_ids = await contact_guard_excludes(
            account_id, outbound_hours=guard_h)

    sent = 0
    skipped_locked = 0
    skipped_cooldown = 0
    errors = 0
    cap_hit = False
    key_error = None
    image_attached = 0
    first_error: str | None = None

    def _note_error(what: str) -> None:
        nonlocal errors, first_error
        errors += 1
        if first_error is None:
            first_error = " ".join(str(what).split())[:240]

    for fan in eligible:
        fid = fan["fan_id"]
        times = msg_times.get(fid, {"in": None, "out": None})
        e, effects = decide(state.get(fid) or Entry(),
                            Seen(now, times["in"], times["out"], fid in guard_ids), thresholds)
        due = await _perform(fid, e, effects)
        if due is None:
            continue
        if await ax.fan_on_cooldown(account_id, fid):
            skipped_cooldown += 1
            continue
        # One bot message per fan per cycle: don't race the other senders.
        if not await ax.acquire_fan_lease(account_id, fid, "send_followup"):
            skipped_locked += 1
            continue
        sent_ok = False
        try:
            try:
                res = await freed_chat(
                    budget_s=rhythm.INLINE_MAX_S,
                    model=model,
                    messages=[
                        {"role": "system", "content": _compose_system(
                            cfg, tod, activity, clock,
                            fan["name"], bios.get(fid, ""))},
                        {"role": "user", "content": _compose_user(
                            due.step, fan["name"], due.silence_hours,
                            (cfg.get("_voice") or _voice.HER).fan_address)},
                    ],
                    purpose=_PURPOSE,
                    account_id=account_id,
                    fan_id=fid,
                    temperature=_TEMPERATURE,
                )
            except run_slot.SlotLost:
                raise
            except LLMCapExceeded:
                cap_hit = True
                log.warning("send_followup daily LLM cap reached account=%s — stopping",
                            account_id)
                break
            except llm_client.LLMKeyError as exc:
                key_error = llm_client.key_error_payload(exc)
                break
            except Exception as gen_exc:
                _note_error(f"generate: {gen_exc}")
                log.warning("send_followup generate failed account=%s fan=%s",
                            account_id, fid, exc_info=True)
                continue

            text = apply_word_restriction(strip_asides(getattr(res, "content", "") or ""))
            if strip_emoji_on:
                text = strip_emojis(text)
            if not text:
                _note_error("empty draft after filters")
                log.warning("send_followup empty draft account=%s fan=%s "
                            "(model returned nothing, or filters stripped it all)",
                            account_id, fid)
                continue

            # msg_times predates the loop and the generate takes minutes: re-read so a fan who just wrote goes to reply_cooldown.
            fresh = await _load_fan_message_times(account_id, fid)
            e, effects = decide(e, Seen(now, fresh["in"], fresh["out"], fid in guard_ids),
                                thresholds)
            due = await _perform(fid, e, effects)
            if due is None:
                continue

            if dry_run:
                sent += 1
                continue

            media_files: list[int] = []
            if with_image:
                mid = _slot_image_id(cfg, hour)
                if mid is None:
                    client_for_vault = await asyncio.to_thread(ax._make_client, account_id)
                    mid = await asyncio.to_thread(_bot_folder_media_id, client_for_vault, hour)
                if mid is not None:
                    media_files = [mid]

            client = await asyncio.to_thread(ax._make_client, account_id)
            try:
                # The send-once marker is committed before OF can take anything; the DM-rate wait stays outside it.
                await dm_rate.turn(account_id)
                e = replace(e, sending_at=datetime.utcnow(), sending_ctx={"step": due.step})
                await _save_entry(account_id, fid, e, now)
            except Exception as exc:
                _note_error(f"mark: {exc}")
                log.warning("send_followup mark failed account=%s fan=%s",
                            account_id, fid, exc_info=True)
                continue
            try:
                outcome = await send_dropping_bad_media(
                    client, fid, text, media_files, log=log,
                    send_purpose="gated")
                result = outcome.result
            except Exception as exc:
                _note_error(f"send: {exc}")
                unreachable = await skip_unreachable_fan(account_id, fid, exc, log=log)
                if not unreachable:
                    # A lapsed-sub fan raises on every send and state advances only on a returned send, so without this probe the same nudge re-fires every tick.
                    await quarantine_if_undeliverable(client, account_id, fid)
                # Send once: may have sent -> unconfirmed, never re-sent by a tick; surely not -> the marker goes. Write only while this attempt's mark stands.
                keys = _keys(account_id, fid)
                match smd.failure_outcome(0, 0, True, of_write._may_have_sent(exc),
                                          unreachable=unreachable):
                    case smd.UNCONFIRMED:
                        await smst.unconfirm(FollowupState, keys, e.sending_at)
                    case smd.CLEAR:
                        await smst.clear(FollowupState, keys, if_sending_at=e.sending_at)
                log.warning("send_followup send failed account=%s fan=%s",
                            account_id, fid, exc_info=True)
                continue

            if outcome.media_landed:
                image_attached += 1

            msg_id = result.get("id") if isinstance(result, dict) else None
            if msg_id:
                await write_outbound_attribution(
                    account_id=account_id,
                    fan_id=int(fid),
                    message_id=int(msg_id),
                    sent_by_employee_id=None,
                    automation_kind=_PURPOSE,
                    body=str(result.get("text") or text),
                    price_cents=0,
                    created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                    emit_live=True,
                )

            e, effects = decide(e, Sent(due.step, now), thresholds)
            await _perform(fid, e, effects)
            sent += 1
            sent_ok = True
        finally:
            # Keep the lease (let it expire) and rest the fan on a confirmed send; release only when nothing went out.
            if sent_ok:
                try:
                    await ax.start_fan_cooldown(account_id, fid)
                except Exception:
                    log.warning("send_followup cooldown set failed account=%s fan=%s",
                                account_id, fid, exc_info=True)
            else:
                await ax.release_fan_lease(account_id, fid)

    return {
        "eligible": len(eligible),
        **audience_stats,
        "transitioned": fx[Resume()],
        "followups_sent": sent,
        "state_advanced": (fx[Cooldown("reply")] + fx[Cooldown("restart")]
                           + (0 if dry_run else sent)),
        "skipped_unread": fx[Cooldown("reply")],
        "skipped_locked": skipped_locked,
        "skipped_cooldown": skipped_cooldown,
        "skipped_guard": fx[Wait()],
        "completed": fx[Complete()],
        "image_attached": image_attached,
        "errors": errors,
        "first_error": first_error,
        "cap_hit": cap_hit,
        "dry_run": dry_run,
        "model": model,
        **({"key_error": key_error} if key_error else {}),
    }

