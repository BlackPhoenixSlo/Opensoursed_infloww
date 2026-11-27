from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import accounts as account_registry

_HERE = Path(__file__).resolve().parent
_FANSLY_PKG = _HERE.parent / "fansly"
if str(_FANSLY_PKG) not in sys.path:
    sys.path.insert(0, str(_FANSLY_PKG))

from fansly_client import FanslyAPIError as APIError  # noqa: E402,F401
from fansly_client import FanslySession  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402
from fansly_shim import check_sendable  # noqa: E402,F401
from fansly_ws import FanslyWebSocket  # noqa: E402

if TYPE_CHECKING:
    from fansly_revenue import TickResult

log = logging.getLogger("of-relay")

Shim = FanslyShimClient

SESSION_FILENAME = "fansly_session.json"

_lock = threading.Lock()
_pool: dict[str, FanslyShimClient] = {}


def session_path(account_id: str) -> Path:
    return account_registry.account_dir(account_id) / SESSION_FILENAME


def get_client(account_id: str) -> FanslyShimClient:
    with _lock:
        cached = _pool.get(account_id)
        if cached is not None:
            return cached

        path = session_path(account_id)
        if not path.exists():
            raise FileNotFoundError(
                f"account {account_id} has no Fansly session at {path.name} — "
                f"capture one with the login extension (Fansly tab)"
            )

        data = json.loads(path.read_text())
        session = FanslySession(data, path)
        client = FanslyShimClient(session)
        if not session.device_id:
            client.ensure_device_id()
        _pool[account_id] = client
        return client


def identify(session: dict) -> tuple[dict, dict]:
    s = FanslySession(dict(session))
    client = FanslyShimClient(s)
    fetched = {}
    if not s.device_id:
        client.ensure_device_id()
        fetched = {"device_id": s.device_id, "device_id_ts": s.device_id_ts}
    return client.me(), {**session, **fetched}


class SessionRefused(ValueError):
    pass


def session_blob(*, token: str, session_id: str | None, account_id: str, device_id: str | None,
                 user_agent: str, accept_language: str | None = None,
                 check_key: str | None = None) -> dict:
    return {
        "token": token,
        "id": session_id,
        "accountId": account_id,
        "device_id": device_id,
        "user_agent": user_agent,
        "accept_language": accept_language or "en-US,en;q=0.9",
        "check_key": check_key,
    }


def prove(session: dict) -> tuple[dict, dict]:
    import platforms

    account_id = str(session.get("accountId") or "")
    account_registry.account_dir(account_id)
    account_registry.ensure_platform(account_id, platforms.FANSLY.key)
    try:
        me, session = identify(session)
    except Exception as e:  # noqa: BLE001 — any failure means the token is not proven
        why = f"{type(e).__name__}: {e}"
        token = session.get("token")
        if token:
            why = why.replace(token, "***")
        log.warning("fansly session for %s not proven: %s", account_id, why)
        raise SessionRefused(f"Fansly did not accept this session: {why}") from None
    me_id = str(me.get("id") or "")
    if me_id != account_id:
        raise SessionRefused(
            f"this session signs in as Fansly account {me_id or '(none)'}, not {account_id}")
    account_registry.ensure_platform(account_id, platforms.FANSLY.key)
    return me, session


def save(session: dict, me: dict, *, nickname: str | None, make_active: bool) -> Path:
    import platforms

    account_id = str(session["accountId"])
    platforms.require_account(account_id)
    name = me.get("name") or me.get("username")
    adir = account_registry.account_dir(account_id)
    adir.mkdir(parents=True, exist_ok=True)
    session_file = adir / SESSION_FILENAME
    session_file.write_text(json.dumps(session, indent=2) + "\n")
    try:
        session_file.chmod(0o600)
    except OSError:
        pass
    account_registry.upsert_account(
        account_id,
        platform=platforms.FANSLY.key,
        name=name,
        nickname=nickname or name or f"Fansly {account_id}",
    )
    if make_active:
        account_registry.set_active_account_id(account_id)
    return session_file


def drop(account_id: str | None = None) -> None:
    """Evict a cached client (e.g. after a fresh capture is written).

    `None` evicts every account, matching client_pool.evict — which is what
    calls this, so one invalidation covers both platforms' pools."""
    with _lock:
        if account_id is None:
            _pool.clear()
        else:
            _pool.pop(account_id, None)


def ws(client: FanslyShimClient) -> FanslyWebSocket:
    return FanslyWebSocket(client)


async def revenue_tick(account_id: str) -> TickResult:
    # Circular: fansly_revenue imports this module at load.
    import fansly_revenue

    return await fansly_revenue.run_one_tick(account_id)
