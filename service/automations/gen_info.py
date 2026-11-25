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

_PURPOSE = "gen_info"
_MAX_CONCURRENCY = 4
_DEFAULT_FAN_LIMIT = 200

# a paying fan with thin local history was never deep-scraped (WS pump only sees live traffic): scrape and defer profiling instead of burning an LLM call on empty input
_THIN_HISTORY_MSG_FLOOR = 30
_THIN_HISTORY_MIN_SPEND_CENTS = 100
_SCRAPE_REFRESH_AGE = timedelta(days=7)
_AUTOSCRAPE_BATCH_MAX = 25

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


async def fan_cadence_knobs(s, account_id: str, fan_id: int, now: datetime,
                            *, lifetime_spend_cents: int | None = None) -> tuple:
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
            if direction == "in" and is_substantive_msg(text):
                c.fan_msg_n += 1
            if direction == "out" and is_paid and (price_cents or 0) > 0:
                c.spend_cents += int(price_cents or 0)
            c.messages.append((direction, text))

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
    nickname = plan.profile_set["nickname"]
    fact_update: dict[str, Any] = {**plan.fan_set, **plan.facts, **plan.events}

    async with get_session() as s:
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
        fans_upd: dict[str, Any] = dict(fact_update)
        if plan.write_lang:
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
    if not nick or "/" not in nick:
        nick = ""
    # 200 pinned explicitly: this PUTs to OnlyFans
    notes = build_facts_note(facts_from_fan(ftmp), max_len=200, short_bio=short_bio)
    current = str(c.known.get("notes") or "").strip()
    if notes and current and current != str(c.known.get("applied_notes") or "").strip():
        notes = ""
    if notes and notes == current:
        notes = ""
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



async def _existing_profiles(
    account_id: str, fan_ids: list[int]
) -> dict[int, tuple[int, datetime | None]]:
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



async def _enqueue_thin_fan_scrapes(
    account_id: str, candidates: list[gen_info_plan.Candidate], force_ids: set[int], now: datetime
) -> set[int]:
    thin = [
        c for c in candidates
        if c.fan_id not in force_ids
        and c.fan_msg_n < _THIN_HISTORY_MSG_FLOOR
        and c.spend_cents > _THIN_HISTORY_MIN_SPEND_CENTS
    ]
    if not thin:
        return set()

    fresh_cutoff = now - _SCRAPE_REFRESH_AGE
    async with get_session() as s:
        rows = (await s.execute(
            select(ScrapeHistory.fan_id, ScrapeHistory.last_scrape_at,
                   ScrapeHistory.history_deferred_at).where(
                ScrapeHistory.account_id == account_id,
                ScrapeHistory.fan_id.in_([c.fan_id for c in thin]),
            )
        )).all()
    hist = {int(fid): at for fid, at, _held in rows}
    held_back = {int(fid) for fid, _at, held in rows if held is not None}
    to_scrape = [
        c.fan_id for c in thin
        if (at := hist.get(c.fan_id)) is None or at < fresh_cutoff
    ]
    if not to_scrape:
        return set()

    import automation_executor as ax
    import webhook_dispatch
    queued: set[int] = set()
    plain: list[int] = []
    for fid in to_scrape:
        if fid not in held_back:
            plain.append(fid)
        elif await webhook_dispatch.enqueue_fan_scrape(account_id, fid, webhook_dispatch.GEN_INFO_PICK_SOURCE):
            queued.add(fid)
        if len(plain) + len(queued) >= _AUTOSCRAPE_BATCH_MAX:
            break
    if plain:
        await ax.enqueue_job(account_id, "scrape_chats", payload={"fan_ids": plain})
    queued.update(plain)
    log.info("gen_info_autoscrape account=%s deferred=%d fans=%s",
             account_id, len(queued), sorted(queued))
    return queued


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
    provider = llm_client.MODELS[model].provider
    if not await llm_client.llm_key_available(account_id, provider, _PURPOSE):
        return {"no_llm_key": provider, "candidates": 0, "generated": 0}

    now = datetime.utcnow()
    candidates = await _gather_candidates(account_id, force_ids, limit, now)
    if refill_ids:
        candidates = [c for c in candidates if c.fan_id in refill_ids]

    deferred = await _enqueue_thin_fan_scrapes(account_id, candidates, force_ids, now)
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
    key_error = None

    of_client = None
    if todo:
        try:
            import automation_executor as ax
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
