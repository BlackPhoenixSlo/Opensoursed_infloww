"""service/automations/autoreply.py — Automation: autoreply ("Auto Convo").

CONTINUE the chat when the team didn't reply fast enough. When a KNOWN fan in
the picked audience MESSAGED and nobody (team or AI) answered within the window (default 5 min –
3 h), send ONE casual, **never-PPV** reply — tone-matched to the recent messages,
just keeping the conversation going. It does NOT gather info (we already know him)
and it does NOT sell: no PPV, no tip-ask, no content offer. It only chats. After
the window it's too stale → send_followup's drip owns it (26h+).

Photos he sends: with `describe_photos` on, the photo in the message being
answered is described once (inbound_describe, the account's DeepInfra key) and
the reply reacts to it. Off, keyless or failed: text with the photo is answered
as normal, and a photo-only message still gets a reply that does not claim to
know what is in it — unless `skip_photo_only` is on, which skips those.

How it stays out of the other senders' way (timing, not trigger):
  • welcome_chatter_for_info answers its fans within SECONDS (webhook) — so by
    silence_min those fans aren't waiting. Auto Convo only catches fans no one
    covered in time (graduated / team-owned / AI not enabled for them).
  • send_followup re-engages much later (26h+).

Eligibility (ALL must hold; every knob is per-account in autoreply_config_json):
  1. enabled + not in quiet hours
  2. the FAN spoke last (an unanswered inbound) and the wait (now − his last
     inbound) is in [silence_min, silence_max] — the team didn't reply in time.
     With an optional step-in RANGE (step_in_max_minutes > silence_min) the
     floor is instead drawn per (fan, message) in [silence_min, step_in_max],
     deterministically, so the reply lag stops looking like a fixed timer.
  3. info-complete (≥75% bio bar — a fan we actually know)
  4. (no hidden spend / tenure caps — WHO is item 9, set on the Auto-reply page)
  5. (a fan who just paid is ours too: no other engine answers him)
  6. not restricted / unreachable / promo-spam
  7. not blacklisted, not on automation_paused_until (a human is in the chat)
  8. not already covered this wait (max_nudges per his message, min_gap apart) —
     and re-checked at send time that he's STILL waiting (AutoreplyState).
  9. the audience — EITHER source the owner turned on (`_audience`):
     (a) folders_enabled: in a picked OF list (`list_ids`; none picked = every
         fan), lifetime spend under folder_max_spend_cents (None = no cap);
     (b) new_fans_enabled: first seen under new_fan_hours ago (`_first_seen`,
         DB-only) AND lifetime spend under new_fan_max_spend_cents.
     And the account can resolve an LLM key for the run's provider — else the
     run stops before its first query.

Like nudge_online, this NEVER sets fans.automation_paused_until (it gates on its
own AutoreplyState), so the chat engines are never frozen by it. Self-
registers via @register("autoreply"); schedule with an automation_rules row
(kind="autoreply", trigger_json={"every_seconds": N}).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import llm_client
from ._persona import compose_persona
from . import _language
from . import _voice  # whose voice this account writes in (NULL → 'her')
import inbound_describe
from attribution import write_outbound_attribution
from automation_registry import register
from db.engine import get_session
from db.models import (
    AccountAiConfig, AutoreplyState, Blacklist, Fan, Message, SkipList, Transaction,
)
from llm_client import LLMCapExceeded, LLMConfigError
from ._common import (
    BIO_CONSISTENCY_GUARDRAIL,
    # PAINFUL_TEXTING / LIVE_PROOF_GUARDRAIL are NOT imported here: both vary by
    # creator voice, so this engine reads them off `_voice.blocks(...)` instead.
    # `_common` still exports the female lane for the engines that don't.
    NO_NARRATION_RULE, ONPLATFORM_GUARDRAIL,
    STYLE_3LINE, STYLE_MAX_BUBBLES,
    NONNATIVE_OUTPUTS, NONNATIVE_REGISTER, apply_nonnative_spacing, apply_nonnative_style, apply_word_restriction,
    hold_with_typing, apply_typo_throttle,
    load_nonnative_flags, load_spacing_flags, load_voice_blocks,
    load_painful_texting_flag,
    load_strip_emojis, load_style_flags,
    load_typing_indicator, load_typing_wpm, load_typo_flags, load_hard_skip_ids,
    load_promo_spam_ids,
    resolve_fan_name, resolve_model, should_skip_muted_creator,
    skip_unreachable_fan, typing_delay_seconds,
)
from ._wordfilter import (  # compliance word filter
    banned_hit_summary, filter_banned, load_banned_words,
)
from ._clock import clock_block, clock_line, load_clock_tz
from automations._outbound import finalize_draft
from .welcome_chatter_for_info import (_history_text, _is_info_complete, _strip_html,
                         split_for_bubbles, _dedupe_lead_reaction)

log = logging.getLogger("of-relay.automation.autoreply")

_PURPOSE = "autoreply"
_DEFAULT_LIMIT = 200          # candidate sweep ceiling
_DEFAULT_MAX_SENDS = 25       # per-run send cap
_TEMPERATURE = 0.95
_HISTORY_TAIL = 16            # last N messages handed to the model for tone
_MSG_CLIP = 300
_REPLY_MAX_CHARS = 600


def _defaults() -> dict:
    """Built-in OFF state + sensible knobs (the UI seeds from this)."""
    return {
        "enabled": False,
        "silence_min_minutes": 24,   # give the team this long before stepping in; 0 = at once
        "silence_max_minutes": 1115,  # ~18.5h — past this the thread is too stale
        # top of the step-in range; 0 = step in at exactly silence_min. The
        # Auto-reply page's "randomise" writes 2 × silence_min here.
        "step_in_max_minutes": 0,
        "max_nudges": 1,
        "min_gap_minutes": 5,        # ≥ this between replies to the same fan
        "last_n_messages": _HISTORY_TAIL,
        "quiet_hours_json": None,             # [start,end] creator-local; null=24/7
        # When True, don't require a complete profile — just respond from the last
        # few messages + whatever's already been gathered. Widens coverage to fans
        # we don't fully know yet.
        "info_not_required": True,
        # WHO gets replies — two sources, a fan qualifies on EITHER:
        # (a) folders: OF custom list ids (the same lists the Messages Pro chips
        #     and the mass composer pick); none ticked = every fan. Optional
        #     lifetime-spend cap on top (None = no cap).
        "folders_enabled": True,
        "list_ids": [],
        "folder_max_spend_cents": None,
        # (b) new fans: first seen under N hours ago AND lifetime spend under $Y.
        "new_fans_enabled": False,
        "new_fan_hours": 72,
        "new_fan_max_spend_cents": 1_000,
        # Photos he sends. Both opt-in. describe_photos: read the photo in the
        # message being answered with the vision model (needs a DeepInfra key).
        # skip_photo_only: a message that is only media, no text, gets no reply.
        "describe_photos": False,
        "skip_photo_only": False,
    }


def _step_in_minutes(cfg: dict, fan_id: int, inbound_at: datetime) -> int:
    """Minutes he must have been waiting before Auto Convo steps in. With a
    step-in RANGE set (step_in_max > silence_min), a per-(fan, message) draw
    in [silence_min, step_in_max] — capped one minute under silence_max so
    the top of the band is still a reachable window — and DETERMINISTIC
    (seeded by fan + his message's second), so every tick sees the same
    number and it re-rolls only when he writes again. step_in_max absent /
    0 / <= silence_min ⇒ exactly silence_min, no rng drawn."""
    lo = int(cfg["silence_min_minutes"])
    hi = min(int(cfg.get("step_in_max_minutes") or 0),
             int(cfg["silence_max_minutes"]) - 1)
    if hi <= lo:
        return lo
    key = inbound_at.replace(microsecond=0).isoformat()
    return random.Random(f"autoreply:{int(fan_id)}:{key}").randint(lo, hi)


# Folder membership is OF's (the lists are not mirrored locally), so it is read
# off OF — and only on a tick that has someone waiting. Cached per (account,
# folders) for a few minutes so the 30 s cadence does not re-crawl every
# folder each tick; a fan added to / removed from a folder is seen within TTL.
_FOLDER_TTL_S = 300
_folder_cache: dict[tuple[str, tuple[int, ...]], tuple[float, frozenset]] = {}


def _folder_ids(cfg: dict) -> tuple[int, ...]:
    """The picked OF list ids, normalised; () = no folder pick = every fan."""
    out: set[int] = set()
    for x in cfg.get("list_ids") or []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(out))


async def _folder_members(account_id: str, client, list_ids: tuple[int, ...]) -> frozenset | None:
    """Fans in ANY of the picked folders, or None when a folder could not be
    read at all (the caller then replies to nobody this tick — never widens to
    every fan on a failed read). A crawl that hits the paging backstop keeps
    what it read: a short allow-list only ever narrows who gets a reply."""
    key = (str(account_id), list_ids)
    hit = _folder_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < _FOLDER_TTL_S:
        return hit[1]
    from audience_include import _crawl_list_ids_blocking
    members: set[int] = set()
    for lid in list_ids:
        try:
            ids, truncated = await asyncio.to_thread(_crawl_list_ids_blocking, client, lid)
        except Exception as e:
            log.warning("autoreply folder read failed account=%s list=%s: %s",
                        account_id, lid, (str(e).splitlines() or [type(e).__name__])[0][:120])
            return None
        if truncated:
            log.warning("autoreply folder %s on account=%s hit the paging backstop "
                        "— replying to the members read so far", lid, account_id)
        members |= ids
    out = frozenset(members)
    _folder_cache[key] = (time.monotonic(), out)
    return out


async def _load_config(account_id: str) -> dict | None:
    """Per-account gate + knobs; returns the merged config when ENABLED, else None
    (absent/NULL/disabled/bad JSON → OFF, the safe default)."""
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
    """True if the creator-local hour is inside quiet_hours_json=[start,end].
    null / [0,0] → never quiet (24/7). Mirrors the executor's gate."""
    qh = cfg.get("quiet_hours_json")
    if not qh or not isinstance(qh, (list, tuple)) or len(qh) != 2:
        return False
    start, end = int(qh[0]), int(qh[1])
    if start == end:
        return False
    hour = int((now + timedelta(hours=cfg.get("_utc_offset", 0))).hour)
    return start <= hour < end if start < end else (hour >= start or hour < end)


# ── Re-engagement style variety (controls vibe + shape, never sells) ──
_STYLE_VARIANTS = (
    "answer him directly, then a light tease.",
    "short flirty reply, NO question.",
    "warm + playful, like you've been thinking of him.",
    "vibe sexual? keep it going — one suggestive line, still NO pics/PPV.",
    "two TINY texts on separate lines. 0-1 emoji.",
)


# His waiting turn holds a photo: "seen" = described (the "[he sent: …]" note in
# the transcript is what is in it), "unseen" = no description to go on.
_PHOTO_SEEN = (
    "HE SENT A PHOTO — the [he sent: …] note in the chat is what's in it. React to "
    "it like you're looking at it, in your own voice.\n\n")
_PHOTO_UNSEEN = (
    "HE SENT A PHOTO you can't make out — [he sent a photo] in the chat. Never say "
    "or imply what's in it. If he wrote something, answer that. If it's just the "
    "photo, react warmly and naturally anyway: a playful guess said AS a guess, or a "
    "flirty question about it, is fine.\n\n")


def _fan_facts(f: Fan, v: "_voice.VoiceBlocks" = _voice.HER) -> str:
    """What the prompt knows about him, one "- label: value" line per fact.
    Shared with the AI Copilot (copilot_api), which grounds its suggestions in
    the same facts."""
    facts = []
    nm = resolve_fan_name(f)
    if nm:
        facts.append(f"name: {nm.split('/')[0][:40]}")
    # `likes` is boobs/ass and nothing else — it exists to route a straight man to
    # the right body content out of a WOMAN's vault, and `gen_info` fills it
    # fleet-wide. On a male account it asserts, inside a facts block the model is
    # told never to contradict, a preference for a body the creator does not have.
    # Dropped for the male lane rather than re-mapped: what a submissive man is
    # into is a different axis entirely and `fetishes` already carries it as free
    # text. Resolved BEFORE the tuple so the lane check is one named decision
    # rather than a branch buried in a literal.
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

    # Auto Convo only chats: no PPV, no tip-ask, no content offer.
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

    # The prompt clock (clock_block: "" when the account has no tz configured →
    # byte-equal prompt) — same block as welcome_chatter_for_info. A model with
    # no clock invents one.
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
        # The live-proof refusal only — Auto Convo never offers anything paid.
        f"{v.live_proof}\n\n"
        f"{BIO_CONSISTENCY_GUARDRAIL}\n\n"
        # The emoji VOCABULARY is a fact about who the creator is, not a style
        # preference — but it ships inside the humanizer, which is opt-in per
        # automation. An account with `autoreply: false` in style_config therefore
        # had NO emoji guidance at all, and the prompt still asks for emoji, so the
        # model picked the female set. `v.emoji_vocab` is "" for her, so this is a
        # no-op on every female account whichever branch it takes.
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
    """[(fan, his_last_inbound_at)] where the FAN spoke last and is STILL WAITING
    on a reply — nobody (team or AI) answered within [silence_min, silence_max].
    That's the "cover a slow team" trigger: give the team `silence_min` to reply,
    and stop after `silence_max` (too stale → send_followup's drip owns it).

    Read from the MESSAGES table (source of truth — Fan.last_message_* lag scrape).
    welcome_chatter_for_info answers its fans within seconds, so by silence_min those
    aren't waiting; Auto Convo only catches fans no one covered in time. Also gated
    on info-complete + not blacklisted/human-handled. WHO (folders / new fans,
    and their spend caps) is `_audience`'s, applied after this."""
    sil_max = int(cfg["silence_max_minutes"])
    horizon = now - timedelta(minutes=sil_max)   # ignore chats quiet longer than max

    async with get_session() as s:
        bl = {int(r[0]) for r in (await s.execute(select(Blacklist.fan_id))).all()}
        # The LATEST message per fan within the silence-max horizon (most-recent
        # first; first row seen per fan_id is its latest).
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
    # Fans where the FAN spoke last (an unanswered inbound) and the wait is in
    # [step-in, max] — i.e. the team hasn't replied fast enough. The step-in
    # floor is `silence_min`, or this fan's own draw when a range is set.
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
            continue  # a human is in the chat → stand down
        if not cfg.get("info_not_required") and not _is_info_complete(f):
            continue  # known fan only (unless "info not needed" mode is on)
        out.append((f, waiting[int(f.fan_id)]))
    return out


async def _first_seen(account_id: str, fans: list[Fan]) -> dict[int, datetime]:
    """{fan_id: when he became ours}, from the DB only — the earliest of
    `fans.subscribed_at` (when a sync has set it), his first subscription /
    rebill charge, and his first message on record. OF's own subscribe date is
    not stored anywhere locally; every candidate has at least one message (he
    is waiting on a reply), so this always has an answer."""
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
    """WHO gets a reply: the waiting fans matching EITHER source the owner
    turned on — (a) in a picked folder (none picked = every fan) and under the
    folder spend cap, or (b) new (first seen under `new_fan_hours`) and under
    the new-fan spend cap. Neither on = nobody.

    Returns (kept, stats, client). The OF client is built only when a folder's
    members must be read, and handed back so the send loop reuses it. A folder
    OF will not return drops the FOLDER source for this tick (never widens to
    every fan); the new-fan source still applies."""
    stats: dict = {}
    client = None
    if not cands:
        return cands, stats, client
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
            except Exception:
                log.warning("autoreply client init failed account=%s", account_id,
                            exc_info=True)
            if members is None:
                stats["folder_error"] = "read"
                pool = set()
            else:
                pool &= members
        keep |= pool

    kept = [(f, t) for (f, t) in cands if int(f.fan_id) in keep]
    stats["skipped_audience"] = len(cands) - len(kept)
    return kept, stats, client


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
    """The last `tail` rows, oldest first, as [direction, text, media_count,
    image_desc, message_id] (a list, so a fresh description can be filled in)."""
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
    """His unanswered run: the inbound rows after our last outbound."""
    run: list[list] = []
    for r in reversed(rows):
        if r[0] != "in":
            break
        run.append(r)
    return run[::-1]


def _transcript(rows: list[list]) -> list[tuple[str, str]]:
    """Rows → the (direction, line) pairs the prompt reads. A described photo
    rides in as "[he sent: …]" (the shared `_history_text`); an undescribed one
    as "[he sent a photo]", so a photo-only message is not an invisible turn."""
    out: list[tuple[str, str]] = []
    for d, text, media, desc, _mid in rows:
        line = _history_text(d, text, desc)
        if d == "in" and media and not desc:
            line = f"{line} [he sent a photo]" if line else "[he sent a photo]"
        out.append((d, line))
    return out


async def _fan_still_waiting(account_id: str, fan_id: int, inbound_at) -> bool:
    """Re-validate just before sending: the fan must STILL be waiting — no reply
    (outbound) landed since his last inbound. If the team or welcome_chatter_for_info answered
    in the meantime, stand down (don't double-message). Reads the messages table
    (the truth), not Fan.last_message_sent_at (which lags scrape)."""
    async with get_session() as s:
        row = (await s.execute(
            select(Message.message_id).where(
                Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                Message.direction == "out", Message.is_unsent.is_(False),
                Message.created_at > inbound_at).limit(1)
        )).first()
    return row is None


async def _load_unreachable_ids(account_id: str) -> set[int]:
    """Fans skip-listed 'unreachable' (deleted/blocked — every send 404s and burns
    an LLM call). autoreply otherwise ignores skip_list, but this one reason must
    be honored: the 7d undeliverable pause eventually expires and, without this,
    a widened autoreply would re-generate + re-fail on a dead fan."""
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
    # No key for the provider this run would bill → stop here, quietly: one
    # owner/key read, before any candidate query, image or context fetch. Without
    # it every waiting fan raised LLMConfigError inside the loop, one warning
    # and traceback per fan per tick, on an account that cannot reply at all.
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
    # Minimum time between Auto Convo replies to the SAME fan — never faster than
    # min_gap, and never faster than silence_min (so a fan who fires back can't
    # pull instant replies; he waits the same minimum again).
    reply_gap = timedelta(minutes=max(int(cfg["min_gap_minutes"]),
                                      int(cfg["silence_min_minutes"])))

    cands = await _candidates(account_id, cfg, now)  # [(fan, our_last_out_at)]
    if only_set is not None:
        cands = [(f, t) for (f, t) in cands if int(f.fan_id) in only_set]

    # WHO to reply (folders / new fans) — before the audience fence and the
    # [:limit] slice, and before any LLM spend. Folders are read only when
    # someone is waiting.
    cands, folder_stats, client = await _audience(account_id, cfg, cands, now)

    # Include-only audience (operator decision O1: autoreply IS gated) — before
    # the [:limit] slice so the fence can't eat the tick's budget, and before
    # any LLM spend.
    import audience_include as _audiences
    audience_stats: dict = {}
    _kept = set(await _audiences.filter_candidates(
        account_id, [int(f.fan_id) for (f, _) in cands], kind="autoreply",
        stats=audience_stats))
    cands = [(f, t) for (f, t) in cands if int(f.fan_id) in _kept][:limit]
    # Nobody waiting → done. Same shape as the disabled / quiet-hours returns,
    # and what makes the 30 s cadence cheap: an empty tick is the config, model
    # and key reads, one messages query and the audience step — the ~20
    # per-account loads below run only for a real fan.
    if not cands:
        return {"enabled": True, "candidates": 0, "sent": 0, **folder_stats,
                **audience_stats}

    typing_wpm = await load_typing_wpm(account_id)
    typing_indicator = await load_typing_indicator(account_id)  # live "...is typing"
    style_on = (await load_style_flags(account_id))[_PURPOSE]  # human-style opt-in
    account_lang = await _language.load_account_language(account_id)  # output language + guards
    # Whose voice this account writes in, as one resolved bundle off ONE row read. Built once per run beside the language for
    # the same reason: both are account-constant and cannot change mid-sweep.
    # NULL → 'her' → every string below renders exactly as it always has.
    voice_blocks = await load_voice_blocks(account_id)
    typo_on = (await load_typo_flags(account_id))[_PURPOSE]    # thumb-typo opt-in
    nonnative_on = (await load_nonnative_flags(account_id))[_PURPOSE]  # non-native opt-in
    # Space-before-"?" — its own tri-state key, read independently but only
    # ever APPLIED inside the non-native block below, so it can narrow that
    # register and never widen it.
    spacing_on = (await load_spacing_flags(account_id))[_PURPOSE]
    painful_on = await load_painful_texting_flag(account_id)  # brevity/emotion framing (default ON)
    strip_emoji_on = await load_strip_emojis(account_id)  # account-wide emoji strip
    max_bubbles = STYLE_MAX_BUBBLES if style_on else 2
    style_pool = _STYLE_VARIANTS + ((STYLE_3LINE,) if style_on else ())

    # autoreply gates on automation_paused_until, not skip_list — so load the
    # HARD skips (muted_creator / manual "restrict this fan") explicitly and skip
    # them here too, so a restricted fan is silenced on EVERY automation.
    hard_skip = await load_hard_skip_ids(account_id)
    promo_spam = await load_promo_spam_ids(account_id)
    # The info-complete gate used to ACCIDENTALLY shield no-info / promo /
    # unreachable fans from Auto Convo. With info_not_required widening coverage,
    # those exclusions must be explicit — mirror what every other chat sender does
    # so a widened autoreply never texts a dead fan or peer-creator promo spam.
    # (Mid-funnel fans are NOT excluded here by design — the funnel replies fast,
    # so a fan is never left waiting long enough mid-funnel for Auto Convo to step
    # in; if the funnel stalls, a keep-warm line is preferable to silence.)
    unreachable = await _load_unreachable_ids(account_id)

    persona = await _load_persona(account_id)
    clock_tz = await load_clock_tz(account_id)  # None ⇒ no clock line in the prompt
    banned_words, banned_mode = await load_banned_words(account_id)  # compliance word filter
    # Photo describe: on only by the owner's opt-in, and off for the rest of the
    # run after a hard stop (no DeepInfra key / LLMConfigError).
    describe_on = bool(cfg.get("describe_photos"))
    skip_photo_only = bool(cfg.get("skip_photo_only"))

    sent = skipped_cap = skipped_raced = errors = 0
    skipped_restricted = 0   # muted creator / manual "restrict from automations"
    skipped_unreachable = 0  # skip_list 'unreachable' (dead/blocked → send 404s)
    skipped_banned = 0       # compliance word filter tripped in "block" mode
    skipped_spam = 0         # peer-creator promo: creator_we_follow + $0 + no exchange + blasted
    skipped_cooldown = 0     # a sibling sender paused him this tick
    skipped_locked = 0       # another sender holds the fan-lease
    skipped_photo_only = 0   # media-only message and skip_photo_only is on
    photos_described = 0     # vision calls that produced a description
    key_error = None         # a rejected key stops the run: one call, not one per fan

    for f, inbound_at in cands:
        if sent >= max_sends:
            break
        fid = int(f.fan_id)
        # Durably restricted (muted peer-creator, or hand-restricted) → never reply.
        if fid in hard_skip or should_skip_muted_creator(f):
            skipped_restricted += 1
            continue
        # Dead/blocked fan — sending 404s and burns an LLM call.
        if fid in unreachable:
            skipped_unreachable += 1
            continue
        # Peer-creator promo spam — the founder problem. Needs real promo evidence,
        # not just OF's creator_we_follow flag (see load_promo_spam_ids).
        if fid in promo_spam:
            skipped_spam += 1
            continue

        st = await _load_state(account_id, fid)
        # Min cadence: never reply to this fan again within `reply_gap`, even if
        # he re-messages fast (applies ACROSS messages, not just the same one).
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

        # Re-validate right before sending: he must STILL be waiting (no reply
        # landed since his message — else the team/welcome_chatter_for_info got it first).
        if not await _fan_still_waiting(account_id, fid, inbound_at):
            skipped_raced += 1
            continue

        # Cooldown read + the DB-atomic fan-lease, BEFORE any generation (the
        # cross-engine mutex; a reply drawn before we hold it may be thrown away).
        if await ax.fan_on_cooldown(account_id, fid):
            skipped_cooldown += 1
            continue
        if not await ax.acquire_fan_lease(account_id, fid, _PURPOSE):
            skipped_locked += 1
            continue

        # Everything from here holds the lease — a try/finally guarantees it's
        # released on every non-send path (like welcome_chatter_for_info)
        # so a future raise can never leak it for the full TTL. autoreply NEVER
        # sets a cooldown (it must not freeze the other senders): on a confirmed
        # send it KEEPS the lease to expire by TTL (no sibling double-messages
        # right after us), on anything else it RELEASES for a faster retry.
        sent_ok = False
        try:
            rows = await _history(account_id, fid, tail)
            waiting = _waiting_turn(rows)
            photo_rows = [r for r in waiting if r[2] > 0]
            photo_only = bool(photo_rows) and not any(r[1] for r in waiting)
            if photo_only and skip_photo_only:
                skipped_photo_only += 1
                continue
            # Per-fan language: fans.language (manual pin or gen_info detection)
            # overrides the account default; unset → account default.
            fan_lang = _language.resolve_language(account_lang,
                                                  getattr(f, "language", None))

            if client is None:
                try:
                    client = await asyncio.to_thread(ax._make_client, account_id)
                except Exception:
                    log.warning("autoreply client init failed account=%s", account_id,
                                exc_info=True)
                    break

            # Describe the newest undescribed photo in his waiting turn, once —
            # the result is cached on messages.image_desc.
            todo = next((r for r in reversed(photo_rows) if not r[3]), None)
            if describe_on and todo is not None:
                try:
                    todo[3] = await inbound_describe.describe_photo(
                        account_id, todo[4], client,
                        his_words=" ".join(r[1] for r in waiting if r[1]))
                    photos_described += bool(todo[3])
                except LLMConfigError as e:
                    describe_on = False   # hard stop: no retry, no bigger model
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
                res = await llm_client.chat(model=model, messages=msgs, purpose=_PURPOSE,
                                            account_id=account_id, fan_id=fid,
                                            temperature=_TEMPERATURE)
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
            # Deterministic floor under ONPLATFORM_GUARDRAIL: if the model still leaked
            # a number / off-platform handle / meetup arrangement, swap for a deflection.
            # The shared send chokepoint (_outbound): off-platform guard, then the
            # account-wide emoji strip, before the split. No PHASE 2 consistency check
            # — autoreply does not implement it, which is why there is no
            # `consistency_autoreply` flag to switch on (see _common.CONSISTENCY_AUTOMATIONS).
            raw, _leak = await finalize_draft(
                raw, account_id=account_id, fan_id=fid, purpose=_PURPOSE,
                strip_emoji=strip_emoji_on, v=voice_blocks)
            parts = [apply_word_restriction(p)[:_REPLY_MAX_CHARS]
                     for p in split_for_bubbles(raw, max_bubbles,
                                                rng=random.Random(f"split:{f.fan_id}:{raw}"))
                     if p.strip()][:max_bubbles]
            # Don't open with the same reaction word we just used ('oof' every send).
            if style_on and parts:
                parts = _dedupe_lead_reaction(parts, [b for d, b in history if d == "out"])
            if not parts:
                errors += 1
                continue
            # Compliance word filter — before the nonnative/typo layers
            # (filter_banned's documented contract), so a typo can't smuggle a
            # flagged word past the scan.
            parts, _bw = filter_banned(parts, banned_words, banned_mode)
            if parts is None:
                skipped_banned += 1
                log.warning("autoreply BLOCKED reply — banned word(s) %r account=%s fan=%s",
                            banned_hit_summary(_bw), account_id, fid)
                continue
            if _bw:
                log.info("autoreply masked banned word(s) %r account=%s fan=%s",
                         banned_hit_summary(_bw), account_id, fid)
            name_protect = [n for n in (f.real_name, f.generated_nickname,
                                        f.of_display_name) if n]
            if nonnative_on:  # opt-in: deterministic non-native misspellings (always)
                # ONE rng for the whole reply — see apply_nonnative_spacing.
                _q_rng = random.Random(f"{f.fan_id}:{raw}:q")
                parts = [apply_nonnative_style(p, protect=name_protect)
                         for p in parts]
                if spacing_on:
                    parts = [apply_nonnative_spacing(p, _q_rng) for p in parts]
            if typo_on:  # opt-in: a realistic thumb-slip (+ a throttled "*fix" bubble)
                protect = name_protect + (list(NONNATIVE_OUTPUTS) if nonnative_on else [])
                parts = await apply_typo_throttle(
                    account_id, f.fan_id, parts, random.Random(f"{f.fan_id}:{raw}"),
                    protect=protect, max_bubbles=max_bubbles)
            if dry_run:
                sent += 1
                continue

            # Re-check after the generation: the LLM call can take longer than a
            # sibling's short (10-15s) cooldown, so someone may have answered him
            # while we drew the reply. If he's no longer waiting, stand down.
            if not await _fan_still_waiting(account_id, fid, inbound_at):
                skipped_raced += 1
                continue

            for idx, part in enumerate(parts):
                await hold_with_typing(account_id, fid,
                                       typing_delay_seconds(part, typing_wpm),
                                       typing_indicator=typing_indicator)  # "typing"
                try:
                    result = await asyncio.to_thread(client.send_message, fid, part)
                except Exception as e:
                    errors += 1
                    # Permanent (deleted/blocked) → quarantine, so the next tick's
                    # paused-gate drops the fan BEFORE the LLM call. Transients retry.
                    await skip_unreachable_fan(account_id, fid, e, log=log)
                    log.warning("autoreply send failed account=%s fan=%s", account_id, fid,
                                exc_info=True)
                    break
                mid = result.get("id") if isinstance(result, dict) else None
                if mid:
                    await write_outbound_attribution(
                        account_id=account_id, fan_id=fid, message_id=int(mid),
                        sent_by_employee_id=None, automation_kind=_PURPOSE,  # autoreply
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
        finally:
            if not sent_ok:
                await ax.release_fan_lease(account_id, fid)

    return {"enabled": True, "candidates": len(cands), "sent": sent,
            **folder_stats, **audience_stats,
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
