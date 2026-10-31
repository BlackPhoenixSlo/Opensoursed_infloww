#!/usr/bin/env python3
"""A missing, empty or rejected API key is ONE typed error, shown to the owner.

Before this, a feature with no usable key failed however its call site happened
to fail: a vault sweep stamped every item `failed` and said "1,777 could not be
described", a customs brief returned `ok: false` with a developer string, a
background automation paid one rejected call per fan and logged it. These cases
pin the shared contract that replaced all of that:

  * `llm_client.chat` raises `LLMKeyError(kind)` — `missing` before any request
    (no owned-agency key, an empty one, an un-owned account with no house key),
    `invalid` for 401/403, `no_credit` for 402 — exactly once, never retried.
    429 stays a transient, retried fault and is NOT a key error.
  * `server.py` answers it as HTTP 424 with `detail = key_error_payload(...)`:
    {error: "api_key_<kind>", feature, provider, fix_url: "/settings/ai-keys",
    message, fix}.
  * No part of the key ever reaches the payload or the log, even when the
    provider's own error body echoes it back.
  * Vault describe refuses before pulling a frame and leaves `describe_status`
    alone (so the item is retried once a key is added); describe-all refuses to
    start; a key rejected mid-sweep stops the sweep after one item.
  * The customs brief raises the same 424 instead of a soft `ok: false`.
  * `/admin/ai-key-status` (the automation pages' notice) reports a missing key
    and an automation's stored `key_error`, and is per-agency: B cannot read A's,
    and A's notice never names another agency or account.

Transport is stubbed (no network, no key spend).

Run: ./venv/bin/python service/tests/test_api_key_errors.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AccountAiConfig, AutomationRun, GrokCall,  # noqa: E402
                       User, UserAccount, VaultItem)
from llm_client import LLMConfigError, LLMHTTPError, LLMKeyError, chat  # noqa: E402

MODEL = "deepseek-v4-flash"
SENTINEL = "sk-SENTINEL-9f3c2e71b0d4"   # must never appear in a payload or a log

llm_client._LLM_RETRY_BACKOFF_S = 0  # the 429 case retries; don't sleep for it


# ── Transport stub ────────────────────────────────────────────────────────

class _Transport:
    """httpx.AsyncClient stand-in answering every POST with `status` (and a body
    that echoes SENTINEL, as some providers echo the key they refused)."""

    status = 200
    calls = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls += 1
        req = httpx.Request("POST", url)
        if cls.status == 200:
            return httpx.Response(200, request=req, json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        return httpx.Response(cls.status, request=req,
                              text=f'{{"error": "Incorrect API key provided: {SENTINEL}"}}')


async def _call(account_id: str, status: int = 200, purpose: str = "gen_info"):
    """Run one chat() against a stubbed transport; return (exception, calls)."""
    _Transport.status, _Transport.calls = status, 0
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _Transport
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose=purpose, account_id=account_id)
        return None, _Transport.calls
    except Exception as e:  # noqa: BLE001
        return e, _Transport.calls
    finally:
        llm_client.httpx.AsyncClient = orig


class _LogTap(logging.Handler):
    """Every formatted record (with traceback) any logger emits."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.text: list[str] = []

    def emit(self, record):
        self.text.append(logging.Formatter("%(message)s").format(record))


def _tap() -> _LogTap:
    tap = _LogTap()
    root = logging.getLogger()
    root.addHandler(tap)
    root.setLevel(logging.DEBUG)
    return tap


def _untap(tap: _LogTap) -> str:
    logging.getLogger().removeHandler(tap)
    return "\n".join(tap.text)


# ── Seeding ───────────────────────────────────────────────────────────────

async def _user(username: str, password: str = "pw-for-tests") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password, is_admin=False))
    return uid


async def _account(account_id: str, *owners: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id, daily_cost_cap_cents=1_000_000))
        for uid in owners:
            s.add(UserAccount(user_id=uid, account_id=account_id))


def _anon_admin(on: bool) -> None:
    """These HTTP cases test the key path, not the account gate — the documented
    escape hatch, read per call. The isolation case runs with it OFF."""
    if on:
        os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    else:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)


# ── 1. What chat() raises ────────────────────────────────────────────────

async def case_owned_agency_without_a_key_is_missing_and_sends_nothing():
    a = await _user("keyerr_agency_nokey")
    await _account("keyerr_acct_nokey", a)
    e, calls = await _call("keyerr_acct_nokey")
    assert isinstance(e, LLMKeyError), repr(e)
    assert isinstance(e, LLMConfigError), "existing `except LLMConfigError` hard stops must still catch it"
    assert (e.kind, e.provider, e.house) == ("missing", "deepseek", False), vars(e)
    assert calls == 0, "a request went out with no key"
    p = llm_client.key_error_payload(e)
    assert p == {
        "error": "api_key_missing", "feature": "Fan info", "provider": "deepseek",
        "fix_url": "/settings/ai-keys",
        "message": "Fan info can't run: no DeepSeek API key is set.",
        "fix": "Add it in Settings › AI keys.",
    }, p
    # The developer text (which names the owner + account) stays in str(e) for
    # logs; the owner-facing payload must not carry it.
    assert "keyerr_agency_nokey" not in json.dumps(p), p


async def case_an_empty_key_is_missing_too():
    a = await _user("keyerr_agency_empty")
    await _account("keyerr_acct_empty", a)
    await tenant_keys.set_keys(a, {"deepseek": "sk-was-here"})
    await tenant_keys.set_keys(a, {"deepseek": ""})  # cleared in Settings
    e, calls = await _call("keyerr_acct_empty")
    assert isinstance(e, LLMKeyError) and e.kind == "missing", repr(e)
    assert calls == 0


async def case_unowned_account_with_no_house_key_is_missing_house():
    await _account("keyerr_acct_house")
    real = llm_providers._api_key
    llm_providers._api_key = lambda env: ""
    try:
        e, calls = await _call("keyerr_acct_house")
    finally:
        llm_providers._api_key = real
    assert isinstance(e, LLMKeyError) and e.kind == "missing" and e.house, repr(e)
    assert calls == 0
    p = llm_client.key_error_payload(e)
    assert "Settings › System" in p["fix"], p


async def case_rejected_keys_are_typed_and_never_retried():
    a = await _user("keyerr_agency_wrong")
    await _account("keyerr_acct_wrong", a)
    await tenant_keys.set_keys(a, {"deepseek": SENTINEL})
    for status, kind in ((401, "invalid"), (403, "invalid"), (402, "no_credit")):
        tap = _tap()
        e, calls = await _call("keyerr_acct_wrong", status, purpose="reply_mass_funnel")
        logs = _untap(tap)
        assert isinstance(e, LLMKeyError) and e.kind == kind, (status, repr(e))
        assert isinstance(e, LLMHTTPError) and e.status == status, "HTTP callers keep the status"
        assert calls == 1, f"HTTP {status} is permanent — retried {calls - 1}×"
        p = llm_client.key_error_payload(e)
        assert p["error"] == f"api_key_{kind}" and p["feature"] == "Auto Funnel", p
        assert SENTINEL not in json.dumps(p), "the payload echoed the key"
        assert SENTINEL not in logs, f"HTTP {status}: the key reached a log line: " + " // ".join(l[:300] for l in logs.splitlines() if SENTINEL in l)
    assert "out of credit" in p["message"] and "Top it up at DeepSeek" in p["fix"], p
    # Nor is it STORED: the audit row keeps the status, not the provider body
    # that echoed the key.
    async with get_session() as s:
        texts = (await s.execute(select(GrokCall.error_text).where(
            GrokCall.account_id == "keyerr_acct_wrong"))).scalars().all()
    assert len(texts) == 3 and all(t and "HTTP 40" in t for t in texts), texts
    assert not any(SENTINEL in t for t in texts), "the key was stored in grok_calls.error_text"


async def case_429_is_still_retried_and_not_a_key_error():
    a = await _user("keyerr_agency_429")
    await _account("keyerr_acct_429", a)
    await tenant_keys.set_keys(a, {"deepseek": "sk-fine"})
    e, calls = await _call("keyerr_acct_429", 429)
    assert isinstance(e, LLMHTTPError) and not isinstance(e, LLMKeyError), repr(e)
    assert calls == llm_client._LLM_MAX_ATTEMPTS, f"429 must be retried, got {calls} call(s)"


# ── 2. The 424 the app reads ─────────────────────────────────────────────

async def _vault_item(aid: str, mid: int) -> None:
    from datetime import datetime
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=mid, kind="photo",
                        created_at=datetime(2026, 6, 1), tags="[]"))


async def _describe_status(aid: str, mid: int):
    async with get_session() as s:
        return (await s.get(VaultItem, (aid, mid))).describe_status


async def case_seed_vault_accounts():
    nokey = await _user("keyerr_vault_nokey")
    await _account("keyerr_vault_nokey", nokey)
    await _vault_item("keyerr_vault_nokey", 1)
    for mid in range(10, 15):
        await _vault_item("keyerr_vault_nokey", mid)
    wrong = await _user("keyerr_vault_wrong")
    await _account("keyerr_vault_wrong", wrong)
    await tenant_keys.set_keys(wrong, {"deepinfra": SENTINEL})
    await _vault_item("keyerr_vault_wrong", 2)
    for mid in range(20, 25):
        await _vault_item("keyerr_vault_wrong", mid)


def case_vault_describe_without_a_key_is_424_before_any_frame():
    import vault_frames
    pulled: list[int] = []
    orig = vault_frames.collect

    async def _spy(*a, **k):
        pulled.append(1)
        return await orig(*a, **k)

    vault_frames.collect = _spy
    _anon_admin(True)
    try:
        r = _harness.make_client().post("/admin/vault-ai/describe",
                                        json={"account_id": "keyerr_vault_nokey", "media_id": 1})
    finally:
        vault_frames.collect = orig
        _anon_admin(False)
    assert r.status_code == 424, (r.status_code, r.text)
    d = r.json()["detail"]
    assert d["error"] == "api_key_missing" and d["provider"] == "deepinfra", d
    assert d["feature"] == "Vault describe" and d["fix_url"] == "/settings/ai-keys", d
    assert d["message"] == "Vault describe can't run: no DeepInfra API key is set.", d
    assert pulled == [], "frames were pulled for a describe that could never run"
    assert asyncio.run(_describe_status("keyerr_vault_nokey", 1)) is None, "item was stamped"


def case_vault_describe_with_a_rejected_key_is_424_and_leaves_the_item_alone():
    import vault_frames
    orig_collect = vault_frames.collect
    orig_http = llm_client.httpx.AsyncClient

    async def _frame(*a, **k):
        return vault_frames.Collected(["data:image/png;base64,AAAA"], "")

    vault_frames.collect = _frame
    llm_client.httpx.AsyncClient = _Transport
    _Transport.status, _Transport.calls = 401, 0
    _anon_admin(True)
    tap = _tap()
    try:
        r = _harness.make_client().post("/admin/vault-ai/describe",
                                        json={"account_id": "keyerr_vault_wrong", "media_id": 2})
    finally:
        logs = _untap(tap)
        vault_frames.collect = orig_collect
        llm_client.httpx.AsyncClient = orig_http
        _anon_admin(False)
    assert r.status_code == 424, (r.status_code, r.text)
    d = r.json()["detail"]
    assert d["error"] == "api_key_invalid", d
    assert d["message"] == ("Vault describe stopped: DeepInfra rejected the API key "
                            "(wrong or revoked)."), d
    assert d["fix"] == "Paste the right key in Settings › AI keys.", d
    assert _Transport.calls == 1, "the rejected key was tried again (escalation model?)"
    assert SENTINEL not in r.text, "the 424 echoed the key"
    assert SENTINEL not in logs, "the key reached a log line"
    assert asyncio.run(_describe_status("keyerr_vault_wrong", 2)) is None, (
        "a key problem was stamped on the item — it would not be retried once fixed")


def case_describe_all_without_a_key_refuses_to_start():
    import vault_ai_vision
    _anon_admin(True)
    try:
        r = _harness.make_client().post("/admin/vault-ai/describe-all",
                                        json={"account_id": "keyerr_vault_nokey"})
    finally:
        _anon_admin(False)
    assert r.status_code == 424 and r.json()["detail"]["error"] == "api_key_missing", r.text
    assert "keyerr_vault_nokey" not in vault_ai_vision._describe_running


async def case_a_key_rejected_mid_sweep_stops_it_after_one_item():
    import vault_ai_vision
    calls: list[int] = []

    async def _rejected(aid, mid, **k):
        calls.append(int(mid))
        raise LLMKeyError("invalid", "deepinfra", "describe_media", status=401,
                          detail=f"deepinfra HTTP 401: {SENTINEL}")

    orig, conc = vault_ai_vision._describe_one, vault_ai_vision._DESCRIBE_CONCURRENCY
    vault_ai_vision._describe_one, vault_ai_vision._DESCRIBE_CONCURRENCY = _rejected, 1
    try:
        await vault_ai_vision._run_describe_all("keyerr_vault_wrong", "force", prompt_version="v2")
    finally:
        vault_ai_vision._describe_one, vault_ai_vision._DESCRIBE_CONCURRENCY = orig, conc
    assert len(calls) == 1, f"the sweep kept paying for a dead key: {calls}"
    prog = vault_ai_vision._describe_progress["keyerr_vault_wrong"]
    assert prog["key_error"]["error"] == "api_key_invalid", prog
    assert prog["error"] == prog["key_error"]["message"], prog
    assert SENTINEL not in json.dumps(prog), "the sweep snapshot carried the key"
    for mid in range(20, 25):
        assert await _describe_status("keyerr_vault_wrong", mid) is None, mid


def case_customs_brief_without_a_key_is_424():
    import customs_api

    async def _ctx(**k):
        return {"messages": [{"message_id": 1, "from_fan": True, "at": "2026-06-01T10:00:00",
                              "text": "a 5 minute video in the red dress please"}]}

    async def _order(**k):
        return {"lines": []}

    asyncio.run(_seed_customs())
    real_ctx, real_order = customs_api.customs_context, customs_api.customs_order
    customs_api.customs_context, customs_api.customs_order = _ctx, _order
    _anon_admin(True)
    try:
        r = _harness.make_client().post("/admin/customs/brief",
                                        json={"account_id": "keyerr_customs", "fan_id": 77})
    finally:
        customs_api.customs_context, customs_api.customs_order = real_ctx, real_order
        _anon_admin(False)
    assert r.status_code == 424, (r.status_code, r.text)
    d = r.json()["detail"]
    assert d["error"] == "api_key_missing" and d["feature"] == "Customs brief", d


async def _seed_customs():
    a = await _user("keyerr_customs_owner")
    await _account("keyerr_customs", a)


# ── 3. The automation pages' notice, per agency ──────────────────────────

_ISO: dict = {}


async def case_seed_two_agencies_for_the_notice():
    _ISO["a"] = await _user("keyerr_agency_alpha", password="alpha-pw")
    _ISO["b"] = await _user("keyerr_agency_bravo", password="bravo-pw")
    await _account("keyerr_alpha_nokey", _ISO["a"])
    await _account("keyerr_alpha_keyed", _ISO["a"])
    await _account("keyerr_bravo_acct", _ISO["b"])
    await tenant_keys.set_keys(_ISO["b"], {"deepseek": "sk-bravo"})
    # A keyed agency whose last funnel run stopped on a rejected key.
    alpha2 = await _user("keyerr_agency_alpha2", password="alpha2-pw")
    _ISO["a2"] = alpha2
    await _account("keyerr_alpha2_keyed", alpha2)
    await tenant_keys.set_keys(alpha2, {"deepseek": "sk-alpha2"})
    p = llm_client.key_error_payload(LLMKeyError("invalid", "deepseek", "reply_mass_funnel"))
    async with get_session() as s:
        s.add(AutomationRun(account_id="keyerr_alpha2_keyed", kind="reply_mass_funnel",
                            status="ok", stats_json=json.dumps({"key_error": p})))


def _login(username: str, password: str):
    c = _harness.make_client()
    r = c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, (r.status_code, r.text)
    return c


def case_the_notice_reports_a_missing_key_per_feature():
    c = _login("keyerr_agency_alpha", "alpha-pw")
    r = c.get("/admin/ai-key-status",
              params={"account_id": "keyerr_alpha_nokey",
                      "kinds": "autoreply,welcome_chatter_for_info,send_followup"})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert [i["available"] for i in body["items"]] == [False, False, False], body
    assert len(body["notices"]) == 1, "one provider, one problem → one grouped notice"
    n = body["notices"][0]
    assert n["error"] == "api_key_missing" and n["provider"] == "deepseek", n
    assert n["message"] == ("Auto-reply, Info chatter and Follow-ups can't run: "
                            "no DeepSeek API key is set."), n
    # Never another agency's name, never another account.
    for other in ("keyerr_agency_bravo", "keyerr_bravo_acct", "keyerr_alpha_keyed"):
        assert other not in r.text, f"the notice named {other}"


def case_the_notice_reports_a_stored_key_error():
    c = _login("keyerr_agency_alpha2", "alpha2-pw")
    r = c.get("/admin/ai-key-status",
              params={"account_id": "keyerr_alpha2_keyed", "kinds": "reply_mass_funnel,autoreply"})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    funnel = next(i for i in body["items"] if i["kind"] == "reply_mass_funnel")
    assert funnel["available"] is True, funnel
    assert funnel["last_key_error"]["error"] == "api_key_invalid", funnel
    assert [n["error"] for n in body["notices"]] == ["api_key_invalid"], body
    assert body["notices"][0]["feature"] == "Auto Funnel", body


def case_one_agency_cannot_read_anothers_key_status():
    c = _login("keyerr_agency_bravo", "bravo-pw")
    r = c.get("/admin/ai-key-status",
              params={"account_id": "keyerr_alpha_nokey", "kinds": "autoreply"})
    assert r.status_code == 403, (r.status_code, r.text)
    anon = _harness.make_client().get("/admin/ai-key-status",
                                      params={"account_id": "keyerr_alpha_nokey",
                                              "kinds": "autoreply"})
    assert anon.status_code == 401, anon.status_code


_harness.run()
