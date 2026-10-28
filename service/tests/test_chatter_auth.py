#!/usr/bin/env python3
"""
Step 10 of Todo.txt STEP 8 — chatter-auth security tests.

The project doesn't ship pytest; this file is intentionally written as a
stand-alone script with plain assertions so it can be run via:

    ./venv/bin/python service/tests/test_chatter_auth.py

It boots a temp SQLite DB, seeds two owners (@alice, @bob) each with one
OF account, lazy-creates a chatter (Tim), and exercises the seven cases
the STEP 8 plan calls out. Exit code 0 = all pass; non-zero = first
failing case logged.

Each case is independent. Failures don't short-circuit subsequent cases
so a single CI run surfaces every regression at once.

Why TestClient and not `requests` against a live relay: TestClient runs
the full ASGI app in-process, so we can write directly to the test DB
without racing the running relay's session middleware. The cookie jar
behaves the same as a browser would.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# ── 1. Hard-bind the DB BEFORE importing any service module that touches
# the engine. Past incident memory: alembic / engine code can silently
# fall back to service/chatterly.db (PROD) if these env-vars are unset.

_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
# Disable the share-token gate so test requests don't need ?t=…
os.environ["SHARE_TOKEN"] = ""
# Stable secrets so cookies are reproducible across reruns of this file.
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

# ── 2. Bring the schema up. The engine's init_db() does additive
# create_all + column catch-up which is what gets us to a usable DB
# without running alembic (the project's runtime path).

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


# ── 3. Now import the app — engine + models are already loaded against
# the temp DB.

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

import server  # noqa: E402  — sets up routers + middlewares against engine
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402
from db.engine import get_session  # noqa: E402


client = TestClient(server.app)


# ── 4. Seeders — drop rows in via SQLAlchemy so we don't have to climb
# through the founder-password endpoints.


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
    # As the product's link (account_security.link_login): `assignment_changed` on commit.
    import events
    from db.models import ChatterUser
    async with get_session() as s:
        s.add(ChatterUser(chatter_id=chatter_id, user_id=user_id, created_at=datetime.utcnow()))
        events.on_commit(s, "assignment_changed", agency=user_id)


async def _unlink_chatter(chatter_id: str, user_id: str) -> None:
    # As the product's unlink (employees.py): `assignment_changed` on commit.
    import events
    from db.models import ChatterUser
    from sqlalchemy import delete
    async with get_session() as s:
        await s.execute(delete(ChatterUser).where(
            ChatterUser.chatter_id == chatter_id,
            ChatterUser.user_id == user_id,
        ))
        events.on_commit(s, "assignment_changed", agency=user_id)


# ── 5. Helpers.

FAILURES: list[str] = []


def _expect(case: str, condition: bool, detail: str = "") -> None:
    label = case if not detail else f"{case} — {detail}"
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}")
        FAILURES.append(label)


def _fresh_client() -> TestClient:
    """A new TestClient each test so cookies from previous cases don't
    bleed across. (TestClient shares a cookie jar within an instance.)"""
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


# ── 6. Setup phase: two owners, two accounts, one chatter linked to both.


async def _setup() -> dict[str, str]:
    alice = await _seed_user("alice")
    bob = await _seed_user("bob")
    await _seed_account("acct_alice", alice, nickname="alice's model")
    await _seed_account("acct_bob", bob, nickname="bob's model")
    # Shared account granted to BOTH owners (cross-grant edge case).
    await _seed_account("acct_shared", alice, nickname="shared model")
    async with get_session() as s:
        s.add(UserAccount(user_id=bob, account_id="acct_shared"))

    tim = await _seed_chatter("tim")
    await _link_chatter(tim, alice)
    await _link_chatter(tim, bob)
    # An install from before role enforcement was on by default: its logins hold Admin.
    await seed_pre_enforcement_install()
    return {"alice": alice, "bob": bob, "tim": tim}


# ── 7. The cases.


def case_chatter_blocked_from_admin_users(_ids: dict[str, str]) -> None:
    c = _login_chatter("tim")
    r = c.get("/admin/users")
    _expect(
        "chatter cookie cannot read /admin/users",
        r.status_code == 403,
        detail=f"got {r.status_code}",
    )


def case_anonymous_cannot_reach_admin(_ids: dict[str, str]) -> None:
    """The gate must be IN the real ASGI stack, not merely importable.

    Every case in `test_account_isolation_gate.py` calls the middleware function
    directly and sets the contextvar by hand, so all of them pass even if the
    middleware is never registered with the app at all. This case is the only one
    that sends a real cookieless request through the real stack.

    RED via: deleting the 401 branch, or dropping
    `app.middleware("http")(_account_isolation_middleware)` from server.py.

    ⚠️ It does NOT catch the registration being moved back below the session
    middlewares — that was measured, not assumed: with the registration moved, this
    case still passes 401 (for the wrong reason — the gate now runs before any
    cookie is read and refuses EVERYONE). What catches that regression is the other
    19 cases in this file going red with `got 401` on a legitimately signed-in
    chatter. That is the safety property worth knowing: since 2026-08-10 a
    misplaced registration fails LOUD. Before, when the gate abstained on an
    unidentified caller, the same mistake was silent — which is how it sat dead in
    production for months.
    """
    c = _fresh_client()          # never logs in — no session cookie of any kind
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
    # Grant + impersonate are both /admin/* — the chatter
    # middleware blocks the whole prefix.
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
    # An owner-signed-in TestClient hits /chatter/me — it should NOT
    # auto-mint a chatter session just because the user is authed.
    c = _login_user("alice")
    r = c.get("/chatter/me")
    # /chatter/me returns null when no chatter cookie is present (not 401
    # — by design, so the AuthGate can probe both principals in parallel
    # without a noisy error in DevTools).
    body = r.json()
    _expect(
        "User cookie does NOT auto-mint a chatter session",
        r.status_code == 200 and body is None,
        detail=f"got {r.status_code} body={body!r}",
    )


async def case_audit_ignores_chatter_x_employee_id(ids: dict[str, str]) -> None:
    # Tim sends a fabricated X-Employee-Id pointing at Alice's domain;
    # the audit pipeline must drop it and instead resolve a per-(chatter,
    # owner) mirror Employee.id stamped with chatter_id=Tim.
    #
    # We can't hit a real /api/of/* (would need a captured OF session)
    # but the audit middleware fires on ANY 2xx-mutating endpoint. We
    # use the chatter logout endpoint (POST, returns 200, on the audit
    # path) as a no-cost trigger.
    # First seed a fabricated "owner Employee" Alice doesn't own so we
    # can prove the header isn't honored.
    async with get_session() as s:
        s.add(Employee(
            id=9999, display_name="fake", color="#000",
            is_active=True, user_id=ids["alice"], chatter_id=None,
        ))

    c = _login_chatter("tim")
    # POST /chatter/logout is on the audit path (POST, 2xx, not in skip
    # prefixes). With X-Employee-Id=9999 the audit must NOT use it.
    r = c.post("/chatter/logout", headers={
        "X-Employee-Id": "9999",
        "X-Account-Id": "acct_alice",
    })
    assert r.status_code == 200

    # Most recent action row for this account should NOT carry emp_id=9999.
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
        # The resolver creates the mirror Employee under (chatter=tim,
        # owner=alice) since acct_alice belongs to alice.
        async with get_session() as s:
            emp = await s.get(Employee, last.employee_id) if last.employee_id else None
        _expect(
            "audit attributes to per-(chatter, owner) mirror Employee",
            emp is not None and emp.chatter_id == ids["tim"] and emp.user_id == ids["alice"],
            detail=f"emp={emp.id if emp else None} chatter_id={emp.chatter_id if emp else None}",
        )


async def case_unlink_strips_account_ids_next_request(ids: dict[str, str]) -> None:
    # Tim is linked to both alice and bob. /chatter/me/accounts should
    # list 3 accounts (acct_alice, acct_bob, acct_shared). After alice
    # unlinks tim, the NEXT request should see only acct_bob + acct_shared
    # — no stale cache (chatter_identity_cache.py), no leftover.
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

    # Re-link for downstream tests.
    await _link_chatter(ids["tim"], ids["alice"])


async def case_account_ids_is_set_union_no_dupes(_ids: dict[str, str]) -> None:
    # acct_shared was granted to BOTH alice and bob (cross-grant). Tim is
    # linked to both. The UNION must contain acct_shared exactly once.
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
    """The chatter-admin gate must ALLOW per-account /admin/* surfaces
    (saved-replies, mass-messages, etc.) so the Templates / Mass tabs
    work — and the underlying account-id check must still 403 a chatter
    who asks about an account they aren't linked to."""
    c = _login_chatter("tim")
    # tim is linked to alice + bob; acct_alice is on the allowed list.
    r_ok = c.get("/admin/saved-replies?account_id=acct_alice")
    _expect(
        "chatter can GET /admin/saved-replies for an allowed account",
        r_ok.status_code == 200,
        detail=f"got {r_ok.status_code} {r_ok.text[:200]}",
    )

    # Forge a brand-new account that tim's owners do NOT hold; the
    # account-isolation middleware should 403.
    async with get_session() as s:
        s.add(Account(id="acct_foreign", nickname="not yours", color="#000"))

    r_blocked = c.get("/admin/saved-replies?account_id=acct_foreign")
    _expect(
        "chatter cannot reach saved-replies for a foreign account",
        r_blocked.status_code == 403,
        detail=f"got {r_blocked.status_code}",
    )


async def case_chatter_owner_admin_still_blocked(_ids: dict[str, str]) -> None:
    """Owner-only /admin/* prefixes (users/impersonate/chatters/proxies/
    accounts/audit) must still 403 — the blocklist replaced the
    blanket gate, not weakened it."""
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
    """A chatter linked to owner X may filter stats by ANY Employee
    owned by X (team-transparency model). The gate only rejects filters
    pointing at employees under owners the chatter ISN'T linked to —
    that would be a cross-agency leak.

    Setup:
      • Tim is linked to Alice and Bob.
      • Employee 88888 belongs to Alice → Tim CAN filter by it.
      • Seed an unlinked third owner "carol" with Employee 88889 →
        Tim CANNOT filter by it (cross-agency).
    """
    # Linked-owner employee — chatter is allowed.
    linked_emp_id = 88888
    async with get_session() as s:
        s.add(Employee(
            id=linked_emp_id, display_name="alice's own", color="#fff",
            is_active=True, user_id=ids["alice"], chatter_id=None,
        ))
    # Unlinked-owner employee — chatter is denied.
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

    # Linked-owner filter is now ALLOWED. acct_alice is in tim's union.
    paid_linked = c.get(
        f"/admin/paid-messages?from=2026-01-01&to=2026-12-31"
        f"&account_id=acct_alice&employee_id={linked_emp_id}",
    )
    _expect(
        "chatter CAN filter by an employee under a linked owner",
        paid_linked.status_code == 200,
        detail=f"got {paid_linked.status_code} {paid_linked.text[:200]}",
    )

    # Cross-agency filter — Tim isn't linked to Carol. Even passing one
    # of his own accounts as account_id (acct_alice), the second axis
    # (employee_id under Carol) must 403.
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

    # Sanity: omitting employee_id still works.
    paid_open = c.get(
        "/admin/paid-messages?from=2026-01-01&to=2026-12-31&account_id=acct_alice",
    )
    _expect(
        "chatter can still read /admin/paid-messages without employee_id filter",
        paid_open.status_code == 200,
        detail=f"got {paid_open.status_code}",
    )


async def case_owner_cannot_filter_other_owners_employees(ids: dict[str, str]) -> None:
    """Same axis from the owner side. Founder/alice cannot ask `?employee_id=`
    pointing at bob's employee — would surface bob's audit slice under
    alice's account scope (if the account is shared)."""
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
    # Step 11 of the plan: Tim acts on alice's model AND bob's model.
    # Audit rows must attribute to TWO distinct Employee rows, each
    # tied to (chatter=tim, owner=alice|bob) — confirming the per-owner
    # mirror is materialised on first hit and reused thereafter.
    from db.models import Action
    c = _login_chatter("tim")
    # Two audit-path mutations, one per owner's account.
    r1 = c.post("/chatter/logout", headers={"X-Account-Id": "acct_alice"})
    # Re-login since logout cleared the cookie.
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
    # The UI counts the 7-day free trial from the signed-in principal's own
    # registration, so both /auth/me and /chatter/me carry it, with a UTC
    # offset (a naive stamp would be read as browser-local time).
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


# ── 8. Driver.


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
        # Best-effort cleanup of the temp DB; SQLite WAL/SHM siblings too.
        for ext in ("", "-wal", "-shm"):
            p = Path(str(_TMP_DB) + ext)
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    raise SystemExit(rc)
