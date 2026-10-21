"""service/tests/_agency_fixtures.py — the shared two-Agency bench.

Seeds Agency A and Agency B, each with an owner, a chatter linked only to its
own Agency, and a Creator (an `accounts` row, its `user_accounts` link and an
on-disk account directory in a temp sessions tree, so the account isolation
middleware's `is_account` check does a real stat). Plus `chatter_ab`, linked
to both Agencies, and a Master (`users.is_admin`).

Later Phases import this for their cross-agency 403/404 cases instead of
seeding their own two Agencies (docs/spec/phase-01, Testing Decisions).

Every name and id is neutral and obviously fake; the mapping key of each
principal IS its username, so `login_owner("agency_a_owner")` reads the way
the mapping does.

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap
`_harness` FIRST (the temp-DB footgun), then import this.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete

import _harness
import accounts as account_registry
from db.engine import get_session
from db.models import (
    SETTINGS_EPOCH, VERSIONED_SETTINGS_TABS, Account, Chatter, ChatterUser, SettingsVersion, User, UserAccount,
    UserSetting,
)

PASSWORD = "fixture-pw"

_OWNERS = ("agency_a_owner", "agency_b_owner")
_MASTER = "agency_master"
_CREATORS = {"creator_a": ("1000001", "agency_a_owner"),
             "creator_b": ("1000002", "agency_b_owner")}
_CHATTERS = {"chatter_a": ("agency_a_owner",),
             "chatter_b": ("agency_b_owner",),
             "chatter_ab": ("agency_a_owner", "agency_b_owner")}

_IDS: dict[str, str] | None = None


# ASSUMPTION: all four path settings in accounts.py (SESSIONS_DIR, ACCOUNTS_DIR,
# ACTIVE_FILE, MIGRATED_MARKER) are redirected, not just ACCOUNTS_DIR, so no
# code path can fall back to service/sessions. Overturned if accounts.py grows
# another module-level path, which must then be redirected here too.
def _sandbox_sessions_tree() -> Path:
    """Point the account registry at a throwaway sessions tree, so the seeded
    Creator directories are real and nothing touches service/sessions."""
    root = Path(tempfile.mkdtemp(prefix="agency_fixture_sessions_"))
    account_registry.SESSIONS_DIR = root
    account_registry.ACCOUNTS_DIR = root / "accounts"
    account_registry.ACTIVE_FILE = root / "active.json"
    account_registry.MIGRATED_MARKER = root / ".migrated"
    account_registry.ACCOUNTS_DIR.mkdir(parents=True)
    return root


async def _seed() -> dict[str, str]:
    ids: dict[str, str] = {}
    now = datetime.utcnow()
    async with get_session() as s:
        for name in (*_OWNERS, _MASTER):
            ids[name] = uuid.uuid4().hex
            s.add(User(id=ids[name], username=name, password=PASSWORD,
                       is_admin=(name == _MASTER)))
        for key, (aid, _owner) in _CREATORS.items():
            ids[key] = aid
            s.add(Account(id=aid, nickname=key, color="#aaaaaa"))
        for name in _CHATTERS:
            ids[name] = uuid.uuid4().hex
            s.add(Chatter(id=ids[name], username=name, password=PASSWORD,
                          display_name=name, color="#bbbbbb",
                          created_at=now, last_seen_at=now))
    async with get_session() as s:
        for key, (aid, owner) in _CREATORS.items():
            s.add(UserAccount(user_id=ids[owner], account_id=aid))
        for name, owners in _CHATTERS.items():
            for owner in owners:
                s.add(ChatterUser(chatter_id=ids[name], user_id=ids[owner],
                                  created_at=now))
    return ids


# ASSUMPTION: seed_two_agencies is sync and seeds once per process (asyncio.run
# inside), matching how _harness tests seed at module level. Overturned if a
# caller needs it from inside a running event loop or a fresh seed per case.
def seed_two_agencies() -> dict[str, str]:
    """Seed both Agencies once and return a plain mapping of ids.

    Keys: `agency_a_owner`, `agency_b_owner`, `agency_master` (users.id);
    `creator_a`, `creator_b` (digit-only account ids); `chatter_a`,
    `chatter_b`, `chatter_ab` (chatters.id). A second call returns the same
    mapping without seeding again. Call it outside a running event loop
    (module level or a sync case)."""
    global _IDS
    if _IDS is None:
        _sandbox_sessions_tree()
        for aid, _owner in _CREATORS.values():
            (account_registry.ACCOUNTS_DIR / aid).mkdir()
        _IDS = asyncio.run(_seed())
    return dict(_IDS)


def _login(path: str, name: str):
    client = _harness.make_client()
    r = client.post(path, json={"username": name, "password": PASSWORD})
    assert r.status_code == 200, f"{path} as {name}: {r.status_code} {r.text}"
    return client


def login_owner(name: str):
    """A test client carrying `name`'s real owner session cookie (the Master
    logs in here too)."""
    return _login("/auth/login", name)


def login_chatter(name: str):
    """A test client carrying `name`'s real chatter session cookie."""
    return _login("/chatter/login", name)


def store_blob(user_id: str, tab: str, blob: dict) -> None:
    """Write a Settings blob straight into `user_settings`, bypassing the PUT
    and its schema: a value stored before Phase 4's validation existed. A
    versioned tab's (`sales`, `time-tracking`) becomes its only version, in
    effect since before versioning (SETTINGS_EPOCH)."""
    async def _write():
        async with get_session() as s:
            if tab in VERSIONED_SETTINGS_TABS:
                await s.execute(delete(SettingsVersion).where(SettingsVersion.user_id == user_id,
                                                              SettingsVersion.tab == tab))
                s.add(SettingsVersion(user_id=user_id, tab=tab, effective_from=SETTINGS_EPOCH,
                                      config_json=json.dumps(blob)))
                return
            row = await s.get(UserSetting, (user_id, tab))
            if row is None:
                s.add(UserSetting(user_id=user_id, tab=tab, config_json=json.dumps(blob),
                                  updated_at=datetime.utcnow()))
            else:
                row.config_json = json.dumps(blob)
    asyncio.run(_write())
