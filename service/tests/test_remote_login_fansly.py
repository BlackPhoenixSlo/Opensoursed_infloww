#!/usr/bin/env python3
from __future__ import annotations

import _harness

import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import typing  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

import requests  # noqa: E402

import accounts as account_registry  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_remote_login_")
ROOT = Path(_TMP.name)
account_registry.SESSIONS_DIR = ROOT
account_registry.ACCOUNTS_DIR = ROOT / "accounts"
account_registry.ACTIVE_FILE = ROOT / "active.json"
account_registry.MIGRATED_MARKER = ROOT / ".migrated"
account_registry.ACCOUNTS_DIR.mkdir()


def _no_requests(self, method, url, *a, **k):
    raise AssertionError(f"the test reached the network: {method} {url}")


requests.Session.request = _no_requests

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
_harness.bootstrap()
client = _harness.make_client()

import fansly_backend  # noqa: E402
import platforms  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import remote_login as rl  # noqa: E402
import remote_login_fansly as fl  # noqa: E402
import server  # noqa: E402

assert account_registry.ACCOUNTS_DIR == ROOT / "accounts", "server import moved the accounts dir"
proxy_registry.REGISTRY_PATH = ROOT / "proxies.json"
proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fansly_login.html"
USER = "creator@example.test"
PASSWORD = "fixture-pass-0451"
TOKEN = "fixture-token-aaaabbbbccccdddd"
ACCOUNT_ID = "900539700124344320"
SESSION_ID = "900539700124344321"
DEVICE_ID = "900539700124344999"
UA = "Mozilla/5.0 (FixtureBrowser) fansly-remote-login-test"
OTP = "135790"


@contextlib.contextmanager
def _patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@contextlib.contextmanager
def _captured_logs():
    h, root = _Logs(), logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        yield h
    finally:
        root.removeHandler(h)
        root.setLevel(old)


def _wipe() -> None:
    for p in ROOT.iterdir():
        if p.name == "proxies.json":
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    account_registry.ACCOUNTS_DIR.mkdir()
    fansly_backend.drop(None)


def _job(**kw) -> rl.RemoteLoginJob:
    now = time.time()
    base = dict(id=uuid.uuid4().hex, email=USER, principal=None, created_at=now,
                expires_at=now + rl.JOB_WINDOW_S, proxy=rl.PROXY_NONE, platform=platforms.FANSLY.key)
    base.update(kw)
    return rl.RemoteLoginJob(**base)


def _identify_ok(session):
    return {"id": session["accountId"], "name": "Fixture Creator", "username": "fixture"}, session


def _read(**over) -> dict:
    session = {"id": SESSION_ID, "accountId": ACCOUNT_ID, "deviceId": None, "token": TOKEN, "metadata": "{}"}
    read = {"session": session, "device_id": DEVICE_ID, "user_agent": UA}
    for k, v in over.items():
        if k in session:
            session[k] = v
        else:
            read[k] = v
    return read


def case_every_platform_names_a_login_driver_with_the_whole_interface():
    import remote_login_onlyfans as ofl

    members = [m for m in rl.LoginDriver.__dict__ if not m.startswith("_")] + list(
        typing.get_type_hints(rl.LoginDriver))
    for p in platforms.ALL:
        missing = [m for m in members if not hasattr(rl.driver(p.key), m)]
        assert not missing, (p.key, missing)
    assert rl.driver(platforms.ONLYFANS.key) is ofl and ofl.SITE == "OnlyFans"
    assert rl.driver(platforms.FANSLY.key) is fl
    assert _job(platform=platforms.ONLYFANS.key).login is ofl and _job().login is fl
    for bad in (None, "", "bogus", "OnlyFans"):
        try:
            rl.driver(bad)
        except ValueError as e:
            assert "unknown platform" in str(e), e
        else:
            raise AssertionError(f"{bad!r} must be refused")


def case_the_registry_imports_no_login_driver():
    import subprocess
    import sys

    code = "import platforms, sys; print(sorted(m for m in sys.modules if m.startswith('remote_login')))"
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(rl.__file__).parent,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "[]", (out.stdout, out.stderr[-500:])


def case_start_route_resolves_one_platform_key():
    seen: list[dict] = []

    def _start(**kw):
        seen.append(kw)
        return _job(platform=kw["platform"])

    base = {"email": "a@b.c", "password": PASSWORD, "backend": "browserbase", "proxy": "none"}
    with _patched(rl, start_login=_start):
        for sent, want in (({}, "onlyfans"),
                           ({"platform": "onlyfans"}, "onlyfans"), ({"platform": "fansly"}, "fansly")):
            r = client.post("/admin/login/remote/start", json={**base, **sent})
            assert r.status_code == 200 and seen[-1]["platform"] == want, (sent, r.text, seen[-1])
        n = len(seen)
        for value in ("myspace", "", None, False, 0, [], {}):
            r = client.post("/admin/login/remote/start", json={**base, "platform": value})
            status = 400 if isinstance(value, str) else 422
            assert r.status_code == status and PASSWORD not in r.text, r.text
        assert len(seen) == n, "a refused Platform must start no job"
    rl._jobs.clear()


def case_fansly_start_accepts_only_server_ip():
    seen: list[dict] = []

    def _start(**kw):
        seen.append(kw)
        return _job(platform=kw["platform"])

    base = {"email": USER, "password": PASSWORD, "backend": "browserbase", "platform": "fansly"}
    with _patched(rl, start_login=_start), _patched(proxy_registry, pool_entries=lambda: ["configured"]):
        for choice in ({}, {"proxy": "none"}):
            r = client.post("/admin/login/remote/start", json={**base, **choice})
            assert r.status_code == 200, r.text
            assert (seen[-1]["proxy"], seen[-1]["proxy_label"], seen[-1]["proxy_defaulted"]) == ("none", "", False)
        for choice in ({"proxy": ""}, {"proxy": "infloww"},
                       {"proxy": "custom", "proxy_label": "isp"}, {"proxy_label": "isp"}):
            r = client.post("/admin/login/remote/start", json={**base, **choice})
            assert r.status_code == 400 and "does not support login proxies" in r.text, r.text
        assert len(seen) == 2


def case_start_route_passes_the_expected_account_to_both_drivers():
    seen: list[dict] = []

    def _start(**kw):
        seen.append(kw)
        return _job(platform=kw["platform"])

    with _patched(rl, start_login=_start):
        for platform in platforms.KEYS:
            r = client.post("/admin/login/remote/start", json={
                "email": USER, "password": PASSWORD, "backend": "browserbase", "proxy": "none",
                "platform": platform, "expected_account_id": ACCOUNT_ID,
            })
            assert r.status_code == 200, r.text
            assert seen[-1]["expected_account_id"] == ACCOUNT_ID
        r = client.post("/admin/login/remote/start", json={
            "email": USER, "password": PASSWORD, "backend": "browserbase", "expected_account_id": 123,
        })
        assert r.status_code == 422 and PASSWORD not in r.text, r.text
        assert len(seen) == len(platforms.KEYS)


def case_conflict_key_is_platform_and_email():
    os.environ["BROWSERBASE_API_KEY"], os.environ["BROWSERBASE_PROJECT_ID"] = "bb-test", "proj-test"
    base = {"email": USER, "password": PASSWORD, "backend": "browserbase", "proxy": "none"}
    try:
        with _patched(rl, _run_login=lambda job, pw: None):
            r = client.post("/admin/login/remote/start", json={**base, "platform": "onlyfans"})
            assert r.status_code == 200, r.text
            r = client.post("/admin/login/remote/start", json=base)
            assert r.status_code == 409 and "this OnlyFans email" in r.text, \
                "an omitted Platform is OnlyFans, so it must clash with an explicit one"
            r = client.post("/admin/login/remote/start", json={**base, "platform": "fansly"})
            assert r.status_code == 200, "another Platform's login for the same email is no clash"
            r = client.post("/admin/login/remote/start", json={**base, "email": USER.upper(), "platform": "fansly"})
            assert r.status_code == 409 and "this Fansly email" in r.text and PASSWORD not in r.text, r.text
    finally:
        for k in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"):
            os.environ.pop(k, None)
        rl._jobs.clear()


def case_capture_takes_exactly_the_snippet_fields():
    s = fl.session_from(_read())
    assert s == {"token": TOKEN, "id": SESSION_ID, "accountId": ACCOUNT_ID, "device_id": DEVICE_ID,
                 "user_agent": UA, "accept_language": "en-US,en;q=0.9", "check_key": None}, s
    assert fl.session_from(_read(deviceId="dev-in-blob"))["device_id"] == "dev-in-blob"
    assert fl.session_from(_read(device_id=None))["device_id"] is None
    assert "metadata" not in s


def case_capture_with_a_missing_field_fails_clearly():
    for over, words in (({"token": None}, "no token"), ({"token": ""}, "no token"),
                        ({"accountId": None}, "no account id"), ({"user_agent": ""}, "no user agent"),
                        ({"session": None}, "no token")):
        try:
            fl.session_from(_read(**over))
        except RuntimeError as e:
            assert words in str(e) and TOKEN not in str(e), (over, e)
        else:
            raise AssertionError(f"{over} must fail")


def _paste_blob(aid: str) -> dict:
    return {"token": TOKEN, "id": SESSION_ID, "accountId": aid, "device_id": DEVICE_ID, "user_agent": UA}


def case_remote_and_paste_ingest_write_the_same_session():
    _wipe()
    hooks: list[str] = []
    paste_aid, remote_aid = "5800001", "5800002"
    with _patched(fansly_backend, identify=_identify_ok), _patched(server, post_bootstrap_hooks=hooks.append):
        r = client.post("/admin/session/fansly", json=_paste_blob(paste_aid))
        assert r.status_code == 200, r.text
        job = _job()
        fl_page = _StaticPage(_read(accountId=remote_aid))
        rl._capture_and_persist(job, fl_page, None)
    assert job.state == rl.STATE_DONE and job.account_id == remote_aid, (job.state, job.error)
    assert job.session_file == fansly_backend.SESSION_FILENAME
    assert hooks == [paste_aid, remote_aid], hooks
    files = {aid: account_registry.ACCOUNTS_DIR / aid / fansly_backend.SESSION_FILENAME
             for aid in (paste_aid, remote_aid)}
    blobs = {aid: json.loads(f.read_text()) for aid, f in files.items()}
    assert {**blobs[paste_aid], "accountId": remote_aid} == blobs[remote_aid], blobs
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in files.values())
    for aid in (paste_aid, remote_aid):
        assert account_registry.get_platform(aid) == platforms.FANSLY.key, aid
    assert account_registry.get_active_account_id() == remote_aid


class _StaticPage:
    def __init__(self, read: dict) -> None:
        self.read = read

    def evaluate(self, script, *_a):
        return self.read


@contextlib.contextmanager
def _no_browser(_job):
    yield None, None


def case_remote_ingest_refuses_like_paste_and_saves_nothing():
    _wipe()
    binds: list[str] = []
    for identify, words in ((lambda s: ({"id": "5899999"}, s), "not 5800003"),
                            (lambda s: (_ for _ in ()).throw(RuntimeError(f"401 auth={s['token']}")),
                             "Fansly did not accept this session")):
        job = _job()
        with _patched(fansly_backend, identify=identify), _captured_logs() as logs, \
                _patched(rl, bind_proxy=lambda j, a: binds.append(a), _browserbase_backend=_no_browser):
            rl._serve(job, secrets=(PASSWORD,), body=lambda page, ctx: rl._capture_and_persist(
                job, _StaticPage(_read(accountId="5800003")), None))
        assert job.state == rl.STATE_ERROR and words in job.error, job.error
        assert TOKEN not in job.error and not any(TOKEN in line for line in logs.lines), (job.error, logs.lines)
    assert binds == [], "a refused session must bind no proxy"
    assert not (account_registry.ACCOUNTS_DIR / "5800003").exists()


def case_token_scrubbed_from_any_later_failure():
    _wipe()
    job = _job()

    def _body(page, ctx):
        fl.capture(job, _StaticPage(_read()), None)
        raise RuntimeError(f"disk said no while writing {{'token': '{TOKEN}', 'pw': '{PASSWORD}'}}")

    with _captured_logs() as logs, _patched(rl, _browserbase_backend=_no_browser):
        rl._serve(job, secrets=(PASSWORD,), body=_body)
    blob = json.dumps(job.public()) + "\n".join(logs.lines)
    assert job.state == rl.STATE_ERROR and job.error.count("***") == 2, job.error
    assert TOKEN not in blob and PASSWORD not in blob, blob
    assert TOKEN not in repr(vars(job)), "the finished job still holds the token"



_ABORTED: list[str] = []


@contextlib.contextmanager
def _local_backend(cfg: dict):
    from playwright.sync_api import sync_playwright

    html = FIXTURE.read_text().replace("__CFG__", json.dumps(cfg))

    def _route(route):
        if route.request.url.startswith(fl.HOME):
            route.fulfill(status=200, content_type="text/html", body=html)
        else:
            _ABORTED.append(route.request.url)
            route.abort()

    @contextlib.contextmanager
    def _backend(job):
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(user_agent=UA)
                context.route("**/*", _route)
                page = context.new_page()
                rl._open_site(job, context, page)
                yield context, page
            finally:
                browser.close()

    with _patched(rl, _browserbase_backend=_backend, POLL_S=0.1):
        yield


def _cfg(**kw) -> dict:
    return {"user": USER, "password": PASSWORD, "otp": None, "token": TOKEN,
            "accountId": ACCOUNT_ID, "sessionId": SESSION_ID, "deviceId": DEVICE_ID, **kw}


def _run(job, password=PASSWORD, *, during=None):
    import threading

    t = threading.Thread(target=rl._run_login, args=(job, password), daemon=True)
    t.start()
    if during:
        during(job)
    t.join(60)
    assert not t.is_alive(), "the login never ended"


def _until(cond, timeout=30.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def _browser_login(cfg: dict, password=PASSWORD, during=None, *, identify=None, **job_options):
    _wipe()
    _ABORTED.clear()
    hooks: list[str] = []
    bound: list[tuple[str, bool]] = []
    session_file = account_registry.ACCOUNTS_DIR / ACCOUNT_ID / fansly_backend.SESSION_FILENAME

    def _bind(job, aid):
        bound.append((aid, session_file.exists()))

    job = _job(nickname="Fixture nick", **job_options)
    with _local_backend(cfg), _patched(fansly_backend, identify=identify or _identify_ok), \
            _patched(server, post_bootstrap_hooks=hooks.append), _patched(rl, bind_proxy=_bind), \
            _captured_logs() as logs:
        _run(job, password, during=during)
    return job, hooks, bound, logs.lines, session_file


def case_fixture_login_captures_and_ingests_the_session():
    job, hooks, bound, lines, session_file = _browser_login(_cfg())
    assert job.state == rl.STATE_DONE, (job.state, job.error)
    assert job.account_id == ACCOUNT_ID and hooks == [ACCOUNT_ID], (job.account_id, hooks)
    assert bound == []
    assert job.message == "session captured; no proxy attached (server IP)"
    saved = json.loads(session_file.read_text())
    assert saved == {"token": TOKEN, "id": SESSION_ID, "accountId": ACCOUNT_ID, "device_id": DEVICE_ID,
                     "user_agent": UA, "accept_language": "en-US,en;q=0.9", "check_key": None}, saved
    meta = json.loads((session_file.parent / "meta.json").read_text())
    assert meta["platform"] == "fansly" and meta["nickname"] == "Fixture nick", meta
    blob = json.dumps(job.public()) + "\n".join(lines)
    assert PASSWORD not in blob and TOKEN not in blob, "a secret reached the job status or a log line"
    assert _ABORTED == [], f"the fake page reached past fansly.com: {_ABORTED}"


def case_fixture_relink_rejects_the_wrong_account():
    job, hooks, bound, _, session_file = _browser_login(_cfg(), expected_account_id="999")
    assert job.state == rl.STATE_ERROR and "expected account 999" in job.error, (job.state, job.error)
    assert hooks == [] and bound == [] and not session_file.exists()


def case_fixture_login_stopped_during_claim_saves_nothing():
    for stop, expected, prove_error in (
        (rl.cancel, rl.STATE_CANCELLED, False),
        (lambda job: setattr(job, "expires_at", 0), rl.STATE_ERROR, False),
        (rl.cancel, rl.STATE_ERROR, True),
    ):
        import threading

        claiming, release = threading.Event(), threading.Event()

        def identify(session):
            claiming.set()
            assert release.wait(15), "claim never released"
            if prove_error:
                raise RuntimeError("fixture prove failed")
            return _identify_ok(session)

        def during(job):
            try:
                assert claiming.wait(15), "claim never started"
                stop(job)
            finally:
                release.set()

        job, hooks, bound, _, session_file = _browser_login(_cfg(), during=during, identify=identify)
        assert job.state == expected, (job.state, job.error)
        if prove_error:
            assert "fixture prove failed" in job.error, job.error
        assert hooks == [] and bound == [] and not session_file.exists()


def case_fixture_dismisses_gates_even_when_sign_in_is_visible():
    with _local_backend(_cfg(preopened=True)), rl._browserbase_backend(_job()) as (_, page):
        fl.fill_login_form(page, USER, PASSWORD)
        assert page.locator("#age-gate, #cookies").count() == 0


def case_fixture_rejects_visible_sign_in_behind_a_blocked_gate():
    with _local_backend(_cfg(preopened=True, blockedGate=True)), rl._browserbase_backend(_job()) as (_, page):
        assert page.locator("#sign-in").is_visible()
        with _patched(rl, FIELD_TIMEOUT_MS=150):
            try:
                fl.fill_login_form(page, USER, PASSWORD, wait_s=1)
            except rl.LoginFormError as e:
                assert "the Fansly login form did not appear" in str(e), e
            else:
                raise AssertionError("accepted the login form behind a blocked gate")


def case_fixture_failed_submit_raises_after_fallback():
    with _local_backend(_cfg()), rl._browserbase_backend(_job()) as (_, page):
        fl.fill_login_form(page, USER, PASSWORD)
        page.locator("#sign-in, #login-pw").evaluate_all("(nodes) => nodes.forEach(node => node.remove())")
        with _patched(rl, FIELD_TIMEOUT_MS=150):
            try:
                fl.submit_login_form(page)
            except rl.LoginFormError as e:
                assert "submit" in str(e)
            else:
                raise AssertionError("submit failed but the driver silently returned")


def case_fixture_token_with_sign_in_still_visible_is_not_logged_in():
    with _local_backend(_cfg(preopened=True)):
        with rl._browserbase_backend(_job()) as (context, page):
            page.evaluate("(session) => localStorage.setItem('session_active_session', JSON.stringify(session))",
                          _read()["session"])
            assert fl.logged_in(page, context) is None


def case_fixture_login_with_otp_goes_through_the_otp_flow():
    asked: list[dict] = []

    def _during(job):
        _until(lambda: job.state == rl.STATE_OTP or job.is_terminal())
        asked.append(job.public())
        job.submit_otp(OTP)

    job, hooks, _bound, lines, session_file = _browser_login(_cfg(otp=OTP), during=_during)
    assert asked and asked[0]["state"] == rl.STATE_OTP, asked
    assert asked[0]["message"] == "Fansly asks for the 2FA code — enter it here or in the live view", asked
    assert job.state == rl.STATE_DONE and hooks == [ACCOUNT_ID], (job.state, job.error)
    assert json.loads(session_file.read_text())["token"] == TOKEN
    assert OTP not in json.dumps(job.public()) + "\n".join(lines)


def case_fixture_wrong_password_fails_fast_and_saves_nothing():
    t0 = time.monotonic()
    job, hooks, bound, lines, session_file = _browser_login(_cfg(), password="wrong-pass-9")
    assert time.monotonic() - t0 < 30, "a refused password must fail fast, not wait out the window"
    assert job.state == rl.STATE_ERROR and "Fansly refused the login" in job.error, (job.state, job.error)
    assert "Invalid username or password" in job.error, job.error
    assert hooks == [] and bound == [] and not session_file.exists()
    assert "wrong-pass-9" not in json.dumps(job.public()) + "\n".join(lines)


try:
    _harness.run()
finally:
    _TMP.cleanup()
