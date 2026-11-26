#!/usr/bin/env python3

import _harness

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_SCAN = _REPO / "scripts" / "cell_scope_scan.py"
sys.path[:0] = [str(_REPO / "scripts"), str(Path(__file__).resolve().parent / "_cell_probe")]
from _probe_run_fixture import seed_probe_run

import cell_features as feat  # noqa: E402
import cell_probe  # noqa: E402
import cell_scope_scan as scan  # noqa: E402

_DOC = json.loads(scan.SCOPE.read_text())


def _run(*args, **env):
    e = {k: v for k, v in os.environ.items() if k != "CELL_SCOPE_EXTRA_ROUTE"} | env
    p = subprocess.run([sys.executable, str(_SCAN), *args], cwd=_REPO, env=e, capture_output=True, text=True,
                       timeout=600)
    return p.returncode, p.stdout + p.stderr


def _copy(doc) -> Path:
    path = Path(tempfile.mkdtemp(prefix="cell_scope_t_")) / "cell_scope.json"
    path.write_text(scan.dump(doc))
    return path


def case_committed_draft_has_four_exact_maps_and_a_why_on_every_row():
    assert set(_DOC) == {"schema", "routes", "tables", "files", "jobs"}, sorted(_DOC)
    assert scan.validate(_DOC) == [], scan.validate(_DOC)[:5]
    for k in _DOC["routes"]:
        method, _, path = k.partition(" ")
        assert method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "WS", "MOUNT") and path.startswith("/"), k
        assert not path.endswith(("*", "/")) or path == "/", f"prefix-style key {k}"
    assert len(_DOC["routes"]) >= 700 and len(_DOC["tables"]) >= 118 and _DOC["files"] and _DOC["jobs"]
    assert {"data_migrations", "alembic_version"} <= _DOC["tables"].keys(), "real schema tables not scanned"
    assert "GET /auth/fleet/whois" in _DOC["routes"], "fleet profile not scanned"
    assert _DOC["routes"]["GET /auth/fleet/whois"]["hint"]["profiles"] == ["fleet"]
    assert any(k.startswith("automation:") for k in _DOC["jobs"]) and "pump-supervisor" in _DOC["jobs"]


def case_agency_write_takes_precedence_over_creator_keys():
    revoke = "DELETE /admin/users/{user_id}/accounts/{account_id}"
    facts = {"kind": "api", "path_params": ["account_id"]}
    row = scan.draft_route(revoke, facts, {revoke: ["user_accounts"]}, set())
    assert row["scope"] == "agency" and row["key"] == "none", row
    assert scan.validate({"routes": {revoke: row | {"scope": "model"}}})
    assert not scan.validate({"routes": {revoke: row | {
        "scope": "model", "why": "Agency write exception: control owns the mirrored write"}}})
    fresh = {section: {} for section in scan.HUMAN} | {"routes": {revoke: row.copy()}}
    old = {"routes": {revoke: row | {"scope": "model", "why": "names its Creator in the path"}}}
    merged = scan.merge(fresh, old)
    assert merged["routes"][revoke]["scope"] == "model", "regeneration flipped a decided scope"
    assert scan.validate(merged), "a decided scope against probe evidence was published"
    prefix = "PUT /admin/chatters/{chatter_id}/folder-access"
    row = scan.draft_route(prefix, {"kind": "api", "body": ["account_id"]}, {}, set())
    assert row["hint"]["rule"] == "agency_prefix" and row["scope"] == "agency", row
    assert scan.validate({"routes": {prefix: row | {"scope": "model", "key": "body"}}})
    for key in (revoke, "POST /admin/users/{user_id}/accounts", "POST /admin/chatters/link",
                "PUT /admin/employees/{employee_id}/access", prefix, "GET /admin/shifts"):
        assert _DOC["routes"][key]["scope"] == "agency", (key, _DOC["routes"][key])
    for key in ("GET /admin/sensitive-words", "POST /admin/assistant/edit/apply"):
        assert _DOC["routes"][key]["scope"] == "model" and scan._has_agency_exception(_DOC["routes"][key]), key



def case_send_labels_use_registered_prefixes():
    from collections import Counter
    from fastapi import APIRouter, FastAPI
    from send_site_inventory import SendInventory

    def send():
        return {}

    router = APIRouter(prefix="/router")
    router.add_api_route("/send", send, methods=["POST"])
    app = FastAPI()
    app.include_router(router, prefix="/include")
    sites = SendInventory(Counter(), frozenset(), frozenset({("tests/test_cell_scope.py", "send")}))
    assert sites.route_labels(scan.route_facts(app)) == {"http:POST /include/router/send"}


def case_mounted_api_members_are_scanned_and_mount_is_closed():
    from fastapi import FastAPI

    outer, inner = FastAPI(), FastAPI()
    inner.get("/one")(lambda: {})
    outer.mount("/api/nested", inner)
    facts = scan.route_facts(outer)
    assert facts["GET /api/nested/one"]["kind"] == "api"
    assert scan.draft_route("MOUNT /api/nested", facts["MOUNT /api/nested"], {}, set())["scope"] == "closed"
    inner.get("/two")(lambda: {})
    assert "GET /api/nested/two" in scan.route_facts(outer)


def case_unreviewed_job_and_file_refuse_a_scope_write():
    live = {"routes": {}, "tables": {}, "files": {"lit:fixture.json"}, "jobs": {"fixture": {}}}
    fresh = scan.draft(live, {}, set())
    for section, name in (("jobs", "fixture"), ("files", "lit:fixture.json")):
        assert fresh[section][name]["scope"] == "closed"
        assert f"{section} {name}: unreviewed" in scan.validate(fresh)
    decided = json.loads(json.dumps(fresh))
    decided["jobs"]["fixture"].update(scope="cell_local", why="per-Relay fixture loop")
    decided["files"]["lit:fixture.json"].update(scope="cell_local", why="per-Relay fixture file")
    again = scan.merge(scan.draft(live, {}, set()), decided)
    assert again["jobs"]["fixture"]["scope"] == again["files"]["lit:fixture.json"]["scope"] == "cell_local"
    assert not [b for b in scan.validate(again) if "fixture" in b], scan.validate(again)


def case_probe_writers_from_block_and_record_are_folded_into_table_rows():
    inv = json.loads(scan.PROBE.read_text())
    want = scan.writers_by_table(inv)
    for table, writers in want.items():
        assert _DOC["tables"][table].get("writers") == writers, f"{table}: writers not folded"
    assert not [t for t, r in _DOC["tables"].items() if r.get("writers") and t not in want]
    lazy = [w for w in _DOC["tables"]["employees"]["writers"]
            if w["label"] == "http:POST /api/of/v2/chats/{chat_id}/messages"]
    assert lazy and lazy[0]["site"] == "employees.py:get_or_create_mirror_employee", lazy
    modes = {m for r in _DOC["tables"].values() for w in r.get("writers", []) for m in w["modes"]}
    assert modes == {"block", "record"}, modes


def case_fold_probe_takes_the_block_and_record_run_dirs():
    root = Path(tempfile.mkdtemp(prefix="cell_scope_fold_"))
    req = [{"table": t, "op": op, "label": "http:GET /x", "class": "copied", "site": f"a.py:1:{fn}",
            "frames": [f"a.py:1:{fn}"], "n": 1, "test": "test_a", "mode": "record"} for t, op, fn in
           cell_probe.REQUIRED.values()]
    blk = {"table": "shifts", "op": "DELETE", "label": "job:x", "class": "copied", "site": "shifts_api.py:9:drop",
           "frames": ["shifts_api.py:9:drop"], "n": 1, "test": "test_a", "mode": "block"}
    for m, rows in (("block", [blk]), ("record", req + [blk | {"mode": "record"}])):
        seed_probe_run(root / m, m)
        (root / m / "test_cell_scope.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = root / "scope.json"
    out.write_text(scan.dump(_DOC))
    rc, log = _run("--fold-probe", str(root / "block"), str(root / "record"), "--out", str(out))
    assert rc == 0, log[-2000:]
    doc = json.loads(out.read_text())
    assert doc["tables"]["shifts"]["writers"] == [
        {"op": "DELETE", "label": "job:x", "site": "shifts_api.py:drop", "modes": ["block", "record"]}]
    assert doc["tables"]["users"]["writers"][0]["modes"] == ["record"]
    rc, log = _run("--check", "--out", str(out))
    assert rc == 1 and "stale: tables shifts (writers changed)" in log, log[-2000:]


def case_check_is_green_on_main_and_red_on_a_fixture_route():
    rc, log = _run("--check")
    assert rc == 0, f"committed draft drifted; rerun scripts/cell_scope_scan.py:\n{log[-3000:]}"
    rc, log = _run("--check", CELL_SCOPE_EXTRA_ROUTE="/api/of/__cell_scope_fixture")
    assert rc == 1 and "missing: routes GET /api/of/__cell_scope_fixture" in log, log[-2000:]


def case_check_flags_a_public_route_missing_from_the_actor_exemptions():
    doc = json.loads(json.dumps(_DOC))
    doc["routes"]["GET /public-fixture"] = doc["routes"]["GET /.well-known/oauth-authorization-server"]
    assert scan.check(doc, doc) == ["actor gate blocks public route: GET /public-fixture"]


def case_check_is_red_on_a_stale_or_invalid_row():
    doc = json.loads(json.dumps(_DOC))
    doc["routes"]["GET /api/of/__gone"] = dict(doc["routes"]["GET /livez"])
    doc["tables"]["users"]["hint"] = {"rule": "edited"}
    doc["jobs"]["pump-supervisor"]["why"] = " "
    rc, log = _run("--check", "--out", str(_copy(doc)))
    assert rc == 1, log[-2000:]
    for line in ("stale: routes GET /api/of/__gone (gone)", "stale: tables users (hint changed)",
                 "invalid: jobs pump-supervisor: no why"):
        assert line in log, f"{line!r} not in:\n{log[-2000:]}"


def case_regenerate_keeps_decided_fields():
    doc = json.loads(json.dumps(_DOC))
    doc["routes"]["GET /livez"] |= {"scope": "public", "why": "owner: Front door answers it"}
    out = _copy(doc)
    rc, log = _run("--out", str(out))
    assert rc == 0, log[-2000:]
    assert json.loads(out.read_text())["routes"]["GET /livez"]["why"] == "owner: Front door answers it"


def case_only_cell_mode_reads_cell_scope():
    hits = [str(f.relative_to(scan.SERVICE)) for f in scan.SERVICE.rglob("*.py")
            if "tests" not in f.relative_to(scan.SERVICE).parts and "cell_scope" in f.read_text(errors="replace")]
    assert hits == ["cell_mode.py"], f"service code outside cell mode reads cell_scope: {hits}"


def case_stdlib_check_is_red_on_a_duplicated_row():
    raw = scan.dump(_DOC).replace('\n "GET /livez":', '\n "GET /livez":{"scope":"cell_local","why":"x"},\n "GET /livez":', 1)
    path = Path(tempfile.mkdtemp(prefix="cell_scope_t_")) / "cell_scope.json"
    path.write_text(raw)
    p = subprocess.run(["python3", str(_REPO / "scripts" / "cell_scope_check.py"), "--out", str(path)], cwd=_REPO,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 1 and "duplicated: GET /livez" in p.stdout, (p.returncode, p.stdout[-2000:], p.stderr[-2000:])


def _features():
    scope, kinds = feat.load()
    return json.loads(feat.FEATURES.read_text()), scope, kinds


def _home(doc, kind, member):
    return next(n for n, f in doc["features"].items() if member in f[kind])


def _problems(doc, scope, kinds, page=None):
    return feat.check(doc, scope, feat.sha256(feat.SCOPE), kinds, page)


def case_feature_table_is_green_unsigned_and_its_page_is_current():
    rc, log = _run("--features", "--check")
    assert rc == 0, f"feature table drifted; rerun scripts/cell_scope_scan.py --features:\n{log[-3000:]}"
    doc, scope, kinds = _features()
    assert doc["signed"] is None and set(doc) == feat.DOC_KEYS
    assert _problems(doc, scope, kinds, feat.PAGE.read_text()) == []
    assert 40 <= len(doc["features"]) <= 60, len(doc["features"])
    page = feat.PAGE.read_text()
    assert page.index("## Switched off") < page.index("## Works with a gap") < page.index("## Works as today")
    assert "Draft. Not signed yet." in page


def case_every_route_job_and_send_kind_sits_in_exactly_one_feature():
    import _send_kill_chat
    import _send_kill_http
    import _send_kill_jobs
    import _send_kill_markers
    from agency_write_fold import send_routes_from_scope

    doc, scope, kinds = _features()
    drivers = {d.kind for m in (_send_kill_http, _send_kill_jobs, _send_kill_markers, _send_kill_chat)
               for d in m.DRIVERS}
    assert set(kinds) == drivers, (set(kinds) ^ drivers)
    assert "http:POST /api/of/v2/chats/{chat_id}/messages" in send_routes_from_scope(scope)
    for kind, member, other in (("routes", "GET /livez", "Chat with a fan"), ("jobs", "pump-supervisor", "Full AI"),
                                ("send_kinds", "composer", "Funnels")):
        home = _home(doc, kind, member)
        gone = json.loads(json.dumps(doc))
        gone["features"][home][kind].remove(member)
        assert f"missing: {kind[:-1]} {member} is in no feature" in _problems(gone, scope, kinds)
        two = json.loads(json.dumps(doc))
        two["features"][other][kind].append(member)
        dup = [p for p in _problems(two, scope, kinds) if p.startswith(f"duplicate: {kind[:-1]} {member} is in ")]
        assert len(dup) == 1 and repr(home) in dup[0] and repr(other) in dup[0], dup
    grown = json.loads(json.dumps(scope))
    grown["routes"]["GET /api/of/__fixture"] = scope["routes"]["GET /livez"]
    assert "missing: route GET /api/of/__fixture is in no feature" in _problems(doc, grown, kinds)


def case_no_feature_is_better_than_its_worst_member_and_the_scope_hash_is_current():
    doc, scope, kinds = _features()
    for member, kind, low in (("GET /docs", "routes", "off"), ("GET /admin/accounts", "routes", "partial"),
                              ("autoreply", "send_kinds", "off")):
        bad = json.loads(json.dumps(doc))
        home = _home(doc, kind, member)
        bad["features"][home]["state"] = "works"
        assert any(p.startswith(f"better than worst member: {home!r} says works")
                   and p.endswith(f"is {low}") for p in _problems(bad, scope, kinds)), home
    over_off = json.loads(json.dumps(doc))
    over_off["features"]["API docs pages"]["state"] = "partial"
    assert any("'API docs pages' says partial" in p for p in _problems(over_off, scope, kinds))
    kind_only = json.loads(json.dumps(doc))
    kind_only["features"][_home(doc, "send_kinds", "nudge")]["send_kinds"].remove("nudge")
    kind_only["features"]["Auto clock-out"] = {"state": "works", "why": "x", "routes": [], "jobs": [],
                                               "send_kinds": ["nudge"]}
    assert "better than worst member: 'Auto clock-out' says works, send_kind nudge is off" in _problems(
        kind_only, scope, kinds)
    stale = json.loads(json.dumps(doc)) | {"scope_sha256": "0" * 64}
    assert any(p.startswith("stale: scope_sha256") for p in _problems(stale, scope, kinds))
    page = feat.PAGE.read_text().replace("Translate", "Translation")
    assert any(p.startswith("stale: docs/cell-mode/release-1-features.md") for p in _problems(doc, scope, kinds, page))


def case_draft_states_name_what_release_1_switches_off():
    doc, scope, kinds = _features()
    f = doc["features"]

    def state(kind, member):
        return f[_home(doc, kind, member)]["state"]

    for r in ("GET /t/{slug}", "GET /share/{key}/data", "GET /admin/bio-pages", "POST /admin/s4s/requests"):
        assert state("routes", r) == "off", r
    fanin_reads = [k for k, r in scope["routes"].items() if r["scope"] == "fanin" and k.startswith("GET ")]
    kept = {"GET /admin/accounts", "GET /admin/chats/recent", "GET /admin/screens/inbox"}
    assert kept <= set(fanin_reads) and len(fanin_reads) >= 9
    for r in fanin_reads:
        assert (state("routes", r) == "partial") if r in kept else (state("routes", r) == "off"), r
    assert state("routes", "GET /admin/shifts/timesheet") == "partial"
    assert f["Auto clock-out"]["state"] == "off"
    assert {k for k in kinds if state("send_kinds", k) == "off"} == {
        "autoreply", "welcome_chatter", "welcome_closing_ppv", "followup", "vault_send", "nudge", "purchase_followup"}
    assert state("routes", "POST /api/of/v2/posts") == state("routes", "POST /api/of/v2/stories") == "partial"
    assert state("send_kinds", "composer") == state("routes", "GET /admin/full-ai/config") == "works"



def case_redraft_is_stable_drops_gone_members_and_never_keeps_a_stale_signature():
    doc, scope, kinds = _features()
    again, unplaced = feat.draft(scope, kinds, doc)
    assert unplaced == [] and again == doc
    shrunk = json.loads(json.dumps(scope))
    del shrunk["routes"]["GET /livez"]
    assert "stale: route GET /livez in 'Relay health and housekeeping' is gone" in _problems(doc, shrunk, kinds)
    redrafted, _ = feat.draft(shrunk, kinds, doc)
    assert all("GET /livez" not in f["routes"] for f in redrafted["features"].values())
    signed = json.loads(json.dumps(doc)) | {"signed": {"by": "owner", "at": "2026-11-26",
                                                      "sha256": feat.table_sha256(doc)}}
    assert _problems(signed, scope, kinds) == []
    assert feat.draft(scope, kinds, signed)[0]["signed"] == signed["signed"]
    changed = json.loads(json.dumps(signed))
    changed["features"]["Translate"]["why"] = "edited after signing"
    assert any(p.startswith("stale: signed sha256") for p in _problems(changed, scope, kinds))
    assert feat.draft(shrunk, kinds, signed)[0]["signed"] is None


if __name__ == "__main__":
    _harness.run()
