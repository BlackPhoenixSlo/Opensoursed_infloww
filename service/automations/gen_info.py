"""service/automations/gen_info.py — Automation 02: fan-profile generation.

Spec: library/one_section_of_automations/02_gen_info.md (network-rewrite mapping at
the bottom — the DOM/JSON-file world is replaced by DB reads + llm_client).

What it does, per tick (`run(account_id, payload, *, run_id)`):

  1. Read the account's fans + their messages from OUR DB (no OF traffic; the WS
     pump + scrape_chats already filled `messages`/`fans`). of_client is never
     touched here — gen_info is pure backend.
  2. Qualify a fan: ≥ 7 fan messages OR ≥ $1 lifetime spend (legacy gate ported
     to cents). `payload.force_ids` bypasses the gate (process_old_fans path).
  2b. Auto-scrape guard: a PAYING fan with thin LOCAL history (we never deep-
     scraped them — the WS pump only sees live traffic) is deferred this pass and
     a one-fan `scrape_chats` is enqueued, so the next pass profiles on the real
     transcript instead of emitting "<name>/Whale" with no facts. See the
     `_THIN_HISTORY_*` knobs + `_enqueue_thin_fan_scrapes`.
  3. Re-run gate: skip a fan whose `fan_profiles` row is still fresh — only
     regenerate when their message count has grown ≥ 22% since the last gen
     (legacy 1.22× factor). `force_ids` bypasses this too.
  4. For each qualifying fan call `llm_client.chat(... response_format=
     json_object ...)` — which writes the `grok_calls` audit row itself (pending
     → done/error) and enforces the per-account/provider daily soft-cap — and
     parse the structured profile.
  5. Persist: upsert the `fan_profiles` row (nickname / short_bio /
     bullet_points / original_name + the generating grok_calls id) AND write the
     AI-extracted facts back onto the `fans` row (real_name / age / location /
     hobbies / occupation / … + grok_facts_updated_at).
  6. Push the fan's info to the drawer's tabs on OF (`_sync_of_fan_info`): the
     structured nickname (displayName) and the fact-sheet Fan notes (notice).

No Q&A: gen_info no longer asks for or writes the Q1-3 / Tease1-3 opener lines.
Lines already stored stay on the row untouched; nothing refills them.

Split: the pure rules (selection, prompt, nickname guard, facts/events/language
decisions → `plan_persist`) live in gen_info_plan.py; this module does the IO.

Concurrency: fans are processed with a bounded `asyncio.Semaphore` (cap 5, the
legacy ThreadPoolExecutor width). Each fan's DB write uses its OWN AsyncSession —
never a shared one across gather() branches (the SQLAlchemy parallel-session
footgun). The daily-spend cap is serialized inside llm_client's atomic reserve,
so gen_info does NOT need the executor's account_spend_lock.

Scheduling: this self-registers via `@register("gen_info")` on import (the
executor auto-imports `service/automations/*`). To run it periodically, insert an
`automation_rules` row with `kind="gen_info"` and
`trigger_json={"every_seconds": N}`; the executor's generic `_materialize_due_rules`
turns it into a `scheduled_jobs` row each cycle (after scrape_chats has refreshed
the messages). NO edit to automation_executor.py.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from automation_registry import register
from db.engine import get_session
from db.models import AccountAiConfig, Fan, FanProfile, Message, ScrapeHistory, Transaction
import llm_client
from llm_client import LLMCapExceeded, LLMError
from ._fan_notes import build_facts_note, facts_from_fan, push_nick_and_notes
from ._knobs import coerce_ids
from ._model_pick import resolve_model
from ._skiplist import load_promo_spam_ids
from ._textutil import is_substantive_msg
from .names import build_structured_nickname
from . import gen_info_plan

log = logging.getLogger("of-relay.automation.gen_info")

# ── Knobs (ported from 02_gen_info.md) ───────────────────────────────
_PURPOSE = "gen_info"
_MAX_CONCURRENCY = 4             # background fan-out cap (≤4 — never block proxy/LLM)
_DEFAULT_FAN_LIMIT = 200         # sweep ceiling when no force_ids

# Auto-scrape guard. A PAYING fan with thin LOCAL history is almost always a fan we
# never deep-scraped: the WS pump only captures live traffic, so a whale who chatted
# before we connected looks empty in our DB and profiles as "<name>/Whale" with no
# facts (the Alex Nielsen case — 1 inbound msg locally, 200 on OF). When a candidate
# has < _THIN_HISTORY_MSG_FLOOR inbound messages AND > _THIN_HISTORY_MIN_SPEND_CENTS
# lifetime spend, enqueue a one-fan scrape_chats and DEFER profiling them this pass —
# don't burn an LLM call on near-empty input; the NEXT pass profiles on the real
# transcript. Gated on scrape_history so we never loop: a fan deep-scraped within
# _SCRAPE_REFRESH_AGE is left alone (if it's STILL thin after a scrape, OF genuinely
# has little, so we profile it honestly with what we have). Forced ids are never
# auto-scraped — an explicit force means "profile now with whatever is here".
_THIN_HISTORY_MSG_FLOOR = 30          # < this many inbound msgs locally = thin
_THIN_HISTORY_MIN_SPEND_CENTS = 100   # > $1 lifetime spend → a paying fan worth scraping
_SCRAPE_REFRESH_AGE = timedelta(days=7)
_AUTOSCRAPE_BATCH_MAX = 25            # cap scrapes enqueued per pass (highest-spend first)

# The structured fields Grok must return. Profile fields land in fan_profiles;
# fact fields are written back onto the fans row.
_SYSTEM_PROMPT = (
    "You build a concise CRM profile of an OnlyFans fan from their chat history "
    "with the creator. You may be given KNOWN INFO already confirmed about him — "
    "treat it as ground truth and BUILD ON it (confirm/refine from the chat, never "
    "drop a known fact). Respond with a SINGLE JSON object and nothing else. Use an "
    "empty string (or [] for lists) for anything you cannot determine — never guess, "
    'never write "Unknown" or "??". Keys:\n'
    '  "nickname": slash-joined tag "Name/City,Country/Age/Job" (<=60 chars). '
    "The Name MUST be his real first name (from the chat or the KNOWN real name). "
    "NEVER use a number, a fan id, a u<digits> handle, a username, or a PLACE "
    "(country/state/city — those belong in the second section) as the Name — "
    "leave the Name section EMPTY if you don't know it. Leave any unknown section "
    'EMPTY (no "??", no filler), e.g. "Garrett/Delta,Canada/30/Paramedic". '
    "NEVER add a spend/status label (Free, Buyer, Spender, Whale, VIP) — his "
    "spending is not part of his name.\n"
    '  "short_bio": one sentence describing who he is and his spending,\n'
    '  "bullet_points": markdown "- Label: value" lines, MOST USEFUL FIRST with '
    'SHORT labels. Lead with "Recent:" (what is going on in his life lately), then '
    '"Intr:" (hobbies/interests), then "Important:" (what matters most about him — '
    'what he wants, gripes/complaints, pay day). Then "Job:", "Rel:" (relationship), '
    '"Kinks:". OMIT his name, age and location (those are already in the nickname) '
    "and his lifetime spend (shown elsewhere),\n"
    '  "original_name": his real first name if stated, else "" (never "Unknown"),\n'
    '  "real_name": same as original_name,\n'
    '  "his_age": his age as a string (ONLY if he stated it; "" if unknown — never guess),\n'
    '  "home_country": his country (only if stated, or obvious from a city he named; "" otherwise),\n'
    '  "home_city": his city (ONLY a city he actually named; "" if not stated — do NOT guess one from the country),\n'
    '  "hobbies": comma-separated interests he actually mentioned ("" if none — do NOT invent),\n'
    '  "occupation": his job (only if stated; ""),\n'
    '  "relationship_status": single/married/etc (only if stated; ""),\n'
    '  "fetishes": comma-separated kinks he mentioned ("" if none),\n'
    '  "recent_events": a JSON array of short strings — things happening in his life '
    "lately (trip, new job, breakup, birthday, holiday); [] if none.\n"
    # ── Richer facts (appended at the END so the stable prompt prefix — and its
    #    DeepSeek cache — is untouched). Same never-guess discipline. ──
    '  "employer": the company/place he works (ONLY if named; ""),\n'
    '  "partner_name": his partner\'s name (ONLY if he named one; ""),\n'
    '  "relationship_stage": where things stand with YOU the creator (e.g. new/regular/'
    'devoted/cooling) — ONLY if the chat clearly shows it; "" otherwise,\n'
    '  "has_kids": true or false ONLY if he clearly stated it; otherwise the empty '
    'string "" (never guess),\n'
    '  "pets": a JSON array of short strings like "dog Toby" for pets he mentioned; [] '
    "if none (do NOT invent),\n"
    '  "communication_style": a JSON object with any of {"chatty":true/false,'
    '"kink_forward":true/false,"romantic":true/false,"blunt":true/false} you can '
    "actually tell from how he writes; {} if unsure,\n"
    '  "language": the ISO 639-1 code (two letters, e.g. "en", "es", "pt") of the '
    "language HE writes in — judge from his own messages, not yours. If he mixes "
    'languages, pick the dominant one. "" if you truly cannot tell.\n'
    "\nCRITICAL: only record facts the fan ACTUALLY stated in the chat. If something "
    "wasn't said, leave it EMPTY — never guess or infer (don't guess a city from a "
    "country, don't invent hobbies or a job he never mentioned).\n"
)

# ── Pure half lives in gen_info_plan; the old private names that other modules /
#    tests still import are kept as aliases. IO code below reads `gen_info_plan.X`.
_MIN_NEW_MSGS = gen_info_plan.MIN_NEW_MSGS
_CADENCE_PAYING = gen_info_plan.CADENCE_PAYING
_CADENCE_MIDDLE = gen_info_plan.CADENCE_MIDDLE
_CADENCE_COLD = gen_info_plan.CADENCE_COLD
_Candidate = gen_info_plan.Candidate
_clean_nickname = gen_info_plan.clean_nickname
_guard_name = gen_info_plan.guard_name
_name_hint = gen_info_plan.name_hint
_tier_knobs = gen_info_plan.tier_knobs
profile_is_stale = gen_info_plan.profile_is_stale
_known_block = gen_info_plan.known_block
select_candidates = gen_info_plan.select_candidates
_trim_messages = gen_info_plan.trim_messages
_build_user_prompt = gen_info_plan.build_user_prompt
_PROFILE_KEEP_IF_EMPTY = gen_info_plan.PROFILE_KEEP_IF_EMPTY


async def fan_cadence_knobs(s, account_id: str, fan_id: int, now: datetime,
                            *, lifetime_spend_cents: int | None = None) -> tuple:
    """(fresh_after, volume_cap) for one fan, classified from the DB on an open
    session `s` — the per-fan analogue of the batch tier computation the sweep does
    inline. Reads lifetime spend + subscribed_at off the fans row and sums CLEARED
    spend in the last gen_info_plan.RECENT_SPEND_WINDOW. Used by welcome_chatter_for_info's refresh hook."""
    fan_id = int(fan_id)
    if lifetime_spend_cents is None:
        frow = (await s.execute(
            select(Fan.lifetime_spend_cents, Fan.subscribed_at)
            .where(Fan.account_id == str(account_id), Fan.fan_id == fan_id)
        )).first()
        lifetime_spend_cents = int(frow[0] or 0) if frow else 0
        subscribed_at = frow[1] if frow else None
    else:
        subscribed_at = (await s.execute(
            select(Fan.subscribed_at)
            .where(Fan.account_id == str(account_id), Fan.fan_id == fan_id)
        )).scalar()
    recent = (await s.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.account_id == str(account_id),
               Transaction.fan_id == fan_id,
               Transaction.status == "cleared",
               Transaction.occurred_at >= now - gen_info_plan.RECENT_SPEND_WINDOW)
    )).scalar() or 0
    return gen_info_plan.tier_knobs(int(lifetime_spend_cents), int(recent), subscribed_at, now)


async def _gather_candidates(
    account_id: str, force_ids: set[int], limit: int, now: datetime
) -> list[gen_info_plan.Candidate]:
    """One pass over the account's messages → per-fan counts + trimmed history.

    Spend is summed from PURCHASED outbound PPV/tips (legacy `sender==Model and
    is_paid`). Fan-message count is inbound messages. The fan's display name +
    subscribed_at + recent cleared spend are lifted for the cadence tiering. Returns
    candidates that pass the qualification gate (or are forced)."""
    counts: dict[int, gen_info_plan.Candidate] = {}
    async with get_session() as s:
        rows = (
            await s.execute(
                select(
                    Message.fan_id,
                    Message.direction,
                    Message.body,
                    Message.price_cents,
                    Message.is_paid,
                    Message.is_tip,
                )
                .where(Message.account_id == account_id)
                .order_by(Message.fan_id, Message.created_at)
            )
        ).all()

        for fan_id, direction, body, price_cents, is_paid, is_tip in rows:
            c = counts.get(fan_id)
            if c is None:
                c = counts[fan_id] = gen_info_plan.Candidate(int(fan_id))
            c.total_msg_n += 1
            text = gen_info_plan.strip_html(body)[:gen_info_plan.MSG_CLIP]
            # Count only substantive inbound (matches welcome_chatter_for_info): emoji-only
            # reactions don't inflate fan_msg_n, so message_count_at_gen and the
            # welcome_chatter_for_info staleness baseline stay on ONE scale (no suppressed/false
            # refreshes for emoji-heavy fans).
            if direction == "in" and is_substantive_msg(text):
                c.fan_msg_n += 1
            if direction == "out" and is_paid and (price_cents or 0) > 0:
                c.spend_cents += int(price_cents or 0)
            c.messages.append((direction, text))

        # Lift display name + username + prior extracted facts (ground truth, W2h)
        # + subscribed_at (tiering) onto the fans we care about — ONE DB read, no OF
        # call (proxy-safe). A fan with no fans row keeps the Candidate defaults.
        if counts:
            frows = (await s.execute(
                select(
                    Fan.fan_id, Fan.of_display_name, Fan.of_username,
                    Fan.real_name, Fan.his_age, Fan.home_city, Fan.home_country,
                    Fan.hobbies, Fan.occupation, Fan.relationship_status,
                    Fan.fetishes, Fan.recent_events, Fan.recent_events_timeline,
                    Fan.generated_nickname,
                    Fan.custom_nickname, Fan.source, Fan.is_muted, Fan.subscribed_at,
                    Fan.notes, Fan.applied_notes,
                ).where(
                    Fan.account_id == account_id,
                    Fan.fan_id.in_(list(counts)),
                )
            )).all()
            for r in frows:
                c = counts.get(int(r.fan_id))
                if c is None:
                    continue
                c.known = {
                    "of_display_name": r.of_display_name or "",
                    "of_username": r.of_username or "",
                    "real_name": r.real_name or "",
                    "his_age": r.his_age or "",
                    "home_city": r.home_city or "",
                    "home_country": r.home_country or "",
                    "hobbies": r.hobbies or "",
                    "occupation": r.occupation or "",
                    "relationship_status": r.relationship_status or "",
                    "fetishes": r.fetishes or "",
                    "recent_events": r.recent_events or "[]",
                    "recent_events_timeline": r.recent_events_timeline or "[]",
                    "generated_nickname": r.generated_nickname or "",
                    "custom_nickname": r.custom_nickname or "",
                    "notes": r.notes or "",
                    "applied_notes": r.applied_notes or "",
                    "source": r.source or "",
                    "is_muted": bool(r.is_muted),
                }
                c.of_name = c.known["of_display_name"]
                c.of_username = c.known["of_username"]
                c.source = c.known["source"]
                c.is_muted = c.known["is_muted"]
                c.subscribed_at = r.subscribed_at

        # Lifetime spend from the transactions ledger (cleared, fan-attributed) is
        # more accurate than the message-derived PPV/tips sum, so take the HIGHER of
        # the two — a fan's true spend is at least whatever either source shows
        # ("usually the higher wins"). Same session, sequential read (not gather()).
        if counts:
            txrows = (await s.execute(
                select(Transaction.fan_id, func.sum(Transaction.amount_cents))
                .where(Transaction.account_id == account_id)
                .where(Transaction.status == "cleared")
                .where(Transaction.fan_id.is_not(None))
                .where(Transaction.fan_id.in_(list(counts)))
                .group_by(Transaction.fan_id)
            )).all()
            for fid, total in txrows:
                c = counts.get(int(fid))
                if c is not None:
                    c.spend_cents = max(c.spend_cents, int(total or 0))

        # Recent cleared spend (last gen_info_plan.RECENT_SPEND_WINDOW) → the "paying" cadence tier.
        if counts:
            txrecent = (await s.execute(
                select(Transaction.fan_id, func.sum(Transaction.amount_cents))
                .where(Transaction.account_id == account_id)
                .where(Transaction.status == "cleared")
                .where(Transaction.fan_id.is_not(None))
                .where(Transaction.fan_id.in_(list(counts)))
                .where(Transaction.occurred_at >= now - gen_info_plan.RECENT_SPEND_WINDOW)
                .group_by(Transaction.fan_id)
            )).all()
            for fid, total in txrecent:
                c = counts.get(int(fid))
                if c is not None:
                    c.recent_spend_cents = int(total or 0)

    promo_spam = await load_promo_spam_ids(account_id)
    return gen_info_plan.select_candidates(counts, force_ids=force_ids, limit=limit,
                                           promo_spam=promo_spam)


async def _persist(
    account_id: str, c: gen_info_plan.Candidate, plan: gen_info_plan.PersistPlan,
    now: datetime, *, client=None
) -> None:
    """Write one fan's `plan` (from gen_info_plan.plan_persist): upsert fan_profiles +
    the extracted facts onto the fans row, in ONE fresh session (never shared across
    gather branches). When `client` is given, also (re)assert the structured OF
    nickname so the chat-header name stays in sync — see _sync_of_fan_info.

    The race-safe rules stay SQL here, comparing against the row AS STORED:
    keep-if-empty (`gen_info_plan.PROFILE_KEEP_IF_EMPTY`) and the operator language
    pin (`gen_info_plan.MANUAL_LANGUAGE_SOURCES`)."""
    nickname = plan.profile_set["nickname"]
    fact_update: dict[str, Any] = {**plan.fan_set, **plan.facts, **plan.events}

    async with get_session() as s:
        # FIX-2: for the content columns, KEEP the stored value when the LLM returned
        # an empty/NULL one — a sparse (~7%) response must not wipe a fan's nickname /
        # bio. Metadata columns (counts, timestamps, call id) always take the new value.
        prof_stmt = sqlite_insert(FanProfile).values(
            account_id=str(account_id), fan_id=int(c.fan_id), **plan.profile_set)
        prof_set: dict[str, Any] = {}
        keep_if_empty = gen_info_plan.PROFILE_KEEP_IF_EMPTY
        for k in plan.profile_set:
            new_val = prof_stmt.excluded[k]
            if k in keep_if_empty:
                prof_set[k] = case(
                    (or_(new_val.is_(None), new_val == ""), getattr(FanProfile, k)),
                    else_=new_val,
                )
            else:
                prof_set[k] = new_val
        await s.execute(
            prof_stmt.on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=prof_set
            )
        )
        # The fans row exists (scrape/WS created it); guard anyway with an upsert
        # carrying identity-safe defaults so gen_info never fails on a stray fan.
        fans_upd: dict[str, Any] = dict(fact_update)
        if plan.write_lang:
            # FIX-3, per-column: keep the operator's pin when language_source is an
            # operator-pinned source (MANUAL_LANGUAGE_SOURCES); otherwise record the AI
            # observation. Bare `Fan.language*` = the EXISTING row's value in an ON
            # CONFLICT DO UPDATE set_.
            manual = Fan.language_source.in_(gen_info_plan.MANUAL_LANGUAGE_SOURCES)
            fans_upd["language"] = case((manual, Fan.language), else_=plan.write_lang)
            fans_upd["language_source"] = case((manual, Fan.language_source), else_="ai")
        await s.execute(
            sqlite_insert(Fan)
            .values(
                account_id=str(account_id),
                fan_id=int(c.fan_id),
                generated_nickname=nickname,
                grok_facts_updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=fans_upd
            )
        )

    if client is not None:
        await _sync_of_fan_info(client, account_id, c, fact_update,
                                short_bio=plan.profile_set["short_bio"] or "")


async def _sync_of_fan_info(
    client, account_id: str, c: gen_info_plan.Candidate, fact_update: dict[str, Any], *,
    short_bio: str = "",
) -> None:
    """Push the fan's info to the two drawer fields OF stores, after a profile regen:

      • Nickname   — OF `displayName`, the structured Name/City,Country/Age/Job,
                     built by the SAME canonical builder the senders use.
      • Fan notes  — OF `notice`, the 200-char fact sheet (Recent / Intr / Job / Rel /
                     Kinks, then the short bio), the same `build_facts_note` text
                     apply_profiles and welcome_chatter_for_info write.

    Both go through `push_nick_and_notes` (separate PUT /subscriptions/{id} calls, so
    a non-subscriber's note 404 can't sink the nickname; it mirrors what stuck into
    fans.custom_nickname / fans.notes). The drawer's other Profile cells (Location,
    Language) read the fans columns `_persist` just wrote, so they need no push.

    The nickname is re-pushed on every regen of a STRUCTURED nickname (>= 2 segments)
    so drift is corrected; bare-name-only nicknames are skipped (OF already falls back
    to the profile name). The note is pushed only when the stored note is empty or is
    the one gen_info last wrote (`fans.applied_notes`), so a note a chatter typed in
    the drawer is never overwritten. Best-effort — never breaks the gen_info run.

    `fact_update` carries the freshly-written column values; we overlay them on
    `c.known` so both reflect facts found THIS run."""
    def _val(col: str) -> str:
        v = fact_update.get(col)
        if isinstance(v, str) and v.strip():
            return v.strip()
        return str(c.known.get(col) or "").strip()

    ftmp = Fan(
        account_id=str(account_id), fan_id=int(c.fan_id),
        real_name=_val("real_name"),
        his_age=_val("his_age"),
        home_country=_val("home_country"),
        home_city=_val("home_city"),
        occupation=_val("occupation"),
        hobbies=_val("hobbies"),
        relationship_status=_val("relationship_status"),
        fetishes=_val("fetishes"),
        recent_events=_val("recent_events") or "[]",
        custom_nickname=str(c.known.get("custom_nickname") or "").strip(),
        of_display_name=str(c.known.get("of_display_name") or "").strip(),
    )
    nick = build_structured_nickname(ftmp)
    # Only push a genuinely STRUCTURED name (has at least one fact beyond the name).
    if not nick or "/" not in nick:
        nick = ""
    # 200 pinned EXPLICITLY, as welcome_chatter_for_info does: this PUTs to OnlyFans.
    notes = build_facts_note(facts_from_fan(ftmp), max_len=200, short_bio=short_bio)
    current = str(c.known.get("notes") or "").strip()
    if notes and current and current != str(c.known.get("applied_notes") or "").strip():
        notes = ""                         # a chatter's own note: leave it alone
    if notes and notes == current:
        notes = ""                         # already on OF — skip the PUT
    if not nick and not notes:
        return
    try:
        _nick_ok, note_ok = await push_nick_and_notes(
            client, account_id, int(c.fan_id), nick=nick, notes=notes)
    except Exception:
        log.debug("gen_info of-fan-info push failed account=%s fan=%s",
                  account_id, c.fan_id, exc_info=True)
        return
    if note_ok:
        # Remember the note as OURS, so the next regen may replace it.
        now = datetime.utcnow()
        async with get_session() as s:
            await s.execute(
                sqlite_insert(Fan)
                .values(account_id=str(account_id), fan_id=int(c.fan_id),
                        applied_notes=notes, applied_notes_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_={"applied_notes": notes, "applied_notes_at": now},
                )
            )


# ── Re-run gate ──────────────────────────────────────────────────────

async def _existing_profiles(
    account_id: str, fan_ids: list[int]
) -> dict[int, tuple[int, datetime | None]]:
    """(message_count_at_gen, last_generated_at) of existing fan_profiles rows —
    feeds the re-run gate (`profile_is_stale`)."""
    if not fan_ids:
        return {}
    async with get_session() as s:
        rows = (
            await s.execute(
                select(
                    FanProfile.fan_id,
                    FanProfile.message_count_at_gen,
                    FanProfile.last_generated_at,
                ).where(
                    FanProfile.account_id == account_id,
                    FanProfile.fan_id.in_(fan_ids),
                )
            )
        ).all()
    return {int(fid): (int(cnt or 0), gen_at) for fid, cnt, gen_at in rows}


# ── The automation entry point ───────────────────────────────────────

async def _enqueue_thin_fan_scrapes(
    account_id: str, candidates: list[gen_info_plan.Candidate], force_ids: set[int], now: datetime
) -> set[int]:
    """Prevent "<name>/Whale with no facts": find PAYING fans with thin LOCAL history
    that we've never (recently) deep-scraped, enqueue a one-shot `scrape_chats` for
    them, and return their fan_ids so run() DEFERS profiling them this pass. See the
    _THIN_HISTORY_* / _SCRAPE_REFRESH_AGE knobs. Returns only the fans actually
    enqueued — a thin fan already scraped within the cooldown is left to profile
    normally (OF genuinely has little for them)."""
    thin = [
        c for c in candidates
        if c.fan_id not in force_ids
        and c.fan_msg_n < _THIN_HISTORY_MSG_FLOOR
        and c.spend_cents > _THIN_HISTORY_MIN_SPEND_CENTS
    ]
    if not thin:
        return set()

    # Don't re-enqueue a fan we just scraped — a thin fan stays thin until the scrape
    # lands, and scrape jobs, while idempotent (ScrapeHistory fast-skip), aren't free.
    fresh_cutoff = now - _SCRAPE_REFRESH_AGE
    async with get_session() as s:
        hist = {
            int(fid): at
            for fid, at in (await s.execute(
                select(ScrapeHistory.fan_id, ScrapeHistory.last_scrape_at).where(
                    ScrapeHistory.account_id == account_id,
                    ScrapeHistory.fan_id.in_([c.fan_id for c in thin]),
                )
            )).all()
        }
    # `thin` preserves the candidate order (spend desc), so the highest-value fans are
    # scraped first; the rest get picked up on later passes — keeps any one job bounded.
    to_scrape = [
        c.fan_id for c in thin
        if (at := hist.get(c.fan_id)) is None or at < fresh_cutoff
    ][:_AUTOSCRAPE_BATCH_MAX]
    if not to_scrape:
        return set()

    import automation_executor as ax  # lazy: avoid an import cycle at module load
    await ax.enqueue_job(account_id, "scrape_chats", payload={"fan_ids": to_scrape})
    log.info("gen_info_autoscrape account=%s deferred=%d fans=%s",
             account_id, len(to_scrape), to_scrape)
    return set(to_scrape)


@register("gen_info")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Generate/refresh fan_profiles for the qualifying fans of one account.

    payload:
      force_ids:  [fan_id, …]  bypass qualification + re-run gates.
      refill_ids: [fan_id, …]  narrow the sweep to JUST these ids but still run the
                               GATED check (profile_is_stale) — used by
                               welcome_chatter_for_info's refresh-if-stale hook. Unlike
                               force_ids it does NOT bypass the new-message guard,
                               so a refill with nothing new no-ops.
      limit:      int          sweep ceiling (default 200).
      model:      str          override the resolved model for this run.
    """
    payload = payload or {}
    force_ids = coerce_ids(payload.get("force_ids"))
    refill_ids = coerce_ids(payload.get("refill_ids"))
    limit = int(payload.get("limit") or _DEFAULT_FAN_LIMIT)
    model = await resolve_model(account_id, _PURPOSE, payload.get("model"))
    provider = llm_client.MODELS[model].provider  # no key → skip the run, as autoreply does
    if not await llm_client.llm_key_available(account_id, provider, _PURPOSE):
        return {"no_llm_key": provider, "candidates": 0, "generated": 0}

    now = datetime.utcnow()
    candidates = await _gather_candidates(account_id, force_ids, limit, now)
    # Refill path: narrow to just the requested ids; they still go through the gated
    # stale check below (NOT forced) so a refill with no new messages no-ops instead
    # of burning an LLM call.
    if refill_ids:
        candidates = [c for c in candidates if c.fan_id in refill_ids]

    # Prevention: paying fans with thin local history get a deep-scrape enqueued and
    # are deferred from this pass (profiled next pass on the real transcript).
    deferred = await _enqueue_thin_fan_scrapes(account_id, candidates, force_ids, now)
    # Re-run gate (skipped for forced ids): needs >= _MIN_NEW_MSGS new inbound msgs,
    # then regenerates on the fan's spend-tiered time window or new-message volume cap.
    prior = await _existing_profiles(account_id, [c.fan_id for c in candidates])
    todo: list[gen_info_plan.Candidate] = []
    skipped_fresh = 0
    for c in candidates:
        if c.fan_id in deferred:
            continue
        if c.fan_id in force_ids:
            todo.append(c)
            continue
        stored = prior.get(c.fan_id)
        prev_count = stored[0] if stored else None
        last_gen_at = stored[1] if stored else None
        fresh_after, volume_cap = gen_info_plan.tier_knobs(
            c.spend_cents, c.recent_spend_cents, c.subscribed_at, now)
        if gen_info_plan.profile_is_stale(prev_count, last_gen_at, c.fan_msg_n, now,
                            fresh_after=fresh_after, volume_cap=volume_cap):
            todo.append(c)
        else:
            skipped_fresh += 1
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    generated = 0
    capped = 0
    failed = 0
    key_error = None  # a rejected key ends the pass: no call per remaining fan

    # OF client for the nickname + Fan notes push (best-effort). gen_info is
    # otherwise OF-free; build it once and only when there's work, so a sweep that
    # regenerates nothing never touches OF.
    of_client = None
    if todo:
        try:
            import automation_executor as ax  # lazy: avoid an import cycle at load
            of_client = await asyncio.to_thread(ax._make_client, account_id)
        except Exception:
            log.debug("gen_info of-client init failed account=%s", account_id,
                      exc_info=True)

    async def _one(c: gen_info_plan.Candidate) -> None:
        nonlocal generated, capped, failed, key_error
        async with sem:
            if key_error:
                return
            try:
                result = await llm_client.chat(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": gen_info_plan.build_user_prompt(c)},
                    ],
                    purpose=_PURPOSE,
                    account_id=account_id,
                    fan_id=c.fan_id,
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            except LLMCapExceeded:
                capped += 1
                log.info("gen_info_capped account=%s fan=%s", account_id, c.fan_id)
                return
            except llm_client.LLMKeyError as e:
                key_error = llm_client.key_error_payload(e)
                return
            except LLMError:
                failed += 1
                log.warning("gen_info_llm_failed account=%s fan=%s",
                            account_id, c.fan_id, exc_info=True)
                return

            data = result.parsed if isinstance(result.parsed, dict) else None
            if data is None:
                failed += 1
                log.warning("gen_info_unparseable account=%s fan=%s call_id=%s",
                            account_id, c.fan_id, result.call_id)
                return
            try:
                plan = gen_info_plan.plan_persist(c, data, call_id=result.call_id, now=now)
                await _persist(account_id, c, plan, now, client=of_client)
                generated += 1
            except Exception:
                failed += 1
                log.warning("gen_info_persist_failed account=%s fan=%s",
                            account_id, c.fan_id, exc_info=True)

    if todo:
        await asyncio.gather(*(_one(c) for c in todo))

    return {
        "candidates": len(candidates),
        "deferred_for_scrape": len(deferred),
        "skipped_fresh": skipped_fresh,
        "attempted": len(todo),
        "generated": generated,
        "capped": capped,
        "failed": failed,
        "model": model,
        **({"key_error": key_error} if key_error else {}),
    }
