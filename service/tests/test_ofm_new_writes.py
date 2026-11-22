#!/usr/bin/env python3
"""test_ofm_new_writes.py — ofm-not-yet's new OF write routes stay inert until OFM_NEW_WRITES_ENABLED.

The switch (runtime_switches, default off) gates every write route the effort added (server._OFM_WRITES):
off, each answers 404 before any OF call, as does the Mirror's probe GET /api/of/ofm-writes; on, each
reaches the (faked) OF client and the probe answers {"on": true}. PATCH /users/me takes `avatar`/`header`
only while it is on. Per Creator: on for a Creator = env on, not forced off box-wide, and that Creator not forced off
by its owner (PUT /admin/ofm-writes/{id}); the probe answers for the request's Creator. OF is faked
(`server._get_client`): no request leaves the process.

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
B = _IDS["creator_b"]
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


def _send(client, method, path, kw, aid=A):
    return client.request(method, path, headers={"X-Account-Id": aid}, **kw)


@contextlib.contextmanager
def _fake_of_any_creator():
    """OF faked; the request's Creator is its X-Account-Id, ownership-checked as `_resolve_account_id` does (the
    fixture's Creators have no registry meta, so the real one 404s them)."""
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
    """Settings › System's box-wide force-off (the cached override), Creator rows kept."""
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


def case_inline_new_key_read_asks_the_creator_only_when_it_matters():
    """server._new_writes_for (follow-up #11): the request's Creator is resolved only for a body with a new key (or
    `ask`, PATCH /users/me's formatted Bio), and only once the switch is on box-wide."""
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


def case_per_creator_env_off_refuses_every_creator_and_no_override_enables():
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    with _switch(None), _fake_of_any_creator() as fake:
        assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
        r = _force(owner_a, A, False)   # clearing a force-off never turns it on
        assert r.status_code == 200 and r.json()["on"] is False and r.json()["server_on"] is False, r.text
        assert _probe(owner_a, A) == 404
        assert _send(owner_a, "DELETE", "/api/of/v2/sessions", {}).status_code == 404
        assert fake.calls == [], fake.calls
    sw = runtime_switches.BY_NAME[SWITCH]
    assert sw.off_only
    for bad in ((True, A), (False, "")):   # a Creator row only ever forces off; a Creator is named
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
            assert v["changed_at"].endswith("Z") and "+" not in v["changed_at"], v   # naive UTC, sent as UTC
            assert runtime_switches.on(SWITCH) and not runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 200)
            for method, path, kw in ROUTES:
                assert _send(owner_a, method, path, kw).status_code == 404, (method, path)
            assert fake.calls == [], fake.calls   # 404 before any OF call
            # the inline reads too: A's new keys refused, B's taken
            sec = "/api/of/v2/users/me/settings/security"
            assert _send(owner_a, "PATCH", sec, {"json": {"isPrivate": True}}).status_code == 422
            assert _send(owner_a, "PATCH", "/api/of/v2/users/me", {"json": {"header": ""}}).status_code == 422
            assert _send(owner_b, "PATCH", sec, {"json": {"isPrivate": True}}, aid=B).status_code == 200
            assert _send(owner_b, "PATCH", "/api/of/v2/users/me", {"json": {"header": ""}}, aid=B).status_code == 200
            for method, path, kw in ROUTES:
                assert _send(owner_b, method, path, kw, aid=B).status_code == 200, (method, path)
            # the row survives a reload (boot) and stays out of Settings › System's list
            _run(runtime_switches.load())
            assert not runtime_switches.on(SWITCH, A)
            assert [d["env"] for d in runtime_switches.describe_all()] == [s.env for s in runtime_switches.SWITCHES]
            assert _force(owner_a, A, False).json()["on"] is True   # cleared: back to the box-wide value
            assert _probe(owner_a, A) == 200
            # Settings › System's box-wide force-off beats every Creator (a write re-reads the cache, so none inside)
            with _global_off():
                assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
                assert owner_a.get(f"/admin/ofm-writes/{A}").json() | {"changed_at": None} == {
                    "account_id": A, "server_on": False, "forced_off": False, "on": False,
                    "changed_by": None, "changed_at": None}
        finally:
            _force(owner_a, A, False)


def case_not_loaded_reads_off_for_every_creator_until_load():
    """A failed boot load (`_loaded` False, cache empty) must not read a forced-off Creator on: env on, the switch
    is off box-wide and for every Creator, and the probe 404s, until load() reads the table."""
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")
    with _switch("1"), _fake_of_any_creator() as fake:
        try:
            assert _force(owner_a, A, True).status_code == 200
            saved = runtime_switches._overrides
            runtime_switches._overrides, runtime_switches._loaded = {}, False   # boot load() failed
            try:
                assert not runtime_switches.loaded()
                assert not runtime_switches.on(SWITCH) and not runtime_switches.describe(SWITCH)["effective"]
                assert not runtime_switches.on(SWITCH, A) and not runtime_switches.on(SWITCH, B)
                assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 404)
                assert _send(owner_b, "DELETE", "/api/of/v2/sessions", {}, aid=B).status_code == 404
                assert fake.calls == [], fake.calls
            finally:
                runtime_switches._overrides = saved
            _run(runtime_switches.load())   # the retry reads the table: as before
            assert runtime_switches.loaded()
            assert runtime_switches.on(SWITCH) and not runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            assert (_probe(owner_a, A), _probe(owner_b, B)) == (404, 200)
        finally:
            runtime_switches._loaded = True
            _force(owner_a, A, False)


def case_force_off_holds_when_the_reread_after_commit_fails():
    """The row commits, then the cache re-read fails: the committed force-off (box-wide or a Creator's) is enforced
    anyway, and clearing it after another failed re-read lets writes back."""
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
            assert _force(owner_a, B, True).status_code == 403   # another agency's Creator
            assert owner_a.get(f"/admin/ofm-writes/{B}").status_code == 403
            assert _force(chatter_a, A, True).status_code == 403   # a chatter reads, never writes
            assert chatter_a.get(f"/admin/ofm-writes/{A}").status_code == 200
            assert fx._harness.make_client().put(f"/admin/ofm-writes/{A}", json={"forced_off": True}).status_code in (401, 403)
            assert _force(owner_a, A, "yes").status_code == 422
            # the Master's "view as" owner_a is read-only; an owner access token is not on the token allowlist
            view_as = fx.login_owner("agency_master")
            r = view_as.post("/admin/impersonate", json={"user_id": _IDS["agency_a_owner"],
                                                         "admin_password": os.environ["ADMIN_PASSWORD"]})
            assert r.status_code == 200, r.text
            assert _force(view_as, A, True).status_code == 403
            assert view_as.get(f"/admin/ofm-writes/{A}").status_code == 200   # reads, as the owner does
            token = fx.mint_token(fx.login_owner("agency_a_owner"))
            r = fx._harness.make_client().put(f"/admin/ofm-writes/{A}", json={"forced_off": True},
                                              headers={"Authorization": f"Bearer {token}"})
            import token_auth
            assert r.status_code == 403 and token_auth.REFUSED in r.text, (r.status_code, r.text)
            assert runtime_switches.on(SWITCH, A) and runtime_switches.on(SWITCH, B)
            # the Master holds every Creator: it may, as on PUT /admin/of-consent
            master = fx.login_owner("agency_master")
            assert _force(master, B, True).status_code == 200 and not runtime_switches.on(SWITCH, B)
            assert _force(master, B, False).status_code == 200 and runtime_switches.on(SWITCH, B)
        finally:
            _force(owner_a, A, False)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


_harness.run()
