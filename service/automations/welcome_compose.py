from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from . import rhythm
from ._fan_notes import substitute_placeholders
from ._outbound_guard import apply_word_restriction
from ._textutil import strip_emojis
from .names import name_token, resolve_fan_name
from .pacing import (ROLE_GAP as _ROLE_GAP, ROLE_OPENER as _ROLE_OPENER,
                     ROLE_TAIL as _ROLE_TAIL)
from db.engine import get_session
from db.models import AccountAiConfig, Fan, FanProfile


log = logging.getLogger("of-relay.automation.send_welcome")


_ADJS = {
    "A": "Adoring", "B": "Brave", "C": "Cute", "D": "Dreamy", "E": "Epic", "F": "Flirty",
    "G": "Gorgeous", "H": "Handsome", "I": "Incredible", "J": "Juicy", "K": "Kind", "L": "Lovely",
    "M": "Mighty", "N": "Naughty", "O": "Original", "P": "Playful", "Q": "Quick", "R": "Radiant",
    "S": "Sexy", "T": "Tasty", "U": "Unique", "V": "Vibrant", "W": "Wild", "X": "Xtra",
    "Y": "Yummy", "Z": "Zesty",
}

_ADJS_HIM = {
    "A": "Ambitious", "B": "Bold", "C": "Cocky", "D": "Devoted", "E": "Eager",
    "F": "Fearless", "G": "Game", "H": "Hungry", "I": "Impatient", "J": "Jumpy",
    "K": "Keen", "L": "Loyal", "M": "Mighty", "N": "Needy", "O": "Obedient",
    "P": "Patient", "Q": "Quick", "R": "Ready", "S": "Solid", "T": "Tough",
    "U": "Unruly", "V": "Vicious", "W": "Willing", "X": "Xtra", "Y": "Yearning",
    "Z": "Zealous",
}
_ADJ_DEFAULT = {"her": "Flirty", "him": "Eager"}
_NAMELESS_GREET = {"her": "cutie", "him": "boy"}


def _adjs(voice: str) -> tuple[dict, str]:
    if str(voice or "").strip().lower() == "him":
        return _ADJS_HIM, _ADJ_DEFAULT["him"]
    return _ADJS, _ADJ_DEFAULT["her"]

def _clock_hours(cfg: dict) -> float:
    return rhythm.tz_hours_for(cfg.get("timezone"), cfg.get("utc_offset"))


def _model_hour(utc_offset: float | int | None) -> int:
    try:
        off = float(utc_offset)
    except (TypeError, ValueError):
        off = 0.0
    return (datetime.utcnow() + timedelta(hours=off)).hour


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


_SLOT_REPR_HOUR = {
    "morning_1": 7, "morning_2": 10, "afternoon_1": 13,
    "afternoon_2": 16, "evening": 19, "night": 22,
}


def _slot_hour(slot: str | None) -> int | None:
    return _SLOT_REPR_HOUR.get(slot or "")


def _pinned_line(cfg: dict, hour: int) -> str | None:
    pins = cfg.get("welcome_pins") or {}
    pin = pins.get(_slot_key(hour))
    if not isinstance(pin, dict):
        return None
    line = str(pin.get("line") or "").strip()
    if not line:
        return None
    old_wd = str(pin.get("weekday") or "").strip()
    cur_wd = _model_weekday(_clock_hours(cfg))
    if old_wd and old_wd.lower() != cur_wd.lower():
        def _sub(m: "re.Match") -> str:
            s = m.group(0)
            if s.isupper():
                return cur_wd.upper()
            if s.islower():
                return cur_wd.lower()
            return cur_wd
        line = re.sub(rf"\b{re.escape(old_wd)}\b", _sub, line, flags=re.IGNORECASE)
    return line


def _slot_image_id(cfg: dict, hour: int) -> int | None:
    imgs = cfg.get("time_images") or {}
    val = imgs.get(_slot_key(hour))
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None



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
        pins: dict = {}
        if getattr(cfg, "welcome_pinned_json", None):
            try:
                pins = json.loads(cfg.welcome_pinned_json) or {}
            except Exception:
                pins = {}
        return {
            "persona": cfg.persona,
            "utc_offset": cfg.utc_offset,
            "timezone": getattr(cfg, "timezone", None),
            "location": cfg.location,
            "time_activities": acts,
            "time_images": imgs,
            "welcome_pins": pins,
            "model": cfg.model,
        }


def _model_weekday(utc_offset) -> str:
    try:
        off = float(utc_offset)
    except (TypeError, ValueError):
        off = 0.0
    return (datetime.utcnow() + timedelta(hours=off)).strftime("%A")


_name_token = name_token


async def _resolve_welcome_name(account_id: str, fan_id: int, sub: dict) -> str:
    async with get_session() as s:
        prof = (await s.execute(select(FanProfile.nickname).where(
            FanProfile.account_id == str(account_id),
            FanProfile.fan_id == int(fan_id)))).scalar_one_or_none()
        fan = (await s.execute(select(
            Fan.real_name, Fan.generated_nickname, Fan.custom_nickname,
            Fan.of_display_name, Fan.home_country, Fan.home_city
        ).where(Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).first()
    row = dict(zip(("real_name", "generated_nickname", "custom_nickname",
                    "of_display_name", "home_country", "home_city"), fan or ()))
    row["generated_nickname"] = row.get("generated_nickname") or prof
    row["of_display_name"] = row.get("of_display_name") or sub.get("name")
    return _name_token(resolve_fan_name(row))



def _local_greeting(name: str, voice: str = "her") -> str:
    L = name[0].upper()
    table, default = _adjs(voice)
    return f"Hey {L}-{L}-{L}-{table.get(L, default)} {name} ! !!"


_HANDLE_WORD = re.compile(r"[A-Za-z]{3,}")


def _greet_token(sub: dict, voice: str = "her") -> str:
    target = (sub.get("name") or sub.get("username") or "").strip()
    words = _HANDLE_WORD.findall(target)
    if words:
        return max(words, key=len).lower()
    return _NAMELESS_GREET["him" if str(voice or "").strip().lower() == "him"
                           else "her"]


def _activity_bubble(cfg: dict, hour: int | None = None, *,
                     time_only: bool = False) -> list[str]:
    off = _clock_hours(cfg)
    if hour is None:
        hour = _model_hour(off)
    tod, activity = _time_activity(hour, cfg.get("time_activities") or {})
    if not activity and not time_only:
        return []
    location = (cfg.get("location") or "").strip()
    where = f" in {location}" if location else ""
    clock = f"it's {_model_weekday(off)} {tod}{where}"
    return [clock] if time_only else [f"{activity}... {clock}"]



# Never fall through to arbitrary folders (Streams/Posts would DM the wrong media).
_IMAGE_FOLDER_NAMES = ("bot", "welcome script", "welcome")


def _bot_folder_media_id(client, hour: int) -> int | None:
    try:
        lists = client.vault_lists(view="main", limit=100)
    except Exception:
        log.debug("send_welcome vault_lists failed", exc_info=True)
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
            log.debug("send_welcome vault_media failed folder=%s", folder_id, exc_info=True)
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





async def _compose_bubbles(
    *, greeting: str, cfg: dict, hour: int, skip_time_bubble: bool,
    time_only: bool, question: str, strip_emoji_on: bool,
) -> tuple[list[str], list[str], bool]:
    pin = (None if (skip_time_bubble or time_only)
           else _pinned_line(cfg, hour))
    pinned = False
    roles = [_ROLE_OPENER]
    if skip_time_bubble:
        bubbles = [greeting]
    elif pin is not None:
        bubbles = [greeting, pin]
        roles.append(_ROLE_GAP)
        pinned = True
    else:
        activity = _activity_bubble(cfg, hour, time_only=time_only)
        bubbles = [greeting, *activity]
        roles += [_ROLE_GAP] * len(activity)

    if question:
        bubbles.append(question)
        roles.append(_ROLE_TAIL)

    bubbles = [apply_word_restriction(b) for b in bubbles]
    if strip_emoji_on:
        bubbles = [strip_emojis(b) for b in bubbles]
    kept = [(b, r) for b, r in zip(bubbles, roles) if b.strip()]
    return [b for b, _ in kept], [r for _, r in kept], pinned


def message_variants(raw) -> tuple[str, ...]:
    items = raw if isinstance(raw, list) else [raw]
    return tuple(s.strip() for s in items if isinstance(s, str) and s.strip())


def _custom_message(message: str, name: str, *, strip_emoji_on: bool) -> str:
    text = apply_word_restriction(substitute_placeholders(message, None, name=name or None))
    return strip_emojis(text) if strip_emoji_on else text



