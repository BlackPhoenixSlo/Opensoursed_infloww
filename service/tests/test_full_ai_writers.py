#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import os  # noqa: E402

import llm_client  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402
from llm_client import LLMConfigError, LLMHTTPError, chat  # noqa: E402

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
    await _seed_account("acct_writer_body")
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient)
    plain = dict(_OkClient.last_body)
    await _fire("deepseek-v4-flash", "acct_writer_body", _OkClient,
                timeout_s=5.0, max_attempts=1)
    assert _OkClient.last_body == plain, (_OkClient.last_body, plain)
    assert "timeout_s" not in plain and "max_attempts" not in plain, plain


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
    assert res.cost_cents == 9860, res.cost_cents


async def case_hermes_goes_to_openrouter_at_d60_price():
    res = await _fire_million("hermes-4-405b", "acct_hermes")
    assert _OkClient.last_url == "https://openrouter.ai/api/v1/chat/completions", \
        _OkClient.last_url
    assert _OkClient.last_body.get("model") == "nousresearch/hermes-4-405b", \
        _OkClient.last_body.get("model")
    assert res.cost_cents == 40000, res.cost_cents


async def case_writers_refuse_json_object_before_firing():
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


async def case_walk_cuts_a_slow_drip_try_at_its_timeout():
    import asyncio
    import time
    calls = []

    async def try_once(writer, timeout):
        calls.append(writer)
        if writer == "slow":
            await asyncio.sleep(5)
        return "hey you", None

    cfg = {"writer_timeout_s": 0.2, "writer_retries": 0}
    t0 = time.monotonic()
    res = await wr.walk(cfg, ["slow", "fast"], time.monotonic() + 10, try_once)
    assert time.monotonic() - t0 < 2, time.monotonic() - t0
    assert [a["outcome"] for a in res.attempts] == ["timeout", "ok"], res.attempts
    assert res.writer == "fast" and calls == ["slow", "fast"], (res, calls)
    calls.clear()
    res = await wr.walk(cfg, ["fast"], time.monotonic() - 1, try_once)
    assert calls == [] and res.attempts == [{"writer": "fast", "outcome": "timeout", "ms": 0}], res.attempts



def case_floor_table():
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
    offer_table = [
        ("STICKER: kiss", True, 4242, "no_letters"),
        ("[STICKER: kiss]", True, 4242, "no_letters"),
        ("STICKER: kiss", True, None, None),
        ("its $50 babe\nSTICKER: kiss", True, 4242, None),
    ]
    for text, gifs, ref, want in offer_table:
        assert reject(text, "en", gifs, ref) == want, (text, ref, reject(text, "en", gifs, ref), want)


from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from automations import cat_stickers  # noqa: E402
from automations import _voice  # noqa: E402
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
        fan_info=dict(fan_info or {}), next_question=None, spent=[], offer_piece=None,
        cut_rows=[_msg_row("out", "hii", 1), _msg_row("in", text, 2)])


def _system(route, row="otherwise", heat=2, persona=wr.PERSONA_FALLBACK, **kw):
    return wr.messages_for(route, row, heat, _turn(**kw), None, persona=persona)[0]["content"]


def case_route_constants_are_their_catalog_text():
    old = (_DOCS / "old" / "upseller-pipeline.md").read_text(encoding="utf-8")
    for c in (wr.DARE, wr.SEXT_HOT, wr.NO_SELL_OFFERS, wr.STICKER_EXCEPTION.strip()):
        assert c in old, c
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    for c in (wr.BRUSH_OFF, wr.DARE_NEXT, wr.SELL_OFF_LINE, wr.DARE_JOIN.strip(), wr.SEXT_HEAT, wr.MAKE_RIGHT_HEAD,
              wr.MAKE_RIGHT_TAIL, *wr.APOLOGY_FRAMES, wr.NEAREST_NOTE, wr.OFFER_OPEN):
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
        assert sys_.startswith(persona), heat
        assert wr.EXPLICIT_EARLY in sys_
        assert wr.KNOW_ENOUGH not in sys_ and wr.FAN_ASKED not in sys_


def case_bot_check_is_two_steps():
    sys_ = _system("ai_dare", "asks_if_ai")
    assert sys_.count(wr.BRUSH_OFF) == 1 and wr.DARE not in sys_ and wr.DARE_NEXT not in sys_
    for route, row in (("chat", "otherwise"), ("sext", "sexual_now")):
        due = _photo_system(route, row, read=False, dared=False, photo=False, due=True)
        assert wr.DARE_NEXT in due and wr.BRUSH_OFF not in due and wr.DARE not in due, route
        assert wr.SEXT_HOT not in due, route
        for kw in ({"dared": False}, {"dared": True}):
            assert wr.DARE_NEXT not in _photo_system(route, row, read=False, photo=False, **kw), (route, kw)
    again = _photo_system("ai_dare", "asks_if_ai", read=False, dared=False, photo=False, due=True)
    i, j, k = again.index(wr.BRUSH_OFF), again.index(wr.DARE_JOIN), again.index(wr.DARE)
    assert i < j < k and again.count(wr.DARE) == 1, (i, j, k)
    for route, row in (("sell_now", "wants_content"), ("make_right", "complains_now")):
        assert wr.DARE_NEXT not in _photo_system(route, row, read=False, dared=False, photo=False, due=True), route


def _photo_system(route, row, *, read, dared, photo=True, due=False):
    f = _turn("i dont believe rate my face")
    f.dared, f.dare_due = dared, due
    if photo:
        f.cut_rows[-1].media_count = 1
        f.cut_rows[-1].photo_read = "a man in a black parka with a grey fur hood" if read else None
    return wr.messages_for(route, row, 2, f, None)[0]["content"]


def case_bot_check_photo_is_rated_and_never_dared_twice():
    for dared in (False, True):
        sys_ = _photo_system("ai_dare", "asks_if_ai", read=True, dared=dared)
        assert wr.DARE_RATE in sys_ and wr.DARE not in sys_ and wr.BRUSH_OFF not in sys_, dared
    sys_ = _photo_system("ai_dare", "asks_if_ai", read=False, dared=True)
    assert wr.BRUSH_OFF in sys_ and wr.DARE_BLIND in sys_ and wr.DARE not in sys_
    sys_ = _photo_system("ai_dare", "asks_if_ai", read=False, dared=True, photo=False)
    assert wr.BRUSH_OFF in sys_ and wr.DARE not in sys_ and wr.DARE_BLIND not in sys_
    for kw in ({"read": False, "dared": False}, {"read": False, "dared": False, "photo": False}):
        sys_ = _photo_system("ai_dare", "asks_if_ai", **kw)
        assert wr.BRUSH_OFF in sys_ and wr.DARE not in sys_, kw
    for route, row in (("chat", "otherwise"), ("sext", "sexual_now")):
        assert wr.DARE_RATE in _photo_system(route, row, read=True, dared=True), route
        due = _photo_system(route, row, read=True, dared=False, due=True)
        assert wr.DARE_RATE in due and wr.DARE_NEXT not in due, route
        assert wr.DARE_RATE not in _photo_system(route, row, read=True, dared=False), route
        assert wr.DARE_RATE not in _photo_system(route, row, read=False, dared=True), route
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    for c in (wr.DARE_RATE, wr.DARE_BLIND, wr.GIF_NOW.strip()):
        assert c in new, c


def case_gif_now_only_with_gif_pct():
    f = _turn(gifs=True, gif_pct=100)
    assert wr.GIF_NOW in wr.messages_for("chat", "otherwise", 2, f, None, gif_ok=True)[0]["content"]
    assert wr.GIF_NOW not in wr.messages_for("chat", "otherwise", 2, f, None, gif_ok=False)[0]["content"]
    f = _turn(gifs=True)
    assert wr.GIF_NOW not in wr.messages_for("chat", "otherwise", 2, f, None, gif_ok=True)[0]["content"]


def case_make_right_is_the_apology_with_no_free_item():
    sys_ = _system("make_right", "complains_now", fan_info={"real_name": "Tom"})
    assert wr.MAKE_RIGHT_HEAD in sys_ and wr.MAKE_RIGHT_TAIL in sys_
    for frame in wr.APOLOGY_FRAMES:
        assert frame.replace("{name}", "Tom") in sys_, frame
    assert "{name}" not in sys_
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

import re  # noqa: E402

from automations.full_ai_sell import Pick, Refusal, Teased  # noqa: E402

_PICK = Pick(ref=4242, media=(4242,), previews=(), price_cents=5000, list_cents=5000,
             subject="anything", format="video", lane="$50",
             facts={"kinds": {"video": 1}, "items": [{"seconds": 95}],
                    "description": "her in a red bikini by the pool"})


def _fragments(c: str) -> list[str]:
    return [x for x in re.split(r"\{[^}]*\}", c) if x.strip()]


def case_sell_now_constants_are_their_old_text():
    old = ((_DOCS / "old" / "upseller-pipeline.md").read_text(encoding="utf-8")
           + (_DOCS / "old" / "core-modules.md").read_text(encoding="utf-8"))
    old = (old.replace('"\n                         f"', "").replace('"\n                f"', "")
           .replace('"\n                "', ""))
    for c in (wr.CONTENT_ASK, wr.CLOSE_BY_ID, wr.INTRO_BY_ID, wr.ITEM_LINE, wr.TERMS,
              wr.NO_CUSTOMS, wr.FILMING_MORE, wr.CONTRACT_OFFER):
        for frag in _fragments(c):
            assert frag in old, (c, frag)
    for c in (wr.MANIFEST, wr.PRICE_BLOCK, wr.WAS_PRICE_BLOCK):
        for line in c.split("\n"):
            for frag in _fragments(line):
                assert frag in old, (c, frag)
    for c in (wr.ESCALATION, wr.SELL_STEP.removeprefix("\n")):
        for frag in _fragments(c):
            assert frag in old, (c, frag)
    assert wr.SELL_STEP.startswith("\n4. ") and "\\n4. THEN SELL HIM" in old


def _sell_system(pick, *, row="sell", offer_piece=None):
    t = _turn("send me pics")
    t.offer_piece = offer_piece
    return wr.messages_for("sell_now", row, 3, t, pick)[0]["content"]


def case_manifest_test_twin():
    assert "already filmed" in wr.MANIFEST and "already filmed" not in wr.MANIFEST_TEST
    assert wr.MANIFEST_TEST == wr.MANIFEST.replace("already filmed", "already made")
    for mode, want, other in (("test", wr.MANIFEST_TEST, wr.MANIFEST), ("live", wr.MANIFEST_TEST, wr.MANIFEST),
                              ("shadow", wr.MANIFEST, wr.MANIFEST_TEST)):
        t = _turn("send me pics")
        t.mode = mode
        sys_ = wr.messages_for("sell_now", "sell", 3, t, _PICK)[0]["content"]
        head = want.split("{", 1)[0]
        assert head in sys_ and other.split("{", 1)[0] not in sys_, mode


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
    s3 = _sell_system(Pick(ref=7, media=(7, 8, 9), previews=(10,), price_cents=1000, list_cents=1000,
                           subject="anything", format="photo", lane="$10", facts={"items": [{}]}))
    assert "- [id 7] photo — 3 photos:  — $10 to unlock" in s3, s3
    assert wr.PRICE_BLOCK.format(px="$10") in s3


def case_sell_section_terms_keep_a_folder_price_cents():
    """A folder price with cents: the item line's terms name the price the price block demands
    ($24.99, not $24); whole dollars stay `$24` (Shadow bytes unchanged)."""
    for cents, px in ((2499, "$24.99"), (2400, "$24"), (1050, "$10.50"), (20000, "$200")):
        p = Pick(**{**_PICK.__dict__, "price_cents": cents, "list_cents": cents})
        sec = wr.sell_section(p, None)
        assert f"— {px} to unlock" in sec and wr.PRICE_BLOCK.format(px=px) in sec, (cents, sec)


def case_haggle_offer_moment_and_hot_sell_prompts():
    quote = Pick(ref=4242, media=(4242,), previews=(), price_cents=3400, list_cents=5000,
                 subject="anything", format="photo", lane="$50", facts={"items": [{}]})
    offer = Teased("anything", "photo", (4242,), (), 5000)
    was = wr.WAS_PRICE_BLOCK.format(was="$50", px="$34")
    haggle = _sell_system(quote, row="haggle", offer_piece=offer)
    assert was in haggle and wr.PRICE_BLOCK.format(px="$34") not in haggle, haggle
    assert "— $34 to unlock" in haggle and wr.CONTENT_ASK.format(close=wr.CLOSE_BY_ID) in haggle
    at_list = _sell_system(_PICK, row="haggle", offer_piece=Teased("anything", "video", (4242,), (), 5000))
    assert wr.PRICE_BLOCK.format(px="$50") in at_list and "already saw" not in at_list
    other = Teased("anything", "photo", (7,), (), 5000)
    for kw in (dict(row="sell", offer_piece=offer), dict(row="haggle"), dict(row="haggle", offer_piece=other)):
        assert "already saw" not in _sell_system(quote, **kw), kw
    moment = _sell_system(_PICK, row="offer_moment")
    assert wr.ESCALATION.format(close=wr.CLOSE_BY_ID) in moment and wr.CONTENT_ASK[:20] not in moment
    step = wr.SEXT_HOT + wr.SELL_STEP.format(close=wr.CLOSE_BY_ID, example=_voice.HER.sell_caption_example)
    for row in ("sell", "haggle", "offer_moment"):
        hot = wr.messages_for("sell_now", row, 3, _turn("fuck me"), quote, hot=True)[0]["content"]
        assert step in hot and wr.SEXT_HEAT.format(heat=3) not in hot, row
        assert wr.ESCALATION[:20] not in hot and wr.CONTENT_ASK[:20] not in hot, row
    assert wr.sell_beat("sell", False) == wr.CONTENT_ASK.format(close=wr.CLOSE_BY_ID)


def case_broke_joke_rides_any_goal():
    assert "{" not in wr.BROKE_JOKE and not hasattr(wr, "BROKE_SELL")
    for route, row, pick in (("chat", "otherwise", None), ("sell_now", "sell", _PICK)):
        t = _turn("no im broke")
        off = wr.messages_for(route, row, 2, t, pick)[0]["content"]
        on = wr.messages_for(route, row, 2, t, pick, broke=True)[0]["content"]
        assert wr.BROKE_JOKE not in off and on.count(wr.BROKE_JOKE) == 1, route
        assert on.replace("\n" + wr.BROKE_JOKE, "", 1) == off, route
    for route, row in (("sext", "sexual_now"), ("tease", "tease_price")):
        t = _turn("no im broke")
        assert wr.messages_for(route, row, 2, t, None, broke=True)[0]["content"].count(wr.BROKE_JOKE) == 1, route
    for route, row in (("make_right", "complains_now"), ("ai_dare", "asks_if_ai")):
        t = _turn("no im broke")
        assert wr.messages_for(route, row, 2, t, None, broke=True) == wr.messages_for(route, row, 2, t, None), route
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    entry = new[new.index("### NEW-154"):]
    entry = entry[:entry.index("\n#", 1)]
    assert wr.BROKE_JOKE in entry and "2026-11-15" in entry


def case_sell_now_refusal_is_chat_with_its_need_line():
    for reason, line in (("no_match", wr.FILMING_MORE), ("all_owned", wr.FILMING_MORE),
                         ("no_priced_items", wr.FILMING_MORE), ("inventory_unknown", None),
                         ("offer_open", wr.offer_open_line(None))):
        sys_ = _sell_system(Refusal(reason))
        assert wr.NO_SELL_OFFERS in sys_ and wr.INTRO_BY_ID not in sys_, reason
        assert "CONTENT YOU CAN ACTUALLY SEND HIM" not in sys_ and ">>OFFER" not in sys_, reason
        if line:
            assert sys_.endswith(f"{line}\n\n{wr.CONTRACT}"), (reason, sys_[-300:])
        else:
            assert wr.FILMING_MORE not in sys_ and sys_.endswith(wr.CONTRACT), reason
    for piece, clause in ((Teased("feet", "photo", (4,), (), 5000, 1), " (a photo: call it nothing else)"),
                          (Teased("feet", "video", (4,), (), 5000, 1), " (a video: call it nothing else)"),
                          (Teased("feet", "gif", (4,), (), 5000, 1), " (a video: call it nothing else)"),
                          (Teased("feet", "audio", (4,), (), 5000, 1), " (a voice note: call it nothing else)"),
                          (Teased("feet", "photo", (4, 5, 6), (), 5000, 1), " (3 pieces: name no kind)")):
        line = wr.OFFER_OPEN.format(piece=clause)
        assert wr.offer_open_line(piece) == line, (piece, wr.offer_open_line(piece))
        sys_ = _sell_system(Refusal("offer_open"), offer_piece=piece)
        assert sys_.endswith(f"{line}\n\n{wr.CONTRACT}"), sys_[-300:]
        assert "already unlocked it, believe him" in line and "name no price" in line, line
    # A Pick handed to any other Route is ignored: the 03a prompt, byte for byte.
    for route, row in (("chat", "otherwise"), ("sext", "sexual_now"), ("make_right", "complains_now")):
        t = _turn()
        assert wr.messages_for(route, row, 2, t, _PICK) == wr.messages_for(route, row, 2, t, None)


def case_floor_offer_ref_table():
    from automations.full_ai_writers import floor, strip_offer
    table = [
        ("its $50 to unlock babe 😏\n>>OFFER 4242", 4242, None),
        ("its $50 to unlock babe 😏\n>>OFFER 4242\nSTICKER: wink", 4242, None),
        ("its $50 to unlock babe 😏", 4242, None),
        ("its $50 to unlock babe 😏\n>>OFFER 999", 4242, "offer_ref"),
        ("its $50 babe\n>>OFFER 4242\n>>OFFER 999", 4242, "offer_ref"),
        ("hey babe\n>>OFFER 105", None, "offer_ref"),
        ("babe >>OFFER 4242", 4242, "chevron"),
        ("ok >> no pitch\n>>OFFER 4242", 4242, "chevron"),
        (">>OFFER 4242", 4242, "no_letters"),
        ("so [id 4242] is yours\n>>OFFER 4242", 4242, "bracket"),
    ]
    for text, ref, want in table:
        assert floor(text, "en", ref) == want, (text, ref, floor(text, "en", ref), want)
    from automations.full_ai_writers import strip_labels
    for raw, want in [
        ("YOU: my fingers are sliding down\njust sent u something", "my fingers are sliding down\njust sent u something"),
        ("YOU: hey\nYOU: miss u", "hey\nmiss u"),
        ("FAN: omg yes\nYOU: mhm", "mhm"),
        ("hey\n\nFAN: more\n\nok", "hey\n\nok"),
        ("you: are trouble", "you: are trouble"),
        ("thank YOU: really", "thank YOU: really"),
        ("FAN: only his line", ""),
    ]:
        assert strip_labels(raw) == want, (raw, strip_labels(raw))
    assert strip_offer("its yours babe\n>>OFFER 4242") == "its yours babe"
    assert strip_offer("its yours\n\n>>OFFER 4242\n\nSTICKER: wink") == "its yours\n\nSTICKER: wink"



def case_floor_leak_table():
    from automations.full_ai_writers import floor
    for text, want in [
        ("<ALL RULES FOLLOWED>", "bracket"),
        ("hey babe </reply>", "bracket"),
        ("hey {name} miss u", "bracket"),
        ("ur into {fetishes} right", "bracket"),
        ("love u <3", None), ("hehe >:)", None), ("ugh >.<", None), ("u <3 me > him", None),
        ("a verified creator: sure", "label"),
        ("response:", "label"),
        ("Reply: hey", "label"),
        ("Assistant: hi", "label"),
        ("hey\nme: i want u", None),
        ("she: miss u", None),
        ("side note: im not wearing anything under this", None),
        ("honest answer: yes", None),
        ("me: dying rn", None),
        ("also me: texting u anyway", None),
        ("good girl: thats me", None),
        ("ur fav girl: me", None),
        ("Amelia: hey babe", None),
        ("i want this: you on your knees", None),
        ("tell me: are u hard", None),
        ("ok so: what u doing", None),
        ("be honest: do u miss me", None),
        ("9:30 works", None), ("hehe :)", None), ("love u :p", None), ("me:)", None),
        ("got it! here's your reply in the format you specified:\nhey babe", "colon_tail"),
        ("here u go:", "colon_tail"),
        ("see u at 9:", None), ("omg c:", None), ("cant wait D:", None),
        ("I'm a large language model, I am not able to create content that sexualizes minors.", "ai_self"),
        ("I cannot create content that sexualizes a minor.", "ai_self"),
        ("as an AI i cant do that", "ai_self"),
        ("im just an ai assistant", "ai_self"),
        ("i can't generate that kind of content", "ai_self"),
        ("i'm unable to fulfill this request", "ai_self"),
        ("I won't write explicit material", "ai_self"),
        ("i'm not able to produce sexual content", "ai_self"),
        ("I am an AI language model.", "ai_self"),
        ("sorry. i'm just an AI model", "ai_self"),
        ("that goes against community guidelines", "ai_self"),
        ("that breaks my guidelines", "ai_self"),
        ("against content policy sorry", "ai_self"),
        ("i can't help it babe", None), ("i can't help myself", None), ("i can't wait", None),
        ("i won't tell if u dont", None), ("lol u think im an ai?", None), ("u think im a bot", None),
        ("i cant create customs babe", None),
        ("lol im not some ai model", None),
        ("do i sound like a language model to u 😂", None),
        ("no guidelines here babe just fun", None),
        ("i can't produce that much cum lol", None),
        ("u think im an ai assistant or something", None),
        ("i can't generate that babe", None),
    ]:
        assert floor(text, "en") == want, (text, floor(text, "en"), want)


def case_strip_quotes_table():
    from automations.full_ai_writers import strip_quotes
    for raw, want in [
        ('"cumming in my pink dress rn, wish u could see "', "cumming in my pink dress rn, wish u could see"),
        ("“miss u already”", "miss u already"),
        ("'i'm so wet rn'", "i'm so wet rn"),
        ("‘come here’", "come here"),
        ('"he said "hi" lol"', 'he said "hi" lol'),
        ('"line one\nline two"', "line one\nline two"),
        ('"hi" and "bye"', '"hi" and "bye"'),
        ('i said "hi"', 'i said "hi"'),
        ("no quotes here", "no quotes here"),
        ('"', '"'),
    ]:
        assert strip_quotes(raw) == want, (raw, strip_quotes(raw), want)


def case_copied_table():
    from automations.full_ai_writers import copied, prompt_pieces
    tease = "tease this piece from its description only, make him want it, name no price and don't send it yet:"
    persona = "You are Mia, 22, a bubbly girl from Ohio who loves late night drives and pizza."
    system = (f"{persona}\n\nRULES\n{tease}\n- [id 1] photo — a girl holding an american flag fan\n"
              '- GOOD: "so what do u do for work?" / "where u textin me from"\nbe short.')
    prompt = prompt_pieces(system, persona)
    assert not any(persona in p or "GOOD" in p for p in prompt), prompt
    own = ["omg ur gonna love this clip of me in my red dress by the pool 😘", "hii"]
    for text, want in [
        ("tease this piece from its description only, make him want it", "echo"),
        ("coming ur way, a girl holding an american flag fan", "echo"),
        ("a girl holding an american flag", None),
        ("i'm a bubbly girl from ohio who loves late night drives", None),
        ("so what do u do for work?", None),
        ("ur gonna love this clip of me in my red dress, its yours", "repeat"),
        ("ur gonna love this clip of me", None),
        ("hey babe what u up to", None),
    ]:
        assert copied(text, prompt, own) == want, (text, copied(text, prompt, own), want)
    assert copied("bubbly girl from ohio who loves late night drives", [system], []) == "echo"
    assert copied("so what do u do for work?", [system], []) == "echo"
    assert copied("one two three four five six seven", ["one two three four", "five six seven"], []) is None


def case_nearest_note_honest_lines_pass_copied():
    """NEAREST_NOTE (item 1a, 2026-11-16): {asked} and {got} sit in different sentences, so the
    honest line the note asks for never echoes it."""
    from automations.full_ai_writers import copied, prompt_pieces
    for asked, got, line in [
        ("a feet video", "3 photos", "this one is 3 photos, not a feet video babe"),
        ("a feet video", "3 photos", "no feet video rn babe, its 3 photos instead"),
        ("a shower video", "a photo", "its a photo not a shower video, still hot tho"),
        ("a lingerie photo", "a video", "not a lingerie photo babe, this one is a video"),
        ("a boobs video", "2 photos and a video", "u asked for a boobs video but this is 2 photos and a video"),
        ("a feet photo", "a voice note", "he asked for a feet photo, this piece is a voice note"),
        ("a feet video", "3 photos", "u asked for a feet video, this piece is 3 photos instead babe"),
    ]:
        note = wr.NEAREST_NOTE.format(asked=asked, got=got)
        assert copied(line, prompt_pieces(note), []) is None, (line, note)


def case_reoffers_table():
    pick = Pick(ref=4, media=(4, 5), previews=(), price_cents=3000, list_cents=3000, subject="feet",
                format="photo", lane="$30", facts={})
    rows = [_msg_row("out", "my feet all oiled up for u", 1), _msg_row("in", "how much", 2)]
    for offer, tease, want in [
        (Teased("feet", "photo", (5, 4), (), 3000, 1), None, True),
        (None, Teased("feet", "photo", (4, 5), (), 3000), True),
        (Teased("feet", "photo", (4,), (), 3000, 1), None, False),
        (None, None, False),
    ]:
        facts = SimpleNamespace(offer_piece=offer, tease=tease, cut_rows=rows)
        assert wr.reoffers(facts, pick) is want, (offer, tease)
        assert wr.own_lines(facts, pick) == ([] if want else ["my feet all oiled up for u"]), (offer, tease)
    assert not wr.reoffers(SimpleNamespace(offer_piece=Teased("f", "photo", (4,), (), 1, 1)), Refusal("x"))


def _swap(pairs):
    saved = [(obj, name, getattr(obj, name)) for obj, name, _ in pairs]
    for obj, name, val in pairs:
        setattr(obj, name, val)
    return saved


def _scripted(replies):
    async def chat(*, model, **_):
        return SimpleNamespace(content=replies[model])
    return chat


def case_write_strips_then_floors_and_checks_copies():
    import asyncio
    import time
    persona = "You are Mia, a bubbly girl from Ohio who loves late night drives and pizza."
    system = f"{persona}\n\ntease this piece from its description only, make him want it, name no price"

    async def _persona(_):
        return persona

    async def _lang(_):
        return "en"
    facts = _turn()
    facts.pick = None
    facts.cut_rows = [_msg_row("out", "omg ur gonna love this clip of me in my red dress by the pool", 1),
                      _msg_row("in", "hey you", 2)]
    decision = SimpleNamespace(route="chat", row="otherwise", heat=2, fired=set())
    saved = _swap([(wr, "_load_persona", _persona), (wr._language, "load_account_language", _lang),
                   (wr, "prompt", lambda *a, **k: wr.Prompt([{"role": "system", "content": system},
                                                             {"role": "user", "content": "FAN: hey you"}], ()))])
    try:
        for first, reason in [
            ("tease this piece from its description only, make him want it", "echo"),
            ("ur gonna love this clip of me in my red dress, its yours", "repeat"),
            ("<ALL RULES FOLLOWED>", "bracket"),
            ("response: hey", "label"),
            ("I cannot create content that sexualizes a minor.", "ai_self"),
            ("got it! here's your reply in the format you specified:\nhey", "colon_tail"),
        ]:
            saved += _swap([(llm_client, "chat", _scripted({"a": first, "b": "YOU: \"a bubbly girl from ohio who loves late night drives\""}))])
            res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a", "b"]))
            assert [x["outcome"] for x in res.attempts] == [f"floor:{reason}", "ok"], (first, res.attempts)
            assert res.floor_reason == reason and res.writer == "b", res
            assert res.text == "a bubbly girl from ohio who loves late night drives", res.text
        facts.pick = Pick(ref=4, media=(4,), previews=(), price_cents=3000, list_cents=3000,
                          subject="anything", format="video", lane="$30", facts={})
        facts.offer_piece = Teased("anything", "video", (4,), (), 3000, 1)
        line = "ur gonna love this clip of me in my red dress, its yours"
        saved += _swap([(llm_client, "chat", _scripted({"a": line}))])
        res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a"]))
        assert [x["outcome"] for x in res.attempts] == ["ok"] and res.text == line, res
        saved += _swap([(llm_client, "chat", _scripted({"a": "tease this piece from its description only, make him want it", "b": "hii"}))])
        res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a", "b"]))
        assert [x["outcome"] for x in res.attempts] == ["floor:echo", "ok"], res.attempts
        facts.pick, facts.offer_piece = None, None
        facts.config = {**facts.config, "floor_on": False}
        saved += _swap([(llm_client, "chat", _scripted({"a": "“response: hey”"}))])
        res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a"]))
        assert [x["outcome"] for x in res.attempts] == ["ok"] and res.text == "response: hey", res
    finally:
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)


def case_offer_details_copied_floor():
    import asyncio
    import time
    from datetime import datetime
    from automations.full_ai_offer_details import OfferFacts
    persona = "You are Mia, a bubbly girl from Ohio who loves late night drives and pizza."
    of = OfferFacts(locked_kinds={"video": 1}, locked=1, preview_kinds={}, previews=0, seconds=(83,),
                    descriptions=("her in a red dress by the pool at sunset",), quoted_cents=3000,
                    sent_at=datetime(2026, 11, 16), bought=False, same_as_first=None, missing=frozenset(),
                    captions=("omg ur gonna love this clip of me in my red dress by the pool",))
    system = f"{persona}\n\n{wr.GOAL_HEAD}{wr.OFFER_GOAL}\n{wr.offer_facts_block(of)}\n\n{wr.CONTRACT}"

    async def _persona(_):
        return persona

    async def _lang(_):
        return "en"
    facts = _turn()
    facts.pick, facts.offer_facts = None, of
    facts.cut_rows = [_msg_row("out", "i was thinking about u all morning on my way to the gym", 1),
                      _msg_row("out", "omg ur gonna love this clip of me in my red dress by the pool", 2),
                      _msg_row("in", "whats in it", 3)]
    decision = SimpleNamespace(route="chat", row="offer_details", heat=2, fired=set())
    saved = _swap([(wr, "_load_persona", _persona), (wr._language, "load_account_language", _lang),
                   (wr, "prompt", lambda *a, **k: wr.Prompt([{"role": "system", "content": system},
                                                             {"role": "user", "content": "FAN: whats in it"}], ()))])
    try:
        for first, outcomes in [
            ("its 1 vid, me in a red dress by the pool at sunset babe", ["ok"]),
            ("ur gonna love this clip of me in my red dress, its 1 vid", ["ok"]),
            ("the offer he means the only facts you may state", ["floor:echo", "ok"]),
            ("i was thinking about u all morning on my way, its 1 vid", ["floor:repeat", "ok"]),
        ]:
            saved += _swap([(llm_client, "chat", _scripted({"a": first, "b": "hii"}))])
            res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a", "b"]))
            assert [x["outcome"] for x in res.attempts] == outcomes, (first, res.attempts)
        facts.offer_facts = None
        decision.row = "otherwise"
        for first, reason in [("its 1 vid, me in a red dress by the pool at sunset babe", "echo"),
                              ("ur gonna love this clip of me in my red dress, its 1 vid", "repeat")]:
            saved += _swap([(llm_client, "chat", _scripted({"a": first, "b": "hii"}))])
            res = asyncio.run(wr.write(decision, facts, deadline=time.monotonic() + 30, writers=["a", "b"]))
            assert [x["outcome"] for x in res.attempts] == [f"floor:{reason}", "ok"], (first, res.attempts)
    finally:
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)


def case_caption_write_runs_the_chat_floor():
    """`full_ai_caption.write`: the chat Writer's strips + `reject`, then `echo` against its own
    messages and `repeat` against her last lines."""
    import asyncio
    import json
    import time
    from automations import full_ai_caption as fc

    async def _lang(_):
        return "en"
    msgs = [{"role": "system", "content": "Match the register of these (adapt to the facts, never copy them)"},
            {"role": "user", "content": "description: a girl holding an american flag fan on a porch"}]
    facts = _turn()
    facts.cut_rows = [_msg_row("out", "couldnt keep my red lace set on for long, come see babe", 1)]
    saved = _swap([(wr._language, "load_account_language", _lang)])
    try:
        for first, reason in [
            ("“a verified creator: sure”", "label"),
            ("{name} come see", "bracket"),
            ("a girl holding an american flag fan on a porch", "echo"),
            ("couldnt keep my red lace set on for long, its yours", "repeat"),
        ]:
            cap = lambda t: json.dumps({"caption": t})  # noqa: E731
            saved += _swap([(llm_client, "chat", _scripted({"a": cap(first), "b": cap('"waving my flag just for u"')}))])
            res = asyncio.run(fc.write(facts, msgs, deadline=time.monotonic() + 30, writers=["a", "b"]))
            assert [x["outcome"] for x in res.attempts] == [f"floor:{reason}", "ok"], (first, res.attempts)
            assert res.text == "waving my flag just for u", res.text
        # The Pick re-offers the Pending tease's piece: no repeat, echo kept.
        facts.pick = Pick(ref=9, media=(9,), previews=(), price_cents=3000, list_cents=3000,
                          subject="anything", format="photo", lane="$30", facts={})
        facts.tease = Teased("anything", "photo", (9,), (), 3000)
        for first, outcomes in [("couldnt keep my red lace set on for long, its yours", ["ok"]),
                                ("a girl holding an american flag fan on a porch", ["floor:echo", "ok"])]:
            saved += _swap([(llm_client, "chat", _scripted({"a": cap(first), "b": cap("waving my flag just for u")}))])
            res = asyncio.run(fc.write(facts, msgs, deadline=time.monotonic() + 30, writers=["a", "b"]))
            assert [x["outcome"] for x in res.attempts] == outcomes, (first, res.attempts)
    finally:
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)


def case_caption_write_reads_the_shown_thread():
    """Test / live: the chat lines `full_ai_caption.chat_block` puts in the caption prompt are out of
    the `echo` pieces (his quoted ask passes) and her lines in them are `repeat`, past OWN_LINES
    too; a re-offer may reuse them; CHAT_RULE itself still echoes."""
    import asyncio
    import json
    import time
    from automations import full_ai_caption as fc

    async def _lang(_):
        return "en"
    old = "couldnt keep my red lace set on for long, come see babe"
    ask = "can you send me something with the red lace on tonight please"
    rows = [_msg_row("out", old, 1)] + [_msg_row("out", f"line number {i} for you", i) for i in range(2, 13)]
    facts = _turn()
    facts.mode, facts.fan_id, facts.cut_rows = "test", 7, rows + [_msg_row("in", ask, 13)]
    hero = {"media_id": 9, "kind": "photo", "seconds": None, "fields": {"description": "red lace on the bed"}}
    facts.pick = Pick(ref=9, media=(9,), previews=(), price_cents=3000, list_cents=3000, subject="anything",
                      format="photo", lane="$30", facts={"kinds": {"photo": 1}, "hero": hero})
    msgs = fc.messages(facts, facts.pick, None)
    assert f"YOU: {old}" in msgs[1]["content"] and f"FAN: {ask}" in msgs[1]["content"], msgs[1]["content"]
    assert len(wr.own_lines(facts, facts.pick)) == wr.OWN_LINES       # her first line is past OWN_LINES
    cap = lambda t: json.dumps({"caption": t})  # noqa: E731
    saved = _swap([(wr._language, "load_account_language", _lang)])
    try:
        def run(first):
            saved.extend(_swap([(llm_client, "chat", _scripted({"a": cap(first), "b": cap("all yours babe")}))]))
            res = asyncio.run(fc.write(facts, msgs, deadline=time.monotonic() + 30, writers=["a", "b"]))
            return [x["outcome"] for x in res.attempts]
        quoted = f"u said {ask}, so here it is"
        rule = "it is not a list of things the media contains babe"
        assert run(quoted) == ["ok"]
        assert run(old.replace("come see babe", "its yours")) == ["floor:repeat", "ok"]
        assert run(rule) == ["floor:echo", "ok"]
        facts.tease = Teased("anything", "photo", (9,), (), 3000)          # a re-offer: her line is fair
        assert run(old.replace("come see babe", "its yours")) == ["ok"]
        assert run(rule) == ["floor:echo", "ok"]
        facts.tease, facts.mode = None, "shadow"                            # Shadow: no thread, as before
        msgs = fc.messages(facts, facts.pick, None)
        assert fc.CHAT_HEAD not in msgs[1]["content"]
        assert run(old.replace("come see babe", "its yours")) == ["ok"]   # past OWN_LINES, never shown
    finally:
        for obj, name, val in reversed(saved):
            setattr(obj, name, val)


# ── tease and make_right with a Free item (03b, ticket 46), pure ─────────────

_FREE = Pick(ref=77, media=(77, 78), previews=(), price_cents=0, list_cents=1000,
             subject="feet", format="photo", lane="$10", facts={"kinds": {"photo": 2}, "items": [{}],
                                                                 "description": "soles up on white sheets"})


def case_tease_and_free_constants_are_their_catalog_text():
    old = ((_DOCS / "old" / "upseller-pipeline.md").read_text(encoding="utf-8")
           + (_DOCS / "old" / "core-modules.md").read_text(encoding="utf-8"))
    assert wr.FREE_TERMS in old and wr.GOAL_HEAD.strip() in old
    new = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    entry = new[new.index("### NEW-123"):]
    entry = entry[:entry.index("\n#", 1)]
    assert wr.TEASE_GOAL.strip() in entry and "DRAFT" in entry


def case_tease_with_a_pick_describes_it_without_a_price():
    for row in ("tease_price",):
        sys_ = wr.messages_for("tease", row, 2, _turn("how much?"), _PICK)[0]["content"]
        goal = (wr.GOAL_HEAD + wr.TEASE_GOAL
                + "- [id 4242] video 1:35 — untitled: her in a red bikini by the pool")
        assert goal + "\n" in sys_, sys_
        assert wr.SELF_BAN + wr.READ_ALL in sys_ and sys_.endswith(wr.CONTRACT), row
        for absent in ("$", "to unlock", "THE PRICE", "SELLING RULES", ">>OFFER", "FREE",
                       wr.NO_SELL_OFFERS, wr.SELL_OFF_LINE, wr.INTRO_BY_ID, wr.KNOW_ENOUGH, wr.ASK_HEAD):
            assert absent not in sys_, (row, absent)
    for reason, line in (("no_match", wr.FILMING_MORE), ("inventory_unknown", None)):
        sys_ = wr.messages_for("tease", "tease_price", 2, _turn("how much?"), Refusal(reason))[0]["content"]
        assert wr.TEASE_GOAL not in sys_ and sys_.endswith(f"{line}\n\n{wr.CONTRACT}" if line else wr.CONTRACT)
    t = _turn("how much?")
    assert wr.TEASE_GOAL not in wr.messages_for("tease", "tease_price", 2, t, None)[0]["content"]


def case_make_right_with_a_free_item():
    sys_ = wr.messages_for("make_right", "complains_now", 2, _turn("this is a scam", fan_info={"real_name": "Tom"}),
                           _FREE)[0]["content"]
    item = "- [id 77] photo — 2 photos: soles up on white sheets — FREE — just send it when the moment fits"
    assert wr.MAKE_RIGHT_HEAD in sys_ and item in sys_, sys_
    for frame in wr.APOLOGY_FRAMES:
        assert frame.replace("{name}", "Tom") in sys_, frame
    assert sys_.index(wr.MAKE_RIGHT_HEAD) < sys_.index(item)
    for absent in (wr.MAKE_RIGHT_TAIL, "SELLING RULES", "THE PRICE", ">>OFFER", "to unlock", "$",
                   wr.NO_SELL_OFFERS, wr.INTRO_BY_ID):
        assert absent not in sys_, absent
    assert wr.SELF_BAN + wr.READ_ALL in sys_ and sys_.endswith(wr.CONTRACT)
    t = _turn("this is a scam")
    assert wr.messages_for("make_right", "complains_now", 2, t, _PICK) == wr.messages_for(
        "make_right", "complains_now", 2, t, None)


def case_spend_line_only_without_a_pick():
    spent = [SimpleNamespace(kind="ppv_message", amount_cents=1000, occurred_at=None)]
    line = wr.spend_line(spent)
    assert line and line.startswith("he's spent: unlocked 1 PPV ($10 total, biggest $10)"), line
    rows = [
        ("sell_now", _PICK, spent, False),
        ("sell_now", Refusal("all_owned"), spent, True),
        ("chat", None, spent, True),
        ("chat", _PICK, spent, True),
        ("sext", None, spent, True),
        ("tease", _PICK, spent, False),
        ("tease", None, spent, True),
        ("make_right", _FREE, spent, False),
        ("make_right", _PICK, spent, True),
        ("sell_now", _PICK, [], False),
        ("chat", None, [], False),
    ]
    for route, pick, sp, want in rows:
        t = _turn("send me pics")
        t.spent = sp
        row = {"sell_now": "sell", "tease": "tease_price", "make_right": "complains_now"}.get(route, "otherwise")
        user = wr.messages_for(route, row, 3, t, pick)[1]["content"]
        assert (f"- {line}" in user) is want, (route, pick, bool(sp), user)



def _ppv(*cents):
    return [SimpleNamespace(kind="ppv_message", amount_cents=c, occurred_at=None) for c in cents]


TAIL = " — talk like you remember it, never like he's never paid."


def _old_buyer_facts(ppv_n, ppv_total, ppv_max, tip_rows):
    tip_total = sum(int(x or 0) for x in tip_rows)
    tip_n = sum(1 for x in tip_rows if int(x or 0) > 0)
    if tip_total <= 0 and ppv_n <= 0:
        return []
    parts: list[str] = []
    if ppv_n > 0:
        parts.append(f"unlocked {ppv_n} PPV{'s' if ppv_n != 1 else ''} "
                     f"(${ppv_total // 100} total, biggest ${ppv_max // 100})")
    if tip_total > 0:
        parts.append(f"tipped ${tip_total // 100} across "
                     f"{tip_n} tip{'s' if tip_n != 1 else ''}")
    return [
        "he's spent: " + " and ".join(parts)
        + " — talk like you remember it, never like he's never paid."
    ]


def case_spend_line_tips_table():
    for spent, tips, want in [
        ([], (), None),
        ([], [0], None),
        (_ppv(1000), (), "he's spent: unlocked 1 PPV ($10 total, biggest $10)" + TAIL),
        (_ppv(1000, 2500), (), "he's spent: unlocked 2 PPVs ($35 total, biggest $25)" + TAIL),
        ([], [500], "he's spent: tipped $5 across 1 tip" + TAIL),
        ([], [500, 500, 1000], "he's spent: tipped $20 across 3 tips" + TAIL),
        (_ppv(1000), [500, 700], "he's spent: unlocked 1 PPV ($10 total, biggest $10) and tipped $12 across 2 tips" + TAIL),
        ([], [50], "he's spent: tipped $0 across 1 tip" + TAIL),          # a 50-cent tip counts in tip_n
        ([], [50, 300], "he's spent: tipped $3 across 2 tips" + TAIL),
    ]:
        assert wr.spend_line(spent, tips) == want, (spent, tips, wr.spend_line(spent, tips))
    # Equals the old bot for the same numbers.
    for cents, tips in [((1000, 2500), [500, 50]), ((), [700]), ((4000,), []), ((999, 1), [1, 1, 1])]:
        old = _old_buyer_facts(len(cents), sum(cents), max(cents, default=0), tips)
        assert [x for x in [wr.spend_line(_ppv(*cents), tips)] if x] == old, (cents, tips, old)


def case_tips_reach_the_prompt_not_the_selling():
    import asyncio
    from automations import full_ai_turn as ft
    facts = ft.TurnFacts(account_id="acct_msgs", fan_id=1, mode="live", anchor_key="42", state={},
                         cut_rows=[_msg_row("out", "hii", 1), _msg_row("in", "hey you", 2)], bought=None,
                         offer=None, fan_info={}, asked={}, config={**DEFAULTS, "sell_on": True},
                         side=None, tips=[500, 500])
    assert facts.spent == [] and facts.tips == [500, 500]
    user = wr.messages_for("chat", "otherwise", 2, facts, None)[1]["content"]
    assert "- he's spent: tipped $10 across 2 tips" + TAIL in user, user
    assert ft._sells("make_right", facts) is False
    seen = {}

    class _Stop(Exception):
        pass

    def _state(*a, **k):
        seen.update(k)
        raise _Stop
    saved, ft._price_jev.state = ft._price_jev.state, _state
    try:
        facts.pick = _PICK
        try:
            asyncio.run(ft._price(facts, {}, 0.0, 2, False))
        except _Stop:
            pass
    finally:
        ft._price_jev.state = saved
    assert seen.get("bought_before") is False, seen
    user = wr.messages_for("sell_now", "sell", 3, facts, _PICK)[1]["content"]
    assert "he's spent" not in user, user


_FLAG_OF = {"texting": "style_on", "nonnative": "nonnative_on", "spacing": "spacing_on", "typos": "typo_on",
            "painful": "painful_on"}


def case_style_flags_one_switch_per_layer():
    on = dict.fromkeys(_FLAG_OF.values(), True)
    assert wr.style_flags(DEFAULTS) == on and list(DEFAULTS["style"]) == list(_FLAG_OF)
    for layer, flag in _FLAG_OF.items():
        got = wr.style_flags({**DEFAULTS, "style": {**DEFAULTS["style"], layer: False}})
        assert got == {**on, flag: False}, (layer, got)
    assert wr.style_flags({"text_style": "girl"}) == on
    assert wr.style_flags({"text_style": "formal"}) == dict.fromkeys(_FLAG_OF.values(), False)
    typo_off = {**DEFAULTS["style"], "typos": False}
    for route in _ROUTES:
        assert _system(route, style=typo_off) == _system(route), route



def case_open_card_kind_one_word():
    from automations import full_ai_turn
    from automations.full_ai_decide import Decision
    d = Decision("sell_now", 2, "sell", frozenset({"says_yes_to_offer"}))
    for fmt, word, yes_photo, yes_video in (("photo", "a photo", True, False), ("video", "a video", False, True),
                                            ("gif", "a video", False, True), ("audio", "a voice note", False, False)):
        piece = Teased("anything", fmt, (4,), (), 5000, 1)
        assert f"({word}: call it nothing else)" in wr.offer_open_line(piece), (fmt, wr.offer_open_line(piece))
        facts = SimpleNamespace(mode="test", offer_piece=piece)
        for asked, want in (("photo", yes_photo), ("video", yes_video), ("any", True)):
            got = full_ai_turn._yes_to_open(d, facts, {"asks_format": {asked: 1.0}})
            assert got is want, (fmt, asked, got)


_harness.run()
