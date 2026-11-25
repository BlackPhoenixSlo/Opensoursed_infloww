import dataclasses
import json
import os
import re
import signal
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

import capture as capture_cmd
import live_entry
import prove
from live_entry import (PROOF_CREATOR, copy_session, expected_creator, link_account, preflight_problems, serve_wait,
                        session_dir_refusal)

ROOT = Path(__file__).resolve().parents[2]
X_BC = "bc0123456789abcdef0123456789abcdef012345"
COOKIE = "sess-value-0123456789"


def _session_dir(root: Path, meta=False) -> Path:
    d = root / "some-account-dir"
    d.mkdir(parents=True)
    (d / "session_20261120T000000Z.json").write_text(json.dumps({
        "headers": {"user_id": PROOF_CREATOR, "x_bc": X_BC, "user_agent": "UA/1"},
        "cookies": [{"name": "sess", "value": COOKIE, "domain": ".onlyfans.com", "path": "/"}],
        "local_storage": {}}))
    (d / "latest.json").write_text(json.dumps({"session": "session_20261120T000000Z.json", "ts": "x"}))
    if meta:
        (d / "meta.json").write_text(json.dumps({"id": PROOF_CREATOR, "nickname": "mine"}))
    return d



@pytest.mark.parametrize("of, make, want", [
    ("live", None, "--session-dir is required"),
    ("live", "missing", "not an account session dir"),
    ("live", "empty", "not an account session dir"),
    ("live", "ok", None),
    ("fake", "ok", "live mode only"),
    ("fake", None, None),
], ids=["live, none", "live, no such dir", "live, no latest.json", "live, session dir", "fake with one", "fake"])
def test_session_dir_refusal(tmp_path, of, make, want):
    arg = {None: None, "missing": tmp_path / "nope", "ok": _session_dir(tmp_path)}.get(make)
    if make == "empty":
        arg = tmp_path / "empty"
        arg.mkdir()
    got = session_dir_refusal(of, arg)
    assert (got is None) if want is None else (want in got)


@pytest.mark.parametrize("argv", [
    ["--of", "live", "--proof", "tracer.create-list"],
    ["--of", "live", "serve"],
    ["--of", "live", "capture", "--abort", "--proof", "tracer.create-list"],
])
def test_live_without_session_dir_exits_non_zero_before_anything_starts(monkeypatch, capsys, argv):
    monkeypatch.setattr(prove, "prove", lambda *a, **k: pytest.fail("the run started"))
    assert prove.main(argv) != 0
    assert "--session-dir is required" in capsys.readouterr().err


def test_fake_with_a_session_dir_is_refused(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(prove, "prove", lambda *a, **k: pytest.fail("the run started"))
    assert prove.main(["--of", "fake", "--session-dir", str(_session_dir(tmp_path))]) != 0
    assert "live mode only" in capsys.readouterr().err


def test_wrong_creator_is_a_fake_only_fault(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(prove, "prove", lambda *a, **k: pytest.fail("the run started"))
    assert prove.main(["--of", "live", "--session-dir", str(_session_dir(tmp_path)), "--fault", "wrong-creator"]) != 0
    assert "fake mode only" in capsys.readouterr().err


def test_live_never_defaults_the_proof_fan(monkeypatch, tmp_path):
    got = {}
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: got.update(fan=fan, **k) or 0)
    monkeypatch.setattr(prove.signal, "signal", lambda *a: None)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    sess = _session_dir(tmp_path)
    assert prove.main(["--of", "live", "--session-dir", str(sess)]) == 0
    assert got == {"fan": None, "capture": None, "of": "live", "session_src": sess, "serve": False,
                   "expected": PROOF_CREATOR, "lockout": False, "reverify": None,
                   "cotag_partner": None}


def test_reverify_needs_an_evidence_folder_and_runs_no_proof(monkeypatch, capsys, tmp_path):
    got = {}
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: got.update(ids=ids, **k) or 0)
    monkeypatch.setattr(prove.signal, "signal", lambda *a: None)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    sess = _session_dir(tmp_path)
    assert prove.main(["--of", "live", "--session-dir", str(sess), "reverify"]) == 2
    assert "--evidence" in capsys.readouterr().err
    assert prove.main(["--of", "live", "--session-dir", str(sess), "reverify", "--evidence", str(tmp_path / "no")]) == 2
    assert "no kept picture" in capsys.readouterr().err and not got
    ev = tmp_path / "ev"
    (ev / "settings--profile-cover-avatar").mkdir(parents=True)
    (ev / "settings--profile-cover-avatar" / "undo-3-before.jpg").write_bytes(b"\xff\xd8\xff")
    assert prove.main(["--of", "live", "--session-dir", str(sess), "reverify", "--evidence", str(ev)]) == 0
    assert got["ids"] == [] and got["reverify"] == ev and got["serve"] is False and got["capture"] is None
    assert prove.main(["--of", "live", "--session-dir", str(sess), "--evidence", str(ev)]) == 2


def test_main_resolves_wrong_creator_once_and_fakeof_never_sees_it(monkeypatch):
    got = {}
    monkeypatch.setattr(prove, "prove", lambda ids, fault, fan, **k: got.update(fault=fault, **k) or 0)
    monkeypatch.setattr(prove.signal, "signal", lambda *a: None)
    monkeypatch.setattr(prove.os, "setpriority", lambda *a: None)
    assert prove.main(["--of", "fake", "--fault", "wrong-creator"]) == 0
    assert got["fault"] is None and got["expected"] == expected_creator("fake", "wrong-creator")


@pytest.mark.parametrize("dirty, want", [
    ((), (False, False, False)),
    (("app",), (True, False, False)),
    (("service",), (False, True, False)),
    (("scripts/of-live-proof",), (False, False, True)),
    (("soak",), (False, False, True)),
])
def test_revision_flags_each_tree_with_uncommitted_changes(monkeypatch, dirty, want):
    def git(*args):
        if args[0] == "status":
            return "".join(f" M {t}/x.py\n" for t in args[3:] if t in dirty)
        return "abc\n"
    monkeypatch.setattr(prove, "_git", git)
    rev = prove.revision()
    assert (rev["app_dirty"], rev["relay_dirty"], rev["harness_dirty"]) == want and rev["head"] == "abc"


def test_expected_creator():
    from fake_layer import creator_id
    assert expected_creator("live", None) == PROOF_CREATOR == "80000112"
    assert expected_creator("fake", None) == creator_id(1)
    assert expected_creator("fake", "wrong-creator") not in (creator_id(1), PROOF_CREATOR)



def test_copy_session_lands_in_the_temp_dir_and_prints_nothing(tmp_path, capsys):
    src = _session_dir(tmp_path / "src")
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    dst = copy_session(src, tmp_path / "run")
    assert dst == tmp_path / "run" / "sessions" / "accounts" / PROOF_CREATOR
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before
    assert all((dst / n).read_bytes() == b for n, b in before.items())
    assert json.loads((dst / "meta.json").read_text())["id"] == PROOF_CREATOR
    assert json.loads((tmp_path / "run" / "sessions" / "active.json").read_text()) == {
        "active_account_id": PROOF_CREATOR}
    assert capsys.readouterr() == ("", "")


def test_copy_session_keeps_its_own_meta(tmp_path):
    dst = copy_session(_session_dir(tmp_path / "src", meta=True), tmp_path / "run")
    assert json.loads((dst / "meta.json").read_text())["nickname"] == "mine"


def test_link_account_writes_the_row_and_owner_link_once(tmp_path):
    db = tmp_path / "relay.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE users(id TEXT PRIMARY KEY);
        CREATE TABLE accounts(id TEXT PRIMARY KEY, nickname TEXT, color TEXT, is_active_default INT,
                              created_at TEXT, last_used_at TEXT);
        CREATE TABLE user_accounts(user_id TEXT REFERENCES users(id), account_id TEXT REFERENCES accounts(id),
                                   created_at TEXT, PRIMARY KEY(user_id, account_id));
        INSERT INTO users VALUES ('u1');""")
    con.commit()
    con.close()
    link_account(db, "u1")
    link_account(db, "u1")
    con = sqlite3.connect(db)
    assert con.execute("SELECT id FROM accounts").fetchall() == [(PROOF_CREATOR,)]
    assert con.execute("SELECT user_id, account_id FROM user_accounts").fetchall() == [("u1", PROOF_CREATOR)]


def test_a_live_stack_that_fails_to_start_deletes_its_temp_dir_and_session_copy(tmp_path, monkeypatch, capsys):
    run_tmp = tmp_path / "run"
    seen = {}

    class P:
        pid = 999999999

        def __init__(self, cmd, env=None, **_):
            seen.setdefault("cmds", []).append((cmd, env))

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    def mkdtemp(prefix=""):
        run_tmp.mkdir()
        return str(run_tmp)

    def boom(*a, **k):
        seen["copied"] = (run_tmp / "sessions" / "accounts" / PROOF_CREATOR / "latest.json").exists()
        raise RuntimeError("relay not ready")

    monkeypatch.setattr(prove.subprocess, "Popen", P)
    monkeypatch.setattr(prove.os, "killpg", lambda *a: None)
    monkeypatch.setattr(prove.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(prove, "_wait_http", boom)
    (tmp_path / "ev").mkdir()
    with pytest.raises(RuntimeError, match="relay not ready"):
        prove.Stack(tmp_path / "ev", app=False, session_src=_session_dir(tmp_path / "src"))
    assert seen["copied"] and not run_tmp.exists()
    (cmd, env), = seen["cmds"]
    assert cmd[-1].endswith("relay_live.py") and "OF_API_ORIGIN" not in env
    assert not {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"} & set(env)
    assert COOKIE not in json.dumps(env) and X_BC not in json.dumps(env)
    assert capsys.readouterr() == ("", "")


def test_stack_close_deletes_the_temp_dir_even_when_teardown_is_interrupted(tmp_path, monkeypatch):
    st = prove.Stack.__new__(prove.Stack)
    st.tmp = tmp_path / "run"
    (st.tmp / "sessions" / "accounts" / PROOF_CREATOR).mkdir(parents=True)

    def interrupted():
        raise KeyboardInterrupt

    st._close = interrupted
    with pytest.raises(KeyboardInterrupt):
        st.close()
    assert not st.tmp.exists()



def _proof(id, kind="live", tags=(), arm=True, of_read=None, browser=False):
    from proof_core import Proof, Write
    w = (Write("POST", "/api2/v2/lists"),) if arm else ()
    return Proof(id=id, phase=0, page="collections/index", control="x", kind=kind, tags=frozenset(tags), arm=w,
                 undo=(Write("DELETE", "/api2/v2/lists/{id}"),) if arm else (), of_read=of_read,
                 trigger=(("fetch", "POST", "/api2/v2/lists", {}, "allowed"),) if browser else (("click", "#x"),),
                 effect=(lambda b, a: True) if arm else None)


LIVE_PROOFS = {"p.mocked": _proof("p.mocked", kind="mocked"), "p.stream": _proof("p.stream", tags={"stream_start"}),
               "p.irrev": _proof("p.irrev", tags={"irreversible"}), "p.write": _proof("p.write"),
               "p.read": _proof("p.read", arm=False, of_read=lambda get, fan: get("/api2/v2/lists", {})),
               "p.ui": _proof("p.ui", arm=False), "p.bwrite": _proof("p.bwrite", browser=True),
               "p.bread": _proof("p.bread", arm=False, browser=True)}
LIVE_PROOFS["p.notrig"] = dataclasses.replace(LIVE_PROOFS["p.write"], id="p.notrig", trigger=())
LIVE_PROOFS["p.mnotrig"] = dataclasses.replace(LIVE_PROOFS["p.mocked"], id="p.mnotrig", trigger=())


@pytest.mark.parametrize("pid, of, want", [
    ("p.mocked", "live", ("parked", "mocked: not run live")),
    ("p.stream", "live", ("parked", "stream start: needs the owner's stream go; no owner-go run path yet (ticket 126)")),
    ("p.irrev", "live", ("parked", "irreversible: needs the owner's go naming this proof; no owner-go run path yet "
                                   "(ticket 126)")),
    ("p.write", "live", None), ("p.read", "live", None),
    ("p.bwrite", "live", ("refused", live_entry.LIVE_BROWSER_STEPS)),
    ("p.bread", "live", None), ("p.bwrite", "fake", None),
    ("p.ui", "live", None),
    ("p.write", "fake", None), ("p.mocked", "fake", None), ("p.read", "fake", None),
    ("p.notrig", "fake", ("refused", live_entry.NO_TRIGGER)), ("p.notrig", "live", ("refused", live_entry.NO_TRIGGER)),
    ("p.mnotrig", "fake", ("parked", "mocked: no trigger; covered by the Mirror check")),
])
def test_live_refusal(pid, of, want):
    assert live_entry.live_refusal(LIVE_PROOFS[pid], of, "555") == want


@pytest.mark.parametrize("pid, of, want", [
    ("p.write", "live", ("refused", live_entry.LIVE_BROWSER_STEPS)),
    ("p.read", "live", ("refused", live_entry.LIVE_BROWSER_STEPS)),
    ("p.ui", "live", None), ("p.write", "fake", None),
    ("p.mocked", "live", ("parked", "mocked: not run live")),
])
def test_live_refusal_of_a_capture(pid, of, want):
    assert live_entry.live_refusal(LIVE_PROOFS[pid], of, "555", capture="send") == want


class _NoStack:
    fake, of, relay, app, login = None, "live", "http://127.0.0.1:1", "http://127.0.0.1:2", ("ofmproof", "pw")

    def __init__(self, evidence, fault=None, app=True, session_src=None):
        self.session_src = session_src

    def wait_app(self):
        pass

    def session_dir(self, creator):
        return self.session_src

    def close(self):
        return {"temp_dir": "x", "temp_deleted": True, "restored": []}


def _stub_live_run(monkeypatch, tmp_path, stack=_NoStack):
    from contextlib import contextmanager
    from types import SimpleNamespace
    armed = []
    monkeypatch.setattr(prove, "ROOT", tmp_path)
    monkeypatch.setattr(prove, "ALL", LIVE_PROOFS)
    monkeypatch.setattr(prove, "Stack", stack)
    monkeypatch.setattr(prove, "AppBrowser", lambda pw, st, ev: SimpleNamespace(
        ctx=SimpleNamespace(request=None, add_init_script=lambda s: None), offhost=lambda: [],
        browser=SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(prove, "bootstrap", lambda st, ab: PROOF_CREATOR)
    monkeypatch.setattr(prove, "load_session", lambda d: {})
    monkeypatch.setattr(prove, "session_secrets", lambda s: [COOKIE])
    monkeypatch.setattr(prove, "holds_lock", lambda c: True)
    monkeypatch.setattr(prove, "_relay_client", lambda st, ab: None)
    monkeypatch.setattr(live_entry, "preflight", lambda *a: [])
    monkeypatch.setattr(prove, "run_proof", lambda p, *a, **k: armed.append(p.id) or {
        "proof": p.id, "state": "pass", "problems": [], "undo": []})
    monkeypatch.setattr(capture_cmd, "start", lambda *a, **k: armed.append("capture browser"))

    @contextmanager
    def pw():
        yield None

    def run(ids, capture=None):
        code = prove._prove(ids, None, "sha", "r", "f", "", pw, "555", capture, of="live", session_src=tmp_path,
                            expected=PROOF_CREATOR)
        return code, json.loads((tmp_path / "slop" / "evidence" / "f" / "report.json").read_text())
    return run, armed


def test_a_live_run_parks_or_refuses_and_nothing_arms(monkeypatch, tmp_path):
    run, armed = _stub_live_run(monkeypatch, tmp_path)
    code, rep = run(["p.mocked", "p.stream", "p.irrev", "p.bwrite"])
    assert armed == []
    assert [p["proof"] for p in rep["parked"]] == ["p.mocked", "p.stream", "p.irrev"]
    assert rep["refused"] == [{"proof": "p.bwrite", "reason": live_entry.LIVE_BROWSER_STEPS}]
    assert code == 1 and rep["exit"] == 1


def test_a_live_run_starts_reading_and_writing_proofs(monkeypatch, tmp_path):
    run, armed = _stub_live_run(monkeypatch, tmp_path)
    _, rep = run(["p.write", "p.read"])
    assert armed == ["p.read", "p.write"] and rep["refused"] == [] and rep["parked"] == []



class _Reply:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _reader_stack(fake):
    st = prove.Stack.__new__(prove.Stack)
    st.relay, st.fake, st.account = "http://127.0.0.1:1", fake, PROOF_CREATOR
    return st


@pytest.mark.parametrize("fake", [None, object()], ids=["live", "fake"])
def test_of_get_reads_through_the_relay_in_both_modes(monkeypatch, fake):
    from urllib.parse import parse_qs, urlsplit
    seen = []
    monkeypatch.setattr(prove._DIRECT, "open", lambda req, timeout: seen.append(req) or _Reply(b'{"list": []}'))
    assert _reader_stack(fake).of_get("/api2/v2/lists", {"offset": 0, "limit": 50}) == {"list": []}
    (req,) = seen
    u = urlsplit(req.full_url)
    assert (u.netloc, u.path, req.get_method()) == ("127.0.0.1:1", "/__proof/of-read", "GET")
    assert parse_qs(u.query) == {"path": ["/api2/v2/lists"], "query": ["offset=0&limit=50"]}
    assert req.get_header("X-account-id") == PROOF_CREATOR
    assert [k.lower() for k in req.headers] == ["x-account-id"]


def test_of_get_names_the_relays_refusal(monkeypatch):
    import io

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"detail": "guard"}'))

    monkeypatch.setattr(prove._DIRECT, "open", refuse)
    with pytest.raises(RuntimeError, match=r"/api2/v2/lists: the Relay answered 403"):
        _reader_stack(None).of_get("/api2/v2/lists", {})


@pytest.mark.parametrize("ids, capture", [
    (["p.write"], "send"), (["p.write"], "abort"), (["p.bwrite"], None), (["p.mocked"], "send"),
], ids=["capture send, armed", "capture --abort, armed", "prove, browser-step armed", "capture, mocked"])
def test_a_live_capture_browser_never_opens_for_a_refused_proof(monkeypatch, tmp_path, ids, capture):
    run, armed = _stub_live_run(monkeypatch, tmp_path)
    _, rep = run(ids, capture)
    assert armed == [] and len(rep["refused"]) + len(rep["parked"]) == 1


def test_a_live_browser_step_proof_that_may_start_opens_it(monkeypatch, tmp_path):
    run, armed = _stub_live_run(monkeypatch, tmp_path)
    run(["p.write", "p.bread"])
    assert armed == ["capture browser", "p.bread", "p.write"]


def test_an_interrupt_before_serve_waits_is_not_a_pass(monkeypatch, tmp_path):
    class Interrupted(_NoStack):
        def __init__(self, *a, **k):
            raise KeyboardInterrupt

    run, armed = _stub_live_run(monkeypatch, tmp_path, Interrupted)
    before = signal.getsignal(signal.SIGINT)
    code, rep = run([])
    assert (code, rep["error"], armed) == (1, "interrupted", [])
    assert signal.getsignal(signal.SIGINT) is before



URLS = ["http://127.0.0.1:1", "http://127.0.0.1:2"]
ME = (200, {"id": int(PROOF_CREATOR)})


@pytest.mark.parametrize("urls, ids, identity, lock, want", [
    (URLS, [PROOF_CREATOR], ME, True, []),
    (URLS + ["http://10.0.0.2:3"], [PROOF_CREATOR], ME, True, ["not loopback: http://10.0.0.2:3"]),
    (URLS, ["42"], ME, True, [f"expected one Creator {PROOF_CREATOR}, the Relay has ['42']"]),
    (URLS, [PROOF_CREATOR, "42"], ME, True, [f"expected one Creator {PROOF_CREATOR}, the Relay has ['80000112', '42']"]),
    (URLS, [], ME, True, [f"expected one Creator {PROOF_CREATOR}, the Relay has []"]),
    (URLS, [PROOF_CREATOR], (200, {"id": "42"}), True,
     [f"Relay identity read (/__proof/session): session probe named '42', not the run's Creator {PROOF_CREATOR}"]),
    (URLS, [PROOF_CREATOR], (400, {"error": {"code": 301, "message": "Wrong user."}}), True,
     ['session dead: OnlyFans answered "Wrong user" (code 301) to the signed /users/me probe (400)']),
    (URLS, [PROOF_CREATOR], (502, "boom"), True,
     ["Relay identity read (/__proof/session): session probe answered 502: boom"]),
    (URLS, [PROOF_CREATOR], ME, False, [f"the run lock for Creator {PROOF_CREATOR} is not held by this run"]),
], ids=["go", "off loopback", "another Creator", "two Creators", "no Creator", "identity names another",
        "session dead", "identity read fails", "lock not held"])
def test_preflight_problems(urls, ids, identity, lock, want):
    assert preflight_problems(urls, ids, PROOF_CREATOR, identity, lock) == want


@pytest.mark.parametrize("capture, ids, refused, want", [
    (None, ["tracer.create-list"], [], False),
    (None, [], [], False),
    (None, ["tracer.create-list", "drill.browser"], [], True),
    ("tracer.create-list", ["tracer.create-list"], [], True),
    (None, ["drill.browser"], ["session dead"], False),
    ("send", [], [], False),
], ids=["no browser steps", "serve", "a browser-step proof", "capture", "preflight refused", "capture, none startable"])
def test_capture_browser_opens_on_demand_only(capture, ids, refused, want):
    from proofs import ALL
    assert capture_cmd.opens_capture_browser(capture, [ALL[i] for i in ids], refused) is want


def test_every_proof_defined_in_proofs_reads_with_get_and_fan():
    import gc
    import importlib
    import inspect
    from proof_core import Proof
    mods = sorted(f.stem for f in (Path(__file__).parent / "proofs").glob("*.py") if f.stem != "__init__")
    for m in mods:
        importlib.import_module(f"proofs.{m}")
    found = [o for o in gc.get_objects() if isinstance(o, Proof)]
    assert "settings--fully-private" in {p.id for p in found}
    bad = sorted({p.id for p in found if p.of_read is not None and len(inspect.signature(p.of_read).parameters) != 2})
    assert bad == []


def test_preflight_reads_the_relay_accounts_and_the_uncached_identity():
    class R:
        def __init__(self, status, body):
            self.status, self.ok, self._b = status, status < 400, body

        def json(self):
            return self._b

        def text(self):
            return json.dumps(self._b)

    calls = []

    class Req:
        def get(self, url, headers=None):
            calls.append((url, headers))
            return R(200, {"accounts": [{"id": 7}]}) if url.endswith("/admin/accounts") else R(200, {"id": 8})

    got = live_entry.preflight(Req(), "http://127.0.0.1:5", URLS, "6", True)
    assert calls == [("http://127.0.0.1:5/admin/accounts", None),
                     ("http://127.0.0.1:5/__proof/session", {"X-Account-Id": "7"})]
    assert got == ["expected one Creator 6, the Relay has ['7']",
                   "Relay identity read (/__proof/session): session probe named 8, not the run's Creator 6"]



def test_serve_wait_prints_the_urls_and_returns_on_interrupt(monkeypatch, capsys):
    def sleep(_):
        raise KeyboardInterrupt

    serve_wait("http://127.0.0.1:1", "http://127.0.0.1:2", ("ofmproof", "pw"), sleep=sleep)
    out = capsys.readouterr().out
    assert "serve: app http://127.0.0.1:1" in out and "serve: relay http://127.0.0.1:2" in out
    assert "interrupted; tearing down" in out



e2e = pytest.mark.skipif(os.environ.get("OFM_E2E") != "1", reason="starts the fake stack; set OFM_E2E=1")
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _run(*args):
    return subprocess.Popen([str(ROOT / "scripts/of-live-proof/run.sh"), *args], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)


def _evidence(out: str) -> Path:
    return ROOT / re.search(r"ofm-live-proof: evidence (\S+)", out).group(1)


def _serve_up() -> tuple:
    end = time.time() + 600
    while time.time() < end:
        p, lines = _run("--of", "fake", "serve"), []
        while line := p.stdout.readline():
            lines.append(line)
            if "serve: up" in line or "lock held" in line:
                break
        out = "".join(lines)
        if "lock held" not in out:
            return p, out
        p.wait()
        time.sleep(15)
    pytest.fail("FakeOF's Creator lock stayed held for 10 min")


@e2e
def test_serve_fake_up_then_sigint_tears_down():
    p, out = _serve_up()
    assert "serve: up" in out, out
    app = re.search(r"serve: app (http://127\.0\.0\.1:\d+)", out).group(1)
    relay = re.search(r"serve: relay (http://127\.0\.0\.1:\d+)", out).group(1)
    with _DIRECT.open(f"{relay}/health", timeout=30) as r:
        assert r.status == 200
    with _DIRECT.open(f"{app}/", timeout=120) as r:
        assert r.status == 200
    p.send_signal(signal.SIGINT)
    rest, _ = p.communicate(timeout=120)
    out += rest
    assert p.returncode == 0, out
    rep = json.loads((_evidence(out) / "report.json").read_text())
    assert rep["cmd"] == "serve" and rep["teardown"]["temp_deleted"] is True and not rep["session_leaks"]
    assert not Path(rep["teardown"]["temp_dir"]).exists()
    for url in (relay, app):
        with pytest.raises(OSError):
            _DIRECT.open(url, timeout=5)


@e2e
def test_fake_stack_naming_another_creator_is_refused_before_any_proof():
    p = _run("--of", "fake", "--fault", "wrong-creator", "--proof", "tracer.create-list")
    out, _ = p.communicate(timeout=900)
    assert p.returncode != 0, out
    assert "refused before any proof: preflight: expected one Creator" in out
    assert "refused before any proof: preflight: Relay identity read (/__proof/session): session probe named" in out
    rep = json.loads((_evidence(out) / "report.json").read_text())
    assert rep["proofs"] == [] and rep["preflight"] and rep["teardown"]["temp_deleted"] is True


def test_a_proof_parked_at_run_time_is_reported_parked_and_the_run_still_passes(monkeypatch, tmp_path):
    run, armed = _stub_live_run(monkeypatch, tmp_path)
    monkeypatch.setattr(prove, "run_proof", lambda p, *a, **k: {
        "proof": p.id, "state": "parked", "parked": "parked — needs X", "problems": [], "undo": ["none"],
        "screens": []})
    code, rep = run(["p.read"])
    assert rep["proofs"] == [] and rep["parked"] == [{"proof": "p.read", "reason": "parked — needs X", "screens": []}]
    assert code == 0 and rep["run_ok"] is True


def _park_run(monkeypatch, tmp_path, proof, replies, app_reads=False, wire=None, page=None):
    from types import SimpleNamespace
    wire = [] if wire is None else wire

    def of_get(path, query):
        wire.append({"seq": len(wire) + 1, "origin": "app" if app_reads else "driver", "method": "GET", "path": path})
        return replies[path](query) if callable(replies[path]) else replies[path]

    def relay_client(stack, ab):
        return lambda method, route, data=None, account=None: (200, json.dumps({"wire": list(wire)}).encode())

    class Ctx:
        request = SimpleNamespace(post=lambda url, data=None: SimpleNamespace(ok=True, status=200, text=lambda: ""))

        def new_page(self):
            return page if page is not None else pytest.fail("the page opened")

    monkeypatch.setattr(prove, "_relay_client", relay_client)
    (tmp_path / "undo-log.jsonl").touch()
    stack = SimpleNamespace(relay="http://relay.invalid", app="http://app.invalid", of="fake", of_get=of_get)
    ab = SimpleNamespace(ctx=Ctx(), offhost=lambda: [], errors=None, writes=None, responses=None)
    return prove.run_proof(proof, stack, ab, "1", tmp_path, "20261121T000000Z")


def _t61_proof():
    from expects import Expect
    from proof_core import Proof
    return Proof(id="p.sort", phase=3, page="settings/subscription/tracking-links", control="Sort", kind="live",
                 trigger=(("click", "button"),),
                 settled=("text", ".row", Expect("/api2/v2/c", {"field": "name", "sort": "desc"},
                                                 lambda r: [x["n"] for x in r["list"]])))


def test_run_proof_parks_an_expect_before_the_page_opens_and_sends_nothing(monkeypatch, tmp_path):
    res = _park_run(monkeypatch, tmp_path, _t61_proof(), {"/api2/v2/c": {"list": [{"n": "Only"}]}})
    assert res["state"] == "parked" and "read 1 row(s)" in res["parked"] and res["undo"] == ["none"]
    assert res["screens"] == [] and res["problems"] == []


def test_run_proof_parks_on_ready_before_the_page_opens(monkeypatch, tmp_path):
    from proofs.phase3 import FREQUENCY
    groups = [{"items": [{"code": "new_likes_digest", "isEnabled": False, "value": 0}]}]
    res = _park_run(monkeypatch, tmp_path, FREQUENCY, {"/api2/v2/users/settings/notifications/email": groups,
                                                       "/api2/v2/users/me/settings": {"isEmailNotificationsEnabled": False}})
    assert res["state"] == "parked" and res["parked"].endswith("New Likes Summary switch body")
    assert res["problems"] == [] and res["undo"] == ["none"]


def test_run_proof_fails_frequency_when_its_read_lacks_the_master_switch(monkeypatch, tmp_path):
    from proofs.phase3 import FREQUENCY
    groups = [{"items": [{"code": "new_likes_digest", "isEnabled": False, "value": 0}]}]
    res = _park_run(monkeypatch, tmp_path, FREQUENCY, {"/api2/v2/users/settings/notifications/email": groups,
                                                       "/api2/v2/users/me/settings": {}})
    assert res["state"] == "fail" and not res.get("parked") and res["problems"][0].startswith("KeyError")


def test_run_proof_fails_a_park_after_anything_but_the_drivers_reads_left(monkeypatch, tmp_path):
    res = _park_run(monkeypatch, tmp_path, _t61_proof(), {"/api2/v2/c": {"list": [{"n": "Only"}]}}, app_reads=True)
    assert res["state"] == "fail" and "beyond the driver's reads: GET /api2/v2/c" in res["problems"][0]


@pytest.mark.parametrize("sorted_query, problems", [
    ("limit=10", ["the app sent no GET /api2/v2/c with {'field': 'name', 'sort': 'desc'}: the sort did not reach "
                  "OnlyFans"]),
    ("limit=10&field=name&sort=desc", []),
])
def test_run_proof_checks_that_the_sort_reached_onlyfans(monkeypatch, tmp_path, sorted_query, problems):
    from types import SimpleNamespace
    wire = []

    def app_get(query):
        wire.append({"seq": len(wire) + 1, "origin": "app", "method": "GET", "path": "/api2/v2/c", "query": query,
                     "verdict": "read"})
    page = SimpleNamespace(goto=lambda *a, **k: app_get("limit=10"), evaluate=lambda js: "model:1",
                           screenshot=lambda **k: None, wait_for_load_state=lambda *a, **k: None,
                           wait_for_timeout=lambda ms: None)
    button = SimpleNamespace(wait_for=lambda **k: None, click=lambda **k: app_get(sorted_query))
    monkeypatch.setattr(prove, "_mirror_frame", lambda page, p: SimpleNamespace(locator=lambda sel: SimpleNamespace(
        first=button)))
    monkeypatch.setattr(prove, "_wait_text", lambda *a: None)
    rows = lambda q: {"list": [{"n": n} for n in (["Zed", "Ann"] if q.get("sort") == "desc" else ["Mid", "Zed"])]}  # noqa: E731
    res = _park_run(monkeypatch, tmp_path, _t61_proof(), {"/api2/v2/c": rows}, wire=wire, page=page)
    assert not res.get("parked") and res["wants"] == {"settled": "Zed"} and res["problems"] == problems
    assert res["state"] == ("fail" if problems else "pass")
