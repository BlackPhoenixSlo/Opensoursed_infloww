"""A standalone scenario must load without imports left by an earlier run."""
from pathlib import Path
import subprocess
import sys


def test_vault_collect_loads_in_a_fresh_harness():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-I", "-c", "\n".join((
            "import sys",
            "from pathlib import Path",
            "sys.path.insert(0, str(Path.cwd()))",
            "from slop.lib.cli import load, SCEN",
            "load(SCEN / '2026-11-05-vault-collect.py')",
        ))],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_models_scenario_keeps_todays_fake():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-I", "-c", "\n".join((
            "import sys",
            "from pathlib import Path",
            "sys.path.insert(0, str(Path.cwd()))",
            "from slop.lib.cli import load, SCEN",
            "load(SCEN / '2026-11-20-all-models-shared-inbox.py')",
            "assert 'slop.lib.all_models_wire' in sys.modules",
            "assert 'slop.lib.badge_wire' not in sys.modules, 'the badge fake is opt-in'",
        ))],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_badge_scenarios_load_and_declare():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-I", "-c", "\n".join((
            "import sys",
            "from pathlib import Path",
            "sys.path.insert(0, str(Path.cwd()))",
            "from slop.lib.cli import load, SCEN",
            "want = {'badge-storm': ('RED_P95_UNDER_2S', 'RED_MAX_UNDER_5S', 'FINAL_EQUALS_TRUTH',",
            "                        'OPERATOR_P95_WITHIN_10PCT', 'RAW_COUNTER_NEVER_RENDERED'),",
            "        'badge-load-sweep-safety': ('ZERO_RELAY_MARKS', 'COUNTER_UNCHANGED_BY_SWEEP'),",
            "        'badge-edge-shared-hover': ('HOVER_ONE_READ_PER_30S', 'HOVER_ANSWERS_FRESH'),",
            "        'badge-edge-deep-inbox': ('NINE_PLUS', 'MUTED_NO_DOT', 'RAW_COUNTER_NEVER_RENDERED',",
            "                                  'INCOMPLETE_NO_FLIP', 'SWAP_SETTLES', 'NO_PHANTOM_AMBER'),",
            "        'badge-edge-degraded': ('GREY_NOT_ZERO', 'NO_READS_DEAD', 'NO_READS_PROXY_DOWN', 'READS_HOLD_ON_429',",
            "                                'SOCKET_DOWN_POLL_15S', 'RECOVERY_UNDER_30S', 'FOCUS_WALK_COMPLETES',",
            "                                'GREY_AFTER_RESTART'),",
            "        'badge-load-elsewhere': ('DOT_FLIP_P95_UNDER_8S', 'DOT_FLIP_MAX_UNDER_30S', 'FINAL_EQUALS_TRUTH',",
            "                                 'READS_GAP_5S', 'READS_SINGLE_FLIGHT', 'READS_MAX_2_PAGES',",
            "                                 'STALE_READ_NEVER_CLEARS', 'LEAN_GAP_15S', 'LEAN_READS_HALVE',",
            "                                 'OFF_ZERO_READS'),",
            "        'badge-load-amber': ('AMBER_P95_UNDER_8S', 'AMBER_MAX_UNDER_30S', 'NO_FAN_IN_BOTH',",
            "                             'FINAL_EQUALS_TRUTH')}",
            "for slug, checks in want.items():",
            "    m = load(next(SCEN.glob(f'*-{slug}.py')))",
            "    assert m.PROFILE and m.OF_WIRE is True and m.TIMEOUT_S == 900, slug",
            "    assert m.CHECKS == checks and all(getattr(m, c) == c for c in checks), slug",
            "    assert set(m.TIERS) == {'small', 'full'}, slug",
            "    assert not any(hasattr(m, k) for k in ('P95_VS_LAST', 'CPU_BUDGET_PCT', 'POOL_GATE')), slug",
            "storm = load(next(SCEN.glob('*-badge-storm.py')))",
            "assert storm.RED_P95_S == 2.0 and storm.RED_MAX_S == 5.0 and storm.OPERATOR_MIN_N == 200",
            "plan = storm.plan([{'id': i} for i in range(storm.CHATS)])",
            "kinds = [f['kind'] for f in plan]",
            "assert kinds.count('only_friends') + kinds.count('restricted') == storm.GAP > kinds.count('plain')",
            "assert all(f['unread'] for f in plan if f['kind'] != 'plain') and kinds.count('muted') == 1",
            "sweep = load(next(SCEN.glob('*-badge-load-sweep-safety.py')))",
            "plan = sweep.plan([{'id': i} for i in range(sweep.CHATS)])",
            "kinds = [f['kind'] for f in plan]",
            "assert len(plan) == 30 and all(f['unread'] for f in plan)",
            "assert kinds.count('only_friends') >= 1 and kinds.count('restricted') == 1 and kinds.count('deep') > 0",
            "assert sweep.phase_a() in (True, False)",
            "elsewhere = load(next(SCEN.glob('*-badge-load-elsewhere.py')))",
            "assert elsewhere.FAULT == 'badge-ordering-fence-off' and elsewhere.RELAY_ENV['BADGE_READS'] == 'full'",
            "assert elsewhere.DOT_P95_S == 8.0 and elsewhere.DOT_MAX_S == 30.0",
            "assert any(f['kind'] == 'only_friends' and f['unread'] for f in elsewhere.plan([{'id': i} for i in range(elsewhere.CHATS)]))",
            "amber = load(next(SCEN.glob('*-badge-load-amber.py')))",
            "assert amber.RELAY_ENV['BADGE_READS'] == 'full' and amber.UI is False and amber.FAULT is None",
            "assert 'require_amber' in Path(amber.__file__).read_text()",
            "assert 'slop.lib.badge_wire' in sys.modules",
        ))],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
