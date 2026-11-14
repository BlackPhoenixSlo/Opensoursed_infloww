#!/usr/bin/env python3
"""Full AI Chat Writers (phase 03a, slice A): the two new hosts and the
one-shot Writer call.

  1. A Writer is tried ONCE with a short timeout (`timeout_s`, `max_attempts`)
     so a 429 or a stall reaches the next Writer fast, not after three 120 s
     retries. Proven at the HTTP seam: what the transport was built with and
     how many requests it saw.
  2. Every existing caller passes neither kwarg and must see today's request
     count and timeout (parity).
  3. Euryale v2.3 (NanoGPT) and Hermes 4 405B (OpenRouter) reach their hosts
     with the spec's wire ids and bill at the D54/D60 prices; neither takes
     the JSON lanes.
  4. `messages_for` per Route (ticket 34), pure: each old constant is its
     `docs/prompts/old` text, each new one its catalog entry; the sell-off
     line only on rows `sell_off` / `tease_off`; sext at Heat with her Model
     info; ai_dare two beats in order; make_right the apology frames, no free
     item; the cat-sticker block only with `gifs` on; no_send builds nothing.

Offline: the transport is stubbed, no provider is called.

Run: cd service && ../venv/bin/python tests/test_full_ai_writers.py
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import os  # noqa: E402

import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402
from llm_client import LLMConfigError, LLMHTTPError, chat  # noqa: E402

# House keys so an orphan account can resolve one (fake values, never real).
os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")


class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _TimeoutClient:
    """Every request times out. Records the timeout each client was built
    with and how many requests left the process."""

    timeouts: list = []
    calls: int = 0

    def __init__(self, *a, timeout=None, **k):
        type(self).timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls += 1
        raise llm_client.httpx.ReadTimeout("timed out")


class _OkClient(_TimeoutClient):
    last_url: str = ""
    last_body: dict = {}
    usage: dict = {"prompt_tokens": 10, "completion_tokens": 5}

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls += 1
        cls.last_url = str(url)
        cls.last_body = dict(json or {})
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": dict(cls.usage),
        })


async def _seed_account(account_id: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id,
                                  daily_cost_cap_cents=1_000_000))


async def _fire(model: str, account_id: str, client, **kw):
    client.calls = 0
    client.timeouts = []
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = client
    try:
        return await chat(model=model, messages=[{"role": "user", "content": "hi"}],
                          purpose="full_ai_writer", account_id=account_id, **kw)
    finally:
        llm_client.httpx.AsyncClient = orig


async def _expect_http_error(model, account_id, client, **kw):
    try:
        await _fire(model, account_id, client, **kw)
    except LLMHTTPError:
        return
    raise AssertionError("a timed-out call must raise LLMHTTPError")


# ── 1. One attempt at the given bound ─────────────────────────────────────

async def case_one_attempt_times_out_at_the_given_bound():
    await _seed_account("acct_writer_once")
    await _expect_http_error("deepseek-v4-flash", "acct_writer_once", _TimeoutClient,
                             timeout_s=7.5, max_attempts=1)
    assert _TimeoutClient.calls == 1, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [7.5], _TimeoutClient.timeouts


async def case_two_attempts_means_two_requests():
    await _seed_account("acct_writer_twice")
    orig = llm_client._LLM_RETRY_BACKOFF_S
    llm_client._LLM_RETRY_BACKOFF_S = 0.0
    try:
        await _expect_http_error("deepseek-v4-flash", "acct_writer_twice", _TimeoutClient,
                                 timeout_s=3.0, max_attempts=2)
    finally:
        llm_client._LLM_RETRY_BACKOFF_S = orig
    assert _TimeoutClient.calls == 2, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [3.0, 3.0], _TimeoutClient.timeouts


# ── 2. Parity: no kwargs = today's 3 attempts at 120 s ────────────────────

async def case_default_kwargs_keep_todays_count_and_timeout():
    await _seed_account("acct_writer_parity")
    orig = llm_client._LLM_RETRY_BACKOFF_S
    llm_client._LLM_RETRY_BACKOFF_S = 0.0
    try:
        await _expect_http_error("deepseek-v4-flash", "acct_writer_parity", _TimeoutClient)
    finally:
        llm_client._LLM_RETRY_BACKOFF_S = orig
    assert _TimeoutClient.calls == 3, _TimeoutClient.calls
    assert _TimeoutClient.timeouts == [120.0, 120.0, 120.0], _TimeoutClient.timeouts


async def case_default_kwargs_send_the_same_body():
    """The kwargs shape the transport, never the request body."""
    await _seed_account("acct_writer_body")
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient)
    plain = dict(_OkClient.last_body)
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient,
                timeout_s=5.0, max_attempts=1)
    assert _OkClient.last_body == plain, (_OkClient.last_body, plain)
    assert "timeout_s" not in plain and "max_attempts" not in plain, plain


# ── 3. The two new Writers: host, wire id, price ──────────────────────────
# Billed in the internal unit, cents x100. 1M tokens each way so the spec's
# per-1M dollar prices land exact (10 in / 5 out rounds Euryale to 0).
_MILLION = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}


async def _fire_million(model, account_id):
    await _seed_account(account_id)
    _OkClient.usage = _MILLION
    try:
        return await _fire(model, account_id, _OkClient)
    finally:
        _OkClient.usage = {"prompt_tokens": 10, "completion_tokens": 5}


async def case_euryale_goes_to_nanogpt_at_d54_price():
    res = await _fire_million("euryale-v2.3", "acct_euryale")
    assert _OkClient.last_url == "https://nano-gpt.com/api/v1/chat/completions", \
        _OkClient.last_url
    assert _OkClient.last_body.get("model") == "Sao10K/L3.3-70B-Euryale-v2.3", \
        _OkClient.last_body.get("model")
    # D54: $0.493/M in + $0.493/M out = 98.6 cents.
    assert res.cost_cents == 9860, res.cost_cents


async def case_hermes_goes_to_openrouter_at_d60_price():
    res = await _fire_million("hermes-4-405b", "acct_hermes")
    assert _OkClient.last_url == "https://openrouter.ai/api/v1/chat/completions", \
        _OkClient.last_url
    assert _OkClient.last_body.get("model") == "nousresearch/hermes-4-405b", \
        _OkClient.last_body.get("model")
    # D60: $1/M in + $3/M out = 400 cents.
    assert res.cost_cents == 40000, res.cost_cents


async def case_writers_refuse_json_object_before_firing():
    """Not offered on the JSON lanes (gen_info, copilot): refused, no request."""
    await _seed_account("acct_writer_json")
    for mid in ("euryale-v2.3", "hermes-4-405b"):
        try:
            await _fire(mid, "acct_writer_json", _OkClient,
                        response_format={"type": "json_object"})
            raise AssertionError(f"{mid} json_object call was not refused")
        except LLMConfigError:
            pass
        assert _OkClient.calls == 0, (mid, _OkClient.calls)


async def case_zero_attempts_is_refused_before_anything_fires():
    await _seed_account("acct_writer_zero")
    try:
        await _fire("deepseek-v4-flash", "acct_writer_zero", _OkClient, max_attempts=0)
        raise AssertionError("max_attempts=0 was not refused")
    except LLMConfigError:
        pass
    assert _OkClient.calls == 0, _OkClient.calls


# ── 4. The code floor (ticket 33): a reply the next Writer must replace ──

def case_floor_table():
    """`floor(text, lang)`: each reject reason; CJK only on an English account;
    normal text passes."""
    from automations.full_ai_writers import floor
    table = [
        ("haha ok i see u, what r u up to tonight", "en", None),
        ("hey <3 > that", "en", None),
        ("look [photo set description: black lace]", "en", "bracket"),
        ("so [id 101] is yours", "es", "bracket"),
        ("framework: 1) tease him", "en", "framework"),
        ("Framework: step one", "en", "framework"),
        ("ok >> no pitch <", "en", "chevron"),
        ("babe >>OFFER 105", "en", "chevron"),
        ("ok babe 结果 later", "en", "cjk"),
        ("かわいい", "en", "cjk"),
        ("안녕 babe", "en", "cjk"),
        ("hola guapo 结果", "es", None),
        ("123 !!", "en", "no_letters"),
        ("😘😘", "en", "no_letters"),
        ("", "en", "no_letters"),
    ]
    for text, lang, want in table:
        assert floor(text, lang) == want, (text, lang, floor(text, lang), want)


def case_floor_reads_the_reply_without_its_sticker_marker():
    """`reject`: a marker in any wrapper is not a `bracket` reject; a marker-only reply passes
    only with GIFs on and a known tag; the body under a marker is still floored."""
    from automations.full_ai_writers import reject
    table = [
        ("haha ok\n[STICKER: kiss]", True, None),
        ("haha ok\n[STICKER: kiss]", False, None),
        ("haha ok STICKER: [kiss]", True, None),
        ("STICKER: kiss", True, None),
        ("STICKER: kiss", False, "no_letters"),
        ("STICKER: nosuchtagatall", True, "no_letters"),
        ("look [photo set: black lace]\nSTICKER: kiss", True, "bracket"),
        ("babe >>OFFER 105 STICKER: kiss", True, "chevron"),
        ("haha ok i see u", False, None),
    ]
    for text, gifs, want in table:
        assert reject(text, "en", gifs) == want, (text, gifs, reject(text, "en", gifs), want)


# ── messages_for per Route (ticket 34), pure ──────────────────────────────
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations import cat_stickers  # noqa: E402
from automations import full_ai_writers as wr  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "prompts"
_ROUTES = ("chat", "sext", "ai_dare", "make_right")
_ROWS = ("otherwise", "stop", "jev_failed", "sext_off", "sell_off", "tease_off", "sexual_now",
         "asks_if_ai", "complains_now")


def _msg_row(direction, text, mid):
    return SimpleNamespace(direction=direction, body=text, created_at=None, message_id=mid,
                           automation_kind=None, media_count=0, raw_json=None,
                           price_cents=None, is_paid=False, purchased_at=None)


def _turn(text="hey you", *, fan_info=None, **cfg):
    return SimpleNamespace(
        account_id="acct_msgs", anchor_key="test:s:1", config={**DEFAULTS, **cfg},
        fan_info=dict(fan_info or {}), next_question=None, spent=[],
        cut_rows=[_msg_row("out", "hii", 1), _msg_row("in", text, 2)])


def _system(route, row="otherwise", heat=2, persona=wr.PERSONA_FALLBACK, **kw):
    return wr.messages_for(route, row, heat, _turn(**kw), None, persona=persona)[0]["content"]


def case_route_constants_are_their_catalog_text():
    """Old constants: substrings of their `docs/prompts/old` text. New glue: substrings of
    `docs/prompts/new/current-repo.md` (the apology frames ride in their NEW entry: the old
    catalog leaves `make_right._APOLOGY_FRAMES` out of scope)."""
    old = (_DOCS / "old" / "upseller-pipeline.md").read_text(encoding="utf-8")
    for c in (wr.BRUSH_OFF, wr.DARE, wr.SEXT_HOT, wr.NO_SELL_OFFERS, wr.STICKER_EXCEPTION.strip()):
        assert c in old, c
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    for c in (wr.SELL_OFF_LINE, wr.DARE_JOIN.strip(), wr.SEXT_HEAT, wr.MAKE_RIGHT_HEAD,
              wr.MAKE_RIGHT_TAIL, *wr.APOLOGY_FRAMES):
        assert c in new, c


def case_sell_off_line_only_on_sell_off_and_tease_off():
    for route in _ROUTES:
        for row in _ROWS:
            sys_ = _system(route, row)
            off = row in ("sell_off", "tease_off")
            assert (wr.SELL_OFF_LINE in sys_) is off, (route, row)
            assert (wr.NO_SELL_OFFERS in sys_) is (not off), (route, row)


def case_chat_keeps_the_chat_goal():
    sys_ = _system("chat", info_fields=[])
    assert wr.KNOW_ENOUGH in sys_
    for c in (wr.SEXT_HOT, wr.BRUSH_OFF, wr.DARE, wr.MAKE_RIGHT_HEAD):
        assert c not in sys_, c


def case_sext_is_old_aic_08_at_heat_with_her_model_info():
    model_info = "MODEL INFO (written by your team; it is true about you, never contradict it):"
    persona = f"You are Mia.\n\n{model_info}\n- Likes: telling him what she'd do to him"
    for heat in (1, 2, 3, 4):
        sys_ = _system("sext", "sexual_now", heat, persona, info_fields=[])
        assert wr.SEXT_HOT in sys_ and wr.SEXT_HEAT.format(heat=heat) in sys_, heat
        assert sys_.startswith(persona), heat              # her Model info leads the prompt
        assert wr.EXPLICIT_EARLY in sys_                    # verbatim until the owner's OK
        assert wr.KNOW_ENOUGH not in sys_ and wr.FAN_ASKED not in sys_


def case_ai_dare_is_one_reply_brush_off_then_dare():
    sys_ = _system("ai_dare", "asks_if_ai")
    i, j, k = sys_.index(wr.BRUSH_OFF), sys_.index(wr.DARE_JOIN), sys_.index(wr.DARE)
    assert i < j < k, (i, j, k)
    assert sys_.count(wr.DARE) == 1 and sys_.count(wr.BRUSH_OFF) == 1


def case_make_right_is_the_apology_with_no_free_item():
    sys_ = _system("make_right", "complains_now", fan_info={"real_name": "Tom"})
    assert wr.MAKE_RIGHT_HEAD in sys_ and wr.MAKE_RIGHT_TAIL in sys_
    for frame in wr.APOLOGY_FRAMES:
        assert frame.replace("{name}", "Tom") in sys_, frame
    assert "{name}" not in sys_
    # No name he gave: her lane's fan address, as the old `_fan_first_name` fell back.
    sys_ = _system("make_right", "complains_now")
    assert wr.APOLOGY_FRAMES[0].replace("{name}", "babe") in sys_


def case_sticker_block_only_with_gifs_on():
    block = cat_stickers.prompt_block("allow")
    for route in _ROUTES:
        on, off = _system(route, gifs=True), _system(route, gifs=False)
        assert block in on and on.endswith(wr.CONTRACT + wr.STICKER_EXCEPTION), route
        assert "STICKER" not in off, route


def case_no_send_builds_no_messages():
    assert wr.messages_for("no_send", "promo", 2, _turn(), None) == []
    assert wr.messages_for("no_send", "says_under_18", 2, _turn(), None) == []


def case_route_prompts_replay():
    for route in _ROUTES:
        assert _system(route) == _system(route), route

# ── sell_now (03b, ticket 42), pure ───────────────────────────────────────
import re  # noqa: E402

from automations.full_ai_sell import Pick, Refusal  # noqa: E402

_PICK = Pick(ref=4242, media=(4242,), previews=(), price_cents=5000, list_cents=5000,
             subject="anything", format="video", lane="$50",
             facts={"kinds": {"video": 1}, "items": [{"seconds": 95}],
                    "description": "her in a red bikini by the pool"})


def _fragments(c: str) -> list[str]:
    """A template's literal pieces between its `{slots}`."""
    return [x for x in re.split(r"\{[^}]*\}", c) if x.strip()]


def case_sell_now_constants_are_their_old_text():
    """Each sell_now constant (NEW-116's pieces) is its `docs/prompts/old` text: every literal
    piece between its slots is a substring (OLD-AIC-04/11/12/18, OLD-CORE-33)."""
    old = ((_DOCS / "old" / "upseller-pipeline.md").read_text(encoding="utf-8")
           + (_DOCS / "old" / "core-modules.md").read_text(encoding="utf-8"))
    # OLD-CORE-33 is quoted as source: join its implicit string concatenations.
    old = old.replace('"\n                         f"', "").replace('"\n                f"', "")
    for c in (wr.CONTENT_ASK, wr.CLOSE_BY_ID, wr.INTRO_BY_ID, wr.ITEM_LINE, wr.TERMS,
              wr.NO_CUSTOMS, wr.FILMING_MORE, wr.CONTRACT_OFFER):
        for frag in _fragments(c):
            assert frag in old, (c, frag)
    for c in (wr.MANIFEST, wr.PRICE_BLOCK):            # multi-line: line by line
        for line in c.split("\n"):
            for frag in _fragments(line):
                assert frag in old, (c, frag)


def _sell_system(pick, *, row="sell"):
    t = _turn("send me pics")
    return wr.messages_for("sell_now", row, 3, t, pick)[0]["content"]


def case_sell_now_with_a_pick_is_the_content_ask_sell_prompt():
    sys_ = _sell_system(_PICK)
    line = "- [id 4242] video 1:35 — untitled: her in a red bikini by the pool — $50 to unlock"
    beat = wr.CONTENT_ASK.format(close=wr.CLOSE_BY_ID)
    block = wr.MANIFEST.format(no_customs=wr.NO_CUSTOMS, items=line)
    price = wr.PRICE_BLOCK.format(px="$50")
    for piece in (wr.INTRO_BY_ID, beat, block, price):
        assert piece in sys_, piece
    assert sys_.index(wr.INTRO_BY_ID) < sys_.index(beat) < sys_.index(block) < sys_.index(price)
    assert sys_.endswith(f"{price}\n\n{wr.CONTRACT_OFFER}"), sys_[-400:]
    assert wr.NO_SELL_OFFERS not in sys_ and wr.SELL_OFF_LINE not in sys_
    assert wr.KNOW_ENOUGH not in sys_ and wr.ASK_HEAD not in sys_
    # A photo set: the count as its label, no length; no describe text leaves the slot empty.
    s3 = _sell_system(Pick(ref=7, media=(7, 8, 9), previews=(10,), price_cents=1000, list_cents=1000,
                           subject="anything", format="photo", lane="$10", facts={"items": [{}]}))
    assert "- [id 7] photo — 3 photos:  — $10 to unlock" in s3, s3
    assert wr.PRICE_BLOCK.format(px="$10") in s3


def case_sell_now_refusal_is_chat_with_its_need_line():
    for reason, line in (("no_match", wr.FILMING_MORE), ("all_owned", wr.FILMING_MORE),
                         ("no_priced_items", wr.FILMING_MORE), ("inventory_unknown", None)):
        sys_ = _sell_system(Refusal(reason))
        assert wr.NO_SELL_OFFERS in sys_ and wr.INTRO_BY_ID not in sys_, reason
        assert "CONTENT YOU CAN ACTUALLY SEND HIM" not in sys_ and ">>OFFER" not in sys_, reason
        if line:
            assert sys_.endswith(f"{line}\n\n{wr.CONTRACT}"), (reason, sys_[-300:])
        else:
            assert wr.FILMING_MORE not in sys_ and sys_.endswith(wr.CONTRACT), reason
    # A Pick handed to any other Route is ignored: the 03a prompt, byte for byte.
    for route, row in (("chat", "otherwise"), ("sext", "sexual_now"), ("make_right", "complains_now")):
        t = _turn()
        assert wr.messages_for(route, row, 2, t, _PICK) == wr.messages_for(route, row, 2, t, None)


def case_floor_offer_ref_table():
    """`floor(text, lang, offer_ref)`: the Pick's whole marker line is stripped first, another
    ref (or any, with no Pick) rejects, an inline `>>` stays a chevron, a missing marker is fine."""
    from automations.full_ai_writers import floor, strip_offer
    table = [
        ("its $50 to unlock babe 😏\n>>OFFER 4242", 4242, None),
        ("its $50 to unlock babe 😏\n>>OFFER 4242\nSTICKER: wink", 4242, None),
        ("its $50 to unlock babe 😏", 4242, None),                     # no marker: fine
        ("its $50 to unlock babe 😏\n>>OFFER 999", 4242, "offer_ref"),
        ("its $50 babe\n>>OFFER 4242\n>>OFFER 999", 4242, "offer_ref"),
        ("hey babe\n>>OFFER 105", None, "offer_ref"),                  # no Pick: any marker
        ("babe >>OFFER 4242", 4242, "chevron"),                        # not a line of its own
        ("ok >> no pitch\n>>OFFER 4242", 4242, "chevron"),
        (">>OFFER 4242", 4242, "no_letters"),                          # nothing but the marker
        ("so [id 4242] is yours\n>>OFFER 4242", 4242, "bracket"),
    ]
    for text, ref, want in table:
        assert floor(text, "en", ref) == want, (text, ref, floor(text, "en", ref), want)
    assert strip_offer("its yours babe\n>>OFFER 4242") == "its yours babe"
    assert strip_offer("its yours\n\n>>OFFER 4242\n\nSTICKER: wink") == "its yours\n\nSTICKER: wink"


_harness.run()
