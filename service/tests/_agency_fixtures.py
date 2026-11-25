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


# All four accounts.py path settings must be redirected so nothing falls back to service/sessions.
def _sandbox_sessions_tree() -> Path:
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


def seed_two_agencies() -> dict[str, str]:
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
    return _login("/auth/login", name)


def login_chatter(name: str):
    return _login("/chatter/login", name)


def mint_token(client) -> str:
    r = client.post("/admin/owner-tokens", json={"name": "mcp"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def store_blob(user_id: str, tab: str, blob: dict) -> None:
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
