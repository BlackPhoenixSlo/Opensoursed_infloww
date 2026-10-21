#!/usr/bin/env python3
"""
Chatter access to the roster badges + per-model color picker.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_chatter_roster_color.py

A chatter-only session may now reach exactly TWO surfaces under
/admin/accounts (every other one stays owner-only):

  • GET   /admin/accounts/roster-counts  → the unread / owe-reply badges,
    scoped to the chatter's account union.
  • PATCH /admin/accounts/{id}           → recolor a model. The handler forces
    every field except `color` to None for a chatter, so a crafted body can't
    rename a model.

Fixture (mirrors the real velvetvoice chatter):
    owner A "velvetvoice"  → accAva, accCelest
    owner C "stranger"       → accForeign
    chatter "sensui"         → linked to owner A only (union = accAva, accCelest)

Cases:
  case_chatter_sees_badges        — GET roster-counts: 200, only the union's
                                     accounts, never accForeign.
  case_chatter_recolor_color_only — PATCH a union account: 200, and upsert was
                                     called with ONLY color (nickname / incog
                                     forced to None even though the body sent them).
  case_chatter_recolor_foreign_403 — PATCH an account outside the union → 403.
  case_chatter_still_blocked      — the rest of /admin/accounts stays shut to
                                     chatters: GET list, POST active, DELETE.
  case_owner_keeps_full_patch     — negative: an OWNER PATCH still applies
                                     nickname (proves color-only is chatter-only).

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
# env can fall back to PROD — same incident guard as the other auth tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_rostercolor_{uuid.uuid4().hex}.db"
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
    ChatterUser,
    User,
    UserAccount,
)

asyncio.run(init_db())

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402

# ── In-process registry so the DB-seeded (non-numeric) test ids are
# recognised by get_account / list_accounts. upsert_account is replaced by a
# capture so we can assert exactly which fields the handler forwarded.
_TEST_ACCOUNTS = {"accAva", "accCelest", "accForeign"}
_orig_get_account = account_registry.get_account


def _patched_get_account(account_id: str):
    if account_id in _TEST_ACCOUNTS:
        return {"id": account_id, "nickname": account_id, "color": "#aaaaaa"}
    return _orig_get_account(account_id)


def _patched_list_accounts():
    return [{"id": aid, "nickname": aid, "color": "#aaaaaa"} for aid in sorted(_TEST_ACCOUNTS)]


_UPSERT_CALLS: list[dict] = []


def _patched_upsert(account_id, *, nickname=None, color=None):
    call = {
        "account_id": account_id,
        "nickname": nickname,
        "color": color,
    }
    _UPSERT_CALLS.append(call)
    return {"id": account_id, "nickname": nickname, "color": color}


account_registry.get_account = _patched_get_account
account_registry.list_accounts = _patched_list_accounts
# The isolation middleware asks per-candidate (one stat, no descriptor).
account_registry.is_account = lambda aid: aid in _TEST_ACCOUNTS
account_registry.upsert_account = _patched_upsert

# Don't touch OF — the badge fetcher returns a fixed count per account.
# Async, mirroring the real signature (it now derives from the shared
# "list_chats" window and takes the bust path's bypass flag).
async def _fixed_roster_count(aid, *, bypass=False):
    return {"unread": 1, "owe_reply": 2}
server._compute_roster_count_of = _fixed_roster_count
# Keep the post-write DB sync from doing real work in the test process.
server._kick_db_sync = lambda *_a, **_k: None


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


# ── 3. Harness ───────────────────────────────────────────────────────

FAILURES: list[str] = []


def _expect(case: str, condition: bool, detail: str = "") -> None:
    label = case if not detail else f"{case} — {detail}"
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILURES.append(label)


def _login_user(username: str, password: str = "secretpw") -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return c


def _login_chatter(username: str, password: str = "secretpw") -> TestClient:
    c = TestClient(server.app)
    r = c.post("/chatter/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"chatter login failed: {r.status_code} {r.text}"
    return c


# ── 4. Fixture ───────────────────────────────────────────────────────

async def _setup() -> None:
    owner_a = await _seed_user("velvetvoice")
    owner_c = await _seed_user("stranger")
    await _seed_account("accAva", owner_a, "Ava")
    await _seed_account("accCelest", owner_a, "Celest2")
    await _seed_account("accForeign", owner_c, "not yours")
    cid = await _seed_chatter("sensui")
    await _link_chatter(cid, owner_a)  # no ChatterAccountAccess rows ⇒ full union


# ── 5. Cases ─────────────────────────────────────────────────────────

def case_chatter_sees_badges() -> None:
    chatter = _login_chatter("sensui")
    r = chatter.get("/admin/accounts/roster-counts")
    _expect("chatter GET roster-counts → 200", r.status_code == 200,
            detail=f"got {r.status_code} {r.text[:120]}")
    counts = (r.json() or {}).get("counts", {}) if r.status_code == 200 else {}
    _expect("chatter badge set == its account union",
            set(counts.keys()) == {"accAva", "accCelest"},
            detail=f"got {sorted(counts.keys())!r}")
    _expect("chatter never sees a non-union account's badge",
            "accForeign" not in counts)


def case_chatter_recolor_color_only() -> None:
    _UPSERT_CALLS.clear()
    chatter = _login_chatter("sensui")
    r = chatter.patch("/admin/accounts/accAva", json={
        "color": "#ff0000",
        "nickname": "HACKED",                 # must be ignored for a chatter
    })
    _expect("chatter PATCH a union account → 200", r.status_code == 200,
            detail=f"got {r.status_code} {r.text[:120]}")
    call = _UPSERT_CALLS[-1] if _UPSERT_CALLS else {}
    _expect("recolor applied the color", call.get("color") == "#ff0000",
            detail=f"got {call.get('color')!r}")
    _expect("chatter recolor did NOT carry nickname", call.get("nickname") is None,
            detail=f"got {call.get('nickname')!r}")


def case_chatter_recolor_foreign_403() -> None:
    chatter = _login_chatter("sensui")
    r = chatter.patch("/admin/accounts/accForeign", json={"color": "#00ff00"})
    _expect("chatter PATCH outside its union → 403", r.status_code == 403,
            detail=f"got {r.status_code}")


def case_chatter_still_blocked() -> None:
    chatter = _login_chatter("sensui")
    rl = chatter.get("/admin/accounts")
    ra = chatter.post("/admin/accounts/active", json={"account_id": "accAva"})
    rd = chatter.delete("/admin/accounts/accAva")
    _expect("chatter GET /admin/accounts (raw list) still 403", rl.status_code == 403,
            detail=f"got {rl.status_code}")
    _expect("chatter POST /admin/accounts/active still 403", ra.status_code == 403,
            detail=f"got {ra.status_code}")
    _expect("chatter DELETE /admin/accounts/{id} still 403", rd.status_code == 403,
            detail=f"got {rd.status_code}")


def case_owner_keeps_full_patch() -> None:
    _UPSERT_CALLS.clear()
    owner = _login_user("velvetvoice")
    r = owner.patch("/admin/accounts/accAva", json={
        "color": "#123456", "nickname": "Ava (renamed)",
    })
    _expect("owner PATCH → 200", r.status_code == 200, detail=f"got {r.status_code}")
    call = _UPSERT_CALLS[-1] if _UPSERT_CALLS else {}
    _expect("owner PATCH still applies nickname (color-only is chatter-only)",
            call.get("nickname") == "Ava (renamed)",
            detail=f"got {call.get('nickname')!r}")


# ── 6. Runner ────────────────────────────────────────────────────────

def _main() -> int:
    asyncio.run(_setup())
    cases = [
        ("chatter sees the roster badges", case_chatter_sees_badges),
        ("chatter recolor is color-only", case_chatter_recolor_color_only),
        ("chatter recolor of a foreign account is 403", case_chatter_recolor_foreign_403),
        ("rest of /admin/accounts stays owner-only", case_chatter_still_blocked),
        ("owner keeps the full PATCH field set", case_owner_keeps_full_patch),
    ]
    for i, (title, fn) in enumerate(cases, 1):
        print(f"\n─── Case {i}: {title} " + "─" * max(2, 40 - len(title)))
        fn()

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
        rc = _main()
    finally:
        for ext in ("", "-wal", "-shm"):
            p = Path(str(_TMP_DB) + ext)
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    raise SystemExit(rc)
