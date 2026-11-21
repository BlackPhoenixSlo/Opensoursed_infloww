#!/usr/bin/env python3
"""test_ofm_new_writes.py — ofm-not-yet's new OF write routes stay inert until OFM_NEW_WRITES_ENABLED.

The switch (runtime_switches, default off) gates every write route the effort added (server._OFM_WRITES):
off, each answers 404 before any OF call, as does the Mirror's probe GET /api/of/ofm-writes; on, each
reaches the (faked) OF client and the probe answers {"on": true}. PATCH /users/me takes `avatar`/`header`
only while it is on. OF is faked (`server._get_client`): no request leaves the process.

Run:  ./venv/bin/python service/tests/test_ofm_new_writes.py
"""
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
SWITCH = "OFM_NEW_WRITES_ENABLED"
PROBE = "/api/of/ofm-writes"
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")

# The /api/of/ write routes ofm-not-yet added, but /api/of/live-window/session (OWN_SWITCH).
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
# main's write routes under /api/of/, frozen once from main's test_route_order golden (the json's "source"): any other
# write route there is new and must be gated, but these, which have their own switch.
MAIN_WRITES = Path(__file__).with_name("test_ofm_new_writes.main_writes.json")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
OWN_SWITCH = {("POST", "/api/of/live-window/session")}  # OF_LIVE_WINDOW_ENABLED
# (method, path, request kwargs): one valid request per gated route.
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
    """Records every OnlyFans client call; an upload answers one upload item, anything else {"ok": True}."""

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


def _send(client, method, path, kw):
    return client.request(method, path, headers={"X-Account-Id": A}, **kw)


def case_switch_defaults_off():
    os.environ.pop(SWITCH, None)
    sw = runtime_switches.BY_NAME[SWITCH]
    assert sw.default is False and sw.kind == "bool", sw
    assert runtime_switches.on(SWITCH) is False


def case_the_gate_covers_exactly_the_new_write_routes():
    """The app's /api/of/ write routes not in main's frozen set are GATED (and OWN_SWITCH): a new one cannot ship
    without server._ofm_new_writes_on, and the gate is on nothing else but the probe."""
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
        assert chatter.get(PROBE).status_code == 200  # every Mirror session reads it
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
        assert r.status_code == 200, r.text  # the rest of the profile write is untouched
        assert fake.calls == ["update_profile"], fake.calls
    with _switch("1"), _fake_of() as fake:
        r = _send(owner, "PATCH", "/api/of/v2/users/me", {"json": body})
        assert r.status_code == 200, r.text
        assert fake.calls == ["update_profile"], fake.calls


def case_profile_patch_new_key_only_when_on_and_bio_as_main():
    """The Tip switch's key is new to PATCH /users/me: refused off. Off, `about` goes as main sent it, markup-looking
    or not (a plain Bio may start with `<p`); on, a formatted Bio is sanitized (test_settings_writes)."""
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
    """Fully private (`isPrivate`) is new to the mirror's security PATCH: 422 off; main's other toggles as before."""
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


def case_env_turns_it_on_and_the_db_override_can_only_force_it_off():
    """Panel D30: a Settings › System click must not enable live writes on a client box; it can still stop them."""
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
            # (None, True): a row written before off_only (or by hand) still can't turn it on
            runtime_switches._overrides = {} if override is None else {SWITCH: {
                "value": override, "updated_at": "t", "updated_by": "x"}}
            with _switch(env):
                assert runtime_switches.on(SWITCH) is want, (env, override)
                assert runtime_switches.describe(SWITCH)["effective"] is want, (env, override)
    finally:
        runtime_switches._overrides = saved


_harness.run()
