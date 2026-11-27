#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from fastapi import APIRouter, Request  # noqa: E402
from sqlalchemy import delete  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import employees  # noqa: E402
import account_page  # noqa: E402
import leak_tracker  # noqa: E402
import leak_tracker_api  # noqa: E402
import runtime_switches  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import RuntimeSwitch, UserLlmKey  # noqa: E402

TESTS = Path(__file__).resolve().parent
APPLIED = "/admin/settings/applied"
PROBE = "/admin/leaks/_key-probe"

IDS = fx.seed_two_agencies()

_probe = APIRouter()


@_probe.get(PROBE)
async def _key_probe(request: Request):
    await leak_tracker.require_gates(request, need_key=True)
    return {"ok": True}


server.app.include_router(_probe)


def _no_tracker(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no tracker in the gates test")


def _mirror(chatter: str, owner: str) -> int:
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS[chatter], IDS[owner], display_name=chatter, color="#bbbbbb"))
    assert emp is not None
    return emp


EMP_A = _mirror("chatter_a", "agency_a_owner")
EMP_AB_A = _mirror("chatter_ab", "agency_a_owner")
EMP_AB_B = _mirror("chatter_ab", "agency_b_owner")

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_AB = fx.login_chatter("chatter_ab")

ON = {"LEAK_TRACKER_URL": "http://127.0.0.1:9", "LEAK_TRACKER_ENABLED": "1", "OI_CELL_MAP": None}


@contextmanager
def _env(**values: str | None):
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


async def _no_live_session(account_id: str) -> None:
    return None


@contextmanager
def _on(**over: str | None):
    real, real_me = httpx.AsyncClient, account_page.of_me
    leak_tracker.httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(_no_tracker)})
    account_page.of_me = _no_live_session
    try:
        with _env(**{**ON, **over}):
            yield
    finally:
        leak_tracker.httpx.AsyncClient = real
        account_page.of_me = real_me


def _set_key(agency: str, key: str | None) -> None:
    async def _write():
        async with get_session() as s:
            await s.execute(delete(UserLlmKey).where(UserLlmKey.user_id == IDS[agency],
                                                     UserLlmKey.provider == "leak_tracker"))
            if key is not None:
                s.add(UserLlmKey(user_id=IDS[agency], provider="leak_tracker", api_key=key,
                                 updated_at=datetime.utcnow()))
    asyncio.run(_write())


def _roles(assignments: dict[int, str], roles: list[dict] | None = None, enforce: bool = True) -> dict:
    return {"enforce": enforce, "roles": roles or [], "assignments": {str(k): v for k, v in assignments.items()}}


def _agency(agency: str, *, flag: bool = True, key: str | None = "fixture-tracker-key",
            roles: dict | None = None) -> None:
    fx.store_blob(IDS[agency], "flags", {"leak_tracker": flag})
    fx.store_blob(IDS[agency], "roles", roles or _roles({}))
    _set_key(agency, key)


def _routes(client, headers: dict | None = None, creator: str = "creator_a") -> list:
    out = []
    for route in leak_tracker_api.router.routes:
        path = re.sub(r"\{[^}]+\}", IDS[creator], route.path)
        for method in sorted(route.methods):
            out.append((f"{method} {route.path}", client.request(method, path, headers=headers or {}, json={})))
    out.append((f"GET {PROBE}", client.get(PROBE, headers=headers or {})))
    return out


def _all_404(client, label: str, headers: dict | None = None) -> None:
    for name, r in _routes(client, headers):
        assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), f"{label}: {name} -> {r.status_code} {r.text}"


REFUSED = {"PUT /admin/leaks/key": {"owner": 422, "writer": 403, "reader": 403},
           "PUT /admin/leaks/watches/{account_id}": {"owner": 422, "writer": 422, "reader": 403},
           "POST /admin/leaks/watches/{account_id}/tracking": {"owner": 422, "writer": 422, "reader": 403},
           "POST /admin/leaks/watches/{account_id}/offer-snooze": {"owner": 422, "writer": 422, "reader": 403},
           "DELETE /admin/leaks/watches/{account_id}": {"owner": 200, "writer": 200, "reader": 403},
           "GET /admin/leaks/watches/{account_id}/offer": {"owner": 404, "writer": 404, "reader": 404},
           "GET /admin/leaks/offer-video/{part}": {"owner": 404, "writer": 404, "reader": 404}}
SNOOZE = "POST /admin/leaks/watches/{account_id}/offer-snooze"


def _all_reached(client, label: str, headers: dict | None = None, *, writes: bool = True,
                 creator: str = "creator_a", offers: bool = True) -> None:
    who = "owner" if client in (OWNER_A, OWNER_B) else "writer" if writes else "reader"
    for name, r in _routes(client, headers, creator):
        want = REFUSED[name][who] if name in REFUSED else 200
        if name == SNOOZE and who == "writer" and not offers:
            want = 403
        assert r.status_code == want, f"{label}: {name} -> {r.status_code} {r.text}, want {want}"


def _flag(client, headers: dict | None = None) -> bool:
    r = client.get(APPLIED, headers=headers or {})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()["flags"]["leak_tracker"]


def _reset() -> None:
    _agency("agency_a_owner")
    _agency("agency_b_owner", flag=False, key=None)


def case_every_gate_on_answers_and_reports_the_flag():
    _reset()
    assert [p for p in leak_tracker_api.router.routes if not p.path.startswith("/admin/leaks/")] == []
    with _on():
        _all_reached(OWNER_A, "every gate on")
        assert _flag(OWNER_A) is True


def case_default_off_with_no_env():
    _reset()
    with _env(LEAK_TRACKER_URL=None, LEAK_TRACKER_ENABLED=None, OI_CELL_MAP=None):
        _all_404(OWNER_A, "no env")
        assert _flag(OWNER_A) is False


def case_deployment_gate_off_is_404_everywhere():
    _reset()
    for label, over in [
        ("url unset", {"LEAK_TRACKER_URL": None}),
        ("url blank", {"LEAK_TRACKER_URL": "  "}),
        ("switch unset", {"LEAK_TRACKER_ENABLED": None}),
        ("switch 0", {"LEAK_TRACKER_ENABLED": "0"}),
        ("plain http off loopback", {"LEAK_TRACKER_URL": "http://tracker.example.test"}),
        ("not a url", {"LEAK_TRACKER_URL": "tracker.example.test"}),
        ("other scheme", {"LEAK_TRACKER_URL": "ftp://tracker.example.test"}),
    ]:
        with _on(**over):
            _all_404(OWNER_A, label)
            assert _flag(OWNER_A) is False, label
    with _on(LEAK_TRACKER_URL="https://tracker.example.test"):
        _all_reached(OWNER_A, "https")


def case_loopback_http_needs_test_mode():
    _reset()
    with _on(CHATTERLY_TEST_MODE=None):
        _all_404(OWNER_A, "loopback http outside test mode")
        assert _flag(OWNER_A) is False
    with _on(CHATTERLY_TEST_MODE=None, LEAK_TRACKER_URL="https://tracker.example.test"):
        _all_reached(OWNER_A, "https outside test mode")
        assert _flag(OWNER_A) is True
    with _on():
        _all_reached(OWNER_A, "loopback http in test mode")


CELL_CHILD = r"""
import json, os, re, sys
sys.path.insert(0, sys.argv[1])
import _harness
_harness.bootstrap()
os.environ.update({"OI_CELL_MAP": sys.argv[2], "OI_CELL_ID": "s01", "OI_CELL_ROLE": "control",
                   "OI_ACCOUNTS": "onlyfans:1000001,onlyfans:1000002", "OI_EPOCH": "1",
                   "LEAK_TRACKER_URL": "https://tracker.example.test", "LEAK_TRACKER_ENABLED": "1"})
import _agency_fixtures as fx
ids = fx.seed_two_agencies()
owner = fx.login_owner("agency_a_owner")
import server, leak_tracker_api
assert server._CELLS
fx.store_blob(ids["agency_a_owner"], "flags", {"leak_tracker": True})
out = {"flag": owner.get("/admin/settings/applied").json()["flags"]["leak_tracker"], "status": []}
for route in leak_tracker_api.router.routes:
    path = re.sub(r"\{[^}]+\}", ids["creator_a"], route.path)
    for m in sorted(route.methods):
        out["status"].append(f"{m} {route.path} {owner.request(m, path, json={}).status_code}")
print("OUT " + json.dumps(out))
"""


def case_cell_mode_on_reads_off():
    with tempfile.TemporaryDirectory() as t:
        placement = Path(t) / "placement.json"
        placement.write_text(json.dumps({
            "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-27T10:00:00Z", "by": "fleet.py",
            "min_cell_proto": 1,
            "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:1", "role": "control", "state": "live"}},
            "accounts": {"onlyfans:1000001": "s01", "onlyfans:1000002": "s01"}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith("OI_CELL")}
        r = subprocess.run(["nice", "-n", "10", sys.executable, "-c", CELL_CHILD, str(TESTS), str(placement)],
                           cwd=TESTS.parent, env=env, capture_output=True, text=True, timeout=300)
    line = next((x for x in r.stdout.splitlines() if x.startswith("OUT ")), None)
    assert line, r.stderr[-3000:]
    out = json.loads(line[len("OUT "):])
    assert out["flag"] is False, out
    assert out["status"] and all(s.endswith(" 404") for s in out["status"]), out["status"]


def _switch_row(value) -> None:
    async def _write():
        async with get_session() as s:
            await s.execute(delete(RuntimeSwitch).where(RuntimeSwitch.name == "LEAK_TRACKER_ENABLED"))
            if value is not None:
                s.add(RuntimeSwitch(name="LEAK_TRACKER_ENABLED", value_json=json.dumps(value), updated_by="fixture",
                                    updated_at=datetime.utcnow()))
    asyncio.run(_write())
    asyncio.run(runtime_switches.load())


def _put_switch(value) -> int:
    return MASTER.put("/admin/system/switches/LEAK_TRACKER_ENABLED",
                      json={"value": value, "admin_password": os.environ["ADMIN_PASSWORD"]}).status_code


def case_a_db_row_cannot_switch_it_on_but_can_force_it_off():
    _reset()
    try:
        _switch_row(True)
        with _on(LEAK_TRACKER_ENABLED=None):
            _all_404(OWNER_A, "db row true, env unset")
            assert _flag(OWNER_A) is False
        _switch_row(None)
        with _on(LEAK_TRACKER_ENABLED=None):
            assert _put_switch(True) == 422
            _all_404(OWNER_A, "switches panel asked for on, env unset")
        with _on():
            assert _put_switch(True) == 422
            assert _put_switch(False) == 200
            _all_404(OWNER_A, "switches panel forced off, env on")
            assert _flag(OWNER_A) is False
            assert _put_switch(None) == 200
            _all_reached(OWNER_A, "override cleared, env on")
    finally:
        _switch_row(None)


def case_agency_gate_reads_one_agency():
    _reset()
    try:
        with _on():
            _all_404(OWNER_B, "agency B flag off")
            _agency("agency_b_owner", flag=False)
            _all_404(OWNER_B, "agency B flag off, key set")
            fx.store_blob(IDS["agency_b_owner"], "flags", {"leak_tracker": "yes"})
            _all_404(OWNER_B, "flag not a real true")
            _agency("agency_b_owner")
            _all_reached(OWNER_B, "agency B on", creator="creator_b")
            _all_404(OWNER_B, "agency B names agency A's Creator", {"X-Account-Id": IDS["creator_a"]})
            _all_404(CHATTER_AB, "multi-agency chatter names no allowed Creator", {"X-Account-Id": "1000999"})
            _agency("agency_a_owner", flag=False)
            _all_404(OWNER_A, "agency A flag off")
    finally:
        _reset()


def case_the_all_merge_never_turns_it_on():
    _agency("agency_a_owner", roles=_roles({EMP_AB_A: "admin"}))
    _agency("agency_b_owner", roles=_roles({EMP_AB_B: "admin"}))
    try:
        with _on():
            _all_404(CHATTER_AB, "several agencies")
            assert _flag(CHATTER_AB) is False
            a = {"X-Account-Id": IDS["creator_a"]}
            _all_reached(CHATTER_AB, "one agency named", a)
            assert _flag(CHATTER_AB, a) is True
    finally:
        _reset()


def case_setup_is_exempt_from_the_key_gate():
    _agency("agency_a_owner", key=None)
    try:
        with _on():
            r = OWNER_A.get("/admin/leaks/setup")
            assert r.status_code == 200, r.text
            assert r.json() == {"key": "missing", "masked": None, "is_owner": True, "can_write": True,
                                "brand": None}
            assert OWNER_A.get(PROBE).status_code == 404
            assert _flag(OWNER_A) is True
            _set_key("agency_a_owner", "   ")
            assert OWNER_A.get(PROBE).status_code == 404
            _set_key("agency_a_owner", "fixture-tracker-key")
            assert OWNER_A.get("/admin/leaks/setup").json()["key"] == "set"
            assert OWNER_A.get(PROBE).status_code == 200
    finally:
        _reset()


CUSTOM_WITH = {"id": "role-leaks", "name": "Leak watcher", "description": "", "scope": "self",
               "permissions": {"/creators/leaks": True}}
CUSTOM_WITHOUT = {"id": "role-closer", "name": "Closer", "description": "", "scope": "self",
                  "permissions": {"/messages-pro": True, "/creators/leaks": False}}
SAVED_TL = {"id": "team-leader", "name": "Team Leader", "description": "", "scope": "subordinates",
            "permissions": {"/creators": True}}
SAVED_TL_TICKED = {**SAVED_TL, "permissions": {"/creators": True, "/creators/leaks": True}}
SAVED_ADMIN = {"id": "admin", "name": "Admin", "description": "", "scope": "all", "permissions": {"/": True}}


def case_role_table():
    rows = [
        ("built-in Owner", _roles({EMP_A: "owner"}), True, True, False),
        ("built-in Admin", _roles({EMP_A: "admin"}), True, True, True),
        ("saved Admin object", _roles({EMP_A: "admin"}, [SAVED_ADMIN]), True, True, True),
        ("Team Leader default", _roles({EMP_A: "team-leader"}), True, False, False),
        ("saved Team Leader, no tick", _roles({EMP_A: "team-leader"}, [SAVED_TL]), False, False, False),
        ("saved Team Leader, ticked", _roles({EMP_A: "team-leader"}, [SAVED_TL_TICKED]), True, False, False),
        ("Chatter", _roles({EMP_A: "chatter"}), False, False, False),
        ("Creator", _roles({EMP_A: "creator"}), False, False, False),
        ("custom role with the page", _roles({EMP_A: "role-leaks"}, [CUSTOM_WITH]), True, False, False),
        ("custom role without the page", _roles({EMP_A: "role-closer"}, [CUSTOM_WITHOUT]), False, False, False),
        ("custom role disabled", _roles({EMP_A: "role-leaks"}, [{**CUSTOM_WITH, "disabled": True}]), False, False, False),
        ("no role", _roles({}), False, False, False),
        ("unknown role id", _roles({EMP_A: "role-gone"}), False, False, False),
        ("enforcement off", _roles({EMP_A: "team-leader"}, enforce=False), False, False, False),
        ("enforcement off, Admin", _roles({EMP_A: "admin"}, enforce=False), False, False, False),
    ]
    try:
        with _on():
            for label, roles, passes, writes, offers in rows:
                _agency("agency_a_owner", roles=roles)
                if passes:
                    _all_reached(CHATTER_A, label, writes=writes, offers=offers)
                    body = CHATTER_A.get("/admin/leaks/setup").json()
                    assert body == {"key": "set", "masked": None, "is_owner": False, "can_write": writes,
                                    "brand": None}, f"{label}: {body}"
                else:
                    _all_404(CHATTER_A, label)
                assert _flag(CHATTER_A) is passes, label
            _agency("agency_a_owner", roles=_roles({EMP_A: "team-leader"}, enforce=False))
            _all_reached(OWNER_A, "owner with enforcement off")
            assert _flag(OWNER_A) is True
    finally:
        _reset()


def case_team_leader_with_no_key_reaches_setup_only():
    _agency("agency_a_owner", key=None, roles=_roles({EMP_A: "team-leader"}))
    try:
        with _on():
            assert _flag(CHATTER_A) is True
            body = CHATTER_A.get("/admin/leaks/setup").json()
            assert body == {"key": "missing", "masked": None, "is_owner": False, "can_write": False,
                            "brand": None}, body
            assert CHATTER_A.get(PROBE).status_code == 404
    finally:
        _reset()


def case_a_method_a_leak_path_lacks_reads_404_not_405():
    _reset()
    with _on():
        for path in ("/admin/leaks/setup", f"/admin/leaks/watches/{IDS['creator_a']}"):
            r = OWNER_A.patch(path, json={})
            assert (r.status_code, r.json()) == (404, {"detail": "Not Found"}), f"{path}: {r.status_code} {r.text}"
        assert OWNER_A.delete(APPLIED).status_code == 405, "other paths keep their 405"


def case_signed_out_never_reaches_a_route():
    anon = _harness.make_client()
    with _on():
        for name, r in _routes(anon):
            assert r.status_code == 401, f"{name} signed out: {r.status_code}"


if __name__ == "__main__":
    _harness.run()
