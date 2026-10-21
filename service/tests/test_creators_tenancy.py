#!/usr/bin/env python3
"""Creators tenancy check: Creator linking and proxy data stay inside their Agency
(docs/spec/phase-05-remaining-parity-gaps.md, item 9; ticket 39, stories 56, 57).

Nothing here is built; this file only shows what the Relay already does. With the shared two-Agency fixture,
Agency A's owner holds a private proxy, and A's Creator is bound to a shared default proxy (`user_id` null,
visible to every Agency); B's Creator is on B's private proxy. Then:

  - Owner B's `GET /admin/proxies` holds none of A's proxies (label, host or password anywhere in the body) and
    none of A's Creator nicknames or ids in either Creator field: the `accounts` picker list and each proxy's
    `assigned_accounts`, including the shared proxy A's Creator is bound to.
  - Owner B's `POST /admin/proxies/assign` naming A's Creator is refused, 403 or 404 (story 55 allows either),
    whether B names B's own proxy, the shared proxy or A's proxy, and the registry file is byte-for-byte unchanged.
  - A caller with no session gets 401 on both routes (story 55; ticket 40), and the registry is unchanged.
  - `GET /health?all_accounts=1` (round 2, ticket 12, story 37a): Owner B's answer holds none of A's Creator
    ids or nicknames, a chatter's answer holds only the Creators in their access union, no row in any answer
    carries `proxy.url` (the proxy's username and password), and a signed-out caller gets 401 (under the
    ALLOW_ANONYMOUS_ADMIN escape hatch it gets every row, still without `proxy.url`). The probe's
    client is a fake whose proxy URL holds obviously fake credentials; no OnlyFans call is made.

Positive controls keep the negatives honest: Owner A sees A's proxy, and A's Creator nickname in both Creator
fields (the shared proxy's `assigned_accounts` included), and Owner A's own assign succeeds and changes the
registry, so B's refusals are not a route that refuses everyone. The write control runs last (cases run in
definition order), so the negatives see only the seeded state.

The proxy registry is repointed at a `tempfile.mkdtemp` file, as `test_proxy_paste.py` does; the real registry
file is never read or written. Every label, host and password is fake (`.invalid` hosts).

Run: ./venv/bin/python service/tests/test_creators_tenancy.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import os  # noqa: E402
import tempfile  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import proxies as proxy_registry  # noqa: E402

proxy_registry.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="creators_tenancy_proxies_")) / "proxies.json"

IDS = fx.seed_two_agencies()
CREATOR_A, CREATOR_B = IDS["creator_a"], IDS["creator_b"]
NICK_A, NICK_B = "Tenancy Creator Alpha", "Tenancy Creator Beta"
account_registry.upsert_account(CREATOR_A, nickname=NICK_A)
account_registry.upsert_account(CREATOR_B, nickname=NICK_B)

PROXY_A = {"label": "agency-a-private", "host": "proxy-a.invalid", "port": 8001,
           "username": "agency-a-user", "password": "agency-a-secret-pw"}
PROXY_B = {"label": "agency-b-private", "host": "proxy-b.invalid", "port": 8002,
           "username": "agency-b-user", "password": "agency-b-secret-pw"}
SHARED = {"label": "shared-default", "host": "proxy-shared.invalid", "port": 8003,
          "username": None, "password": None}

# A's private proxy serves nobody; A's Creator sits on the shared default; B's proxy serves B's Creator.
proxy_registry.upsert({**PROXY_A, "user_id": IDS["agency_a_owner"]})
proxy_registry.upsert({**SHARED, "user_id": None})
proxy_registry.upsert({**PROXY_B, "user_id": IDS["agency_b_owner"]})
proxy_registry.assign_account(SHARED["label"], CREATOR_A)
proxy_registry.assign_account(PROXY_B["label"], CREATOR_B)

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")

import server  # noqa: E402 — imported by the logins above; named here for the health probe's seam

FAKE_PROXY_URL = "http://user:pass@203.0.113.10:8001"


def _list(client) -> tuple[dict, str]:
    r = client.get("/admin/proxies")
    assert r.status_code == 200, f"GET /admin/proxies: {r.status_code} {r.text}"
    return r.json(), r.text


def _assign(client, label: str, account_id: str):
    return client.post("/admin/proxies/assign", json={"label": label, "account_id": account_id})


def case_owner_a_sees_own_proxy_and_creator():
    """Positive control: the fields the negatives search do carry A's data for A."""
    body, _ = _list(OWNER_A)
    labels = {p["label"] for p in body["proxies"]}
    assert PROXY_A["label"] in labels, labels
    assert PROXY_B["label"] not in labels, labels
    shared = next(p for p in body["proxies"] if p["label"] == SHARED["label"])
    assert NICK_A in {a["nickname"] for a in shared["assigned_accounts"]}, shared["assigned_accounts"]
    assert NICK_A in {a["nickname"] for a in body["accounts"]}, body["accounts"]


def case_owner_b_list_holds_none_of_agency_a():
    body, text = _list(OWNER_B)
    labels = {p["label"] for p in body["proxies"]}
    assert PROXY_A["label"] not in labels, f"B sees A's proxy: {labels}"
    assert PROXY_B["label"] in labels and SHARED["label"] in labels, labels
    for needle in (PROXY_A["label"], PROXY_A["host"], PROXY_A["username"], PROXY_A["password"]):
        assert needle not in text, f"A's proxy field {needle!r} appears in B's list"
    # Either Creator field: the picker list and every proxy's assigned_accounts (the shared one included).
    assert NICK_A not in {a.get("nickname") for a in body["accounts"]}, body["accounts"]
    assert CREATOR_A not in {a.get("id") for a in body["accounts"]}, body["accounts"]
    for p in body["proxies"]:
        for a in p["assigned_accounts"]:
            assert a.get("nickname") != NICK_A and a.get("id") != CREATOR_A, f"{p['label']}: {a}"
    assert NICK_A not in text, "A's Creator nickname appears in B's list"
    assert CREATOR_A not in text, "A's Creator id appears in B's list"
    assert NICK_B in {a.get("nickname") for a in body["accounts"]}, body["accounts"]


def case_owner_b_cannot_assign_to_agency_a_creator():
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    for label in (PROXY_B["label"], SHARED["label"], PROXY_A["label"]):
        r = _assign(OWNER_B, label, CREATOR_A)
        assert r.status_code in (403, 404), f"B assigns A's Creator to {label}: {r.status_code} {r.text}"
        assert proxy_registry.REGISTRY_PATH.read_bytes() == before, f"B's assign to {label} wrote the registry"
        assert NICK_A not in r.text, f"refusal for {label} names A's Creator: {r.text}"
    assert proxy_registry.get_for_account(CREATOR_A)["label"] == SHARED["label"], "seeded binding moved"


def case_signed_out_is_401_on_list_and_assign():
    """Story 55: both routes answer 401 to a caller with no session, and the refused assign writes nothing."""
    anon = _harness.make_client()
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    r = anon.get("/admin/proxies")
    assert r.status_code == 401, f"signed out GET: {r.status_code} {r.text}"
    r = _assign(anon, PROXY_A["label"], CREATOR_A)
    assert r.status_code == 401, f"signed out assign: {r.status_code} {r.text}"
    assert proxy_registry.REGISTRY_PATH.read_bytes() == before, "a signed-out assign wrote the registry"


class _FakeProbeClient:
    """Enough OFClient surface for one health row: `me()` and the proxy pair. Never touches the network."""

    def __init__(self, aid: str):
        self.account_id = aid
        self.proxy_label = f"probe-{aid}"
        self.proxy_url = FAKE_PROXY_URL

    def me(self) -> dict:
        return {"id": int(self.account_id), "name": f"probe-name-{self.account_id}"}


@contextmanager
def _probed_fleet():
    """Both Creators read as having a session (a `latest.json` in the fixture's temp sessions tree) and their
    probe loads the fake client, so every row carries a `proxy` the clamp must strip. Undone on exit, so the
    write control below sees the seeded state."""
    marks = [account_registry.ACCOUNTS_DIR / aid / "latest.json" for aid in (CREATOR_A, CREATOR_B)]
    for m in marks:
        m.write_text("{}")
    old_load = server._load_client
    server._load_client = _FakeProbeClient
    server.relay_coalesce.reset_for_tests()
    try:
        yield
    finally:
        server._load_client = old_load
        server.relay_coalesce.reset_for_tests()
        for m in marks:
            m.unlink()


def _health_all(client) -> tuple[dict, str]:
    r = client.get("/health?all_accounts=1")
    assert r.status_code == 200, f"GET /health?all_accounts=1: {r.status_code} {r.text}"
    return r.json(), r.text


def _assert_no_proxy_url(body: dict, text: str, who: str) -> None:
    for row in body["accounts"]:
        assert "url" not in (row.get("proxy") or {}), f"{who}: row {row.get('account_id')} carries proxy.url"
    assert FAKE_PROXY_URL not in text and "user:pass@" not in text, f"{who}: the proxy URL is in the body"


def case_owner_a_health_all_holds_own_creator():
    """Positive control: A's answer holds A's Creator, probed (so it had a proxy to strip), and no proxy URL."""
    with _probed_fleet():
        body, text = _health_all(OWNER_A)
    rows = {r["account_id"]: r for r in body["accounts"]}
    assert set(rows) == {CREATOR_A}, rows
    assert rows[CREATOR_A]["nickname"] == NICK_A, rows[CREATOR_A]
    assert rows[CREATOR_A]["ok"] is True and rows[CREATOR_A]["proxy"]["label"] == f"probe-{CREATOR_A}", rows
    _assert_no_proxy_url(body, text, "Owner A")


def case_owner_b_health_all_holds_none_of_agency_a():
    with _probed_fleet():
        body, text = _health_all(OWNER_B)
    ids = {r["account_id"] for r in body["accounts"]}
    assert ids == {CREATOR_B}, f"B's health answer holds {ids}"
    assert CREATOR_A not in text, "A's Creator id appears in B's health answer"
    assert NICK_A not in text, "A's Creator nickname appears in B's health answer"
    _assert_no_proxy_url(body, text, "Owner B")


def case_a_chatter_health_all_holds_only_their_access_union():
    """chatter_a is linked to Agency A only; chatter_ab to both, so its union is both Creators."""
    for name, want in (("chatter_a", {CREATOR_A}), ("chatter_ab", {CREATOR_A, CREATOR_B})):
        with _probed_fleet():
            body, text = _health_all(fx.login_chatter(name))
        ids = {r["account_id"] for r in body["accounts"]}
        assert ids == want, f"{name}'s health answer holds {ids}, want {want}"
        _assert_no_proxy_url(body, text, name)
    with _probed_fleet():
        _, text = _health_all(fx.login_chatter("chatter_a"))
    assert CREATOR_B not in text and NICK_B not in text, "chatter_a's health answer names Agency B's Creator"


def case_signed_out_is_401_on_health_all():
    with _probed_fleet():
        r = _harness.make_client().get("/health?all_accounts=1")
    assert r.status_code == 401, f"signed out health_all: {r.status_code} {r.text}"
    assert CREATOR_A not in r.text and CREATOR_B not in r.text, r.text


def case_escape_hatch_is_unclamped_but_still_has_no_proxy_url():
    """ALLOW_ANONYMOUS_ADMIN=1 (the lockout revert `/admin/*` also honours): a signed-out caller gets every row,
    and still no proxy URL. The flag is read per call, so it is set only around this one request."""
    old = os.environ.get("ALLOW_ANONYMOUS_ADMIN")
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        with _probed_fleet():
            body, text = _health_all(_harness.make_client())
    finally:
        if old is None:
            os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)
        else:
            os.environ["ALLOW_ANONYMOUS_ADMIN"] = old
    assert {r["account_id"] for r in body["accounts"]} == {CREATOR_A, CREATOR_B}, body
    _assert_no_proxy_url(body, text, "escape hatch")


def case_owner_a_moves_own_creator_to_own_proxy():
    """Positive control for the write, last so the negatives above see only the seeded state: A's own assign
    succeeds, changes the registry, and moves A's Creator from the shared proxy onto A's private proxy."""
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    r = _assign(OWNER_A, PROXY_A["label"], CREATOR_A)
    assert r.status_code == 200, f"A assigns own Creator: {r.status_code} {r.text}"
    assert proxy_registry.REGISTRY_PATH.read_bytes() != before, "A's assign wrote nothing"
    assert proxy_registry.get_for_account(CREATOR_A)["label"] == PROXY_A["label"]


_harness.run()
