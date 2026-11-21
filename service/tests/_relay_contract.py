"""service/tests/_relay_contract.py — the shared bench for a Phase's Relay route contract test.

Used by test_of_mirror_content_writes.py (Phase 2) and test_go_live_stream.py (Phase 4); each keeps its own
`assert_contract`. On import: seeds the two-Agency bench, stubs the account registry so the seeded Creators resolve
(they have a directory but no session metadata), and logs in Agency A's owner and chatter.

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap `_harness` FIRST, then import this.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import _agency_fixtures as fx
import accounts as account_registry
import employees
import of_client
import server

IDS = fx.seed_two_agencies()
CREATOR = IDS["creator_a"]
_real_get_account = account_registry.get_account
account_registry.get_account = lambda aid: (
    {"id": aid} if aid in (IDS["creator_a"], IDS["creator_b"]) else _real_get_account(aid))
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))


class _Refused:
    status_code = 400
    text = '{"error":{"code":0,"message":"Synthetic refusal"}}'


def fake_of(refuse: bool = False):
    """An OFClient that skips __init__ and records (method, url, json_body) instead of calling OF, a read's (get_json)
    as ("GET", url?params, None); `refuse`: OF answers 400 "Synthetic refusal"."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.user_id = CREATOR
    c.sent = []

    def request_json(method, path, **kw):
        c.sent.append((method, path, kw.get("json_body")))
        if refuse:
            raise of_client.OFAPIError("400", response=_Refused())
        return {"success": True}
    c.request_json = request_json

    def get_json(path, params=None, **_kw):
        return request_json("GET", path + (f"?{urlencode(params)}" if params else ""))
    c.get_json = get_json
    return c


def send(client, method: str, path: str, body, account: str | None, refuse: bool = False):
    """One Relay request with OF faked: (response, the OF calls made)."""
    c = fake_of(refuse)
    # The client loader is faked, not `_get_client`: the Creator is still resolved (and refused) as in production.
    orig = server._load_client
    server._load_client = lambda *_a, **_k: c
    try:
        headers = {"X-Account-Id": account} if account else {}
        r = client.request(method, path, json=body, headers=headers)
    finally:
        server._load_client = orig
    return r, c.sent


def roles(role_id: str, enforce: bool, pages: dict) -> None:
    """Assign chatter_a one role granting `pages`, enforced or not."""
    blob = {"enforce": enforce, "roles": [{"id": role_id, "name": f"Fixture {role_id}", "description": "",
                                            "permissions": pages, "scope": "self"}],
            "assignments": {str(EMP_A): role_id}}
    r = OWNER_A.put("/admin/settings/roles", json=blob)
    assert r.status_code == 200, r.text
