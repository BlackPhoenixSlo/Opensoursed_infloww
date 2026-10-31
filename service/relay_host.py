"""service/relay_host.py — the serving relay module, looked up at call time.

Modules split out of server.py reach its globals (`_proxy`, `_get_client`,
`_get_request_user`, ...) through these forwards, never `from server import`.
Forwards look the server up on every call, so the one copy uvicorn serves
answers and a test's `server._get_client = fake` still reaches the moved code.
Two resolvers run once, at the importing module's import time: `account_ttl`
(decorator) and `server_module_name` (accounts_admin_api's `_ActivateBody`
OpenAPI name). Such modules must be imported BY server.py (mid-file), never
first; both raise if the server isn't loaded.
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


def get_request_client(request):
    return live_server()._get_client(request)


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


def server_module_name() -> str:
    # Runs at class-body time (accounts_admin_api._ActivateBody.__module__).
    # A fallback name would silently rename the OpenAPI component. Fail loudly.
    mod = loaded_server()
    if mod is None:
        raise RuntimeError(
            "relay_host.server_module_name: server not loaded — "
            "accounts_admin_api must be imported by server.py, not first")
    return mod.__name__


def priority_lane_background(account_id: str):
    return live_server()._priority_lane_background(account_id)


def invalidate_client(account_id: str | None = None):
    return live_server()._invalidate_client(account_id)


def kick_db_sync(reason: str):
    return live_server()._kick_db_sync(reason)


def stop_account_pump(account_id: str):
    return live_server()._stop_account_pump(account_id)


def post_bootstrap_hooks(account_id: str):
    return live_server().post_bootstrap_hooks(account_id)


def sync_and_link_after_bootstrap(account_id: str):
    return live_server()._sync_and_link_after_bootstrap(account_id)


def assemble_chats_page(client, **kwargs):
    return live_server()._assemble_chats_page(client, **kwargs)


def get_request_user():
    return live_server()._get_request_user()


def chats_window_fetched_at() -> dict[str, float]:
    return live_server()._chats_window_fetched_at


def list_chats_ttl() -> float:
    return live_server()._LIST_CHATS_TTL


def roster_window_max_age_s() -> float:
    return live_server()._ROSTER_WINDOW_MAX_AGE_S
