#!/usr/bin/env python3
from __future__ import annotations

import _harness
from _jev_fixtures import mapped  # noqa: E402

import contextlib  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from _full_ai_chat_helpers import (  # noqa: E402
    A, NANO, OWNER_A, TURN, _body, _Clock, _db, _guarded, _reply, _rows, _SlowJev,
)
from _full_ai_fixtures import QUIET, FakeJev, FakeWriterHTTP, _fake_jev  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import ownership  # noqa: E402
import vault_jev_rules  # noqa: E402
from automations import full_ai_turn, full_ai_writers  # noqa: E402
from automations.full_ai_config import DEFAULTS, turn_bound_s  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import CatalogItem, ContentOffer, VaultItem  # noqa: E402

CONFIG = "/admin/full-ai/config"
PICS = "send me pics"
CLIP = 301
FALLBACK = "1 vid, $10 to unlock"


async def _seed_offer_row() -> None:
    async with get_session() as s:
        item = CatalogItem(account_id=A)
        s.add(item)
        await s.flush()
        s.add(ContentOffer(account_id=A, fan_id=5, item_id=item.id, price_cents=1000))


_db(_seed_offer_row)


async def _offers() -> list[tuple]:
    async with get_session() as s:
        return [tuple(r) for r in (await s.execute(select(
            ContentOffer.id, ContentOffer.fan_id, ContentOffer.item_id, ContentOffer.price_cents))).all()]


class StampReached(Exception):
    pass


@contextlib.contextmanager
def _sell_guarded():
    real, hits = ownership.stamp_media_owned, []

    async def trap(*_a, **_k):
        hits.append("ownership.stamp_media_owned")
        raise StampReached()
    before = _db(_offers)
    ownership.stamp_media_owned = trap
    try:
        with _guarded():
            yield
    finally:
        ownership.stamp_media_owned = real
    assert hits == [] and before and _db(_offers) == before, (hits, before)


def _post(script: list[str], pair: str, *, fake_w=None, fake_j=None):
    fake_w = fake_w or FakeWriterHTTP({})
    fake_w.script = {NANO: list(script)}
    with _sell_guarded(), fake_w.on(), _fake_jev(fake_j or FakeJev(({**QUIET, "wants_content": 0.9}, 1.0))):
        r = OWNER_A.post(TURN, json=_body(pair, text=PICS, side="draft"))
    assert r.status_code == 200, r.text
    return r, fake_w



def _put_draft(draft: dict) -> None:
    rev = OWNER_A.get(CONFIG, params={"account_id": A}).json()["rev"]
    r = OWNER_A.put(f"{CONFIG}/draft", json={"account_id": A, "draft": draft, "rev": rev})
    assert r.status_code == 200, r.text


DRESSED = {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
           "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
           "anus_vis": "not_in_frame", "over_vulva": "jeans", "over_breasts": "t-shirt",
           "people_count": 1, "partner_visible": False, "description": "a mirror selfie in jeans"}
JEV = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": "$10", "state": {}, "kind": "video",
       "vv": vault_jev_rules.VIDEO_VERSION, "frames": [], "breasts_bare": "n", "crotch_bare": "n",
       "penetration": "n", "tags": {}}


@contextlib.contextmanager
def _one_clip_sell():
    async def add():
        async with get_session() as s:
            s.add(VaultItem(account_id=A, media_id=CLIP, kind="video", duration_seconds=12,
                            created_at=datetime(2026, 7, 1) + timedelta(days=1), tags="[]",
                            describe_status="described", of_folder_ids="[]",
                            ai_fields_json=json.dumps(mapped({**DRESSED, vault_jev_rules.JEV_KEY: JEV}))))

    async def drop():
        async with get_session() as s:
            await s.execute(delete(VaultItem).where(VaultItem.account_id == A))
    _put_draft({**DEFAULTS, "sell_on": True})
    _db(add)
    try:
        yield
    finally:
        _db(drop)
        _put_draft(dict(DEFAULTS))


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if "text" in p]


def _ppv_on_last(parts: list[dict]) -> None:
    assert [i for i, p in enumerate(parts) if "ppv" in p] == [len(parts) - 1], parts
    assert parts[-1]["ppv"]["ref"] == CLIP and parts[-1]["ppv"]["price_cents"] == 1000, parts[-1]


def _outcomes(attempts: list[dict]) -> list[tuple]:
    return [(a["writer"], a["outcome"], a.get("rewrite", False)) for a in attempts]


EURYALE = DEFAULTS["writers"][0]



def case_good_caption_no_rewrite():
    pair = "p-claim-good"
    with _one_clip_sell():
        r, fw = _post(["ok:my new vid just for u, $10 to unlock"], pair)
    got = r.json()
    assert (got["status"], got["route"]) == ("sent", "sell_now"), got
    assert len(fw.requests) == 1 and _outcomes(got["attempts"]) == [(EURYALE, "ok", False)], got["attempts"]
    assert FALLBACK not in _texts(got["parts"]), got["parts"]
    _ppv_on_last(got["parts"])
    assert _reply(_rows(A, pair)[0])["caption_fallback"] is False
    assert _reply(_rows(A, pair)[0])["claim_fail"] == [], "a pass records no failure"


def case_claim_fail_then_fallback():
    pair = "p-claim-5vids"
    with _one_clip_sell():
        r, fw = _post(["ok:5 videos just for u babe", "ok:all my videos r waiting for u"], pair)
    got = r.json()
    assert got["status"] == "sent", got
    assert len(fw.requests) == 2 and fw.requests[1]["body"]["messages"] == fw.requests[0]["body"]["messages"]
    assert _outcomes(got["attempts"]) == [(EURYALE, "ok", False), (EURYALE, "ok", True)], got["attempts"]
    assert _texts(got["parts"]) == [FALLBACK], got["parts"]
    _ppv_on_last(got["parts"])
    (row,) = _rows(A, pair)
    reply = _reply(row)
    assert reply["caption_fallback"] is True and reply["attempts"] == got["attempts"], reply
    fails = reply["claim_fail"]
    assert [f["check"] for f in fails] == ["claim", "claim"], ("first write + rewrite recorded", fails)
    assert "5 videos" in fails[0]["text"] and "videos" in fails[1]["text"], fails
    assert reply["typo_state"] == {"at": None, "since": 1}, ("the chained fallback's typo state (rwl-a F2)", reply)
    assert row.offer_price_cents == 1000, row.offer_price_cents


def case_claim_fail_rewrite_ok():
    pair = "p-claim-rewrite-ok"
    with _one_clip_sell():
        r, fw = _post(["ok:5 videos just for u babe", "ok:made a lil vid just for u"], pair)
    got = r.json()
    assert len(fw.requests) == 2 and _outcomes(got["attempts"])[-1] == (EURYALE, "ok", True), got["attempts"]
    joined = " ".join(_texts(got["parts"]))
    assert "vid" in joined and "videos" not in joined and FALLBACK not in joined, got["parts"]
    _ppv_on_last(got["parts"])
    assert _reply(_rows(A, pair)[0])["caption_fallback"] is False


def case_wrong_price_then_fallback():
    pair = "p-claim-price"
    with _one_clip_sell():
        r, fw = _post(["ok:its $40 to unlock babe", "ok:only $40 for u"], pair)
    got = r.json()
    assert len(fw.requests) == 2, fw.requests
    assert _outcomes(got["attempts"]) == [(EURYALE, "ok", False), (EURYALE, "ok", True)], got["attempts"]
    assert _texts(got["parts"]) == [FALLBACK] and "$40" not in json.dumps(got["parts"]), got["parts"]
    _ppv_on_last(got["parts"])
    assert _reply(_rows(A, pair)[0])["caption_fallback"] is True
    fails = _reply(_rows(A, pair)[0])["claim_fail"]
    assert [f["check"] for f in fails] == ["price", "price"] and all("$40" in f["text"] for f in fails), fails


def _photo_ask():
    return FakeJev(({**QUIET, "wants_content": 0.9}, 1.0, {"asks_format": "photo"}))


def case_disclose_fail_then_fallback():
    pair = "p-claim-disclose"
    with _one_clip_sell():
        _put_draft({**DEFAULTS, "sell_on": True, "typo_pct": 100})
        r, _fw = _post(["ok:my new vid just for u, $10 to unlock", "ok:a hot vid for u, $10"], pair,
                       fake_j=_photo_ask())
    got = r.json()
    (text,) = _texts(got["parts"])
    assert text == "not what u asked for babe, this one's 1 vid, $10 to unlock", got["parts"]
    _ppv_on_last(got["parts"])
    reply = _reply(_rows(A, pair)[0])
    assert reply["nearest"]["asked_format"] == "photo" and reply["caption_fallback"] is True, reply
    assert [f["check"] for f in reply["claim_fail"]] == ["disclose", "disclose"], reply["claim_fail"]


def case_disclose_pass():
    pair = "p-claim-disclose-ok"
    with _one_clip_sell():
        r, fw = _post(["ok:no pics rn babe but this vid tho, $10 to unlock"], pair, fake_j=_photo_ask())
    got = r.json()
    assert len(fw.requests) == 1 and "no pics rn" in " ".join(_texts(got["parts"])), got["parts"]
    _ppv_on_last(got["parts"])
    assert _reply(_rows(A, pair)[0])["claim_fail"] == []


class _SlowWriter(FakeWriterHTTP):

    def __init__(self, clock: _Clock):
        super().__init__({})
        self.clock = clock

    def __call__(self, *a, timeout=None, **k):
        self.clock.t += timeout
        return super().__call__(*a, timeout=timeout, **k)


def case_deadline_no_rewrite():
    bound = turn_bound_s(DEFAULTS)
    assert bound == 245 and DEFAULTS["writer_timeout_s"] == 45, bound
    clock = _Clock()
    start = clock.t
    saved = (full_ai_turn.time, full_ai_writers.time)
    full_ai_turn.time = full_ai_writers.time = types.SimpleNamespace(monotonic=clock.now,
                                                                     perf_counter=time.perf_counter)
    fw = _SlowWriter(clock)
    try:
        t0 = time.perf_counter()
        with _one_clip_sell():
            r, _ = _post(["ok:5 videos just for u babe", "ok:my 1 vid for u"], "p-claim-deadline", fake_w=fw,
                         fake_j=_SlowJev(clock, 170.0, ({**QUIET, "wants_content": 0.9}, 1.0)))
        wall = time.perf_counter() - t0
    finally:
        full_ai_turn.time, full_ai_writers.time = saved
    got = r.json()
    assert [x["timeout"] for x in fw.requests] == [45.0], fw.requests
    assert _outcomes(got["attempts"]) == [(EURYALE, "ok", False)], got["attempts"]
    assert _texts(got["parts"]) == [FALLBACK], got["parts"]
    _ppv_on_last(got["parts"])
    assert _reply(_rows(A, "p-claim-deadline")[0])["caption_fallback"] is True
    assert clock.t - start <= bound, (clock.t - start, bound)
    assert wall < 5.0, wall


if __name__ == "__main__":
    _harness.run()
