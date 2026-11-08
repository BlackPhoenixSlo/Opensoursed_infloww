#!/usr/bin/env python3
"""Growth > Scripts at Infloww size: the bulk import (`POST /admin/saved-replies/bulk`), sequence meta
(`saved_reply_sequences`, `GET /admin/saved-replies/sequences`) kept in step with relabel / delete, the one-request
selection delete (`POST /admin/saved-replies/delete`) and the send count (`POST /admin/saved-replies/sent`).

The seam is the Relay over HTTP with real session cookies from the shared two-Agency fixture.

Run: ./venv/bin/python service/tests/test_scripts_bulk_import.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import SavedReply, SavedReplySequence  # noqa: E402
import employees  # noqa: E402
import permissions  # noqa: E402
import server  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
B = IDS["creator_b"]
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
CHATTER_A = fx.login_chatter("chatter_a")


def _bulk(body: dict, client=OWNER_A, acc: str = A):
    return client.post(f"/admin/saved-replies/bulk?account_id={acc}", json=body)


def _list(acc: str = A, client=OWNER_A) -> list[dict]:
    r = client.get(f"/admin/saved-replies?account_id={acc}")
    assert r.status_code == 200, r.text
    return r.json()["list"]


def _metas(acc: str = A, client=OWNER_A) -> dict[str, dict]:
    r = client.get(f"/admin/saved-replies/sequences?account_id={acc}")
    assert r.status_code == 200, r.text
    return {m["name"]: m for m in r.json()["list"]}


def _wipe(acc: str = A) -> None:
    async def go() -> None:
        async with get_session() as s:
            await s.execute(delete(SavedReply).where(SavedReply.account_id == acc))
            await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == acc))
    asyncio.run(go())


def _seq(name: str, order: int, n: int = 3, **extra) -> dict:
    return {"name": name, "order": order, "created_by": "Mia", "created_on": "2025-03-01T10:00:00Z",
            "modified_on": 1746000000000,
            "steps": [{"step": str(i), "text": f"{name} text {i}", "notes": f"{i}/{n}, bridge",
                       "name": f"{name} s{i}"} for i in range(1, n + 1)], **extra}


def _steps(acc: str, name: str) -> list[tuple]:
    rows = [r for r in _list(acc) if r["script_id"] == name]
    return [(r["script_step"], r["title"], r["text"], r["notes"], r["conditional"], r["price"])
            for r in sorted(rows, key=lambda r: (r["script_step"], r["id"]))]


def case_bulk_creates_sequences_whole_with_meta_steps_options_and_prices():
    _wipe()
    branch = {"name": "Branchy", "order": 2, "description": "PPV ladder", "steps": [
        {"step": "3", "text": "last"},
        {"step": "2.2", "text": "not bought", "conditional": "if he did not buy"},
        {"step": "1", "text": "opener", "notes": "1/3, bridge", "price": 0},
        {"step": "2.1", "text": "bought", "conditional": "if he bought", "price": 12.5},
    ]}
    r = _bulk({"sequences": [_seq("Night 10", 1), branch], "mode": "skip"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sequences"] == {"total": 2, "created": 2, "skipped": 0, "replaced": 0, "failed": 0}, b
    assert b["steps"] == {"total": 7, "created": 7, "deleted": 0}, b
    assert _steps(A, "Branchy") == [(1, None, "opener", "1/3, bridge", None, 0),
                                    (2, None, "bought", None, "if he bought", 12.5),
                                    (2, None, "not bought", None, "if he did not buy", 0),
                                    (3, None, "last", None, None, 0)]
    assert [s[1] for s in _steps(A, "Night 10")] == ["Night 10 s1", "Night 10 s2", "Night 10 s3"]
    m = _metas()
    assert (m["Night 10"]["position"], m["Night 10"]["created_by"]) == (1, "Mia"), m
    assert m["Night 10"]["created_at"].startswith("2025-03-01T10:00:00"), m
    assert m["Night 10"]["updated_at"].startswith("2025-04-30"), m  # 1746000000000 ms
    assert (m["Branchy"]["position"], m["Branchy"]["description"], m["Branchy"]["created_by"]) == (
        2, "PPV ladder", None), m
    # Its scripts carry the sequence's dates (Infloww's), so derived dates agree with the meta.
    night = [x for x in _list() if x["script_id"] == "Night 10"]
    assert all(x["created_at"].startswith("2025-03-01") for x in night), night


def case_a_rerun_creates_nothing_and_reports_the_skips():
    _wipe()
    body = {"sequences": [_seq("S1", 1), _seq("S2", 2)],
            "tags": [{"name": "Openers", "order": 1, "scripts": [{"name": "hi", "text": "hey"}]}]}
    assert _bulk(body).status_code == 200
    before = _list()
    r = _bulk(body)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sequences"]["created"] == 0 and b["sequences"]["skipped"] == 2 and b["skipped"] == ["S1", "S2"], b
    assert b["steps"]["created"] == 0 and b["tag_scripts"] == {
        "total": 1, "created": 0, "tagged": 0, "skipped": 1, "failed": 0}, b
    after = _list()
    assert sorted(x["id"] for x in after) == sorted(x["id"] for x in before)
    assert len(after) == 7


def case_replace_swaps_the_steps_and_updates_the_meta():
    _wipe()
    assert _bulk({"sequences": [_seq("R", 5, n=4)]}).status_code == 200
    new = _seq("R", 9, n=2)
    new["steps"][1]["text"] = "edited"
    r = _bulk({"sequences": [new], "mode": "replace"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sequences"]["replaced"] == 1 and b["steps"] == {"total": 2, "created": 2, "deleted": 4}, b
    assert [(x[0], x[2]) for x in _steps(A, "R")] == [(1, "R text 1"), (2, "edited")]
    assert _metas()["R"]["position"] == 9


def case_a_bad_step_fails_its_whole_sequence_with_a_reason_and_the_rest_import():
    _wipe()
    long_name = "n" * 65
    bad = [
        {"name": "zero", "order": 1, "steps": [{"step": "0", "text": "x"}]},
        {"name": "words", "order": 2, "steps": [{"step": "two", "text": "x"}]},
        {"name": "twice", "order": 3, "steps": [{"step": "1", "text": "a"}, {"step": "1", "text": "b"}]},
        {"name": "fat", "order": 4, "steps": [{"step": "1", "text": "t" * 6501}]},
        {"name": long_name, "order": 5, "steps": [{"step": "1", "text": "x"}]},
        {"name": "FM123", "order": 6, "steps": [{"step": "1", "text": "x"}]},
        {"name": "notes", "order": 7, "steps": [{"step": "1", "text": "x", "notes": "n" * 257}]},
        {"name": "cond", "order": 8, "steps": [{"step": "1", "text": "x", "conditional": "c" * 151}]},
        {"name": "empty", "order": 9, "steps": []},
        {"name": "ok", "order": 10, "steps": [{"step": "1", "text": "t" * 6500}]},
        {"name": "ok", "order": 11, "steps": [{"step": "1", "text": "again"}]},
    ]
    r = _bulk({"sequences": bad, "tags": [{"name": "t" * 33, "scripts": [{"name": "x", "text": "y"}]}]})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sequences"]["created"] == 1 and b["sequences"]["failed"] == 10, b
    reasons = {(f["name"], f["reason"].split(":")[-1].strip()) for f in b["failed"] if f["kind"] == "sequence"}
    assert reasons == {("zero", "must be N or N.M with N >= 1"), ("words", "must be N or N.M with N >= 1"),
                       ("twice", "twice"), ("fat", "text longer than 6500 characters"),
                       (long_name, "name longer than 64 characters"),
                       ("FM123", "name is reserved (FM follow-up scripts)"),
                       ("notes", "notes longer than 256 characters"),
                       ("cond", "conditional longer than 150 characters"),
                       ("empty", "no steps"), ("ok", "name twice in this request")}, reasons
    assert b["tag_scripts"]["failed"] == 1, b
    assert {x["script_id"] for x in _list()} == {"ok"}
    # A request over the row cap is refused whole.
    many = [{"name": f"m{i}", "order": i, "steps": [{"step": "1", "text": "x"}]} for i in range(5001)]
    r = _bulk({"sequences": many})
    assert r.status_code == 413, r.text
    assert {x["script_id"] for x in _list()} == {"ok"}


def case_dry_run_counts_and_writes_nothing():
    _wipe()
    r = _bulk({"sequences": [_seq("D", 1)], "dry_run": True})
    assert r.status_code == 200 and r.json()["sequences"]["created"] == 1 and r.json()["dry_run"], r.text
    assert _list() == [] and _metas() == {}


def case_tag_scripts_merge_into_an_identical_step():
    _wipe()
    assert _bulk({"sequences": [_seq("Q", 1, n=2)]}).status_code == 200
    r = _bulk({"tags": [{"name": "VIP", "order": 1, "scripts": [
        {"name": "Q s1", "text": "Q text 1"},      # == step 1 of Q: tagged, not created
        {"name": "q S1", "text": "Q text 1"},      # name is case-blind: same script, already tagged
        {"name": "solo", "text": "only here", "notes": "n", "price": 5},
    ]}], "mode": "replace"})
    assert r.status_code == 200, r.text
    assert r.json()["tag_scripts"] == {"total": 3, "created": 1, "tagged": 1, "skipped": 1, "failed": 0}, r.json()
    rows = {(x["title"], x["script_id"]): x for x in _list()}
    assert rows[("Q s1", "Q")]["tags"] == ["VIP"]
    assert rows[("solo", None)]["price"] == 5 and rows[("solo", None)]["tags"] == ["VIP"]
    # A replace of Q drops its tag with its old steps; the tag pass of the same payload puts it back.
    r = _bulk({"sequences": [_seq("Q", 1, n=2)], "tags": [{"name": "VIP", "scripts": [
        {"name": "Q s1", "text": "Q text 1"}]}], "mode": "replace"})
    assert r.json()["tag_scripts"]["tagged"] == 1, r.json()


def case_a_step_carries_its_own_tags_and_infloww_day_only_dates():
    _wipe()
    q = _seq("NSQ", 1, n=2, created_on="Oct 13, 2026", modified_on="Sep 2, 2026")
    q["steps"][0]["tags"] = [" NS ", "NS", "", "VIP"]
    r = _bulk({"sequences": [q]})
    assert r.status_code == 200 and r.json()["steps"]["created"] == 2, r.text
    rows = sorted((x for x in _list() if x["script_id"] == "NSQ"), key=lambda x: x["script_step"])
    assert [x["tags"] for x in rows] == [["NS", "VIP"], []], rows
    m = _metas()["NSQ"]
    # Day-only: noon UTC, so the day reads the same in any browser zone.
    assert (m["created_at"], m["updated_at"]) == ("2026-10-13T12:00:00", "2026-09-02T12:00:00"), m
    # One script, never two: a re-run is a no-op; a step tag over the tag cap fails the sequence.
    assert _bulk({"sequences": [q]}).json()["steps"]["created"] == 0
    assert len([x for x in _list() if x["script_id"] == "NSQ"]) == 2
    bad = _seq("Fat tag", 2, n=1)
    bad["steps"][0]["tags"] = ["t" * 33]
    b = _bulk({"sequences": [bad]}).json()
    assert b["failed"] == [{"kind": "sequence", "name": "Fat tag",
                            "reason": "step 1: tag name longer than 32 characters"}], b


def _cli():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / "import_infloww_scripts.py"
    spec = importlib.util.spec_from_file_location("import_infloww_scripts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_cli_plan_maps_an_infloww_dump_to_one_row_per_script():
    """The real dump's shape: steps carry `script_name` (or candidates when ambiguous), tags.json holds the fixed
    views "All scripts" / "Uncategorized" plus real tags whose scripts are steps. One row per script, never two."""
    _wipe()
    cli = _cli()
    seqs = [{"order": 0, "name": "654/A", "script_count": 3, "created_by": "024", "created_on": "Oct 13, 2026",
             "modified_on": "Oct 13, 2026", "steps": [
                 {"step": "1", "text": "hi 😭", "notes": "1/2, bridge", "sent": 0, "script_name": "a1"},
                 {"step": "2", "text": "same", "notes": "2/2", "sent": 0, "script_name_candidates": ["x", "y"]},
                 {"step": "3", "text": "ppv", "notes": "", "sent": 0, "script_name": "a3"}]},
            {"order": 1, "name": "720/B", "script_count": 1, "created_by": "024", "created_on": "Sep 1, 2026",
             "modified_on": "Sep 2, 2026", "description": "B desc", "steps": [
                 {"step": "1", "text": "same", "notes": "2/2", "sent": 0, "script_name_candidates": ["x", "y"]}]}]
    every = [{"name": n, "text": t, "notes": ""} for n, t in (("a1", "hi 😭"), ("x", "same"), ("a3", "ppv"),
                                                              ("y", "same"), ("solo", "loose"))]
    tags = [{"order": 0, "name": "All scripts", "scripts": every},
            {"order": 1, "name": "NS", "scripts": [every[0], every[3], every[4]]},
            {"order": 2, "name": "Uncategorized", "scripts": [every[1], every[2]]}]
    p = cli.plan(seqs, tags)
    assert p["problems"] == [], p["problems"]
    assert [[s["name"] for s in q["steps"]] for q in p["sequences"]] == [["a1", "x", "a3"], ["y"]]
    assert p["expected"] == {"sequences": 2, "steps": 4, "standalone": 1, "rows": 5, "per_tag": {"NS": 3},
                             "untagged": 2}, p["expected"]
    for body in cli.chunks(p["sequences"], p["tags"], 1000):
        r = _bulk({**body, "mode": "skip"})
        assert r.status_code == 200 and not r.json()["failed"], r.text
    rb = cli.read_back(_list(), list(_metas().values()), p)
    assert (rb["mismatches"], rb["step_diffs"], rb["meta_diffs"]) == ([], [], []), rb
    assert rb["got"]["rows"] == 5 and rb["got"]["untagged"] == 2
    # A dump whose views disagree with the plan is a problem the CLI exits 1 on.
    tags[2]["scripts"] = every[1:2]
    assert cli.plan(seqs, tags)["problems"] == ["dump 'Uncategorized' 1 != planned untagged 2"]


def case_cli_reads_back_what_the_relay_stores_and_reports_instead_of_crashing():
    """The read-back compares the relay's stored text (its `of_text`) and UTC days, a loose tag script sharing a
    step's name (other text) is imported, a sequence the relay refused (bad step label) is a diff, not a
    traceback, and an unreachable relay is HTTP 0."""
    _wipe()
    cli = _cli()
    seqs = [{"order": 0, "name": "Html", "created_on": "2026-03-01T23:30:00-05:00", "steps": [
                {"step": "1", "text": '<p><span onclick="x">hi</span></p>', "script_name": "h1"}]},
            {"order": 1, "name": "Bad", "steps": [{"step": "two", "text": "x", "script_name": "b1"}]}]
    tags = [{"order": 0, "name": "VIP", "scripts": [{"name": "h1", "text": '<p><span onclick="x">hi</span></p>'},
                                                    {"name": "h1", "text": "another script, same name"}]}]
    p = cli.plan(seqs, tags)
    assert p["sequences"][0]["steps"][0]["tags"] == ["VIP"], p["sequences"]
    assert [sc["text"] for t in p["tags"] for sc in t["scripts"]] == ["another script, same name"], p["tags"]
    for body in cli.chunks(p["sequences"], p["tags"], 1000):
        assert _bulk({**body, "mode": "skip"}).status_code == 200
    rb = cli.read_back(_list(), list(_metas().values()), p)
    assert rb["step_diffs"] == [{"sequence": "Bad", "field": "steps", "want": 1, "got": 0}], rb["step_diffs"]
    html = [d for d in rb["meta_diffs"] if d["sequence"] == "Html"]
    assert html == [] and _metas()["Html"]["created_at"].startswith("2026-03-02"), (html, _metas())
    assert rb["got"]["per_tag"] == {"VIP": 2}, rb["got"]
    code, ans = cli.Relay("http://127.0.0.1:9", None).call("GET", "/admin/saved-replies/sequences")
    assert code == 0 and ans.get("detail"), (code, ans)


def case_cli_reads_dates_with_the_relays_own_rule():
    """One date and step rule, not two copies: the CLI imports the module the relay reads a dump with, and a dump's
    every date form (epoch s / ms, ISO with a zone, Infloww's day-only, unreadable, absent) reads back without a
    diff."""
    import infloww_dump
    import scripts_import_api
    _wipe()
    cli = _cli()
    assert cli._sequence_dates is infloww_dump.sequence_dates is scripts_import_api.sequence_dates
    assert cli._parse_step is infloww_dump.parse_step is scripts_import_api.parse_step
    forms = [(1746000000, None), (1746000000000, "2026-01-02T03:04:05Z"), ("2026-03-01T23:30:00-05:00", "garbage"),
             ("Oct 13, 2026", "Sep 2, 2026"), ("not a date", None), (None, 1746000000)]
    seqs = [{"order": i, "name": f"D{i}", "created_on": c, "modified_on": m,
             "steps": [{"step": "1", "text": f"d{i}", "script_name": f"d{i}"}]} for i, (c, m) in enumerate(forms)]
    p = cli.plan(seqs, [])
    for body in cli.chunks(p["sequences"], p["tags"], 1000):
        assert _bulk({**body, "mode": "skip"}).status_code == 200
    rb = cli.read_back(_list(), list(_metas().values()), p)
    assert (rb["mismatches"], rb["step_diffs"], rb["meta_diffs"]) == ([], [], []), rb


def case_cli_rerun_on_a_later_day_compares_only_the_dates_the_dump_gives():
    """A sequence the dump gives no date is stored with the import's time: a re-run's read-back on a later day must
    not call that a mismatch, while a date the dump does give is still compared."""
    from datetime import datetime
    _wipe()
    cli = _cli()
    seqs = [{"order": 0, "name": "Undated", "steps": [{"step": "1", "text": "u", "script_name": "u"}]},
            {"order": 1, "name": "Dated", "created_on": "Oct 13, 2026",
             "steps": [{"step": "1", "text": "d", "script_name": "d"}]}]
    p = cli.plan(seqs, [])
    for body in cli.chunks(p["sequences"], p["tags"], 1000):
        assert _bulk({**body, "mode": "skip"}).status_code == 200

    async def age(name: str, when: datetime) -> None:  # as if imported then, read back today
        async with get_session() as s:
            m = (await s.execute(select(SavedReplySequence).where(
                SavedReplySequence.account_id == A, SavedReplySequence.name == name))).scalar_one()
            m.created_at = m.updated_at = when
    asyncio.run(age("Undated", datetime(2020, 1, 1)))
    rb = cli.read_back(_list(), list(_metas().values()), p)
    assert (rb["mismatches"], rb["step_diffs"], rb["meta_diffs"]) == ([], [], []), rb
    asyncio.run(age("Dated", datetime(2020, 1, 1)))
    rb = cli.read_back(_list(), list(_metas().values()), p)
    assert {(d["sequence"], d["field"]) for d in rb["meta_diffs"]} == {
        ("Dated", "created_on"), ("Dated", "modified_on")}, rb["meta_diffs"]


def case_cli_sign_in_failure_exits_2():
    """The docstring's "2 usage / sign-in": a refused sign-in is exit 2 with the reason on stderr, no traceback."""
    import contextlib
    import io
    import os
    import tempfile
    from pathlib import Path
    cli = _cli()
    cli.Relay.call = lambda self, method, path, body=None, **q: (401, {"detail": "no"})
    os.environ.update(RELAY_USER="u", RELAY_PASS="p")
    err = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(err):
            (Path(d) / "sequences.json").write_text(json.dumps([_seq("SI", 0, n=1)]))
            code = cli.main(["--base-url", "http://unused", "--account-id", A, "--dump", d])
    finally:
        del os.environ["RELAY_USER"], os.environ["RELAY_PASS"]
    assert code == 2 and "sign-in failed (HTTP 401)" in err.getvalue(), (code, err.getvalue())


def case_cli_without_the_relays_service_dir_exits_2():
    """No silent fallback: a CLI copied away from service/ can't read text and dates as the relay does, so it says
    so and exits 2 (usage), never reconciling with a guess."""
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "scripts" / "import_infloww_scripts.py"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "scripts").mkdir()
        cli = Path(d) / "scripts" / src.name
        shutil.copy(src, cli)
        r = subprocess.run([sys.executable, "-I", str(cli), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "service/" in r.stderr, (r.returncode, r.stderr)


def case_cli_writes_its_report_when_the_read_back_fails():
    """A read-back the relay answers with an error still leaves `--report` (counts, failures, the HTTP codes)."""
    import tempfile
    from pathlib import Path
    _wipe()
    cli = _cli()

    def call(self, method, path, body=None, **q):
        if method == "GET" and path == "/admin/saved-replies":
            return 503, {"detail": "busy"}
        r = OWNER_A.request(method, path, params=q, json=body)
        return r.status_code, r.json()
    cli.Relay.call = call
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sequences.json").write_text(json.dumps([_seq("RB", 0, n=2)]))
        out = Path(d) / "report.json"
        code = cli.main(["--base-url", "http://unused", "--account-id", A, "--dump", d, "--report", str(out)])
        report = json.loads(out.read_text()) if out.exists() else None
    assert code == 1, code
    assert report and report["ok"] is False, report
    assert report["read_back"] == {"failed": {"list_http": 503, "sequences_http": 200}}, report["read_back"]
    assert report["counts"]["steps.created"] == 2, report["counts"]


def case_relabel_rename_and_delete_keep_the_meta_in_step():
    _wipe()
    assert _bulk({"sequences": [_seq("Old", 3), _seq("Gone", 4), _seq("Part", 5)]}).status_code == 200
    rel = lambda **b: OWNER_A.post(f"/admin/saved-replies/relabel?account_id={A}", json=b)  # noqa: E731
    assert rel(kind="sequence", **{"from": "Old"}, to="New").status_code == 200
    m = _metas()
    assert "Old" not in m and (m["New"]["position"], m["New"]["created_by"]) == (3, "Mia"), m
    assert rel(kind="sequence", **{"from": "Gone"}).status_code == 200      # ungroup the whole sequence
    assert "Gone" not in _metas()
    part = [x["id"] for x in _list() if x["script_id"] == "Part"]
    assert rel(kind="sequence", **{"from": "Part"}, ids=part[:1]).status_code == 200   # one script out
    assert "Part" in _metas()
    # The rest out one by one: PUT moving the last one out prunes the meta.
    for rid in part[1:]:
        row = [x for x in _list() if x["id"] == rid][0]
        r = OWNER_A.put(f"/admin/saved-replies/{rid}", json={"text": row["text"], "script_id": None})
        assert r.status_code == 200, r.text
    assert "Part" not in _metas()
    # A stale meta of the target name never blocks or leaks into a rename.
    asyncio.run(_stale_meta(A, "Fresh"))
    assert rel(kind="sequence", **{"from": "New"}, to="Fresh").status_code == 200
    assert _metas()["Fresh"]["position"] == 3


async def _stale_meta(acc: str, name: str) -> None:
    async with get_session() as s:
        s.add(SavedReplySequence(account_id=acc, name=name, position=99))


def case_batch_delete_is_one_request_scoped_to_the_account_and_prunes_meta():
    _wipe(A)
    _wipe(B)
    assert _bulk({"sequences": [_seq("Del", 1, n=3), _seq("Keep", 2, n=2)]}).status_code == 200
    b_row = OWNER_B.post(f"/admin/saved-replies?account_id={B}", json={"text": "B's"}).json()
    ids = [x["id"] for x in _list() if x["script_id"] == "Del"]
    r = OWNER_A.post(f"/admin/saved-replies/delete?account_id={A}", json={"ids": ids + [b_row["id"]]})
    assert r.status_code == 200 and r.json() == {"deleted": 3}, r.text
    assert {x["script_id"] for x in _list()} == {"Keep"} and set(_metas()) == {"Keep"}
    assert [x["id"] for x in _list(B, OWNER_B)] == [b_row["id"]]
    r = OWNER_A.post(f"/admin/saved-replies/delete?account_id={B}", json={"ids": [b_row["id"]]})
    assert r.status_code in (403, 404), r.text


def case_sent_counts_one_per_call_on_the_owners_script_only():
    _wipe(A)
    _wipe(B)
    row = OWNER_A.post(f"/admin/saved-replies?account_id={A}", json={"text": "hi"}).json()
    assert row["sent_count"] == 0
    for n in (1, 2):
        r = OWNER_A.post("/admin/saved-replies/sent", json={"id": row["id"]})
        assert r.status_code == 200 and r.json() == {"id": row["id"], "sent_count": n}, r.text
    assert _list()[0]["sent_count"] == 2
    r = OWNER_B.post("/admin/saved-replies/sent", json={"id": row["id"]})
    assert r.status_code in (403, 404), r.text
    assert OWNER_A.post("/admin/saved-replies/sent", json={"id": 10**9}).status_code == 404
    assert _list()[0]["sent_count"] == 2


def case_the_list_reads_more_media_than_sqlites_variable_cap():
    _wipe()

    async def go() -> None:
        async with get_session() as s:
            # 260k distinct ids: past this build's 250,000 bound variables (and the 32,766 default).
            for k in range(2):
                s.add(SavedReply(account_id=A, text=f"m{k}", media_json=json.dumps(
                    [{"id": 1_000_000 + k * 130_000 + i} for i in range(130_000)])))
    asyncio.run(go())
    rows = _list()
    assert len(rows) == 2 and all(len(r["media"]) == 130_000 and r["removed_media_ids"] == [] for r in rows)
    _wipe()


def case_role_gate_bulk_as_the_excel_import_and_batch_delete_as_delete_scripts():
    _wipe()
    assert permissions.route_pages("/admin/saved-replies/bulk", "POST") == ("/growth/scripts",)
    assert permissions.route_action("POST", "/admin/saved-replies/delete") == "delete-script"
    assert permissions.route_pages("/admin/saved-replies/sent", "POST") == ("/messages-pro",)
    emp = asyncio.run(employees.get_or_create_mirror_employee(
        IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))

    def roles(pages: dict) -> None:
        r = OWNER_A.put("/admin/settings/roles", json={
            "enforce": True, "assignments": {str(emp): "r"},
            "roles": [{"id": "r", "name": "Fixture", "description": "", "permissions": pages, "scope": "all"}]})
        assert r.status_code == 200, r.text

    body = {"sequences": [_seq("Gate", 1, n=1)]}
    try:
        roles({"/dashboard": True})
        r = _bulk(body, client=CHATTER_A)
        assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Scripts"}, r.text
        roles({"/growth/scripts": True, "/growth/scripts#delete-script": False})
        assert _bulk(body, client=CHATTER_A).status_code == 200
        ids = [x["id"] for x in _list()]
        r = CHATTER_A.post(f"/admin/saved-replies/delete?account_id={A}", json={"ids": ids})
        assert r.status_code == 403, r.text
        # Replace deletes the sequence's scripts: Delete scripts too, dry run or not; nothing is touched.
        for dry in (False, True):
            r = _bulk({**body, "mode": "replace", "dry_run": dry}, client=CHATTER_A)
            assert r.status_code == 403 and r.json() == {"detail": "Your role does not allow Delete scripts"}, r.text
        assert [x["id"] for x in _list()] == ids
        roles({"/growth/scripts": True})
        r = _bulk({**body, "mode": "replace"}, client=CHATTER_A)
        assert r.status_code == 200 and r.json()["sequences"]["replaced"] == 1, r.text
        ids = [x["id"] for x in _list()]
        r = CHATTER_A.post(f"/admin/saved-replies/delete?account_id={A}", json={"ids": ids})
        assert r.status_code == 200 and r.json()["deleted"] == 1, r.text
    finally:
        assert OWNER_A.put("/admin/settings/roles", json={"enforce": False}).status_code == 200


def case_identical_tag_chunks_at_once_create_each_script_once():
    """Two identical tag-only chunks at once (a re-run beside a stuck run): one bulk per Creator at a time, so the
    second sees the first's scripts and creates none."""
    _wipe()
    body = {"tags": [{"name": "Race", "scripts": [{"name": f"r{i}", "text": f"t{i}"} for i in range(200)]}]}

    async def race():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver",
                                     cookies=dict(OWNER_A.cookies)) as c:
            return await asyncio.gather(*(c.post(f"/admin/saved-replies/bulk?account_id={A}", json=body)
                                          for _ in range(4)))

    got = asyncio.run(race())
    assert [r.status_code for r in got] == [200] * 4, [r.text for r in got]
    assert sorted(r.json()["tag_scripts"]["created"] for r in got) == [0, 0, 0, 200], [r.json() for r in got]
    assert len(_list()) == 200


def case_infloww_html_is_sanitized_to_ofs_markup_and_plain_stays_byte_identical():
    _wipe()
    hostile = '<p><span class="m-editor-fc__gray m-editor-fs__sm" onclick="x">hi</span><script>y</script></p>'
    clean = '<p><span class="m-editor-fs__sm m-editor-fc__gray">hi</span></p>'
    plain = "hey <3 & <VIP20>  "
    seq = {"name": "H", "order": 1, "steps": [{"step": "1", "text": hostile, "name": "h1"},
                                              {"step": "2", "text": plain, "name": "h2"}]}
    r = _bulk({"sequences": [seq]})
    assert r.status_code == 200 and r.json()["sequences"]["created"] == 1, r.text
    assert [s[2] for s in _steps(A, "H")] == [clean, plain]
    # A tag's script matches the stored (sanitized) step text however its markup was written; markup counts as read.
    r = _bulk({"tags": [{"name": "T", "scripts": [{"name": "h1", "text": hostile}, {"name": "h2", "text": plain},
                                                  {"name": "long", "text": "<p>" + "x" * 6500 + "</p>"}]}]})
    assert r.json()["tag_scripts"] == {"total": 3, "created": 1, "tagged": 2, "skipped": 0, "failed": 0}, r.json()
    assert len(_list()) == 3


def case_markup_that_keeps_no_text_fails_and_prose_in_angles_is_stored_as_written():
    _wipe()
    seqs = [{"name": "gone", "order": 1, "steps": [{"step": "1", "text": "ok"},
                                                   {"step": "2", "text": "<img src=x>"}]},
            {"name": "media", "order": 2, "steps": [{"step": "1", "text": "<p></p>"}, {"step": "2", "text": ""}]},
            {"name": "prose", "order": 3, "steps": [{"step": "1", "text": "<link in bio>"},
                                                    {"step": "2", "text": "Use <code VIP20> at checkout"},
                                                    {"step": "3", "text": "my <style is everything>"},
                                                    {"step": "4", "text": "<img src=x onerror=a()>"}]}]
    r = _bulk({"sequences": seqs, "tags": [{"name": "T", "scripts": [{"name": "s", "text": "<font color=red></font>"}]}]})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["sequences"]["created"] == 2 and b["tag_scripts"]["failed"] == 1, b
    assert {(f["name"], f["reason"]) for f in b["failed"]} == {
        ("gone", "step 2: text is only markup that is not kept (nothing a fan would read)"),
        ("s", "text is only markup that is not kept (nothing a fan would read)")}, b["failed"]
    assert [s[2] for s in _steps(A, "media")] == ["<p></p>", ""]
    # prose stays as written; a text that fails closed is stored escaped whole: the fan reads it as written
    assert [s[2] for s in _steps(A, "prose")] == ["<link in bio>", "Use <code VIP20> at checkout",
                                                  "<p>my &lt;style is everything&gt;</p>",
                                                  "<p>&lt;img src=x onerror=a()&gt;</p>"]


def case_old_rows_without_meta_keep_working():
    _wipe()
    for step in (1, 2):
        OWNER_A.post(f"/admin/saved-replies?account_id={A}", json={"text": f"t{step}", "script_id": "Legacy",
                                                                    "script_step": step})
    assert _metas() == {}
    assert [s[2] for s in _steps(A, "Legacy")] == ["t1", "t2"]
    r = _bulk({"sequences": [_seq("Legacy", 1)]})
    assert r.json()["sequences"]["skipped"] == 1 and _metas() == {}, r.text


_harness.run()
