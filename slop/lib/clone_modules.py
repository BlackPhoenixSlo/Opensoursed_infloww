"""Clone app/node_modules into a linked worktree before its venv exists."""
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def clone(main: Path, root: Path) -> bool:
    source, app = main / "app/node_modules", root / "app"
    if not source.is_dir():
        return False
    dest = app / "node_modules"
    if dest.is_dir() and not dest.is_symlink():
        return False
    app.mkdir(parents=True, exist_ok=True)
    scratch = app / ".next"
    scratch.mkdir(exist_ok=True)
    with (scratch / "slop-node_modules.lock").open("a+") as lock:
        deadline = time.monotonic() + 900
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("slop: timed out waiting for app/node_modules copy")
                time.sleep(0.2)
        for stale in scratch.glob("slop-node_modules.tmp.*"):
            shutil.rmtree(stale)
        if dest.is_dir() and not dest.is_symlink():
            return False
        tmp = Path(tempfile.mkdtemp(prefix="slop-node_modules.tmp.", dir=scratch))
        try:
            try:
                subprocess.run(["cp", "-cR", str(source) + "/.", str(tmp)], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.CalledProcessError):
                shutil.rmtree(tmp)
                tmp.mkdir()
                subprocess.run(["cp", "-R", str(source) + "/.", str(tmp)], check=True)
            tmp.chmod(0o755)
            if dest.is_symlink():
                dest.unlink()  # unlink only the worktree link, never its target
            os.replace(tmp, dest)
            return True
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)


if __name__ == "__main__":
    if clone(Path(sys.argv[1]), Path(sys.argv[2])):
        print(f"slop: worktree: copied app/node_modules from {sys.argv[1]}", file=sys.stderr)
