"""scenarios/2026-11-08-consent-required-notice.py's checks and faults (service/consent_notices.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.

  consent-send-ok-not-clearing  an accepted media send no longer clears the row (the clear-on-send branch
                                dropped): targets CLEARED_BY_SEND and UI_SETTLED.
  consent-pinned-readable       `read` no longer refuses a pinned row: targets NOT_DISMISSABLE.
"""
from __future__ import annotations

SEND_ROUTE = "POST /api/of/v2/chats/:id/messages"
FLAGGED_ONCE = ("consent: after the send load, the refused Creator holds exactly one consent_required row per owner "
                "(SQL), the others none, and GET pinned names it alone")
SENDS_KEPT = ("consent: every media send of an unflagged Creator answered 200 and OF kept it; every one of the "
              "flagged Creator's answered 502 with OF's 400 Consent not accepted, none kept")
FLAGGED_BY_ME = "consent: a /users/me with needConsent (the pump's reconnect) files the row with its law (AL)"
NOT_DISMISSABLE = ("consent: POST /{id}/read on each pinned row answers 409 and read-all leaves them unread "
                   "(SQL read_at NULL; both rows remain pinned)")
UI_TRIGGER = ("consent UI: desktop and phone portrait show the banner naming both Creators, its View opens the "
              "bell's Agency tab with both pinned rows and no dismiss button on them")
CLEARED_BY_ME = "consent: /users/me consentStatus approved (the pump's reconnect) deletes the row (SQL, API)"
CLEARED_BY_SEND = "consent: an accepted media send deletes the row (SQL, API)"
CLEARED_BY_REMOVAL = "consent: the owner removing the flagged Creator (DELETE /admin/accounts/{id}) drops its row"
UI_SETTLED = "consent UI: desktop and phone portrait show no banner and no pinned row once all cleared"



def _send_ok_not_clearing() -> None:
    import consent_notices as cn

    real = cn.verdict

    def verdict(method, *a, **k):
        need, state = real(method, *a, **k)
        return (None, state) if need is False and method != "GET" else (need, state)

    cn.verdict = verdict


def _pinned_readable() -> None:
    import notifications_api as na

    real = na._mark_read

    async def mark(user_id, notification_id):
        if notification_id is None:
            return await real(user_id, None)
        na.PINNED_KIND, keep = "", na.PINNED_KIND
        try:
            return await real(user_id, notification_id)
        finally:
            na.PINNED_KIND = keep

    na._mark_read = mark


def register(Fault) -> dict:
    return {
        # slop/run consent-required-notice --break (the scenario's FAULT)
        "consent-send-ok-not-clearing": Fault(_send_ok_not_clearing, (CLEARED_BY_SEND, UI_SETTLED)),
        # slop/run consent-required-notice --break --fault=consent-pinned-readable --baseline=...
        "consent-pinned-readable": Fault(_pinned_readable, (NOT_DISMISSABLE,)),
    }
