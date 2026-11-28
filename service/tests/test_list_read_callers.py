#!/usr/bin/env python3
from __future__ import annotations

import _harness

import ast  # noqa: E402
import importlib  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import NamedTuple  # noqa: E402

import test_platform_lift_table as lift_table  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
READS = frozenset({"list_member_ids", "list_users_in", "_crawl_list_ids_blocking"})
ROSTER_READS = frozenset({"subscribers", "iter_online_subscribers"})
DELETE_WRITES = frozenset({"delete_list"})
DISPATCHERS = frozenset({"_platform_call", "getattr"})
KINDS = frozenset({"read", "refuses", "pass-through", "behind-02f-mass-write-gate", "unused"})


class Row(NamedTuple):
    kind: str
    why: str
    cell: str = ""
    probe: str = ""


CALLERS = {
    "of_paging:list_member_ids.fetch": Row("read", "OnlyFans offset paging inside the read",
                                           "test_of_paging:case_one_page_list_table"),
    "of_paging:_one_page_member_ids": Row("read", "the one-page read using the platform registry",
                                          "test_of_paging:case_one_page_list_table"),
    "audience_include:<module>": Row("read", "`_crawl_list_ids_blocking` alias of `of_paging.list_member_ids`",
                                     "smart_list_sync/chat"),
    "server:of_list_users_in": Row("pass-through", "the route answers the Platform's page with its hasMore; on "
                                                   "Fansly 501 off the one observed 50-row page or on an unknown "
                                                   "list, 502 on a malformed row",
                                   "test_fansly_list_routes:case_fansly_members_route_reads_one_page_and_an_unknown_"
                                   "list_answers_501", "/users"),
    "audiences:roster_audience_blocking.custom": Row("refuses", "an incomplete one-page read raises AudienceRefusal "
                                                                "`platform_lacks:list_users_in:incomplete`",
                                                     "priority_mass/list"),
    "automations.smart_list_sync:_sync_one": Row("refuses", "a truncated read leaves the row `error`, nothing synced",
                                                 "smart_list_sync/chat"),
    "automations.autoreply:_folder_members": Row("refuses", "an incomplete one-page read replies to nobody in the "
                                                            "folder; `folder_error` names the lack", "autoreply/folder"),
    "audience_include:_build_autofence_blocking": Row("behind-02f-mass-write-gate", "autofence for a broadcast",
                                                      "send_mass_message/broadcast"),
    "audiences:_ensure_exclude_blocking": Row("behind-02f-mass-write-gate", "Auto_Exclude sync before a broadcast",
                                              "send_mass_message/broadcast"),
    "audiences:_refresh_auto_exclude": Row("behind-02f-mass-write-gate", "Auto_Exclude refresh after that sync",
                                           "send_mass_message/broadcast"),
    "audiences:_ResumableLists.list_users_in": Row("behind-02f-mass-write-gate", "the refresh's retrying reader",
                                                   "send_mass_message/broadcast"),
    "of_paging:list_audience": Row("refuses", "ListGone propagates; other read errors yield an incomplete "
                                              "ListAudience, which `live_check` refuses as `platform_lacks:delete_list`",
                                   "test_platform_kind_verdicts:case_a_granted_tombstone_deletes_only_a_proof_fan_list"),
}

ROSTER_CALLERS = {
    "of_reads:ReadsMixin.iter_online_subscribers": Row("read", "OnlyFans' own online walk; the Shim overrides it"),
    "server:of_subscribers": Row("pass-through", "the route answers the Platform's page with its hasMore, true on "
                                                 "an incomplete Fansly roster"),
    "automations.lifecycle_messages:_crawl_blocking": Row("refuses", "pages until hasMore is false; an empty page "
                                                                     "with hasMore marks it truncated and "
                                                                     "`_refresh_roster` keeps the old snapshot "
                                                                     "(test_fansly_automation_gates)"),
    "automations.nudge_online:run": Row("refuses", "the online adapter raises `platform_lacks:subscribers:incomplete`; "
                                                   "the run stores `skipped` before any last-seen write or enqueue"),
    "audiences:roster_audience_blocking": Row("refuses", "the `fans` crawl pages via hasMore; a cut read answers "
                                                         "None, or AudienceRefusal on a one-page client"),
    "audiences:resolve_mass_audience": Row("behind-02f-mass-write-gate", "online-only thresholded broadcast; the "
                                                                         "adapter's refusal propagates"),
}

DELETE_CALLERS = {
    "server:_delete_list": Row("refuses", "checks the grant and fresh membership before returning the delete response"),
    "side_effect_gate:delete_list_checked": Row("refuses", "checks the grant and fresh membership before the write"),
}

for _path in sorted(Path(__file__).parent.glob("_list_read_callers_*.py")):
    _mod = importlib.import_module(_path.stem)
    CALLERS.update({c: Row(*r) for c, r in _mod.CALLERS.items()})
    DELETE_CALLERS.update({c: Row(*r) for c, r in getattr(_mod, "DELETE_CALLERS", {}).items()})


def readers(module: str, tree: ast.Module, reads: frozenset = READS) -> set[str]:
    found: set[str] = set()

    class V(ast.NodeVisitor):
        stack: list[str] = []

        def _scope(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

        def _hit(self):
            found.add(f"{module}:{'.'.join(self.stack) or '<module>'}")

        def visit_Name(self, node):
            if node.id in reads:
                self._hit()

        def visit_Attribute(self, node):
            if node.attr in reads:
                self._hit()
            self.generic_visit(node)

        def visit_Call(self, node):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in DISPATCHERS and any(isinstance(a, ast.Constant) and a.value in reads for a in node.args):
                self._hit()
            self.generic_visit(node)

    V().visit(tree)
    return found


def scan(root: Path = SERVICE, reads: frozenset = READS) -> set[str]:
    out: set[str] = set()
    for p in sorted(root.rglob("*.py")):
        if "tests" not in p.relative_to(root).parts:
            out |= readers(".".join(p.relative_to(root).with_suffix("").parts), ast.parse(p.read_text(), str(p)),
                           reads)
    return out


def drift(found: set[str], inventory: dict) -> list[str]:
    return ([f"list read with no Fansly outcome: {c}" for c in sorted(found - set(inventory))]
            + [f"inventory row for no list read: {c}" for c in sorted(set(inventory) - found)])


def cell_problems(rows: dict, verdicts: dict, tests: Path = TESTS) -> list[str]:
    out = []
    for caller, row in sorted(rows.items()):
        module, sep, case = row.cell.partition(":")
        if sep:
            path = tests / f"{module}.py"
            src = path.read_text() if path.is_file() else ""
            cases = {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if not case.startswith("case_") or case not in cases:
                out.append(f"{caller}: no test case {row.cell!r}")
            elif row.kind == "pass-through" and (not row.probe or row.probe not in cases[case]):
                out.append(f"{caller}: test case {row.cell!r} does not name the route {row.probe!r}")
            continue
        kind, _, branch = row.cell.partition("/")
        verdict = verdicts.get(kind, {}).get(branch)
        if verdict is None:
            out.append(f"{caller}: no Fansly verdict cell {row.cell!r}")
        elif verdict.startswith("owner"):
            out.append(f"{caller}: Fansly verdict cell {row.cell!r} is still {verdict!r}")
    return out


def case_every_list_read_caller_has_a_fansly_outcome():
    problems = drift(scan(), CALLERS)
    assert not problems, "\n".join(problems)
    bad = {c: r for c, r in CALLERS.items() if r.kind not in KINDS or not r.why.strip()}
    assert not bad, bad


def case_every_list_read_caller_names_a_fansly_verdict_cell_that_is_not_owner():
    problems = cell_problems(CALLERS, lift_table.kind_verdicts()["fansly"])
    assert not problems, "\n".join(problems)


def case_a_missing_unknown_or_owner_cell_fails():
    verdicts = {"k": {"b": "same", "o": "owner:7", "g": "gated:platform_lacks:x"}}
    rows = {"ok": Row("refuses", "x", "k/b"), "gated": Row("refuses", "x", "k/g"),
            "case": Row("refuses", "x", "test_list_read_callers:case_a_missing_unknown_or_owner_cell_fails"),
            "none": Row("refuses", "x"), "owner": Row("refuses", "x", "k/o"), "branch": Row("refuses", "x", "k/z"),
            "nocase": Row("refuses", "x", "test_list_read_callers:case_gone"),
            "nofile": Row("refuses", "x", "test_gone:case_a"),
            "helper": Row("refuses", "x", "test_list_read_callers:cell_problems"),
            "route": Row("pass-through", "x", "test_list_read_callers:case_an_unlisted_caller_and_a_stale_row_fail",
                         "/users"),
            "routed": Row("pass-through", "x", "test_list_read_callers:case_an_unlisted_caller_and_a_stale_row_fail",
                          "drift(")}
    assert cell_problems(rows, verdicts) == [
        "branch: no Fansly verdict cell 'k/z'",
        "helper: no test case 'test_list_read_callers:cell_problems'",
        "nocase: no test case 'test_list_read_callers:case_gone'",
        "nofile: no test case 'test_gone:case_a'",
        "none: no Fansly verdict cell ''",
        "owner: Fansly verdict cell 'k/o' is still 'owner:7'",
        "route: test case 'test_list_read_callers:case_an_unlisted_caller_and_a_stale_row_fail' does not name "
        "the route '/users'",
    ], cell_problems(rows, verdicts)


def case_an_unused_reader_has_no_relay_caller():
    for caller in (c for c, r in CALLERS.items() if r.kind == "unused"):
        name = caller.rpartition(":")[2].rpartition(".")[2]
        assert not (refs := scan(reads=frozenset({name}))), (caller, refs)


def case_every_roster_read_caller_checks_the_incomplete_flag():
    problems = drift(scan(reads=ROSTER_READS), ROSTER_CALLERS)
    assert not problems, "\n".join(problems)
    assert all(r.kind in KINDS and r.why.strip() for r in ROSTER_CALLERS.values()), ROSTER_CALLERS


def case_every_list_delete_caller_checks_the_grant_before_the_write():
    problems = drift(scan(reads=DELETE_WRITES), DELETE_CALLERS)
    assert not problems, "\n".join(problems)
    assert all(r.kind == "refuses" and r.why.strip() for r in DELETE_CALLERS.values()), DELETE_CALLERS


def case_an_unlisted_caller_and_a_stale_row_fail():
    rows = {"a:f": Row("refuses", "x")}
    assert drift({"a:f"}, rows) == []
    assert drift({"a:f", "b:g"}, rows) == ["list read with no Fansly outcome: b:g"]
    assert drift(set(), rows) == ["inventory row for no list read: a:f"]


def case_a_new_reader_in_a_module_is_found():
    tree = ast.parse("import of_paging\n"
                     "def fresh(c, lid):\n    return of_paging.list_member_ids(c, lid)\n"
                     "def routed(name):\n    return _platform_call('list_users_in', 'x')\n"
                     "class K:\n    def m(self, c):\n        return c.list_users_in(1)\n"
                     "def other(c):\n    return c.get_list(1)\n")
    assert readers("lane", tree) == {"lane:fresh", "lane:routed", "lane:K.m"}


_harness.run(
    case_every_list_read_caller_has_a_fansly_outcome,
    case_every_list_read_caller_names_a_fansly_verdict_cell_that_is_not_owner,
    case_a_missing_unknown_or_owner_cell_fails,
    case_an_unused_reader_has_no_relay_caller,
    case_every_roster_read_caller_checks_the_incomplete_flag,
    case_every_list_delete_caller_checks_the_grant_before_the_write,
    case_an_unlisted_caller_and_a_stale_row_fail,
    case_a_new_reader_in_a_module_is_found,
)
