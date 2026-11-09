"""Screen bundles' break-it-once faults (service/screens_api.py; its routes look `_deadline`,
`deadline_at`, `_narrow` and `_gate` up on the module at call time, so the patch is what the real
/admin/screens/* routes run). lib/faults.py merges `register(Fault)` into FAULTS. The check
names live here and scenarios/2026-11-05-screen-bundles.py (and slow-connections, C_AGAIN) imports
them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

C_SLOW = ("slow Creator (OF +10 s): the bundle answered by deadline_ms + slack, that Creator stale "
          "(its 3 reads 504 bundle_deadline), every other Creator complete")
C_SCOPE = ("scope: a restricted chatter naming Creators not its own, and an owner naming the neighbour "
           "Agency's Creator (its counts warm in the relay), get 404s and no value")

C_PRIORITY = ("priority: a user bundle with focus=Creator 1 leaves every other Creator background (only "
              "Creator 1 user-active in lane stats); a tap on Creator 2 meanwhile never waited for a lane")
C_AGAIN = "dashboard-again: the Per-model cards' fan counts converge to OF's (one Creator's changed since the first visit)"
C_INLINE = ("inline boot: each document load of the Dashboard / Messages Pro fetched none of /auth/me, /chatter/me, "
            "the Dashboard's Applied settings and its screen bundle itself (they came with its HTML)")
C_NO_SKIP = ("no skip: a cold inbox bundle answered at 300 ms; every (Creator, read) still reached OF "
             "and the next bundle is complete with no OF call")


def _screen_bundle_user_priority() -> None:
    """The priority leak back: every inner read carries the caller's X-Priority (focus ignored),
    so one user bundle takes every Creator's user lanes and marks every Creator user-active."""
    import screens_api

    real = screens_api._inner_request

    def copy_priority(outer, path, query, aid, focus):
        inner = real(outer, path, query, aid, focus)
        hdrs = [(k, v) for k, v in inner.scope["headers"] if k != b"x-priority"]
        pri = outer.headers.get("x-priority") or "user"
        hdrs.append((b"x-priority", pri.encode()))
        inner.scope["headers"] = hdrs
        return type(inner)(inner.scope)

    screens_api._inner_request = copy_priority


def _screen_bundle_waits_slowest() -> None:
    """The per-Creator timeout removed: the bundle waits for every read (up to an hour), so
    one Creator whose proxy is slow holds the whole screen."""
    import screens_api

    import time

    screens_api.deadline_at = lambda deadline_ms: time.monotonic() + 3600.0


def _screen_bundle_ignores_scope() -> None:
    """The scope check removed: `accounts=` is trusted as asked (not narrowed to the caller's
    own Creators) and the inner reads skip the ownership resolver (role hook only). A chatter
    is still refused by the role hook (it checks the Agency); an owner has only the resolver, so
    another Agency's warm relay_cache entry (counts, chart) is served before any route code runs."""
    import screens_api

    def trusts_asked(ids, wanted):
        if not wanted:
            return ids, []
        return list(dict.fromkeys(x for x in wanted.split(",") if x)), []

    async def role_only(inner):
        import json

        import permissions
        resp = await permissions.role_enforcement_middleware(inner, screens_api._passed)
        if resp is screens_api._PASSED:
            return None
        return resp.status_code, json.loads(resp.body).get("detail")

    screens_api._narrow = trusts_asked
    screens_api._gate = role_only


def _screen_bundle_stale_unmarked() -> None:
    """Serve-stale without its mark: a last value answers without `refreshing`, so the client never
    follows up and a card the relay answered stale keeps the old count (30 min staleTime)."""
    import screens_api

    real = screens_api._Done

    def unmarked(*a, **kw):
        kw["refreshing"] = False
        return real(*a, **kw)

    screens_api._Done = unmarked


# The reads the Next server starts for a document load's HTML (app/lib/inlineBoot.server.ts inlinePaths).
_INLINE_PATHS = ("/auth/me", "/chatter/me", "/admin/settings/applied", "/admin/screens/dashboard", "/admin/screens/inbox")


def _inline_boot_relay_refuses_server() -> None:
    """The relay unreachable from the Next server (a bad RELAY_URL, the compose network split): every read the root
    layout starts for the HTML (Node's fetch, `user-agent: node`) gets a 503, the browser's own calls (through the
    rewrites, its iPhone user agent) do not. The page must render as before the inline boot: the browser fetches them
    itself, one round trip later; only the inline check sees it."""
    import server
    from starlette.responses import Response

    async def refuse_node(request, call_next):
        ua = request.headers.get("user-agent", "")
        if request.url.path.startswith(_INLINE_PATHS) and (ua == "node" or ua.startswith("undici")):
            return Response("relay unreachable (slop fault)", status_code=503)
        return await call_next(request)

    server._http_hooks.add(refuse_node)


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-05-screen-bundles --break   (the scenario's FAULT)
        "screen-bundle-waits-slowest": Fault(_screen_bundle_waits_slowest, (C_SLOW,)),
        # slop/run 2026-11-05-screen-bundles --break --fault=screen-bundle-ignores-scope
        "screen-bundle-ignores-scope": Fault(_screen_bundle_ignores_scope, (C_SCOPE,)),
        "screen-bundle-user-priority": Fault(_screen_bundle_user_priority, (C_PRIORITY,)),
        # slop/run 2026-11-05-slow-connections --net=jp --break --fault=screen-bundle-stale-unmarked
        "screen-bundle-stale-unmarked": Fault(_screen_bundle_stale_unmarked, (C_AGAIN,)),
        # slop/run 2026-11-05-slow-connections --net=jp --break --fault=inline-boot-relay-refuses-server
        "inline-boot-relay-refuses-server": Fault(_inline_boot_relay_refuses_server, (C_INLINE,)),
    }
