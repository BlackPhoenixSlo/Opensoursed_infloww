#!/usr/bin/env python3
import _harness  # MUST be first: binds a throwaway temp DB (unset env falls back to PROD)

_harness.bootstrap()

import asyncio  # noqa: E402
import ipaddress  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_security as sec  # noqa: E402
import client_addr  # noqa: E402
import employees  # noqa: E402
import login_throttle  # noqa: E402
import token_bucket  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Chatter, ChatterUser, User  # noqa: E402
from sqlalchemy import update  # noqa: E402

IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")


def _seed_chatter(owners: tuple[str, ...], **values) -> str:
    name = f"sec_{uuid.uuid4().hex[:8]}"

    async def _write():
        now = datetime.utcnow()
        async with get_session() as s:
            cid = uuid.uuid4().hex
            s.add(Chatter(id=cid, username=name, password=fx.PASSWORD, display_name=name,
                          created_at=now, last_seen_at=now, **values))
            await s.flush()
            for owner in owners:
                s.add(ChatterUser(chatter_id=cid, user_id=IDS[owner], created_at=now))
    asyncio.run(_write())
    return name


def _employee_row(owner, username: str) -> dict:
    rows = [r for r in owner.get("/admin/employees").json()["employees"] if r.get("username") == username]
    assert len(rows) == 1, rows
    return rows[0]


def _code(secret: str, ahead: int = 0) -> str:
    return sec.totp(secret, sec.current_step() + ahead)


def _enrol(client) -> tuple[str, list[str]]:
    init = client.post("/auth/2fa/init", json={})
    assert init.status_code == 200, init.text
    secret = init.json()["secret"]
    r = client.post("/auth/2fa/activate", json={"enrol_token": init.json()["enrol_token"], "code": _code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


class _OneStep:
    def __enter__(self):
        self.real = sec.current_step
        step = self.real()
        sec.current_step = lambda: step

    def __exit__(self, *_):
        sec.current_step = self.real


def _clear_two_factor(model, principal_id: str) -> None:
    async def _write():
        async with get_session() as s:
            await s.execute(update(model).where(model.id == principal_id).values(**sec.clear_two_factor_values()))
    asyncio.run(_write())


class _StepAhead:
    def __init__(self, n: int):
        self.n, self.real = n, sec.current_step

    def __enter__(self):
        sec.current_step = lambda: self.real() + self.n

    def __exit__(self, *_):
        sec.current_step = self.real



def case_log_out_other_sessions_keeps_this_one_and_refuses_every_other_owner_cookie():
    login_throttle.reset()
    here, there = fx.login_owner("agency_b_owner"), fx.login_owner("agency_b_owner")
    assert there.get("/auth/me").json()["username"] == "agency_b_owner"
    r = here.post("/auth/sessions/revoke-others")
    assert r.status_code == 200, r.text
    assert here.get("/auth/me").json()["username"] == "agency_b_owner"
    assert there.get("/auth/me").json() is None
    assert fx.login_owner("agency_b_owner").get("/auth/me").json()["username"] == "agency_b_owner"


def case_a_chatter_logs_out_its_other_sessions_too():
    name = _seed_chatter(("agency_a_owner",))
    here, there = fx.login_chatter(name), fx.login_chatter(name)
    assert here.post("/auth/sessions/revoke-others").status_code == 200
    assert here.get("/chatter/me").json()["username"] == name
    assert there.get("/chatter/me").json() is None


def case_an_owner_password_reset_signs_the_employee_out_everywhere():
    name = _seed_chatter(("agency_a_owner",))
    session = fx.login_chatter(name)
    eid = _employee_row(OWNER_A, name)["id"]
    r = OWNER_A.post(f"/admin/employees/{eid}/password", json={"password": "brand-new-pw"})
    assert r.status_code == 200, r.text
    assert session.get("/chatter/me").json() is None
    r = session.post("/chatter/login", json={"username": name, "password": "brand-new-pw"})
    assert r.status_code == 200 and r.json()["username"] == name, r.text
    assert session.get("/chatter/me").json()["username"] == name


def case_deactivating_a_shared_login_keeps_its_other_agency_session():
    name = _seed_chatter(("agency_a_owner", "agency_b_owner"))
    session = fx.login_chatter(name)
    eid = _employee_row(OWNER_A, name)["id"]
    assert OWNER_A.delete(f"/admin/employees/{eid}").status_code == 200
    assert session.get("/chatter/me").json()["username"] == name


def case_the_deactivate_switch_ends_the_session_like_delete_and_reactivating_lets_it_back_in():
    login_throttle.reset()
    name = _seed_chatter(("agency_a_owner",))
    session = fx.login_chatter(name)
    eid = _employee_row(OWNER_A, name)["id"]
    r = OWNER_A.patch(f"/admin/employees/{eid}", json={"is_active": False})
    assert r.status_code == 200, r.text
    assert session.get("/chatter/me").json() is None, "the deactivated session still signed in"
    r = session.post("/chatter/login", json={"username": name, "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text
    r = OWNER_A.patch(f"/admin/employees/{eid}", json={"is_active": True})
    assert r.status_code == 200, r.text
    me = fx.login_chatter(name).get("/chatter/me").json()
    assert me and me["username"] == name, me
    login_throttle.reset()


def case_a_cookie_minted_before_revoke_support_still_reads_its_seconds():
    from session_stamps import issued_ms, session_revoked
    assert issued_ms("1700000000") == 1_700_000_000_000
    assert issued_ms("1700000000123") == 1_700_000_000_123
    later = datetime.fromtimestamp(1_700_000_001)
    assert session_revoked(issued_ms("1700000000"), later)
    assert not session_revoked(issued_ms("1700000000"), None)


def case_reactivating_a_shared_login_at_an_agency_that_requires_2fa_signs_it_out():
    login_throttle.reset()
    owner_b = fx.login_owner("agency_b_owner")
    name = _seed_chatter(("agency_a_owner", "agency_b_owner"))
    eid = _employee_row(owner_b, name)["id"]
    assert owner_b.delete(f"/admin/employees/{eid}").status_code == 200
    try:
        assert owner_b.put("/admin/settings/security", json={"require_2fa": True}).status_code == 200
        session = fx.login_chatter(name)
        assert session.get("/chatter/me").json()["username"] == name
        r = owner_b.patch(f"/admin/employees/{eid}", json={"is_active": True})
        assert r.status_code == 200, r.text
        assert session.get("/chatter/me").json() is None
        r = _harness.make_client().post("/auth/sign-in", json={"username": name, "password": fx.PASSWORD})
        assert r.status_code == 200 and r.json()["two_factor"] == "setup", r.text
    finally:
        assert owner_b.put("/admin/settings/security", json={"require_2fa": False}).status_code == 200
    login_throttle.reset()



def case_five_wrong_passwords_then_429_until_the_bucket_refills():
    login_throttle.reset()
    real_clock, t = login_throttle._clock, [1000.0]
    login_throttle._clock = lambda: t[0]
    try:
        c = _harness.make_client()
        for _ in range(login_throttle.NAME_CAPACITY):
            assert c.post("/auth/login", json={"username": "agency_a_owner", "password": "nope"}).status_code == 401
        r = c.post("/auth/login", json={"username": "agency_a_owner", "password": fx.PASSWORD})
        assert r.status_code == 429, r.text
        assert r.json()["detail"]["code"] == "too_many_attempts" and int(r.headers["retry-after"]) > 0, r.text
        assert c.post("/chatter/login", json={"username": "agency_a_owner", "password": "x"}).status_code == 429
        t[0] += login_throttle.NAME_REFILL_S
        r = c.post("/auth/login", json={"username": "agency_a_owner", "password": fx.PASSWORD})
        assert r.status_code == 200, r.text
        for _ in range(login_throttle.NAME_CAPACITY):
            assert c.post("/auth/login", json={"username": "agency_a_owner", "password": "nope"}).status_code == 401
        assert c.post("/auth/login", json={"username": "agency_a_owner", "password": "nope"}).status_code == 429
    finally:
        login_throttle._clock = real_clock
        login_throttle.reset()


def _client_from(peer: str):
    from fastapi.testclient import TestClient
    return TestClient(_harness.make_client().app, client=(peer, 50000))


def case_the_ip_bucket_stops_spraying_across_usernames():
    login_throttle.reset()
    c = _client_from("172.18.0.5")
    spread = login_throttle.IP_CAPACITY // login_throttle.NAME_CAPACITY + 2
    names = [_seed_chatter(("agency_a_owner",)) for _ in range(spread)]
    codes = [c.post("/chatter/login", json={"username": names[i % spread], "password": "bad"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"}).status_code
             for i in range(login_throttle.IP_CAPACITY + 1)]
    assert codes[:login_throttle.IP_CAPACITY] == [401] * login_throttle.IP_CAPACITY and codes[-1] == 429, codes
    r = c.post("/chatter/login", json={"username": names[0], "password": fx.PASSWORD},
               headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.7"})
    assert r.status_code == 200, r.text
    login_throttle.reset()


def case_trusted_proxies_default_to_loopback_and_private_ranges():
    trusted = client_addr._is_trusted_proxy
    for peer in ("127.0.0.1", "::1", "10.1.2.3", "172.18.0.5", "192.168.1.9", "fd00::7", "fe80::1",
                 "::ffff:172.18.0.5"):
        assert trusted(peer), peer
    for peer in ("203.0.113.5", "172.32.0.1", "2001:db8::1", "testclient", "unknown"):
        assert not trusted(peer), peer
    assert client_addr._parse_trusted("") == client_addr._parse_trusted("  ") \
        == client_addr._parse_trusted(client_addr._DEFAULT_TRUSTED)
    assert client_addr._parse_trusted("10.0.0.7, 192.168.0.0/16") == (
        ipaddress.ip_network("10.0.0.7/32"), ipaddress.ip_network("192.168.0.0/16"))
    assert client_addr._parse_trusted("10.0.0.7,proxy-host") == (ipaddress.ip_network("10.0.0.7/32"),)


def case_the_forwarded_address_is_parsed_before_it_keys_a_bucket():
    from starlette.requests import Request

    def key(forwarded: str, peer: str = "172.18.0.5") -> str:
        return token_bucket.bucket_key(client_addr.client_address(Request({
            "type": "http", "headers": [(b"x-forwarded-for", forwarded.encode())], "client": (peer, 1)})))
    assert key("203.0.113.9:4431") == key("::ffff:203.0.113.9") == "203.0.113.9"
    assert key("[2001:db8:1:2::9]:443") == key("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert key("not-an-address") == "172.18.0.5"
    assert key("203.0.113.9", peer="198.51.100.4") == "198.51.100.4"


def case_rotating_the_forwarded_address_still_ends_in_429_for_one_username():
    login_throttle.reset()
    c = _client_from("172.18.0.5")
    def guess(i: int) -> int:
        return c.post("/auth/sign-in", json={"username": "agency_a_owner", "password": "bad"},
                      headers={"X-Forwarded-For": f"198.51.{i // 250}.{i % 250}"}).status_code
    codes = [guess(i) for i in range(login_throttle.USER_CAPACITY - 1)]
    assert codes == [401] * (login_throttle.USER_CAPACITY - 1), codes
    r = c.post("/auth/sign-in", json={"username": "agency_a_owner", "password": fx.PASSWORD},
               headers={"X-Forwarded-For": "203.0.113.50"})
    assert r.status_code == 200, r.text
    codes = [guess(login_throttle.USER_CAPACITY + i) for i in range(2)]
    assert codes == [401, 429], codes
    login_throttle.reset()


def case_flooding_other_keys_never_forgets_a_drained_username_bucket():
    login_throttle.reset()
    real_clock, t = login_throttle._clock, [5000.0]
    login_throttle._clock = lambda: t[0]
    real_max = login_throttle._buckets.max_keys
    login_throttle._buckets.max_keys = 6
    c = _client_from("172.18.0.5")
    try:
        def post(user: str, i: int) -> int:
            return c.post("/auth/sign-in", json={"username": user, "password": "bad"},
                          headers={"X-Forwarded-For": f"198.51.{i // 250}.{i % 250}"}).status_code
        drained = [post("agency_a_owner", i) for i in range(login_throttle.USER_CAPACITY)]
        assert drained == [401] * login_throttle.USER_CAPACITY, drained
        flood = [post(f"nobody_{i}", 1000 + i) for i in range(login_throttle._buckets.max_keys)]
        assert flood == [401] * len(flood), flood
        code = post("agency_a_owner", 2000)
        assert code == 429, f"drained username got {code} after a flood of other keys"
        assert len(login_throttle._buckets) > login_throttle._buckets.max_keys
    finally:
        login_throttle._buckets.max_keys = real_max
        login_throttle._clock = real_clock
        login_throttle.reset()


def case_a_peer_that_is_not_a_trusted_proxy_cannot_pick_its_address():
    login_throttle.reset()
    c = _client_from("203.0.113.200")
    codes = [c.post("/auth/sign-in", json={"username": f"nobody_{i}", "password": "bad"},
                    headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
             for i in range(login_throttle.IP_CAPACITY + 1)]
    assert codes == [401] * login_throttle.IP_CAPACITY + [429], codes
    login_throttle.reset()


def case_wrong_guesses_from_one_address_do_not_lock_the_owner_out_elsewhere():
    login_throttle.reset()
    c = _client_from("172.18.0.5")
    stranger, owner = {"X-Forwarded-For": "203.0.113.66"}, {"X-Forwarded-For": "198.51.100.1"}
    codes = [c.post("/auth/sign-in", json={"username": "agency_a_owner", "password": "bad"},
                    headers=stranger).status_code for _ in range(login_throttle.NAME_CAPACITY + 1)]
    assert codes == [401] * login_throttle.NAME_CAPACITY + [429], codes
    r = c.post("/auth/sign-in", json={"username": "agency_a_owner", "password": fx.PASSWORD}, headers=owner)
    assert r.status_code == 200, r.text
    login_throttle.reset()


def case_the_sign_in_form_signs_owners_and_employees_in_through_one_endpoint():
    login_throttle.reset()
    name = _seed_chatter(("agency_a_owner",))
    owner, employee = _harness.make_client(), _harness.make_client()
    r = owner.post("/auth/sign-in", json={"username": "Agency_A_Owner ", "password": fx.PASSWORD})
    assert r.status_code == 200 and r.json() == {"kind": "user"}, r.text
    assert owner.get("/auth/me").json()["username"] == "agency_a_owner"
    r = employee.post("/auth/sign-in", json={"username": name, "password": fx.PASSWORD})
    assert r.status_code == 200 and r.json() == {"kind": "chatter"}, r.text
    assert employee.get("/chatter/me").json()["username"] == name
    switched_off = _seed_chatter(("agency_a_owner",), is_active=False)
    r = employee.post("/auth/sign-in", json={"username": switched_off, "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text
    for _ in range(login_throttle.IP_CAPACITY + 2):
        assert employee.post("/auth/sign-in", json={"username": name, "password": fx.PASSWORD}).status_code == 200
    login_throttle.reset()


def case_one_wrong_password_is_one_token_whoever_has_the_name():
    login_throttle.reset()
    c = _harness.make_client()
    for name in ("agency_a_owner", _seed_chatter(("agency_a_owner",)), f"nobody_{uuid.uuid4().hex[:6]}"):
        codes = [c.post("/auth/sign-in", json={"username": name, "password": "wrong"}).status_code
                 for _ in range(login_throttle.NAME_CAPACITY + 1)]
        assert codes == [401] * login_throttle.NAME_CAPACITY + [429], (name, codes)
    login_throttle.reset()


def case_the_audit_log_keeps_no_2fa_code_or_ticket():
    snap = employees._safe_snapshot(b'{"ticket": "2fa.user.x", "code": "123456", "username": "ann"}',
                                    keys_only=False)
    assert "123456" not in snap and "2fa.user.x" not in snap and "ann" in snap, snap



def case_totp_matches_the_rfc_6238_vector():
    # RFC 6238 appendix B, SHA-1, T = 59 s: step 1, 6 digits 287082
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert sec.totp(secret, 1) == "287082"
    assert sec.match_step(secret, "287082", None) is None
    assert sec.otpauth_uri("ann", "ABC").startswith("otpauth://totp/Inflowwww%3Aann?secret=ABC&issuer=Inflowwww")


def case_an_owner_enrols_and_every_other_session_signs_out():
    with _OneStep():
        login_throttle.reset()
        here, there = fx.login_owner("agency_master"), fx.login_owner("agency_master")
        assert here.get("/auth/2fa").json() == {"enabled": False, "enabled_at": None,
                                                "recovery_codes_left": 0, "required": False}
        init = here.post("/auth/2fa/init", json={}).json()
        assert init["otpauth_uri"].startswith("otpauth://totp/") and len(init["secret"]) == 32
        bad = here.post("/auth/2fa/activate", json={"enrol_token": init["enrol_token"], "code": "000000"
                                                    if _code(init["secret"]) != "000000" else "111111"})
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_code", bad.text
        forged = init["enrol_token"].replace(init["secret"], sec.new_secret())
        assert here.post("/auth/2fa/activate", json={"enrol_token": forged,
                                                     "code": _code(init["secret"])}).status_code == 400
        r = here.post("/auth/2fa/activate", json={"enrol_token": init["enrol_token"], "code": _code(init["secret"])})
        assert r.status_code == 200, r.text
        codes = r.json()["recovery_codes"]
        assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 19 for c in codes), codes
        assert here.get("/auth/me").json()["username"] == "agency_master"
        assert there.get("/auth/me").json() is None
        status = here.get("/auth/2fa").json()
        assert status["enabled"] and status["enabled_at"] and status["recovery_codes_left"] == 10, status
        again = here.post("/auth/2fa/init", json={})
        assert again.status_code == 409, again.text


def case_sign_in_with_2fa_asks_for_a_code_and_each_code_works_once():
    with _OneStep():
        try:
            login_throttle.reset()
            c = fx.login_owner("agency_b_owner")
            secret, codes = _enrol(c)
            fresh = _harness.make_client()
            r = fresh.post("/auth/login", json={"username": "agency_b_owner", "password": fx.PASSWORD})
            assert r.status_code == 200 and r.json()["two_factor"] == "verify", r.text
            ticket = r.json()["ticket"]
            assert fresh.get("/auth/me").json() is None
            bad = fresh.post("/auth/2fa/login", json={"ticket": ticket, "code": _code(secret)})
            assert bad.status_code == 400, bad.text
            r = fresh.post("/auth/2fa/login", json={"ticket": ticket, "code": codes[0].upper()})
            assert r.status_code == 200 and r.json() == {"kind": "user"}, r.text
            assert fresh.get("/auth/me").json()["username"] == "agency_b_owner"
            assert fresh.get("/auth/2fa").json()["recovery_codes_left"] == 9
            t2 = _harness.make_client().post("/auth/login", json={"username": "agency_b_owner",
                                                                  "password": fx.PASSWORD}).json()["ticket"]
            assert _harness.make_client().post("/auth/2fa/login", json={"ticket": t2, "code": codes[0]}).status_code == 400
            with _StepAhead(1):
                nxt = _harness.make_client()
                r = nxt.post("/auth/2fa/login", json={"ticket": t2, "code": _code(secret)})
                assert r.status_code == 200, r.text
                assert nxt.get("/auth/me").json()["username"] == "agency_b_owner"
            # flip the last char: a fixed "0" is no change 1 time in 16
            tampered = t2[:-1] + ("1" if t2[-1] == "0" else "0")
            r = _harness.make_client().post("/auth/2fa/login", json={"ticket": tampered, "code": "123456"})
            assert r.status_code == 401 and r.json()["detail"]["code"] == "ticket_expired", r.text
            with _StepAhead(2):
                r = c.post("/auth/2fa/recovery-codes", json={"code": _code(secret)})
                assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10, r.text
            assert c.post("/auth/2fa/disable", json={"code": codes[1]}).status_code == 400
            assert fresh.get("/auth/me").json()["username"] == "agency_b_owner"
            with _StepAhead(3):
                assert c.post("/auth/2fa/disable", json={"code": _code(secret)}).status_code == 200
            assert c.get("/auth/2fa").json()["enabled"] is False
            assert fresh.get("/auth/me").json() is None
            assert c.get("/auth/me").json()["username"] == "agency_b_owner"
            r = _harness.make_client().post("/auth/login", json={"username": "agency_b_owner", "password": fx.PASSWORD})
            assert "two_factor" not in r.json() and r.json()["username"] == "agency_b_owner", r.text
            login_throttle.reset()
        finally:
            _clear_two_factor(User, IDS["agency_b_owner"])


def case_wrong_codes_hit_the_throttle():
    with _OneStep():
        login_throttle.reset()
        name = _seed_chatter(("agency_a_owner",))
        c = fx.login_chatter(name)
        _enrol(c)
        ticket = c.post("/chatter/login", json={"username": name, "password": fx.PASSWORD}).json()["ticket"]
        codes = [c.post("/auth/2fa/login", json={"ticket": ticket, "code": "nope-nope"}).status_code
                 for _ in range(login_throttle.NAME_CAPACITY + 1)]
        assert codes == [400] * login_throttle.NAME_CAPACITY + [429], codes
        login_throttle.reset()


def case_the_owner_resets_an_employees_2fa_and_signs_them_out():
    with _OneStep():
        login_throttle.reset()
        name = _seed_chatter(("agency_a_owner",))
        c = fx.login_chatter(name)
        _enrol(c)
        row = _employee_row(OWNER_A, name)
        assert row["two_factor"] is True and row["last_login_at"].endswith("Z"), row
        r = OWNER_A.post(f"/admin/employees/{row['id']}/2fa/reset")
        assert r.status_code == 200, r.text
        assert c.get("/chatter/me").json() is None
        assert _employee_row(OWNER_A, name)["two_factor"] is False
        r = c.post("/chatter/login", json={"username": name, "password": fx.PASSWORD})
        assert r.status_code == 200 and r.json()["username"] == name, r.text
        shared = _seed_chatter(("agency_a_owner", "agency_b_owner"))
        r = OWNER_A.post(f"/admin/employees/{_employee_row(OWNER_A, shared)['id']}/2fa/reset")
        assert r.status_code == 409, r.text
        other = _employee_row(fx.login_owner("agency_b_owner"), _seed_chatter(("agency_b_owner",)))["id"]
        assert OWNER_A.post(f"/admin/employees/{other}/2fa/reset").status_code in (403, 404)


def case_an_agency_that_requires_2fa_has_its_employees_set_it_up_at_sign_in():
    with _OneStep():
        login_throttle.reset()
        owner = fx.login_owner("agency_b_owner")
        name = _seed_chatter(("agency_b_owner",))
        before = fx.login_chatter(name)
        r = owner.put("/admin/settings/security", json={"require_2fa": True})
        assert r.status_code == 200 and r.json()["config"]["require_2fa"] is True, r.text
        assert before.get("/chatter/me").json() is None
        c = _harness.make_client()
        r = c.post("/chatter/login", json={"username": name, "password": fx.PASSWORD})
        assert r.status_code == 200 and r.json()["two_factor"] == "setup", r.text
        ticket = r.json()["ticket"]
        assert c.get("/chatter/me").json() is None
        init = c.post("/auth/2fa/init", json={"ticket": ticket}).json()
        r = c.post("/auth/2fa/activate", json={"enrol_token": init["enrol_token"], "ticket": ticket,
                                               "code": _code(init["secret"])})
        assert r.status_code == 200 and r.json()["kind"] == "chatter" and len(r.json()["recovery_codes"]) == 10, r.text
        assert c.get("/chatter/me").json()["username"] == name
        status = c.get("/auth/2fa").json()
        assert status["enabled"] and status["required"], status
        with _StepAhead(1):
            r = c.post("/auth/2fa/disable", json={"code": _code(init["secret"])})
        assert r.status_code == 409 and "required" in r.json()["detail"], r.text
        again = c.post("/auth/2fa/init", json={"ticket": ticket})
        assert again.status_code == 401 and again.json()["detail"]["code"] == "ticket_expired", again.text
        newcomer = _seed_chatter(("agency_a_owner",))
        session = fx.login_chatter(newcomer)
        assert owner.post("/admin/chatters/link", json={"username": newcomer}).status_code == 200
        assert session.get("/chatter/me").json() is None
        assert "two_factor" not in fx.login_owner("agency_b_owner").get("/auth/me").json()
        assert owner.put("/admin/settings/security", json={"require_2fa": False}).status_code == 200
        login_throttle.reset()



def case_a_deactivated_login_is_told_why_only_after_the_right_password():
    login_throttle.reset()
    c = _harness.make_client()
    switched_off = _seed_chatter(("agency_a_owner",), is_active=False)
    r = c.post("/chatter/login", json={"username": switched_off, "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text
    assert "deactivated" in r.json()["detail"]["message"]
    assert c.post("/chatter/login", json={"username": switched_off, "password": "wrong"}).status_code == 401
    orphan = _seed_chatter(())
    r = c.post("/chatter/login", json={"username": orphan, "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text
    name = _seed_chatter(("agency_a_owner",))
    session = fx.login_chatter(name)
    assert OWNER_A.delete(f"/admin/employees/{_employee_row(OWNER_A, name)['id']}").status_code == 200
    assert session.get("/chatter/me").json() is None
    r = session.post("/chatter/login", json={"username": name, "password": fx.PASSWORD})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated", r.text



def case_the_employee_limit_is_a_typed_refusal():
    real = os.environ.get("MAX_EMPLOYEES_PER_USER")
    os.environ["MAX_EMPLOYEES_PER_USER"] = "1"
    try:
        r = OWNER_A.post("/admin/employees", json={"display_name": "One Too Many"})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "employee_limit" and detail["limit"] == 1 and detail["active"] >= 1, detail
        assert "cap reached" in detail["message"]
    finally:
        if real is None:
            os.environ.pop("MAX_EMPLOYEES_PER_USER", None)
        else:
            os.environ["MAX_EMPLOYEES_PER_USER"] = real


_harness.run()
