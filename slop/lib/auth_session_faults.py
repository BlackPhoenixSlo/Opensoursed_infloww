from __future__ import annotations

OWNER = ("the owner (All scope) signed in and its /events stayed open (reconnecting with Last-Event-ID as the "
         "browser does when the relay ends it), got every DM of its Agency's Creators "
         "sent after it subscribed, in per-thread order, and nothing of another Agency (stream, inbox)")
SETUP = ("owner /setup (GET /health?all_accounts=1, one proxy's Creators dead): 200, exactly the "
         "Agency's Creators, every Creator off the dead proxy ok, only the dead proxy's time out, "
         "every gated stage")

_ALL_SCOPE = ("/events", "/admin/chats/recent", "/health")


def _auth_owner_ids_dropped() -> None:
    import auth
    import server

    # scoped to the All-scope reads: the scenario's isolation-probe controls must not be refused (run INFRA, not CAUGHT)
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
        "auth-owner-ids-dropped": Fault(_auth_owner_ids_dropped, (OWNER, SETUP)),
    }
