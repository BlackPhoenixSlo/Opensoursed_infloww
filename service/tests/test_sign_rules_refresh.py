#!/usr/bin/env python3
"""Central sign-rule refresh (roadmap 2.17, service/sign_rules.py).

Sign rules belong to an OF build, so one capture at the live build refreshes
every account on an older one. Pins: the donor is the freshest session at the
live build whose rules reproduce its own samples and that OF has answered with
a 2xx since the capture (OFClient stamps `signed_ok_at` once and asks for a
refresh), never one whose static_param was typed into the override box; every
other OnlyFans account
on another build takes the donor's build and rules (cookies untouched) and its
pooled client is evicted (its old 2xx stamp dropped); with no verified donor
nothing changes; a session
on a newer build (by the build id's time prefix, else by capture time) is
never walked back; a stale-build capture still takes the new rules; a session
that took copied rules is never itself a donor; Fansly accounts are left alone; a
new build seen by live_rev triggers a refresh; and the background refresh is
off until server startup enables it, then single-flight (any number of
triggers during a run queue exactly one more).

No network: sessions are temp files, samples are computed with of_signer.

Run:  ./venv/bin/python service/tests/test_sign_rules_refresh.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

import json  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import accounts as account_registry  # noqa: E402
import client_pool  # noqa: E402
import live_rev  # noqa: E402
import of_signer  # noqa: E402
import sign_rules  # noqa: E402

OLD, NEW = "202610010000-aaaaaaaaaa", "202610190000-bbbbbbbbbb"


def _rules(seed: int) -> dict:
    return {"static_param": f"sp{seed}", "start": str(40000 + seed), "end": f"e{seed}",
            "checksum_indexes": [(seed + i * 7) % 40 for i in range(32)],
            "checksum_constant": -(1000 + seed)}


def _sample(rules: dict, user_id: str) -> dict:
    signed = of_signer.sign("https://onlyfans.com/api2/v2/users/me", user_id, rules, time_ms=1)
    _start, sha1, hexsum, _end = signed["sign"].split(":")
    return {"sha1Hex": sha1, "checksumValue": int(hexsum, 16)}


def _fresh_dirs() -> None:
    root = Path(tempfile.mkdtemp(prefix="signrules_"))
    account_registry.SESSIONS_DIR = root
    account_registry.ACCOUNTS_DIR = root / "accounts"
    account_registry.ACCOUNTS_DIR.mkdir(parents=True)
    live_rev._cache.update(rev=None, fetched_at=0.0, source=None, error=None)
    client_pool._POOL.clear()


def _account(aid: str, rev: str, rules: dict, captured_at: str, *, verified: bool = True,
             platform: str = "onlyfans", signed_ok: bool = True,
             static_param_source: str | None = None) -> Path:
    adir = account_registry.account_dir(aid)
    adir.mkdir(parents=True)
    sample = _sample(rules, aid)
    if not verified:
        sample["checksumValue"] += 1
    session = {
        "captured_at": captured_at,
        "headers": {"user_id": aid, "x_bc": f"bc{aid}", "x_of_rev": rev, "user_agent": "ua"},
        "signing": {"rules": rules, "samples": [sample], "static_param_source": static_param_source,
                    **({"signed_ok_at": captured_at} if signed_ok else {})},
        "cookies": [{"name": "sess", "value": f"cookie{aid}", "domain": ".onlyfans.com", "path": "/"}],
    }
    sp = adir / f"session_{captured_at}.json"
    sp.write_text(json.dumps(session))
    account_registry.record_session(aid, sp)
    if platform != "onlyfans":
        meta = account_registry.load_meta(aid)
        meta["platform"] = platform
        account_registry.save_meta(aid, meta)
    return sp


def _read(sp: Path) -> dict:
    return json.loads(sp.read_text())


def _live(rev: str) -> None:
    live_rev._cache.update(rev=rev, fetched_at=time.time(), source="test", error=None)


def case_spreads_live_build_rules_to_older_accounts():
    _fresh_dirs()
    donor = _account("1", NEW, _rules(1), "20261019T100000Z")
    stale = _account("2", OLD, _rules(2), "20261001T100000Z")
    client_pool._POOL["2"] = object()
    _live(NEW)
    out = sign_rules.refresh("test")
    assert out["donor"] == "1" and out["updated"] == ["2"], out
    s = _read(stale)
    assert s["headers"]["x_of_rev"] == NEW, s["headers"]
    assert s["signing"]["rules"] == _rules(1), "the donor's rules are copied"
    assert s["signing"]["rules_captured_at"] == "20261019T100000Z"
    assert s["signing"]["rules_from"] == {"account_id": "1", "x_of_rev": NEW}
    assert "signed_ok_at" not in s["signing"], "its 2xx proved the old rules, not these"
    assert s["cookies"][0]["value"] == "cookie2" and s["headers"]["x_bc"] == "bc2", \
        "the account's own cookies and x-bc stay"
    assert "2" not in client_pool._POOL, "the stale account's pooled client is evicted"
    assert _read(donor)["signing"]["rules"] == _rules(1), "the donor is untouched"
    assert sign_rules.last()["updated"] == ["2"]
    # The copied rules sign: the new session is a valid OFClient session.
    of_signer.sign("https://onlyfans.com/api2/v2/chats", "2", s["signing"]["rules"])


def case_no_verified_donor_changes_nothing():
    _fresh_dirs()
    stale = _account("2", OLD, _rules(2), "20261001T100000Z")
    _account("3", NEW, _rules(3), "20261019T100000Z", verified=False)
    before = stale.read_text()
    _live(NEW)
    out = sign_rules.refresh("test")
    assert out["donor"] is None and out["updated"] == [], out
    assert "no verified session" in out["skipped"]
    assert stale.read_text() == before


def case_a_donor_needs_a_2xx_and_no_typed_static_param():
    _fresh_dirs()
    stale = _account("2", OLD, _rules(2), "20261001T100000Z")
    _account("3", NEW, _rules(3), "20261019T100000Z", signed_ok=False)
    _account("4", NEW, _rules(4), "20261019T110000Z", static_param_source="override")
    before = stale.read_text()
    _live(NEW)
    out = sign_rules.refresh("test")
    assert out["donor"] is None and out["updated"] == [], out
    assert stale.read_text() == before
    _account("5", NEW, _rules(5), "20261019T090000Z", static_param_source="rev_lookup")
    out = sign_rules.refresh("test")
    assert out["donor"] == "5" and out["updated"] == ["2"], "a proven rev-lookup capture lends"


def case_first_2xx_stamps_once_and_asks_for_a_refresh():
    _fresh_dirs()
    sp = _account("6", NEW, _rules(6), "20261019T100000Z", signed_ok=False)
    from of_client import OFClient
    c = OFClient.from_session_file(sp, proxies=None)
    asked: list[str] = []
    real = sign_rules.request_refresh
    sign_rules.request_refresh = lambda reason: asked.append(reason) or True
    try:
        c._note_signed_ok("https://onlyfans.com/api2/v2/users/me", type("R", (), {"status_code": 400})())
        c._note_signed_ok("https://cdn2.onlyfans.com/files/x.jpg", type("R", (), {"status_code": 200})())
        assert "signed_ok_at" not in _read(sp)["signing"], "a 4xx or an unsigned URL proves nothing"
        for _ in range(2):
            c._note_signed_ok("https://onlyfans.com/api2/v2/users/me", type("R", (), {"status_code": 200})())
    finally:
        sign_rules.request_refresh = real
    assert _read(sp)["signing"]["signed_ok_at"], _read(sp)["signing"]
    assert asked == ["verified 6"], asked


def case_no_stamp_when_the_file_rules_changed_under_the_client():
    _fresh_dirs()
    sp = _account("7", OLD, _rules(7), "20261001T100000Z", signed_ok=False)
    from of_client import OFClient, update_session_file
    c = OFClient.from_session_file(sp, proxies=None)
    update_session_file(sp, lambda d: d["signing"].update(rules=_rules(8)))  # a refresh copied new rules
    c._note_signed_ok("https://onlyfans.com/api2/v2/users/me", type("R", (), {"status_code": 200})())
    assert "signed_ok_at" not in _read(sp)["signing"], "the 2xx proved the old rules"


def case_unknown_live_build_changes_nothing():
    _fresh_dirs()
    out = sign_rules.refresh("test")   # no sessions: the cold seed finds no build
    assert out["skipped"] == "live build unknown", out


def case_never_walks_rules_back():
    # OF flips back to the older build mid-rollout: an account on the newer one keeps it.
    _fresh_dirs()
    _account("1", OLD, _rules(1), "20261019T100000Z")
    newer = _account("2", NEW, _rules(2), "20261018T100000Z")
    before = newer.read_text()
    _live(OLD)
    out = sign_rules.refresh("test")
    assert out["donor"] == "1" and out["updated"] == [], out
    assert newer.read_text() == before


def case_stale_tab_capture_still_takes_the_new_build():
    # Captured after the donor, but from a tab still on the old build.
    _fresh_dirs()
    _account("1", NEW, _rules(1), "20261019T100000Z")
    stale = _account("2", OLD, _rules(2), "20261020T100000Z")
    _live(NEW)
    out = sign_rules.refresh("test")
    assert out["updated"] == ["2"], out
    assert _read(stale)["signing"]["rules"] == _rules(1)


def case_odd_build_ids_compare_by_capture_time():
    _fresh_dirs()
    _account("1", "rev-b", _rules(1), "20261019T100000Z")
    newer = _account("2", "rev-a", _rules(2), "20261020T100000Z")
    older = _account("3", "rev-a", _rules(3), "20261001T100000Z")
    before = newer.read_text()
    _live("rev-b")
    out = sign_rules.refresh("test")
    assert out["updated"] == ["3"], out
    assert newer.read_text() == before
    assert _read(older)["signing"]["rules"] == _rules(1)


def case_copied_rules_never_donate():
    _fresh_dirs()
    _account("1", NEW, _rules(1), "20261019T100000Z")
    _account("2", OLD, _rules(2), "20261001T100000Z")
    _live(NEW)
    sign_rules.refresh("test")
    # Account 2 now reads build NEW but its samples are from OLD. Remove the
    # real donor's session: nothing at NEW verifies any more.
    (account_registry.account_dir("1") / "latest.json").unlink()
    out = sign_rules.refresh("test")
    assert out["donor"] is None, out


def case_fansly_accounts_left_alone():
    _fresh_dirs()
    _account("1", NEW, _rules(1), "20261019T100000Z")
    fansly = _account("9", OLD, _rules(9), "20261001T100000Z", platform="fansly")
    before = fansly.read_text()
    _live(NEW)
    out = sign_rules.refresh("test")
    assert out["updated"] == [], out
    assert fansly.read_text() == before


def case_new_build_triggers_refresh():
    _fresh_dirs()
    seen: list[str] = []
    real = sign_rules.request_refresh
    sign_rules.request_refresh = lambda reason: seen.append(reason) or True
    try:
        live_rev.note(OLD, source="test")
        live_rev.note(OLD, source="test")   # same build: no second trigger
        live_rev.note(NEW, source="test")
    finally:
        sign_rules.request_refresh = real
    assert seen == [f"build {OLD}", f"build {NEW}"], seen


def case_background_refresh_is_single_flight():
    runs: list[str] = []
    gate = threading.Event()
    real, real_auto = sign_rules.refresh, sign_rules._auto

    def _slow(reason):
        runs.append(reason)
        gate.wait(5)
        return {}
    sign_rules.refresh = _slow
    sign_rules._auto = True
    try:
        assert sign_rules.request_refresh("first") is True
        for i in range(5):
            assert sign_rules.request_refresh(f"t{i}") is False, "a run is in flight"
        gate.set()
        deadline = time.time() + 5
        while sign_rules._running and time.time() < deadline:
            time.sleep(0.01)
    finally:
        sign_rules.refresh, sign_rules._auto = real, real_auto
    assert not sign_rules._running
    assert runs == ["first", "queued"], runs


def case_off_until_server_startup_enables_it():
    assert sign_rules._auto is False
    assert sign_rules.request_refresh("test") is False, "no background thread outside the server"


if __name__ == "__main__":
    _harness.run()
