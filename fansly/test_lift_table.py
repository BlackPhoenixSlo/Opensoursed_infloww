import pathlib
import subprocess
import sys

TEST = pathlib.Path(__file__).resolve().parents[1] / "service" / "tests" / "test_platform_lift_table.py"

if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, str(TEST)]))
