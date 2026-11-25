#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import runtime_switches  # noqa: E402
import server  # noqa: E402

_IDS = fx.seed_two_agencies()
A = _IDS["creator_a"]
B = _IDS["creator_b"]
SWITCH = "OFM_NEW_WRITES_ENABLED"
PROBE = "/api/of/ofm-writes"
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

GATED = {
    ("POST", "/api/of/v2/campaigns/share-access"), ("DELETE", "/api/of/v2/campaigns/share-access"),
    ("DELETE", "/api/of/v2/sessions"), ("DELETE", "/api/of/v2/streams/obs/key"),
    ("POST", "/api/of/v2/streams/users/{username}/block"), ("DELETE", "/api/of/v2/streams/users/{user_id}/block"),
    ("PUT", "/api/of/v2/users/links"), ("DELETE", "/api/of/v2/users/links/{link_id}"),
    ("PUT", "/api/of/v2/users/social/buttons"), ("DELETE", "/api/of/v2/users/social/buttons/{button_id}"),
    ("POST", "/api/of/v2/users/me/profile-image"),
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-countries"),
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-ips"),
}
MAIN_WRITES = Path(__file__).with_name("test_ofm_new_writes.main_writes.json")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
OWN_SWITCH = {("POST", "/api/of/live-window/session")}
ROUTES = [
    ("POST", "/api/of/v2/campaigns/share-access", {"json": {"campaignId": 1, "userId": 2}}),
    ("DELETE", "/api/of/v2/campaigns/share-access", {"json": {"campaignId": 1, "userId": 2}}),
    ("DELETE", "/api/of/v2/sessions", {}),
    ("DELETE", "/api/of/v2/streams/obs/key?type=obs_agora", {}),
    ("POST", "/api/of/v2/streams/users/oi_fan/block", {}),
    ("DELETE", "/api/of/v2/streams/users/7/block", {}),
    ("PUT", "/api/of/v2/users/links", {"json": {"link": "https://www.youtube.com/watch?v=x"}}),
    ("DELETE", "/api/of/v2/users/links/7", {}),
    ("PUT", "/api/of/v2/users/social/buttons",
     {"json": {"socialMedia": "instagram", "label": "IG", "link": "", "username": "a"}}),
    ("DELETE", "/api/of/v2/users/social/buttons/7", {}),
    ("POST", "/api/of/v2/users/me/profile-image",
     {"files": {"file": ("cover.png", PNG_1PX, "image/png")}, "data": {"kind": "header"}}),
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-countries",
     {"json": {"blockedCountries": ["DE"], "blockedStates": []}}),
    ("PUT", "/api/of/v2/users/me/settings/security/blocked-ips", {"json": {"blockedIps": ["1.2.3.4"]}}),
]


class _FakeOF:

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name):
        def _call(*_a, **_k):
            self.calls.append(name)
            if name == "upload_media":
                return {"ready": True, "send_with": [{"processId": "p1"}]}
            return {"ok": True}
        return _call


@contextlib.contextmanager
def _switch(value):
    old = os.environ.get(SWITCH)
    if value is None:
        os.environ.pop(SWITCH, None)
    else:
        os.environ[SWITCH] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(SWITCH, None)
        else:
            os.environ[SWITCH] = old


@contextlib.contextmanager
def _fake_of():
    fake = _FakeOF()
    get, resolve = server._get_client, server._resolve_account_id
    server._get_client = lambda *_a, **_k: fake
    server._resolve_account_id = lambda _ctx: A
    try:
        yield fake
    finally:
        server._get_client, server._resolve_account_id = get, resolve


def _send(client, method, path, kw, aid=A):
    return client.request(method, path, headers={"X-Account-Id": aid}, **kw)


@contextlib.contextmanager
def _fake_of_any_creator():
    fake = _FakeOF()
    get, resolve = server._get_client, server._resolve_account_id

    def _resolve(req):
        aid = req.headers["x-account-id"]
        server.assert_account_owned(aid)
        return aid
    server._get_client = lambda *_a, **_k: fake
    server._resolve_account_id = _resolve
    try:
        yield fake
    finally:
        server._get_client, server._resolve_account_id = get, resolve


@contextlib.contextmanager
def _global_off():
    saved = runtime_switches._overrides
    runtime_switches._overrides = {**saved, SWITCH: {"value": False, "updated_at": "t", "updated_by": "x"}}
    try:
        yield
    finally:
        runtime_switches._overrides = saved


def _probe(client, aid):
    return client.get(PROBE, headers={"X-Account-Id": aid}).status_code


def _force(client, aid, off):
    return client.put(f"/admin/ofm-writes/{aid}", json={"forced_off": off})


def case_switch_defaults_off():
    os.environ.pop(SWITCH, None)
    sw = runtime_switches.BY_NAME[SWITCH]
    assert sw.default is False and sw.kind == "bool", sw
    assert runtime_switches.on(SWITCH) is False


def case_the_gate_covers_exactly_the_new_write_routes():
    def gated_(r):
        return any(getattr(d, "dependency", None) is server._ofm_new_writes_on for d in getattr(r, "dependencies", []))
    base = {tuple(r) for r in json.loads(MAIN_WRITES.read_text())["routes"]}
    assert base and all(m in WRITE_METHODS and p.startswith("/api/of/") for m, p in base), base
    writes = {
        (m, r.path) for r in server.app.routes if getattr(r, "path", "").startswith("/api/of/")
        for m in getattr(r, "methods", None) or () if m in WRITE_METHODS}
    assert base <= writes, sorted(base - writes)
    assert writes - base - OWN_SWITCH == GATED, sorted((writes - base - OWN_SWITCH) ^ GATED)
    gated = {(m, r.path) for r in server.app.routes if gated_(r) for m in getattr(r, "methods", None) or ()}
    assert gated == {("GET", PROBE)} | GATED, sorted(gated ^ ({("GET", PROBE)} | GATED))
    assert len(ROUTES) == len(GATED)


def case_off_every_route_and_the_probe_404_before_of():
    owner = fx.login_owner("agency_a_owner")
    for value in (None, "0", ""):
        with _switch(value), _fake_of() as fake:
            assert owner.get(PROBE).status_code == 404
            for method, path, kw in ROUTES:
                r = _send(owner, method, path, kw)
                assert r.status_code == 404, (value, method, path, r.status_code, r.text)
            assert fake.calls == [], fake.calls


def case_on_every_route_reaches_of_and_the_probe_answers():
    owner = fx.login_owner("agency_a_owner")
    chatter = fx.login_chatter("chatter_a")
    with _switch("1"), _fake_of() as fake:
        r = owner.get(PROBE)
        assert r.status_code == 200 and r.json() == {"on": True}, r.text
        assert chatter.get(PROBE).status_code == 200
        for method, path, kw in ROUTES:
            before = len(fake.calls)
            r = _send(owner, method, path, kw)
            assert r.status_code == 200, (method, path, r.status_code, r.text)
            assert len(fake.calls) > before, (method, path, fake.calls)


def case_profile_patch_takes_images_only_when_on():
    owner = fx.login_owner("agency_a_owner")
    body = {"header": ""}
    with _switch(None), _fake_of() as fake:
        r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": body})
        assert r.status_code == 422 and "header" in r.text, (r.status_code, r.text)
        r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": {"name": "x"}})
        assert r.status_code == 200, r.text
        assert fake.calls == ["update_profile"], fake.calls
    with _switch("1"), _fake_of() as fake:
        r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": body})
        assert r.status_code == 200, r.text
        assert fake.calls == ["update_profile"], fake.calls


def case_profile_patch_new_key_only_when_on_and_bio_as_main():
    owner = fx.login_owner("agency_a_owner")
    tip = {"canAcceptMessageOnlyFromFriends": True}
    bios = [{"about": "Hi there"}, {"about": "<p><strong>Hi</strong> there</p>"}, {"about": "<p>s are my thing"}]
    with _switch(None), _fake_of() as fake:
        r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": tip})
        assert r.status_code == 422 and "canAcceptMessageOnlyFromFriends" in r.text, (r.status_code, r.text)
        for body in bios:
            r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": body})
            assert r.status_code == 200, (body, r.text)
        assert fake.calls == ["update_profile"] * len(bios), fake.calls
    with _switch("1"), _fake_of() as fake:
        for body in [tip, bios[1]]:
            r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": body})
            assert r.status_code == 200, (body, r.text)
        assert fake.calls == ["update_profile", "update_profile"], fake.calls


def case_security_patch_takes_fully_private_only_when_on():
    owner = fx.login_owner("agency_a_owner")
    path = "/api/of/v2/users/me/settings/security"
    with _switch(None), _fake_of() as fake:
        r = _send(owner, "PATCH", path, {"json": {"isPrivate": True}})
        assert r.status_code == 422, (r.status_code, r.text)
        r = _send(owner, "PATCH", path, {"json": {"showPostsTips": True}})
        assert r.status_code == 200, r.text
        assert fake.calls == ["patch_security_settings"], fake.calls
    with _switch("1"), _fake_of() as fake:
        r = _send(owner, "PATCH", path, {"json": {"isPrivate": True}})
        assert r.status_code == 200, r.text
        assert fake.calls == ["patch_security_settings"], fake.calls


def case_inline_new_key_read_asks_the_creator_only_when_it_matters():
    asked = []
    saved = server._current_aid
    server._current_aid = lambda: asked.append(1) or A
    keys = frozenset({"isPrivate"})
    try:
        with _switch("1"):
            assert server._new_writes_for({"showPostsTips": True}, keys) is False and asked == []
            assert server._new_writes_for({"isPrivate": True}, keys) is True and asked == [1]
            assert server._new_writes_for({"about": "<b>x</b>"}, keys, ask=True) is True and asked == [1, 1]
        with _switch(None):
            assert server._new_writes_for({"isPrivate": True}, keys) is False and asked == [1, 1]
    finally:
        server._current_aid = saved


def case_env_turns_it_on_and_the_db_override_can_only_force_it_off():
    sw = runtime_switches.BY_NAME[SWITCH]
    try:
        runtime_switches.coerce(sw, True)
        raise AssertionError("an override of true must be refused")
    except ValueError as e:
        assert "env" in str(e), e
    assert runtime_switches.coerce(sw, False) is False
    saved = runtime_switches._overrides
    try:
        for env, override, want in ((None, None, False), ("1", None, True), ("1", False, False),
                                    (None, True, False), ("1", True, True), (None, False, False)):
            runtime_switches._overrides = {} if override is None else {SWITCH: {
                "value": override, "updated_at": "t", "updated_by": "x"}}
            with _switch(env):
                assert runtime_switches.on(SWITCH) is want, (env, override)
                assert runtime_switches.describe(SWITCH)["effective"] is want, (env, override)
    finally:
        runtime_switches._overrides = saved


def case_per_creator_env_off_refuses_every_creator_and_no_override_enables():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    with _switch(None), _fake_of_any_creator() as fake:
        assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
        r = _force(owner_a, A, False)
        assert r.status_code == 200 and r.json()["on"] is False and r.json()["server_on"] is False, r.text
        assert _probe(owner_a, A) == 404
        assert _send(owner_a, "DELETE", "/api/of/v2/sessions", {}).status_code == 404
        assert fake.calls == [], fake.calls
    sw = runtime_switches.BY_NAME[SWITCH]
    assert sw.off_only
    for bad in ((True, A), (False, "")):
        try:
            _run(runtime_switches.set_override(SWITCH, bad[0], by="t", account_id=bad[1]))
            raise AssertionError(f"{bad} must be refused")
        except ValueError:
            pass
    try:
        _run(runtime_switches.set_override("FULL_AI_CHAT_OFF", True, by="t", account_id=A))
        raise AssertionError("a switch that is not off_only has no Creator row")
    except ValueError:
        pass


def case_per_creator_force_off_refuses_that_creator_only():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    with _switch("1"), _fake_of_any_creator() as fake:
        try:
            assert (_probe(owner_a, A), _probe(owner_b, B)) == (200, 200)
            r = _force(owner_a, A, True)
            assert r.status_code == 200, r.text
            v = r.json()
            assert (v["forced_off"], v["on"], v["server_on"], v["changed_by"]) == (True, False, True, "agency_a_owner"), v
            assert v["changed_at"].endswith("Z") and "+" not in v["changed_at"], v
            assert runtime_switches.on(SWITCH) and not runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 200)
            for method, path, kw in ROUTES:
                assert _send(owner_a, method, path, kw).status_code == 404, (method, path)
            assert fake.calls == [], fake.calls
            sec = "/api/of/v2/users/me/settings/security"
            assert _send(owner_a, "PATCH", sec, {"json": {"isPrivate": True}}).status_code == 422
            assert _send(owner_a, "PATCH", "/api/of/v2/users/me", {"json": {"header": ""}}).status_code == 422
            assert _send(owner_b, "PATCH", sec, {"json": {"isPrivate": True}}, aid=B).status_code == 200
            assert _send(owner_b, "PATCH", "/api/of/v2/users/me", {"json": {"header": ""}}, aid=B).status_code == 200
            for method, path, kw in ROUTES:
                assert _send(owner_b, method, path, kw, aid=B).status_code == 200, (method, path)
            _run(runtime_switches.load())
            assert not runtime_switches.on(SWITCH, A)
            assert [d["env"] for d in runtime_switches.describe_all()] == [s.env for s in runtime_switches.SWITCHES]
            assert _force(owner_a, A, False).json()["on"] is True
            assert _probe(owner_a, A) == 200
            with _global_off():
                assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
                assert owner_a.get(f"/admin/ofm-writes/{A}").json() | {"changed_at": None} == {
                    "account_id": A, "server_on": False, "forced_off": False, "on": False,
                    "changed_by": None, "changed_at": None}
        finally:
            _force(owner_a, A, False)


def case_not_loaded_reads_off_for_every_creator_until_load():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    with _switch("1"), _fake_of_any_creator() as fake:
        try:
            assert _force(owner_a, A, True).status_code == 200
            saved = runtime_switches._overrides
            runtime_switches._overrides, runtime_switches._loaded = {}, False
            try:
                assert not runtime_switches.loaded()
                assert not runtime_switches.on(SWITCH) and not runtime_switches.describe(SWITCH)["effective"]
                assert not runtime_switches.on(SWITCH, A) and not runtime_switches.on(SWITCH, B)
                assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
                assert _send(owner_b, "DELETE", "/api/of/v2/sessions", {}, aid=B).status_code == 404
                assert fake.calls == [], fake.calls
            finally:
                runtime_switches._overrides = saved
            _run(runtime_switches.load())
            assert runtime_switches.loaded()
            assert runtime_switches.on(SWITCH) and not runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 200)
        finally:
            runtime_switches._loaded = True
            _force(owner_a, A, False)


def case_force_off_holds_when_the_reread_after_commit_fails():
    owner_a = fx.login_owner("agency_a_owner")
    real = runtime_switches._read_rows

    async def _fail():
        raise RuntimeError("db gone")
    with _switch("1"), _fake_of_any_creator() as fake:
        try:
            runtime_switches._read_rows = _fail
            assert _force(owner_a, A, True).status_code == 200
            assert not runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            assert _probe(owner_a, A) == 404
            assert _send(owner_a, "DELETE", "/api/of/v2/sessions", {}).status_code == 404
            _run(runtime_switches.set_override(SWITCH, False, by="t"))
            assert not runtime_switches.on(SWITCH) and not runtime_switches.on(SWITCH, B)
            assert fake.calls == [], fake.calls
            _run(runtime_switches.set_override(SWITCH, None, by="t"))
            assert _force(owner_a, A, False).status_code == 200
            assert runtime_switches.on(SWITCH, A)
        finally:
            runtime_switches._read_rows = real
            _run(runtime_switches.set_override(SWITCH, None, by="t"))
            _force(owner_a, A, False)
        assert runtime_switches.loaded() and runtime_switches.on(SWITCH, A)


def case_per_creator_force_off_is_the_creators_owner_only():
    owner_a, chatter_a = fx.login_owner("agency_a_owner"), fx.login_chatter("chatter_a")
    with _switch("1"):
        try:
            assert _force(owner_a, B, True).status_code == 403
            assert owner_a.get(f"/admin/ofm-writes/{B}").status_code == 403
            assert _force(chatter_a, A, True).status_code == 403
            assert chatter_a.get(f"/admin/ofm-writes/{A}").status_code == 200
            assert fx._harness.make_client().put(f"/admin/ofm-writes/{A}", json={"forced_off": True}).status_code in (401, 403)
            assert _force(owner_a, A, "yes").status_code == 422
            view_as = fx.login_owner("agency_master")
            r = view_as.post("/admin/impersonate", json={"user_id": _IDS["agency_a_owner"],
                                                         "admin_password": os.environ["ADMIN_PASSWORD"]})
            assert r.status_code == 200, r.text
            assert _force(view_as, A, True).status_code == 403
            assert view_as.get(f"/admin/ofm-writes/{A}").status_code == 200
            token = fx.mint_token(fx.login_owner("agency_a_owner"))
            r = fx._harness.make_client().put(f"/admin/ofm-writes/{A}", json={"forced_off": True},
                                              headers={"Authorization": f"Bearer {token}"})
            import token_auth
            assert r.status_code == 403 and token_auth.REFUSED in r.text, (r.status_code, r.text)
            assert runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            master = fx.login_owner("agency_master")
            assert _force(master, B, True).status_code == 200 and not runtime_switches.on(SWITCH, B)
            assert _force(master, B, False).status_code == 200 and runtime_switches.on(SWITCH, B)
        finally:
            _force(owner_a, A, False)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


_harness.run()
