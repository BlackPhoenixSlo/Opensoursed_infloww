from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from proof_core import is_lockout  # noqa: E402
from prove import proof_ok  # noqa: E402

PY = ROOT / "venv" / "bin" / "python"
CAPTURES = ROOT / "docs" / "of-manager" / "captures"
COMMITTED_SWEEP = ROOT / "docs" / "of-manager" / "not-yet-sweep-2026-11-20.json"
COMMITTED_OVERLAYS = (ROOT / "docs" / "of-manager" / "not-yet-sweep-2026-11-21-live.json",
                      ROOT / "docs" / "of-manager" / "not-yet-sweep-2026-11-21-own-bubbles.json")
SWEEP_SECTIONS = {3: ("settings", "profile")}
RETRYABLE = re.compile(r"Page\.goto: Timeout|no Mirror frame")
LOCK_HELD = "refused: lock held"
LOCK_WAIT, LOCK_TRIES = 15, 80  # 20 min of another lane's runs at most
_EVIDENCE = re.compile(r"^ofm-live-proof: evidence (\S+)", re.M)


def phase_proofs(n: int) -> list:
    mod = importlib.import_module(f"proofs.phase{n}")
    return [*mod.PROOFS, *getattr(mod, "WIRED_PROOFS", ())]


def batches(proofs, size: int, lockout=is_lockout) -> list[tuple[list[str], bool]]:
    plain = [p.id for p in proofs if not lockout(p)]
    locked = [p.id for p in proofs if lockout(p)]
    return ([(plain[i:i + size], False) for i in range(0, len(plain), size)]
            + [(locked[i:i + size], True) for i in range(0, len(locked), size)])


def evidence_of(output: str) -> str | None:
    m = _EVIDENCE.search(output)
    return m.group(1) if m else None


def retry_ids(rep: dict) -> list[str] | None:
    if rep.get("run_ok") is not True:
        return None
    if rep.get("exit") == 0:
        return []
    bad = [r for r in rep.get("proofs", []) if not proof_ok(r)]
    if not bad:
        return None
    if all(r.get("problems") and all(RETRYABLE.search(x) for x in r["problems"]) for r in bad):
        return [r["proof"] for r in bad]
    return None


def run(ids: list[str], lockout: bool) -> tuple[int, str | None, dict | None]:
    """One run.sh fake run: (exit, evidence folder, report.json), retried while another run holds the lock."""
    cmd = [str(ROOT / "scripts" / "of-live-proof" / "run.sh"), "--of", "fake", "--proof", ",".join(ids)]
    cmd += ["--lockout"] if lockout else []
    for _ in range(LOCK_TRIES):
        print(f"accept: {' '.join(cmd[1:])}", flush=True)
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        out = p.stdout + p.stderr
        if LOCK_HELD in out and not evidence_of(out):
            print(f"accept: lock held; waiting {LOCK_WAIT} s", flush=True)
            time.sleep(LOCK_WAIT)
            continue
        folder = evidence_of(out)
        rep = None
        if folder and (ROOT / folder / "report.json").is_file():
            rep = json.loads((ROOT / folder / "report.json").read_text())
        tail = [ln for ln in out.splitlines() if re.match(r"ofm-live-proof: \S+: (pass|fail|FAILED|parked)", ln)
                or "PASS" in ln or "FAIL" in ln or "refused" in ln]
        print("\n".join(f"  {ln}" for ln in tail[-12:]), flush=True)
        return p.returncode, folder, rep
    return 1, None, None


def check(label: str, cmd: list[str], env=None) -> bool:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)
    last = ((p.stdout + p.stderr).strip().splitlines() or ["(no output)"])[-1]
    print(f"accept: {label}: exit {p.returncode}: {last}", flush=True)
    return p.returncode == 0


def load() -> str:
    return " ".join(f"{x:.2f}" for x in os.getloadavg())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="accept.py")
    ap.add_argument("--phase", type=int, required=True)
    ap.add_argument("--batch", type=int, default=4)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sweep-port", type=int, help="a running next dev: take a fresh dead.py --sweep-out there")
    g.add_argument("--sweep", type=Path, default=COMMITTED_SWEEP, help="an existing sweep file")
    a = ap.parse_args(argv)
    if a.batch < 1:
        ap.error("--batch must be at least 1")
    if a.sweep_port and not SWEEP_SECTIONS.get(a.phase):
        ap.error(f"--sweep-port: phase {a.phase} has no sweep sections")
    start = load()
    print(f"accept: phase {a.phase}, load average {start}", flush=True)
    folders, retried, failed = [], [], []
    for ids, lockout in batches(phase_proofs(a.phase), a.batch):
        code, folder, rep = run(ids, lockout)
        folders.append(folder or "(no evidence folder)")
        again = retry_ids(rep) if rep else None
        if code == 0 and again == []:
            continue
        if again is None:
            failed.append(f"batch {','.join(ids)}" + (f" ({folder})" if folder else ""))
            continue
        for pid in again:
            print(f"accept: retrying {pid} alone (Page.goto timeout / no Mirror frame)", flush=True)
            code, folder, _ = run([pid], lockout)
            folders.append(folder or "(no evidence folder)")
            (retried if code == 0 else failed).append(pid)

    phase_py = str(HERE / "proofs" / f"phase{a.phase}.py")
    if not check("check-records", [str(PY), "-I", phase_py, "--check-records", str(CAPTURES)]):
        failed.append("check-records")
    sweep = a.sweep
    if a.sweep_port:
        sections = SWEEP_SECTIONS[a.phase]
        sweep = Path(tempfile.mkstemp(prefix=f"oi-p{a.phase}-sweep-", suffix=".json")[1])
        env = {**os.environ, "PORT": str(a.sweep_port)}
        if not check(f"dead.py --sweep-out {sweep}", [str(PY), "-I", str(ROOT / "scripts" / "of-mirror-check" / "dead.py"),
                                                       "--sweep-out", str(sweep), *sections], env=env):
            failed.append("dead.py sweep")
    overlays = [x for f in COMMITTED_OVERLAYS for x in ("--overlay", str(f))] if sweep == COMMITTED_SWEEP else []
    if not check(f"check-sweep {sweep}" + "".join(f" + {Path(f).name}" for f in overlays[1::2]),
                 [str(PY), "-I", phase_py, "--check-sweep", str(sweep), str(CAPTURES), *overlays]):
        failed.append("check-sweep")

    for f in folders:
        print(f"accept: evidence {f}", flush=True)
    print(f"accept: load average start {start}, end {load()}", flush=True)
    if failed:
        print(f"accept phase {a.phase}: FAIL ({'; '.join(failed)})", flush=True)
        return 1
    print(f"accept phase {a.phase}: PASS ({len(retried)} retried" + (f": {', '.join(retried)})" if retried else ")"),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
