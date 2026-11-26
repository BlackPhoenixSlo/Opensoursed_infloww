import json
from pathlib import Path

from run_tests_parallel import RUN_FILE, discover_scripts


def seed_probe_run(path: Path, mode: str) -> None:
    names = [p.stem for p in discover_scripts(Path(__file__).parent)]
    path.mkdir()
    (path / RUN_FILE).write_text(json.dumps({"mode": mode, "run_id": path.as_posix()}))
    (path / "_scripts.txt").write_text("".join(f"{name}\n" for name in names))
    (path / "_rc.tsv").write_text("".join(f"0\t{name}\n" for name in names))
    for name in names:
        (path / f"{name}.jsonl").touch()
