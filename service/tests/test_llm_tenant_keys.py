#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import delete as sa_delete, select  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import tenant_keys  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AccountHealth, GrokCall, GrokDailyCost,
    GrokUserDailyCost, Session, User, UserAccount, UserLlmKey,
)
from llm_client import LLMCapExceeded, LLMConfigError, chat  # noqa: E402

MODEL = "deepseek-v4-flash"
HOUSE_PROVIDER = "deepseek"



class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _KeyCapturingClient:

    last_bearer: str = ""
    calls: int = 0

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        cls = type(self)
        cls.calls += 1
        auth = (headers or {}).get("Authorization", "")
        cls.last_bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else auth
        return _FakeResp({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "prompt_cache_hit_tokens": 0},
        })


async def _bearer_for(account_id: str, purpose: str = "gen_info") -> str:
    _KeyCapturingClient.last_bearer = ""
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _KeyCapturingClient
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose=purpose, account_id=account_id)
    finally:
        llm_client.httpx.AsyncClient = orig
    return _KeyCapturingClient.last_bearer


async def _bearer_for_agency(user_id: str, purpose: str = "help_assistant") -> str:
    _KeyCapturingClient.last_bearer = ""
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _KeyCapturingClient
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose=purpose, account_id=None, user_id=user_id)
    finally:
        llm_client.httpx.AsyncClient = orig
    return _KeyCapturingClient.last_bearer



async def _seed_user(username: str, is_admin: bool = False,
                     password: str = "x") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password,
                   is_admin=is_admin))
    return uid


import accounts as _accounts_mod  # noqa: E402


def _register_seeded_accounts(*, live: set[str] | None = None,
                              omit: set[str] | None = None) -> None:
    async def _ids():
        async with get_session() as s:
            return list((await s.execute(select(Account.id))).scalars().all())
    ids = [a for a in asyncio.run(_ids()) if a not in (omit or set())]
    _accounts_mod.list_accounts = lambda: [  # type: ignore[assignment]
        {"id": a, "has_session": live is None or a in live} for a in ids
    ]


async def _seed_account(account_id: str, *owner_ids: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            s.add(AccountAiConfig(account_id=account_id,
                                  daily_cost_cap_cents=1_000_000))
        for uid in owner_ids:
            s.add(UserAccount(user_id=uid, account_id=account_id))


def _house_key() -> str:
    return llm_providers.house_key(HOUSE_PROVIDER)



async def case_two_agencies_put_two_different_keys_on_the_wire():
    a = await _seed_user("agency_a")
    b = await _seed_user("agency_b")
    await _seed_account("acct_a", a)
    await _seed_account("acct_b", b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-agency-a"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-agency-b"})

    assert await _bearer_for("acct_a") == "sk-agency-a", "agency A billed the wrong key"
    assert await _bearer_for("acct_b") == "sk-agency-b", "agency B billed the wrong key"


async def case_every_account_of_one_agency_shares_that_agencys_key():
    a = await _seed_user("agency_multi")
    await _seed_account("acct_multi_1", a)
    await _seed_account("acct_multi_2", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-multi"})

    assert await _bearer_for("acct_multi_1") == "sk-multi"
    assert await _bearer_for("acct_multi_2") == "sk-multi"


async def case_agency_key_beats_the_house_key():
    a = await _seed_user("agency_beats_house")
    await _seed_account("acct_beats_house", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-mine-not-yours"})

    sent = await _bearer_for("acct_beats_house")
    assert sent == "sk-mine-not-yours", f"expected the agency key, got {sent!r}"
    assert sent != _house_key(), "the house key leaked into a tenant's call"



async def case_orphan_account_falls_back_to_the_house_key():
    await _seed_account("acct_orphan")
    assert await _bearer_for("acct_orphan") == _house_key()


async def case_an_explicit_api_key_beats_the_house_key():
    _KeyCapturingClient.last_bearer = ""
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _KeyCapturingClient
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose="support_summary", account_id=None, api_key="hub-only-key")
    finally:
        llm_client.httpx.AsyncClient = orig
    assert _KeyCapturingClient.last_bearer == "hub-only-key" != _house_key()


async def case_blank_account_id_falls_back_to_the_house_key():
    prov = llm_providers.PROVIDERS[HOUSE_PROVIDER]
    assert await llm_client._tenant_api_key("", prov) == _house_key()
    assert await tenant_keys.owners_of("") == []


async def case_owner_without_a_key_fails_closed_and_sends_nothing():
    a = await _seed_user("agency_no_key")
    await _seed_account("acct_no_key", a)

    _KeyCapturingClient.calls = 0
    before = await _grok_call_count()
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _KeyCapturingClient
    raised = None
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose="gen_info", account_id="acct_no_key")
    except LLMConfigError as e:
        raised = e
    finally:
        llm_client.httpx.AsyncClient = orig

    assert raised is not None, "an owner with no key was allowed to call"
    assert "no 'deepseek' API key" in str(raised), f"unhelpful error: {raised}"
    assert _KeyCapturingClient.calls == 0, "a request went out anyway"
    assert await _grok_call_count() == before, "a pending audit row was written"


async def case_a_missing_provider_is_specific_to_that_provider():
    a = await _seed_user("agency_one_provider")
    await _seed_account("acct_one_provider", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-deepseek-only"})

    assert await _bearer_for("acct_one_provider") == "sk-deepseek-only"
    zai = llm_providers.PROVIDERS["zai"]
    try:
        await llm_client._tenant_api_key("acct_one_provider", zai)
        assert False, "zai resolved despite no zai key for this agency"
    except LLMConfigError as e:
        assert "zai" in str(e), f"error names the wrong provider: {e}"



async def case_a_master_oversight_link_does_not_outrank_the_agency():
    master = await _seed_user("master_oversight", is_admin=True)
    agency = await _seed_user("agency_runs_it")
    await _seed_account("acct_oversight", agency, master)
    await tenant_keys.set_keys(master, {HOUSE_PROVIDER: "sk-founder"})
    await tenant_keys.set_keys(agency, {HOUSE_PROVIDER: "sk-agency"})

    assert await tenant_keys.owners_of("acct_oversight") == [agency], \
        "the master's oversight link was treated as ownership"
    assert await _bearer_for("acct_oversight") == "sk-agency", \
        "the founder was billed for an agency's traffic"


async def case_master_is_the_owner_when_it_is_the_only_link():
    master = await _seed_user("master_solo", is_admin=True)
    await _seed_account("acct_master_solo", master)
    await tenant_keys.set_keys(master, {HOUSE_PROVIDER: "sk-master-solo"})

    assert await _bearer_for("acct_master_solo") == "sk-master-solo"


async def case_two_owners_bill_the_only_one_with_a_key():
    a = await _seed_user("agency_share_keyed")
    b = await _seed_user("agency_share_bare")
    await _seed_account("acct_two_owners_one_key", a, b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-share-keyed"})

    owners = await tenant_keys.owners_of("acct_two_owners_one_key")
    assert sorted(owners) == sorted([a, b]), f"both owners not surfaced: {owners}"
    assert await _bearer_for("acct_two_owners_one_key") == "sk-share-keyed", \
        "a shared account with exactly one keyed owner was not billed to them"


async def case_two_owners_with_no_key_anywhere_name_them_both():
    a = await _seed_user("agency_share_none_1")
    b = await _seed_user("agency_share_none_2")
    await _seed_account("acct_two_owners_no_key", a, b)
    try:
        await llm_client._tenant_api_key(
            "acct_two_owners_no_key", llm_providers.PROVIDERS[HOUSE_PROVIDER])
        assert False, "a shared account with no key anywhere resolved to one"
    except LLMConfigError as e:
        assert "no 'deepseek' API key" in str(e), f"unhelpful error: {e}"
        assert a in str(e) and b in str(e), f"error does not name both: {e}"


async def case_two_owners_both_keyed_refuse_rather_than_guess():
    a = await _seed_user("agency_share_1")
    b = await _seed_user("agency_share_2")
    await _seed_account("acct_two_owners", a, b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-share-1"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-share-2"})

    try:
        await llm_client._tenant_api_key(
            "acct_two_owners", llm_providers.PROVIDERS[HOUSE_PROVIDER])
        assert False, "an ambiguously-owned account resolved to a key"
    except LLMConfigError as e:
        assert "more than one owner" in str(e), f"unhelpful error: {e}"


async def case_a_dispute_is_per_provider_not_per_account():
    a = await _seed_user("agency_split_1")
    b = await _seed_user("agency_split_2")
    await _seed_account("acct_split_dispute", a, b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-split-1", "zai": "zai-only-a"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-split-2"})

    zai = llm_providers.PROVIDERS["zai"]
    assert await llm_client._tenant_api_key("acct_split_dispute", zai) == "zai-only-a"
    try:
        await llm_client._tenant_api_key(
            "acct_split_dispute", llm_providers.PROVIDERS[HOUSE_PROVIDER])
        assert False, "a provider both owners hold resolved to a key"
    except LLMConfigError as e:
        assert "more than one owner" in str(e), f"unhelpful error: {e}"



async def case_masked_value_never_overwrites_a_stored_key():
    a = await _seed_user("agency_mask")
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-real-value"})
    try:
        await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "••••lue"})
        assert False, "a masked placeholder was stored as a key"
    except ValueError as e:
        assert "masked" in str(e), f"unhelpful error: {e}"
    assert await tenant_keys.get_key(a, HOUSE_PROVIDER) == "sk-real-value", \
        "the stored key was damaged by the rejected write"


async def case_unknown_provider_is_refused():
    a = await _seed_user("agency_typo")
    try:
        await tenant_keys.set_keys(a, {"deep_seek": "sk-typo"})
        assert False, "an unknown provider was stored"
    except ValueError as e:
        assert "unknown provider" in str(e), f"unhelpful error: {e}"
    async with get_session() as s:
        rows = (await s.execute(select(UserLlmKey).where(
            UserLlmKey.user_id == a))).all()
    assert not rows, "an unreachable row was written"


async def case_empty_value_clears_the_key():
    a = await _seed_user("agency_clear")
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-temp"})
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: ""})
    assert await tenant_keys.get_key(a, HOUSE_PROVIDER) == ""


async def case_status_masks_and_never_returns_the_key():
    a = await _seed_user("agency_status")
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-abcdefghijkl"})
    st = await tenant_keys.status(a)
    assert st[HOUSE_PROVIDER]["set"] is True
    assert st[HOUSE_PROVIDER]["hint"] == "••••ijkl", st[HOUSE_PROVIDER]["hint"]
    assert "sk-abcdefghijkl" not in repr(st), "status leaked the raw key"
    assert st["zai"]["set"] is False and st["zai"]["hint"] == ""


async def case_deleting_an_agency_destroys_its_keys():
    a = await _seed_user("agency_offboard")
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-offboard"})
    async with get_session() as s:
        await s.execute(sa_delete(User).where(User.id == a))
    assert await tenant_keys.get_key(a, HOUSE_PROVIDER) == "", \
        "an offboarded agency's key survived the user row"



_UI: dict[str, str] = {}


async def case_seed_the_ui_owner():
    _UI["owner"] = await _seed_user("agency_ui", password="secretpw")
    _UI["other"] = await _seed_user("agency_ui_bystander")
    await tenant_keys.set_keys(_UI["other"], {HOUSE_PROVIDER: "sk-bystander"})


def case_endpoints_require_a_signed_in_owner():
    client = _harness.make_client()
    assert client.get("/admin/my-llm-keys").status_code == 401
    r = client.put("/admin/my-llm-keys", json={HOUSE_PROVIDER: "sk-anon"})
    assert r.status_code == 401, f"anonymous write returned {r.status_code}"


def case_signed_in_owner_round_trips_only_their_own_key():
    client = _harness.make_client()
    r = client.post("/auth/login",
                    json={"username": "agency_ui", "password": "secretpw"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"

    r = client.put("/admin/my-llm-keys", json={HOUSE_PROVIDER: "sk-from-the-ui"})
    assert r.status_code == 200, f"save failed: {r.status_code} {r.text}"
    provs = r.json()["providers"]
    assert provs[HOUSE_PROVIDER]["set"] is True
    assert provs[HOUSE_PROVIDER]["hint"] == "••••e-ui", provs[HOUSE_PROVIDER]["hint"]
    assert "sk-from-the-ui" not in r.text, "the response echoed the raw key"

    got = client.get("/admin/my-llm-keys")
    assert got.status_code == 200
    assert got.json()["providers"][HOUSE_PROVIDER]["hint"] == "••••e-ui"

    stored = asyncio.run(tenant_keys.get_key(_UI["owner"], HOUSE_PROVIDER))
    assert stored == "sk-from-the-ui", f"owner row not written: {stored!r}"
    bystander = asyncio.run(tenant_keys.get_key(_UI["other"], HOUSE_PROVIDER))
    assert bystander == "sk-bystander", "another agency's key was touched"


def case_http_refuses_a_masked_value():
    client = _harness.make_client()
    r = client.post("/auth/login",
                    json={"username": "agency_ui", "password": "secretpw"})
    assert r.status_code == 200
    r = client.put("/admin/my-llm-keys", json={HOUSE_PROVIDER: "••••e-ui"})
    assert r.status_code == 400, f"mask accepted: {r.status_code} {r.text}"
    stored = asyncio.run(tenant_keys.get_key(_UI["owner"], HOUSE_PROVIDER))
    assert stored == "sk-from-the-ui", f"key damaged by the rejected write: {stored!r}"



async def _grok_call_count() -> int:
    async with get_session() as s:
        return len((await s.execute(select(GrokCall.id))).all())


_MANAGED: dict[str, str] = {}


async def case_seed_a_master_and_a_managed_agency():
    _MANAGED["master"] = await _seed_user(
        "master_manager", is_admin=True, password="secretpw")
    _MANAGED["agency"] = await _seed_user("agency_managed", password="secretpw")
    await _seed_account("acct_managed", _MANAGED["agency"])


def case_master_can_set_another_agencys_key():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200

    uid = _MANAGED["agency"]
    r = client.put(f"/admin/users/{uid}/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"],
        "providers": {HOUSE_PROVIDER: "sk-set-by-founder"}})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert "sk-set-by-founder" not in r.text, "the response echoed the raw key"

    got = client.get(f"/admin/users/{uid}/llm-keys")
    assert got.status_code == 200
    assert got.json()["providers"][HOUSE_PROVIDER]["hint"] == "••••nder"

    assert asyncio.run(_bearer_for("acct_managed")) == "sk-set-by-founder"


def case_a_wrong_admin_password_cannot_set_a_key():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200
    r = client.put(f"/admin/users/{_MANAGED['agency']}/llm-keys", json={
        "admin_password": "nope", "providers": {HOUSE_PROVIDER: "sk-hijack"}})
    assert r.status_code == 403, f"{r.status_code} {r.text}"
    assert asyncio.run(
        tenant_keys.get_key(_MANAGED["agency"], HOUSE_PROVIDER)
    ) == "sk-set-by-founder", "a refused write still changed the key"


def case_a_non_master_cannot_touch_another_agencys_keys():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "agency_managed", "password": "secretpw"}).status_code == 200
    uid = _MANAGED["master"]
    assert client.get(f"/admin/users/{uid}/llm-keys").status_code == 403
    r = client.put(f"/admin/users/{uid}/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"],
        "providers": {HOUSE_PROVIDER: "sk-hijack"}})
    assert r.status_code == 403, f"{r.status_code} {r.text}"


TRACKER_KEY = "ltk_" + "z" * 40


def case_the_llm_key_writes_refuse_the_tracker_provider():
    owner = _harness.make_client()
    assert owner.post("/auth/login", json={"username": "agency_ui", "password": "secretpw"}).status_code == 200
    r = owner.put("/admin/my-llm-keys", json={"leak_tracker": TRACKER_KEY})
    assert r.status_code == 400, f"{r.status_code} {r.text}"
    master = _harness.make_client()
    assert master.post("/auth/login", json={"username": "master_manager", "password": "secretpw"}).status_code == 200
    r = master.put(f"/admin/users/{_MANAGED['agency']}/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"], "providers": {"leak_tracker": TRACKER_KEY}})
    assert r.status_code == 400, f"{r.status_code} {r.text}"
    for uid in (_UI["owner"], _MANAGED["agency"]):
        assert asyncio.run(tenant_keys.get_key(uid, "leak_tracker")) == ""


def case_the_key_overview_never_lists_the_tracker_key():
    uid = _MANAGED["agency"]
    non_llm = (*tenant_keys.NON_LLM_PROVIDERS, "unknown_provider")
    asyncio.run(tenant_keys.set_keys(uid, {"leak_tracker": TRACKER_KEY, "unknown_provider": "fixture"}, known=non_llm))
    try:
        assert asyncio.run(tenant_keys.get_key(uid, "leak_tracker")) == TRACKER_KEY
        assert "leak_tracker" not in asyncio.run(tenant_keys.status(uid))
        master = _harness.make_client()
        assert master.post("/auth/login", json={"username": "master_manager", "password": "secretpw"}).status_code == 200
        roster = master.get("/admin/users/llm-key-status")
        assert roster.status_code == 200, roster.text
        row = next(a for a in roster.json()["agencies"] if a["user_id"] == uid)
        assert row["providers_set"] == [HOUSE_PROVIDER], row
        one = master.get(f"/admin/users/{uid}/llm-keys")
        assert "leak_tracker" not in one.json()["providers"] and TRACKER_KEY not in one.text
        own = _harness.make_client()
        assert own.post("/auth/login", json={"username": "agency_managed", "password": "secretpw"}).status_code == 200
        mine = own.get("/admin/my-llm-keys")
        assert "leak_tracker" not in mine.json()["providers"] and TRACKER_KEY not in mine.text
    finally:
        asyncio.run(tenant_keys.set_keys(uid, {"leak_tracker": "", "unknown_provider": ""}, known=non_llm))


def case_key_status_roster_ranks_agencies_with_a_live_model_first():
    master = asyncio.run(_seed_user("roster_master", is_admin=True, password="secretpw"))
    live = asyncio.run(_seed_user("roster_live", password="secretpw"))
    dead = asyncio.run(_seed_user("roster_dead", password="secretpw"))
    assert master
    asyncio.run(_seed_account("acct_roster_live", live))
    asyncio.run(_seed_account("acct_roster_dead", dead))
    asyncio.run(tenant_keys.set_keys(live, {HOUSE_PROVIDER: "sk-roster-live"}))

    now = datetime.utcnow()

    async def _sessions():
        async with get_session() as s:
            for aid in ("acct_roster_live", "acct_roster_dead"):
                s.add(Session(account_id=aid, captured_at=now, cookies_json="{}",
                              x_of_rev="r", signing_rules_json="{}", is_latest=True))
            s.add(AccountHealth(account_id="acct_roster_dead",
                                session_dead_at=now,
                                session_dead_reason="Wrong user."))
    asyncio.run(_sessions())

    _register_seeded_accounts()
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "roster_master", "password": "secretpw"}).status_code == 200
    r = client.get("/admin/users/llm-key-status")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert "sk-roster-live" not in r.text, "the roster leaked a raw key"

    by_name = {a["username"]: a for a in r.json()["agencies"]}
    assert by_name["roster_live"]["live_accounts"] == 1, by_name["roster_live"]
    assert by_name["roster_dead"]["live_accounts"] == 0, by_name["roster_dead"]
    assert by_name["roster_dead"]["accounts"] == 1, "a dead model still counts as owned"
    assert by_name["roster_master"]["live_accounts"] == 0, by_name["roster_master"]
    assert by_name["roster_live"]["providers_set"] == [HOUSE_PROVIDER]
    assert by_name["roster_dead"]["providers_set"] == []
    names = [a["username"] for a in r.json()["agencies"]]
    assert names.index("roster_live") < names.index("roster_dead"), names


def case_the_roster_counts_what_is_BILLED_not_what_is_linked():
    master = asyncio.run(_seed_user("billed_master", is_admin=True, password="secretpw"))
    agency = asyncio.run(_seed_user("billed_agency", password="secretpw"))
    rival = asyncio.run(_seed_user("billed_rival", password="secretpw"))
    solo = asyncio.run(_seed_user("billed_solo_master_acct", password="secretpw"))
    assert solo
    asyncio.run(tenant_keys.set_keys(agency, {HOUSE_PROVIDER: "sk-billed-agency"}))
    asyncio.run(tenant_keys.set_keys(rival, {HOUSE_PROVIDER: "sk-billed-rival"}))

    asyncio.run(_seed_account("acct_billed_watched", agency, master))
    asyncio.run(_seed_account("acct_billed_master_only", master))
    asyncio.run(_seed_account("acct_billed_disputed", agency, rival))
    bare = asyncio.run(_seed_user("billed_bare_dup", password="secretpw"))
    asyncio.run(_seed_account("acct_billed_shared_one_key", bare, agency))

    now = datetime.utcnow()

    async def _live():
        async with get_session() as s:
            for aid in ("acct_billed_watched", "acct_billed_master_only",
                        "acct_billed_disputed", "acct_billed_shared_one_key"):
                s.add(Session(account_id=aid, captured_at=now, cookies_json="{}",
                              x_of_rev="r", signing_rules_json="{}", is_latest=True))
    asyncio.run(_live())

    _register_seeded_accounts()
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "billed_master", "password": "secretpw"}).status_code == 200
    by_name = {a["username"]: a
               for a in client.get("/admin/users/llm-key-status").json()["agencies"]}

    assert by_name["billed_master"]["live_accounts"] == 1, by_name["billed_master"]
    assert by_name["billed_master"]["blocked_accounts"] == 0, by_name["billed_master"]
    assert by_name["billed_agency"]["live_accounts"] == 2, by_name["billed_agency"]
    assert by_name["billed_agency"]["blocked_accounts"] == 1, by_name["billed_agency"]
    assert by_name["billed_rival"]["live_accounts"] == 0, by_name["billed_rival"]
    assert by_name["billed_rival"]["blocked_accounts"] == 1, by_name["billed_rival"]
    assert by_name["billed_bare_dup"]["live_accounts"] == 0, by_name["billed_bare_dup"]
    assert by_name["billed_bare_dup"]["blocked_accounts"] == 0, by_name["billed_bare_dup"]


def case_two_masters_on_one_model_bill_nobody_on_the_roster_too():
    m1 = asyncio.run(_seed_user("twomaster_a", is_admin=True, password="secretpw"))
    m2 = asyncio.run(_seed_user("twomaster_b", is_admin=True, password="secretpw"))
    assert tenant_keys.billable_owners([(m1, True), (m2, True)]) == [m1, m2], \
        "two masters and no agency is a dispute, not a pick"
    for m in (m1, m2):
        asyncio.run(tenant_keys.set_keys(m, {HOUSE_PROVIDER: f"sk-{m[:6]}"}))

    asyncio.run(_seed_account("acct_two_masters", m1, m2))
    _register_seeded_accounts()
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "twomaster_a", "password": "secretpw"}).status_code == 200
    by_name = {a["username"]: a
               for a in client.get("/admin/users/llm-key-status").json()["agencies"]}

    for name in ("twomaster_a", "twomaster_b"):
        row = by_name[name]
        assert row["accounts"] == 0, f"{name} was billed a disputed model: {row}"
        assert row["live_accounts"] == 0, f"{name} showed it live: {row}"
        assert row["blocked_accounts"] == 1, f"{name} lost the dispute: {row}"


def case_a_deleted_model_is_not_live_however_alive_its_rows_look():
    agency = asyncio.run(_seed_user("registry_agency", password="secretpw"))
    asyncio.run(_seed_account("acct_still_registered", agency))
    asyncio.run(_seed_account("acct_deleted_from_disk", agency))

    async def _both_look_alive():
        async with get_session() as s:
            for aid in ("acct_still_registered", "acct_deleted_from_disk"):
                s.add(Session(account_id=aid, captured_at=datetime.utcnow(),
                              cookies_json="{}", x_of_rev="r",
                              signing_rules_json="{}", is_latest=True))
    asyncio.run(_both_look_alive())

    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200

    _register_seeded_accounts()
    both = {a["username"]: a
            for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    assert both["registry_agency"]["live_accounts"] == 2, both["registry_agency"]
    assert both["registry_agency"]["accounts"] == 2, both["registry_agency"]

    _register_seeded_accounts(omit={"acct_deleted_from_disk"})
    after = {a["username"]: a
             for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    assert after["registry_agency"]["live_accounts"] == 1, after["registry_agency"]
    assert after["registry_agency"]["accounts"] == 1, \
        "a deleted model still counted as owned — 'of N models' quotes a model " \
        "the operator cannot see"


def case_a_registered_model_with_no_session_is_owned_but_not_live():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200
    _register_seeded_accounts(omit={"acct_deleted_from_disk"},
                              live=set())
    got = {a["username"]: a
           for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    assert got["registry_agency"]["accounts"] == 1, got["registry_agency"]
    assert got["registry_agency"]["live_accounts"] == 0, got["registry_agency"]


def case_the_wrong_providers_key_still_needs_a_key():
    other = "deepinfra" if HOUSE_PROVIDER != "deepinfra" else "zai"
    agency = asyncio.run(_seed_user("partial_agency", password="secretpw"))
    asyncio.run(_seed_account("acct_partial", agency))
    asyncio.run(tenant_keys.set_keys(agency, {other: "sk-wrong-provider"}))

    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200
    _register_seeded_accounts(omit={"acct_deleted_from_disk"})
    got = {a["username"]: a
           for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    row = got["partial_agency"]
    assert row["providers_set"] == [other], row
    assert row["missing_providers"] == [HOUSE_PROVIDER], row


def case_the_roster_is_not_one_agencys_business():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "roster_live", "password": "secretpw"}).status_code == 200
    assert client.get("/admin/users/llm-key-status").status_code == 403
    assert _harness.make_client().get(
        "/admin/users/llm-key-status").status_code in (401, 403)


def case_keys_for_an_unknown_agency_are_a_404():
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200

    assert client.get("/admin/users/no-such-agency/llm-keys").status_code == 404
    r = client.put("/admin/users/no-such-agency/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"],
        "providers": {HOUSE_PROVIDER: "sk-into-the-void"}})
    assert r.status_code == 404, f"{r.status_code} {r.text}"



async def case_seed_a_two_owner_account_and_confirm_it_refuses():
    a = await _seed_user("agency_shared_a", password="secretpw")
    b = await _seed_user("agency_shared_b")
    await _seed_account("acct_two_owner_fix", a, b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-shared-a", "zai": "zai-a"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-shared-b"})
    try:
        await llm_client._tenant_api_key(
            "acct_two_owner_fix", llm_providers.PROVIDERS[HOUSE_PROVIDER])
        assert False, "a two-owner account both hold a key for resolved to one"
    except LLMConfigError as e:
        assert "more than one owner" in str(e), f"unhelpful error: {e}"


async def case_shared_accounts_names_the_account_its_owners_and_who_pays():
    rows = await tenant_keys.shared_accounts(
        ["acct_two_owner_fix", "acct_a", "acct_orphan", "acct_oversight"])
    assert [r["account_id"] for r in rows] == ["acct_two_owner_fix"], rows
    assert rows[0]["owners"] == ["agency_shared_a", "agency_shared_b"], rows[0]
    assert rows[0]["nickname"] == "acct_two_owner_fix"
    assert rows[0]["pays"] == {"zai": "agency_shared_a"}, rows[0]
    assert rows[0]["contested"] == [HOUSE_PROVIDER], rows[0]



async def case_ownership_transfer_bills_the_new_owner_on_the_very_next_call():
    a = await _seed_user("agency_transfer_from")
    b = await _seed_user("agency_transfer_to")
    await _seed_account("acct_transferred", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-old-owner"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-new-owner"})

    assert await _bearer_for("acct_transferred") == "sk-old-owner"

    async with get_session() as s:
        await s.execute(sa_delete(UserAccount).where(
            UserAccount.user_id == a,
            UserAccount.account_id == "acct_transferred",
        ))
        s.add(UserAccount(user_id=b, account_id="acct_transferred"))

    assert await _bearer_for("acct_transferred") == "sk-new-owner", \
        "the transferred account still billed its previous owner's key"


async def case_one_purpose_may_spend_the_deployments_own_money():
    owner = await _seed_user("agency_no_keys_at_all")
    await _seed_account("acct_keyless", owner)

    real = llm_providers._api_key
    llm_providers._api_key = lambda env: (
        "sk-deployment-help" if env == "HELP_ASSISTANT_DEEPSEEK_KEY" else "")
    try:
        assert await _bearer_for("acct_keyless", "help_assistant") == \
            "sk-deployment-help"

        for purpose in ("gen_info", "autoreply", "help_assistant_v2", ""):
            try:
                await _bearer_for("acct_keyless", purpose)
                raise AssertionError(
                    f"the deployment's key leaked to purpose={purpose!r}")
            except LLMConfigError:
                pass
    finally:
        llm_providers._api_key = real

    try:
        await _bearer_for("acct_keyless", "help_assistant")
        raise AssertionError("an unset fallback must restore the old refusal")
    except LLMConfigError:
        pass


async def case_an_agencys_own_key_still_beats_the_fallback():
    owner = await _seed_user("agency_with_its_own_key")
    await _seed_account("acct_own_key", owner)
    await tenant_keys.set_keys(owner, {HOUSE_PROVIDER: "sk-the-agencys-own"})

    real = llm_providers._api_key
    llm_providers._api_key = lambda env: (
        "sk-deployment-help" if env == "HELP_ASSISTANT_DEEPSEEK_KEY" else "")
    try:
        assert await _bearer_for("acct_own_key", "help_assistant") == \
            "sk-the-agencys-own"
    finally:
        llm_providers._api_key = real


async def case_the_fallback_policy_is_one_reviewable_row():
    import secrets_store

    assert llm_providers._FALLBACK_KEY_ENVS == {
        ("help_assistant", "deepseek"): "HELP_ASSISTANT_DEEPSEEK_KEY",
        ("help_assistant_do", "deepseek"): "HELP_ASSISTANT_DEEPSEEK_KEY",
        ("help_assistant", "anthropic"): "HELP_ASSISTANT_ANTHROPIC_KEY",
    }, llm_providers._FALLBACK_KEY_ENVS

    house_envs = {p.api_key_env for p in llm_providers.PROVIDERS.values()}
    for (purpose, provider), env in llm_providers._FALLBACK_KEY_ENVS.items():
        assert purpose, "the empty purpose must never carry a fallback"
        assert provider in llm_providers.PROVIDERS, provider
        assert env in secrets_store.KNOWN, f"{env} is not offered by Setup → Keys"
        assert env not in house_envs, (
            f"{env} IS a provider's house key — a fallback must be its own "
            f"credential, or this deployment pays for agency SENDING too")


async def case_a_call_with_no_account_bills_the_asker_and_never_the_house():
    keyed = await _seed_user("fresh_agency_with_key")
    await tenant_keys.set_keys(keyed, {HOUSE_PROVIDER: "sk-fresh-own"})
    bare = await _seed_user("fresh_agency_no_key")
    assert _house_key(), "the harness must inject a house key for this to mean anything"

    assert await _bearer_for_agency(keyed) == "sk-fresh-own"

    real = llm_providers._api_key
    llm_providers._api_key = lambda env: (
        "sk-deployment-help" if env == "HELP_ASSISTANT_DEEPSEEK_KEY" else real(env))
    try:
        assert await _bearer_for_agency(bare) == "sk-deployment-help"
        _KeyCapturingClient.calls = 0
        for purpose in ("gen_info", "autoreply", ""):
            try:
                await _bearer_for_agency(bare, purpose)
                raise AssertionError(f"a no-account {purpose!r} call found a key")
            except LLMConfigError:
                pass
        assert _KeyCapturingClient.calls == 0, "a refused call still went out"
    finally:
        llm_providers._api_key = real

    try:
        await _bearer_for_agency(bare)
        raise AssertionError("a keyless agency's no-account call reached a key")
    except LLMConfigError:
        pass

    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose="help_assistant", account_id="acct_x", user_id=keyed)
        raise AssertionError("a call billed to an account AND an agency went out")
    except LLMConfigError:
        pass


async def case_a_call_with_no_account_is_capped_per_agency():
    spent = await _seed_user("fresh_agency_spent")
    other = await _seed_user("fresh_agency_fresh")
    for uid in (spent, other):
        await tenant_keys.set_keys(uid, {HOUSE_PROVIDER: "sk-" + uid[:6]})
    day = datetime.utcnow().strftime("%Y-%m-%d")
    cap_mc = llm_client._DEFAULT_CAP_CENTS * llm_client._MILLICENTS_PER_CENT
    async with get_session() as s:
        s.add(GrokUserDailyCost(day=day, user_id=spent, provider="chat",
                                cost_cents=cap_mc, call_count=40))

    _KeyCapturingClient.calls = 0
    try:
        await _bearer_for_agency(spent)
        raise AssertionError("a spent agency's no-account call went out")
    except LLMCapExceeded:
        pass
    assert _KeyCapturingClient.calls == 0, "the cap refused AFTER sending"

    async with get_session() as s:
        before = await s.scalar(select(GrokDailyCost.call_count).where(
            GrokDailyCost.day == day, GrokDailyCost.account_id.is_(None)))
    assert await _bearer_for_agency(other) == "sk-" + other[:6]
    async with get_session() as s:
        row = await s.get(GrokUserDailyCost, (day, other, "chat"))
        after = await s.scalar(select(GrokDailyCost.call_count).where(
            GrokDailyCost.day == day, GrokDailyCost.account_id.is_(None)))
        assert row is not None and row.call_count == 1, row
        assert 0 <= row.cost_cents < cap_mc, row.cost_cents
        assert after == before, "a no-account call landed on the account rollup"
        await s.execute(sa_delete(User).where(User.id == other))
    async with get_session() as s:
        assert await s.get(GrokUserDailyCost, (day, other, HOUSE_PROVIDER)) is None, \
            "deleting the agency left its spend rows behind"



class _HouseTypesafe:

    def __init__(self, key="ts-house"):
        self.key = key

    def __enter__(self):
        self.saved = llm_providers.typesafe_key
        llm_providers.typesafe_key = lambda: self.key
        return self

    def __exit__(self, *a):
        llm_providers.typesafe_key = self.saved


async def case_typesafe_is_an_agency_key_but_not_a_chat_provider():
    assert "typesafe" not in llm_providers.PROVIDERS, "TypeSafe leaked into the chat registry"
    a = await _seed_user("ts_store")
    await tenant_keys.set_keys(a, {"typesafe": "ts-store-abcd"})
    assert await tenant_keys.get_key(a, "typesafe") == "ts-store-abcd"
    st = await tenant_keys.status(a)
    assert st["typesafe"] == {"set": True, "hint": "••••abcd"}, st
    assert st[HOUSE_PROVIDER]["set"] is False


async def case_typesafe_agency_key_beats_the_house_key():
    a = await _seed_user("ts_agency")
    await _seed_account("acct_ts_agency", a)
    await tenant_keys.set_keys(a, {"typesafe": "ts-agency-a"})
    with _HouseTypesafe():
        assert await tenant_keys.typesafe_key_for("acct_ts_agency") == "ts-agency-a"


async def case_typesafe_no_agency_key_falls_back_to_the_house_key():
    a = await _seed_user("ts_bare")
    await _seed_account("acct_ts_bare", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-ts-bare"})
    await _seed_account("acct_ts_orphan")
    with _HouseTypesafe():
        assert await tenant_keys.typesafe_key_for("acct_ts_bare") == "ts-house"
        assert await tenant_keys.typesafe_key_for("acct_ts_orphan") == "ts-house"
        assert await tenant_keys.typesafe_key_for(None) == "ts-house"
    await tenant_keys.set_keys(a, {"typesafe": "ts-cleared"})
    await tenant_keys.set_keys(a, {"typesafe": ""})
    with _HouseTypesafe(""):
        assert await tenant_keys.typesafe_key_for("acct_ts_bare") == "", "a cleared key still resolved"


async def case_typesafe_never_uses_another_agencys_key():
    a = await _seed_user("ts_owner_a")
    b = await _seed_user("ts_owner_b")
    await _seed_account("acct_ts_of_a", a)
    await _seed_account("acct_ts_of_b", b)
    await tenant_keys.set_keys(a, {"typesafe": "ts-only-a"})
    with _HouseTypesafe():
        assert await tenant_keys.typesafe_key_for("acct_ts_of_b") == "ts-house"
    with _HouseTypesafe(""):
        assert await tenant_keys.typesafe_key_for("acct_ts_of_b") == "", "B's creator got A's key"


async def case_typesafe_shared_account_bills_only_a_sole_keyed_owner():
    a = await _seed_user("ts_share_a")
    b = await _seed_user("ts_share_b")
    await _seed_account("acct_ts_shared", a, b)
    await tenant_keys.set_keys(a, {"typesafe": "ts-share-a"})
    with _HouseTypesafe():
        assert await tenant_keys.typesafe_key_for("acct_ts_shared") == "ts-share-a"
        await tenant_keys.set_keys(b, {"typesafe": "ts-share-b"})
        assert await tenant_keys.typesafe_key_for("acct_ts_shared") == "ts-house", \
            "two keyed owners: picked one instead of the house key"



_WRITER_HOSTS = ("nanogpt", "openrouter")


async def case_seed_the_writer_hosts_owner():
    _UI["writers"] = await _seed_user("agency_writers", password="secretpw")
    st = await tenant_keys.status(_UI["writers"])
    for p in _WRITER_HOSTS:
        assert st[p] == {"set": False, "hint": ""}, (p, st.get(p))


def case_writer_hosts_store_by_put_and_never_read_back():
    client = _harness.make_client()
    r = client.post("/auth/login",
                    json={"username": "agency_writers", "password": "secretpw"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"

    before = client.get("/admin/my-llm-keys")
    assert before.status_code == 200
    for p in _WRITER_HOSTS:
        assert before.json()["providers"][p] == {"set": False, "hint": ""}, before.json()

    raw = {"nanogpt": "ng-writer-key-1234", "openrouter": "or-writer-key-5678"}
    r = client.put("/admin/my-llm-keys", json=raw)
    assert r.status_code == 200, f"save failed: {r.status_code} {r.text}"
    provs = r.json()["providers"]
    assert provs["nanogpt"] == {"set": True, "hint": "••••1234"}, provs["nanogpt"]
    assert provs["openrouter"] == {"set": True, "hint": "••••5678"}, provs["openrouter"]

    got = client.get("/admin/my-llm-keys")
    assert got.status_code == 200
    assert got.json()["providers"]["nanogpt"]["hint"] == "••••1234"
    assert got.json()["providers"]["openrouter"]["hint"] == "••••5678"
    for v in raw.values():
        assert v not in r.text, "the PUT response echoed a raw key"
        assert v not in got.text, "the status read returned a raw key"

    for p, v in raw.items():
        stored = asyncio.run(tenant_keys.get_key(_UI["writers"], p))
        assert stored == v, f"{p} not stored"


def case_the_audit_log_keeps_key_names_never_values():
    import json as _json
    from db.models import Action

    async def _rows():
        async with get_session() as s:
            return (await s.execute(select(Action.action, Action.payload_json).where(
                Action.action.like("PUT /admin/%llm-keys")))).all()
    rows = asyncio.run(_rows())
    acts = {a for a, _ in rows}
    assert "PUT /admin/my-llm-keys" in acts and f"PUT /admin/users/{_MANAGED['agency']}/llm-keys" in acts, acts
    blob = " ".join(p or "" for _, p in rows)
    for raw in ("sk-from-the-ui", "sk-set-by-founder", "ng-writer-key-1234", "or-writer-key-5678",
                os.environ["ADMIN_PASSWORD"]):
        assert raw not in blob, f"audit payload kept {raw!r}: {blob}"
    payloads = [_json.loads(p) for _, p in rows if p]
    assert {"nanogpt": "set", "openrouter": "set"} in payloads, payloads
    assert {"admin_password": "set", "providers": {HOUSE_PROVIDER: "set"}} in payloads, payloads


_harness.run()
