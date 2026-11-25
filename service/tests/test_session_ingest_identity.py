#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import requests  # noqa: E402

import accounts as account_registry  # noqa: E402
import session_bootstrap  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="ingest_identity_")
ROOT = Path(_TMP.name)
account_registry.SESSIONS_DIR = ROOT
account_registry.ACCOUNTS_DIR = ROOT / "accounts"
account_registry.ACTIVE_FILE = ROOT / "active.json"
account_registry.MIGRATED_MARKER = ROOT / ".migrated"
session_bootstrap.SESSIONS_DIR = ROOT
account_registry.ACCOUNTS_DIR.mkdir()


class _NoNetwork(AssertionError):
    pass


_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_LOOPBACK = {"127.0.0.1", "::1", "localhost", None}


def _getaddrinfo(host, *a, **k):
    if host not in _LOOPBACK:
        raise _NoNetwork(f"test tried to resolve {host!r}")
    return _real_getaddrinfo(host, *a, **k)


def _connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in _LOOPBACK:
        raise _NoNetwork(f"test tried to connect to {address!r}")
    return _real_connect(self, address)


def _no_requests(self, method, url, *a, **k):
    raise _NoNetwork(f"unrecorded {method} {url}")


socket.getaddrinfo = _getaddrinfo
socket.socket.connect = _connect
requests.Session.request = _no_requests
try:
    import curl_cffi.requests as _cc
    _cc.Session.request = _no_requests
except ImportError:
    pass

CHUNK = "/* 2313 */"
CHUNK_URL = session_bootstrap.CHUNK_URL_TPL.format(rev="rev1")


class _Resp:
    def __init__(self, body: str) -> None:
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(url, *a, **k):
    if url != CHUNK_URL:
        raise _NoNetwork(f"unrecorded urlopen {url!r}")
    return _Resp(CHUNK)


urllib.request.urlopen = _urlopen
session_bootstrap.derive_rules_from_chunk = lambda code, samples: {"checksum_indexes": [1, 2, 3],
                                                                   "checksum_constant": 7}
session_bootstrap.verify_rules = lambda rules, samples: (True, None)

TS = "20261124T000000Z"
NOW = "2026-11-24T00:00:00Z"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 24, 0, 0, 0, tzinfo=timezone.utc)


session_bootstrap.datetime = _Frozen
account_registry._utc_now = lambda: NOW

_harness.bootstrap()
_harness.make_client()
import fansly_backend  # noqa: E402
import platforms  # noqa: E402
import remote_login as rl  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import User  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

assert account_registry.ACCOUNTS_DIR == ROOT / "accounts", "server import moved the accounts dir"

OWNER = "ingest_owner"


async def _seed_owner() -> None:
    async with get_session() as s:
        s.add(User(id=uuid.uuid4().hex, username=OWNER, password="pw"))


asyncio.run(_seed_owner())


def _owner() -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": OWNER, "password": "pw"})
    assert r.status_code == 200, r.text
    return c


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(logging.Formatter("%(message)s").format(record)
                          + (logging.Formatter().formatException(record.exc_info) if record.exc_info else ""))


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


@contextlib.contextmanager
def _patched(obj, **attrs):
    old = {k: getattr(obj, k, None) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def _wipe() -> None:
    for p in ROOT.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    account_registry.ACCOUNTS_DIR.mkdir()
    fansly_backend.drop(None)


def _tree() -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(ROOT)): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in sorted(ROOT.rglob("*")) if p.is_file()}


def _seed(aid: str, files: dict[str, str]) -> None:
    adir = account_registry.ACCOUNTS_DIR / aid
    adir.mkdir()
    for name, text in files.items():
        (adir / name).write_text(text)


def _of_creator(aid: str) -> None:
    _seed(aid, {
        "meta.json": json.dumps({"id": aid, "nickname": "Old", "color": "#123456", "platform": "onlyfans",
                                 "name": "Real", "created_at": "2026-01-01T00:00:00Z",
                                 "last_used_at": "2026-02-01T00:00:00Z"}, indent=2),
        "latest.json": json.dumps({"session": "session_20260101T000000Z.json", "ts": "20260101T000000Z"}, indent=2),
        "session_20260101T000000Z.json": '{"old": true}',
    })


def _fansly_creator(aid: str, token: str = "old-token") -> None:
    _seed(aid, {
        "meta.json": json.dumps({"id": aid, "nickname": "Fan", "color": "#654321", "platform": "fansly",
                                 "name": "Fan", "created_at": "2026-01-01T00:00:00Z",
                                 "last_used_at": None}, indent=2),
        "fansly_session.json": json.dumps({"token": token, "id": "sess", "accountId": aid,
                                           "device_id": "dev-old", "user_agent": "UA/F"}, indent=2) + "\n",
    })


TOKEN = "fansly-secret-token-0123456789"


def _blob(aid: str, **kw) -> dict:
    return {"token": TOKEN, "id": "sess-1", "accountId": aid, "user_agent": "UA/F", **kw}


def _no_identify(session):
    raise AssertionError("identify must not run")




def case_identify_fetches_device_id_before_me_and_writes_nothing():
    _wipe()
    aid = "5100001"
    seen: list[tuple[str, str, str]] = []

    def _recorder(self, method, path, **kw):
        seen.append((method, path, self.session.device_id))
        if path == "/device/id":
            return "dev-123"
        if path == "/account/me":
            return {"account": {"id": aid, "displayName": "Mia", "username": "mia"}}
        raise _NoNetwork(f"unrecorded {method} {path}")

    session = {"token": TOKEN, "id": "s", "accountId": aid, "device_id": None, "user_agent": "UA/F",
               "accept_language": "en-US,en;q=0.9", "check_key": None}
    before = _tree()
    with _patched(fansly_backend.FanslyShimClient, _request=_recorder):
        me, blob = fansly_backend.identify(dict(session))
        assert seen == [("GET", "/device/id", ""), ("GET", "/account/me", "dev-123")], seen
        assert me["id"] == aid and me["name"] == "Mia", me
        assert blob["device_id"] == "dev-123" and blob["device_id_ts"] > 0, blob
        assert {k: blob[k] for k in session if k != "device_id"} == {k: v for k, v in session.items()
                                                                       if k != "device_id"}, blob
        assert _tree() == before, "identify wrote a file"
        assert aid not in fansly_backend._pool, "identify pooled its client"

        seen.clear()
        me, blob = fansly_backend.identify({**session, "device_id": "dev-have"})
        assert seen == [("GET", "/account/me", "dev-have")], seen
        assert blob["device_id"] == "dev-have" and "device_id_ts" not in blob, blob
        assert _tree() == before




def case_fansly_me_raises_is_400_nothing_on_disk_token_never_echoed():
    _wipe()
    aid = "5200001"

    def _boom(session):
        raise RuntimeError(f"GET /account/me -> 401 headers={{'authorization': '{session['token']}'}}")

    c = _owner()
    before = _tree()
    with _patched(fansly_backend, identify=_boom), _captured_logs() as logs:
        r = c.post("/admin/session/fansly", json=_blob(aid))
        assert any("not proven" in line and "***" in line for line in logs.lines), logs.lines
    assert r.status_code == 400, (r.status_code, r.text)
    assert "401" in r.json()["detail"], r.text
    assert TOKEN not in r.text, "the 400 echoed the token"
    assert not any(TOKEN in line for line in logs.lines), "a log line carried the token"
    assert _tree() == before, "a refused link wrote"


def case_fansly_id_mismatch_or_empty_is_400_nothing_on_disk():
    _wipe()
    aid = "5300001"
    c = _owner()
    before = _tree()
    for got in ("5399999", ""):
        with _patched(fansly_backend, identify=lambda s, got=got: ({"id": got, "name": "X"}, s)):
            r = c.post("/admin/session/fansly", json=_blob(aid))
        assert r.status_code == 400, (got, r.status_code, r.text)
        assert TOKEN not in r.text
        assert _tree() == before, got


def case_fansly_bad_id_is_400():
    _wipe()
    with _patched(fansly_backend, identify=_no_identify):
        r = _owner().post("/admin/session/fansly", json=_blob(".."))
    assert r.status_code == 400, (r.status_code, r.text)
    assert _tree() == {}, _tree()


def case_fansly_on_onlyfans_creator_is_409_untouched():
    _wipe()
    aid = "5400001"
    _of_creator(aid)
    before = _tree()
    with _patched(fansly_backend, identify=_no_identify):
        r = _owner().post("/admin/session/fansly", json=_blob(aid))
    assert r.status_code == 409, (r.status_code, r.text)
    assert r.json()["detail"], r.text
    assert _tree() == before, "the OnlyFans Creator's files changed"


def case_fansly_collision_rechecked_after_identify():
    _wipe()
    aid = "5400002"

    raced: dict = {}

    def _raced(session):
        _of_creator(aid)
        raced["tree"] = _tree()
        return {"id": aid, "name": "X"}, session

    with _patched(fansly_backend, identify=_raced):
        r = _owner().post("/admin/session/fansly", json=_blob(aid))
    assert r.status_code == 409, (r.status_code, r.text)
    assert _tree() == raced["tree"], "the raced OnlyFans Creator's files or the active pick changed"


def case_fansly_success_writes_0600_meta_and_runs_hooks():
    _wipe()
    aid = "5500001"
    hooks: list[str] = []

    def _identify(session):
        return {"id": aid, "name": "Mia", "username": "mia"}, {**session, "device_id": "dev-9", "device_id_ts": 1.5}

    with _patched(fansly_backend, identify=_identify), _patched(server, post_bootstrap_hooks=hooks.append):
        r = _owner().post("/admin/session/fansly", json=_blob(aid))
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"ok": True, "account_id": aid, "platform": "fansly", "name": "Mia"}, r.json()
    f = account_registry.ACCOUNTS_DIR / aid / fansly_backend.SESSION_FILENAME
    assert f.stat().st_mode & 0o777 == 0o600, oct(f.stat().st_mode)
    written = json.loads(f.read_text())
    assert written["token"] == TOKEN and written["accountId"] == aid, written
    assert written["device_id"] == "dev-9" and written["device_id_ts"] == 1.5, written
    meta = account_registry.load_meta(aid)
    assert meta["platform"] == "fansly" and meta["name"] == "Mia" and meta["nickname"] == "Mia", meta
    assert hooks == [aid], hooks
    assert account_registry.get_stored_active_account_id() == aid
    row = next(a for a in account_registry.list_accounts() if a["id"] == aid)
    assert row["has_session"] is True, row


def case_fansly_relink_restarts_the_live_connection_on_the_new_token():
    _wipe()
    aid = "5600001"
    _fansly_creator(aid, token="old-token")
    old = server._load_client(aid)
    assert old.session.token == "old-token"
    restarted, cleared, linked = [], [], []
    with _patched(fansly_backend, identify=lambda s: ({"id": aid, "name": "Fan"}, {**s, "device_id": "dev-new"})), \
            _patched(server, _restart_account_pump=restarted.append, _kick_clear_session_dead=cleared.append,
                     _sync_and_link_after_bootstrap=linked.append):
        r = _owner().post("/admin/session/fansly", json=_blob(aid))
    assert r.status_code == 200, (r.status_code, r.text)
    assert restarted == [aid] and cleared == [aid] and linked == [aid], (restarted, cleared, linked)
    new = server._load_client(aid)
    assert new is not old and new.session.token == TOKEN, "the relink kept the stale client"
    assert account_registry.get_platform(aid) == "fansly"



URL = "https://onlyfans.com/api2/v2/users/me"


def _curl(aid: str) -> str:
    return (f"curl '{URL}' -H 'user-id: {aid}' -H 'x-bc: bc1' -H 'x-of-rev: rev1' "
            f"-H 'sign: 1:abc:ff:2' -H 'time: 1700000000000' -H 'user-agent: UA/1' "
            f"-H 'x-relay-static-param: SP' -b 'sess=s1; auth_id={aid}'")


def _cookie(name: str, value: str) -> dict:
    return {"name": name, "value": value, "domain": ".onlyfans.com", "path": "/",
            "expires": -1, "httpOnly": False, "secure": True, "sameSite": "None"}


def _session_dump(aid: str) -> str:
    return json.dumps({
        "captured_at": TS,
        "profile_id": "paste-curl",
        "page_url": URL,
        "headers": {"user_id": aid, "x_bc": "bc1", "x_of_rev": "rev1", "user_agent": "UA/1"},
        "signing": {
            "rules": {"static_param": "SP", "start": "1", "end": "2",
                      "checksum_indexes": [1, 2, 3], "checksum_constant": 7},
            "samples": [{"sha1Hex": "abc", "checksumValue": 255, "url": URL,
                         "time": "1700000000000", "user_id": aid}],
            "last_sign_seen": "1:abc:ff:2",
            "last_time_seen": 1700000000000,
            "chunk_2313_url": CHUNK_URL,
            "chunk_2313_file": f"chunk_2313_{TS}.js",
            "static_param_source": "curl",
        },
        "cookies": [_cookie("sess", "s1"), _cookie("auth_id", aid)],
        "local_storage": {},
    }, indent=2)


class _Hooked:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, aid: str):
        self.calls.append(aid)
        return type("C", (), {"user_id": int(aid), "x_of_rev": "rev1"})()


def _bootstrap(aid: str, **kw):
    hooks = _Hooked()
    with _patched(server, post_bootstrap_hooks=hooks):
        r = _owner().post("/admin/session/bootstrap", json={"mode": "paste-curl", "curl": _curl(aid), **kw})
    return r, hooks.calls


def _f(text: str, mode: int = 0o644) -> tuple[bytes, int]:
    return text.encode(), mode


def _mode() -> int:
    probe = ROOT / ".probe"
    probe.write_text("")
    m = probe.stat().st_mode & 0o777
    probe.unlink()
    return m


def case_bootstrap_fresh_id_is_todays_outcome():
    _wipe()
    aid = "4100001"
    r, hooks = _bootstrap(aid, nickname="Bella")
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"ok": True, "session_file": f"session_{TS}.json", "account_id": aid,
                        "user_id": int(aid), "x_of_rev": "rev1"}, r.json()
    assert hooks == [aid], hooks
    m = _mode()
    color = account_registry._COLORS[abs(hash(aid)) % len(account_registry._COLORS)]
    d = f"accounts/{aid}"
    assert _tree() == {
        "active.json": _f(json.dumps({"active_account_id": aid}, indent=2), m),
        f"{d}/chunk_2313_{TS}.js": _f(CHUNK, m),
        f"{d}/latest.json": _f(json.dumps({"session": f"session_{TS}.json", "ts": TS}, indent=2), m),
        f"{d}/meta.json": _f(json.dumps({"id": aid, "nickname": "Bella", "color": color, "platform": "onlyfans",
                                         "name": None, "created_at": NOW, "last_used_at": NOW}, indent=2), m),
        f"{d}/session_{TS}.json": _f(_session_dump(aid), m),
    }, _tree()


def case_bootstrap_existing_onlyfans_id_is_todays_outcome():
    _wipe()
    aid = "4200001"
    _of_creator(aid)
    r, hooks = _bootstrap(aid)
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json() == {"ok": True, "session_file": f"session_{TS}.json", "account_id": aid,
                        "user_id": int(aid), "x_of_rev": "rev1"}, r.json()
    assert hooks == [aid], hooks
    m = _mode()
    d = f"accounts/{aid}"
    assert _tree() == {
        "active.json": _f(json.dumps({"active_account_id": aid}, indent=2), m),
        f"{d}/chunk_2313_{TS}.js": _f(CHUNK, m),
        f"{d}/latest.json": _f(json.dumps({"session": f"session_{TS}.json", "ts": TS}, indent=2), m),
        f"{d}/meta.json": _f(json.dumps({"id": aid, "nickname": "Old", "color": "#123456", "platform": "onlyfans",
                                         "name": "Real", "created_at": "2026-01-01T00:00:00Z",
                                         "last_used_at": NOW}, indent=2), m),
        f"{d}/session_20260101T000000Z.json": _f('{"old": true}', m),
        f"{d}/session_{TS}.json": _f(_session_dump(aid), m),
    }, _tree()


def case_bootstrap_on_fansly_creator_is_409_untouched():
    _wipe()
    aid = "4300001"
    _fansly_creator(aid)
    before = _tree()
    r, hooks = _bootstrap(aid)
    assert r.status_code == 409, (r.status_code, r.text)
    assert r.json()["detail"], r.text
    assert hooks == [], hooks
    assert _tree() == before, "the Fansly Creator's directory changed"




def case_ensure_platform_passes_and_raises_by_table():
    _wipe()
    of, fan = platforms.ONLYFANS.key, platforms.FANSLY.key
    _of_creator("6000001")
    _seed("6000002", {"meta.json": json.dumps({"id": "6000002", "platform": "myspace"})})
    _seed("6000003", {"latest.json": "{}"})
    _seed("6000004", {"session_20260101T000000Z.json": "{}"})
    _seed("6000005", {"meta.json": "{not json", "latest.json": "{}"})
    _fansly_creator("6000006")
    _seed("6000007", {"fansly_session.json": "{}"})
    _seed("6000008", {"meta.json": "[1, 2]", "fansly_session.json": "{}"})
    before = _tree()
    for aid in ("6999999", "6000001", "6000002", "6000003", "6000004", "6000005", ".."):
        account_registry.ensure_platform(aid, of)
    for aid in ("6999999", "6000006", "6000007", "6000008"):
        account_registry.ensure_platform(aid, fan)
    for aid, key in (("6000006", of), ("6000007", of), ("6000008", of),
                     ("6000001", fan), ("6000002", fan), ("6000003", fan), ("6000005", fan)):
        try:
            account_registry.ensure_platform(aid, key)
        except account_registry.PlatformCollision as e:
            assert str(e), aid
        else:
            raise AssertionError(f"{aid} as {key}: no collision")
    assert _tree() == before, "ensure_platform wrote"




class _Ctx:
    def cookies(self, _urls=None):
        return [{"name": "auth_id", "value": "4400001", "domain": ".onlyfans.com", "path": "/"}]


class _Page:
    def goto(self, *_a, **_k):
        return None

    def evaluate(self, script, *_a):
        if "__relayCapture" in script:
            return {"url": URL, "headers": {"user-id": "4400001", "x-bc": "bc", "x-of-rev": "r",
                                            "sign": "1:a:b:2", "time": "1"},
                    "rules": {"static_param": "SP"}}
        return "UA/2"

    def wait_for_timeout(self, _ms):
        return None


def case_capture_on_fansly_creator_fails_job_before_proxy_bind():
    _wipe()
    aid = "4400001"
    _fansly_creator(aid)
    before = _tree()
    calls: list[str] = []

    @contextlib.contextmanager
    def _backend(job):
        yield None, None

    now = time.time()
    job = rl.RemoteLoginJob(id=uuid.uuid4().hex, email="e@x.com", principal=None,
                            created_at=now, expires_at=now + rl.JOB_WINDOW_S)
    with _patched(rl, _browserbase_backend=_backend, bind_proxy=lambda j, a: calls.append(("bind", a))), \
            _patched(session_bootstrap, from_request=lambda *a, **k: calls.append("persist")), \
            _patched(server, post_bootstrap_hooks=lambda a: calls.append(("hooks", a))):
        rl._serve(job, secrets=(), body=lambda page, ctx: rl._capture_and_persist(job, _Page(), _Ctx()))
    assert job.state == rl.STATE_ERROR, (job.state, job.message)
    assert "Fansly" in (job.error or ""), job.error
    assert calls == [], calls
    assert _tree() == before


try:
    _harness.run()
finally:
    _TMP.cleanup()
