import copy
import json
import subprocess
import sys
from pathlib import Path

from sweep_diff import ny_unchanged, ro_counts, sweep_diff

HERE = Path(__file__).parent
SWEEP = HERE.parent.parent / "docs/of-manager/not-yet-sweep-2026-11-20.json"
OLD = json.loads(SWEEP.read_text())


def page(sweep, name):
    return next(v for p, v in sweep if p == name)


def with_ro(sweep, ro):
    out = copy.deepcopy(sweep)
    for p, v in out:
        v["ro"] = list(ro.get(p, []))
    return out


def log(counts, scope="model:1"):
    lines = ['{"check": "model:1: pages swept", "want": true, "got": true}']
    lines += [json.dumps({"scope": scope, "page": p, "controls": 9, "links": 0, "wired": 0, "readonly": n}) for p, n in counts.items()]
    lines.append(json.dumps({"scope": scope, "pages": len(counts), "controls": 9, "links": 0, "wired": 0, "readonly": sum(counts.values())}))
    return lines


def test_old_file_diffs_against_new_shape_all_kept():
    new = with_ro(OLD, {"collections/index": ["New list"]})
    diff = sweep_diff(OLD, new)
    assert all(not d["removed"] and not d["added"] for d in diff.values())
    assert [k for k in diff["collections"]["kept"] if k[0] == "collections/index"] == [
        ["collections/index", "ny", "Search"], ["collections/index", "ny", "Sort"],
        ["collections/index", "ny", "Pin to home"], ["collections/index", "ny", "Posts"]]
    assert ny_unchanged(OLD, new) == []


def test_removed_and_added_per_section():
    new = with_ro(OLD, {})
    page(new, "collections/index")["ny"].remove("Pin to home")
    page(new, "settings/account/sessions")["ny"].append("Log out")
    diff = sweep_diff(OLD, new)
    assert diff["collections"]["removed"] == [["collections/index", "ny", "Pin to home"]]
    assert diff["collections"]["added"] == []
    assert diff["settings"]["added"] == [["settings/account/sessions", "ny", "Log out"]]
    assert diff["home"]["removed"] == diff["home"]["added"] == []


def test_ro_diffed_when_both_files_list_it():
    old = with_ro(OLD, {"queue/index": ["More", "Sort"]})
    new = with_ro(OLD, {"queue/index": ["More", "Filter"]})
    diff = sweep_diff(old, new)
    assert diff["queue"]["removed"] == [["queue/index", "ro", "Sort"]]
    assert diff["queue"]["added"] == [["queue/index", "ro", "Filter"]]
    assert ["queue/index", "ro", "More"] in diff["queue"]["kept"]


def test_ro_repeats_count():
    old = with_ro(OLD, {"queue/index": ["More", "More"]})
    new = with_ro(OLD, {"queue/index": ["More"]})
    assert sweep_diff(old, new)["queue"]["removed"] == [["queue/index", "ro", "More"]]


def test_page_only_in_one_file_is_listed_not_diffed():
    new = with_ro(OLD, {}) + [["release-forms/index", {"ny": ["Create new invitation link"], "dis": [], "ro": []}]]
    diff = sweep_diff(OLD, new)
    assert diff["release-forms"] == {"removed": [], "added": [], "kept": [], "pages only in new": ["release-forms/index"]}
    partial = [x for x in with_ro(OLD, {}) if x[0].startswith("queue/")]
    assert sweep_diff(OLD, partial)["home"]["pages only in old"][0] == "home/index"


def test_expect_ny_unchanged_fails_on_edited_copy():
    edited = with_ro(OLD, {})
    page(edited, "messages/chat")["ny"].remove("More")
    page(edited, "settings/streaming")["ny"].append("Go live")
    problems = ny_unchanged(OLD, edited)
    assert len(problems) == 2
    assert any("messages/chat" in p and "More" in p for p in problems)
    assert any("settings/streaming" in p and "Go live" in p for p in problems)


def test_expect_ny_unchanged_fails_on_missing_page():
    short = [x for x in with_ro(OLD, {}) if x[0] != "home/index"]
    assert [p for p in ny_unchanged(OLD, short) if "home/index" in p]


def test_expect_ny_unchanged_ignores_order_and_dis():
    reordered = with_ro(OLD, {})
    page(reordered, "collections/index")["ny"].reverse()
    page(reordered, "home/index")["dis"] = []
    assert ny_unchanged(OLD, reordered) == []


def test_expect_ro_counts():
    new = with_ro(OLD[:3], {"home/index": ["More", "Add to story"], "home/state-avatar-menu": ["More"]})
    good = {"home/index": 2, "home/state-avatar-menu": 1, "home/state-expiration": 0}
    assert ro_counts(new, log(good)) == []
    assert ro_counts(new, log(good) + log({"home/index": 5}, scope="all creators")) == []
    wrong = ro_counts(new, log({**good, "home/index": 3}))
    assert len(wrong) == 1 and "home/index" in wrong[0]
    missing = ro_counts(new, log({"home/index": 2, "home/state-avatar-menu": 1}))
    assert len(missing) == 1 and "home/state-expiration" in missing[0]


def test_expect_ro_counts_total_above_zero():
    new = with_ro(OLD[:2], {})
    problems = ro_counts(new, log({"home/index": 0, "home/state-avatar-menu": 0}))
    assert len(problems) == 1 and "total" in problems[0]


def run_cli(*args):
    return subprocess.run([sys.executable, "-I", str(HERE / "sweep_diff.py"), *map(str, args)], capture_output=True, text=True)


def test_cli_passes_on_unchanged_regeneration(tmp_path):
    new = with_ro(OLD, {"collections/index": ["New list"]})
    (tmp_path / "new.json").write_text(json.dumps(new))
    counts = {p: len(v["ro"]) for p, v in new}
    (tmp_path / "dead.log").write_text("\n".join(log(counts) + ["dead ok"]) + "\n")
    r = run_cli("--expect-ny-unchanged", "--expect-ro-counts", tmp_path / "dead.log", SWEEP, tmp_path / "new.json")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    assert [x["section"] for x in lines][:2] == ["home", "streaming"]
    assert all(set(x) >= {"section", "removed", "added", "kept"} for x in lines)


def test_cli_fails_on_edited_copy(tmp_path):
    edited = with_ro(OLD, {"collections/index": ["New list"]})
    page(edited, "collections/index")["ny"].remove("Sort")
    (tmp_path / "new.json").write_text(json.dumps(edited))
    counts = {p: len(v["ro"]) for p, v in edited}
    (tmp_path / "dead.log").write_text("\n".join(log(counts)))
    r = run_cli("--expect-ny-unchanged", SWEEP, tmp_path / "new.json")
    assert r.returncode == 1 and "collections/index" in r.stdout
    counts["collections/index"] = 4
    (tmp_path / "dead.log").write_text("\n".join(log(counts)))
    r = run_cli("--expect-ro-counts", tmp_path / "dead.log", SWEEP, tmp_path / "new.json")
    assert r.returncode == 1 and "collections/index" in r.stdout
    assert run_cli(SWEEP, tmp_path / "new.json").returncode == 0


def test_dates_compare_as_date_placeholder():
    for label in ["From {date} To {date}", "From Dec 3, 2026 To Dec 3, 2026"]:
        new = with_ro(OLD, {})
        page(new, "statements/stats/earnings")["ny"] = [label]
        assert ny_unchanged(OLD, new) == []
        assert sweep_diff(OLD, new)["statements"]["removed"] == []
    changed = with_ro(OLD, {})
    page(changed, "statements/stats/earnings")["ny"] = ["From {date}"]
    assert ny_unchanged(OLD, changed)
