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
from collections import Counter
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax  # _make_client / _parse_iso / _to_cents / lease seams
import dm_rate
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
from ._funnel_signals import (
    has_fan_paid_ppv, last_funnel_out_at, last_inbound_at, latest_reply,
    replied_recipient_fans,
)
from db.engine import get_session
from db.models import (
    AccountAiConfig, FunnelAccountMedia, FunnelResponder, FunnelState,
    MassMessageFunnel, MassRun, Message,
)
from llm_client import LLMCapExceeded
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
_DISCOVERY_WINDOW_DAYS = 14


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
    DISCOVER new repliers (inside `_DISCOVERY_WINDOW_DAYS` of the broadcast) or
    WALK someone already enrolled (a `pending` funnel_state row). A run that can
    do neither is finished, and re-listing it forever is what made this the most
    expensive automation on the box — see `_DISCOVERY_WINDOW_DAYS`. The two arms
    are OR'd deliberately: an old run holding a mid-funnel fan keeps walking them
    for as long as they are pending, so the bound can never strand a live fan.

    `only_id` (operator-explicit targeting, `payload.mass_run_id`) BYPASSES the
    bound — asking for one run by id means you want that run looked at, even if
    it has aged out.
    """
    cutoff = now - timedelta(days=_DISCOVERY_WINDOW_DAYS)
    async with get_session() as s:
        q = select(
            MassRun.id, MassRun.funnel_id, MassRun.queue_id,
            MassRun.started_at, MassRun.discovery_closed_at, MassRun.audience_filter,
        ).where(
            MassRun.account_id == str(account_id),
            MassRun.status == "ok",
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
    """Detached `funnel_state` rows ready to process: pending + due."""
    async with get_session() as s:
        q = select(FunnelState).where(
            FunnelState.mass_run_id == int(mass_run_id),
            FunnelState.status == "pending",
            (FunnelState.next_check_at.is_(None)) | (FunnelState.next_check_at <= now),
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


async def _save_state(cs: FunnelState, now: datetime) -> None:
    """Persist the mutated state machine fields for one (mass_run, fan)."""
    async with get_session() as s:
        row = await s.get(FunnelState, (int(cs.mass_run_id), int(cs.fan_id)))
        if row is None:  # pragma: no cover — defensive (discovery just inserted it)
            return
        row.current_step = cs.current_step
        row.last_sent_step = cs.last_sent_step
        row.next_check_at = cs.next_check_at
        row.check_count = cs.check_count
        row.status = cs.status
        row.last_error = cs.last_error
        row.last_ppv_sent_at = cs.last_ppv_sent_at
        row.hops = cs.hops
        row.updated_at = now


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

async def _send_step(
    client, account_id: str, fan_id: int, mass_run_id: int, step: dict,
    texts: list[str], is_ppv: bool,
    *, media: list[int] | None = None, previews: list[int] | None = None,
    typing_wpm: float = 0.0, typing_indicator: bool = False,
    strip_emoji_on: bool = False,
) -> int:
    """Send the step's message(s) and persist each outbound row (tagged
    mass_run_id + funnel_step, emit_live for the WORKER→SSE bridge). Returns the
    count of messages actually sent. PPV: price (from the shared step) + the
    caller-resolved per-account `media`/`previews` on the FIRST (only) message —
    vault ids are per-account, so the run loop resolves them via
    FunnelAccountMedia before calling here."""
    media = list(media or [])
    previews = list(previews or [])   # clamped to `media` by fd.ppv_send_kwargs
    step_num = fd.step_number(step)

    sent = 0
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
        try:
            if i > 0 and _STEP_GAP_S:
                await hold_with_typing(account_id, fan_id, _jittered_gap(),
                                       typing_indicator=typing_indicator)
            await hold_with_typing(account_id, fan_id,
                                   typing_delay_seconds(text, typing_wpm),
                                   typing_indicator=typing_indicator)
            # The account's DM rate (OF_DM_PER_MIN): a full window waits like
            # a typing hold, the slot handed back (dm_rate).
            await dm_rate.turn(account_id, release_budget_s=INLINE_MAX_S)
        except run_slot.SlotLost as e:
            e.sent = sent       # the run lost its slot: the caller records what landed
            raise

        result = await asyncio.to_thread(client.send_message, fan_id, text, **kwargs)
        msg_id = result.get("id") if isinstance(result, dict) else None
        if not msg_id:
            log.warning("reply_mass_funnel send returned no id account=%s fan=%s step=%s",
                        account_id, fan_id, step_num)
            continue
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
        sent += 1
    return sent


# ── The automation ───────────────────────────────────────────────────

@register("reply_mass_funnel")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    dry_run = bool(payload.get("dry_run"))
    only_run = payload.get("mass_run_id")
    only_run = int(only_run) if only_run is not None else None
    only_fan = payload.get("test_fan")
    only_fan = int(only_fan) if only_fan is not None else None
    max_chats = int(payload.get("max_chats") or _DEFAULT_MAX_CHATS)

    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    typing_wpm = await load_typing_wpm(account_id)            # per-bubble pacing
    typing_indicator = await load_typing_indicator(account_id)  # live "...is typing"
    strip_emoji_on = await load_strip_emojis(account_id)  # account-wide emoji strip
    banned_words, banned_mode = await load_banned_words(account_id)  # compliance word filter
    persona = await _load_persona(account_id)

    now = datetime.utcnow()
    runs = await _active_mass_runs(account_id, only_run, now)
    if not runs:
        return {"status": "skipped", "reason": "no_active_funnel_runs",
                "runs": 0, "discovered": 0, "advanced": 0}

    client = await asyncio.to_thread(ax._make_client, account_id)

    discovered = 0
    discovery_skipped = 0  # anchors past the window — walking only, not scanning
    advanced = 0          # states that sent a step this tick
    # waiting / completed / converted / branched / blocked: fx (funnel_decide's
    # Wait / Complete / Convert / Branch / Block effects performed this tick)
    skipped_locked = 0
    skipped_cooldown = 0
    errors = 0
    cap_hit = False
    key_error = None  # missing/rejected key: generated steps stop for this run, static ones still send

    # Include-only audience: one policy read for the whole tick. Applied at BOTH
    # per-fan seams — discovery (stops enrolling outside fans) and the due-state
    # walk (stops advancing already-enrolled fans who left/never were in the
    # folder) — before any LLM step-text spend. `only_fan` is operator-explicit
    # targeting and stays exempt (like force_ids).
    import audience_include as _audiences
    _audience_pol = await _audiences.automation_audience(account_id)
    audience_skipped = 0

    async def _audience_allows(fan_id: int) -> bool:
        nonlocal audience_skipped
        if _audience_pol.mode == "off" or (only_fan is not None and fan_id == only_fan):
            return True
        if _audience_pol.mode == "shadow":
            if int(fan_id) not in _audience_pol.member_ids:
                audience_skipped += 1        # would-skip; shadow gates nothing
            return True
        ok, _why = await _audiences.audience_allows_fan(
            account_id, fan_id, kind="reply_mass_funnel", policy=_audience_pol)
        if not ok:
            audience_skipped += 1
        return ok

    async def _save(cs: FunnelState) -> None:
        # dry_run walks the states without moving them (they're detached, so
        # only an explicit save persists).
        if not dry_run:
            await _save_state(cs, now)

    fx: Counter = Counter()  # every effect performed, by value (the stats read it)

    async def _perform(cs: FunnelState, e: fd.Entry, effects: list[fd.Effect]) -> bool:
        """Carry out decide()'s effects in order; Save copies entry' onto the
        detached row and persists it. True iff it asks for the step to be
        generated and sent."""
        fx.update(effects)
        for eff in effects:
            if isinstance(eff, fd.Save):
                for k, v in vars(e).items():
                    setattr(cs, k, v)
                await _save(cs)
        return fd.Generate() in effects

    for (mass_run_id, funnel_id, queue_id, started_at,
         discovery_closed_at, audience, discovery_open) in runs:
        steps = await _load_funnel_steps(funnel_id)
        if not steps:
            log.info("reply_mass_funnel run=%s funnel=%s has no steps — skipping",
                     mass_run_id, funnel_id)
            continue
        # Branching: `next` targets are step NUMBERS → resolve them to indices.
        script = fd.Script(steps=steps, num_to_idx=step_number_index(steps),
                           max_hops=_MAX_HOPS)
        # MEDIA is per-account (vault ids don't carry between models) — resolve
        # this account's binding once per run; _resolve_step_media falls back to
        # any legacy in-step media for funnels not yet seeded.
        acct_media = await _load_account_media(funnel_id, account_id)

        # ── 0) List-audience sends wrote no per-fan rows — adopt the
        #      scrape-backfilled opener rows so those fans are discoverable.
        if audience.get("user_lists") or audience.get("list_ids"):
            try:
                openers = await _opener_texts(account_id, funnel_id, queue_id)
                excluded = {int(x) for x in (audience.get("excluded_users") or [])}
                await _adopt_list_recipients(
                    account_id, mass_run_id, started_at, openers, excluded)
            except Exception:
                log.warning("reply_mass_funnel adopt failed run=%s", mass_run_id,
                            exc_info=True)

        # ── 1) Discovery: new repliers → ledger + fresh step-0 state ──
        dry_enrolled: list[FunnelState] = []
        # Past the discovery window this run is here solely to walk fans who are
        # already enrolled — asking ~1,600 recipients "did you reply yet?"
        # forever is precisely the leak `_DISCOVERY_WINDOW_DAYS` closes.
        # `discovery_open` is decided in `_active_mass_runs`; see `_Anchor`.
        if discovery_open:
            # ONE query for the whole question, not two per recipient.
            tracked = await _tracked_fans(mass_run_id)
            for fan_id in sorted(
                await replied_recipient_fans(account_id, mass_run_id) - tracked
            ):
                if only_fan is not None and fan_id != only_fan:
                    continue
                # They ANSWERED this funnel's opener → durable dedup ledger
                # (R1/R2), regardless of the discovery cutoff below. Not on a
                # dry run: the ledger drops the fan from every later send of
                # this funnel, and nothing ever deletes it.
                if not dry_run:
                    await _record_responder(
                        account_id, funnel_id, fan_id, mass_run_id, now)
                # #R4: once the first mass is unsent (discovery_closed_at set),
                # only ENROLL repliers whose inbound landed at/before the cutoff —
                # a fan who replies after the mass is gone is deduped but not
                # walked. Pre-cutoff replies (adopted late) still enroll.
                if discovery_closed_at is not None:
                    broadcast_at = await last_funnel_out_at(
                        account_id, fan_id, mass_run_id)
                    last_in = await last_inbound_at(
                        account_id, fan_id, since=broadcast_at)
                    if last_in is None or last_in > discovery_closed_at:
                        continue
                # Audience fence: the responder-dedup row above is ALWAYS
                # recorded (so a later admit can never re-send the opener), but
                # an outside fan is not ENROLLED for the walk.
                if not await _audience_allows(fan_id):
                    continue
                if dry_run:
                    # Would enroll: walk an unsaved step-0 state below instead.
                    discovered += 1
                    dry_enrolled.append(FunnelState(
                        mass_run_id=int(mass_run_id), fan_id=int(fan_id),
                        current_step=0, next_check_at=now, check_count=0,
                        status="pending", hops=0))
                    continue
                if await _ensure_state(mass_run_id, fan_id, now):
                    discovered += 1
        else:
            discovery_skipped += 1

        # ── 2) Process due states ────────────────────────────────────
        for cs in [*dry_enrolled, *await _due_states(mass_run_id, now, only_fan)]:
            if advanced >= max_chats:
                log.info("reply_mass_funnel batch capped run=%s cap=%d (rest next tick)",
                         mass_run_id, max_chats)
                break

            # The fan's state, threaded through every decide() below; the row
            # only follows it on a Save.
            entry, _fx = fd.decide(fd.Entry.from_row(cs), fd.Due(now), script)
            await _perform(cs, entry, _fx)
            if fd.Complete() in _fx:        # past the script's end
                continue
            c = entry.current_step

            fan_id = int(cs.fan_id)
            # Audience fence at the walk too: a fan who left (or never joined)
            # the folder stops advancing — his state simply waits; an admit
            # resumes it on a later tick.
            if not await _audience_allows(fan_id):
                continue
            # Another automation messaged this fan recently → rest it (W3 cooldown).
            if await ax.fan_on_cooldown(account_id, fan_id):
                skipped_cooldown += 1
                continue
            # One bot message per fan per cycle — don't race A05/A06/A07/A09.
            if not await ax.acquire_fan_lease(account_id, fan_id, _PURPOSE):
                skipped_locked += 1
                continue
            sent_ok = False
            try:
                step = steps[c]
                is_ppv = step.get("type") == "paid_ppv"

                # ── Branching FACTS — gathered once, drive the status machine.
                #    #30 "offer taken" (a PPV unlocked since this funnel's
                #    baseline — our own last PPV, else the broadcast time),
                #    whether the fan replied since our last funnel message, and
                #    that reply's text.
                paid_since = fd.offer_since(entry, started_at)
                bought = bool(paid_since is not None and await has_fan_paid_ppv(
                    account_id, fan_id, paid_since))
                last_out = await last_funnel_out_at(account_id, fan_id, mass_run_id)
                # One query answers both "replied since?" and "with what text?" —
                # the old pair scanned the identical rows twice per due fan per tick.
                replied, reply_text = await latest_reply(account_id, fan_id, last_out)
                substantive = is_substantive_msg(reply_text) if reply_text else False
                facts = fd.Facts(replied=replied, bought=bought,
                                 substantive=substantive, reply_text=reply_text)
                # Offer taken (halt, or a `next.bought` branch), no reply yet
                # (wait, or a spent window's `next.ignored` branch), else send.
                entry, _fx = fd.decide(entry, fd.Checked(now, facts), script)
                if not await _perform(cs, entry, _fx):
                    continue  # finally releases the lease (sent_ok False)

                if key_error and _is_generated(step):
                    continue  # no usable key this run — one failed call, not one per fan
                try:
                    texts = await _step_texts(account_id, fan_id, step, persona, model)
                except LLMCapExceeded:
                    cap_hit = True
                    log.warning("reply_mass_funnel daily LLM cap reached account=%s — stopping",
                                account_id)
                    break
                except llm_client.LLMKeyError as e:
                    key_error = llm_client.key_error_payload(e)
                    continue
                except Exception:
                    errors += 1
                    log.warning("reply_mass_funnel generate failed account=%s fan=%s step=%s",
                                account_id, fan_id, c, exc_info=True)
                    continue

                if not texts:
                    errors += 1
                    log.warning("reply_mass_funnel empty step text account=%s fan=%s step=%s",
                                account_id, fan_id, c)
                    continue

                if dry_run:
                    advanced += 1  # would-send; do NOT send or advance state
                    continue

                step_media, step_previews = (
                    _resolve_step_media(step, acct_media) if is_ppv else ([], []))

                # ── #1 Pre-send validation: never send a blank paywall or an empty
                #    bubble. A broken step (PPV with no media bound for THIS account,
                #    or text that empties after word-restriction) won't fix itself
                #    per tick — record it, back off to the fallback interval, and
                #    skip. It stays `pending` so a later media/text fix can resume.
                # Compliance word filter. A "block" verdict joins the #1 pre-send
                # reasons below so it rides the SAME blocked/back-off/resume path —
                # an operator fixing the copy makes the step deliverable again.
                texts, _bw = filter_banned(texts, banned_words, banned_mode)
                if _bw:
                    log.info("reply_mass_funnel banned word(s) %r account=%s fan=%s step=%s",
                             banned_hit_summary(_bw), account_id, fan_id, c)
                problems = (["banned_words"] if texts is None
                            else _presend_problems(is_ppv, texts, step_media))
                if problems:
                    entry, _fx = fd.decide(entry, fd.Blocked(now, tuple(problems)), script)
                    await _perform(cs, entry, _fx)
                    log.warning("reply_mass_funnel BLOCKED send account=%s fan=%s step=%s "
                                "reasons=%s", account_id, fan_id, c, problems)
                    continue
                lost = None
                try:
                    n = await _send_step(client, account_id, fan_id, mass_run_id,
                                         step, texts, is_ppv,
                                         media=step_media, previews=step_previews,
                                         typing_wpm=typing_wpm,
                                         typing_indicator=typing_indicator,
                                         strip_emoji_on=strip_emoji_on)
                except run_slot.SlotLost as e:
                    # The run lost its slot: not this fan's failure, stop the run.
                    # Part of the step landed → it counts as sent (advance, cooldown)
                    # first, so the next run does not send it again.
                    if not e.sent:
                        raise
                    lost, n = e, e.sent
                except Exception as e:
                    errors += 1
                    # Permanent (deleted/blocked) → quarantine fleet-wide AND end
                    # THIS funnel state — it stays due forever otherwise, regenerating
                    # the step texts (an LLM call) every tick. Transients stay
                    # pending and retry when next due.
                    if await skip_unreachable_fan(account_id, fan_id, e, log=log):
                        entry, _fx = fd.decide(entry, fd.Unreachable(now), script)
                        await _perform(cs, entry, _fx)
                    log.warning("reply_mass_funnel send failed account=%s fan=%s step=%s",
                                account_id, fan_id, c, exc_info=True)
                    continue
                if n == 0:
                    errors += 1
                    continue

                # Advance the state machine + schedule the next reply-check: the
                # step just sent picks the next one (a reply keyword, a purchase,
                # `default`, else +1); a routeless PPV hands off (done).
                entry, _fx = fd.decide(entry, fd.Sent(now, facts), script)
                await _perform(cs, entry, _fx)
                advanced += 1
                sent_ok = True
                if lost is not None:
                    raise lost
            finally:
                # W3 (paced-funnel variant): on a confirmed step send set the
                # SHORT cooldown then RELEASE the lease, so the next step (due in
                # 2-10 min via next_check_at) isn't blocked by a 30-min rest or a
                # 900s lease. Cooldown is committed BEFORE release so it guards the
                # moment the lease drops; on a cooldown-write failure KEEP the
                # lease (900s) as the fallback guard.
                if sent_ok:
                    try:
                        await ax.start_fan_cooldown(
                            account_id, fan_id, cooldown_s=_REPLY_COOLDOWN_S
                        )
                        await ax.release_fan_lease(account_id, fan_id)
                    except Exception:
                        log.warning("reply_mass_funnel cooldown set failed account=%s fan=%s "
                                    "— keeping lease as fallback guard",
                                    account_id, fan_id, exc_info=True)
                else:
                    await ax.release_fan_lease(account_id, fan_id)

        if cap_hit or advanced >= max_chats:
            break  # LLM cap or the per-run send cap → stop sweeping further runs

    return {
        "runs": len(runs),
        "discovered": discovered,
        "discovery_skipped": discovery_skipped,
        "advanced": advanced,
        "waiting": fx[fd.Wait()],
        "completed": fx[fd.Complete()],
        "converted": fx[fd.Convert()],
        "branched": fx[fd.Branch()],
        "blocked": fx[fd.Block()],
        "skipped_locked": skipped_locked,
        "skipped_cooldown": skipped_cooldown,
        "audience_mode": _audience_pol.mode,
        "audience_skipped": audience_skipped,
        "errors": errors,
        "cap_hit": cap_hit,
        "dry_run": dry_run,
        "model": model,
        **({"key_error": key_error} if key_error else {}),
    }
