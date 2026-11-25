from __future__ import annotations

import json
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
