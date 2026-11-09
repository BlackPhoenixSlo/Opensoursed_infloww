import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from slop.lib import clone_modules, report


ROOT = Path(__file__).resolve().parents[2]


def _repo(tmp_path):
    work = tmp_path / "work"
    (work / "app").mkdir(parents=True)
    (work / "slop").mkdir()
    (work / "app/.gitignore").write_text((ROOT / "app/.gitignore").read_text())
    (work / "slop/.gitignore").write_text((ROOT / "slop/.gitignore").read_text())
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / ".git/info/exclude").write_text("app/.gitignore\nslop/.gitignore\n")
    return work


def test_clone_leaves_clean_repo_and_cleans_killed_copy(tmp_path):
    work = _repo(tmp_path)
    main = tmp_path / "main"
    source = main / "app/node_modules"
    source.mkdir(parents=True)
    (source / "package").write_text("data")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ready = tmp_path / "copy-started"
    cp = bin_dir / "cp"
    cp.write_text("#!/bin/sh\ntouch \"$COPY_READY\"\nsleep 60\n")
    cp.chmod(0o755)
    proc = subprocess.Popen([sys.executable, clone_modules.__file__, str(main), str(work)],
                            env={**os.environ, "PATH": str(bin_dir) + ":" + os.environ["PATH"],
                                 "COPY_READY": str(ready)}, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    assert list((work / "app/.next").glob("slop-node_modules.tmp.*"))
    assert clone_modules.clone(main, work)
    assert not list((work / "app/.next").glob("slop-node_modules.tmp.*"))
    assert stat.S_IMODE((work / "app/node_modules").stat().st_mode) == 0o755
    assert not clone_modules.clone(main, work)
    status = subprocess.check_output(["git", "-C", str(work), "status", "--porcelain"], text=True)
    assert status == ""


def test_atomic_temp_is_ignored_and_final_mode_is_readable(tmp_path, monkeypatch):
    work = _repo(tmp_path)
    path = work / "slop/map.json"
    original = report.tempfile.mkstemp
    names = []

    def capture(*args, **kwargs):
        fd, name = original(*args, **kwargs)
        names.append(name)
        return fd, name

    monkeypatch.setattr(report.tempfile, "mkstemp", capture)
    report.write_atomic(path, "{}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    leftover = Path(names[0])
    leftover.touch()
    ignored = subprocess.run(["git", "-C", str(work), "check-ignore", "-q", str(leftover)])
    assert ignored.returncode == 0
