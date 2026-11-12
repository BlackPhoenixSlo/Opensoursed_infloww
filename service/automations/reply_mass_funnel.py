"""
service/automations/reply_mass_funnel.py — Automation A11: reply_mass_funnel.

Spec: library/one_section_of_automations/11_reply_mass_funnel.md (+ 15_funnel_schema.md).

The DOM-era script polled the OnlyFans chat sidebar every 2 minutes, matched the
last model message against the funnel's `opening_message` to DISCOVER replying
fans, and walked each one through the funnel's `steps` (clicking the composer,
attaching vault media, setting a PPV price). This is the network-rewrite of that
flow as a P4 automation — NO DOM. Per the mapping table at the bottom of spec 11:

    sidebar discovery        → DB scan of `messages` (the broadcast's recipients,
                               written by A10 send_mass_message with mass_run_id)
    replied_recipient_fans() → DB: the run's recipients who have replied since
                               our last funnel-out to them (one set query)
    send next step           → of_client.send_message → write_outbound_attribution
    PPV (vault + price)       → of_client.send_message(price=, media_files=)

State machine (the acceptance bar — "advances one step per eligible reply and
RESUMES from funnel_state after restart") lives entirely in the `funnel_state`
table, keyed (mass_run_id, fan_id). Because every sweep reloads it from the DB
and holds NO in-memory carry-over, a `run_once` after a crash continues from the
persisted `current_step` — a restart is just the next sweep.

What it does, per tick (`run(account_id, payload, *, run_id)`):

  1. Find the account's active funnel broadcasts: `mass_runs` with status='ok'
     and a non-NULL `funnel_id` (optionally narrowed to payload `mass_run_id`).
  2. DISCOVERY — for each broadcast, the recipients are the fans with an outbound
     `messages` row carrying that `mass_run_id` (A10 wrote one per recipient). A
     recipient who has REPLIED since the broadcast and isn't tracked yet gets a
     fresh `funnel_state` row at step 0. Non-repliers never enter the funnel
     (mirrors the DOM "skip chats where You: spoke last").
  3. PROCESS — every due `funnel_state` row (status='pending',
     next_check_at <= now). For each:
       • take the per-(account, fan) send-lease so A05/A06/A07/A09 can't
         double-message the same fan in an overlapping cycle;
       • OFFER TAKEN (#30) — if the fan UNLOCKED a PPV since this funnel began
         (their own or another automation's), halt: mark `done` and hand off to
         the chatters rather than walking the remaining nudge steps;
       • PRE-SEND GUARD (#1) — never send a blank paywall (a paid_ppv step with
         no resolved vault media) or an empty bubble (text emptied by OF word-
         restriction); such a step is logged, backed off, and skipped;
       • if the fan has NOT replied since our last funnel message → bump
         check_count, push next_check_at by the NEXT gap of the just-sent step's
         `check_intervals_min` (default [2,4,10] → checks at +2, +6, +16 after
         the send, then every 10 forever) and move on (no send);
       • if they HAVE replied → resolve the step's text (static `messages`
         verbatim, OR generate via llm_client when the step opts in), send each
         message, persist the outbound row (tagged mass_run_id + funnel_step),
         advance `current_step`. A `paid_ppv` step (or the last step) marks the
         row `done` — hand-off to the chatter team.

Concurrency / sessions: each DB write uses its OWN AsyncSession — never one
shared across branches (the SQLAlchemy parallel-session footgun). The daily-spend
cap is serialized inside llm_client's atomic reserve, so this automation does NOT
need the executor's account_spend_lock. The per-fan lease is the anti-double-send
guard, mirroring welcome_chatter_for_info / send_welcome.

Scheduling: self-registers via `@register("reply_mass_funnel")` on import. To run
it on the spec's 2-minute cadence, insert an `automation_rules` row with
`kind="reply_mass_funnel"` and `trigger_json={"every_seconds": 120}`. NO edit to
automation_executor.py.

Funnel step shape (from `mass_message_funnels.steps_json`, spec 15)::

    {"step": 1, "check_intervals_min": [2,4,10], "messages": ["m1a", "m1b"]}
    {"step": 4, "type": "paid_ppv", "price": 24, "media_files": [123],
     "messages": ["open this..."]}

Generation opt-in (the prompt's "generate step text via llm_client"): a step with
no static `messages` but a `prompt` string — or `"generate": true` — is composed
by llm_client.chat (which writes the `grok_calls` audit row + enforces the daily
cost cap itself). Static-message steps (the reference `strokes_funnel`) send
verbatim and never touch the LLM.

Branching storylines: a step may carry an OPTIONAL `next` map that turns the
linear walker into a BRANCHING one — the next step is chosen from the fan's reply
instead of always advancing +1::

    {"step": 1, "messages": [...],
     "next": {"bought": 5, "ignored": 2, "keyword": {"more": 3}, "default": 3}}

`_funnel_routing.resolve_next(step, facts, ...)` picks the target with precedence
keyword > bought > ignored(didn't reply) > default > (+1 fallback); targets are
step NUMBERS mapped to indices. ABSENT `next` behaves EXACTLY like +1, so every existing funnel is
unaffected. A `next` can point backward, so `funnel_state.hops` counts re-routes
and the walker halts a fan past _MAX_HOPS (done + 'loop_guard') — a mis-authored
cycle can't spin forever. funnels_api validates the shape + that every target
references a real step.

Every status rule above (end of script, offer taken, wait schedule, `next`
branches, blocked, unreachable, the post-send advance, the loop guard) is the pure
`funnel_decide.decide(entry, event, script) -> (entry', effects)`; run() below
gathers the facts, builds the event and performs the effects in order (I/O only).

Send once (send_marker_decide, owner decision Q1): a step's marker (`sending_at`
+ the facts) is committed right before its first OF call; a Sent save clears it.
A raised attempt: a bubble that landed with an id → Sent (the PPV is bubble 0, a
later bubble never requeues it); an id-less return or a may-have-sent raise →
`unconfirmed_at`, never auto-resent (listed by unconfirmed_sends_api for the
user's Retry); surely not sent → cleared. Each non-dry tick first settles the
account's UNCONFIRMED rows whose step landed (`settle_landed`). Status stays
'pending' throughout (webhook_dispatch / wcfi read it).

Payload knobs (all optional): `mass_run_id` (process one broadcast only),
`model` (LLM override), `dry_run` (resolve text but neither send nor advance),
`max_chats` (per-run send cap), `test_fan` (process only this fan id).

Returns a stats dict → automation_runs.stats_json.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import audience_include as _audiences  # the include-only fence (read per call)
import automation_executor as ax  # _make_client / _parse_iso / _to_cents / lease seams
import dm_rate
import of_write                    # _may_have_sent, read at call time
import run_slot
import llm_client                  # call .chat at runtime so tests can patch it
from attribution import write_outbound_attribution
from automation_registry import register
from ._model_pick import resolve_model
from ._outbound_guard import apply_word_restriction
from ._send_failure import skip_unreachable_fan
from ._style_flags import load_strip_emojis, load_voice_blocks
from ._textutil import is_substantive_msg, strip_emojis
from ._typing_hold import (
    hold_with_typing, load_typing_indicator, load_typing_wpm, typing_delay_seconds,
)
from ._wordfilter import (  # compliance word filter
    banned_hit_summary, filter_banned, load_banned_words,
)
from ._funnel_routing import step_number_index, strip_html
from . import funnel_decide as fd  # the per-fan status machine (pure)
from . import funnel_run_decide as frd  # run()'s tick tally + stats dict (pure)
from . import send_marker_decide as smd  # the send-once marker's rules (pure)
from . import send_marker_store as smst  # ...and its SQL (looked up per call)
from ._funnel_signals import (
    has_fan_paid_ppv, last_funnel_out_at, last_inbound_at, latest_reply,
    replied_recipient_fans,
)
from db.engine import get_session
from db.models import (
    MASS_RUN_OK, AccountAiConfig, FunnelAccountMedia, FunnelResponder, FunnelState,
    MassMessageFunnel, MassRun, Message,
)
from llm_client import LLMCapExceeded
from of_client import OFClient
from automations.rhythm import INLINE_MAX_S

log = logging.getLogger("of-relay.automation.reply_mass_funnel")

# ── Knobs (ported from 11_reply_mass_funnel.md) ──────────────────────
_PURPOSE = "reply_mass_funnel"   # also the account_ai_config.model_by_purpose key
# This funnel walks ONE fan through steps paced by next_check_at (each step's
# `check_intervals_min`, funnel_decide.DEFAULT_INTERVALS when absent), so it re-messages the same fan every few minutes. The generic 30-min W3
# cooldown + the 900s kept lease would BOTH clobber that cadence (every 2-min step
# skipped as "resting"/"locked" until 30 min passed). So, like the other live
# flows, set a SHORT cooldown and RELEASE the lease on success. Keep it safely
# BELOW the smallest step interval (120s) so it never blocks a legit next step.
_REPLY_COOLDOWN_S = 60
_DEFAULT_MAX_CHATS = 40          # per-run send cap (logged when it bites)
# Gap between the two back-to-back bubbles of one step — bumped above the old
# 1.5s so it reads as "typing the next line" rather than an instant double-post.
# Jittered ±_STEP_GAP_JITTER so sends don't land on a detectable metronome.
# Tests set _STEP_GAP_S = 0 to skip the sleep.
_STEP_GAP_S = 4.0
_STEP_GAP_JITTER = 0.5           # ±50% → ~2-6s actual
# How long after a broadcast we keep LOOKING for new repliers to enrol. Walking
# an already-enrolled fan is NOT bounded by this — see `_active_mass_runs`.
#
# ⚠️ This is the anchor-set bound, and it is load-bearing. `_active_mass_runs`
# had no time bound at all: every funnel broadcast an account had ever sent
# stayed an anchor forever, and discovery re-walked all ~1,600 of its recipients
# every 120 s, for good. Measured on prod 2026-08-22: one account still
# re-scanning six broadcasts from seven weeks earlier, 2,188 runs burning 76,724
# seconds in 24 h — 53% of all automation time on the box — to discover exactly
# zero fans, with the work set growing by another ~1,600 recipients per blast
# sent. A fan who has not answered a broadcast within this window is not going
# to; if they ever do write, they arrive as ordinary inbound and the chat lanes
# answer them, so nothing is dropped by letting discovery close.
DISCOVERY_WINDOW_DAYS = 14


def _jittered_gap() -> float:
    """A human-ish typing pause around _STEP_GAP_S (±_STEP_GAP_JITTER)."""
    return _STEP_GAP_S * (1.0 + random.uniform(-_STEP_GAP_JITTER, _STEP_GAP_JITTER))
_STEP_TEMPERATURE = 0.85         # warm/varied, matches the persona calls
_MSG_CLIP = 400                  # clip each history message body for the prompt
_HISTORY_TAIL = 20               # last N messages handed to the model on generate
# Branching loop guard: a `next` map may point BACKWARD, so a mis-authored funnel
# can form a cycle. Halt a fan after this many `next` re-routes (passed to
# funnel_decide as `Script.max_hops`). A linear funnel (no `next`) never bumps the
# counter, so it never trips. Tests lower this (a11._MAX_HOPS) to trip the guard fast.
_MAX_HOPS = 20


# ── Model resolution (per-account / per-purpose override, 19 §4) ──────

async def _load_persona(account_id: str) -> str:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
    return (cfg.persona if cfg and cfg.persona else "").strip() or (
        "You are a warm, flirty OnlyFans creator chatting with one of your fans."
    )


# ── Funnel + broadcast lookup (own session each) ─────────────────────

class _Anchor(NamedTuple):
    """One funnel broadcast the walker still has work for.

    `discovery_open` is the whole point of naming this: the age bound is decided
    ONCE, in `_active_mass_runs`, beside the SQL that applies it. It used to be
    re-derived in the walker from `started_at`, which meant the same predicate
    lived in two languages and had to be kept in agreement by hand — and the
    reader had to notice that the Python copy was the first arm of the SQL `OR`
    to understand either. Now the query answers it and the walker just reads it.
    """
    mass_run_id: int
    funnel_id: int
    queue_id: int | None
    started_at: datetime | None
    discovery_closed_at: datetime | None
    audience: dict
    discovery_open: bool


async def _active_mass_runs(
    account_id: str, only_id: int | None, now: datetime,
) -> list[_Anchor]:
    """The account's completed funnel broadcasts →
    [(mass_run_id, funnel_id, queue_id, started_at, discovery_closed_at,
      audience_filter)]. A run is a funnel anchor when status='ok' and funnel_id
    is set. `discovery_closed_at` (set when the first mass was unsent) gates NEW
    enrollment only — see the discovery loop.

    A run stays an anchor while it can still do either half of the walker's job:
    DISCOVER new repliers (inside `DISCOVERY_WINDOW_DAYS` of the broadcast) or
    WALK someone already enrolled (a `pending` funnel_state row). A run that can
    do neither is finished, and re-listing it forever is what made this the most
    expensive automation on the box — see `DISCOVERY_WINDOW_DAYS`. The two arms
    are OR'd deliberately: an old run holding a mid-funnel fan keeps walking them
    for as long as they are pending, so the bound can never strand a live fan.

    `only_id` (operator-explicit targeting, `payload.mass_run_id`) BYPASSES the
    bound — asking for one run by id means you want that run looked at, even if
    it has aged out.
    """
    cutoff = now - timedelta(days=DISCOVERY_WINDOW_DAYS)
    async with get_session() as s:
        q = select(
            MassRun.id, MassRun.funnel_id, MassRun.queue_id,
            MassRun.started_at, MassRun.discovery_closed_at, MassRun.audience_filter,
        ).where(
            MassRun.account_id == str(account_id),
            MassRun.status == MASS_RUN_OK,
            MassRun.funnel_id.is_not(None),
        )
        if only_id is not None:
            q = q.where(MassRun.id == only_id)
        else:
            still_walking = (
                select(FunnelState.fan_id)
                .where(
                    FunnelState.mass_run_id == MassRun.id,
                    FunnelState.status == "pending",
                )
                .exists()
            )
            q = q.where(or_(MassRun.started_at >= cutoff, still_walking))
        rows = (await s.execute(q.order_by(MassRun.id))).all()
    out: list[_Anchor] = []
    for r in rows:
        try:
            audience = json.loads(r[5]) if r[5] else {}
        except Exception:
            audience = {}
        out.append(_Anchor(
            mass_run_id=int(r[0]),
            funnel_id=int(r[1]),
            queue_id=int(r[2]) if r[2] is not None else None,
            started_at=r[3],
            discovery_closed_at=r[4],
            audience=audience if isinstance(audience, dict) else {},
            # Same two facts the WHERE above is built from, so the walker can
            # never disagree with the anchor set it was handed.
            discovery_open=(only_id is not None or r[3] is None or r[3] >= cutoff),
        ))
    return out


async def _load_funnel_steps(funnel_id: int) -> list[dict]:
    """Parse `mass_message_funnels.steps_json` → list of step dicts (or [])."""
    async with get_session() as s:
        fn = await s.get(MassMessageFunnel, funnel_id)
    if fn is None or not fn.steps_json:
        return []
    try:
        steps = json.loads(fn.steps_json)
    except Exception:
        log.warning("reply_mass_funnel_bad_steps_json funnel=%s", funnel_id)
        return []
    return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []


def _digit_ids(raw) -> list[int]:
    """Coerce a media-id list to ints, dropping non-digit junk (mirrors the
    isdigit filter _send_step has always applied to vault ids)."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [int(m) for m in raw if str(m).isdigit()]


async def _load_account_media(funnel_id: int, account_id: str) -> dict | None:
    """The per-(funnel, account) MEDIA binding (FunnelAccountMedia) → a dict
    `{"opening": [int...], "steps": {step_no_str: {"media_files": [int...],
    "previews": [int...]}}}`, or None when this model hasn't mapped any media for
    the funnel yet (→ caller falls back to the funnel's legacy in-step media).

    Funnel TEXT is shared across models; the MEDIA is per-account because vault
    ids don't carry between accounts."""
    async with get_session() as s:
        row = await s.get(FunnelAccountMedia, (int(funnel_id), str(account_id)))
    if row is None:
        return None
    try:
        opening = _digit_ids(json.loads(row.opening_media_ids or "[]"))
    except Exception:
        opening = []
    try:
        steps_raw = json.loads(row.steps_media_json or "{}")
    except Exception:
        steps_raw = {}
    steps: dict[str, dict] = {}
    if isinstance(steps_raw, dict):
        for k, v in steps_raw.items():
            if not isinstance(v, dict):
                continue
            steps[str(k)] = {
                "media_files": _digit_ids(v.get("media_files")),
                "previews": _digit_ids(v.get("previews")),
            }
    return {"opening": opening, "steps": steps}


def _resolve_step_media(step: dict, acct_media: dict | None) -> tuple[list[int], list[int]]:
    """The (media_files, previews) to attach to THIS step's PPV send. Prefers the
    per-account binding (keyed by step number); falls back to any legacy in-step
    `media_files`/`previews` for funnels not yet seeded into funnel_account_media.
    Previews are clamped to the media set at send time (fd.ppv_send_kwargs)."""
    per = None
    if acct_media:
        per = (acct_media.get("steps") or {}).get(str(step.get("step")))
    if per is not None:
        media = list(per.get("media_files") or [])
        previews = list(per.get("previews") or [])
    else:
        media = _digit_ids(step.get("media_files"))
        previews = _digit_ids(step.get("previews"))
    return media, previews


def _presend_problems(is_ppv: bool, texts: list[str], media: list[int]) -> list[str]:
    """#1 pre-send guard: reasons THIS step must NOT be sent as-is ([] = safe).
    Catches the blank-send traps the DOM flow could produce:
      • `ppv_without_media` — a paid_ppv step with no resolved vault media would
        send a blank paywall (a $-locked message with nothing behind it);
      • `empty_text` — every bubble is empty after OF word-restriction, i.e. the
        fan would get an empty message.
    The caller LOGS + SKIPS on any problem rather than sending garbage."""
    problems: list[str] = []
    if not any(apply_word_restriction(str(t)).strip() for t in texts):
        problems.append("empty_text")
    if is_ppv and not media:
        problems.append("ppv_without_media")
    return problems


async def _record_responder(
    account_id: str, funnel_id: int, fan_id: int, mass_run_id: int, now: datetime,
) -> None:
    """Durable "answered this funnel" ledger write (R1/R2 dedup source). Called
    for every confirmed opener-replier at discovery; idempotent per
    (account, funnel, fan) so a later run of the same funnel never double-inserts
    and a re-tick is a no-op."""
    async with get_session() as s:
        await s.execute(
            sqlite_insert(FunnelResponder)
            .values(
                account_id=str(account_id), funnel_id=int(funnel_id),
                fan_id=int(fan_id), mass_run_id=int(mass_run_id),
                first_replied_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["account_id", "funnel_id", "fan_id"])
        )


def _norm_body(s: str | None) -> str:
    """Normalize a message body for opener matching: drop HTML tags,
    collapse whitespace, casefold."""
    return re.sub(r"\s+", " ", strip_html(s)).casefold()


# Adoption window around started_at for scrape-backfilled opener rows. OF
# delivers a queued broadcast over time on big audiences; 12h covers that
# without colliding with a same-text resend a day later (mass_premade Way 1).
_ADOPT_WINDOW_H = 12
_ADOPT_SLACK_MIN = 10


async def _opener_texts(account_id: str, funnel_id: int, queue_id: int | None) -> set[str]:
    """The broadcast's possible body texts, normalized: the funnel's
    opening_message plus the cached OF queue text (covers a composer text
    override on the opener)."""
    out: set[str] = set()
    async with get_session() as s:
        fn = await s.get(MassMessageFunnel, int(funnel_id))
        if fn is not None and fn.opening_message:
            out.add(_norm_body(fn.opening_message))
        if queue_id is not None:
            from db.models import MassBroadcastCache
            row = (await s.execute(
                select(MassBroadcastCache.body_text, MassBroadcastCache.raw_text).where(
                    MassBroadcastCache.account_id == str(account_id),
                    MassBroadcastCache.queue_id == int(queue_id),
                )
            )).first()
            if row is not None:
                for t in row:
                    if t:
                        out.add(_norm_body(t))
    out.discard("")
    return out


async def _adopt_list_recipients(
    account_id: str, mass_run_id: int,
    started_at: datetime | None, openers: set[str],
    excluded: set[int],
) -> int:
    """List-audience broadcasts (`user_lists`) get NO per-fan rows at send
    time — OF doesn't echo recipients and the WS pump skips outbound, so the
    opener only lands in each fan's chat when scrape_history backfills it,
    UNTAGGED. Adopt those rows: any untagged outbound near started_at whose
    normalized body equals the opener gets mass_run_id stamped, which makes
    the fan a recipient as far as `replied_recipient_fans` is concerned, and
    scopes last_funnel_out_at to the run. Idempotent — tagged rows leave the
    candidate set. Returns rows adopted (eventual-consistent: fans appear as
    scrape catches up)."""
    if not openers or started_at is None:
        return 0
    lo = started_at - timedelta(minutes=_ADOPT_SLACK_MIN)
    hi = started_at + timedelta(hours=_ADOPT_WINDOW_H)
    adopted = 0
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.message_id, Message.body).where(
                Message.account_id == str(account_id),
                Message.direction == "out",
                Message.mass_run_id.is_(None),
                Message.created_at >= lo,
                Message.created_at <= hi,
            )
        )).all()
        for fan_id, msg_id, body in rows:
            if int(fan_id) in excluded or _norm_body(body) not in openers:
                continue
            m = await s.get(Message, (str(account_id), int(fan_id), int(msg_id)))
            if m is not None:
                m.mass_run_id = int(mass_run_id)
                adopted += 1
    if adopted:
        log.info("reply_mass_funnel adopted %d list-audience opener rows run=%s",
                 adopted, mass_run_id)
    return adopted


async def _tracked_fans(mass_run_id: int) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(FunnelState.fan_id).where(FunnelState.mass_run_id == int(mass_run_id))
        )).all()
    return {int(r[0]) for r in rows}


async def _due_states(mass_run_id: int, now: datetime, only_fan: int | None) -> list[FunnelState]:
    """Detached `funnel_state` rows ready to process: pending + due, unmarked (a
    send-once marker is never auto-sent: only a settle or the user's Retry clears it)."""
    async with get_session() as s:
        q = select(FunnelState).where(
            FunnelState.mass_run_id == int(mass_run_id),
            FunnelState.status == "pending",
            (FunnelState.next_check_at.is_(None)) | (FunnelState.next_check_at <= now),
            FunnelState.sending_at.is_(None),
            FunnelState.unconfirmed_at.is_(None),
        )
        if only_fan is not None:
            q = q.where(FunnelState.fan_id == int(only_fan))
        rows = (await s.execute(q.order_by(FunnelState.fan_id))).scalars().all()
        # Detach so we can mutate copies and persist with explicit updates.
        for r in rows:
            s.expunge(r)
    return rows


# ── State writes (own session each) ──────────────────────────────────

async def _ensure_state(mass_run_id: int, fan_id: int, now: datetime) -> bool:
    """Insert a fresh step-0 state for a newly-discovered replier. Idempotent
    (ON CONFLICT DO NOTHING) so a race never double-tracks. Returns True iff it
    inserted a new row."""
    async with get_session() as s:
        res = await s.execute(
            sqlite_insert(FunnelState)
            .values(
                mass_run_id=int(mass_run_id),
                fan_id=int(fan_id),
                current_step=0,
                next_check_at=now,
                check_count=0,
                status="pending",
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["mass_run_id", "fan_id"])
        )
    return (res.rowcount or 0) > 0


def _state_values(e: fd.Entry, now: datetime) -> dict:
    """The state machine columns of one save (_save_state and the settle)."""
    return {**vars(e), "updated_at": now}


async def _save_state(cs: FunnelState, now: datetime) -> None:
    """Persist the mutated state machine fields for one (mass_run, fan). The same
    write drops the send-once marker: every save is on a row this tick read
    unmarked (_due_states) or ends its own marked attempt (Sent / Unreachable)."""
    async with get_session() as s:
        await s.execute(
            update(FunnelState)
            .where(FunnelState.mass_run_id == int(cs.mass_run_id),
                   FunnelState.fan_id == int(cs.fan_id))
            .values(**_state_values(fd.Entry.from_row(cs), now), **smst.CLEARED)
        )


# ── Send-once marker (send_marker_decide / send_marker_store) ────────
# House-funnel rows only: funnel-less rows (NULL `mass_runs.funnel_id`)
# share funnel_state — never read or written here.

_HOUSE_JOIN = (MassRun, MassRun.id == FunnelState.mass_run_id)


def _house(account_id: str) -> tuple:
    return (MassRun.account_id == str(account_id), MassRun.funnel_id.is_not(None))


def _keys(mass_run_id: int, fan_id: int) -> dict:
    return {"mass_run_id": int(mass_run_id), "fan_id": int(fan_id)}


async def _run_steps(mass_run_id: int) -> list[dict]:
    async with get_session() as s:
        funnel_id = (await s.execute(
            select(MassRun.funnel_id).where(MassRun.id == int(mass_run_id)))).scalar()
    return await _load_funnel_steps(int(funnel_id)) if funnel_id is not None else []


async def _replay_landed(account_id: str, cs: FunnelState, now: datetime) -> None:
    """One UNCONFIRMED row: its step landed → saved as Sent at `sending_at` (never
    `now`: it is the next "offer taken" baseline), marker cleared, nothing re-sent.
    A row it cannot replay (no steps, a shortened funnel, a bad ctx) is a miss."""
    steps = await _run_steps(cs.mass_run_id)
    if not 0 <= int(cs.current_step) < len(steps):
        return
    try:
        ctx = json.loads(cs.sending_ctx or "null")
    except ValueError:
        return
    if not isinstance(ctx, dict) or set(ctx) != set(vars(fd.Facts())):
        return
    if not await smst.landed(account_id, cs.fan_id, smd.lookup_since(cs.sending_at), _PURPOSE,
                             mass_run_id=int(cs.mass_run_id),
                             funnel_step=fd.step_number(steps[int(cs.current_step)])):
        return
    script = fd.Script(steps=steps, num_to_idx=step_number_index(steps), max_hops=_MAX_HOPS)
    e, _fx = fd.decide(fd.Entry.from_row(cs), fd.Sent(cs.sending_at, fd.Facts(**ctx)), script)
    await smst.clear(FunnelState, _keys(cs.mass_run_id, cs.fan_id), if_sending_at=cs.sending_at,
                     **{**_state_values(e, now), "last_error": None})


async def settle_landed(account_id: str, boot_ts: datetime, now: datetime) -> None:
    """Settle the account's UNCONFIRMED rows whose step landed (IN_FLIGHT ones may
    still be writing: untouched). Idempotent; one bad row never stops the tick."""
    await smst.settle(await smst.marked_rows(FunnelState, *_house(account_id), join=_HOUSE_JOIN),
                      lambda cs: _replay_landed(account_id, cs, now), boot_ts, now)


# The unconfirmed-sends API's entries (it guards, then calls these).

async def marked_sends(account_id: str) -> list[dict]:
    """The account's marked rows: fan, run, the step NUMBER it is on (its index + 1
    when the funnel no longer has it), the marker, last_error."""
    out, steps_of = [], {}
    for cs in await smst.marked_rows(FunnelState, *_house(account_id), join=_HOUSE_JOIN):
        if cs.mass_run_id not in steps_of:
            steps_of[cs.mass_run_id] = await _run_steps(cs.mass_run_id)
        steps, c = steps_of[cs.mass_run_id], int(cs.current_step)
        n = fd.step_number(steps[c]) if 0 <= c < len(steps) else None
        out.append({"fan_id": int(cs.fan_id), "mass_run_id": int(cs.mass_run_id),
                    "step": n if n is not None else c + 1, "sending_at": cs.sending_at,
                    "unconfirmed_at": cs.unconfirmed_at, "last_error": cs.last_error})
    return out


async def read_marker(account_id: str, fan_id: int, mass_run_id: int | None):
    """(sending_at, unconfirmed_at) of this Creator's row, None when there is none."""
    if mass_run_id is None:
        return None
    return await smst.read(FunnelState, _keys(mass_run_id, fan_id), *_house(account_id),
                           join=_HOUSE_JOIN)


async def retry_clear(account_id: str, fan_id: int, mass_run_id: int | None,
                      sending_at: datetime, now: datetime) -> bool:
    """The user's Retry: marker off, pending + due now (the next tick sends it once),
    only while the row still carries `sending_at`."""
    return await smst.clear(FunnelState, _keys(mass_run_id, fan_id), if_sending_at=sending_at,
                            status="pending", next_check_at=now, last_error=None, updated_at=now)


# ── Step text (static verbatim, or generate via llm_client) ──────────

def _is_generated(step: dict) -> bool:
    msgs = step.get("messages")
    if isinstance(msgs, list) and any(str(m).strip() for m in msgs):
        return False  # static messages win — DOM parity, reference funnel verbatim
    return bool(step.get("generate") or step.get("prompt"))


async def _history_block(account_id: str, fan_id: int) -> str:
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.direction, Message.body).where(
                Message.account_id == str(account_id),
                Message.fan_id == int(fan_id),
                Message.is_unsent.is_(False),
            ).order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(_HISTORY_TAIL)
        )).all()
    rows = list(reversed(rows))  # oldest → newest
    return "\n".join(
        f"{'FAN' if d == 'in' else 'YOU'}: {strip_html(b)[:_MSG_CLIP]}"
        for d, b in rows if strip_html(b)
    )


async def _step_texts(
    account_id: str, fan_id: int, step: dict, persona: str, model: str,
) -> list[str]:
    """Resolve the message(s) to send for one step. Static `messages` are sent
    verbatim (max 2, per spec). A generated step composes ONE message through
    llm_client (which writes grok_calls + enforces the cap). Raises
    LLMCapExceeded straight through to the caller."""
    if not _is_generated(step):
        msgs = [str(m).strip() for m in (step.get("messages") or []) if str(m).strip()]
        return msgs[:2]

    prompt = (step.get("prompt") or "").strip() or (
        "Continue the funnel naturally and nudge the conversation forward."
    )
    convo = await _history_block(account_id, fan_id)
    # This engine carries no humanizer, so `v.emoji_vocab` is the only thing
    # naming an emoji set on a male account — "" for her, so hers is unchanged.
    v = await load_voice_blocks(account_id)
    system = (
        f"{persona}\n\n"
        f"Funnel goal for this message: {prompt}\n\n"
        "Write ONE short reply (1-3 sentences, casual texting tone) as the "
        "creator. Output ONLY the message text — no quotes, no name prefix, no "
        "preamble.\n\n"
        f"{v.live_proof}{v.emoji_vocab}"
    )
    user = (
        f"Recent conversation (oldest→newest):\n{convo}\n\n"
        "Send the next funnel message now."
    )
    res = await llm_client.chat(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        purpose=_PURPOSE,
        account_id=account_id,
        fan_id=fan_id,
        temperature=_STEP_TEMPERATURE,
    )
    text = (res.content or "").strip()
    return [text] if text else []


# ── Sending one step (of_client + optimistic persistence) ────────────

@dataclass
class _Attempt:
    """One step's send attempt, owned by the caller and filled in by _send_step as
    it goes, so a return and any raise read the same: `sent` = bubbles OF returned
    with an id, `returned` = every bubble OF returned (id-less too), `marked_at` =
    the send-once mark (written right before the first OF call; None = no call)."""
    facts: fd.Facts
    sent: int = 0
    returned: int = 0
    marked_at: datetime | None = None


async def _send_step(
    client, account_id: str, fan_id: int, mass_run_id: int, step: dict,
    texts: list[str], is_ppv: bool,
    *, attempt: _Attempt, media: list[int] | None = None, previews: list[int] | None = None,
    typing_wpm: float = 0.0, typing_indicator: bool = False,
    strip_emoji_on: bool = False,
) -> None:
    """Send the step's message(s) and persist each outbound row (tagged
    mass_run_id + funnel_step, emit_live for the WORKER→SSE bridge), counting into
    `attempt`. PPV: price (from the shared step) + the
    caller-resolved per-account `media`/`previews` on the FIRST (only) message —
    vault ids are per-account, so the run loop resolves them via
    FunnelAccountMedia before calling here."""
    media = list(media or [])
    previews = list(previews or [])   # clamped to `media` by fd.ppv_send_kwargs
    step_num = fd.step_number(step)

    for i, text in enumerate(texts):
        # PPV: price + the caller-resolved per-account vault ids on the FIRST
        # (only) line; the text stays readable, only the media is paywalled.
        kwargs = fd.ppv_send_kwargs(step, media, previews) if is_ppv and i == 0 else {}

        # Last-mile OF-restricted word substitution — covers both the LLM step
        # replies and any verbatim funnel copy (V1 filtered every send). Done
        # before the typing hold so the delay matches the text actually sent.
        text = apply_word_restriction(text)
        if strip_emoji_on:  # account-wide emoji strip (opt-in)
            text = strip_emojis(text)
        if not text.strip():
            # #1: never emit a blank bubble (word-restriction/emoji-strip emptied
            # it). The run loop's _presend_problems already blocks an all-empty
            # step; this guards a later bubble going empty on its own.
            continue

        # Subsequent bubbles get a human pause first, then EVERY bubble holds for
        # the time it'd take to TYPE it — both waits show the live "...is typing"
        # bubble to the fan when the indicator is enabled.
        if i > 0 and _STEP_GAP_S:
            await hold_with_typing(account_id, fan_id, _jittered_gap(),
                                   typing_indicator=typing_indicator)
        await hold_with_typing(account_id, fan_id,
                               typing_delay_seconds(text, typing_wpm),
                               typing_indicator=typing_indicator)
        # The account's DM rate (OF_DM_PER_MIN): a full window waits like
        # a typing hold, the slot handed back (dm_rate).
        await dm_rate.turn(account_id, release_budget_s=INLINE_MAX_S)

        if attempt.marked_at is None:
            # Send once: the marker is committed before OF can take anything.
            attempt.marked_at = await smst.mark(FunnelState, _keys(mass_run_id, fan_id),
                                                vars(attempt.facts))
        result = await asyncio.to_thread(client.send_message, fan_id, text, **kwargs)
        attempt.returned += 1
        msg_id = result.get("id") if isinstance(result, dict) else None
        if not msg_id:
            log.warning("reply_mass_funnel send returned no id account=%s fan=%s step=%s",
                        account_id, fan_id, step_num)
            continue
        attempt.sent += 1   # OF took it with an id: it landed, whatever follows
        await write_outbound_attribution(
            account_id=account_id,
            fan_id=int(fan_id),
            message_id=int(msg_id),
            sent_by_employee_id=None,  # → system Automation employee
            automation_kind=_PURPOSE,  # reply_mass_funnel
            body=str(result.get("text") or text),
            price_cents=ax._to_cents(kwargs.get("price", 0)),
            created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
            mass_run_id=mass_run_id,
            funnel_step=step_num,
            emit_live=True,  # WORKER→SSE bridge: surface the funnel step live
        )


# ── The automation ───────────────────────────────────────────────────
# run() orchestrates I/O phase helpers sharing one `_Tick`; pure: funnel_decide
# (the fan's status), funnel_run_decide (the tally).

class _Knobs(NamedTuple):
    dry_run: bool
    only_run: int | None
    only_fan: int | None
    max_chats: int


def _knobs(payload: dict) -> _Knobs:
    only_run, only_fan = payload.get("mass_run_id"), payload.get("test_fan")
    return _Knobs(
        dry_run=bool(payload.get("dry_run")),
        only_run=int(only_run) if only_run is not None else None,
        only_fan=int(only_fan) if only_fan is not None else None,
        max_chats=int(payload.get("max_chats") or _DEFAULT_MAX_CHATS),
    )


@dataclass
class _Tick:
    """One run()'s context and tally, shared by its phase helpers."""
    account_id: str
    k: _Knobs
    now: datetime
    model: str
    typing_wpm: float
    typing_indicator: bool
    strip_emoji_on: bool
    banned_words: list[str]
    banned_mode: str
    persona: str
    client: OFClient
    audience_pol: _audiences.AudiencePolicy
    tally: frd.Tally = field(default_factory=frd.Tally)


class _Funnel(NamedTuple):
    """One broadcast's walk invariants: its anchor, script and this account's media."""
    a: _Anchor
    script: fd.Script
    acct_media: dict | None


async def _audience_allows(t: _Tick, fan_id: int) -> bool:
    """Include-only audience fence: applied at discovery (no enrol) and at the walk
    (no advance) before any LLM spend; `only_fan` (operator targeting) is exempt."""
    pol = t.audience_pol
    if pol.mode == "off" or (t.k.only_fan is not None and fan_id == t.k.only_fan):
        return True
    if pol.mode == "shadow":
        if int(fan_id) not in pol.member_ids:
            t.tally.audience_skipped += 1        # would-skip; shadow gates nothing
        return True
    ok, _why = await _audiences.audience_allows_fan(
        t.account_id, fan_id, kind="reply_mass_funnel", policy=pol)
    if not ok:
        t.tally.audience_skipped += 1
    return ok


async def _perform(t: _Tick, cs: FunnelState, e: fd.Entry, effects: list[fd.Effect]) -> bool:
    """Carry out decide()'s effects in order; Save copies entry' onto the detached row
    and persists it (not on a dry run). True iff it asks for the step to be sent."""
    t.tally.fx.update(effects)
    for eff in effects:
        if isinstance(eff, fd.Save):
            for k, v in vars(e).items():
                setattr(cs, k, v)
            if not t.k.dry_run:
                await _save_state(cs, t.now)
    return fd.Generate() in effects


async def _adopt_list_openers(t: _Tick, a: _Anchor) -> None:
    """0) List-audience sends wrote no per-fan rows — adopt the scrape-backfilled
    opener rows so those fans are discoverable."""
    if not (a.audience.get("user_lists") or a.audience.get("list_ids")):
        return
    try:
        openers = await _opener_texts(t.account_id, a.funnel_id, a.queue_id)
        excluded = {int(x) for x in (a.audience.get("excluded_users") or [])}
        await _adopt_list_recipients(t.account_id, a.mass_run_id, a.started_at, openers, excluded)
    except Exception:
        log.warning("reply_mass_funnel adopt failed run=%s", a.mass_run_id, exc_info=True)


async def _discover(t: _Tick, a: _Anchor) -> list[FunnelState]:
    """1) New repliers → ledger + fresh step-0 state. A dry run saves neither and
    returns the unsaved step-0 states it would walk."""
    dry_enrolled: list[FunnelState] = []
    # Past the discovery window this run only walks fans already enrolled — asking
    # ~1,600 recipients "did you reply yet?" forever is the leak
    # `DISCOVERY_WINDOW_DAYS` closes (decided in `_active_mass_runs`; see `_Anchor`).
    if not a.discovery_open:
        t.tally.discovery_skipped += 1
        return dry_enrolled
    # ONE query for the whole question, not two per recipient.
    tracked = await _tracked_fans(a.mass_run_id)
    for fan_id in sorted(await replied_recipient_fans(t.account_id, a.mass_run_id) - tracked):
        if t.k.only_fan is not None and fan_id != t.k.only_fan:
            continue
        # They ANSWERED this funnel's opener → durable dedup ledger (R1/R2),
        # regardless of the cutoff below. Not on a dry run: the ledger drops the fan
        # from every later send of this funnel, and nothing ever deletes it.
        if not t.k.dry_run:
            await _record_responder(t.account_id, a.funnel_id, fan_id, a.mass_run_id, t.now)
        # #R4: once the first mass is unsent, only a replier whose inbound landed
        # at/before the cutoff enrolls; a later one is deduped but not walked.
        if a.discovery_closed_at is not None:
            broadcast_at = await last_funnel_out_at(t.account_id, fan_id, a.mass_run_id)
            last_in = await last_inbound_at(t.account_id, fan_id, since=broadcast_at)
            if last_in is None or last_in > a.discovery_closed_at:
                continue
        # Audience fence: the dedup row above is ALWAYS recorded (a later admit can
        # never re-send the opener), but an outside fan is not ENROLLED.
        if not await _audience_allows(t, fan_id):
            continue
        if t.k.dry_run:
            # Would enroll: walk an unsaved step-0 state instead.
            t.tally.discovered += 1
            dry_enrolled.append(FunnelState(
                mass_run_id=int(a.mass_run_id), fan_id=int(fan_id),
                current_step=0, next_check_at=t.now, check_count=0,
                status="pending", hops=0))
            continue
        if await _ensure_state(a.mass_run_id, fan_id, t.now):
            t.tally.discovered += 1
    return dry_enrolled


async def _facts(t: _Tick, entry: fd.Entry, fan_id: int, a: _Anchor) -> fd.Facts:
    """Branching FACTS, gathered once: #30 "offer taken" (a PPV unlocked since this
    funnel's baseline — our own last PPV, else the broadcast time), whether the fan
    replied since our last funnel message, and that reply's text."""
    paid_since = fd.offer_since(entry, a.started_at)
    bought = bool(paid_since is not None and await has_fan_paid_ppv(
        t.account_id, fan_id, paid_since))
    last_out = await last_funnel_out_at(t.account_id, fan_id, a.mass_run_id)
    # One query answers both "replied since?" and "with what text?".
    replied, reply_text = await latest_reply(t.account_id, fan_id, last_out)
    substantive = is_substantive_msg(reply_text) if reply_text else False
    return fd.Facts(replied=replied, bought=bought, substantive=substantive,
                    reply_text=reply_text)


async def _compose(t: _Tick, fan_id: int, step: dict, c: int) -> list[str] | None:
    """The step's texts, or None: an LLM cap sets tally.cap_hit (the walk stops); a key
    error stops generated steps this run; a failure / empty text is an error."""
    try:
        texts = await _step_texts(t.account_id, fan_id, step, t.persona, t.model)
    except LLMCapExceeded:
        t.tally.cap_hit = True
        log.warning("reply_mass_funnel daily LLM cap reached account=%s — stopping",
                    t.account_id)
        return None
    except llm_client.LLMKeyError as e:
        t.tally.key_error = llm_client.key_error_payload(e)
        return None
    except Exception:
        t.tally.errors += 1
        log.warning("reply_mass_funnel generate failed account=%s fan=%s step=%s",
                    t.account_id, fan_id, c, exc_info=True)
        return None
    if not texts:
        t.tally.errors += 1
        log.warning("reply_mass_funnel empty step text account=%s fan=%s step=%s",
                    t.account_id, fan_id, c)
    return texts or None


def _screen(t: _Tick, texts: list[str], is_ppv: bool, media: list[int],
            fan_id: int, c: int) -> tuple[list[str] | None, list[str]]:
    """#1 pre-send validation + the compliance word filter → (texts', problems).
    A "block" verdict joins the #1 reasons so it rides the SAME blocked/back-off/
    resume path — an operator fixing the copy or media makes the step deliverable."""
    texts, bw = filter_banned(texts, t.banned_words, t.banned_mode)
    if bw:
        log.info("reply_mass_funnel banned word(s) %r account=%s fan=%s step=%s",
                 banned_hit_summary(bw), t.account_id, fan_id, c)
    return texts, (["banned_words"] if texts is None
                   else _presend_problems(is_ppv, texts, media))


async def _send_once(t: _Tick, f: _Funnel, cs: FunnelState, entry: fd.Entry,
                     texts: list[str], facts: fd.Facts) -> None:
    """Screen, send (_send_step commits the marker before OF sees it), then the send-once
    bookkeeping. A lost slot re-raises after what landed is recorded."""
    fan_id, c = int(cs.fan_id), entry.current_step
    step = f.script.steps[c]
    is_ppv = step.get("type") == "paid_ppv"
    media, previews = _resolve_step_media(step, f.acct_media) if is_ppv else ([], [])
    texts, problems = _screen(t, texts, is_ppv, media, fan_id, c)
    if problems:
        # A broken step won't fix itself per tick: backed off, still pending.
        entry, effects = fd.decide(entry, fd.Blocked(t.now, tuple(problems)), f.script)
        await _perform(t, cs, entry, effects)
        log.warning("reply_mass_funnel BLOCKED send account=%s fan=%s step=%s reasons=%s",
                    t.account_id, fan_id, c, problems)
        return
    lost = err = None
    attempt = _Attempt(facts)
    try:
        await _send_step(t.client, t.account_id, fan_id, f.a.mass_run_id, step, texts, is_ppv,
                         attempt=attempt, media=media, previews=previews,
                         typing_wpm=t.typing_wpm, typing_indicator=t.typing_indicator,
                         strip_emoji_on=t.strip_emoji_on)
    except run_slot.SlotLost as e:
        lost = err = e  # not this fan's failure: stop the run (re-raised below)
    except Exception as e:
        t.tally.errors += 1
        err = e
        log.warning("reply_mass_funnel send failed account=%s fan=%s step=%s",
                    t.account_id, fan_id, c, exc_info=True)
    # Permanent (deleted/blocked) → quarantine fleet-wide AND end THIS funnel state
    # — it stays due forever otherwise, regenerating the step texts every tick.
    unreachable = (err is not None and lost is None
                   and await skip_unreachable_fan(t.account_id, fan_id, err, log=log))
    keys = _keys(f.a.mass_run_id, fan_id)
    # Part of the step landed → sent (the PPV is bubble 0, a later bubble's failure
    # never requeues it); may have sent → unconfirmed, left for the user's Retry;
    # surely not → the marker goes and the step retries when due.
    match out := smd.failure_outcome(
            attempt.sent, attempt.returned, attempt.marked_at is not None,
            err is not None and of_write._may_have_sent(err), unreachable=unreachable):
        case smd.SENT:
            # The step just sent picks the next one (a reply keyword, a purchase,
            # `default`, else +1); a routeless PPV hands off.
            entry, effects = fd.decide(entry, fd.Sent(t.now, facts), f.script)
            await _perform(t, cs, entry, effects)
            t.tally.advanced += 1
        case smd.UNCONFIRMED:
            why = ((" ".join(str(err).split())[:200] or type(err).__name__)
                   if err is not None else "send returned no id")
            await smst.unconfirm(FunnelState, keys, attempt.marked_at,
                                 last_error=f"may not have sent: {why}"[:500],
                                 updated_at=datetime.utcnow())
        case smd.CLEAR if attempt.marked_at is not None and not unreachable:
            await smst.clear(FunnelState, keys, if_sending_at=attempt.marked_at)
    if unreachable:   # its save drops any marker too
        entry, effects = fd.decide(entry, fd.Unreachable(t.now), f.script)
        await _perform(t, cs, entry, effects)
    if err is None and out != smd.SENT:
        t.tally.errors += 1     # nothing went out (id-less / all emptied)
    if lost is not None:
        raise lost


async def _leased_step(t: _Tick, f: _Funnel, cs: FunnelState, entry: fd.Entry) -> None:
    """The fan's lease is held: facts → Checked; on Generate compose and send once."""
    fan_id, c = int(cs.fan_id), entry.current_step
    step = f.script.steps[c]
    facts = await _facts(t, entry, fan_id, f.a)
    # Offer taken (halt, or a `next.bought` branch), no reply yet (wait, or a spent
    # window's `next.ignored` branch), else send.
    entry, effects = fd.decide(entry, fd.Checked(t.now, facts), f.script)
    if not await _perform(t, cs, entry, effects):
        return
    if t.tally.key_error and _is_generated(step):
        return  # no usable key this run — one failed call, not one per fan
    texts = await _compose(t, fan_id, step, c)
    if texts is None:
        return
    if t.k.dry_run:
        t.tally.advanced += 1  # would-send; do NOT send or advance state
        return
    await _send_once(t, f, cs, entry, texts, facts)


async def _end_lease(t: _Tick, fan_id: int, sent_ok: bool) -> None:
    """W3 (paced-funnel variant): on a confirmed send set the SHORT cooldown, then
    RELEASE the lease, so the next step (due in 2-10 min) isn't blocked by a 30-min
    rest or a 900s lease. Cooldown first so it guards the moment the lease drops; on
    a cooldown-write failure KEEP the lease (900s) as the fallback guard."""
    if not sent_ok:
        await ax.release_fan_lease(t.account_id, fan_id)
        return
    try:
        await ax.start_fan_cooldown(t.account_id, fan_id, cooldown_s=_REPLY_COOLDOWN_S)
        await ax.release_fan_lease(t.account_id, fan_id)
    except Exception:
        log.warning("reply_mass_funnel cooldown set failed account=%s fan=%s "
                    "— keeping lease as fallback guard", t.account_id, fan_id, exc_info=True)


async def _walk_fan(t: _Tick, f: _Funnel, cs: FunnelState) -> None:
    """2) One due state: past the end → done; the audience / cooldown / lease gates;
    then the leased step."""
    # The fan's state, threaded through every decide(); the row only follows it on a Save.
    entry, effects = fd.decide(fd.Entry.from_row(cs), fd.Due(t.now), f.script)
    await _perform(t, cs, entry, effects)
    if fd.Complete() in effects:  # past the script's end
        return
    fan_id = int(cs.fan_id)
    # A fan who left (or never joined) the folder stops advancing; an admit resumes him.
    if not await _audience_allows(t, fan_id):
        return
    # Another automation messaged this fan recently → rest it (W3 cooldown).
    if await ax.fan_on_cooldown(t.account_id, fan_id):
        t.tally.skipped_cooldown += 1
        return
    # One bot message per fan per cycle — don't race A05/A06/A07/A09.
    if not await ax.acquire_fan_lease(t.account_id, fan_id, _PURPOSE):
        t.tally.skipped_locked += 1
        return
    advanced = t.tally.advanced
    try:
        await _leased_step(t, f, cs, entry)
    finally:
        # Sent = its save went through (only then is it counted; a dry run counts a
        # would-send) — even if a later raise (lost slot, Unreachable save) follows.
        await _end_lease(t, fan_id, not t.k.dry_run and t.tally.advanced > advanced)


async def _walk_anchor(t: _Tick, a: _Anchor) -> bool:
    """One funnel broadcast: adopt, discover, walk its due states (up to the per-run
    send cap). True = stop sweeping (LLM cap or send cap); a stepless one is skipped."""
    steps = await _load_funnel_steps(a.funnel_id)
    if not steps:
        log.info("reply_mass_funnel run=%s funnel=%s has no steps — skipping",
                 a.mass_run_id, a.funnel_id)
        return False
    # Branching: `next` targets are step NUMBERS → resolve them to indices. MEDIA is
    # per-account (vault ids don't carry between models): this account's binding
    # once per run; _resolve_step_media falls back to legacy in-step media.
    f = _Funnel(a, fd.Script(steps=steps, num_to_idx=step_number_index(steps),
                             max_hops=_MAX_HOPS),
                await _load_account_media(a.funnel_id, t.account_id))
    await _adopt_list_openers(t, a)
    dry_enrolled = await _discover(t, a)
    for cs in [*dry_enrolled, *await _due_states(a.mass_run_id, t.now, t.k.only_fan)]:
        if t.tally.advanced >= t.k.max_chats:
            log.info("reply_mass_funnel batch capped run=%s cap=%d (rest next tick)",
                     a.mass_run_id, t.k.max_chats)
            break
        await _walk_fan(t, f, cs)
        if t.tally.cap_hit:
            break  # the daily LLM cap: stop the walk
    return t.tally.cap_hit or t.tally.advanced >= t.k.max_chats


@register("reply_mass_funnel")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    k = _knobs(payload)
    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    typing_wpm = await load_typing_wpm(account_id)            # per-bubble pacing
    typing_indicator = await load_typing_indicator(account_id)  # live "...is typing"
    strip_emoji_on = await load_strip_emojis(account_id)  # account-wide emoji strip
    banned_words, banned_mode = await load_banned_words(account_id)  # compliance word filter
    persona = await _load_persona(account_id)
    now = datetime.utcnow()
    if not k.dry_run:
        # Send once: a step a dead attempt landed is saved as sent, never re-sent.
        await settle_landed(account_id, smd.BOOT_TS, now)
    runs = await _active_mass_runs(account_id, k.only_run, now)
    if not runs:
        return {"status": "skipped", "reason": "no_active_funnel_runs",
                "runs": 0, "discovered": 0, "advanced": 0}

    client = await asyncio.to_thread(ax._make_client, account_id)
    # Include-only audience: one policy read for the whole tick (_audience_allows).
    audience_pol = await _audiences.automation_audience(account_id)
    t = _Tick(account_id=account_id, k=k, now=now, model=model, typing_wpm=typing_wpm,
              typing_indicator=typing_indicator, strip_emoji_on=strip_emoji_on,
              banned_words=banned_words, banned_mode=banned_mode, persona=persona,
              client=client, audience_pol=audience_pol)
    for a in runs:
        if await _walk_anchor(t, a):
            break  # LLM cap or the per-run send cap → stop sweeping further runs
    return frd.summary(t.tally, len(runs), audience_pol.mode, k.dry_run, model)
