#!/usr/bin/env python3
"""Sensitive words enforced server-side on every automation send (S12).

Growth > Sensitive words used to be a browser-only check: the mass-message
composer and Smart Message/template save refuse a listed word ("Please check
the contents of the messages"), the 1:1 composer only warns. Automations never
saw the list. Now:

  • `_wordfilter.load_banned_words(account)` returns the Agency list (every
    Agency holding the account in user_accounts), so each sender that already
    filters (autoreply, welcome chatter, mass message, reply funnel) honours
    it, in block mode.
  • `automation_executor.run_once` sets `of_client.OUTBOUND_TEXT_GUARD` for the
    run; OFClient.send_message / send_mass_message / create_post — and the
    Fansly shim's three — pass their text through it: the floor under every
    sender, including the ones that never filtered (online blast,
    PPV, posts, S4S).
  • block = skip-and-log, one rule whether the sender lets the block abort the
    run or catches it per fan: the guard's summary (texts_passed_guard /
    texts_blocked / blocked_hits) lands in the run stats, the run is `skipped`
    (its own status in the run log) iff something was blocked and nothing
    passed, and its job is done (never retried). mask = the send goes out masked.
  • human sends are untouched (no guard outside a run), and a
    send_purpose="manual" write through of_write_paced (a composer message,
    deferred via scheduled_send) stands the guard aside.

Run:  ./venv/bin/python service/tests/test_outbound_word_guard.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

import automation_executor as ax  # noqa: E402
from automation_registry import register  # noqa: E402
from automations import _wordfilter  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRun, SensitiveWord, User, UserAccount,
)
from of_client import OUTBOUND_TEXT_GUARD, OFClient  # noqa: E402

ACCT = "70001"
OTHER = "70002"

_SESSION = {
    "headers": {"user_id": ACCT, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
    "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                          "checksum_indexes": [1], "checksum_constant": 1}},
    "cookies": [],
}


class _WireSpy(OFClient):
    """A real OFClient whose wire is a list: no network, every POST captured."""

    def __init__(self):
        super().__init__(_SESSION)
        self.posts: list[dict] = []

    def _post_dropping_auto_cotag(self, path, body, retry_plan):
        self.posts.append(body)
        return {"id": None}

    def _http_call(self, method, url, *, json_body=None):  # create_post's path
        self.posts.append(json_body or {})

        class _R:
            status_code = 200
            ok = True

            @staticmethod
            def json():
                return {"id": None}
        return _R()


async def _seed() -> None:
    async with get_session() as s:
        owner, stranger = uuid.uuid4().hex, uuid.uuid4().hex
        s.add(User(id=owner, username=f"owner-{owner[:6]}", password="x"))
        s.add(User(id=stranger, username=f"other-{stranger[:6]}", password="x"))
        s.add(Account(id=ACCT, nickname="Guarded"))
        s.add(Account(id=OTHER, nickname="Elsewhere"))
        await s.flush()
        s.add(UserAccount(user_id=owner, account_id=ACCT))
        s.add(UserAccount(user_id=stranger, account_id=OTHER))
        s.add(SensitiveWord(agency_user_id=owner, word="Telegram", word_key="telegram"))
        s.add(SensitiveWord(agency_user_id=stranger, word="venmo", word_key="venmo"))


asyncio.run(_seed())


async def case_load_reads_the_agencys_sensitive_words():
    words, mode = await _wordfilter.load_banned_words(ACCT)
    assert mode == "block"
    assert [w.lower() for w in words] == ["telegram"], words
    words, _ = await _wordfilter.load_banned_words(OTHER)
    assert words == ["venmo"], f"another Agency's list leaked: {words}"


def case_guard_block_mask_and_empty():
    assert _wordfilter.outbound_guard([], "block") is None
    block = _wordfilter.outbound_guard(["telegram"], "block")
    assert block("hi babe") == "hi babe"
    try:
        block("add me on Telegram")
        raise AssertionError("block mode must refuse")
    except _wordfilter.OutboundWordsBlocked as e:
        assert e.hits == ["telegram"], e.hits
    mask = _wordfilter.outbound_guard(["telegram"], "mask")
    assert mask("add me on Telegram") == "add me on T*******"


def case_client_sends_pass_the_guard():
    spy = _WireSpy()
    spy.send_message(1, "my telegram is x")          # no guard set: human lane
    assert len(spy.posts) == 1
    token = OUTBOUND_TEXT_GUARD.set(_wordfilter.outbound_guard(["telegram"], "block"))
    try:
        for send in (lambda: spy.send_message(1, "my telegram is x"),
                     lambda: spy.send_mass_message("my telegram is x", included_users=[1]),
                     lambda: spy.create_post("my telegram is x")):
            try:
                send()
                raise AssertionError("guarded send went out")
            except _wordfilter.OutboundWordsBlocked:
                pass
        assert len(spy.posts) == 1, "a blocked send must never reach the wire"
        spy.send_message(1, "")                         # media-only: nothing to scan
        assert len(spy.posts) == 2
    finally:
        OUTBOUND_TEXT_GUARD.reset(token)
    token = OUTBOUND_TEXT_GUARD.set(_wordfilter.outbound_guard(["telegram"], "mask"))
    try:
        spy.send_mass_message("my telegram is x", included_users=[1])
    finally:
        OUTBOUND_TEXT_GUARD.reset(token)
    assert "t*******" in spy.posts[-1]["text"], spy.posts[-1]


_SPY = _WireSpy()


@register("_test_guarded_blast")
async def _guarded_blast(account_id, payload, *, run_id):
    # A sender that never filtered: straight to the client, off-thread.
    await asyncio.to_thread(_SPY.send_mass_message, payload["text"], user_lists=["fans"])
    return {"sent": 1}


async def case_run_once_blocks_as_skip_not_error():
    before = len(_SPY.posts)
    res = await ax.run_once(ACCT, "_test_guarded_blast",
                            payload={"text": "Join my Telegram"})
    assert res["status"] == "skipped" and res["reason"] == "sensitive_words", res
    assert res["blocked_hits"] == ["telegram"], res
    assert len(_SPY.posts) == before, "blocked blast reached the wire"
    async with get_session() as s:
        run = await s.get(AutomationRun, res["run_id"])
    assert run.status == "skipped", run.status
    assert json.loads(run.stats_json)["texts_blocked"] == 1, run.stats_json
    ok = await ax.run_once(ACCT, "_test_guarded_blast", payload={"text": "new set tonight"})
    assert ok["status"] == "ok" and len(_SPY.posts) == before + 1, ok
    assert OUTBOUND_TEXT_GUARD.get() is None, "the guard leaked out of the run"


@register("_test_guarded_drip")
async def _guarded_drip(account_id, payload, *, run_id):
    # Sends one DM per text; `catch` mimics a sender that swallows per-fan errors.
    sent = failed = 0
    for i, text in enumerate(payload["texts"]):
        try:
            await asyncio.to_thread(_SPY.send_message, 100 + i, text)
            sent += 1
        except _wordfilter.OutboundWordsBlocked:
            if not payload.get("catch"):
                raise
            failed += 1
    return {"sent": sent, "failed": failed}


async def case_block_keeps_what_went_out_before_it():
    texts = ["hi", "new set", "my telegram", "never reached"]
    summary = {"texts_passed_guard": 2, "texts_blocked": 1, "blocked_hits": ["telegram"]}
    # Propagated after two passed: same rule as caught, so the run is ok.
    res = await ax.run_once(ACCT, "_test_guarded_drip", payload={"texts": texts})
    assert res["status"] == "ok", res
    assert {k: res[k] for k in summary} == summary, res
    async with get_session() as s:
        run = await s.get(AutomationRun, res["run_id"])
    assert run.status == "ok"
    assert {k: json.loads(run.stats_json)[k] for k in summary} == summary, run.stats_json

    caught = await ax.run_once(ACCT, "_test_guarded_drip",
                               payload={"texts": texts, "catch": True})
    assert caught["status"] == "ok", caught
    assert (caught["sent"], caught["failed"]) == (3, 1), caught
    assert caught["texts_passed_guard"] == 3 and caught["texts_blocked"] == 1, caught

    for catch in (False, True):           # nothing passed: skipped on both paths
        blocked = await ax.run_once(ACCT, "_test_guarded_drip",
                                    payload={"texts": ["telegram?"], "catch": catch})
        assert blocked["status"] == "skipped", (catch, blocked)
        assert blocked["reason"] == "sensitive_words", blocked
        assert blocked["texts_passed_guard"] == 0 and blocked["texts_blocked"] == 1
        async with get_session() as s:
            run = await s.get(AutomationRun, blocked["run_id"])
        assert run.status == "skipped", run.status


async def case_of_write_paced_manual_stands_the_guard_aside():
    spy = _WireSpy()
    token = OUTBOUND_TEXT_GUARD.set(_wordfilter.outbound_guard(["telegram"], "block"))
    try:
        await ax.of_write_paced(ACCT, lambda: spy.send_message(1, "my telegram"),
                                min_gap_s=0, send_purpose="manual")
        assert len(spy.posts) == 1, "a human's message must send"
        assert OUTBOUND_TEXT_GUARD.get() is not None, "the guard must come back after"
        try:
            await ax.of_write_paced(ACCT, lambda: spy.send_message(1, "my telegram"),
                                    min_gap_s=0, send_purpose="gated")
            raise AssertionError("an automation write must be guarded")
        except _wordfilter.OutboundWordsBlocked:
            pass
        assert len(spy.posts) == 1
    finally:
        OUTBOUND_TEXT_GUARD.reset(token)


def case_fansly_shim_sends_pass_the_guard():
    fansly_dir = str(Path(__file__).resolve().parents[2] / "fansly")
    if fansly_dir not in sys.path:
        sys.path.insert(0, fansly_dir)
    from fansly_shim import FanslyShimClient

    class _Reached(Exception):
        pass

    def _wire(*_a, **_k):
        raise _Reached()
    shim = FanslyShimClient.__new__(FanslyShimClient)   # no session, no network
    shim._group_for_send = _wire          # send_message's first wire step
    shim._main_wall_id = _wire            # create_post's
    shim._broadcast_group = _wire         # send_mass_message's
    sends = (lambda t: shim.send_message(5, t),
             lambda t: shim.create_post(t),
             lambda t: shim.send_mass_message(t, confirm_live_broadcast=True))
    token = OUTBOUND_TEXT_GUARD.set(_wordfilter.outbound_guard(["telegram"], "block"))
    try:
        for send in sends:
            try:
                send("my telegram")
                raise AssertionError("guarded Fansly send went past the guard")
            except _wordfilter.OutboundWordsBlocked:
                pass
            try:
                send("hi babe")
                raise AssertionError("stub wire not reached")
            except _Reached:
                pass
    finally:
        OUTBOUND_TEXT_GUARD.reset(token)
    for send in sends:                    # no run, no guard: straight to the wire
        try:
            send("my telegram")
        except _Reached:
            pass


async def case_manual_scheduled_send_is_exempt():
    spy = _WireSpy()
    orig = ax._make_client
    ax._make_client = lambda _aid: spy
    try:
        manual = await ax.run_once(ACCT, "scheduled_send", payload={
            "fan_id": 5, "text": "my telegram", "send_purpose": "manual"})
        assert manual["status"] == "sent_no_id", manual   # the spy's wire returns no id
        assert len(spy.posts) == 1, "a human's deferred message must still send"
        automated = await ax.run_once(ACCT, "scheduled_send", payload={
            "fan_id": 5, "text": "my telegram"})
        assert automated.get("reason") == "sensitive_words", automated
        assert len(spy.posts) == 1
    finally:
        ax._make_client = orig


_harness.run()
