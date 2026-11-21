"""Seam 2: `scrub` and `check_record` on planted and committed capture records, and the check-records command.

Expected records come from the spec's Capture record contract (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md,
Implementation Decisions, Contracts) and ticket 06, written out literally.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from capture_record import check_record, scrub

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
COMMITTED = ROOT / "docs" / "of-manager" / "captures"
CREATOR, FAN, RUN = "80000112", "55512345", "20261120T184224Z"
IDS = {"creator": CREATOR, "fan": FAN, "run": RUN}
EMAIL = "someone@example.com"

RAW = {
    "id": "collections--create-new-list", "section": "collections", "label": "Create new list",
    "pages": ["collections/index"], "phase": 0, "source": "live", "captured": "2026-11-20",
    "request": {
        "method": "post",
        "url": f"https://onlyfans.com/api2/v2/users/{CREATOR}/lists?ref={FAN}&x=1",
        "headers": {"Content-Type": "application/json", "Cookie": "sess=s3cret", "User-ID": CREATOR, "X-BC": "bc",
                    "Sign": "sig", "Time": "1763660000000", "App-Token": "tok", "X-Hash": "h",
                    "x-of-rev": "202611201129-df73dce944"},
        "body": json.dumps({"name": f"oi-proof-{RUN}", "userIds": [int(FAN), 777777], "fan": int(FAN),
                            "note": f"for {CREATOR}", "price": 5}),
    },
    "response": {"status": 200, "headers": {"set-cookie": "sess=s3cret"},
                 "body": {"id": 123456789, "name": f"oi-proof-{RUN}", "users": [{"id": int(FAN), "email": EMAIL}]}},
    "proof": {"kind": "live", "verdict": "pass", "evidence": f"slop/evidence/{RUN}-ofm-live-abc1234",
              "undo": "undone", "reason": "", "branches": {}},
}

SCRUBBED = {
    "id": "collections--create-new-list", "section": "collections", "label": "Create new list",
    "pages": ["collections/index"], "phase": 0, "source": "live", "of_rev": "202611201129-df73dce944",
    "captured": "2026-11-20",
    "request": {"method": "POST", "path": "/api2/v2/users/{creator}/lists", "query": {"ref": "{fan}", "x": "1"},
                "content_type": "application/json",
                "body": {"name": "oi-proof-{run}", "userIds": ["{fan}", "{id}"], "fan": "{fan}",
                         "note": "for {creator}", "price": 5}},
    "response": {"status": 200, "keys": ["id", "name", "users"]},
    "proof": {"kind": "live", "verdict": "pass", "evidence": f"slop/evidence/{RUN}-ofm-live-abc1234",
              "undo": "undone", "reason": "", "branches": {}},
}


def test_scrub_planted_raw_capture_gives_placeholders_and_content_type_only():
    assert scrub(RAW, IDS) == SCRUBBED


def test_scrub_leaves_no_secret_in_the_record():
    text = json.dumps(scrub(RAW, IDS))
    for secret in (CREATOR, FAN, RUN + '"', "s3cret", EMAIL, "777777", "123456789", "Cookie", "X-BC", "Sign"):
        assert secret not in text


def test_scrub_of_js_record_keeps_bundle_and_symbol():
    raw = {**copy.deepcopy(RAW), "source": "of-js", "of_js": {"bundle": "app.js", "symbol": "P addList"}}
    rec = scrub(raw, IDS)
    assert rec["of_js"] == {"bundle": "app.js", "symbol": "P addList"}
    assert check_record(rec) == []


def test_scrub_keeps_provenance_only_in_its_fixed_format():
    raw = {**copy.deepcopy(RAW), "source": "of-js", "of_rev": f"rev{FAN}",
           "of_js": {"bundle": f"{FAN}.txt", "symbol": f"fn for {FAN} at 123456", "offset": str(FAN)}}
    raw["proof"]["evidence"] = f"slop/evidence/{FAN}"
    rec = scrub(raw, IDS)
    assert rec["of_rev"] == "rev{fan}"
    assert rec["of_js"] == {"bundle": "{fan}.txt", "symbol": "fn for {fan} at 123456", "offset": "{fan}"}
    assert rec["proof"]["evidence"] == "slop/evidence/{fan}"


def test_scrubbed_record_passes_the_check():
    assert check_record(scrub(RAW, IDS)) == []


def with_(path, value):
    rec = copy.deepcopy(SCRUBBED)
    node = rec
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return rec


GATHERER = {"id": "collections--bookmarks-create-list", "mode": "js", "bundle_build": "202611201129-df73dce944",
            "requests": [{"method": "POST", "path": "/api2/v2/posts/bookmarks/categories",
                          "source": {"file": "collections-017397ff.js", "offset": 273412, "symbol": "P add",
                                     "evidence": "s(758987),M=s(746532)"}}],
            "live_capture": "pending — {creator} session dead"}


@pytest.mark.parametrize("rec, problem", [
    (with_(("request", "body", "userIds"), [int(FAN)]), "digit run"),
    (with_(("request", "path"), f"/api2/v2/users/{FAN}"), "digit run"),
    (with_(("request", "body"), {FAN: "x"}), "digit run"),
    (with_(("label",), f"mail {EMAIL}"), "email"),
    (with_(("request", "headers"), {"Cookie": "sess=x"}), "header"),
    (with_(("request", "headers"), {"Content-Type": "application/json", "Time": "1"}), "header"),
    (with_(("request", "body"), {"x-bc": "v"}), "header"),
    (with_(("request", "body"), {"note": "Authorization: Bearer abc"}), "header"),
    (with_(("response",), {"status": 200, "keys": ["list"], "list": [{"id": "{id}"}]}), "response"),
    (with_(("response",), {"status": 200, "keys": [{"id": "{id}"}]}), "response"),
    (with_(("source",), "of-js"), "of_js"),
    ({**with_(("source",), "of-js"), "of_js": {"bundle": "app.js"}}, "of_js"),
    ({**with_(("source",), "of-js"), "of_js": {"symbol": "x"}}, "of_js"),
    (with_(("source",), "browser"), "source"),
    (with_(("proof", "branches"), {"start": "parked"}), "branch"),
    (with_(("proof", "branches"), {"start": "parked: "}), "branch"),
    (with_(("proof", "branches"), {"start": "fail"}), "branch"),
    (with_(("proof", "verdict"), "parked"), "reason"),
    (with_(("proof", "kind"), "manual"), "kind"),
    (with_(("proof", "undo"), "maybe"), "undo"),
    ({**GATHERER, "requests": [{"method": "GET", "path": "/x", "source": {"file": "app.js"}}]}, "symbol"),
    ({**GATHERER, "live_capture": f"pending — {CREATOR} session dead"}, "digit run"),
    ({**GATHERER, "note": f"see {EMAIL}"}, "email"),
    # a Fan id in each provenance field, or a provenance-looking block off its fixed path, is still caught
    (with_(("of_rev",), FAN), "digit run"),
    ({**GATHERER, "bundle_build": FAN}, "digit run"),
    (with_(("proof", "evidence"), f"slop/evidence/{FAN}"), "digit run"),
    ({**with_(("source",), "of-js"), "of_js": {"bundle": FAN, "symbol": "x"}}, "digit run"),
    ({**with_(("source",), "of-js"), "of_js": {"bundle": "app.js", "symbol": "x", "offset": FAN}}, "digit run"),
    ({**GATHERER, "requests": [{"source": {"file": FAN, "symbol": "x"}}]}, "digit run"),
    (with_(("request", "body"), {"source": {"evidence": FAN, "file": f"{FAN}.js"}}), "digit run"),
    ({**GATHERER, "hosts": {"janus": {"source": {"file": "83602.js", "offset": 1611956}}}}, "digit run"),
    # a response anywhere holds status and key names only
    ({**GATHERER, "requests": [{"source": {"file": "app.js", "symbol": "x"},
                                "response": {"status": 200, "rows": [{"name": "Tom"}]}}]}, "response rows"),
    # quoted header names (DevTools "Copy as fetch") and bare session cookie pairs
    (with_(("request", "body"), {"note": '"headers":{"cookie":"a","x-bc":"9f"}'}), "header line"),
    (with_(("request", "body"), {"note": "sess=abc123; fp=1"}), "header line"),
])
def test_check_fails_planted_record(rec, problem):
    problems = check_record(rec)
    assert any(problem in p for p in problems), problems
    text = " ".join(problems)
    assert FAN not in text and CREATOR not in text and EMAIL not in text  # the check never echoes a secret


@pytest.mark.parametrize("rec", [
    SCRUBBED,
    with_(("proof", "branches"), {"camera": "pass", "start": "parked: no owner go for a stream"}),
    with_(("proof",), {"kind": "live", "verdict": "parked", "evidence": "", "undo": "none",
                       "reason": "mocked: not run live", "branches": {}}),
    with_(("proof", "undo"), "not reversible, owner go"),
    {**with_(("source",), "of-js"), "of_js": {"bundle": "83602.js", "symbol": "83602 startStream", "offset": 1985929}},
    with_(("proof", "evidence"), f"slop/evidence/{RUN}-ofm-fake-0ffce8d62"),
    {**GATHERER, "room_source": {"sources": [{"file": "83602.js", "offset": 1985929, "symbol": "83602 start"}]}},
    with_(("request", "body"), {"note": "auth is the message token, not a cookie", "price": 1000}),
    GATHERER,
])
def test_check_passes_clean_record(rec):
    assert check_record(rec) == []


@pytest.mark.parametrize("path", sorted(COMMITTED.glob("*.json")) if COMMITTED.is_dir() else [])
def test_committed_record_is_clean(path):
    assert check_record(json.loads(path.read_text())) == []


def check_records(*args):
    return subprocess.run([sys.executable, "-I", "-B", str(HERE / "capture_record.py"), "check-records", *map(str, args)],
                          capture_output=True, text=True)


def test_check_command_passes_empty_and_clean_dirs(tmp_path):
    assert check_records(tmp_path).returncode == 0
    (tmp_path / "collections--create-new-list.json").write_text(json.dumps(scrub(RAW, IDS)))
    (tmp_path / "INDEX.md").write_text(f"not a record {CREATOR}")
    assert check_records(tmp_path).returncode == 0


def test_check_command_passes_the_committed_record_dir():
    r = check_records(COMMITTED)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_command_fails_planted_record_without_printing_it(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps(SCRUBBED))
    (tmp_path / "bad.json").write_text(json.dumps(with_(("request", "body"), {"fan": FAN, "mail": EMAIL})))
    (tmp_path / "broken.json").write_text("{not json")
    r = check_records(tmp_path)
    assert r.returncode == 1
    assert "bad.json" in r.stdout and "broken.json" in r.stdout and "ok.json" not in r.stdout
    assert FAN not in r.stdout + r.stderr and EMAIL not in r.stdout + r.stderr


def test_check_command_refuses_a_missing_dir(tmp_path):
    assert check_records(tmp_path / "nope").returncode == 2
