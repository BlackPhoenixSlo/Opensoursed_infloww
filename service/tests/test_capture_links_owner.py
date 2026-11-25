import _harness  # noqa: F401 — MUST be first (binds a throwaway temp DB)

import asyncio  # noqa: E402
import threading  # noqa: E402

import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from db.repo import ensure_user_account_link  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

_harness.bootstrap()

UID = "u_capture_owner"


async def _count_links(account_id: str) -> int:
    async with get_session() as s:
        return (await s.execute(
            select(func.count()).select_from(UserAccount).where(
                UserAccount.user_id == UID,
                UserAccount.account_id == account_id,
            )
        )).scalar_one()


async def _seed(account_id: str | None = None) -> None:
    async with get_session() as s:
        if await s.get(User, UID) is None:
            s.add(User(id=UID, username="capture_owner", password="x"))
        if account_id and await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname="captured"))


async def _repo_contract() -> None:
    await _seed("9990001")
    await ensure_user_account_link(UID, "9990001")
    assert await _count_links("9990001") == 1, "link must land"
    await ensure_user_account_link(UID, "9990001")
    assert await _count_links("9990001") == 1, "re-capture must not duplicate"

    # Parent missing must raise; silence is the bug.
    try:
        await ensure_user_account_link(UID, "9999999")
    except IntegrityError:
        pass
    else:
        raise AssertionError("linking without the parent row must raise, not pass silently")
    assert await _count_links("9999999") == 0


def _ordering() -> None:
    calls: list[str] = []

    async def fake_sync() -> dict:
        await asyncio.sleep(0)
        calls.append("sync")
        return {}

    async def fake_link(user_id: str, account_id: str) -> None:
        calls.append("link")

    class _U:
        id = UID
        account_ids = frozenset()

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    orig = (server._sync_db_from_disk, server.ensure_user_account_link,
            server._get_request_user, server._main_loop)
    try:
        server._sync_db_from_disk = fake_sync
        server.ensure_user_account_link = fake_link
        server._get_request_user = lambda: _U()
        server._main_loop = loop
        server._sync_and_link_after_bootstrap("9990002")
    finally:
        (server._sync_db_from_disk, server.ensure_user_account_link,
         server._get_request_user, server._main_loop) = orig
        loop.call_soon_threadsafe(loop.stop)

    assert calls == ["sync", "link"], f"expected sync before link, got {calls}"


asyncio.run(_repo_contract())
_ordering()
print("test_capture_links_owner: OK")
