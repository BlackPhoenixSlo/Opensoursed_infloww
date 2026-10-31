"""service/relay_host.py — the serving relay module, looked up at call time.

Modules split out of server.py reach its globals (`_proxy`, `_get_client`, ...)
through these forwards, never `from server import`. `proxy`, `get_client`,
`load_client`, `periodic` and `priority_lane_background` look the server up on
every call, so the one copy uvicorn serves answers, and a test's
`server._get_client = fake` still reaches the moved code. `account_ttl` is a
decorator: it resolves once, at the importing module's import time, so that
module must be imported BY server.py (mid-file), never first.
"""
from __future__ import annotations

import sys
from typing import Awaitable, Callable


def loaded_server():
    """The server module already in sys.modules (possibly mid-import), or None.

    Never imports: a module server.py is still importing gets server's
    half-built copy here, not a second one."""
    for name in ("service.server", "server"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "post_bootstrap_hooks"):
            return mod
    return None


def live_server():
    """The server module that is actually serving.

    uvicorn loads it as `service.server`; a bare `import server` would run a
    SECOND copy of server.py under the name `server`, with its own state
    (`_main_loop` unset, its own pump registry). Through that copy the
    post-bootstrap link to the signed-in user was silently skipped: the
    account landed on disk and in `accounts`, but owned by nobody."""
    mod = loaded_server()
    if mod is not None:
        return mod
    import server  # lazy: server imports of_stats_api / remote_login, which import relay_host
    return server


def proxy(call):
    return live_server()._proxy(call)


def get_client():
    return live_server()._get_client()


def load_client(account_id: str):
    return live_server()._load_client(account_id)


def periodic(label: str, interval_s: float, work: Callable[[], Awaitable[None]]):
    return live_server()._periodic(label, interval_s, work)


def account_ttl(namespace: str, ttl_seconds: float):
    # Runs at decoration time. Importing server from here would start
    # server.py, whose `import of_stats_api` gets the half-built caller ->
    # include_router copies 0 routes -> silent 404s. Fail loudly instead.
    mod = loaded_server()
    if mod is None:
        raise RuntimeError(
            "relay_host.account_ttl: server not loaded — of_stats_api must be "
            "imported by server.py, not first")
    return mod._account_ttl(namespace, ttl_seconds)


def priority_lane_background(account_id: str):
    return live_server()._priority_lane_background(account_id)
