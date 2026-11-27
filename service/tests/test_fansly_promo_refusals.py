#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import select  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_promo_refusals_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

import automation_executor as ax  # noqa: E402
import promo_create_guard  # noqa: E402
import promotions_api  # noqa: E402
import server  # noqa: E402
import side_effect_gate  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, PromoCreateReservation, User, UserAccount  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

http = _harness.make_client()

FANSLY_AID = "8803401"
OF_AID = "8803402"
REASON = "platform_lacks:promotion_type"
BODY = {"name": "Half off", "discount": 50, "subscribe_counts": 3, "subscribe_days": 7}
RAW = {"discount": 50, "subscribe_counts": 3, "subscribe_days": 7}
os.environ[promo_create_guard.HOST_ENV] = "test-box"


class _RecordingShim(FanslyShimClient):
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _request(self, method, path, *, params=None, json_body=None, **_kw):
        self.calls.append((method, path))
        if path == "/subscriptions/tiers":
            return [{"id": "t1", "plans": [{"id": "p1", "status": 1, "price": 5000}]}]
        return {"id": "g1", "status": 1, "maxUses": 3, "duration": 7}


class _FakeOF:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def promotions(self, *, offset=0, limit=100):
        return {"hasMore": False, "items": []}

    def create_promo(self, **kw):
        self.created.append(kw)
        return [{"id": 71_000_000 + len(self.created), "message": kw.get("message", ""), "price": 3,
                 "subscribeCounts": kw["subscribe_counts"], "subscribeDays": kw["subscribe_days"],
                 "claimsCount": 0, "isFinished": False}]


async def _seed() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="promo_boss", password="pw")
        s.add_all([boss, Account(id=FANSLY_AID, nickname=FANSLY_AID), Account(id=OF_AID, nickname=OF_AID)])
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=FANSLY_AID),
                   UserAccount(user_id=boss.id, account_id=OF_AID)])

asyncio.run(_seed())
account_registry.save_meta(FANSLY_AID, {"id": FANSLY_AID, "nickname": FANSLY_AID, "platform": "fansly"})
account_registry.save_meta(OF_AID, {"id": OF_AID, "nickname": OF_AID, "platform": "onlyfans"})
assert http.post("/auth/login", json={"username": "promo_boss", "password": "pw"}).status_code == 200


async def _reservations(aid: str) -> list[tuple[str, str]]:
    async with get_session() as s:
        R = PromoCreateReservation
        return [(r.source, r.state) for r in (await s.execute(
            select(R).where(R.account_id == aid).order_by(R.id))).scalars()]


@contextmanager
def _clients(client):
    with patch.object(ax, "_make_client", lambda _aid: client), \
            patch.object(server, "_get_client", lambda: client), \
            patch.object(server, "_load_client", lambda _aid: client):
        yield


@contextmanager
def _refusals():
    real = side_effect_gate.raise_if_refused
    seen: list[str] = []

    def spy(reason, what):
        if reason is not None:
            seen.append(reason)
        real(reason, what)

    with patch.object(side_effect_gate, "raise_if_refused", spy), \
            patch.object(promotions_api, "raise_if_refused", spy):
        yield seen


@contextmanager
def _nothing_before_refusal():
    boom = AssertionError("reached past the promotion_type refusal")
    with patch.object(promotions_api, "reserve_manual", side_effect=boom), \
            patch.object(server, "_promo_reserve_manual", side_effect=boom), \
            patch.object(promotions_api, "fetch_of_promos", side_effect=boom):
        yield


def _raw(aid: str, body: dict):
    return http.post("/api/of/v2/promotions", headers={"X-Account-Id": aid}, json=body)


def case_fansly_both_create_routes_answer_501_before_any_reservation_or_promo_request():
    shim = _RecordingShim()
    with _clients(shim), _refusals() as seen, _nothing_before_refusal():
        managed = http.post("/admin/promotions", json={"account_id": FANSLY_AID, **BODY})
        kept = http.post("/admin/promotions", json={"account_id": FANSLY_AID, **BODY, "auto_reactivate": True})
        raw = _raw(FANSLY_AID, RAW)
    for r in (managed, kept, raw):
        assert r.status_code == 501, (r.status_code, r.text)
    assert seen == [REASON] * 3, seen
    assert shim.calls == [], shim.calls
    assert asyncio.run(_reservations(FANSLY_AID)) == []


def case_fansly_reserve_backstop_refuses_and_maps_to_501():
    terms = {"discount": 50, "subscribe_counts": 3, "subscribe_days": 7, "message": "", "type": "all"}
    got = asyncio.run(promo_create_guard.reserve(FANSLY_AID, None, "manual", terms, {}, None, None))
    assert got == promo_create_guard.Refused(REASON), got
    with _refusals() as seen:
        for call in (lambda: promotions_api._refused(FANSLY_AID, got),
                     lambda: promotions_api.reserve_manual(FANSLY_AID, "manual", terms, None)):
            try:
                asyncio.run(call())
            except server.HTTPException as e:
                assert e.status_code == 501, (e.status_code, e.detail)
            else:
                raise AssertionError("a promotion_type refusal must raise 501")
    assert seen == [REASON] * 2, seen
    assert asyncio.run(_reservations(FANSLY_AID)) == []


def case_onlyfans_both_create_routes_still_reserve_and_create():
    fake = _FakeOF()
    with _clients(fake), _refusals() as seen:
        managed = http.post("/admin/promotions", json={"account_id": OF_AID, **BODY})
        raw = _raw(OF_AID, RAW)
    assert managed.status_code == 200 and raw.status_code == 200, (managed.text, raw.text)
    assert seen == [], seen
    assert [c["type"] for c in fake.created] == ["all", "all"], fake.created
    assert asyncio.run(_reservations(OF_AID)) == [("manual", "created"), ("manual_raw", "created")]
    assert promo_create_guard.promotion_type_refusal(OF_AID) is None


_harness.run()
