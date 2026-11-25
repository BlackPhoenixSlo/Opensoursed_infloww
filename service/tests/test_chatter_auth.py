#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


# Bind a throwaway DB before importing service modules: engine code can fall back to service/chatterly.db (PROD).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_test_{uuid.uuid4().hex}.db"
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
    Employee,
    User,
    UserAccount,
)


async def _bootstrap_db() -> None:
    await init_db()


asyncio.run(_bootstrap_db())



from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import server  # noqa: E402  — sets up routers + middlewares against engine
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402


client = TestClient(server.app)




async def _seed_user(username: str, password: str = "secretpw") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password))
    return uid


async def _seed_account(account_id: str, owner_user_id: str, nickname: str = "model") -> None:
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
    import events
    from db.models import ChatterUser
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=chatter_id, user_id=user_id, created_at=datetime.utcnow()))
        events.on_commit(s, "assignment_changed", agency=user_id)


async def _unlink_chatter(chatter_id: str, user_id: str) -> None:
    import events
    from db.models import ChatterUser
    from sqlalchemy import delete
    async with get_session() as s:
        await s.execute(delete(ChatterUser).where(
            ChatterUser.chatter_id == chatter_id,
            ChatterUser.user_id == user_id,
        ))
        events.on_commit(s, "assignment_changed", agency=user_id)



FAILURES: list[str] = []


def _expect(case: str, condition: bool, detail: str = "") -> None:
    label = case if not detail else f"{case} — {detail}"
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
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




async def _setup() -> dict[str, str]:
    alice = await _seed_user("alice")
    bob = await _seed_user("bob")
    await _seed_account("acct_alice", alice, nickname="alice's model")
    await _seed_account("acct_bob", bob, nickname="bob's model")
    await _seed_account("acct_shared", alice, nickname="shared model")
    async with get_session() as s:
        s.add(UserAccount(user_id=bob, account_id="acct_shared"))

    tim = await _seed_chatter("tim")
    await _link_chatter(tim, alice)
    await _link_chatter(tim, bob)
    await seed_pre_enforcement_install()
    return {"alice": alice, "bob": bob, "tim": tim}




def case_chatter_blocked_from_admin_users(_ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    r = c.get("/admin/users")
    _expect(
        "chatter cookie cannot read /admin/users",
        r.status_code == 403,
        detail=f"got {r.status_code}",
    )


def case_anonymous_cannot_reach_admin(_ids: dict[str, str]) -> None:
    c = _fresh_client()
    for path in ("/admin/accounts", "/api/of/me"):
        r = c.get(path)
        _expect(
            f"anonymous request cannot reach {path}",
            r.status_code == 401,
            detail=f"got {r.status_code} — the isolation gate is not in the stack",
        )


def case_chatter_blocked_from_other_user_accounts(ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    r = c.get(f"/admin/users/{ids['alice']}/accounts")
    _expect(
        "chatter cookie cannot read /admin/users/{other}/accounts",
        r.status_code == 403,
        detail=f"got {r.status_code}",
    )


def case_chatter_blocked_from_mutating_useraccount(ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    grant = c.post(
        f"/admin/users/{ids['alice']}/accounts",
        json={"account_id": "acct_alice", "admin_password": os.environ["ADMIN_PASSWORD"]},
    )
    impersonate = c.post(
        "/admin/impersonate",
        json={"user_id": ids["alice"], "admin_password": os.environ["ADMIN_PASSWORD"]},
    )
    _expect(
        "chatter cannot grant UserAccount", grant.status_code == 403,
        detail=f"got {grant.status_code}",
    )
    _expect(
        "chatter cannot impersonate", impersonate.status_code == 403,
        detail=f"got {impersonate.status_code}",
    )


def case_user_cookie_cannot_mint_chatter_session(_ids: dict[str, str]) -> None:
    c = _login_user("alice")
    # /chatter/me answers null, not 401, so the AuthGate can probe both principals without a DevTools error.
    r = c.get("/chatter/me")
    body = r.json()
    _expect(
        "User cookie does NOT auto-mint a chatter session",
        r.status_code == 200 and body is None,
        detail=f"got {r.status_code} body={body!r}",
    )


async def case_audit_ignores_chatter_x_employee_id(ids: dict[str, str]) -> None:
    # A chatter-supplied X-Employee-Id must be dropped; audit resolves the per-(chatter, owner) mirror Employee.
    async with get_session() as s:
        s.add(Employee(
            id=9999, display_name="fake", color="#000",
            is_active=True, user_id=ids["alice"], chatter_id=None,
        ))

    c = _login_chatter("tim")
    r = c.post("/chatter/logout", headers={
        "X-Employee-Id": "9999",
        "X-Account-Id": "acct_alice",
    })
    assert r.status_code == 200

    from db.models import Action
    async with get_session() as s:
        last = (await s.execute(
            select(Action).where(Action.account_id == "acct_alice")
            .order_by(Action.at.desc()).limit(1)
        )).scalar_one_or_none()
    _expect(
        "X-Employee-Id from chatter is ignored",
        last is None or last.employee_id != 9999,
        detail=f"action.employee_id={last.employee_id if last else None}",
    )
    if last is not None:
        async with get_session() as s:
            emp = await s.get(Employee, last.employee_id) if last.employee_id else None
        _expect(
            "audit attributes to per-(chatter, owner) mirror Employee",
            emp is not None and emp.chatter_id == ids["tim"] and emp.user_id == ids["alice"],
            detail=f"emp={emp.id if emp else None} chatter_id={emp.chatter_id if emp else None}",
        )


async def case_unlink_strips_account_ids_next_request(ids: dict[str, str]) -> None:
    c = _login_chatter("tim")

    r = c.get("/chatter/me/accounts")
    before = {a["account_id"] for a in r.json()}
    _expect(
        "chatter sees union of both owners' accounts before unlink",
        before == {"acct_alice", "acct_bob", "acct_shared"},
        detail=f"got {before!r}",
    )

    await _unlink_chatter(ids["tim"], ids["alice"])

    r = c.get("/chatter/me/accounts")
    after = {a["account_id"] for a in r.json()}
    _expect(
        "unlink strips owner's accounts from union on NEXT request",
        after == {"acct_bob", "acct_shared"},
        detail=f"got {after!r}",
    )

    await _link_chatter(ids["tim"], ids["alice"])


async def case_account_ids_is_set_union_no_dupes(_ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    r = c.get("/chatter/me/accounts")
    rows = r.json()
    ids_in_payload = [a["account_id"] for a in rows]
    _expect(
        "account_ids is set union — duplicates appear once",
        ids_in_payload.count("acct_shared") == 1,
        detail=f"acct_shared appeared {ids_in_payload.count('acct_shared')}×",
    )


async def case_chatter_per_account_admin_works(_ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    r_ok = c.get("/admin/saved-replies?account_id=acct_alice")
    _expect(
        "chatter can GET /admin/saved-replies for an allowed account",
        r_ok.status_code == 200,
        detail=f"got {r_ok.status_code} {r_ok.text[:200]}",
    )

    async with get_session() as s:
        s.add(Account(id="acct_foreign", nickname="not yours", color="#000"))

    r_blocked = c.get("/admin/saved-replies?account_id=acct_foreign")
    _expect(
        "chatter cannot reach saved-replies for a foreign account",
        r_blocked.status_code == 403,
        detail=f"got {r_blocked.status_code}",
    )


async def case_chatter_owner_admin_still_blocked(_ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    for path in (
        "/admin/users",
        "/admin/impersonate",
        "/admin/chatters",
        "/admin/proxies",
        "/admin/accounts",
        "/admin/audit",
    ):
        r = c.get(path)
        _expect(
            f"chatter still 403 on {path}",
            r.status_code == 403,
            detail=f"got {r.status_code}",
        )


async def case_employee_filter_team_transparency(ids: dict[str, str]) -> None:
    linked_emp_id = 88888
    async with get_session() as s:
        s.add(Employee(
            id=linked_emp_id, display_name="alice's own", color="#fff",
            is_active=True, user_id=ids["alice"], chatter_id=None,
        ))
    carol_id = await _seed_user("carol")
    unlinked_emp_id = 88889
    async with get_session() as s:
        s.add(Employee(
            id=unlinked_emp_id, display_name="carol's own", color="#000",
            is_active=True, user_id=carol_id, chatter_id=None,
        ))
        s.add(Account(id="acct_carol", nickname="carol's model", color="#0f0"))
        from db.models import UserAccount as _UA
        s.add(_UA(user_id=carol_id, account_id="acct_carol"))

    c = _login_chatter("tim")

    paid_linked = c.get(
        f"/admin/paid-messages?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_alice&employee_id={linked_emp_id}",
    )
    _expect(
        "chatter CAN filter by an employee under a linked owner",
        paid_linked.status_code == 200,
        detail=f"got {paid_linked.status_code} {paid_linked.text[:200]}",
    )

    paid_cross = c.get(
        f"/admin/paid-messages?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_alice&employee_id={unlinked_emp_id}",
    )
    tips_cross = c.get(
        f"/admin/tips-list?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_alice&employee_id={unlinked_emp_id}",
    )
    top_cross = c.get(
        f"/admin/top-tippers?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_alice&employee_id={unlinked_emp_id}",
    )
    _expect(
        "chatter CANNOT filter by an employee under an unlinked owner (paid-messages)",
        paid_cross.status_code == 403,
        detail=f"got {paid_cross.status_code}",
    )
    _expect(
        "chatter CANNOT filter by an employee under an unlinked owner (tips-list)",
        tips_cross.status_code == 403,
        detail=f"got {tips_cross.status_code}",
    )
    _expect(
        "chatter CANNOT filter by an employee under an unlinked owner (top-tippers)",
        top_cross.status_code == 403,
        detail=f"got {top_cross.status_code}",
    )

    paid_open = c.get(
        "/admin/paid-messages?from=2026-01-01&to=2026-12-31&account_id=acct_alice",
    )
    _expect(
        "chatter can still read /admin/paid-messages without employee_id filter",
        paid_open.status_code == 200,
        detail=f"got {paid_open.status_code}",
    )


async def case_owner_cannot_filter_other_owners_employees(ids: dict[str, str]) -> None:
    bob_emp_id = 77777
    async with get_session() as s:
        s.add(Employee(
            id=bob_emp_id, display_name="bob's own", color="#fff",
            is_active=True, user_id=ids["bob"], chatter_id=None,
        ))

    c = _login_user("alice")
    r = c.get(
        f"/admin/paid-messages?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_shared&employee_id={bob_emp_id}",
    )
    _expect(
        "owner cannot filter /admin/paid-messages by another owner's employee_id",
        r.status_code == 403,
        detail=f"got {r.status_code}",
    )


async def case_step11_happy_path_per_owner_mirrors(ids: dict[str, str]) -> None:
    from db.models import Action
    c = _login_chatter("tim")
    r1 = c.post("/chatter/logout", headers={"X-Account-Id": "acct_alice"})
    c = _login_chatter("tim")
    r2 = c.post("/chatter/logout", headers={"X-Account-Id": "acct_bob"})
    assert r1.status_code == 200 and r2.status_code == 200

    async with get_session() as s:
        last_alice = (await s.execute(
            select(Action).where(Action.account_id == "acct_alice")
            .order_by(Action.at.desc()).limit(1)
        )).scalar_one_or_none()
        last_bob = (await s.execute(
            select(Action).where(Action.account_id == "acct_bob")
            .order_by(Action.at.desc()).limit(1)
        )).scalar_one_or_none()
        emp_alice = await s.get(Employee, last_alice.employee_id) if last_alice and last_alice.employee_id else None
        emp_bob = await s.get(Employee, last_bob.employee_id) if last_bob and last_bob.employee_id else None

    _expect(
        "alice's model mirror Employee is tied to (tim, alice)",
        emp_alice is not None
        and emp_alice.chatter_id == ids["tim"]
        and emp_alice.user_id == ids["alice"],
        detail=f"emp={emp_alice.id if emp_alice else None} chatter={emp_alice.chatter_id if emp_alice else None} owner={emp_alice.user_id if emp_alice else None}",
    )
    _expect(
        "bob's model mirror Employee is tied to (tim, bob)",
        emp_bob is not None
        and emp_bob.chatter_id == ids["tim"]
        and emp_bob.user_id == ids["bob"],
        detail=f"emp={emp_bob.id if emp_bob else None} chatter={emp_bob.chatter_id if emp_bob else None} owner={emp_bob.user_id if emp_bob else None}",
    )
    _expect(
        "alice's and bob's mirror Employees are DIFFERENT rows",
        emp_alice is not None and emp_bob is not None and emp_alice.id != emp_bob.id,
        detail=f"alice_emp={emp_alice.id if emp_alice else None} bob_emp={emp_bob.id if emp_bob else None}",
    )


def case_me_exposes_registration_time(_ids: dict[str, str]) -> None:
    # UTC offset required: a naive stamp is read as browser-local time.
    for label, client, path in (
        ("/auth/me", _login_user("alice"), "/auth/me"),
        ("/chatter/me", _login_chatter("tim"), "/chatter/me"),
    ):
        created = (client.get(path).json() or {}).get("created_at")
        ok = False
        if isinstance(created, str):
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            ok = dt.utcoffset() is not None and dt.utcoffset().total_seconds() == 0
        _expect(f"{label} carries created_at in UTC", ok, detail=f"got {created!r}")




async def _main() -> int:
    print(f"Using DB: {_TMP_DB}")
    ids = await _setup()

    print()
    print("─── Case 1 ─────────────────────────────────────")
    case_chatter_blocked_from_admin_users(ids)

    print("─── Case 13 (anonymous cannot reach /admin) ───")
    case_anonymous_cannot_reach_admin(ids)

    print()
    print("─── Case 2 ─────────────────────────────────────")
    case_chatter_blocked_from_other_user_accounts(ids)

    print()
    print("─── Case 3 ─────────────────────────────────────")
    case_chatter_blocked_from_mutating_useraccount(ids)

    print()
    print("─── Case 4 ─────────────────────────────────────")
    case_user_cookie_cannot_mint_chatter_session(ids)

    print()
    print("─── Case 5 ─────────────────────────────────────")
    await case_audit_ignores_chatter_x_employee_id(ids)

    print()
    print("─── Case 6 ─────────────────────────────────────")
    await case_unlink_strips_account_ids_next_request(ids)

    print()
    print("─── Case 7 ─────────────────────────────────────")
    await case_account_ids_is_set_union_no_dupes(ids)

    print()
    print("─── Case 8 (per-account /admin/* gate) ─────────")
    await case_chatter_per_account_admin_works(ids)

    print()
    print("─── Case 9 (owner-only /admin/* still blocked) ─")
    await case_chatter_owner_admin_still_blocked(ids)

    print()
    print("─── Case 10 (Step 11 happy path) ───────────────")
    await case_step11_happy_path_per_owner_mirrors(ids)

    print()
    print("─── Case 11 (employee_id filter team-transparency) ─")
    await case_employee_filter_team_transparency(ids)

    print()
    print("─── Case 12 (owner cross-employee_id filter) ───")
    await case_owner_cannot_filter_other_owners_employees(ids)

    print()
    print("─── Case 14 (me carries registration time) ────")
    case_me_exposes_registration_time(ids)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All cases passed.")
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
