from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import dm_rate
import run_slot
import llm_client
from ._persona import compose_persona
from . import _language
from . import _voice
import inbound_describe
from attribution import write_outbound_attribution
from audiences import LIST_INCOMPLETE, AudienceRefusal, lacks_reason
from automation_registry import register
from db.engine import get_session
from db.models import (
    AccountAiConfig, AutoreplyState, Blacklist, Fan, Message, SkipList, Transaction,
)
from llm_client import LLMCapExceeded, LLMConfigError
from ._prompt_rules import (
    BIO_CONSISTENCY_GUARDRAIL,
    NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL,
    STYLE_3LINE, STYLE_MAX_BUBBLES,
)
from ._nonnative import NONNATIVE_OUTPUTS, NONNATIVE_REGISTER
from ._typing_hold import (
    hold_with_typing, load_typing_indicator, load_typing_wpm, typing_delay_seconds,
)
from ._typos import apply_typo_throttle
from ._style_flags import (
    load_nonnative_flags, load_painful_texting_flag, load_spacing_flags,
    load_strip_emojis, load_style_flags, load_typo_flags, load_voice_blocks,
)
from ._skiplist import load_hard_skip_ids, load_promo_spam_ids, should_skip_muted_creator
from .names import resolve_fan_name
from ._model_pick import resolve_model
from ._send_failure import skip_unreachable_fan
from ._wordfilter import (
    banned_hit_summary, load_banned_words,
)
from ._clock import clock_block, clock_line, load_clock_tz
from automations._outbound import finalize_draft
from automations._model_wait import freed_chat
from automations.rhythm import INLINE_MAX_S
from ._bubbles import _history_text, _strip_html
from . import _reply_shape
from .welcome_chatter_for_info import _is_info_complete

log = logging.getLogger("of-relay.automation.autoreply")

_PURPOSE = "autoreply"
_DEFAULT_LIMIT = 200
_DEFAULT_MAX_SENDS = 25
_TEMPERATURE = 0.95
_HISTORY_TAIL = 16
_MSG_CLIP = 300
_REPLY_MAX_CHARS = 600


def _defaults() -> dict:
    return {
        "enabled": False,
        "silence_min_minutes": 24,
        "silence_max_minutes": 1115,
        "step_in_max_minutes": 0,
        "max_nudges": 1,
        "min_gap_minutes": 5,
        "last_n_messages": _HISTORY_TAIL,
        "quiet_hours_json": None,
        "info_not_required": True,
        "folders_enabled": True,
        "list_ids": [],
        "folder_max_spend_cents": None,
        "new_fans_enabled": False,
        "new_fan_hours": 72,
        "new_fan_max_spend_cents": 1_000,
        "describe_photos": False,
        "skip_photo_only": False,
    }


def _step_in_minutes(cfg: dict, fan_id: int, inbound_at: datetime) -> int:
    lo = int(cfg["silence_min_minutes"])
    hi = min(int(cfg.get("step_in_max_minutes") or 0),
             int(cfg["silence_max_minutes"]) - 1)
    if hi <= lo:
        return lo
    key = inbound_at.replace(microsecond=0).isoformat()
    return random.Random(f"autoreply:{int(fan_id)}:{key}").randint(lo, hi)


_FOLDER_TTL_S = 300
_folder_cache: dict[tuple[str, tuple[int, ...]], tuple[float, frozenset]] = {}
_folder_failed: dict[tuple[str, tuple[int, ...]], float] = {}
_folder_partial: set[tuple[str, tuple[int, ...]]] = set()


def _folder_key(account_id: str, list_ids) -> tuple[str, tuple[int, ...]]:
    return (str(account_id), tuple(sorted({int(x) for x in list_ids})))


class FolderPeek(NamedTuple):
    read_age_s: float | None
    members: frozenset | None
    failed_age_s: float | None
    partial: bool = False


def peek_folder(account_id: str, list_ids) -> FolderPeek:
    key, now = _folder_key(account_id, list_ids), time.monotonic()
    hit, failed = _folder_cache.get(key), _folder_failed.get(key)
    if hit is not None and failed is not None and (failed <= hit[0] or now - hit[0] < _FOLDER_TTL_S):
        failed = None
    return FolderPeek(None if hit is None else now - hit[0], None if hit is None else hit[1],
                      None if failed is None else now - failed, hit is not None and key in _folder_partial)


def _folder_ids(cfg: dict) -> tuple[int, ...]:
    out: set[int] = set()
    for x in cfg.get("list_ids") or []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(out))


# A failed folder read returns None so the caller replies to nobody; it never widens to every fan.
async def _folder_members(account_id: str, client, list_ids: tuple[int, ...]) -> frozenset | None:
    key = _folder_key(account_id, list_ids)
    hit = _folder_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < _FOLDER_TTL_S:
        return hit[1]
    from audience_include import _crawl_list_ids_blocking
    members: set[int] = set()
    partial = False
    for lid in list_ids:
        try:
            ids, truncated = await asyncio.to_thread(_crawl_list_ids_blocking, client, lid)
        except Exception as e:
            log.warning("autoreply folder read failed account=%s list=%s: %s",
                        account_id, lid, (str(e).splitlines() or [type(e).__name__])[0][:120])
            _folder_failed[key] = time.monotonic()
            lack = lacks_reason(e)
            if lack or getattr(client, "platform_list_page", None):
                raise AudienceRefusal(lack or LIST_INCOMPLETE) from e
            return None
        if truncated and getattr(client, "platform_list_page", None):
            log.warning("autoreply folder %s on account=%s read incomplete — replying to nobody", lid, account_id)
            _folder_failed[key] = time.monotonic()
            raise AudienceRefusal(LIST_INCOMPLETE)
        if truncated:
            log.warning("autoreply folder %s on account=%s hit the paging backstop "
                        "— replying to the members read so far", lid, account_id)
            partial = True
        members |= ids
    out = frozenset(members)
    _folder_cache[key] = (time.monotonic(), out)
    (_folder_partial.add if partial else _folder_partial.discard)(key)
    _folder_failed.pop(key, None)
    return out


async def _load_config(account_id: str) -> dict | None:
    async with get_session() as s:
        row = await s.get(AccountAiConfig, str(account_id))
    stored: dict = {}
    if row is not None and row.autoreply_config_json:
        try:
            stored = json.loads(row.autoreply_config_json) or {}
        except Exception:
            log.warning("bad_autoreply_config account=%s", account_id, exc_info=True)
            stored = {}
    cfg = {**_defaults(), **stored}
    if not cfg.get("enabled"):
        return None
    cfg["_utc_offset"] = int(getattr(row, "utc_offset", 0) or 0) if row else 0
    return cfg


def _in_quiet_hours(cfg: dict, now: datetime) -> bool:
    qh = cfg.get("quiet_hours_json")
    if not qh or not isinstance(qh, (list, tuple)) or len(qh) != 2:
        return False
    start, end = int(qh[0]), int(qh[1])
    if start == end:
        return False
    hour = int((now + timedelta(hours=cfg.get("_utc_offset", 0))).hour)
    return start <= hour < end if start < end else (hour >= start or hour < end)


_STYLE_VARIANTS = (
    "answer him directly, then a light tease.",
    "short flirty reply, NO question.",
    "warm + playful, like you've been thinking of him.",
    "vibe sexual? keep it going — one suggestive line, still NO pics/PPV.",
    "two TINY texts on separate lines. 0-1 emoji.",
)


_PHOTO_SEEN = (
    "HE SENT A PHOTO — the [he sent: …] note in the chat is what's in it. React to "
    "it like you're looking at it, in your own voice.\n\n")
_PHOTO_UNSEEN = (
    "HE SENT A PHOTO you can't make out — [he sent a photo] in the chat. Never say "
    "or imply what's in it. If he wrote something, answer that. If it's just the "
    "photo, react warmly and naturally anyway: a playful guess said AS a guess, or a "
    "flirty question about it, is fine.\n\n")


def _fan_facts(f: Fan, v: "_voice.VoiceBlocks" = _voice.HER) -> str:
    facts = []
    nm = resolve_fan_name(f)
    if nm:
        facts.append(f"name: {nm.split('/')[0][:40]}")
    # `likes` is boobs/ass only: on a male account it would assert a body preference the creator lacks
    likes = "" if v.is_male else ("boobs" if f.likes_boobs
                                 else ("ass" if f.likes_ass else ""))
    for label, val in (("age", f.his_age), ("city", f.home_city),
                       ("country", f.home_country), ("job", f.occupation),
                       ("hobbies", f.hobbies), ("recent", f.recent_events),
                       ("likes", likes)):
        if val:
            facts.append(f"{label}: {str(val).strip()[:80]}")
    return "\n".join(f"- {x}" for x in facts) if facts else "- (not much on file)"


def _build_messages(persona: str, f: Fan, history: list[tuple[str, str]],
                    style: str, style_on: bool = False,
                    nonnative_on: bool = False,
                    painful_on: bool = True,
                    lang: str = "en",
                    clock: str = "",
                    v: "_voice.VoiceBlocks" = _voice.HER,
                    photo: str = "") -> list[dict]:
    facts_block = _fan_facts(f, v)
    convo = "\n".join(f"{'FAN' if d == 'in' else 'YOU'}: {b}" for d, b in history if b)

    directive = f"THIS MESSAGE — {style}"
    hard_rules = (
        "HARD RULES:\n"
        "- NEVER offer or hint at PPV, pics, or anything paid — this is "
        "purely conversation.\n"
        "- quietly make him feel like the only one. you KNOW him: never "
        "re-ask name/age/job, use it.\n"
        "- never apologize for the delay, never needy.\n"
        "- match the recent vibe: sexual stays suggestive, casual stays casual.\n"
        "- SHORT: lowercase, u/ur, 0-1 emoji, never reuse a line or emoji from "
        "this chat, no paragraphs.\n"
        f"{NO_NARRATION_RULE}"
    )
    photo_block = (_PHOTO_SEEN if photo == "seen"
                   else _PHOTO_UNSEEN if photo == "unseen" else "")

    system = (
        f"{persona}\n"
        "A fan messaged you — reply to his last message like you just got back "
        "to your phone. 100% human, never a bot.\n\n"
        f"{v.painful_texting + chr(10) + chr(10) if painful_on else ''}"
        f"{clock_block(clock)}"
        f"{photo_block}"
        f"{directive}\n\n"
        f"{hard_rules}\n"
        f"{ONPLATFORM_GUARDRAIL}\n\n"
        f"{v.live_proof}\n\n"
        f"{BIO_CONSISTENCY_GUARDRAIL}\n\n"
        f"{v.humanizer + chr(10) + chr(10) if style_on else v.emoji_vocab}"
        f"{NONNATIVE_REGISTER + chr(10) + chr(10) if nonnative_on else ''}"
        "Your reply is ONLY the message text — no JSON, quotes, or metadata."
        f"{_language.output_language_directive(lang)}"
    )
    user = (
        f"What you know about him:\n{facts_block}\n\n"
        f"Recent conversation (oldest→newest):\n{convo}\n\n"
        "Reply to his last message now, in THIS MESSAGE's style."
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


async def _candidates(account_id: str, cfg: dict, now: datetime) -> list[tuple[Fan, datetime]]:
    sil_max = int(cfg["silence_max_minutes"])
    horizon = now - timedelta(minutes=sil_max)

    async with get_session() as s:
        bl = {int(r[0]) for r in (await s.execute(select(Blacklist.fan_id))).all()}
        rows = (await s.execute(
            select(Message.fan_id, Message.direction, Message.created_at)
            .where(Message.account_id == str(account_id),
                   Message.is_unsent.is_(False),
                   Message.created_at >= horizon)
            .order_by(Message.fan_id, Message.created_at.desc(), Message.message_id.desc())
        )).all()
    last: dict[int, tuple[str, datetime]] = {}
    for fid, direction, ts in rows:
        fid = int(fid)
        if fid not in last:
            last[fid] = (direction, ts)
    waiting: dict[int, datetime] = {}
    for fid, (direction, ts) in last.items():
        if direction != "in" or ts is None or fid in bl:
            continue
        wait_min = (now - ts).total_seconds() / 60.0
        if _step_in_minutes(cfg, fid, ts) <= wait_min <= sil_max:
            waiting[fid] = ts
    if not waiting:
        return []

    async with get_session() as s:
        frows = (await s.execute(
            select(Fan).where(
                Fan.account_id == str(account_id),
                Fan.fan_id.in_(list(waiting.keys())),
            )
        )).scalars().all()
    out: list[tuple[Fan, datetime]] = []
    for f in frows:
        if f.automation_paused_until and f.automation_paused_until > now:
            continue
        if not cfg.get("info_not_required") and not _is_info_complete(f):
            continue
        out.append((f, waiting[int(f.fan_id)]))
    return out


async def _first_seen(account_id: str, fans: list[Fan]) -> dict[int, datetime]:
    ids = [int(f.fan_id) for f in fans]
    out: dict[int, datetime] = {int(f.fan_id): f.subscribed_at for f in fans if f.subscribed_at}

    def _keep(fid, at):
        if at is not None and (fid not in out or at < out[fid]):
            out[fid] = at
    async with get_session() as s:
        for fid, at in (await s.execute(
            select(Message.fan_id, func.min(Message.created_at))
            .where(Message.account_id == str(account_id), Message.fan_id.in_(ids))
            .group_by(Message.fan_id)
        )).all():
            _keep(int(fid), at)
        for fid, at in (await s.execute(
            select(Transaction.fan_id, func.min(Transaction.occurred_at))
            .where(Transaction.account_id == str(account_id),
                   Transaction.fan_id.in_(ids),
                   Transaction.kind.in_(("subscription", "rebill")))
            .group_by(Transaction.fan_id)
        )).all():
            _keep(int(fid), at)
    return out


async def _audience(account_id: str, cfg: dict, cands: list, now: datetime):
    stats: dict = {}
    client = None
    refused: str | None = None
    if not cands:
        return cands, stats, client, refused
    spend = {int(f.fan_id): int(f.lifetime_spend_cents or 0) for f, _ in cands}
    keep: set[int] = set()

    if cfg.get("new_fans_enabled"):
        cut = now - timedelta(hours=int(cfg.get("new_fan_hours") or 0))
        cap = int(cfg.get("new_fan_max_spend_cents") or 0)
        firsts = await _first_seen(account_id, [f for f, _ in cands])
        keep |= {fid for fid, at in firsts.items()
                 if at >= cut and spend.get(fid, 0) < cap}

    if cfg.get("folders_enabled"):
        cap = cfg.get("folder_max_spend_cents")
        pool = {fid for fid in spend
                if fid not in keep and (cap is None or spend[fid] < int(cap))}
        folders = _folder_ids(cfg)
        if pool and folders:
            members = None
            try:
                client = await asyncio.to_thread(ax._make_client, account_id)
                members = await _folder_members(account_id, client, folders)
            except AudienceRefusal as e:
                refused = stats["folder_error"] = e.reason
            except Exception:
                log.warning("autoreply client init failed account=%s", account_id,
                            exc_info=True)
            if members is None:
                stats.setdefault("folder_error", "read")
                pool = set()
            else:
                pool &= members
        keep |= pool

    kept = [(f, t) for (f, t) in cands if int(f.fan_id) in keep]
    stats["skipped_audience"] = len(cands) - len(kept)
    return kept, stats, client, refused


async def _load_state(account_id: str, fan_id: int) -> AutoreplyState | None:
    async with get_session() as s:
        return await s.get(AutoreplyState, (str(account_id), int(fan_id)))


async def _save_state(account_id: str, fan_id: int, *, spell_inbound_at,
                      nudges_sent: int, last_nudge_at) -> None:
    now = datetime.utcnow()
    vals = dict(account_id=str(account_id), fan_id=int(fan_id),
                spell_inbound_at=spell_inbound_at, nudges_sent=int(nudges_sent),
                last_nudge_at=last_nudge_at, updated_at=now)
    async with get_session() as s:
        await s.execute(
            sqlite_insert(AutoreplyState).values(**vals)
            .on_conflict_do_update(index_elements=["account_id", "fan_id"], set_={
                "spell_inbound_at": spell_inbound_at, "nudges_sent": int(nudges_sent),
                "last_nudge_at": last_nudge_at, "updated_at": now})
        )


async def _history(account_id: str, fan_id: int, tail: int) -> list[list]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.direction, Message.body, Message.media_count,
                   Message.image_desc, Message.message_id)
            .where(Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                   Message.is_unsent.is_(False))
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(tail)
        )).all()
    return [[d, _strip_html(b)[:_MSG_CLIP], int(mc or 0), desc, int(mid)]
            for d, b, mc, desc, mid in reversed(rows)]


def _waiting_turn(rows: list[list]) -> list[list]:
    run: list[list] = []
    for r in reversed(rows):
        if r[0] != "in":
            break
        run.append(r)
    return run[::-1]


def _transcript(rows: list[list]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for d, text, media, desc, _mid in rows:
        line = _history_text(d, text, desc)
        if d == "in" and media and not desc:
            line = f"{line} [he sent a photo]" if line else "[he sent a photo]"
        out.append((d, line))
    return out


async def _fan_still_waiting(account_id: str, fan_id: int, inbound_at) -> bool:
    async with get_session() as s:
        row = (await s.execute(
            select(Message.message_id).where(
                Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                Message.direction == "out", Message.is_unsent.is_(False),
                Message.created_at > inbound_at).limit(1)
        )).first()
    return row is None


# autoreply ignores skip_list except this reason: the 7d undeliverable pause expires and a dead fan would be re-generated and re-failed.
async def _load_unreachable_ids(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(SkipList.account_id == str(account_id),
                                          SkipList.reason == "unreachable")
        )).all()
    return {int(r[0]) for r in rows}


@register("autoreply")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    cfg = await _load_config(account_id)
    if cfg is None:
        return {"enabled": False, "candidates": 0, "sent": 0}
    now = datetime.utcnow()
    if _in_quiet_hours(cfg, now):
        return {"enabled": True, "quiet_hours": True, "candidates": 0, "sent": 0}

    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    provider = llm_client.MODELS[model].provider
    if not await llm_client.llm_key_available(account_id, provider, _PURPOSE):
        log.debug("autoreply skipped account=%s — no %s key", account_id, provider)
        return {"enabled": True, "no_llm_key": provider, "candidates": 0, "sent": 0}
    dry_run = bool(payload.get("dry_run"))
    only = payload.get("only_fan_ids") or payload.get("test_fan")
    only_set = ({int(only)} if isinstance(only, int)
                else {int(x) for x in only} if only else None)
    limit = int(payload.get("limit") or _DEFAULT_LIMIT)
    max_sends = int(payload.get("max_sends") or _DEFAULT_MAX_SENDS)
    tail = int(cfg.get("last_n_messages") or _HISTORY_TAIL)
    max_nudges = int(cfg["max_nudges"])
    reply_gap = timedelta(minutes=max(int(cfg["min_gap_minutes"]),
                                      int(cfg["silence_min_minutes"])))

    cands = await _candidates(account_id, cfg, now)
    if only_set is not None:
        cands = [(f, t) for (f, t) in cands if int(f.fan_id) in only_set]

    cands, folder_stats, client, refused = await _audience(account_id, cfg, cands, now)

    import audience_include as _audiences
    audience_stats: dict = {}
    _kept = set(await _audiences.filter_candidates(
        account_id, [int(f.fan_id) for (f, _) in cands], kind="autoreply",
        stats=audience_stats))
    from automations import full_ai_owner_io
    _claimed, claimed_stats = await full_ai_owner_io.stand_down(
        account_id, [int(f.fan_id) for (f, _) in cands if int(f.fan_id) in _kept], lane="autoreply",
        client=client)
    cands = [(f, t) for (f, t) in cands if int(f.fan_id) in _kept and int(f.fan_id) not in _claimed][:limit]
    if not cands:
        return {"enabled": True, "candidates": 0, "sent": 0, **folder_stats,
                **audience_stats, **claimed_stats, **({"reason": refused} if refused else {})}

    typing_wpm = await load_typing_wpm(account_id)
    typing_indicator = await load_typing_indicator(account_id)
    style_on = (await load_style_flags(account_id))[_PURPOSE]
    account_lang = await _language.load_account_language(account_id)
    voice_blocks = await load_voice_blocks(account_id)
    typo_on = (await load_typo_flags(account_id))[_PURPOSE]
    nonnative_on = (await load_nonnative_flags(account_id))[_PURPOSE]
    spacing_on = (await load_spacing_flags(account_id))[_PURPOSE]
    painful_on = await load_painful_texting_flag(account_id)
    strip_emoji_on = await load_strip_emojis(account_id)
    max_bubbles = STYLE_MAX_BUBBLES if style_on else 2
    style_pool = _STYLE_VARIANTS + ((STYLE_3LINE,) if style_on else ())

    hard_skip = await load_hard_skip_ids(account_id)
    promo_spam = await load_promo_spam_ids(account_id)
    unreachable = await _load_unreachable_ids(account_id)

    persona = await _load_persona(account_id)
    clock_tz = await load_clock_tz(account_id)
    banned_words, banned_mode = await load_banned_words(account_id)
    describe_on = bool(cfg.get("describe_photos"))
    skip_photo_only = bool(cfg.get("skip_photo_only"))

    sent = skipped_cap = skipped_raced = errors = 0
    skipped_restricted = 0
    skipped_unreachable = 0
    skipped_banned = 0
    skipped_spam = 0
    skipped_cooldown = 0
    skipped_locked = 0
    skipped_photo_only = 0
    photos_described = 0
    key_error = None

    for f, inbound_at in cands:
        if sent >= max_sends:
            break
        fid = int(f.fan_id)
        if fid in hard_skip or should_skip_muted_creator(f):
            skipped_restricted += 1
            continue
        if fid in unreachable:
            skipped_unreachable += 1
            continue
        if fid in promo_spam:
            skipped_spam += 1
            continue

        # reply_gap holds across messages; the spell anchor dedupes the same waiting message.
        st = await _load_state(account_id, fid)
        if st is not None and st.last_nudge_at and (now - st.last_nudge_at) < reply_gap:
            skipped_cap += 1
            continue
        # Per-message dedup: don't cover the SAME waiting message twice (a new fan
        # message → new anchor → fresh spell, so it can be covered after the gap).
        spell_anchor = inbound_at
        nudges = int(st.nudges_sent or 0) if (st is not None and st.spell_inbound_at == spell_anchor) else 0
        if nudges >= max_nudges:
            skipped_cap += 1
            continue

        if not await _fan_still_waiting(account_id, fid, inbound_at):
            skipped_raced += 1
            continue

        # Cross-engine mutex before any generation: a reply drawn without the lease may be thrown away.
        if await ax.fan_on_cooldown(account_id, fid):
            skipped_cooldown += 1
            continue
        if not await ax.acquire_fan_lease(account_id, fid, _PURPOSE):
            skipped_locked += 1
            continue

        # Never sets a cooldown (must not freeze siblings): a confirmed send keeps the lease to expire by TTL, anything else releases it.
        sent_ok = False
        try:
            rows = await _history(account_id, fid, tail)
            waiting = _waiting_turn(rows)
            photo_rows = [r for r in waiting if r[2] > 0]
            photo_only = bool(photo_rows) and not any(r[1] for r in waiting)
            if photo_only and skip_photo_only:
                skipped_photo_only += 1
                continue
            fan_lang = _language.resolve_language(account_lang,
                                                  getattr(f, "language", None))

            if client is None:
                try:
                    client = await asyncio.to_thread(ax._make_client, account_id)
                except Exception:
                    log.warning("autoreply client init failed account=%s", account_id,
                                exc_info=True)
                    break

            todo = next((r for r in reversed(photo_rows) if not r[3]), None)
            if describe_on and todo is not None:
                try:
                    todo[3] = await inbound_describe.describe_photo(
                        account_id, todo[4], client,
                        his_words=" ".join(r[1] for r in waiting if r[1]))
                    photos_described += bool(todo[3])
                except LLMConfigError as e:
                    # hard stop for the rest of the run: no DeepInfra key
                    describe_on = False
                    if isinstance(e, llm_client.LLMKeyError):
                        key_error = llm_client.key_error_payload(e)
                    log.info("autoreply photo describe off for this run account=%s: %s",
                             account_id, e)
                except LLMCapExceeded:
                    log.warning("autoreply LLM cap reached account=%s — stopping", account_id)
                    break
                except Exception:
                    log.warning("autoreply photo describe failed account=%s fan=%s",
                                account_id, fid, exc_info=True)
            photo = ("" if not photo_rows
                     else "seen" if any(r[3] for r in photo_rows) else "unseen")
            history = _transcript(rows)

            style = random.choice(style_pool)
            msgs = _build_messages(persona, f, history, style, style_on=style_on,
                                   nonnative_on=nonnative_on, lang=fan_lang,
                                   painful_on=painful_on, clock=clock_line(clock_tz),
                                   v=voice_blocks, photo=photo)
            try:
                res = await freed_chat(
                    budget_s=INLINE_MAX_S, model=model, messages=msgs, purpose=_PURPOSE,
                    account_id=account_id, fan_id=fid, temperature=_TEMPERATURE)
            except run_slot.SlotLost:
                raise
            except LLMCapExceeded:
                log.warning("autoreply LLM cap reached account=%s — stopping", account_id)
                break
            except llm_client.LLMKeyError as e:
                key_error = llm_client.key_error_payload(e)
                break
            except Exception:
                errors += 1
                log.warning("autoreply generate failed account=%s fan=%s", account_id, fid,
                            exc_info=True)
                continue

            raw = (res.content or "").strip()
            raw, _leak = await finalize_draft(
                raw, account_id=account_id, fan_id=fid, purpose=_PURPOSE,
                strip_emoji=strip_emoji_on, v=voice_blocks)
            name_protect = [n for n in (f.real_name, f.generated_nickname,
                                        f.of_display_name) if n]
            shaped = _reply_shape.shape_parts(raw, _reply_shape.ShapeCtx(
                seed_id=f.fan_id, max_bubbles=max_bubbles, max_chars=_REPLY_MAX_CHARS,
                lang=None, echo_of=None, style_on=style_on,
                recent_out=[b for d, b in history if d == "out"], allow_empty=False,
                banned_words=banned_words, banned_mode=banned_mode,
                nonnative_on=nonnative_on, spacing_on=spacing_on, name_protect=name_protect))
            if shaped.dropped_reason == "banned":
                skipped_banned += 1
                log.warning("autoreply BLOCKED reply — banned word(s) %r account=%s fan=%s",
                            banned_hit_summary(shaped.banned_hits), account_id, fid)
                continue
            if shaped.dropped_reason is not None:
                errors += 1
                continue
            if shaped.banned_hits:
                log.info("autoreply masked banned word(s) %r account=%s fan=%s",
                         banned_hit_summary(shaped.banned_hits), account_id, fid)
            parts = shaped.parts
            if typo_on:
                protect = name_protect + (list(NONNATIVE_OUTPUTS) if nonnative_on else [])
                parts = await apply_typo_throttle(
                    account_id, f.fan_id, parts, random.Random(f"{f.fan_id}:{raw}"),
                    protect=protect, max_bubbles=max_bubbles)
            if dry_run:
                sent += 1
                continue

            # Re-check after generation: the LLM call can outlast a sibling's 10-15 s cooldown, so someone may have answered him meanwhile.
            if not await _fan_still_waiting(account_id, fid, inbound_at):
                skipped_raced += 1
                continue

            lost = None
            for idx, part in enumerate(parts):
                try:
                    await hold_with_typing(account_id, fid,
                                           typing_delay_seconds(part, typing_wpm),
                                           typing_indicator=typing_indicator)
                    await dm_rate.turn(account_id, release_budget_s=INLINE_MAX_S)
                except run_slot.SlotLost as e:
                    if not sent_ok:
                        raise
                    lost = e
                    break
                try:
                    result = await asyncio.to_thread(client.send_message, fid, part)
                except Exception as e:
                    errors += 1
                    await skip_unreachable_fan(account_id, fid, e, log=log)
                    log.warning("autoreply send failed account=%s fan=%s", account_id, fid,
                                exc_info=True)
                    break
                mid = result.get("id") if isinstance(result, dict) else None
                if mid:
                    await write_outbound_attribution(
                        account_id=account_id, fan_id=fid, message_id=int(mid),
                        sent_by_employee_id=None, automation_kind=_PURPOSE,
                        body=str(result.get("text") or part),
                        price_cents=0,
                        created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                        emit_live=True,
                    )
                    sent_ok = True
            if sent_ok:
                await _save_state(account_id, fid, spell_inbound_at=spell_anchor,
                                  nudges_sent=nudges + 1, last_nudge_at=datetime.utcnow())
                sent += 1
            if lost is not None:
                raise lost
        finally:
            if not sent_ok:
                await ax.release_fan_lease(account_id, fid)

    return {"enabled": True, "candidates": len(cands), "sent": sent,
            **folder_stats, **audience_stats, **claimed_stats,
            **({"reason": f"partial:{refused}"} if refused else {}),
            "skipped_cap": skipped_cap,
            "skipped_raced": skipped_raced, "skipped_restricted": skipped_restricted,
            "skipped_unreachable": skipped_unreachable, "skipped_spam": skipped_spam,
            "skipped_cooldown": skipped_cooldown,
            "skipped_locked": skipped_locked, "skipped_banned": skipped_banned,
            "skipped_photo_only": skipped_photo_only,
            "photos_described": photos_described,
            "errors": errors, "dry_run": dry_run, "model": model,
            **({"key_error": key_error} if key_error else {})}


async def _load_persona(account_id: str) -> str:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    return compose_persona(cfg, fallback=(
        "You are a warm, flirty OnlyFans creator texting a fan you've been "
        "chatting with."))
