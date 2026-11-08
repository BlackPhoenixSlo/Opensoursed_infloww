"""service/consent_notices.py — OnlyFans' "Consent not accepted" as a pinned
agency notification (NC HB 805 / Alabama consent laws).

OF refuses a flagged Creator's media sends (`400 {"error":{"code":0,"message":
"Consent not accepted"}}` on POST /messages/queue and /chats/{id}/messages)
until the creator signs onlyfans.com/my/consent-form; its GET /users/me reads
`needConsent`, `needConsentState` ("NC"/"AL") and `consentStatus`
("approved" once signed).

No OF call of its own: `OFClient._http_call` hands every answer to `observe`,
which tests the status and path and parses JSON only for a 2xx /users/me (the
WS pump reads it on every (re)connect; the profile route and health probes too).

  flag   a 400 whose body says "Consent not accepted" on any write, or a
         /users/me with needConsent true and consentStatus not "approved"
  clear  a /users/me with needConsent false or consentStatus "approved", or a
         2xx media send (non-empty `mediaFiles`) to /chats/{id}/messages or
         /messages/queue

The state is the rows: one `consent_required` agency_notifications row per
owner of the Creator (dedupe `consent_required:<account>`), deleted on clear.
notifications_api.PINNED_KINDS makes it undismissable and drops it once the
Agency no longer holds the Creator. `_flagged` mirrors which Creators hold a
row (loaded once from the table), so the per-call path schedules DB work only
when the state flips. Send behaviour is unchanged: this only reports.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select

from db.engine import get_session
from db.models import Account, AgencyNotification, UserAccount
from notifications_api import Notice, _push_pruned, notify

log = logging.getLogger("of-relay.consent")

KIND = "consent_required"
MARK = "Consent not accepted"
FORM = "onlyfans.com/my/consent-form"
_ME = re.compile(r"/api2/v2/users/me/?")
_MEDIA_SEND = re.compile(r"/api2/v2/(?:chats/\d+/messages|messages/queue)/?")

_flagged: set[str] | None = None  # Creators holding a row; None until loaded
_lock = threading.Lock()


def _dedupe(account_id: str) -> str:
    return f"{KIND}:{account_id}"


def text_for(name: str, state: str | None) -> str:
    law = f"{state} law" if state in ("NC", "AL") else "NC/AL law"
    return (f"{name}: OnlyFans needs a signed consent form ({law}). Media mass messages and PPVs fail "
            f"until the creator signs at {FORM}.")


def verdict_me(me: Any) -> bool | None:
    """/users/me's word: True consent required, False not, None it says nothing."""
    if not isinstance(me, dict) or "needConsent" not in me:
        return None
    return bool(me.get("needConsent")) and me.get("consentStatus") != "approved"


def verdict_call(method: str, url: str, json_body: dict | None, status: int, text: str) -> bool | None:
    """A non-/users/me call's word: True a consent refusal, False a media send
    OF accepted, None anything else."""
    if method == "GET":
        return None
    if status == 400 and MARK in text[:500]:
        return True
    if (method == "POST" and 200 <= status < 300 and isinstance(json_body, dict) and json_body.get("mediaFiles")
            and _MEDIA_SEND.fullmatch(urlsplit(url).path)):
        return False
    return None


def observe(account_id: str | None, method: str, url: str, json_body: dict | None, r: Any) -> None:
    """One OF answer. Never raises; schedules a flag / clear only on a flip."""
    try:
        if not account_id:
            return
        status = int(getattr(r, "status_code", 0) or 0)
        state = None
        if method == "GET":
            if not (200 <= status < 300 and _ME.fullmatch(urlsplit(url).path)):
                return
            me = json.loads(r.text or "null")
            need = verdict_me(me)
            state = me.get("needConsentState") if isinstance(me, dict) else None
        else:
            need = verdict_call(method, url, json_body, status, getattr(r, "text", "") or "")
        if need is None or not _flips(str(account_id), need):
            return
        _schedule(str(account_id), need, state)
    except Exception:  # noqa: BLE001 — a report must never fail the call it watched
        log.warning("consent observe failed account=%s", account_id, exc_info=True)


def _flips(account_id: str, need: bool) -> bool:
    with _lock:
        return _flagged is None or (account_id in _flagged) != need


def _schedule(account_id: str, need: bool, state: str | None) -> None:
    def make():
        return flag(account_id, state) if need else clear(account_id)
    try:
        asyncio.get_running_loop().create_task(make(), name=f"consent-{account_id}")
        return
    except RuntimeError:
        pass
    from relay_host import loaded_server  # lazy: server imports the client
    srv = loaded_server()
    if srv is not None:
        srv._on_main_loop(make, f"consent-{account_id}")


async def reload() -> set[str]:
    """`_flagged` from the table (startup, and after the feed dropped rows)."""
    global _flagged
    async with get_session() as s:
        ids = set((await s.execute(select(AgencyNotification.account_id).where(
            AgencyNotification.kind == KIND).distinct())).scalars().all())
    with _lock:
        _flagged = {str(a) for a in ids if a}
        return set(_flagged)


async def _loaded() -> set[str]:
    with _lock:
        if _flagged is not None:
            return _flagged
    await reload()
    return _flagged  # type: ignore[return-value]


async def flag(account_id: str, state: str | None = None) -> int:
    """File the row for every owner of the Creator (once: dedupe). Returns how many filed."""
    flagged = await _loaded()
    with _lock:
        if account_id in flagged:
            return 0
        flagged.add(account_id)
    try:
        async with get_session() as s:
            owners = (await s.execute(select(UserAccount.user_id).where(
                UserAccount.account_id == account_id))).scalars().all()
            acc = await s.get(Account, account_id)
        name = (acc.nickname if acc is not None else None) or account_id
        notice = Notice(KIND, text_for(name, state), account_id=account_id,
                        data={"name": name, "state": state, "form": f"https://{FORM}"}, dedupe=_dedupe(account_id))
        filed = 0
        for owner in owners:
            filed += await notify(owner, [notice])
        log.warning("consent_required account=%s state=%s owners=%d", account_id, state, len(owners))
        return filed
    except Exception:
        with _lock:
            flagged.discard(account_id)
        log.exception("consent flag failed account=%s", account_id)
        return 0


async def clear(account_id: str) -> int:
    """Delete the Creator's rows (every Agency's) and push each Agency's new
    unread count. Returns how many went."""
    flagged = await _loaded()
    with _lock:
        if account_id not in flagged:  # the table's mirror: no row to delete
            return 0
        flagged.discard(account_id)
    try:
        async with get_session() as s:
            where = (AgencyNotification.kind == KIND) & (AgencyNotification.account_id == account_id)
            agencies = (await s.execute(select(AgencyNotification.agency_user_id).where(where))).scalars().all()
            if agencies:
                await s.execute(delete(AgencyNotification).where(where))
        await _push_pruned(sorted(set(agencies)))
        if agencies:
            log.warning("consent_cleared account=%s agencies=%d", account_id, len(set(agencies)))
        return len(agencies)
    except Exception:
        log.exception("consent clear failed account=%s", account_id)
        return 0
