#!/usr/bin/env python3
"""
Chatter Access — Step 7 tests (owner-set per-chatter visibility limits).

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_chatter_access.py

Boots a temp SQLite DB and seeds a fixture shaped like the real
`velvetvoice1` chatter so the cases mirror what you verify by hand:

    owner A (≈ "velvetvoice")  →  accAva, accCelest   (2 accounts)
    owner B (≈ "founder")      →  accFounder              (1 account)
    chatter "sensui"             →  linked to BOTH owners

Covers: the account gate (subtractive, per-owner, empty = full),
multi-owner isolation, the folder gate on /api/of/v2/vault/{lists,media}
(soft-deny + filter, evaluated before the cache, DA-1 dual-cookie owner
NOT restricted), the owner endpoints (cross-owner reject, chatter-cookie
reject, not-linked 404), /chatter/me/folder-access (order + 403), and the
BigInteger folder_id guarantee.

Exit 0 = all pass; non-zero lists the first-seen failures. Cases are
independent and self-clean their access rows so order can't bleed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# ── 1. Hard-bind the DB BEFORE importing any service module (same incident
# guard as test_chatter_auth.py: unset env can fall back to PROD).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_caccess_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

from db.engine import init_db  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    Chatter,
    ChatterAccountAccess,
    ChatterFolderAccess,
    ChatterUser,
    User,
    UserAccount,
)

asyncio.run(init_db())

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

import server  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
import vault_cache  # noqa: E402
import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402


# The vault relay's `_resolve_account_id` validates the account id against
# the FILESYSTEM account registry (accounts/<id>/meta.json), not the DB.
# Rather than write meta dirs under the real SESSIONS_DIR, make the
# registry recognise our DB-seeded test ids in-process. `assert_account_owned`
# (the per-principal gate the tests actually exercise) is untouched.
_TEST_ACCOUNTS = {"accAva", "accCelest", "accFounder", "accForeign"}
_orig_get_account = account_registry.get_account


def _patched_get_account(account_id: str):
    if account_id in _TEST_ACCOUNTS:
        return {"id": account_id, "nickname": account_id}
    return _orig_get_account(account_id)


account_registry.get_account = _patched_get_account


# ── 2. Seeders ───────────────────────────────────────────────────────

async def _seed_user(username: str, password: str = "secretpw") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password))
    return uid


async def _seed_account(account_id: str, owner_user_id: str, nickname: str) -> None:
    async with get_session() as s:
        s.add(Account(id=account_id, nickname=nickname, color="#aaaaaa"))
        s.add(UserAccount(user_id=owner_user_id, account_id=account_id))


async def _seed_chatter(username: str, password: str = "secretpw") -> str:
    cid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(Chatter(
            id=cid, username=username, password=password,
            display_name=username.capitalize(),
            created_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        ))
    return cid


async def _link_chatter(chatter_id: str, user_id: str) -> None:
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=chatter_id, user_id=user_id, created_at=datetime.utcnow()))


async def _set_account_access(chatter_id: str, owner_id: str, account_ids: list[str]) -> None:
    async with get_session() as s:
        await s.execute(delete(ChatterAccountAccess).where(
            ChatterAccountAccess.chatter_id == chatter_id,
            ChatterAccountAccess.user_id == owner_id,
        ))
        for aid in account_ids:
            s.add(ChatterAccountAccess(
                chatter_id=chatter_id, user_id=owner_id, account_id=aid,
                created_at=datetime.utcnow(),
            ))


async def _set_folder_access(chatter_id: str, account_id: str, folders: list[tuple[int, str | None]]) -> None:
    async with get_session() as s:
        await s.execute(delete(ChatterFolderAccess).where(
            ChatterFolderAccess.chatter_id == chatter_id,
            ChatterFolderAccess.account_id == account_id,
        ))
        for fid, fname in folders:
            s.add(ChatterFolderAccess(
                chatter_id=chatter_id, account_id=account_id,
                folder_id=fid, folder_name=fname, created_at=datetime.utcnow(),
            ))


async def _clear_access(chatter_id: str) -> None:
    async with get_session() as s:
        await s.execute(delete(ChatterAccountAccess).where(
            ChatterAccountAccess.chatter_id == chatter_id))
        await s.execute(delete(ChatterFolderAccess).where(
            ChatterFolderAccess.chatter_id == chatter_id))


# ── 3. Harness ───────────────────────────────────────────────────────

FAILURES: list[str] = []


def _expect(case: str, condition: bool, detail: str = "") -> None:
    label = case if not detail else f"{case} — {detail}"
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILURES.append(label)


def _fresh_client() -> TestClient:
    return TestClient(server.app)


def _login_user(username: str, password: str = "secretpw") -> TestClient:
    c = _fresh_client()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return c


def _login_chatter(username: str, password: str = "secretpw") -> TestClient:
    c = _fresh_client()
    r = c.post("/chatter/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"chatter login failed: {r.status_code} {r.text}"
    return c


def _login_both(user: str, chatter: str) -> TestClient:
    """One TestClient carrying BOTH a user and a chatter cookie (the
    dual-cookie founder-testing case the DA-1 gate must treat as owner)."""
    c = _fresh_client()
    ru = c.post("/auth/login", json={"username": user, "password": "secretpw"})
    rc = c.post("/chatter/login", json={"username": chatter, "password": "secretpw"})
    assert ru.status_code == 200 and rc.status_code == 200
    return c


# Derived from the server's own key builders — a cache-key format change can
# never strand a stale literal here again (the drift that once turned this
# suite red: the `query=` part vault search added).
LISTS_KEY = server.vault_lists_cache_key()


def _media_key(list_id: int) -> str:
    return server.vault_media_cache_key(list_id=list_id)


# ── 4. Fixture: mirrors the real velvetvoice1 shape ────────────────

async def _setup() -> dict[str, str]:
    owner_a = await _seed_user("velvetvoice")   # 2 accounts
    owner_b = await _seed_user("founder")       # 1 account
    foreign = await _seed_user("stranger")        # NOT linked to the chatter
    await _seed_account("accAva", owner_a, "Ava")
    await _seed_account("accCelest", owner_a, "Celest2")
    await _seed_account("accFounder", owner_b, "Test Race")
    await _seed_account("accForeign", foreign, "not yours")

    sensui = await _seed_chatter("sensui")
    await _link_chatter(sensui, owner_a)
    await _link_chatter(sensui, owner_b)

    # A second chatter linked ONLY to owner_b, for the not-linked 404 path.
    solo_b = await _seed_chatter("solob")
    await _link_chatter(solo_b, owner_b)
    # An install from before role enforcement was on by default: its logins hold Admin.
    await seed_pre_enforcement_install()

    return {
        "owner_a": owner_a, "owner_b": owner_b, "foreign": foreign,
        "sensui": sensui, "solo_b": solo_b,
    }


# ── 5. Cases ─────────────────────────────────────────────────────────

async def case_account_gate_and_isolation(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    c = _login_chatter("sensui")

    base = {a["account_id"] for a in c.get("/chatter/me/accounts").json()}
    _expect("baseline union = all 3 accounts",
            base == {"accAva", "accCelest", "accFounder"}, detail=f"got {base!r}")

    # Owner A restricts the chatter to Ava only. Celest2 must vanish;
    # owner B's account (accFounder) must be UNTOUCHED (multi-owner isolation).
    await _set_account_access(ids["sensui"], ids["owner_a"], ["accAva"])
    after = {a["account_id"] for a in c.get("/chatter/me/accounts").json()}
    _expect("owner A restriction hides accCelest, keeps accAva",
            after == {"accAva", "accFounder"}, detail=f"got {after!r}")
    _expect("owner B's account survives owner A's restriction (isolation)",
            "accFounder" in after)

    # Empty allowlist = full access again (subtractive, backwards-compatible).
    await _set_account_access(ids["sensui"], ids["owner_a"], [])
    restored = {a["account_id"] for a in c.get("/chatter/me/accounts").json()}
    _expect("clearing the allowlist restores full access",
            restored == {"accAva", "accCelest", "accFounder"}, detail=f"got {restored!r}")
    await _clear_access(ids["sensui"])


async def case_account_gate_blocks_resolve(ids: dict[str, str]) -> None:
    # The restriction is a real security boundary, not just a list filter:
    # a per-account /admin/* call for a now-hidden account must 403.
    await _clear_access(ids["sensui"])
    await _set_account_access(ids["sensui"], ids["owner_a"], ["accAva"])
    c = _login_chatter("sensui")
    ok = c.get("/admin/saved-replies?account_id=accAva")
    blocked = c.get("/admin/saved-replies?account_id=accCelest")
    _expect("allowed account still reachable", ok.status_code == 200,
            detail=f"got {ok.status_code}")
    _expect("hidden account is 403 at the resolve gate (not just UI-hidden)",
            blocked.status_code == 403, detail=f"got {blocked.status_code}")
    await _clear_access(ids["sensui"])


async def case_vault_lists_filtered(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    await vault_cache.put("accAva", LISTS_KEY, {
        "list": [{"id": 1, "name": "Best"}, {"id": 2, "name": "Teasers"}],
        "hasMore": False,
    })
    await _set_folder_access(ids["sensui"], "accAva", [(1, "Best")])

    chatter = _login_chatter("sensui")
    r = chatter.get("/api/of/v2/vault/lists", headers={"X-Account-Id": "accAva"})
    ids_seen = [f["id"] for f in r.json().get("list", [])]
    _expect("restricted chatter sees ONLY allowed folder in vault/lists",
            ids_seen == [1], detail=f"got {ids_seen!r}")

    owner = _login_user("velvetvoice")
    ro = owner.get("/api/of/v2/vault/lists", headers={"X-Account-Id": "accAva"})
    owner_ids = [f["id"] for f in ro.json().get("list", [])]
    _expect("owner sees the FULL folder list (cache kept unfiltered)",
            owner_ids == [1, 2], detail=f"got {owner_ids!r}")
    await _clear_access(ids["sensui"])


async def case_vault_media_softdeny_and_allow(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    await _set_folder_access(ids["sensui"], "accAva", [(1, "Best")])
    # Seed the cache for an ALLOWED folder so the pass-through path doesn't
    # need a live OF session.
    await vault_cache.put("accAva", _media_key(1), {"list": [{"id": 111}], "hasMore": False})

    c = _login_chatter("sensui")
    deny_shape = {"list": [], "hasMore": False}

    disallowed = c.get("/api/of/v2/vault/media?list_id=2", headers={"X-Account-Id": "accAva"})
    _expect("media for a DISALLOWED folder soft-denies (empty, 200, OF shape)",
            disallowed.status_code == 200 and disallowed.json() == deny_shape,
            detail=f"got {disallowed.status_code} {disallowed.json()!r}")

    unscoped = c.get("/api/of/v2/vault/media", headers={"X-Account-Id": "accAva"})
    _expect("media with NO list_id (the 'All' view) soft-denies for restricted chatter",
            unscoped.status_code == 200 and unscoped.json() == deny_shape,
            detail=f"got {unscoped.status_code} {unscoped.json()!r}")

    allowed = c.get("/api/of/v2/vault/media?list_id=1", headers={"X-Account-Id": "accAva"})
    _expect("media for an ALLOWED folder passes through (not denied)",
            allowed.status_code == 200 and allowed.json().get("list") == [{"id": 111}],
            detail=f"got {allowed.status_code} {allowed.json()!r}")
    await _clear_access(ids["sensui"])


async def case_da1_dual_cookie_owner_not_restricted(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    await vault_cache.put("accAva", LISTS_KEY, {
        "list": [{"id": 1, "name": "Best"}, {"id": 2, "name": "Teasers"}], "hasMore": False,
    })
    await vault_cache.put("accAva", _media_key(2), {"list": [{"id": 222}], "hasMore": False})
    await _set_folder_access(ids["sensui"], "accAva", [(1, "Best")])

    # Same browser carries BOTH cookies. User cookie wins → owner view → NO
    # folder restriction, even though a chatter_folder_access row exists.
    c = _login_both("velvetvoice", "sensui")
    r = c.get("/api/of/v2/vault/lists", headers={"X-Account-Id": "accAva"})
    seen = [f["id"] for f in r.json().get("list", [])]
    _expect("dual-cookie (user+chatter) is treated as OWNER → vault/lists unfiltered",
            seen == [1, 2], detail=f"got {seen!r}")

    m = c.get("/api/of/v2/vault/media?list_id=2", headers={"X-Account-Id": "accAva"})
    _expect("dual-cookie owner is NOT soft-denied on a folder the chatter can't see",
            m.json().get("list") == [{"id": 222}], detail=f"got {m.json()!r}")
    await _clear_access(ids["sensui"])


async def case_owner_endpoints_guards(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    owner_a = _login_user("velvetvoice")

    # Cross-owner: owner A cannot grant access to accFounder (owner B's account).
    cross = owner_a.put(
        f"/admin/chatters/{ids['sensui']}/account-access",
        json={"account_ids": ["accFounder"]},
    )
    _expect("owner cannot put account-access for an account they don't own",
            cross.status_code == 403, detail=f"got {cross.status_code}")

    good = owner_a.put(
        f"/admin/chatters/{ids['sensui']}/account-access",
        json={"account_ids": ["accAva"]},
    )
    _expect("owner CAN restrict to their own account", good.status_code == 200,
            detail=f"got {good.status_code} {good.text[:160]}")

    acc = owner_a.get(f"/admin/chatters/{ids['sensui']}/access").json()
    _expect("GET access reflects this owner's allowlist",
            acc.get("account_ids") == ["accAva"], detail=f"got {acc!r}")

    # Cross-owner folder grant is rejected too.
    cross_f = owner_a.put(
        f"/admin/chatters/{ids['sensui']}/folder-access",
        json={"account_id": "accFounder", "folders": [{"folder_id": 1, "folder_name": "x"}]},
    )
    _expect("owner cannot put folder-access for an account they don't own",
            cross_f.status_code == 403, detail=f"got {cross_f.status_code}")

    # Not-linked: owner A manages a chatter linked only to owner B → 404.
    nl = owner_a.get(f"/admin/chatters/{ids['solo_b']}/access")
    _expect("owner gets 404 reading access for a chatter not linked to them",
            nl.status_code == 404, detail=f"got {nl.status_code}")

    # A chatter cookie cannot reach the owner-only management surface at all
    # (/admin/chatters is a blocked prefix for chatter sessions).
    chatter = _login_chatter("sensui")
    cput = chatter.put(
        f"/admin/chatters/{ids['sensui']}/account-access",
        json={"account_ids": ["accAva"]},
    )
    _expect("chatter cookie is 403 on /admin/chatters/*/account-access",
            cput.status_code == 403, detail=f"got {cput.status_code}")
    await _clear_access(ids["sensui"])


async def case_me_folder_access_shape(ids: dict[str, str]) -> None:
    await _clear_access(ids["sensui"])
    c = _login_chatter("sensui")

    # No rows → restricted=False (picker shows OF's full list).
    none = c.get("/chatter/me/folder-access?account_id=accAva").json()
    _expect("me/folder-access restricted=False when no rows",
            none["restricted"] is False and none["folders"] == [],
            detail=f"got {none!r}")

    # Foreign account (not in the chatter's union) → 403.
    foreign = c.get("/chatter/me/folder-access?account_id=accForeign")
    _expect("me/folder-access 403s for an account outside the union",
            foreign.status_code == 403, detail=f"got {foreign.status_code}")

    # Deterministic order: insert out of order + a >int32 id (BigInteger).
    big = 5_000_000_000
    await _set_folder_access(ids["sensui"], "accAva", [
        (2, "Zebra"), (big, "Alpha"), (1, "Middle"),
    ])
    resp = c.get("/chatter/me/folder-access?account_id=accAva").json()
    order = [(f["folder_id"], f["folder_name"]) for f in resp["folders"]]
    _expect("me/folder-access restricted=True", resp["restricted"] is True)
    _expect("folders are ordered by (name, id)",
            order == [(big, "Alpha"), (1, "Middle"), (2, "Zebra")],
            detail=f"got {order!r}")
    _expect("BigInteger folder_id (>int32) round-trips intact",
            any(f["folder_id"] == big for f in resp["folders"]),
            detail=f"got {order!r}")
    await _clear_access(ids["sensui"])


# ── 6. Driver ────────────────────────────────────────────────────────

async def _main() -> int:
    print(f"Using DB: {_TMP_DB}")
    ids = await _setup()
    cases = [
        ("account gate + multi-owner isolation", case_account_gate_and_isolation),
        ("account gate enforces at the resolve boundary", case_account_gate_blocks_resolve),
        ("vault/lists folder filter (owner sees all)", case_vault_lists_filtered),
        ("vault/media soft-deny + allowed pass-through", case_vault_media_softdeny_and_allow),
        ("DA-1 dual-cookie owner not restricted", case_da1_dual_cookie_owner_not_restricted),
        ("owner endpoint guards (cross-owner / 404 / chatter)", case_owner_endpoints_guards),
        ("me/folder-access shape + order + BigInteger", case_me_folder_access_shape),
    ]
    for i, (title, fn) in enumerate(cases, 1):
        print(f"\n─── Case {i}: {title} " + "─" * max(2, 40 - len(title)))
        await fn(ids)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"All {len(cases)} cases passed.")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(_main())
    finally:
        for ext in ("", "-wal", "-shm"):
            p = Path(str(_TMP_DB) + ext)
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    raise SystemExit(rc)
