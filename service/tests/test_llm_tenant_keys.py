#!/usr/bin/env python3
"""One agency = one LLM key set. Two agencies never spend on one credential.

The key a call bills is chosen by WHO OWNS the account it is for, not by which
model it picked — `llm_client._tenant_api_key` resolves the owner through the
existing `user_accounts` join and reads that agency's row from
`user_llm_keys`. These cases pin the four ways that resolution can go wrong,
each of which fails SILENTLY in production if it regresses (a wrong key is
still a valid HTTP request; the wrong person just pays for it):

  1. two agencies must put two different bearers on the wire;
  2. an agency's own key must beat the process-wide house key;
  3. an account with NO owner may still use the house key (there is no tenant
     to leak across) — but an owner WITHOUT a key must fail closed, never
     silently fall through to it;
  4. an account with MORE than one owner must refuse rather than pick a side —
     including when one side is the master, because a granted account belongs
     to the grantor and preferring the non-admin link bills the guest.

Plus the store's own footguns: a masked value must never be stored over a
working key, an unknown provider must not create an unreachable row, and
deleting an agency must destroy its credentials.

Assertions read the OUTBOUND Authorization header via a stubbed transport, so
they check the credential that actually left the process rather than what the
resolver claims — no network, deterministic.

Run: ./venv/bin/python service/tests/test_llm_tenant_keys.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

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
    Account, AccountAiConfig, AccountHealth, GrokCall, Session, User,
    UserAccount, UserLlmKey,
)
from llm_client import LLMConfigError, chat  # noqa: E402

# Every case drives this one model, so every call resolves to deepseek and the
# house key under test is a single env var.
MODEL = "deepseek-v4-flash"
HOUSE_PROVIDER = "deepseek"


# ── Transport stub ────────────────────────────────────────────────────────

class _FakeResp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _KeyCapturingClient:
    """Drop-in for httpx.AsyncClient that records the bearer token chat() put
    on the wire. `calls` counts requests so a fail-closed case can assert that
    NOTHING was sent, not merely that an exception surfaced."""

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
    """The credential chat() actually sent for one account.

    `purpose` is a parameter because one purpose is allowed a credential the
    others are not (`llm_providers._FALLBACK_KEY_ENVS`), and the only honest way
    to test that is the bearer that left the process.
    """
    _KeyCapturingClient.last_bearer = ""
    orig = llm_client.httpx.AsyncClient
    llm_client.httpx.AsyncClient = _KeyCapturingClient
    try:
        await chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                   purpose=purpose, account_id=account_id)
    finally:
        llm_client.httpx.AsyncClient = orig
    return _KeyCapturingClient.last_bearer


# ── Seeding ───────────────────────────────────────────────────────────────

async def _seed_user(username: str, is_admin: bool = False,
                     password: str = "x") -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password=password,
                   is_admin=is_admin))
    return uid


# The roster endpoint scopes "live" to the account REGISTRY, which is a
# directory on disk — no seeded account is ever in it. Report every seeded
# account as registered so these cases exercise the ownership rules rather
# than the filesystem; the registry gate itself is pinned separately by
# `case_a_deleted_model_is_not_live_however_alive_its_rows_look`.
import accounts as _accounts_mod  # noqa: E402


def _register_seeded_accounts(*, live: set[str] | None = None,
                              omit: set[str] | None = None) -> None:
    """Publish the seeded accounts as the REGISTRY the route reads.

    `omit` leaves an account out entirely — that is what deleting a model does,
    and the DB rows it leaves behind are the whole reason the route consults a
    registry at all. `live` narrows which of the rest report a session.
    """
    async def _ids():
        async with get_session() as s:
            return list((await s.execute(select(Account.id))).scalars().all())
    # Resolved NOW, outside the request loop: the replacement is called from
    # inside the handler's event loop, where asyncio.run() would explode.
    ids = [a for a in asyncio.run(_ids()) if a not in (omit or set())]
    _accounts_mod.list_accounts = lambda: [  # type: ignore[assignment]
        {"id": a, "has_session": live is None or a in live} for a in ids
    ]


async def _seed_account(account_id: str, *owner_ids: str) -> None:
    async with get_session() as s:
        if await s.get(Account, account_id) is None:
            s.add(Account(id=account_id, nickname=account_id))
        if await s.get(AccountAiConfig, account_id) is None:
            # A cap high enough that no case here is refused for money reasons.
            s.add(AccountAiConfig(account_id=account_id,
                                  daily_cost_cap_cents=1_000_000))
        for uid in owner_ids:
            s.add(UserAccount(user_id=uid, account_id=account_id))


def _house_key() -> str:
    """The process-wide key the harness injected — what "the house key" means
    in these assertions."""
    return llm_providers.house_key(HOUSE_PROVIDER)


# ── 1. The invariant ──────────────────────────────────────────────────────

async def case_two_agencies_put_two_different_keys_on_the_wire():
    """The whole feature in one case: A's creator bills A's key, B's bills B's."""
    a = await _seed_user("agency_a")
    b = await _seed_user("agency_b")
    await _seed_account("acct_a", a)
    await _seed_account("acct_b", b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-agency-a"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-agency-b"})

    assert await _bearer_for("acct_a") == "sk-agency-a", "agency A billed the wrong key"
    assert await _bearer_for("acct_b") == "sk-agency-b", "agency B billed the wrong key"


async def case_every_account_of_one_agency_shares_that_agencys_key():
    """"One agency, one key set" — the agency's second and third creator use it
    too, with nothing configured per account."""
    a = await _seed_user("agency_multi")
    await _seed_account("acct_multi_1", a)
    await _seed_account("acct_multi_2", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-multi"})

    assert await _bearer_for("acct_multi_1") == "sk-multi"
    assert await _bearer_for("acct_multi_2") == "sk-multi"


async def case_agency_key_beats_the_house_key():
    """The house key is present (the harness exports one) and must lose."""
    a = await _seed_user("agency_beats_house")
    await _seed_account("acct_beats_house", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-mine-not-yours"})

    sent = await _bearer_for("acct_beats_house")
    assert sent == "sk-mine-not-yours", f"expected the agency key, got {sent!r}"
    assert sent != _house_key(), "the house key leaked into a tenant's call"


# ── 2. Fallback boundaries ────────────────────────────────────────────────

async def case_orphan_account_falls_back_to_the_house_key():
    """No owner ⇒ no tenant to leak across. The deployment's own un-linked
    accounts must keep working rather than fail closed."""
    await _seed_account("acct_orphan")
    assert await _bearer_for("acct_orphan") == _house_key()


async def case_blank_account_id_falls_back_to_the_house_key():
    """grok_daily_cost keeps a NULL house-account row, so an empty account id is
    a shape this module already knows. It must resolve to the house key rather
    than blow up in an ownership lookup — the store guards its own input."""
    prov = llm_providers.PROVIDERS[HOUSE_PROVIDER]
    assert await llm_client._tenant_api_key("", prov) == _house_key()
    assert await tenant_keys.owners_of("") == []


async def case_owner_without_a_key_fails_closed_and_sends_nothing():
    """The bug this design exists to prevent: an owner with no key must NOT
    quietly bill the house key. It must also cost no cap slot and no audit
    row — the refusal happens before either."""
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
    """An agency that brought only DeepSeek keeps working on DeepSeek and fails
    closed only on the provider it never configured (model_by_purpose can point
    one purpose at zai while the rest stay on deepseek)."""
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


# ── 3. Owner resolution ───────────────────────────────────────────────────

async def case_a_master_oversight_link_does_not_outrank_the_agency():
    """The shape this deployment actually has: the agency captured the account,
    the master's link was added later for oversight. Every dual-owner account
    here looks like that (agency 07-01, master 07-05, etc). Billing the master
    would charge the FOUNDER for another agency's traffic; refusing would take a
    live account dark for a conflict nobody has. The agency pays."""
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
    """The founder's OWN roster: master is the only link, so master's key is the
    right answer — not the house key, and not a refusal."""
    master = await _seed_user("master_solo", is_admin=True)
    await _seed_account("acct_master_solo", master)
    await tenant_keys.set_keys(master, {HOUSE_PROVIDER: "sk-master-solo"})

    assert await _bearer_for("acct_master_solo") == "sk-master-solo"


async def case_two_owners_bill_the_only_one_with_a_key():
    """The shape this deployment actually had: a duplicate owner with NO key
    beside the real one with every key. Refusing it took a live model dark for
    weeks. When only one owner CAN pay there is nothing to guess — bill them."""
    a = await _seed_user("agency_share_keyed")
    b = await _seed_user("agency_share_bare")
    await _seed_account("acct_two_owners_one_key", a, b)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-share-keyed"})

    owners = await tenant_keys.owners_of("acct_two_owners_one_key")
    assert sorted(owners) == sorted([a, b]), f"both owners not surfaced: {owners}"
    assert await _bearer_for("acct_two_owners_one_key") == "sk-share-keyed", \
        "a shared account with exactly one keyed owner was not billed to them"


async def case_two_owners_with_no_key_anywhere_name_them_both():
    """Neither owner has pasted a key: fail closed as before, but the error
    names both, because either of them can fix it."""
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
    """Cross-granted accounts exist in this codebase's own fixtures. When BOTH
    owners hold a key, "we cannot tell whose money this is" must be an error,
    not whichever row sorts first."""
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
    """Both hold DeepSeek (refused) but only one holds Grok (billed). The
    resolution is per provider because the keys are."""
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


# ── 4. Store footguns ─────────────────────────────────────────────────────

async def case_masked_value_never_overwrites_a_stored_key():
    """The classic settings-form bug: the UI renders `••••a1b2`, the form PUTs
    it back, and a working key becomes the mask. Rejected server-side."""
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
    """A typo'd or renamed provider must 400 on save rather than create a row
    the read path can never find (which would fail over to the house key)."""
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
    """Offboarding must not leave credentials behind. This is CASCADE actually
    firing — it only does because PRAGMA foreign_keys=ON is wired at connect."""
    a = await _seed_user("agency_offboard")
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-offboard"})
    async with get_session() as s:
        await s.execute(sa_delete(User).where(User.id == a))
    assert await tenant_keys.get_key(a, HOUSE_PROVIDER) == "", \
        "an offboarded agency's key survived the user row"


# ── 5. The HTTP surface ───────────────────────────────────────────────────
#
# Seeding is its own async case because the request cases below drive a
# TestClient, which needs to own the event loop.

_UI: dict[str, str] = {}


async def case_seed_the_ui_owner():
    _UI["owner"] = await _seed_user("agency_ui", password="secretpw")
    _UI["other"] = await _seed_user("agency_ui_bystander")
    await tenant_keys.set_keys(_UI["other"], {HOUSE_PROVIDER: "sk-bystander"})


def case_endpoints_require_a_signed_in_owner():
    """Anonymous callers get 401, not a house-key write. (A Chatter session
    resolves to no User here for the same reason and takes the same branch.)"""
    client = _harness.make_client()
    assert client.get("/admin/my-llm-keys").status_code == 401
    r = client.put("/admin/my-llm-keys", json={HOUSE_PROVIDER: "sk-anon"})
    assert r.status_code == 401, f"anonymous write returned {r.status_code}"


def case_signed_in_owner_round_trips_only_their_own_key():
    """A save lands on the signed-in owner's row and nowhere else — the write
    path never takes a user id from the caller, so there is no cross-tenant
    write to defend against, and this pins that."""
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
    """Defence in depth for the settings-form footgun: even if a UI round-trips
    its own placeholder, the server refuses it instead of storing the mask."""
    client = _harness.make_client()
    r = client.post("/auth/login",
                    json={"username": "agency_ui", "password": "secretpw"})
    assert r.status_code == 200
    r = client.put("/admin/my-llm-keys", json={HOUSE_PROVIDER: "••••e-ui"})
    assert r.status_code == 400, f"mask accepted: {r.status_code} {r.text}"
    stored = asyncio.run(tenant_keys.get_key(_UI["owner"], HOUSE_PROVIDER))
    assert stored == "sk-from-the-ui", f"key damaged by the rejected write: {stored!r}"


# ── helpers ───────────────────────────────────────────────────────────────

async def _grok_call_count() -> int:
    async with get_session() as s:
        return len((await s.execute(select(GrokCall.id))).all())

# ── 6. The founder setting an agency's keys for them ──────────────────────
#
# The managed flow: an agency connects its model and the founder does the rest.
# `/admin/my-llm-keys` writes only the signed-in owner's row and impersonation
# is read-only, so without this an agency that never pasted a key could not be
# fixed from any screen.

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

    # ...and the agency's models now bill exactly that key.
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
    """A masked hint still leaks the last four characters, so the READ is gated
    too — an agency may only ever see its own row."""
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "agency_managed", "password": "secretpw"}).status_code == 200
    uid = _MANAGED["master"]
    assert client.get(f"/admin/users/{uid}/llm-keys").status_code == 403
    r = client.put(f"/admin/users/{uid}/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"],
        "providers": {HOUSE_PROVIDER: "sk-hijack"}})
    assert r.status_code == 403, f"{r.status_code} {r.text}"


def case_key_status_roster_ranks_agencies_with_a_live_model_first():
    """The founder's screen needs "who is worth a key", not "who exists".

    Two thirds of this deployment's accounts have a DEAD session, and an
    account OF has rejected sends nothing — so a key pasted under its owner
    buys nothing until the session is re-captured. This pins the two facts the
    screen sorts and filters on, and that provider NAMES travel without values.
    """
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
            # Only the second has been probed and found dead.
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
    # The master holds no links of its own here, so it is asked for nothing.
    assert by_name["roster_master"]["live_accounts"] == 0, by_name["roster_master"]
    assert by_name["roster_live"]["providers_set"] == [HOUSE_PROVIDER]
    assert by_name["roster_dead"]["providers_set"] == []
    names = [a["username"] for a in r.json()["agencies"]]
    assert names.index("roster_live") < names.index("roster_dead"), names


def case_the_roster_counts_what_is_BILLED_not_what_is_linked():
    """The screen has to resolve ownership the way the money path does.

    A master holding an oversight link on an agency's model would otherwise
    read as "1 live — needs a key" under its OWN row, while every one of those
    calls bills the agency and nothing would ever spend the master's
    credential. And a model two agencies both claim bills NEITHER — it is
    refused outright, so no key fixes it and it must not be counted as one
    that would. And a model two agencies claim where only ONE has a key bills
    that one — counted under them, and not blocked.
    """
    master = asyncio.run(_seed_user("billed_master", is_admin=True, password="secretpw"))
    agency = asyncio.run(_seed_user("billed_agency", password="secretpw"))
    rival = asyncio.run(_seed_user("billed_rival", password="secretpw"))
    solo = asyncio.run(_seed_user("billed_solo_master_acct", password="secretpw"))
    assert solo
    asyncio.run(tenant_keys.set_keys(agency, {HOUSE_PROVIDER: "sk-billed-agency"}))
    asyncio.run(tenant_keys.set_keys(rival, {HOUSE_PROVIDER: "sk-billed-rival"}))

    # 1. agency owns it, master merely watches  -> bills the AGENCY
    asyncio.run(_seed_account("acct_billed_watched", agency, master))
    # 2. master is the only link                -> bills the MASTER
    asyncio.run(_seed_account("acct_billed_master_only", master))
    # 3. two KEYED agencies claim it            -> bills NOBODY
    asyncio.run(_seed_account("acct_billed_disputed", agency, rival))
    # 4. shared with a keyless duplicate owner  -> bills the one WITH a key
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

    # The oversight link does NOT inflate the master; its solo link is all it owns.
    assert by_name["billed_master"]["live_accounts"] == 1, by_name["billed_master"]
    assert by_name["billed_master"]["blocked_accounts"] == 0, by_name["billed_master"]
    # The agency is billed for the watched model and the one it shares with a
    # keyless duplicate, and NOT for the disputed one.
    assert by_name["billed_agency"]["live_accounts"] == 2, by_name["billed_agency"]
    # ...but the dispute is reported rather than silently dropped.
    assert by_name["billed_agency"]["blocked_accounts"] == 1, by_name["billed_agency"]
    assert by_name["billed_rival"]["live_accounts"] == 0, by_name["billed_rival"]
    assert by_name["billed_rival"]["blocked_accounts"] == 1, by_name["billed_rival"]
    # The keyless duplicate owns nothing and is blocked on nothing.
    assert by_name["billed_bare_dup"]["live_accounts"] == 0, by_name["billed_bare_dup"]
    assert by_name["billed_bare_dup"]["blocked_accounts"] == 0, by_name["billed_bare_dup"]


def case_two_masters_on_one_model_bill_nobody_on_the_roster_too():
    """The shape the roster used to get wrong on its own.

    `billable_owners` drops masters only when a non-master link exists, so two
    MASTER links and no agency link is a genuine dispute and `llm_client`
    refuses it. The roster's old inline copy of the rule looked only at
    non-master links, fell through to `owners[0]` and billed whichever master
    the join happened to return first — showing a model as live and keyable
    that no key can ever unblock. This case is the reason the rule has one
    definition: it passes only while the screen resolves ownership through
    `billable_owners`.
    """
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
    """Deleting a model leaves every DB row behind.

    The `accounts` row stays, the `user_accounts` link stays, a `sessions` row
    stays flagged `is_latest`, and nothing sets `session_dead_at` — the model is
    simply gone from the REGISTRY the operator sees. Counting from the tables
    alone therefore reports a model deleted days ago as live and sends the
    founder to buy a key for it. That is not hypothetical: it happened on
    2026-08-20 to an account deleted on 08-14, and its owner was keyed for
    nothing.

    Driven through the ROUTE, not the store. An earlier version of this case
    called `key_overview` directly and stayed green with the route's registry
    wiring deleted — it pinned the argument and not the fix.
    """
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

    # Both in the registry: both live, both owned.
    _register_seeded_accounts()
    both = {a["username"]: a
            for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    assert both["registry_agency"]["live_accounts"] == 2, both["registry_agency"]
    assert both["registry_agency"]["accounts"] == 2, both["registry_agency"]

    # One deleted: gone from BOTH counts, however alive its rows still look.
    _register_seeded_accounts(omit={"acct_deleted_from_disk"})
    after = {a["username"]: a
             for a in client.get("/admin/users/llm-key-status").json()["agencies"]}
    assert after["registry_agency"]["live_accounts"] == 1, after["registry_agency"]
    assert after["registry_agency"]["accounts"] == 1, \
        "a deleted model still counted as owned — 'of N models' quotes a model " \
        "the operator cannot see"


def case_a_registered_model_with_no_session_is_owned_but_not_live():
    """`accounts` is what the agency HAS, `live_accounts` is what can talk.

    The registry answers both — presence, and `has_session`. The `sessions`
    TABLE cannot: its only writer is the one-shot legacy importer, so it is
    frozen and says nothing about a capture made since.
    """
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
    """Credentials resolve PER PROVIDER, so "has some key" is not the question.

    An agency holding only a DeepInfra key has a key and still fails every chat
    reply closed. `missing_providers` is what the badge must act on.
    """
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
    """It lists every tenant on the deployment, so it is master-only like the
    per-agency read beside it."""
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "roster_live", "password": "secretpw"}).status_code == 200
    assert client.get("/admin/users/llm-key-status").status_code == 403
    assert _harness.make_client().get(
        "/admin/users/llm-key-status").status_code in (401, 403)


def case_keys_for_an_unknown_agency_are_a_404():
    """A mistyped or already-deleted id must not read back as a working agency.

    Without the check the GET returns every provider unset — the exact shape of
    a real agency that has not pasted a key, so the founder "fixes" a row that
    belongs to nobody — and the PUT behind it dies on the `user_llm_keys`
    foreign key as a 500. Same 404 the grant endpoints give.
    """
    client = _harness.make_client()
    assert client.post("/auth/login", json={
        "username": "master_manager", "password": "secretpw"}).status_code == 200

    assert client.get("/admin/users/no-such-agency/llm-keys").status_code == 404
    r = client.put("/admin/users/no-such-agency/llm-keys", json={
        "admin_password": os.environ["ADMIN_PASSWORD"],
        "providers": {HOUSE_PROVIDER: "sk-into-the-void"}})
    assert r.status_code == 404, f"{r.status_code} {r.text}"


# ── 7. Two owners: the refusal and the signal ─────────────────────────────
#
# The refusal is correct but invisible — the operator's only clue is a log line
# on a box nobody is tailing. These pin the whole loop: it refuses when both
# owners hold a key, the UI is told which accounts, who shares them and who
# pays for what.

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
    """What the Setup card renders. Without it the refusal is a log line."""
    rows = await tenant_keys.shared_accounts(
        ["acct_two_owner_fix", "acct_a", "acct_orphan", "acct_oversight"])
    # acct_oversight has two links too, but one is a master's — not shared,
    # and reporting it would cry wolf on every account the founder can see.
    assert [r["account_id"] for r in rows] == ["acct_two_owner_fix"], rows
    assert rows[0]["owners"] == ["agency_shared_a", "agency_shared_b"], rows[0]
    assert rows[0]["nickname"] == "acct_two_owner_fix"
    # Same rule as the money path: zai has one holder and bills them,
    # deepseek has two and is refused, the rest nobody has set.
    assert rows[0]["pays"] == {"zai": "agency_shared_a"}, rows[0]
    assert rows[0]["contested"] == [HOUSE_PROVIDER], rows[0]


# ── 8. The reason there is no cache ───────────────────────────────────────

async def case_ownership_transfer_bills_the_new_owner_on_the_very_next_call():
    """An ownership transfer moves an account between agencies by deleting
    one `user_accounts` row and inserting another. The very next LLM call must
    bill the NEW owner — that is the whole argument against caching this lookup,
    and without this case a future perf pass could add a TTL cache and keep all
    the other assertions green while the old owner pays."""
    a = await _seed_user("agency_transfer_from")
    b = await _seed_user("agency_transfer_to")
    await _seed_account("acct_transferred", a)
    await tenant_keys.set_keys(a, {HOUSE_PROVIDER: "sk-old-owner"})
    await tenant_keys.set_keys(b, {HOUSE_PROVIDER: "sk-new-owner"})

    assert await _bearer_for("acct_transferred") == "sk-old-owner"

    # Exactly what a transfer does, in one session.
    async with get_session() as s:
        await s.execute(sa_delete(UserAccount).where(
            UserAccount.user_id == a,
            UserAccount.account_id == "acct_transferred",
        ))
        s.add(UserAccount(user_id=b, account_id="acct_transferred"))

    assert await _bearer_for("acct_transferred") == "sk-new-owner", \
        "the transferred account still billed its previous owner's key"


async def case_one_purpose_may_spend_the_deployments_own_money():
    """THE ONE HOLE in the fail-closed gate, and it is a different credential
    rather than a wider house key.

    The gate makes "where do I paste my API key?" unanswerable exactly when it
    is asked: a brand-new agency, or one whose key expired, cannot use the
    in-product help bot to find out where the key box is. That one purpose —
    which sends no fan anything — may fall through to a credential this
    deployment sets aside for it. Everything else on the same account, and the
    same purpose on any other provider, still fails closed.

    Asserted on the OUTBOUND bearer, like every case in this file: a policy that
    only looks right in the resolver is not the thing that bills anyone."""
    owner = await _seed_user("agency_no_keys_at_all")
    await _seed_account("acct_keyless", owner)          # …and never set_keys

    real = llm_providers._api_key
    llm_providers._api_key = lambda env: (
        "sk-deployment-help" if env == "HELP_ASSISTANT_DEEPSEEK_KEY" else "")
    try:
        assert await _bearer_for("acct_keyless", "help_assistant") == \
            "sk-deployment-help"

        # Not for its sending, however plausible the purpose reads.
        for purpose in ("gen_info", "autoreply", "help_assistant_v2", ""):
            try:
                await _bearer_for("acct_keyless", purpose)
                raise AssertionError(
                    f"the deployment's key leaked to purpose={purpose!r}")
            except LLMConfigError:
                pass
    finally:
        llm_providers._api_key = real

    # …and with the credential unset, nothing changed: the gate closes again.
    try:
        await _bearer_for("acct_keyless", "help_assistant")
        raise AssertionError("an unset fallback must restore the old refusal")
    except LLMConfigError:
        pass


async def case_an_agencys_own_key_still_beats_the_fallback():
    """The fallback is a LAST resort, not a shortcut. An agency that brought its
    own DeepSeek key must pay for its own help-bot answers — otherwise the
    deployment quietly picks up the bill for every tenant that has one."""
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
    """The policy is a map, so it can be read in one go — and every row has to
    be wired to something real at both ends: a provider that exists, and a
    `secrets_store` field an operator can actually fill. Two hand-kept copies of
    a key id is how a Setup → Keys box ends up writing where nothing reads."""
    import secrets_store

    assert llm_providers._FALLBACK_KEY_ENVS == {
        ("help_assistant", "deepseek"): "HELP_ASSISTANT_DEEPSEEK_KEY",
    }, llm_providers._FALLBACK_KEY_ENVS

    house_envs = {p.api_key_env for p in llm_providers.PROVIDERS.values()}
    for (purpose, provider), env in llm_providers._FALLBACK_KEY_ENVS.items():
        assert purpose, "the empty purpose must never carry a fallback"
        assert provider in llm_providers.PROVIDERS, provider
        assert env in secrets_store.KNOWN, f"{env} is not offered by Setup → Keys"
        assert env not in house_envs, (
            f"{env} IS a provider's house key — a fallback must be its own "
            f"credential, or this deployment pays for agency SENDING too")


_harness.run()
