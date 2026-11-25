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
    # OF refuses a flagged Creator's media sends with 400 "Consent not accepted" until she signs the consent form.
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
    try:
        if not account_id:
            return
        need, state = verdict(method, url, json_body, r)
        if need is not None:
            _schedule(str(account_id), need, state)
    except Exception:  # noqa: BLE001 — a report must never fail the call it watched
        log.warning("consent observe failed account=%s", account_id, exc_info=True)


def _schedule(account_id: str, need: bool, state: str | None) -> None:
    # Lazy: server imports the client.
    from relay_host import loaded_server
    srv = loaded_server()
    if srv is not None:
        srv._on_main_loop(lambda: flag(account_id, state) if need else clear(account_id), f"consent-{account_id}")


async def flag(account_id: str, state: str | None = None) -> int:
    try:
        # A removed Creator gets no row: its links outlive the delete and nothing would take the row away again.
        if not accounts.is_account(account_id):
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
    try:
        gone = await drop_pinned(account_id)
        if gone:
            log.warning("consent_cleared account=%s agencies=%d", account_id, gone)
        return gone
    except Exception:
        log.exception("consent clear failed account=%s", account_id)
        return 0
