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
    c = fake_of(refuse)
    orig = server._load_client
    server._load_client = lambda *_a, **_k: c
    try:
        headers = {"X-Account-Id": account} if account else {}
        r = client.request(method, path, json=body, headers=headers)
    finally:
        server._load_client = orig
    return r, c.sent


def roles(role_id: str, enforce: bool, pages: dict) -> None:
    blob = {"enforce": enforce, "roles": [{"id": role_id, "name": f"Fixture {role_id}", "description": "",
                                            "permissions": pages, "scope": "self"}],
            "assignments": {str(EMP_A): role_id}}
    r = OWNER_A.put("/admin/settings/roles", json=blob)
    assert r.status_code == 200, r.text
