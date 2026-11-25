from __future__ import annotations

import sys
from typing import Awaitable, Callable


def loaded_server():
    for name in ("service.server", "server"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "post_bootstrap_hooks"):
            return mod
    return None


def live_server():
    # A bare `import server` would run a SECOND copy of server.py with its own state (_main_loop unset, own pump registry).
    mod = loaded_server()
    if mod is not None:
        return mod
    import server
    return server


def proxy(call, *, client=None):
    return live_server()._proxy(call, client=client)


def get_client():
    return live_server()._get_client()


def get_request_client(request):
    return live_server()._get_client(request)


def load_client(account_id: str):
    return live_server()._load_client(account_id)


def periodic(label: str, interval_s: float, work: Callable[[], Awaitable[None]],
             *, first_after_s: float | None = None):
    return live_server()._periodic(label, interval_s, work, first_after_s=first_after_s)


def account_ttl(namespace: str, ttl_seconds: float):
    # Importing server from here would start server.py, whose `import of_stats_api` gets the half-built caller: include_router copies 0 routes, silent 404s.
    mod = loaded_server()
    if mod is None:
        raise RuntimeError(
            "relay_host.account_ttl: server not loaded — of_stats_api must be "
            "imported by server.py, not first")
    return mod._account_ttl(namespace, ttl_seconds)


def server_module_name() -> str:
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


async def flag_dead_session(account_id: str, exc: BaseException, via: str, client) -> bool:
    return await live_server().flag_dead_session(account_id, exc, via, client)


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


def resolve_account_id(request):
    return live_server()._resolve_account_id(request)


def current_aid() -> str:
    return live_server()._current_aid()


def request_account_header() -> str | None:
    request = live_server()._request_ctx.get()
    if request is None:
        return None
    return request.headers.get("x-account-id") or request.query_params.get("account_id")


async def annotate_chat_rows(account_id: str, rows):
    return await live_server()._annotate_chat_rows(account_id, rows)


def spawn_bg(coro, name: str):
    return live_server()._spawn_bg(coro, name)


def send_message_body(**kw):
    return live_server().SendMessageBody(**kw)


async def reject_if_resale(account_id: str, fan_id: int, body) -> None:
    return await live_server()._reject_if_resale(account_id, fan_id, body)


async def record_fan_send(account_id: str, fan_id: int, result, *,
                          employee_id: int | None, price: float, before_send_at: int) -> None:
    return await live_server()._record_fan_send(
        account_id, fan_id, result, employee_id=employee_id, price=price, before_send_at=before_send_at)
