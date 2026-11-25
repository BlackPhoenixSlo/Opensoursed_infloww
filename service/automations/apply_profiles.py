from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from automation_registry import register
from db.engine import get_session
from db.models import Blacklist, Fan, FanProfile
from of_client import OFClient
from ._common import build_facts_note, coerce_ids
from .names import strip_spend_tier

log = logging.getLogger("of-relay.automation.apply_profiles")

# OF's note textarea maxlength.
_NOTES_MAX = 200
_COOLDOWN = timedelta(hours=24)
_DEFAULT_LIMIT = 500

_OF_PUSH_SUPPORTED = True

_SLASH_RE = re.compile(r"/{2,}")
_WS_RE = re.compile(r"\s+")



def _clean_nickname(s: str | None) -> str:
    if not s:
        return ""
    parts = [p.strip() for p in strip_spend_tier(s).split("/")]
    parts = [p for p in parts if any(ch.isalnum() for ch in p)]
    return _WS_RE.sub(" ", "/".join(parts)).strip()


def _facts_note(prof: "_Prof") -> str:
    return build_facts_note(prof.facts, _NOTES_MAX, short_bio=prof.short_bio)


def _within_cooldown(last_applied_at: datetime | None, now: datetime) -> bool:
    if last_applied_at is None:
        return False
    return (now - last_applied_at) < _COOLDOWN


def _is_up_to_date(prof: "_Prof", target_nick: str, target_notes: str,
                   now: datetime) -> bool:
    return (
        (prof.last_applied_nickname or "") == target_nick
        and (prof.last_applied_notes or "") == target_notes
        and _within_cooldown(prof.last_applied_at, now)
    )



class _Prof:
    __slots__ = ("fan_id", "nickname", "short_bio", "q1", "q2", "q3", "tease1",
                 "tease2", "tease3", "applied_notes", "last_applied_at",
                 "last_applied_nickname", "last_applied_notes", "facts")

    def __init__(self, row: FanProfile):
        self.fan_id = int(row.fan_id)
        self.nickname = row.nickname
        self.short_bio = row.short_bio or ""
        self.q1, self.q2, self.q3 = row.q1, row.q2, row.q3
        self.tease1, self.tease2, self.tease3 = row.tease1, row.tease2, row.tease3
        self.applied_notes = row.applied_notes
        self.last_applied_at = row.last_applied_at
        self.last_applied_nickname = row.last_applied_nickname
        self.last_applied_notes = row.last_applied_notes
        self.facts: dict[str, str] = {}


async def _load_blacklist() -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(select(Blacklist.fan_id))).all()
    return {int(r[0]) for r in rows}


async def _load_profiles(account_id: str, limit: int) -> list[_Prof]:
    async with get_session() as s:
        rows = (await s.execute(
            select(FanProfile)
            .where(FanProfile.account_id == account_id)
            .order_by(FanProfile.fan_id)
            .limit(limit)
        )).scalars().all()
        profs = [_Prof(r) for r in rows]
        if profs:
            frows = (await s.execute(
                select(
                    Fan.fan_id, Fan.real_name, Fan.his_age, Fan.home_city,
                    Fan.home_country, Fan.occupation, Fan.hobbies,
                    Fan.relationship_status, Fan.fetishes, Fan.recent_events,
                ).where(
                    Fan.account_id == account_id,
                    Fan.fan_id.in_([p.fan_id for p in profs]),
                )
            )).all()
            by_id = {int(r.fan_id): r for r in frows}
            for p in profs:
                r = by_id.get(p.fan_id)
                if r is not None:
                    p.facts = {
                        "age": (r.his_age or "").strip(),
                        "job": (r.occupation or "").strip(),
                        "city": (r.home_city or "").strip(),
                        "country": (r.home_country or "").strip(),
                        "hobbies": (r.hobbies or "").strip(),
                        "relationship": (r.relationship_status or "").strip(),
                        "fetishes": (r.fetishes or "").strip(),
                        "recent_events": (r.recent_events or "").strip(),
                    }
    return profs


async def _apply(account_id: str, fan_id: int, target_nick: str,
                 target_notes: str, now: datetime) -> None:
    prof_set: dict = {
        "notes_applied_successfully": bool(target_notes),
        "last_applied_at": now,
        "last_applied_nickname": target_nick or None,
        "last_applied_notes": target_notes or None,
    }
    # applied_notes is sticky: an empty target never clears a previously chosen note.
    if target_notes:
        prof_set["applied_notes"] = target_notes

    # Never writes fans.generated_nickname: gen_info owns it, and writing here would race a regen and clobber a fresher nickname.
    fan_set: dict = {
        "applied_notes": target_notes or None,
        "applied_notes_at": now,
        "updated_at": now,
    }

    async with get_session() as s:
        await s.execute(
            sqlite_insert(FanProfile)
            .values(account_id=str(account_id), fan_id=int(fan_id), **prof_set)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=prof_set
            )
        )
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id), **fan_set)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_=fan_set
            )
        )


# displayName works for any fan, notice only for subscribers (404 otherwise): separate calls so a 404 can't swallow the nickname write.
async def _push_to_of(client: OFClient, fan_id: int, nick: str, notes: str) -> tuple[bool, bool]:
    nick_ok = note_ok = False
    if nick:
        try:
            await asyncio.to_thread(client.set_fan_custom_name, fan_id, nick)
            nick_ok = True
        except Exception:
            log.warning("apply_profiles_push_nick_failed fan=%s", fan_id, exc_info=True)
    if notes:
        try:
            await asyncio.to_thread(client.set_fan_note, fan_id, notes)
            note_ok = True
        except Exception as e:
            log.info("apply_profiles_push_note_skipped fan=%s (%s)", fan_id, type(e).__name__)
    return nick_ok, note_ok


async def _write_mirror(account_id: str, fan_id: int, *, nick: str, notes: str,
                        now: datetime) -> None:
    set_: dict = {"updated_at": now}
    if nick:
        set_["custom_nickname"] = nick
    if notes:
        set_["notes"] = notes
    if len(set_) == 1:
        return
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=str(account_id), fan_id=int(fan_id), **set_)
            .on_conflict_do_update(index_elements=["account_id", "fan_id"], set_=set_)
        )



@register("apply_profiles")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    limit = int(payload.get("limit") or _DEFAULT_LIMIT)
    force_ids = coerce_ids(payload.get("force_ids"))

    push_requested = bool(payload.get("push_to_of"))
    of_client_obj = None
    # Never pretend a value reached OnlyFans: without a session, stay DB-only.
    if push_requested and _OF_PUSH_SUPPORTED:
        try:
            of_client_obj = OFClient.from_account(account_id)
        except Exception:
            log.warning("apply_profiles push_to_of: no OF session for %s — DB only",
                        account_id)
    pushed_to_of = of_client_obj is not None

    now = datetime.utcnow()
    blacklist = await _load_blacklist()
    profiles = await _load_profiles(account_id, limit)

    applied = 0
    skipped_cooldown = 0
    skipped_blacklist = 0
    skipped_empty = 0
    errors = 0
    pushed_nick = 0
    pushed_note = 0

    for prof in profiles:
        if prof.fan_id in blacklist:
            skipped_blacklist += 1
            continue

        target_nick = _clean_nickname(prof.nickname)
        target_notes = _facts_note(prof)
        if not target_nick and not target_notes:
            skipped_empty += 1
            continue

        if prof.fan_id not in force_ids and _is_up_to_date(
            prof, target_nick, target_notes, now
        ):
            skipped_cooldown += 1
            continue

        try:
            await _apply(account_id, prof.fan_id, target_nick, target_notes, now)
            applied += 1
            if of_client_obj is not None:
                nk, nt = await _push_to_of(of_client_obj, prof.fan_id,
                                           target_nick, target_notes)
                pushed_nick += int(nk)
                pushed_note += int(nt)
                await _write_mirror(account_id, prof.fan_id,
                                    nick=target_nick if nk else "",
                                    notes=target_notes if nt else "", now=now)
        except Exception:
            errors += 1
            log.warning("apply_profiles_apply_failed account=%s fan=%s",
                        account_id, prof.fan_id, exc_info=True)

    if pushed_nick or pushed_note:
        try:
            import relay_cache  # noqa: PLC0415 — lazy, optional in-process dep
            relay_cache.invalidate("list_chats", account_id)
        except Exception:
            log.debug("apply_profiles relay_cache invalidate skipped", exc_info=True)

    return {
        "profiles_seen": len(profiles),
        "applied": applied,
        "skipped_cooldown": skipped_cooldown,
        "skipped_blacklist": skipped_blacklist,
        "skipped_empty": skipped_empty,
        "errors": errors,
        "pushed_to_of": pushed_to_of,
        "pushed_nick": pushed_nick,
        "pushed_note": pushed_note,
    }
