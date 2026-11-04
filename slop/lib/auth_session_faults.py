"""The owner session's break-it-once fault (service/auth.py `account_ids_for`, the one load of a
signed-in owner's Creators, which `_resolve_session` looks up on the module per request), checked
by scenarios/2026-10-24-chatter-crowd.py `--layout=one-agency` (the only layout with an owner
watching): lib/faults.py merges `register(Fault)` into FAULTS. The two target names are that
scenario's OWNER and SETUP checks, byte-verbatim (as faults.py's health-lane-4-core spells SETUP;
the scenario file cannot be imported here), so a drifted name is INCONCLUSIVE, never CAUGHT.
"""
from __future__ import annotations

OWNER = ("the owner (All scope) signed in and its /events stayed open (reconnecting with Last-Event-ID as the "
         "browser does when the relay ends it), got every DM of its Agency's Creators "
         "sent after it subscribed, in per-thread order, and nothing of another Agency (stream, inbox)")
SETUP = ("owner /setup (GET /health?all_accounts=1, one proxy's Creators dead): 200, exactly the "
         "Agency's Creators, every Creator off the dead proxy ok, only the dead proxy's time out, "
         "every gated stage")

# The owner dashboard's All-scope reads (actors/manager.OwnerTab's stream and inbox head, the
# scenario's /setup read). Narrowed to these on purpose: the scenario also reads with the owner's
# session as an isolation probe's target control (GET /admin/messages/{aid}/{fan}) and changes a
# chatter's access (PUT /admin/chatters/{id}/account-access); either refused leaves a probe
# undecided, and the run INFRA instead of CAUGHT.
_ALL_SCOPE = ("/events", "/admin/chats/recent", "/health")


def _auth_owner_ids_dropped() -> None:
    """The owner's Creator load loses a row: on the All-scope dashboard reads, a non-admin owner
    with two or more Creators resolves without one of them (the last id in string order), as an
    off-by-one in the user_accounts read would. Never all of them: a stream with no DM leaves the
    owner's frame -> SSE p95 unmeasured (judge_stage: nodata, the run INFRA). Masters, an
    impersonated user (its load runs after the signed-in founder's has set `_request_user`) and
    every other request resolve as ever. The request in flight is server._request_ctx (its
    `_account_context` hook runs outside session_middleware)."""
    import auth
    import server

    real = auth.account_ids_for

    async def ids_for(s, user_id, is_admin):
        ids = await real(s, user_id, is_admin)
        req = server._request_ctx.get()
        if (is_admin or auth._request_user.get() is not None or len(ids) < 2 or req is None
                or req.url.path not in _ALL_SCOPE or "x-account-id" in req.headers):
            return ids
        return ids - {max(ids)}

    auth.account_ids_for = ids_for


def register(Fault) -> dict:
    return {
        # slop/run chatter-crowd --layout=one-agency --break --fault=auth-owner-ids-dropped
        "auth-owner-ids-dropped": Fault(_auth_owner_ids_dropped, (OWNER, SETUP)),
    }
