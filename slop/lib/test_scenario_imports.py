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
