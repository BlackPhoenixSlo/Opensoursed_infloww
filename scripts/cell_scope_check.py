#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_scope_scan  # noqa: E402

if __name__ == "__main__":
    sys.exit(cell_scope_scan.main(["--check", *sys.argv[1:]]))
