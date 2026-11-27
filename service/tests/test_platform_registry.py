#!/usr/bin/env python3
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first (binds temp DB)

import ast  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import accounts  # noqa: E402
import fansly_backend  # noqa: E402
import platforms  # noqa: E402

LACK_REASONS = {
    "REFERRALS": "platform_lacks:referrals",
    "WALL_MEDIA": "platform_lacks:wall_media",
    "SERVER_SCHEDULE": "platform_lacks:server_schedule",
    "NEAR_SCHEDULE_MEDIA": "platform_lacks:near_schedule_media",
    "HISTORY_UNREAD_GATE": "platform_lacks:history_unread_gate",
    "UNREAD_TOTAL": "platform_lacks:unread_total",
    "SHARED_REFRESH": "platform_lacks:shared_refresh",
    "TIP_LEDGER": "platform_lacks:tip_ledger",
    "PURCHASE_LINKAGE": "platform_lacks:purchase_linkage",
    "RENEWAL_STATE": "platform_lacks:renewal_state",
    "LAPSE_DETECTION": "platform_lacks:lapse_detection",
    "RETURN_DETECTION": "platform_lacks:return_detection",
}


def case_get_and_require_resolve_every_key():
    for key, want in [(None, platforms.ONLYFANS), ("", platforms.ONLYFANS), ("  ", platforms.ONLYFANS),
                      ("onlyfans", platforms.ONLYFANS), ("OnlyFans", platforms.ONLYFANS),
                      (" onlyfans ", platforms.ONLYFANS), ("fansly", platforms.FANSLY),
                      (["onlyfans"], platforms.ONLYFANS), ({"key": "fansly"}, platforms.ONLYFANS),
                      (42, platforms.ONLYFANS)]:
        assert platforms.get(key) is want and platforms.require(key) is want, (key, platforms.get(key))
    unknown = platforms.get("myspace")
    assert isinstance(unknown, platforms.UnknownPlatform) and unknown not in platforms.ALL, unknown
    assert (unknown.key, unknown.label, unknown.backend, unknown.lacks) == (
        "myspace", "Unknown platform", None, frozenset(platforms.Lack)), unknown
    try:
        platforms.require("myspace")
    except ValueError as e:
        assert isinstance(e, platforms.UnknownPlatformKey) and str(e) == "platform_unknown:myspace", e
    else:
        raise AssertionError("require('myspace') must raise")


def case_for_account_reads_get_platform_at_call_time():
    orig = accounts.get_platform
    try:
        for key, want in [(None, platforms.ONLYFANS), ("onlyfans", platforms.ONLYFANS),
                          ("fansly", platforms.FANSLY), ("myspace", platforms.UnknownPlatform("myspace"))]:
            accounts.get_platform = lambda aid, k=key: k
            assert platforms.for_account("acc_1") == want, (key, platforms.for_account("acc_1"))
        for name in ("send_message", "get_chats", "no_such_method"):
            assert platforms.refusal_for_account("acc_1", name) == "platform_unknown:myspace", name
    finally:
        accounts.get_platform = orig


def case_keys_and_session_files():
    assert platforms.ALL == (platforms.ONLYFANS, platforms.FANSLY), platforms.ALL
    assert platforms.KEYS == ("onlyfans", "fansly"), platforms.KEYS
    assert platforms.SESSION_FILES == ("latest.json", "fansly_session.json"), platforms.SESSION_FILES
    assert platforms.ONLYFANS.label == "OF" and platforms.FANSLY.label == "Fansly"


def case_backends_is_exactly_fansly():
    assert platforms.ONLYFANS.backend is None
    assert platforms.backends() == (fansly_backend,), platforms.backends()


CONTRACT = ("get_client", "drop", "ws", "revenue_tick", "check_sendable", "APIError", "Shim")


def case_every_backend_exposes_the_contract():
    for mod in platforms.backends():
        missing = [n for n in CONTRACT if not hasattr(mod, n)]
        assert not missing, (mod.__name__, missing)
        assert isinstance(mod.Shim, type) and issubclass(mod.APIError, Exception), mod.__name__


def case_lack_values_equal_names():
    assert {m.name for m in platforms.Lack} == set(LACK_REASONS), [m.name for m in platforms.Lack]
    for m in platforms.Lack:
        assert m.value == m.name and m == m.name, m
    assert platforms.ONLYFANS.lacks == frozenset()
    assert platforms.FANSLY.lacks == frozenset(platforms.Lack), platforms.FANSLY.lacks


def case_lack_reason_is_lower_case_platform_lacks():
    for m in platforms.Lack:
        assert platforms.lack_reason(m) == LACK_REASONS[m.name], (m, platforms.lack_reason(m))


def case_free_follow_only_on_fansly():
    assert [p.key for p in platforms.ALL if p.free_follow] == ["fansly"]


_SERVICE = Path(__file__).resolve().parents[1]
ALLOWED = {
    "platforms.py", "accounts.py", "fansly_backend.py", "fansly_revenue.py", "remote_login_fansly.py",
    "accounts_admin_api.py",
    "automations/_outbound_guard.py",
}


def _is_get_platform_call(n: ast.AST) -> bool:
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    return ((isinstance(f, ast.Name) and f.id == "get_platform")
            or (isinstance(f, ast.Attribute) and f.attr == "get_platform"))


def _entry_names(p: platforms.Platform) -> list[str]:
    return [n for n, v in vars(platforms).items() if v is p and n.isupper()]


def _probes() -> tuple[set[str], set[str]]:
    others = [p for p in platforms.ALL if p is not platforms.ONLYFANS]
    words = {w.lower() for p in others for w in (p.key, p.label)}
    return words, {n for p in others for n in _entry_names(p)}


def scan(source: str) -> list[int]:
    words, names = _probes()
    hits: set[int] = set()
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.lower() in words:
            hits.add(n.lineno)
        elif ((isinstance(n, ast.Name) and n.id in names)
              or (isinstance(n, ast.Attribute) and n.attr in names)):
            hits.add(n.lineno)
        elif isinstance(n, ast.Compare) and any(
                _is_get_platform_call(o) for o in (n.left, *n.comparators)):
            hits.add(n.lineno)
    return sorted(hits)


def scan_tree(root: Path = _SERVICE) -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("tests/") or rel in ALLOWED:
            continue
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        for ln in scan(src):
            found.setdefault((rel, lines[ln - 1].strip()), []).append(ln)
    return found


def case_scan_passes_on_todays_tree():
    found = scan_tree()
    assert not found, "\n  ".join(
        ["Platform-key comparison outside the registry; ask platforms instead:",
         *(f"{rel}:{ln}  {text}" for (rel, text), lns in found.items() for ln in lns)])


def case_scan_catches_offenders():
    cases = [
        ('if get_platform(a) == "fansly":\n    pass', [1]),
        ('if accounts.get_platform(a) != "onlyfans":\n    pass', [1]),
        ('ok = "onlyfans" == account_registry.get_platform(a)', [1]),
        ('k = "FANSLY"', [1]),
        ('k = "Fansly"', [1]),
        ('p = platforms.FANSLY', [1]),
        ('p = FANSLY', [1]),
        ('x = 1\nif meta.get("platform") == "fansly":\n    pass', [2]),
        ('hit = await asyncio.to_thread(accounts.get_platform, aid)', []),
        ('p = accounts.get_platform(aid)', []),
        ('FLAGS = ("fansly_manager",)', []),
        ('HOST = ".fansly.com"', []),
        ('"""A Fansly snowflake."""', []),
        ('import fansly_backend', []),
    ]
    for src, want in cases:
        assert scan(src) == want, (src, scan(src), want)


def case_scan_derives_probes_from_every_non_onlyfans_platform():
    others = [p for p in platforms.ALL if p is not platforms.ONLYFANS]
    assert others, platforms.ALL
    for p in others:
        names = _entry_names(p)
        assert names, p.key
        probes = [f'x = 1\nif meta.get("platform") == "{p.key}":\n    pass',
                  f'k = "{p.key.upper()}"', f'k = "{p.label}"',
                  *(f"p = {n}" for n in names), *(f"p = platforms.{n}" for n in names)]
        for src in probes:
            assert scan(src), (p.key, src)


def case_scan_covers_a_platform_added_to_the_registry():
    myspace = platforms.Platform("myspace", "MySpace", "myspace_session.json", fansly_backend,
                                 frozenset(), login="remote_login_myspace")
    orig = platforms.ALL
    platforms.MYSPACE = myspace
    platforms.ALL = (*orig, myspace)
    try:
        assert scan('if meta.get("platform") == "myspace":\n    pass') == [1]
        assert scan('k = "MySpace"') == [1] and scan("p = platforms.MYSPACE") == [1]
    finally:
        platforms.ALL = orig
        del platforms.MYSPACE
    assert scan('if meta.get("platform") == "myspace":\n    pass') == []


def case_scan_tree_skips_tests_and_allowlist():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "tests").mkdir()
        (root / "automations").mkdir()
        bad = 'if get_platform(a) == "fansly":\n    pass\n'
        for rel in ("tests/test_x.py", "platforms.py", "automations/_outbound_guard.py",
                    "automations/new_lane.py", "new_mod.py"):
            (root / rel).write_text(bad)
        (root / "two.py").write_text('x = {"a": 1}\nif get_platform(a) == "fansly": pass\n'
                                      'if get_platform(a) == "fansly": pass\n')
        (root / "planted.py").write_text('import os\nKEY = "fansly"\n')
        found = scan_tree(root)
        hit = 'if get_platform(a) == "fansly":'
        assert found == {("automations/new_lane.py", hit): [1], ("new_mod.py", hit): [1],
                         ("planted.py", 'KEY = "fansly"'): [2],
                         ("two.py", hit + " pass"): [2, 3]}, found


_harness.run()
