from __future__ import annotations

import asyncio
import os

from sqlalchemy import func, select

import _agency_fixtures as fx
import s4s_api
from db.engine import get_session
from db.models import Account, Action, User, UserAccount

IDS = fx.seed_two_agencies()

OF_ME: dict[str, dict] = {}


async def _fake_of_me(account_id: str) -> dict | None:
    return OF_ME.get(account_id)


s4s_api._of_me = _fake_of_me


def of_profile(account_id: str, name: str, username: str, avatar: str | None = None) -> None:
    OF_ME[account_id] = {"name": name, "username": username,
                         **({"avatarThumbs": {"c144": avatar}} if avatar else {})}


def with_env(name: str, value: str, fn):
    os.environ[name] = value
    try:
        return fn()
    finally:
        os.environ.pop(name, None)


async def _count(model, **where) -> int:
    async with get_session() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return (await s.execute(q)).scalar_one()


def count(model, **where) -> int:
    return asyncio.run(_count(model, **where))


async def _audit_rows(action: str) -> list[Action]:
    async with get_session() as s:
        return list((await s.execute(
            select(Action).where(Action.action == action).order_by(Action.id))).scalars().all())


def audit_rows(action: str) -> list[Action]:
    return asyncio.run(_audit_rows(action))


def profiles(client) -> dict:
    r = client.get("/admin/s4s/profiles")
    assert r.status_code == 200, f"GET profiles: {r.status_code} {r.text}"
    return r.json()


def profile(client, account_id: str) -> dict:
    (row,) = [p for p in profiles(client)["profiles"] if p["account_id"] == account_id]
    return row


def new_post(client, account_id: str, caption: str) -> dict:
    r = client.post(f"/admin/s4s/profiles/{account_id}/posts", json={"caption": caption})
    assert r.status_code == 200, f"create post: {r.status_code} {r.text}"
    return r.json()


def seed_creators(links: dict[str, str | None], users: tuple[str, ...] = ()) -> None:
    async def go():
        async with get_session() as s:
            for name in users:
                s.add(User(id=name, username=name, password=fx.PASSWORD))
            for aid in links:
                s.add(Account(id=aid, nickname=f"seed_{aid[-3:]}", color="#aaaaaa"))
        async with get_session() as s:
            owners = {u.username: u.id for u in (await s.execute(select(User))).scalars()}
            for aid, owner in links.items():
                if owner:
                    s.add(UserAccount(user_id=owners[owner], account_id=aid))
    asyncio.run(go())


def db(stmt) -> None:
    async def go():
        async with get_session() as s:
            await s.execute(stmt)
    asyncio.run(go())


def list_in_discovery(client, aid: str, name: str, username: str, avatar_url: str | None = None,
                      **extra) -> str:
    of_profile(aid, name, username, avatar_url)
    r = client.put(f"/admin/s4s/profiles/{aid}", json={"opted_in": True, "discovery_visible": True, **extra})
    assert r.status_code == 200, f"opt in {aid}: {r.status_code} {r.text}"
    posts = r.json()["posts"]
    post = posts[0] if len(posts) >= 20 else new_post(client, aid, f"Promo of {name}")
    r = client.post(f"/admin/s4s/profiles/{aid}/posts/{post['id']}/primary")
    assert r.status_code == 200, f"primary {aid}: {r.status_code} {r.text}"
    return post["caption"]
