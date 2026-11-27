#!/usr/bin/env python3
import _harness

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import platforms
import smart_list_rules
from side_effect_gate import LIVE_CHECK_LANES, PLATFORM_LACKS_PREFIX, PLATFORM_UNKNOWN_PREFIX, classify

ROOT = Path(__file__).resolve().parents[2]
PARITY = ROOT / "fansly" / "FANSLY_PARITY_STATUS.md"
VERDICTS = Path(__file__).resolve().parent / "test_platform_kind_verdicts.py"
HEADING = "## Lift table"
COLUMNS = ["Reason", "Where it refuses", "Grade + evidence", "Lifted by", "Owner action", "Follow-up PR", "Ticket"]
UNKNOWN_ROW = f"{PLATFORM_UNKNOWN_PREFIX}<key>"

_COUNTED = re.compile(r":\d+$")
_TICKED = re.compile(r"`([^`]+)`")
_RAISED = re.compile(rf'reason="({PLATFORM_LACKS_PREFIX}[^"{{]+)"')


def normalise(reason: str) -> str:
    return _COUNTED.sub("", reason)


def _literal(path: Path, name: str) -> dict:
    node = next(n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == name for t in n.targets))
    return ast.literal_eval(node.value)


def kind_verdicts() -> dict:
    out = _literal(VERDICTS, "KIND_VERDICTS")
    for path in sorted(VERDICTS.parent.glob("_kind_verdicts_*.py")):
        for platform, kinds in _literal(path, "VERDICTS").items():
            out[platform] = dict(sorted({**out[platform], **kinds}.items()))
    return out


def table_rows(text: str) -> list[list[str]]:
    lines = text.splitlines()
    try:
        start = lines.index(HEADING)
    except ValueError:
        return []
    table = []
    for line in lines[start + 1:]:
        if line.startswith("|"):
            table.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif table:
            break
    return table


def table_reasons(rows: list[list[str]]) -> list[str]:
    return [normalise(r) for row in rows[2:] for r in _TICKED.findall(row[0])]


def raised_reasons(shim: type) -> set[str]:
    out: set[str] = set()
    for cls in shim.__mro__:
        try:
            out |= set(_RAISED.findall(inspect.getsource(cls)))
        except (OSError, TypeError):
            continue
    return out


def expected_reasons(registry, lacks, verdicts: dict, lanes=LIVE_CHECK_LANES,
                     rules=smart_list_rules.RULE_REFUSALS) -> set[str]:
    out = {platforms.lack_reason(lack) for lack in lacks} | {UNKNOWN_ROW}
    out |= {f"{PLATFORM_LACKS_PREFIX}{n}" for n in lanes} | set(rules)
    for p in registry:
        if p.backend is None:
            continue
        shim = p.backend.Shim
        out |= {f"{PLATFORM_LACKS_PREFIX}{n}" for n in dir(shim) if classify(shim, n)[0] not in ("built", "missing")}
        out |= set(shim.SEND_REFUSALS.values()) | raised_reasons(shim)
    for kinds in verdicts.values():
        for branches in kinds.values():
            for verdict in branches.values():
                head, _, tail = verdict.partition(":")
                if head == "gated":
                    out.add(tail)
    return {normalise(r) for r in out}


def failures(rows: list[list[str]], expected: set[str]) -> list[str]:
    if not rows:
        return [f"no table under {HEADING!r}"]
    out = []
    if rows[0] != COLUMNS:
        out.append(f"columns {rows[0]} != {COLUMNS}")
    out += [f"row {r[0]!r} has {len(r)} cells" for r in rows[2:] if len(r) != len(COLUMNS)]
    got = table_reasons(rows)
    out += [f"reason in more than one row: {r}" for r in sorted({r for r in got if got.count(r) > 1})]
    out += [f"refusal without a Lift row: {r}" for r in sorted(expected - set(got))]
    out += [f"Lift row for no refusal: {r}" for r in sorted(set(got) - expected)]
    return out


def case_lift_table_matches_every_refusal():
    text = PARITY.read_text()
    rows = table_rows(text)
    print(f"{len(rows[2:])} Lift rows, {len(table_reasons(rows))} reasons")
    problems = failures(rows, expected_reasons(platforms.ALL, tuple(platforms.Lack), kind_verdicts()))
    assert not problems, f"{len(problems)} Lift-table failures:\n  " + "\n  ".join(problems)


def case_no_phase_1b_row_claims_a_live_check_pass():
    rows = [line for line in PARITY.read_text().splitlines() if line.startswith("|")]
    assert not [r for r in rows if "✅ `Live check" in r]


def case_counted_reason_collapses_to_its_row():
    assert normalise("x:contact_guard:3") == "x:contact_guard"
    assert normalise("platform_lacks:create_post:media") == "platform_lacks:create_post:media"
    assert normalise("x:1:2") == "x:1"


def _doc(*reasons: str) -> str:
    rows = "\n".join(f"| {' '.join(f'`{r}`' for r in group)} | a | b | c | d | e | f |" for group in reasons)
    return f"{HEADING}\n\n| {' | '.join(COLUMNS)} |\n|{'---|' * len(COLUMNS)}\n{rows}\n\nafter\n| `stray` |\n"


def _fake_registry(**marks):
    shim = type("Shim", (), {"SEND_REFUSALS": {"tagged_users": "platform_lacks:tagged_users"}})
    for name, verdict in marks.items():
        fn = lambda self: None
        setattr(fn, f"platform_{verdict}", "why")
        setattr(shim, name, fn)
    return (SimpleNamespace(key="onlyfans", backend=None), SimpleNamespace(key="fake", backend=SimpleNamespace(Shim=shim)))


_LACKS = (platforms.Lack.REFERRALS,)
_VERDICTS = {"fake": {"k": {"run": "same", "x": "gated:x:contact_guard:3"}}}
_FULL = (("platform_lacks:referrals",), ("platform_lacks:pin", "platform_lacks:tagged_users"),
         ("x:contact_guard", UNKNOWN_ROW))


def _fake_failures(text: str, registry=None, lacks=_LACKS, verdicts=None, lanes=frozenset()) -> list[str]:
    return failures(table_rows(text), expected_reasons(registry or _fake_registry(pin="blocked"), lacks,
                                                       verdicts or _VERDICTS, lanes, frozenset()))


def case_full_fake_table_passes():
    assert _fake_failures(_doc(*_FULL)) == []


def case_removed_row_fails():
    assert _fake_failures(_doc(*_FULL[:2])) == [
        f"refusal without a Lift row: {UNKNOWN_ROW}", "refusal without a Lift row: x:contact_guard"]


def case_new_marker_without_row_fails():
    got = _fake_failures(_doc(*_FULL), registry=_fake_registry(pin="blocked", nudge="live_check"))
    assert got == ["refusal without a Lift row: platform_lacks:nudge"], got


def case_new_lane_without_row_fails():
    got = _fake_failures(_doc(*_FULL), lanes=frozenset({"priority_mass"}))
    assert got == ["refusal without a Lift row: platform_lacks:priority_mass"], got


def case_new_lack_without_row_fails():
    got = _fake_failures(_doc(*_FULL), lacks=(platforms.Lack.REFERRALS, platforms.Lack.TIP_LEDGER))
    assert got == ["refusal without a Lift row: platform_lacks:tip_ledger"], got


class _RaisingShim:
    SEND_REFUSALS = {"tagged_users": "platform_lacks:tagged_users"}

    def read(self):
        return dict(reason="platform_lacks:raised_only")


def case_new_raised_reason_without_row_fails():
    registry = (SimpleNamespace(key="fake", backend=SimpleNamespace(Shim=_RaisingShim)),)
    got = _fake_failures(_doc(*_FULL), registry=registry)
    assert got == ["refusal without a Lift row: platform_lacks:raised_only",
                   "Lift row for no refusal: platform_lacks:pin"], got
    assert raised_reasons(type("Shim", (), {})) == set()


def case_new_gated_reason_without_row_fails():
    verdicts = {"fake": {**_VERDICTS["fake"], "j": {"run": "gated:platform_lacks:create_post:media"}}}
    got = _fake_failures(_doc(*_FULL), verdicts=verdicts)
    assert got == ["refusal without a Lift row: platform_lacks:create_post:media"], got


def case_row_for_no_refusal_and_duplicate_fail():
    got = _fake_failures(_doc(*_FULL, ("platform_lacks:gone", "platform_lacks:referrals")))
    assert got == ["reason in more than one row: platform_lacks:referrals", "Lift row for no refusal: platform_lacks:gone"], got


def case_owner_placeholder_cells_pass():
    text = _doc(*_FULL).replace("| a | b | c | d | e | f |", "| a | owner: | owner: | owner: | owner: | owner: |", 1)
    assert _fake_failures(text) == []


def case_bad_header_and_missing_table_fail():
    assert _fake_failures(_doc(*_FULL).replace("| Ticket |", "| Tix |"))[0].startswith("columns ")
    assert _fake_failures("no heading") == [f"no table under {HEADING!r}"]


if __name__ == "__main__":
    _harness.run()
