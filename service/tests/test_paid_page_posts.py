#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from sqlalchemy import select  # noqa: E402

import account_page  # noqa: E402 — module under test
import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.auto_posts as ap  # noqa: E402,F401 — registers "auto_posts"
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Post  # noqa: E402

KIND = "auto_posts"


class FakeClient:

    def __init__(self, subscribe_price: float | None = 0.0, start_id: int = 90000):
        self.user_id = "999"
        self.subscribe_price = subscribe_price
        self.create_calls: list[dict] = []
        self.me_calls = 0
        self._next = start_id

    def me(self) -> dict:
        self.me_calls += 1
        if self.subscribe_price is None:
            raise RuntimeError("Wrong user.")
        return {"id": 999, "username": "fake", "subscribePrice": self.subscribe_price}

    def create_post(self, text, media_files=None, price=0, previews=None):
        self._next += 1
        self.create_calls.append(
            {"text": text, "media_files": list(media_files or []), "price": price,
             "previews": list(previews or [])}
        )
        return {"id": self._next, "text": text}


def _use_fake(**kw) -> FakeClient:
    fake = FakeClient(**kw)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    account_page.invalidate(aid)
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _posts(aid: str) -> list[Post]:
    async with get_session() as s:
        return (await s.execute(select(Post).where(Post.account_id == aid))).scalars().all()



async def case_page_tier_from_of():
    _use_fake(subscribe_price=5)
    assert await account_page.is_paid_page("acc_pp_paid") is True
    assert await account_page.subscribe_price_cents("acc_pp_paid") == 500

    _use_fake(subscribe_price=0)
    assert await account_page.is_paid_page("acc_pp_free") is False
    assert await account_page.subscribe_price_cents("acc_pp_free") == 0

    _use_fake(subscribe_price=None)
    assert await account_page.subscribe_price_cents("acc_pp_dead") is None
    assert await account_page.is_paid_page("acc_pp_dead") is False

    fake = _use_fake(subscribe_price=19.99)
    await account_page.is_paid_page("acc_pp_cache")
    await account_page.is_paid_page("acc_pp_cache")
    assert fake.me_calls == 1, fake.me_calls

    account_page.prime("acc_pp_primed", {"subscribePrice": 9.99})
    fake2 = _use_fake(subscribe_price=0)
    assert await account_page.is_paid_page("acc_pp_primed") is True
    assert fake2.me_calls == 0, "primed answer must not re-probe OF"



# Never re-priced to 0: that would hand the locked set to every subscriber.
async def case_auto_posts_drops_priced_item_on_paid_page():
    aid = "acc_pp_ap_paid"
    await _seed_account(aid)
    fake = _use_fake(subscribe_price=5)

    res = await run_once(aid, KIND, payload={"posts": [
        {"text": "locked drop", "media_files": [11, 12], "price": 19.99},
        {"text": "free tease", "media_files": [13]},
    ]})

    assert res["status"] == "skipped", res
    assert res["reason"] == account_page.PAID_PAGE_SKIP, res
    assert res["remaining"] == 1, "the queue must still drain past the dropped item"
    assert fake.create_calls == [], "a paid post must not reach OF on a paid page"

    res2 = await run_once(aid, KIND)
    assert res2["status"] == "ok" and res2["posted"] == 1, res2
    assert len(fake.create_calls) == 1 and fake.create_calls[0]["price"] in (0, None), \
        fake.create_calls
    rows = await _posts(aid)
    assert len(rows) == 1 and rows[0].price_cents == 0, rows


async def case_auto_posts_priced_still_posts_on_free_page():
    aid = "acc_pp_ap_free"
    await _seed_account(aid)
    fake = _use_fake(subscribe_price=0)

    res = await run_once(aid, KIND, payload={"posts": [
        {"text": "locked drop", "media_files": [21, 22], "price": 19.99},
    ]})

    assert res["status"] == "ok" and res["posted"] == 1, res
    assert len(fake.create_calls) == 1 and fake.create_calls[0]["price"] == 19.99, \
        fake.create_calls
    rows = await _posts(aid)
    assert len(rows) == 1 and rows[0].price_cents == 1999, rows


async def case_auto_posts_dry_run_flags_paid_page():
    aid = "acc_pp_ap_dry"
    await _seed_account(aid)
    _use_fake(subscribe_price=5)

    res = await run_once(aid, KIND, payload={"dry_run": True, "posts": [
        {"text": "locked drop", "media_files": [31], "price": 25},
        {"text": "free tease", "media_files": [32]},
    ]})

    assert res["dry_run"] is True and res["paid_page"] is True, res
    assert res["plan"][0]["skipped_reason"] == account_page.PAID_PAGE_SKIP, res["plan"][0]
    assert res["plan"][1]["skipped_reason"] is None, res["plan"][1]


_harness.run(
    case_page_tier_from_of,
    case_auto_posts_drops_priced_item_on_paid_page,
    case_auto_posts_priced_still_posts_on_free_page,
    case_auto_posts_dry_run_flags_paid_page,
)
