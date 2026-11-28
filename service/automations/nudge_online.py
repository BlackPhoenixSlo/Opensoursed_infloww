from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from audiences import lacks_reason
import automation_executor as ax
from automation_registry import kind_family, register
from db.engine import get_session
from db.models import (
    AccountAiConfig, AutomationRule, Blacklist, Fan, FanLease, Message, NudgeState,
    SkipList, Transaction, WelcomeSent,
)
from side_effect_gate import live_check, live_check_fan, live_check_gated, live_check_ungranted
from . import welcome_compose
from ._fan_notes import substitute_placeholders
from ._knobs import bool_knob

log = logging.getLogger("of-relay.automation.nudge_online")

KIND = "nudge_online"


_DEFAULT_NUDGE_CONFIG: dict = {
    "enabled": True,
    "nudge_line_text": True,
    "nudge_line_image": True,
    "repeat_mode": "new",
    "delay_minutes": 4,
    "jitter_minutes": 3,
    "gap_minutes": 5,
    "min_hours_between_nudges": 12,
    "max_per_tick": 25,
    "max_online_scan": 200,
    "online_recent_minutes": 5,
    "quiet_hours": [0, 7],
    "require_welcomed": True,
    "welcome_grace_hours": 1,
    "active_convo_hours": 6,
    "max_no_reply": 3,
    "min_lifetime_spend_cents": None,
    "max_lifetime_spend_cents": None,
    "recent_spend_days": 30,
    "min_recent_spend_cents": None,
    "max_recent_spend_cents": None,
    "slots": {
        "default": {
            "morning_1": {"text": [
                "morning sleepyhead {name} ☀️ you're up early 👀",
                "mmm {name} caught you first thing 😏 coffee w me?",
                "good morning {name} 💋 dreamt about you",
                "look who's up early 👀 morning {name}",
                "hii {name} 🌞 you + me + coffee? perfect start",
                "{name} 😘 早 you're online before me almost!",
            ], "image": []},
            "morning_2": {"text": [
                "heyy {name} 🌸 busy morning? thinking of you",
                "{name} you're online 👀 make my morning?",
                "mid-morning check-in {name} 😏 miss me yet?",
                "hi {name} 💕 sneaking on before lunch?",
                "{name} 🌼 perfect timing, was just thinking about you",
                "good late-morning {name} 😘 come say hi",
            ], "image": []},
            "afternoon_1": {"text": [
                "afternoon {name} 😘 break time? come keep me company",
                "hey you 👀 {name} sneaking on midday? naughty",
                "{name} 💕 lunch break? spend it with me 😏",
                "caught you {name} 😏 afternoon trouble already?",
                "hii {name} ☀️ how's your day going babe",
                "{name} 👀 online at the perfect moment again",
            ], "image": []},
            "afternoon_2": {"text": [
                "{name} 💕 perfect timing, was getting bored…",
                "caught you {name} 😏 what are you up to rn",
                "heyy {name} 👀 afternoon slump? let me fix that",
                "{name} 😘 you're online… dangerous combo",
                "mmm {name} 💋 come distract me from work",
                "hi {name} 🌅 winding down? me too soon",
            ], "image": []},
            "evening": {"text": [
                "evening {name} 🍷 finally relaxing? me too… alone 😉",
                "heyy {name} 👀 online tonight? been waiting for you",
                "{name} 💋 come unwind with me, had you on my mind",
                "good evening {name} 😏 the fun part of the day",
                "{name} 🌆 done with the day? come play",
                "mmm {name} 💕 perfect time, was hoping you'd pop on",
            ], "image": []},
            "night": {"text": [
                "up late {name}? 👀😏 can't sleep either…",
                "mmm {name} it's late 🌙 thinking naughty thoughts of you",
                "{name} 💕 just you and me online rn… what are you wearing",
                "still up {name}? 😈 i like the company",
                "late night {name} 🌙 my favorite time… and you're here",
                "{name} 👀 can't sleep? let's keep each other up 😏",
            ], "image": []},
        },
        "weekend": {
            "evening": {"text": [
                "happy friday {name} 🍷🔥 plans tonight? or me 😏",
                "weekend {name} 💋 you online means trouble… i like it",
                "{name} 🎉 weekend vibes, come celebrate with me",
            ], "image": []},
            "night": {"text": [
                "saturday night {name} 🌙 still up? come play 😈",
                "weekend night {name} 👀 no work tomorrow… let's misbehave",
            ], "image": []},
        },
        "friday": {
            "afternoon_2": {"text": [
                "friday feeling {name}? 😏 clocking off w me?",
                "almost weekend {name} 🍷 come start it early",
            ], "image": []},
        },
    },
}



async def _load_nudge_config(account_id: str) -> dict:
    async with get_session() as s:
        cfg_row = await s.get(AccountAiConfig, str(account_id))
    merged = json.loads(json.dumps(_DEFAULT_NUDGE_CONFIG))
    utc_offset = 0
    time_images: dict = {}
    if cfg_row is not None:
        utc_offset = cfg_row.utc_offset or 0
        if cfg_row.time_images_json:
            try:
                time_images = json.loads(cfg_row.time_images_json) or {}
            except Exception:
                time_images = {}
        if cfg_row.nudge_config_json:
            try:
                user = json.loads(cfg_row.nudge_config_json) or {}
                if isinstance(user, dict):
                    merged.update(user)
            except Exception:
                log.warning("bad_nudge_config_json account=%s", account_id, exc_info=True)
    merged["utc_offset"] = utc_offset
    merged["time_images"] = time_images
    return merged



def _in_quiet_hours(cfg: dict) -> bool:
    qh = cfg.get("quiet_hours")
    if not isinstance(qh, (list, tuple)) or len(qh) != 2:
        return False
    try:
        start, end = int(qh[0]), int(qh[1])
    except (TypeError, ValueError):
        return False
    if start == end:
        return False
    hour = welcome_compose._model_hour(cfg.get("utc_offset") or 0)
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _spend_bound(v) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


async def _spend_gate_reason(
    s, account_id: str, fan_id: int, fan, cfg: dict, now: datetime,
) -> str | None:
    life = int(getattr(fan, "lifetime_spend_cents", 0) or 0) if fan is not None else 0
    lo, hi = _spend_bound(cfg.get("min_lifetime_spend_cents")), _spend_bound(cfg.get("max_lifetime_spend_cents"))
    if lo is not None and life < lo:
        return "spend_below_min"
    if hi is not None and life > hi:
        return "spend_above_max"

    rlo, rhi = _spend_bound(cfg.get("min_recent_spend_cents")), _spend_bound(cfg.get("max_recent_spend_cents"))
    if rlo is not None or rhi is not None:
        days = _spend_bound(cfg.get("recent_spend_days")) or 30
        since = now - timedelta(days=int(days))
        recent = int((await s.execute(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.account_id == str(account_id),
                Transaction.fan_id == int(fan_id),
                Transaction.occurred_at >= since))).scalar_one() or 0)
        if rlo is not None and recent < rlo:
            return "recent_spend_below_min"
        if rhi is not None and recent > rhi:
            return "recent_spend_above_max"
    return None


async def _welcome_on(s, account_id: str) -> bool:
    return (await s.execute(select(AutomationRule.id).where(
        AutomationRule.account_id == str(account_id),
        AutomationRule.kind.in_(kind_family("send_welcome")),
        AutomationRule.is_enabled.is_(True)).limit(1))).first() is not None


async def _gate_skip_reason(
    account_id: str, fan_id: int, cfg: dict, now: datetime,
    *, fan_obj: dict | None = None, at_fire: bool = False,
) -> str | None:
    async with get_session() as s:
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
        if fan is not None and fan.is_bot:
            return "is_bot"
        if await s.get(Blacklist, int(fan_id)) is not None:
            return "blacklist"
        if await s.get(SkipList, (str(account_id), int(fan_id))) is not None:
            return "skiplist"

        spend_reason = await _spend_gate_reason(s, account_id, fan_id, fan, cfg, now)
        if spend_reason:
            return spend_reason

        if cfg.get("require_welcomed", True) and await _welcome_on(s, account_id):
            ws = await s.get(WelcomeSent, (str(account_id), int(fan_id)))
            if ws is None:
                return "not_welcomed"
            if ws.sent_at and (now - ws.sent_at) < timedelta(
                    hours=cfg.get("welcome_grace_hours", 1)):
                return "welcome_recent"

        lease = await s.get(FanLease, (str(account_id), int(fan_id)))
        if lease is not None and lease.leased_until > now:
            return "active_lease"

        acv = timedelta(hours=cfg.get("active_convo_hours", 6))
        last_out = (await s.execute(select(func.max(Message.created_at)).where(
            Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.direction == "out"))).scalar_one_or_none()
        last_in = (await s.execute(select(func.max(Message.created_at)).where(
            Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.direction == "in"))).scalar_one_or_none()
        if last_out is not None and (now - last_out) < acv:
            return "recent_outbound"
        if (last_in is not None and (now - last_in) < acv
                and (last_out is None or last_in > last_out)):
            return "unanswered_inbound"

        st = await s.get(NudgeState, (str(account_id), int(fan_id)))
        if st is not None:
            if st.last_nudged_at and (now - st.last_nudged_at) < timedelta(
                    hours=cfg.get("min_hours_between_nudges", 12)):
                return "reengagement_cap"
            if (st.no_reply_streak or 0) >= cfg.get("max_no_reply", 3):
                replied = (last_in is not None and st.last_nudged_at is not None
                           and last_in > st.last_nudged_at)
                if not replied:
                    return "no_reply_backoff"

    if not at_fire and isinstance(fan_obj, dict) and fan_obj.get("isMutedNotifications"):
        return "muted"
    if _in_quiet_hours(cfg):
        return "quiet_hours"
    return None



_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _pick_pool(slots: dict, slot: str, weekday_name: str) -> dict:
    wd = (weekday_name or "").lower()
    is_weekend = wd in ("saturday", "sunday")
    entries = [b[slot] for b in (slots.get(k) for k in (wd, "weekend" if is_weekend else "weekday", "default"))
               if isinstance(b, dict) and isinstance(b.get(slot), dict)]
    text = next((e["text"] for e in entries if e.get("text")), None)
    image = next((e["image"] for e in entries if e.get("image")), [])
    return {"text": text or ["hey {name} 👀 saw you pop online"], "image": image}


def _choose_idx(st, fan_id: int, pool_len: int, repeat_mode: str) -> int:
    if pool_len <= 0:
        return 0
    if st is None or st.last_slot is None or st.last_variation_idx is None:
        return int(fan_id) % pool_len
    if repeat_mode == "same":
        return min(int(st.last_variation_idx), pool_len - 1)
    return (int(st.last_variation_idx) + 1) % pool_len


def _image_idx(st, fan_id: int, n: int, repeat_mode: str) -> int:
    base = int(fan_id) % n
    if repeat_mode == "same" or st is None:
        return base
    return (base + int(getattr(st, "nudge_count", 0) or 0)) % n


class _SampleFan:
    of_display_name = "Jack"
    of_username = "jack"
    real_name = "Jack"
    is_name_real = True
    home_city = "Ljubljana"
    his_age = "31"
    occupation = "chef"
    hobbies = "trail running"
    pets = '[{"kind": "dog", "name": "Rex"}]'

    def __getattr__(self, _n):
        return None


def _slot_media(cfg: dict, pool: dict, hour: int, idx: int) -> list[int]:
    imgs = pool.get("image") or []
    if imgs:
        return [int(imgs[idx % len(imgs)])]
    one = welcome_compose._slot_image_id(cfg, hour)
    return [one] if one is not None else []


async def _compose_messages(
    account_id: str, fan_id: int | None, cfg: dict, fan_obj: dict | None, st,
    *, hour: int | None = None, weekday: str | None = None, randomize: bool = False,
) -> tuple[list[dict], str]:
    off = cfg.get("utc_offset") or 0
    h = (int(hour) if hour is not None else welcome_compose._model_hour(off)) % 24
    slot = welcome_compose._slot_key(h)
    weekday = weekday or welcome_compose._model_weekday(off)
    if slot == "night" and h < 5:
        weekday = _DAYS[(_DAYS.index(weekday.lower()) - 1) % 7] if weekday.lower() in _DAYS else weekday

    if fan_id is not None:
        async with get_session() as s:
            fan = await s.get(Fan, (str(account_id), int(fan_id)))
        name = await welcome_compose._resolve_welcome_name(account_id, int(fan_id), fan_obj or {})
        seed = int(fan_id)
    else:
        fan = _SampleFan()
        name = "Jack"
        seed = 0

    pool = _pick_pool(cfg.get("slots") or {}, slot, weekday)
    texts = pool.get("text") or []
    if not texts:
        nidx = 0
    elif randomize:
        nidx = random.randrange(len(texts))
    else:
        nidx = _choose_idx(st, seed, len(texts), cfg.get("repeat_mode", "new"))
    out: list[dict] = []

    text = ""
    if cfg.get("nudge_line_text", True) and texts:
        text = substitute_placeholders(texts[nidx], fan, name=name)
    imgs = pool.get("image") or []
    if not imgs or len(imgs) == len(texts):
        iidx = nidx
    elif randomize:
        iidx = random.randrange(len(imgs))
    else:
        iidx = _image_idx(st, seed, len(imgs), cfg.get("repeat_mode", "new"))
    media = _slot_media(cfg, pool, h, iidx) if cfg.get("nudge_line_image", True) else []
    if text or media:
        out.append({"kind": "nudge", "text": text, "media": media, "idx": nidx})

    return out, slot


async def preview_compose(
    account_id: str, cfg: dict, *, fan_id: int | None = None, hour: int | None = None,
    weekday: str | None = None,
) -> dict:
    msgs, slot = await _compose_messages(account_id, fan_id, cfg, None, None,
                                         hour=hour, weekday=weekday, randomize=True)
    name = "Jack"
    if fan_id is not None:
        name = await welcome_compose._resolve_welcome_name(
            account_id, int(fan_id), {"id": int(fan_id)}) or "(no name)"
    return {"slot": slot, "name": name,
            "messages": [{"kind": m["kind"], "text": m["text"], "media": m["media"]} for m in msgs]}



async def _account_warmed(account_id: str) -> bool:
    async with get_session() as s:
        row = (await s.execute(
            select(NudgeState.fan_id).where(NudgeState.account_id == str(account_id)).limit(1)
        )).first()
    return row is not None


async def _upsert_last_seen(account_id: str, fan_ids: list[int], now: datetime) -> None:
    if not fan_ids:
        return
    async with get_session() as s:
        for fid in fan_ids:
            await s.execute(
                sqlite_insert(NudgeState)
                .values(account_id=str(account_id), fan_id=int(fid),
                        last_seen_online_at=now, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_={"last_seen_online_at": now, "updated_at": now})
            )


async def _load_states(account_id: str, fan_ids: list[int]) -> dict[int, NudgeState]:
    if not fan_ids:
        return {}
    async with get_session() as s:
        rows = (await s.execute(
            select(NudgeState).where(
                NudgeState.account_id == str(account_id),
                NudgeState.fan_id.in_([int(x) for x in fan_ids]))
        )).scalars().all()
    return {int(r.fan_id): r for r in rows}


async def _set_pending(account_id: str, fan_id: int, job_id: int, now: datetime) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(NudgeState)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    pending_job_id=int(job_id), last_seen_online_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"pending_job_id": int(job_id), "updated_at": now})
        )



@register(KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    cfg = await _load_nudge_config(account_id)
    if not cfg.get("enabled", True):
        return {"enabled": False, "online": 0, "enqueued": 0}

    limit = int(payload.get("limit") or cfg.get("max_online_scan") or 200)
    with_image = bool_knob(payload, "with_image",
                           bool_knob(cfg, "with_image", True))

    test_fan = payload.get("test_fan")
    if test_fan is not None:
        try:
            fid = int(test_fan)
        except (TypeError, ValueError):
            return {"test_fan": test_fan, "enqueued": 0, "skipped": "bad_test_fan"}
        if reason := live_check_fan(account_id, KIND, fid):
            return {"test_fan": fid, "enqueued": 0, "reason": reason}
        now = datetime.utcnow()
        force = bool(payload.get("test_force"))
        await _upsert_last_seen(account_id, [fid], now)
        if not force:
            reason = await _gate_skip_reason(account_id, fid, cfg, now, at_fire=False)
            if reason:
                return {"test_fan": fid, "enqueued": 0, "skipped": reason}
        delay = int(cfg.get("delay_minutes", 4))
        jitter = int(cfg.get("jitter_minutes", 3))
        jit = random.randint(0, jitter * 60) if jitter > 0 else 0
        run_at = now + timedelta(minutes=delay, seconds=jit)
        job_id = await ax.enqueue_job(
            account_id, "nudge_online_fire",
            payload={"fan_id": fid, "with_image": bool(with_image), "test_force": force},
            run_at=run_at)
        await _set_pending(account_id, fid, job_id, now)
        return {"test_fan": fid, "enqueued": 1, "job_id": job_id}

    if reason := live_check_ungranted(account_id, KIND):
        return {"online": 0, "enqueued": 0, "reason": reason}
    gated = live_check_gated(account_id, KIND)
    client = await asyncio.to_thread(ax._make_client, account_id)
    try:
        online = await asyncio.to_thread(lambda: client.iter_online_subscribers(max_fans=limit))
    except Exception as e:
        if reason := lacks_reason(e):
            return {"online": 0, "enqueued": 0, "reason": reason}
        raise

    online_objs: dict[int, dict] = {}
    for f in (online or []):
        if not isinstance(f, dict):
            continue
        try:
            fid = int(f.get("id"))
        except (TypeError, ValueError):
            continue
        if not (gated and live_check(account_id, KIND, frozenset({str(fid)}))):
            online_objs.setdefault(fid, f)
    online_ids = list(online_objs.keys())
    now = datetime.utcnow()

    if not await _account_warmed(account_id):
        if online_ids:
            await _upsert_last_seen(account_id, online_ids, now)
        return {"warmup": True, "online": len(online_ids),
                "seeded": len(online_ids), "enqueued": 0}

    states = await _load_states(account_id, online_ids)
    gap = timedelta(minutes=cfg.get("gap_minutes", 5))
    newly = [
        fid for fid in online_ids
        if (st := states.get(fid)) is None
        or st.last_seen_online_at is None
        or (now - st.last_seen_online_at) > gap
    ]

    import audience_include as _audiences
    audience_stats: dict = {}
    newly = await _audiences.filter_candidates(
        account_id, newly, kind="nudge_online_fire", stats=audience_stats)

    max_per = int(cfg.get("max_per_tick", 25))
    handled = newly[:max_per]
    overflow = set(newly[max_per:])
    refresh = [fid for fid in online_ids if fid not in overflow]
    await _upsert_last_seen(account_id, refresh, now)

    delay = int(cfg.get("delay_minutes", 4))
    jitter = int(cfg.get("jitter_minutes", 3))
    enqueued = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}

    for fid in handled:
        st = states.get(fid)
        if st is not None and st.pending_job_id is not None:
            skipped += 1
            skip_reasons["pending"] = skip_reasons.get("pending", 0) + 1
            continue
        reason = await _gate_skip_reason(
            account_id, fid, cfg, now, fan_obj=online_objs.get(fid), at_fire=False)
        if reason:
            skipped += 1
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        jit = random.randint(0, jitter * 60) if jitter > 0 else 0
        run_at = now + timedelta(minutes=delay, seconds=jit)
        job_id = await ax.enqueue_job(
            account_id, "nudge_online_fire",
            payload={"fan_id": int(fid), "with_image": bool(with_image)},
            run_at=run_at)
        await _set_pending(account_id, fid, job_id, now)
        enqueued += 1

    return {
        "online": len(online_ids),
        "newly_online": len(newly),
        "handled": len(handled),
        "deferred": len(overflow),
        "enqueued": enqueued,
        "skipped": skipped,
        "skip_reasons": skip_reasons,
        **audience_stats,
    }
