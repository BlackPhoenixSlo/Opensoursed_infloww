#!/usr/bin/env python3
"""test_full_ai_spacing_chat — the Ask cut-off and Spacing through the Test chat API (phase 03d,
ticket 59).

`POST /admin/full-ai/test/turn` + `/settle` with the owner's cookies, a seeded vault, the Router
faked at `_router_jev._client` (`FakeJev`, its calls recorded), the price Jev at `_price_jev._client`
(fails: the list price stays), the Writers at their wire; every request inside
`_full_ai_sell_helpers._guarded`.

  case_spacing_on_state_and_wording  `sell_spacing` on: the Router's recorded state and the row's
                                     `jev_json.state` hold the three keys; the request carries the
                                     `TEST_SPACING` wording for `offer_moment` and `scene_offer`
  case_exact_counts                  a scripted session: "no piece yet" -> an `offer_moment` Offer
                                     (declined) -> 1, 2, 3 lines -> 3 Unasked Offers -> an ask with
                                     the counts full (fewest lines, 3 unasked) still sells -> the
                                     `sell` Offer resets the lines, adds a Piece, not an Unasked one
  case_ask_cut_off                   `wants_content` .67 -> a `sell` row with an Offer; .64 -> none
  case_switch_off                    `sell_spacing` off: no Spacing keys, today's wording, and the
                                     request (questions + state keys) is the pre-03d one
  case_shadow_request_golden         a Shadow Turn's request still equals the golden bytes

Run: ./venv/bin/python service/tests/test_full_ai_spacing_chat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from _full_ai_sell_helpers import (  # noqa: E402
    A, NANO, OWNER_A, TURN, _body, _guarded, _put_draft, _rows, _vault,
)
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from _full_ai_fixtures import (  # noqa: E402
    KIND, QUIET, T0, FakeJev, FakeWriterHTTP, _dm, _fake_jev, _msg, _seed,
)
from automation_executor import run_once  # noqa: E402
from automations import _price_jev  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Transaction  # noqa: E402

SETTLE = "/admin/full-ai/test/settle"
KEYS = rj.SPACING_STATE_KEYS
NO = "no piece yet"
VAULT = {101: "$10", 202: "$50", 303: "$100", 404: "$25", 505: "$50", 606: "$10"}
GOLDEN = Path(__file__).with_name("test_full_ai_router_test_mode.shadow_request.golden.json")
# test_full_ai_spacing.py's pin (9718d06e3), questions + state key list, by `sext_scene`.
FLAG_OFF_TEST_REQUEST_SHA = {
    False: "06b04a892422a5bffe10ed28274d9c90471c73f3f31e29f321dd8899303a0f71",
    True: "30a0de07d24d5090c981c579f9f5475c69a8bd5f5e7b54d58fdf2ed7047d7abc",
}


class FailedPriceJev:
    """`_price_jev._client`: every call fails, so the Pick keeps its list price (no network)."""

    async def system_one(self, state, questions, model=None):
        raise RuntimeError("no price Jev in this suite")


@contextlib.contextmanager
def _draft(**cfg):
    _put_draft({**DEFAULTS, "sell_on": True, **cfg})
    real = _price_jev._client
    _price_jev._client = lambda key: FailedPriceJev()
    try:
        yield
    finally:
        _price_jev._client = real
        _put_draft(dict(DEFAULTS))


def _turn(pair: str, n: int, text: str, answers: dict, intensity: float = 2.0):
    """One Turn under the invariants: (response json, the Router's one recorded call, the row)."""
    fj = FakeJev(({**QUIET, **answers}, intensity))
    fw = FakeWriterHTTP({NANO: "ok:mm babe"})
    with _guarded(), fw.on(), _fake_jev(fj):
        r = OWNER_A.post(TURN, json=_body(pair, text, n=n))
    assert r.status_code == 200, r.text
    (call,) = fj.calls
    return r.json(), call, _rows(pair)[n - 1]


def _settle(pair: str, row_id: int, outcome: str = "declined"):
    with _guarded():
        r = OWNER_A.post(SETTLE, json={"account_id": A, "pair": pair, "side": "draft",
                                       "row_id": row_id, "outcome": outcome})
    assert r.status_code == 200, r.text


def _counts(st: dict) -> tuple:
    return tuple(st.get(k) for k in KEYS)


def _saved(row) -> dict:
    return json.loads(row.jev_json)["state"]


def _wording(q) -> dict:
    return {"instructions": q.instructions, "criteria": dict(q.criteria)}


def case_spacing_on_state_and_wording():
    pair = "sp-on"
    with _draft(draft_questions=True, sext_scene=True), _vault(VAULT):
        g, call, row = _turn(pair, 1, "hey u", {})
    assert DEFAULTS["sell_spacing"] is True
    assert _counts(call["state"]) == (NO, 0, 0), call["state"]
    assert _counts(_saved(row)) == (NO, 0, 0), row.jev_json
    assert list(call["state"])[-3:] == list(KEYS), list(call["state"])   # after the scene keys
    for qid in ("offer_moment", "scene_offer"):
        assert _wording(call["questions"][qid]) == rj.TEST_SPACING[qid], qid
        assert _wording(call["questions"][qid]) != rj.TEST_NOULS[qid], qid


def case_exact_counts():
    pair = "sp-count"
    with _draft(draft_questions=True, sext_scene=False), _vault(VAULT):
        n = 0

        def step(text, answers, want, row_want=None):
            nonlocal n
            n += 1
            g, call, row = _turn(pair, n, text, answers)
            assert _counts(call["state"]) == want, (n, _counts(call["state"]), want)
            assert _counts(_saved(row)) == want, (n, row.jev_json)
            if row_want:
                assert (row.route, row.route_row) == ("sell_now", row_want), (n, row.route, row.route_row)
                assert row.offer_price_cents and row.offer_item_ref, (n, row.offer_price_cents)
            return row

        step("hey u", {}, (NO, 0, 0))
        r = step("u look so good", {"offer_moment": .9}, (NO, 0, 0), "offer_moment")
        _settle(pair, r.id)
        step("haha", {}, (1, 1, 1))
        step("what u up to", {}, (2, 1, 1))
        r = step("same lol", {"offer_moment": .9}, (3, 1, 1), "offer_moment")
        _settle(pair, r.id)
        r = step("mm", {"offer_moment": .9}, (1, 2, 2), "offer_moment")
        _settle(pair, r.id)
        # Counts full (the fewest lines a Turn can read, 3 Unasked): his ask still sells.
        r = step("send me pics", {"wants_content": .9}, (1, 3, 3), "sell")
        _settle(pair, r.id)
        step("ok", {}, (1, 4, 3))       # the sell reset the lines, added a Piece, not an Unasked one
        step("nice", {}, (2, 4, 3))


def case_ask_cut_off():
    with _draft(), _vault(VAULT):
        g, _, row = _turn("sp-cut-67", 1, "i said show?", {"wants_content": .67})
        assert (row.route, row.route_row) == ("sell_now", "sell"), (row.route, row.route_row)
        assert g["offer"] and row.offer_price_cents, g
        g, _, row = _turn("sp-cut-64", 1, "i said show?", {"wants_content": .64})
        assert row.route != "sell_now" and row.route_row != "sell", (row.route, row.route_row)
        assert g["offer"] is None and row.offer_item_ref is None, g


def _request_sha(call: dict, scene: bool) -> str:
    """test_full_ai_spacing.py's flag-off request: the questions as sent plus the state key list."""
    d = {"questions": {q: v.model_dump(mode="json") for q, v in call["questions"].items()},
         "state_keys": list(call["state"])}
    assert scene == ("scene_offer" in call["questions"])
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def case_switch_off():
    for scene in (False, True):
        pair = f"sp-off-{scene}"
        with _draft(draft_questions=True, sext_scene=scene, sell_spacing=False), _vault(VAULT):
            _, call, row = _turn(pair, 1, "hey u", {})
        assert not set(KEYS) & set(call["state"]), call["state"]
        assert not set(KEYS) & set(_saved(row)), row.jev_json
        assert _wording(call["questions"]["offer_moment"]) == rj.TEST_NOULS["offer_moment"]
        if scene:
            assert _wording(call["questions"]["scene_offer"]) == rj.TEST_NOULS["scene_offer"]
        assert _request_sha(call, scene) == FLAG_OFF_TEST_REQUEST_SHA[scene], scene


def _golden_bytes(call: dict) -> bytes:
    """test_full_ai_router_test_mode.py's `_request_bytes`."""
    return json.dumps(
        {"model": call["model"], "state": call["state"],
         "questions": {qid: q.model_dump(mode="json") for qid, q in call["questions"].items()}},
        ensure_ascii=False, indent=1).encode() + b"\n"


async def case_shadow_request_golden():
    """test_full_ai_router_test_mode.py's Shadow Turn, `sell_spacing` at its default (on)."""
    aid, fan = "fa_sp_golden", 91
    await _seed(aid, rule=True, gate=False)
    for i, (d, body) in enumerate((("in", "hey gorgeous"), ("out", "<p>hi babe &amp; welcome</p>"),
                                   ("in", "what are you up to"))):
        await _msg(aid, fan, 8000 + i, d, body, T0 - timedelta(minutes=90 - 10 * i))
    await _msg(aid, fan, 8010, "out", "<p>just for you 😈</p>", T0 - timedelta(minutes=30),
               price_cents=1500, is_paid=False, automation_kind="reply_mass_funnel")
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan, kind="tip", amount_cents=2500,
                          occurred_at=T0 - timedelta(hours=3)))
    await _msg(aid, fan, 8020, "in", "you there?", T0)
    await _dm(aid, fan, 8021, "send me something hot", T0 + timedelta(minutes=1))
    fake = FakeJev((QUIET, 1.0))
    with _fake_jev(fake):
        res = await run_once(aid, KIND)
    assert res["status"] == "ok", res
    (call,) = fake.calls
    assert _golden_bytes(call) == GOLDEN.read_bytes(), _golden_bytes(call).decode()


_harness.run()
