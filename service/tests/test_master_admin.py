#!/usr/bin/env python3
"""
Master/admin role — `users.is_admin` (migration 0039_user_is_admin).

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_master_admin.py

A master (is_admin=1) is handed the FULL registry account set as its
request-time `account_ids` snapshot, so every per-account gate
(`assert_account_owned`, `_resolve_account_id`, the isolation middleware)
passes — AND the employee-roster scoping (a different column) is bypassed.

Fixture:
    owner A "velvetvoice"  → accAva, accCelest   (normal owner)
    owner B "founder"      → accFounder              (is_admin = MASTER)
    owner C "stranger"       → accForeign           (normal owner)
    one Employee under each owner.

Cases:
  case_master_clears_account_gate:
      the master GETs a per-account endpoint for an account it does NOT own
      via user_accounts (accForeign) → 200, not 403. The registry-sourced fat
      set is what makes _resolve_account_id + the isolation middleware pass.
  case_master_sees_all_rosters:
      /admin/employees returns every owner's employee, minus the sentinel.
  case_non_admin_still_blocked  (the negative test that proves we didn't just
      open the gate for everyone):
      a normal owner is 403 on a non-owned account AND sees only its own
      employee.

Exit 0 = all pass.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# ── 1. Hard-bind a throwaway DB BEFORE importing any service module (unset
# env can fall back to PROD — same incident guard as the chatter tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_master_{uuid.uuid4().hex}.db"
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
from db.models import Account, AutomationRule, Employee, User, UserAccount  # noqa: E402

asyncio.run(init_db())

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402

# The master's account_ids snapshot is built from the in-process registry
# (accounts.account_ids — the id SET; `list_accounts` builds the same answer by
# reading a meta.json per account, which is a directory walk on every request
# the master makes), and _resolve_account_id / the isolation middleware also
# consult the registry. Make ALL of them recognise our DB-seeded ids in-process
# so the gate logic — not a missing filesystem meta dir — is what we test.
_TEST_ACCOUNTS = {"accAva", "accCelest", "accFounder", "accForeign"}
_orig_get_account = account_registry.get_account
_orig_list_accounts = account_registry.list_accounts


def _patched_get_account(account_id: str):
    if account_id in _TEST_ACCOUNTS:
        return {"id": account_id, "nickname": account_id}
    return _orig_get_account(account_id)


def _patched_list_accounts():
    return [{"id": aid, "nickname": aid} for aid in sorted(_TEST_ACCOUNTS)]


account_registry.get_account = _patched_get_account
account_registry.list_accounts = _patched_list_accounts
# What `auth.session_middleware` actually asks for the master's set.
account_registry.account_ids = lambda: frozenset(_TEST_ACCOUNTS)
# The isolation middleware asks per-candidate (one stat, no descriptor).
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS


# ── 2. Seeders ───────────────────────────────────────────────────────

async def _seed_user(username: str, is_admin: bool = False, password: str = "secretpw") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password, is_admin=is_admin))
    return uid


async def _seed_account(account_id: str, owner_user_id: str, nickname: str) -> None:
    async with get_session() as s:
        s.add(Account(id=account_id, nickname=nickname, color="#aaaaaa"))
        s.add(UserAccount(user_id=owner_user_id, account_id=account_id))


async def _seed_employee(display_name: str, owner_user_id: str) -> int:
    async with get_session() as s:
        e = Employee(display_name=display_name, user_id=owner_user_id, is_active=True)
        s.add(e)
        await s.flush()
        return e.id


# ── 3. Harness ───────────────────────────────────────────────────────

FAILURES: list[str] = []


def _expect(case: str, condition: bool, detail: str = "") -> None:
    label = case if not detail else f"{case} — {detail}"
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILURES.append(label)


def _login(username: str, password: str = "secretpw") -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login {username!r} failed: {r.status_code} {r.text}"
    return c


# ── 4. Fixture ───────────────────────────────────────────────────────

async def _setup() -> dict[str, object]:
    owner_a = await _seed_user("velvetvoice")
    master = await _seed_user("founder", is_admin=True)
    owner_c = await _seed_user("stranger")
    await _seed_account("accAva", owner_a, "Ava")
    await _seed_account("accCelest", owner_a, "Celest2")
    await _seed_account("accFounder", master, "Test Race")
    await _seed_account("accForeign", owner_c, "not yours")

    emp_a = await _seed_employee("Alice (A)", owner_a)
    emp_b = await _seed_employee("Bob (B/master)", master)
    emp_c = await _seed_employee("Carol (C)", owner_c)
    return {"emp_a": emp_a, "emp_b": emp_b, "emp_c": emp_c}


# ── 5. Cases ─────────────────────────────────────────────────────────

async def case_master_clears_account_gate(_ids: dict[str, object]) -> None:
    master = _login("founder")
    # accForeign is owned by owner C, NOT by the master via user_accounts.
    own = master.get("/admin/saved-replies?account_id=accFounder")
    foreign = master.get("/admin/saved-replies?account_id=accForeign")
    _expect("master reaches its own account", own.status_code == 200,
            detail=f"got {own.status_code}")
    _expect("master reaches a NON-owned account (fat set clears the gate)",
            foreign.status_code == 200, detail=f"got {foreign.status_code}")


async def case_master_sees_all_rosters(ids: dict[str, object]) -> None:
    master = _login("founder")
    rows = master.get("/admin/employees").json()["employees"]
    seen = {e["id"] for e in rows}
    _expect("master sees every owner's employee",
            {ids["emp_a"], ids["emp_b"], ids["emp_c"]} <= seen,
            detail=f"got {sorted(seen)!r}")


async def case_master_reaches_a_db_only_account(_ids: dict[str, object]) -> None:
    """The master fat set is registry ∪ user_accounts — NOT the registry alone.

    accGhost exists only in the DB (an owner row, no registry entry — the
    retired/no-captured-session account shape, so it is deliberately absent
    from _TEST_ACCOUNTS). The live master's rules DELETE 403'd on exactly this
    on 2026-08-19: the registry-only snapshot made the master WEAKER than a
    regular owner for a DB-only account."""
    ghost_owner = await _seed_user("ghostowner")
    await _seed_account("accGhost", ghost_owner, "Ghost")
    async with get_session() as s:
        r1 = AutomationRule(account_id="accGhost", name="ghost rule",
                            kind="scrape_chats",
                            trigger_json='{"every_seconds": 120}',
                            steps_json='{}', is_enabled=True)
        r2 = AutomationRule(account_id="accGhost", name="ghost rule 2",
                            kind="scrape_chats",
                            trigger_json='{"every_seconds": 120}',
                            steps_json='{}', is_enabled=False)
        s.add(r1); s.add(r2)
        await s.flush()
        rid1, rid2 = r1.id, r2.id

    master = _login("founder")
    resp = master.delete(f"/admin/automation-rules/{rid1}")
    _expect("master deletes a rule on a DB-only account (union fat set)",
            resp.status_code == 200, detail=f"got {resp.status_code} {resp.text[:80]}")

    # The union must NOT open the gate for ordinary principals: a signed-in
    # non-owner is still 403 on the same account.
    other = _login("velvetvoice")
    resp2 = other.delete(f"/admin/automation-rules/{rid2}")
    _expect("non-owner still 403 on the DB-only account",
            resp2.status_code == 403, detail=f"got {resp2.status_code}")


async def case_non_admin_still_blocked(ids: dict[str, object]) -> None:
    owner_a = _login("velvetvoice")
    own = owner_a.get("/admin/saved-replies?account_id=accAva")
    foreign = owner_a.get("/admin/saved-replies?account_id=accForeign")
    _expect("non-admin reaches its own account", own.status_code == 200,
            detail=f"got {own.status_code}")
    _expect("non-admin is 403 on a non-owned account (gate NOT opened for all)",
            foreign.status_code == 403, detail=f"got {foreign.status_code}")

    rows = owner_a.get("/admin/employees").json()["employees"]
    seen = {e["id"] for e in rows}
    _expect("non-admin sees ONLY its own employee",
            seen & {ids["emp_a"], ids["emp_b"], ids["emp_c"]} == {ids["emp_a"]},
            detail=f"got {sorted(seen)!r}")


# ── 6. Runner ────────────────────────────────────────────────────────

async def _main() -> int:
    ids = await _setup()
    cases = [
        ("master clears the per-account gate", case_master_clears_account_gate),
        ("master sees all employee rosters", case_master_sees_all_rosters),
        ("master reaches a DB-only account", case_master_reaches_a_db_only_account),
        ("non-admin still blocked (negative)", case_non_admin_still_blocked),
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
