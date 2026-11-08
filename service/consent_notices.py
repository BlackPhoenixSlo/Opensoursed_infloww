"""service/consent_notices.py — OnlyFans' "Consent not accepted" as a pinned
agency notification (NC HB 805 / Alabama consent laws).

OF refuses a flagged Creator's media sends (`400 {"error":{"code":0,"message":
"Consent not accepted"}}` on POST /messages/queue and /chats/{id}/messages)
until the creator signs onlyfans.com/my/consent-form; its GET /users/me reads
`needConsent`, `needConsentState` ("NC"/"AL") and `consentStatus`
("approved" once signed).

No OF call of its own: `OFClient._http_call` hands every answer to `observe`,
which tests the status and path and reads the body only for a 400 or a 2xx
/users/me (the WS pump reads it on every (re)connect; the profile route and
health probes too).

  flag   a 400 whose body says "Consent not accepted" on any write, or a
         /users/me with needConsent true and consentStatus not "approved"
  clear  a /users/me with needConsent false or consentStatus "approved", or a
         2xx media send (non-empty `mediaFiles`) to /chats/{id}/messages or
         /messages/queue

The state is the rows, nothing in memory: one `consent_required`
agency_notifications row per owner of the Creator (dedupe
notifications_api.pinned_key). Every verdict goes to the table: a flag files
the row for each owner that lacks it; a clear deletes the Creator's row of
every Agency (consent is the Creator's OF fact, so a former owner's row goes
too). Both read first and write only when a row is missing or there: a flag
that changes nothing costs three reads (the owners, the Creator's name, the
owners' rows on the dedupe index), a clear one dedupe-index probe per user,
and a flag or clear lost to a race or a failed write is redone by the next
verdict. The SSE count is pushed only when rows changed.
notifications_api.PINNED_KIND makes the row undismissable and hides it once
the Agency no longer holds the Creator; removing (`DELETE
/admin/accounts/{id}`) or unlinking the Creator deletes it there
(notifications_api.drop_pinned). Send behaviour is unchanged: this only
reports.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import accounts
from notifications_api import PINNED_KIND, Notice, drop_pinned, notify_creator_owners, pinned_key

log = logging.getLogger("of-relay.consent")

KIND = PINNED_KIND
MARK = "Consent not accepted"
FORM = "onlyfans.com/my/consent-form"
_ME = re.compile(r"/api2/v2/users/me/?")
_MEDIA_SEND = re.compile(r"/api2/v2/(?:chats/\d+/messages|messages/queue)/?")


def text_for(name: str, state: str | None) -> str:
    law = f"{state} law" if state in ("NC", "AL") else "NC/AL law"
    return (f"{name}: OnlyFans needs a signed consent form ({law}). Media mass messages and PPVs fail "
            f"until the creator signs at {FORM}.")


def verdict(method: str, url: str, json_body: dict | None, r: Any) -> tuple[bool | None, str | None]:
    """One OF answer's word and the law it names: (True, state) consent
    required, (False, None) not, (None, None) it says nothing. Reads the body
    only for a 2xx /users/me or a 400."""
    status = int(getattr(r, "status_code", 0) or 0)
    path = urlsplit(url).path
    if method == "GET":
        if not (200 <= status < 300 and _ME.fullmatch(path)):
            return None, None
        me = json.loads(r.text or "null")
        if not isinstance(me, dict) or "needConsent" not in me:
            return None, None
        need = bool(me.get("needConsent")) and me.get("consentStatus") != "approved"
        return need, (me.get("needConsentState") if need else None)
    if status == 400 and MARK in (getattr(r, "text", "") or "")[:500]:
        return True, None
    if (method == "POST" and 200 <= status < 300 and isinstance(json_body, dict) and json_body.get("mediaFiles")
            and _MEDIA_SEND.fullmatch(path)):
        return False, None
    return None, None


def observe(account_id: str | None, method: str, url: str, json_body: dict | None, r: Any) -> None:
    """One OF answer. Never raises; schedules a flag / clear on a verdict."""
    try:
        if not account_id:
            return
        need, state = verdict(method, url, json_body, r)
        if need is not None:
            _schedule(str(account_id), need, state)
    except Exception:  # noqa: BLE001 — a report must never fail the call it watched
        log.warning("consent observe failed account=%s", account_id, exc_info=True)


def _schedule(account_id: str, need: bool, state: str | None) -> None:
    from relay_host import loaded_server  # lazy: server imports the client
    srv = loaded_server()
    if srv is not None:
        srv._on_main_loop(lambda: flag(account_id, state) if need else clear(account_id), f"consent-{account_id}")


async def flag(account_id: str, state: str | None = None) -> int:
    """File the row for every owner of the Creator lacking it. Returns how many filed.
    A removed Creator gets none: its links outlive the delete, and nothing
    would ever take the row away again (an in-flight call's 400 lands late)."""
    try:
        if not accounts.is_account(account_id):   # a raise ("could not look") skips too, below
            return 0
        filed = await notify_creator_owners(account_id, lambda name: Notice(
            KIND, text_for(name, state), account_id=account_id,
            data={"name": name, "state": state, "form": f"https://{FORM}"}, dedupe=pinned_key(account_id)))
        if filed:
            log.warning("consent_required account=%s state=%s filed=%d", account_id, state, filed)
        return filed
    except Exception:
        log.exception("consent flag failed account=%s", account_id)
        return 0


async def clear(account_id: str) -> int:
    """Delete the Creator's row of every Agency (pushing each one's new
    unread count). Returns how many went."""
    try:
        gone = await drop_pinned(account_id)
        if gone:
            log.warning("consent_cleared account=%s agencies=%d", account_id, gone)
        return gone
    except Exception:
        log.exception("consent clear failed account=%s", account_id)
        return 0
