"""Fake mode never leaves the machine: relay_live's egress wraps (`_guard_egress`) decide and log a request on its own
host, then send it to FakeOF on the same path; the caller's own Request keeps its host."""
import importlib.util
import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
FAKE = "127.0.0.1:18999"


def _load(monkeypatch, tmp_path, fake: bool):
    monkeypatch.syspath_prepend(str(HERE.parent.parent / "service"))   # of_client, of_session_stream (relay_guarded.py)
    monkeypatch.setenv("OFM_PROOF_EVIDENCE", str(tmp_path))
    if fake:
        monkeypatch.setenv("OF_API_ORIGIN", f"http://{FAKE}")
        monkeypatch.setenv("OFM_FAKE_CDN_HOST", "fake-cdn.ofcdn.com")
    else:   # live: no FakeOF origin, nothing is rewritten
        monkeypatch.delenv("OF_API_ORIGIN", raising=False)
        monkeypatch.delenv("OFM_FAKE_CDN_HOST", raising=False)
    spec = importlib.util.spec_from_file_location(f"relay_live_{'fake' if fake else 'live'}", HERE / "relay_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def relay_live(monkeypatch, tmp_path):
    return _load(monkeypatch, tmp_path, fake=True)


@pytest.fixture(params=["fake", "live"])
def relay_any(request, monkeypatch, tmp_path):
    """relay_live in either mode (`.fake` says which); the stubbed egress below never reaches a network."""
    mod = _load(monkeypatch, tmp_path, fake=request.param == "fake")
    mod.fake = request.param == "fake"
    return mod


class _Sent(list):
    headers: list   # each curl_cffi call's headers, as the stub received them


def _stub_egress(monkeypatch, mod):
    """`_guard_egress()` over recording stubs of the real curl_cffi Session.request and urlopen (restored after)."""
    from curl_cffi import requests as cffi
    import curl_cffi.requests.session as cffi_session
    import of_session_stream
    got = _Sent()
    got.headers = []

    def request(self, method, url, *a, **k):
        got.append(("curl_cffi", method, str(url)))
        got.headers.append(dict(k.get("headers") or {}))
        return SimpleNamespace(status_code=200, json=lambda: {})

    def urlopen(url, data=None, *a, **k):
        got.append(("urlopen", url.get_method() if isinstance(url, urllib.request.Request) else "GET",
                    url.full_url if isinstance(url, urllib.request.Request) else str(url)))
        return SimpleNamespace(status=200)

    monkeypatch.setattr(cffi.Session, "request", request)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cffi_session, "set_curl_options", cffi_session.set_curl_options)
    monkeypatch.setattr(of_session_stream, "set_curl_options", of_session_stream.set_curl_options)
    mod._guard_egress()
    return got


@pytest.fixture
def sent(monkeypatch, relay_live):
    return _stub_egress(monkeypatch, relay_live)


def _wire(tmp_path):
    return [json.loads(x) for x in (tmp_path / "wire.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("url, want", [
    ("https://convert1.onlyfans.com/file/upload?x=1", f"http://{FAKE}/file/upload?x=1"),
    (f"http://{FAKE}/api2/v2/users/me", f"http://{FAKE}/api2/v2/users/me"),
])
def test_to_fake(relay_live, url, want):
    assert relay_live._to_fake(url) == want


def test_curl_cffi_sends_fakeof_and_logs_the_original_host(sent, tmp_path):
    from curl_cffi import requests as cffi
    cffi.Session().request("GET", "https://cdn2.onlyfans.com/files/a.jpg?s=1")
    assert sent == [("curl_cffi", "GET", f"http://{FAKE}/files/a.jpg?s=1")]
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["host"], e["path"], e["verdict"], e["status"]) for e in done] == [
        ("cdn2.onlyfans.com", "/files/a.jpg", "read", 200)]


def test_urlopen_sends_a_new_fakeof_request_and_the_callers_keeps_its_host(sent, tmp_path):
    req = urllib.request.Request("https://public.onlyfans.com/files/b.js", headers={"X-Soak": "1"})
    urllib.request.urlopen(req)
    assert sent == [("urlopen", "GET", f"http://{FAKE}/files/b.js")]
    assert req.full_url == "https://public.onlyfans.com/files/b.js" and req.header_items() == [("X-soak", "1")]
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["host"], e["path"], e["verdict"], e["status"]) for e in done] == [
        ("public.onlyfans.com", "/files/b.js", "read", 200)]


def test_a_refused_host_never_reaches_the_stub(sent, tmp_path):
    import of_client
    with pytest.raises(of_client.OFDeniedError):
        urllib.request.urlopen("https://example.com/x")
    assert sent == [] and [(e["host"], e["verdict"]) for e in _wire(tmp_path) if e["phase"] == "done"] == [
        ("example.com", "refused")]


def test_an_allowed_write_on_a_fixed_onlyfans_host_goes_to_fakeof(relay_live, sent, tmp_path):
    """The Record proof's convert claim (service/of_upload.py's fixed convert.onlyfans.com): allowed under the armed
    proof, logged on its own host, sent to FakeOF."""
    from dataclasses import replace
    from curl_cffi import requests as cffi
    from proofs import ALL
    relay_live._run = replace(relay_live._run, proof=ALL["p2.record-video"])
    cffi.Session().request("POST", "https://convert.onlyfans.com/file/upload", json={"name": "rec.webm"})
    assert sent == [("curl_cffi", "POST", f"http://{FAKE}/file/upload")]
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["host"], e["path"], e["verdict"], e["status"]) for e in done] == [
        ("convert.onlyfans.com", "/file/upload", "allow", 200)]


# ── ticket 11: the driver's OnlyFans-side read through the Relay (`driver_read`, route /__proof/of-read) ──

SIGN = "sign-value-not-for-the-log"


def _of_get(pq):
    """What the route hands `driver_read`: a signed GET on onlyfans.com (OFClient.get's call, stubbed below)."""
    from curl_cffi import requests as cffi
    return cffi.Session().request("GET", f"https://onlyfans.com{pq}", headers={"sign": SIGN})


def test_a_driver_read_is_logged_as_the_drivers_and_tagged_for_fakeof_only(monkeypatch, relay_any, tmp_path):
    sent = _stub_egress(monkeypatch, relay_any)
    relay_any.driver_read(_of_get, "/api2/v2/lists", "offset=0&limit=50")
    _of_get("/api2/v2/lists")   # the app's own read, outside the driver's
    host = FAKE if relay_any.fake else "onlyfans.com"
    scheme = "http" if relay_any.fake else "https"
    assert [u for _, _, u in sent] == [f"{scheme}://{host}/api2/v2/lists?offset=0&limit=50",
                                       f"{scheme}://{host}/api2/v2/lists"]
    tag = {"x-oi-proof-read": "1"} if relay_any.fake else {}   # never sent to OnlyFans itself
    assert sent.headers == [{"sign": SIGN, **tag}, {"sign": SIGN}]
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["origin"], e["method"], e["host"], e["path"], e["query"], e["verdict"]) for e in done] == [
        ("driver", "GET", "onlyfans.com", "/api2/v2/lists", "offset=0&limit=50", "read"),
        ("relay", "GET", "onlyfans.com", "/api2/v2/lists", "", "read")]
    assert SIGN not in (tmp_path / "wire.jsonl").read_text()   # headers are never logged


def test_the_tag_is_fakeofs(relay_live):
    from fake_layer import TAG
    assert relay_live.TAG == TAG


@pytest.mark.parametrize("path", ["https://evil.example/api2/v2/lists", "/api2/v2/lists?x=1", "/files/a.jpg",
                                  "//evil.example/api2/v2/x", "/api2/v2/../../x", ""])
def test_a_driver_read_takes_only_an_onlyfans_api_path(relay_live, sent, path):
    with pytest.raises(ValueError, match="not an OnlyFans API path"):
        relay_live.driver_read(_of_get, path, "")
    assert sent == []


def test_a_driver_read_never_writes(relay_live, sent, tmp_path):
    import of_client
    from curl_cffi import requests as cffi
    with pytest.raises(of_client.OFDeniedError, match="GET only"):
        relay_live.driver_read(lambda pq: cffi.Session().request("POST", f"https://onlyfans.com{pq}", json={}),
                               "/api2/v2/lists", "")
    assert sent == [] and [(e["origin"], e["verdict"]) for e in _wire(tmp_path) if e["phase"] == "done"] == [
        ("driver", "refused")]


def test_arm_keeps_the_relays_own_mode_whatever_the_body_says(relay_any):
    """A live Relay armed with {"of": "fake"} stays live (a Mocked proof's writes are never let through live)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    relay_any._wire_routes(app)
    lie = "live" if relay_any.fake else "fake"
    r = TestClient(app, client=("127.0.0.1", 50000)).post("/__proof/arm", json={"proof": None, "of": lie})
    assert r.status_code == 200, r.text
    assert relay_any._run.of == ("fake" if relay_any.fake else "live")


# ── ticket 53: the Record proofs' storage PUT host, named on the armed Proof (`Proof.hosts`) ──

S3 = "of2transcoder.s3-accelerate.amazonaws.com"
# The live storage PUT's shape (live run 2026-11-21, wire seq 45): OF's key with the Creator's id spliced in.
S3_PATH = "/upload/80000112/00000000-0000-4000-8000-000000000000/900000000000/video-1.mp4"   # live shape, synthetic ids


def _arm(mod, proof):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    mod._wire_routes(app)
    r = TestClient(app, client=("127.0.0.1", 50000)).post("/__proof/arm", json={"proof": proof})
    assert r.status_code == 200, r.text


def _put(host):
    from curl_cffi import requests as cffi
    import of_client
    try:
        cffi.Session().request("PUT", f"https://{host}{S3_PATH}?X-Amz-Signature=s", data=b"x")
    except of_client.OFDeniedError:
        pass


@pytest.mark.parametrize("proof", ["p2.record-video", "p2.record-voice"])
def test_the_armed_record_proof_lets_its_storage_put_through(monkeypatch, relay_any, tmp_path, proof):
    sent = _stub_egress(monkeypatch, relay_any)
    _arm(relay_any, proof)
    assert relay_any._run.hosts == (S3,)
    _put(S3)
    assert len(sent) == 1
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["host"], e["verdict"], e["class"]) for e in done] == [(S3, "allow", "allow")]


@pytest.mark.parametrize("proof, host", [
    (None, S3),                                  # nothing armed
    ("tracer.create-list", S3),                  # another proof armed
    ("p2.record-video", S3 + ".evil"),           # a lookalike host
    ("p2.record-video", "evil-" + S3),
])
def test_the_storage_host_is_refused_unless_its_proof_is_armed(monkeypatch, relay_any, tmp_path, proof, host):
    sent = _stub_egress(monkeypatch, relay_any)
    _arm(relay_any, proof)
    _put(host)
    assert sent == []
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["verdict"], e["class"]) for e in done] == [("refused", "host")]


@pytest.mark.parametrize("then", [None, "tracer.create-list"])
def test_rearming_drops_the_last_proofs_hosts(monkeypatch, relay_any, tmp_path, then):
    """Disarm, or arm another proof, after a Record proof: its host never carries over (`hosts` is the armed proof's
    own, never added to the last run's)."""
    sent = _stub_egress(monkeypatch, relay_any)
    _arm(relay_any, "p2.record-video")
    _arm(relay_any, then)
    assert relay_any._run.hosts == ()
    _put(S3)
    assert sent == []
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["verdict"], e["class"]) for e in done] == [("refused", "host")]


# ── ticket 53: a presigned storage URL's credential and a binary upload's bytes never reach the evidence ──

PRESIGNED = ("X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=ASIAEXAMPLE%2F20261121%2Fus-east-1%2Fs3%2Faws4_request"
             "&X-Amz-Date=20261121T093957Z&X-Amz-Expires=43200&X-Amz-Security-Token=IQoJsecrettoken"
             "&X-Amz-Signature=13d01fsecretsig&X-Amz-SignedHeaders=host&partNumber=1")


def test_the_wire_log_keeps_no_presigned_credential_and_no_upload_bytes(monkeypatch, relay_any, tmp_path):
    from curl_cffi import requests as cffi
    _stub_egress(monkeypatch, relay_any)
    _arm(relay_any, "p2.record-video")
    video = b"\x1aE\xdf\xa3\x00\x00binary-video-bytes\xff\xfe" * 10
    cffi.Session().request("PUT", f"https://{S3}{S3_PATH}?{PRESIGNED}", data=video)
    log = (tmp_path / "wire.jsonl").read_text()
    for secret in ("ASIAEXAMPLE", "IQoJsecrettoken", "13d01fsecretsig", "binary-video-bytes", "43200"):
        assert secret not in log, secret
    done = [e for e in _wire(tmp_path) if e["phase"] == "done"]
    assert [(e["verdict"], e["body"]) for e in done] == [("allow", f"<{len(video)} bytes>")]
    assert done[0]["query"] == ("X-Amz-Algorithm=REDACTED&X-Amz-Credential=REDACTED&X-Amz-Date=REDACTED"
                                "&X-Amz-Expires=REDACTED&X-Amz-Security-Token=REDACTED&X-Amz-Signature=REDACTED"
                                "&X-Amz-SignedHeaders=REDACTED&partNumber=1")
