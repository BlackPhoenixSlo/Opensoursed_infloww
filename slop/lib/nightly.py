"""`slop/run nightly`: the daily full sweep, one digest (README "Nightly").

Phases, each scenario a plain `slop/run <name> <knobs>` subprocess (its own stack and evidence folder,
as `slop/run all` would run it): `all` (small, UI on), `volume` (every map entry tagged volume,
medium/200, no UI), `map` (`--map` for the unmapped; every scenario when map_rule fires). A FAIL in
`all`/`volume` is re-run once: green = FLAKY. The map phase hands its entries over in <folder>/map.json
and restores slop/map.json (`--apply-map=<folder>` merges them elsewhere). Evidence:
evidence/<stamp>-nightly-<hex>/ with plan.txt, run.log, status.json, summary.{json,md}, map.json, done
(the exit code, written last). Pure parts first (lib/test_nightly.py).

The machine gate (~/.slop/gate.py) owns admission: this parent never holds it (slop/run starts it as
`python -m slop.lib.nightly`, which the venv hook leaves alone); each child `slop/run` queues for it.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

from slop.lib import covmap
from slop.lib.report import EVIDENCE, parse_folder_line

SLOP = Path(__file__).resolve().parents[1]
RUN, APP = SLOP / "run", SLOP.parent / "app"
PHASES = ("all", "volume", "map")
KNOBS = {"all": [], "volume": ["--scale=medium", "--users=200", "--no-ui"], "map": ["--map"]}
SMOKE = {"all": ("2026-11-03-os-ping-push", "2026-10-23-inbox-unread-fan-burst"),
         "volume": ("2026-11-01-notifications-feed-volume",)}
MAP_FULL_BEHIND = 100  # newest map sha further behind HEAD than this: full `--map` refresh
P95_MOVE = 0.20  # a p95_vs_last_green key moved more than this vs the previous nightly: listed
COV_RED = "RED (coverage)"  # a --map run red only on budgets: coverage overhead, counted with OK
GREEN, RED = ("OK", "FLAKY", COV_RED), ("FAIL",)
FULL_TABLE_MAX = 10  # a phase with more rows lists only its non-OK ones (a green night stays short)
LOCK_SHA = ".slop-lock-sha"  # in app/node_modules: sha256 of the pnpm-lock.yaml it was installed from
INSTALL_TIMEOUT_S = 1200  # pnpm install past this (after its gate wait): killed, the night INFRA
GATE_PY = Path.home() / ".slop" / "gate.py"
GATE_ENV = ("SLOP_GATED", "SLOP_GATE_PID", "SLOP_GATE_WAIT_S", "SLOP_GATE_LOAD")
CHILD_LOCK_WAIT_S = "7200"  # a child queues this long for the gate before its INFRA (exit 75)
GATE_INFRA = 75  # gate.py: gave up (lock/load) or its thread guard tripped; an `INFRA: <reason>` line
INSTALL_DEADLINE_S = int(CHILD_LOCK_WAIT_S) + INSTALL_TIMEOUT_S  # the gated install: slot wait + the install
TERM_GRACE_S = 30  # a tree's SIGTERM -> SIGKILL


# ---- pure ----

def map_rule(ages: dict[str, int | None], weekday: int) -> tuple[bool, str]:
    """(full refresh?, why). `ages`: per map sha, commits it is behind HEAD, None when it is not an
    ancestor of HEAD (divergent or newer: its count says nothing, so it is stale); `weekday` 0 = Monday."""
    odd = sorted(sha[:7] for sha, n in ages.items() if n is None)
    known = [n for n in ages.values() if n is not None]
    behind = min(known) if known and not odd else None
    if behind is None:
        return True, ("map sha(s) not ancestors of HEAD: " + ", ".join(odd) if odd else "no map entry") + ": full refresh"
    if behind > MAP_FULL_BEHIND:
        return True, f"newest map sha {behind} commits behind HEAD (> {MAP_FULL_BEHIND}): full refresh"
    if weekday == 6:
        return True, "Sunday: weekly full refresh"
    return False, f"newest map sha {behind} commits behind HEAD (<= {MAP_FULL_BEHIND}), not Sunday: unmapped only"


def build_plan(names: list[str], doc: dict, phases: list[str], smoke: bool, ages: dict[str, int | None],
               weekday: int) -> tuple[dict[str, list[str]], str]:
    """({phase: scenarios}, map rule line), phases in PHASES order. `doc`: this worktree's map."""
    mapped = doc.get("scenarios", {})
    unmapped = [n for n in names if n not in mapped]
    full, why = map_rule(ages, weekday)
    if smoke:
        plan = {"all": [n for n in SMOKE["all"] if n in names],
                "volume": [n for n in SMOKE["volume"] if n in names], "map": unmapped}
        why = f"smoke: unmapped only (full rule: {why})"
    else:
        plan = {"all": list(names), "volume": [n for n in names if (mapped.get(n) or {}).get("volume")],
                "map": list(names) if full else unmapped}
    return {p: plan[p] for p in PHASES if p in phases}, why


def verdict(code: int, checks: list[dict] | None, meta: dict | None, *, map_run: bool = False,
            tail: str = "", gate_line: str = "") -> tuple[str, list[str], str | None]:
    """(verdict, failed check names, infra reason) from the child's exit code (slop/run: 0 pass, 1 a
    check failed, 2 usage/refused, 3 infra); invariants.json only names the failed checks. Exit 1 with no
    failed check in invariants.json = SKIP (every check skipped); without it, INFRA. A --map run red only on budgets = COV_RED (README: not the product's)."""
    failed = [c["name"] for c in checks or [] if c.get("status") == "fail"]
    if code == GATE_INFRA:  # the machine gate's: its own `INFRA: <reason>` line
        return "INFRA", failed, "machine gate: " + (gate_line.removeprefix("INFRA: ") or f"exit 75: {tail}")
    if code == 0:
        return "OK", [], None
    if code == 1:
        if not checks:
            return "INFRA", [], "slop/run exit 1 without invariants.json" + (f": {tail}" if tail else "")
        if not failed:
            return "SKIP", [], None
        if map_run and all(c.get("budget") for c in checks if c.get("status") == "fail"):
            return COV_RED, failed, None
        return "FAIL", failed, None
    if code == 3 and (meta or {}).get("infra"):
        return "INFRA", failed, str(meta["infra"])
    return "INFRA", failed, f"slop/run exit {code}" + (f": {tail}" if tail else "")


def settle(first: str, rerun: str | None) -> str:
    """A FAIL re-run once: green again = FLAKY, INFRA = INFRA (no verdict), else FAIL. Others stand."""
    if first != "FAIL" or rerun is None:
        return first
    return {"OK": "FLAKY", "INFRA": "INFRA"}.get(rerun, "FAIL")


def merge_rerun(first: dict, again: dict) -> dict:
    """The row of a FAIL and its re-run: the settled verdict, both folders (the re-run's None if it died
    before making one), the re-run's failed checks (else the first's), infra and p95, seconds summed."""
    return {**first, "verdict": settle(first["verdict"], again["verdict"]), "first_verdict": first["verdict"],
            "rerun_verdict": again["verdict"], "rerun_folder": again["folder"],
            "failed": again["failed"] or first["failed"], "infra": again["infra"],
            "p95": again["p95"] or first["p95"], "seconds": round(first["seconds"] + again["seconds"], 1)}


def exit_code(verdicts: list[str], infra: bool = False) -> int:
    """3 any INFRA (or a preflight failure: `infra`), 1 any stable FAIL, else 0 (OK, FLAKY, SKIP,
    RED (coverage)); as slop/run's own order."""
    return 3 if infra or "INFRA" in verdicts else 1 if "FAIL" in verdicts else 0


def headline(stamp: str, verdicts: list[str], infra: bool = False) -> str:
    """`ok/flaky/fail/infra/skip of n`, adding up to n (RED (coverage) counts as ok)."""
    code = exit_code(verdicts, infra)
    n = {v: verdicts.count(v) for v in ("OK", "FLAKY", "FAIL", "INFRA", "SKIP", COV_RED)}
    return (f"NIGHTLY {'INFRA' if code == 3 else 'RED' if code == 1 else 'OK'} {stamp}: "
            f"{n['OK'] + n[COV_RED]}/{n['FLAKY']}/{n['FAIL']}/{n['INFRA']}/{n['SKIP']} of {len(verdicts)}")


def child_env(env: dict) -> dict:
    """A child's env: outside any gate (its slop/run queues for the machine itself), long lock wait."""
    return {**{k: v for k, v in env.items() if k not in GATE_ENV}, "SLOP_LOCK_WAIT_S": CHILD_LOCK_WAIT_S}


def scrub_gate_env(env) -> bool:
    """Drop inherited SLOP_GATE* from the driver's own env (a stale or reused pid says nothing reliable;
    the driver never holds the gate either way). -> whether any was there."""
    had = [k for k in GATE_ENV if k in env]
    for k in had:
        del env[k]
    return bool(had)


def child_argv(args, out: Path) -> list[str]:
    """The detached driver's argv, rebuilt from the parsed options (never the raw argv: no --detach)."""
    return [f"--phases={args.phases}", *(["--smoke"] if args.smoke else []), f"--folder={out}"]


def tree_order(root: int, kids: dict[int, list[int]]) -> list[int]:
    """`root` and its descendants from a {ppid: [pid]} snapshot, children before parents, root last."""
    out, seen = [], set()

    def walk(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        for c in kids.get(pid, []):
            walk(c)
        out.append(pid)
    walk(root)
    return out


def merge_map(cur: dict, got: dict, names: list[str]) -> tuple[dict, list[str], list[str], list[str]]:
    """`cur` with `got`'s entries for `names` put in (keyed by scenario; the others untouched).
    -> (doc, replaced, added, missing from got)."""
    sc, new = dict(cur.get("scenarios", {})), got.get("scenarios", {})
    replaced = [n for n in names if n in new and n in sc]
    added = [n for n in names if n in new and n not in sc]
    for n in replaced + added:
        sc[n] = new[n]
    return {**cur, "scenarios": sc}, replaced, added, [n for n in names if n not in new]


def changes(rows: list[dict], prev: list[dict] | None) -> dict:
    """vs the previous nightly's rows: newly red (now FAIL, before not), newly green (now OK/FLAKY,
    before FAIL), p95_vs_last_green keys that moved > P95_MOVE."""
    if prev is None:
        return {"newly_red": [], "newly_green": [], "p95": [], "first": True}
    before = {(r["phase"], r["scenario"]): r for r in prev}
    red, green, p95 = [], [], []
    for r in rows:
        k, b = (r["phase"], r["scenario"]), before.get((r["phase"], r["scenario"]))
        if r["verdict"] in RED and (b is None or b["verdict"] not in RED):
            red.append(f"{k[0]} {k[1]}")
        if r["verdict"] in GREEN and b is not None and b["verdict"] in RED:
            green.append(f"{k[0]} {k[1]}")
        for key, now in (r.get("p95") or {}).items():
            last = ((b or {}).get("p95") or {}).get(key)
            if now is not None and last and abs(now - last) / last > P95_MOVE:
                p95.append(f"{k[0]} {k[1]} {key}: {last} -> {now} ms ({(now - last) / last:+.0%})")
    return {"newly_red": red, "newly_green": green, "p95": p95, "first": False}


def _cell(r: dict) -> str:
    bits = []
    if r.get("failed"):
        f = r["failed"]
        bits.append("; ".join(x[:90] for x in f[:3]) + (f" (+{len(f) - 3} more)" if len(f) > 3 else ""))
    if r.get("infra"):
        bits.append(f"infra: {r['infra'][:200]}")
    return " · ".join(bits).replace("|", "/")


def _folders(r: dict) -> str:
    if "rerun_verdict" in r:
        return f"{r['folder'] or '-'} -> re-run {r['rerun_folder'] or '-'}"
    return r["folder"] or "-"


def digest(s: dict) -> str:
    """summary.md from summary.json's dict."""
    v = [r["verdict"] for r in s["rows"]]
    out = [s["headline"],
           f"sha {s['sha']}{' (smoke)' if s['smoke'] else ''} · {s['started']} -> {s['ended']} · "
           f"load {s['load_start']:.1f} -> {s['load_end']:.1f} ({s['cores']} cores)",
           "walls: " + " · ".join(f"{p} {w['wall_s']:.0f}s" for p, w in s["phases"].items()),
           f"exit {exit_code(v, bool(s.get('infra')))} (0 OK/FLAKY, 1 FAIL, 3 INFRA); counts ok/flaky/fail/infra/skip"]
    if s.get("deps"):
        out.append(f"app deps: {s['deps']}")
    waits = [(r["gate_wait_s"], r["scenario"]) for r in s["rows"] if r.get("gate_wait_s")]
    if waits:
        out.append(f"gate wait: {sum(w for w, _ in waits):.0f}s total, max {max(waits)[0]:.0f}s ({max(waits)[1]})")
    for p in s["phases"]:
        rows = [r for r in s["rows"] if r["phase"] == p]
        ok = [r for r in rows if r["verdict"] == "OK"]
        show = rows if len(rows) <= FULL_TABLE_MAX else [r for r in rows if r["verdict"] != "OK"]
        out += ["", f"## {p} `{' '.join(KNOBS[p]) or 'small, UI on'}`: {len(ok)} OK of {len(rows)}"]
        if show:
            out += ["| scenario | verdict | s | folder | failed / infra |", "|---|---|---|---|---|"]
            out += [f"| {r['scenario']} | {r['verdict']} | {r['seconds']:.0f} | {_folders(r)} | {_cell(r)} |"
                    for r in show]
        if len(show) < len(rows):
            out.append(f"{len(ok)} OK rows not listed (folders: summary.json `rows`)")
    c = s["changes"]
    out += ["", f"## changes vs previous nightly {s.get('prev') or '(none)'}"]
    if not c["first"]:
        out += [f"- newly red: {', '.join(c['newly_red']) or 'none'}",
                f"- newly green: {', '.join(c['newly_green']) or 'none'}",
                f"- p95 moved > {P95_MOVE:.0%}:" + ("" if c["p95"] else " none")]
        out += [f"  - {x}" for x in c["p95"][:15]] + ([f"  - (+{len(c['p95']) - 15} more)"] if len(c["p95"]) > 15 else [])
    if s.get("map"):
        m = s["map"]
        out += ["", "## map", f"- rule: {m['rule']}",
                f"- entries refreshed: {len(m['mapped'])} -> map.json here; slop/map.json {m['restored']}; "
                "ship: `slop/run nightly --apply-map=<this folder>` on a branch from origin/main",
                f"- unmapped left: {', '.join(m['unmapped_left']) or 'none'}"]
    return "\n".join(out) + "\n"


# ---- I/O ----

def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def row_of(phase: str, name: str, folder: Path | None, seconds: float, code: int, tail: str = "",
           gate_line: str = "") -> dict:
    meta = checks = None
    if folder:
        try:
            meta = json.loads((folder / "metrics.json").read_text())
            checks = json.loads((folder / "invariants.json").read_text())
        except (OSError, ValueError):
            pass
    v, failed, infra = verdict(code, checks, meta, map_run=phase == "map", tail=tail, gate_line=gate_line)
    return {"phase": phase, "scenario": name, "verdict": v, "seconds": round(seconds, 1),
            "folder": folder.name if folder else None, "failed": failed, "infra": infra,
            "p95": (meta or {}).get("p95_vs_last_green") or {}, "exit": code,
            "gate_wait_s": ((meta or {}).get("params") or {}).get("lock_wait_s")}


def app_deps_stale() -> str | None:
    """Why app/node_modules is not this worktree's own install of app/pnpm-lock.yaml, or None."""
    nm = APP / "node_modules"
    if nm.is_symlink():
        return "app/node_modules is a symlink (APP_MODE=prod's Turbopack build refuses it)"
    if not nm.is_dir():
        return "app/node_modules missing"
    want = hashlib.sha256((APP / "pnpm-lock.yaml").read_bytes()).hexdigest()
    have = (nm / LOCK_SHA).read_text().strip() if (nm / LOCK_SHA).exists() else None
    if have != want:
        return f"app/pnpm-lock.yaml sha256 {want[:12]} != installed {(have or 'none')[:12]}"
    return None


class Night:
    def __init__(self, out: Path, tee: bool):
        self.out, self.log, self.proc = out, open(out / "run.log", "a") if tee else None, None
        lstart = subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True)
        # pid_lstart: a poller's `ps -o lstart= -p <pid>` must print this, else the pid is dead or reused (reboot)
        self.status = {"pid": os.getpid(), "pid_lstart": lstart.stdout.strip(), "phase": None, "scenario": None, "done": 0, "total": 0,
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "updated": None}

    def say(self, *lines: str) -> None:
        for ln in lines:
            print(ln, flush=True)
            if self.log:
                self.log.write(ln + "\n")
                self.log.flush()

    def mark(self, **kw) -> None:
        self.status.update(kw, updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        write_atomic(self.out / "status.json", json.dumps(self.status, indent=1) + "\n")

    def stream(self, cmd: list[str], cwd: Path, env: dict | None = None,
               timeout: float | None = None) -> tuple[int, Path | None, str, bool]:
        """Run `cmd` as self.proc (stop_child reaches it), its output into run.log as it comes.
        -> (exit code, report.FOLDER_LINE's folder, last lines, killed by `timeout`)."""
        folder, last, self.gate_line = None, deque(maxlen=4), ""
        self.proc = p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
        fired = threading.Event()  # past `timeout`: its whole tree (grandchildren hold the pipe too)
        timer = threading.Timer(timeout, lambda: (fired.set(), kill_tree(p))) if timeout else None
        if timer:
            timer.start()
        try:
            for line in p.stdout:
                line = line.rstrip("\n")
                self.say(line)
                folder = parse_folder_line(line) or folder
                if line.startswith("INFRA: "):
                    self.gate_line = line.strip()
                if line.strip():
                    last.append(line.strip())
            code = p.wait()
        finally:
            if timer:
                timer.cancel()
        self.proc = None
        return code, folder, " | ".join(last)[:400], fired.is_set()

    def run(self, phase: str, name: str) -> dict:
        """One `slop/run <name> <knobs>`; its folder from report.FOLDER_LINE."""
        t0 = time.time()
        code, folder, tail, _ = self.stream([str(RUN), name, *KNOBS[phase]], SLOP.parent, env=child_env(os.environ))
        r = row_of(phase, name, folder, time.time() - t0, code, tail, self.gate_line)
        self.say(f"slop: nightly {phase} {r['verdict']} {name} ({r['seconds']:.0f}s) {r['folder']}")
        return r

    def stop_child(self) -> None:
        """SIGINT a running `slop/run` (gate.py run forwards it; KeyboardInterrupt: its stack tears down),
        past 60 s its whole tree (kill_tree)."""
        p = self.proc
        if p is None or p.poll() is not None:
            return
        p.send_signal(signal.SIGINT)
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            kill_tree(p)

    def install_app_deps(self, why: str) -> str | None:
        """pnpm install from this worktree's lockfile, in a gate slot like any heavy child; -> error or None."""
        nm = APP / "node_modules"
        self.say(f"slop: nightly app deps: {why}: gate.py run -- pnpm install --frozen-lockfile in app/")
        if nm.is_symlink():
            nm.unlink()
        code, _, tail, killed = self.stream(["python3", str(GATE_PY), "run", "--", "pnpm", "install", "--frozen-lockfile"],
                                            APP, env={**child_env(os.environ), "CI": "true"}, timeout=INSTALL_DEADLINE_S)
        if code == GATE_INFRA:
            return f"pnpm install preflight: machine gate: {self.gate_line.removeprefix('INFRA: ') or tail[:200]}"
        if killed:
            return (f"pnpm install --frozen-lockfile in app/ timed out after {INSTALL_DEADLINE_S}s "
                    f"(gate wait {CHILD_LOCK_WAIT_S}s + install {INSTALL_TIMEOUT_S}s); see run.log")
        if code:
            return f"pnpm install --frozen-lockfile in app/ failed (exit {code}): {tail[:200]}"
        (nm / LOCK_SHA).write_text(hashlib.sha256((APP / "pnpm-lock.yaml").read_bytes()).hexdigest() + "\n")
        return None


def kill_tree(p: subprocess.Popen) -> None:
    """SIGTERM then (TERM_GRACE_S on) SIGKILL `p` and every descendant, children first, then reap `p`.
    By ppid, not process group: gate.py run starts its workload in a session of its own, which must not
    outlive the wrapper (slot released, workload ungated, its stdout holding stream() open)."""
    def snapshot() -> dict[int, list[int]]:
        kids: dict[int, list[int]] = {}
        for ln in subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout.splitlines():
            pid, ppid = map(int, ln.split())
            kids.setdefault(ppid, []).append(pid)
        return kids
    pids = tree_order(p.pid, snapshot())
    for sig, grace in ((signal.SIGTERM, TERM_GRACE_S), (signal.SIGKILL, 5)):
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)
        end = time.time() + grace
        while time.time() < end and (p.poll() is None or any(_alive(x) for x in pids if x != p.pid)):
            time.sleep(0.2)
        if p.poll() is not None and not any(_alive(x) for x in pids if x != p.pid):
            break
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(5)


def _map_ages(doc: dict) -> dict[str, int | None]:
    """Per map sha: commits behind HEAD, None when not an ancestor of HEAD (or unknown here)."""
    ages = {}
    for sha in {e.get("sha") for e in doc.get("scenarios", {}).values() if e.get("sha")}:
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=SLOP.parent, capture_output=True)
        ages[sha] = int(covmap.git("rev-list", "--count", f"{sha}..HEAD").strip()) if anc.returncode == 0 else None
    return ages


def gate_status() -> str:
    """`python3 ~/.slop/gate.py status` now (who holds the machine, who queues, load)."""
    try:
        r = subprocess.run(["python3", str(GATE_PY), "status"], capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).rstrip() or f"(exit {r.returncode}, no output)"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(gate status failed: {type(e).__name__}: {e})"


def _plan_text(stamp: str, sha: str, smoke: bool, plan: dict, why: str) -> str:
    lines = [f"nightly plan {stamp} @ {sha}{' (smoke)' if smoke else ''}: "
             f"{sum(map(len, plan.values()))} runs, each `slop/run <scenario> <knobs>`; a FAIL in all/volume re-runs once"]
    for p, names in plan.items():
        how = {"all": "every scenario (as slop/run all)", "volume": "map entries tagged volume",
               "map": why}[p] if not smoke else ("smoke set" if p != "map" else why)
        lines += [f"{p} `{' '.join(KNOBS[p]) or 'small, UI on'}` ({len(names)}): {how}"]
        lines += [f"  {n}" for n in names]
    return "\n".join(lines) + "\n"


def _prev(out: Path, smoke: bool, phases: list[str]) -> tuple[str | None, list | None]:
    """The newest earlier finished nightly (`done`; folder name sorts before this one's) of the same
    phases and smoke."""
    for d in sorted(EVIDENCE.glob("*-nightly-*"), reverse=True):
        if d.name >= out.name or not (d / "done").exists():
            continue
        try:
            s = json.loads((d / "summary.json").read_text())
        except (OSError, ValueError):
            continue
        if s.get("rows") is not None and bool(s.get("smoke")) == smoke and s.get("phase_names") == phases:
            return d.name, s["rows"]
    return None, None


def _map_phase(night: Night, names: list[str], why: str, all_names: list[str]) -> tuple[list[dict], dict]:
    """`--map` per scenario; finally its slop/map.json goes to <out>/map.json and the worktree's is
    restored (when it was clean before), so the worktree stays clean and the next pull never conflicts."""
    was_dirty = covmap.git("status", "--porcelain", "--", "slop/map.json").strip()
    before, rows = covmap.load_map()["scenarios"], []
    try:
        for name in names:
            night.mark(phase="map", scenario=name)
            rows.append(night.run("map", name))
            night.mark(done=night.status["done"] + 1)
    finally:
        night.stop_child()  # a killed night: its --map child must not write the map after the restore
        after = covmap.load_map()["scenarios"]
        if covmap.MAP.exists():
            shutil.copyfile(covmap.MAP, night.out / "map.json")
        if was_dirty:
            restored = "left as it was (it had local edits before this run)"
        else:
            covmap.git("checkout", "--", "slop/map.json")
            restored = "restored (git checkout)"
        night.say(f"slop: nightly map: entries -> {night.out / 'map.json'}; slop/map.json {restored}")
    return rows, {"rule": why, "mapped": sorted(n for n in names if after.get(n) != before.get(n)),
                  "unmapped_left": sorted(n for n in all_names if n not in after), "restored": restored}


def sweep(night: Night, args, plan: dict, why: str, stamp: str, sha: str) -> int:
    if shutil.which("caffeinate"):  # macOS: no idle sleep while this process lives
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    night.say(f"slop: nightly {stamp} @ {sha} -> {night.out}", (night.out / "plan.txt").read_text().rstrip())
    cores = os.cpu_count() or 1
    s = {"stamp": stamp, "sha": sha, "smoke": args.smoke, "phase_names": list(plan), "cores": cores,
         "load_start": os.getloadavg()[0], "started": time.strftime("%Y-%m-%d %H:%M %Z"), "phases": {}, "rows": []}
    night.mark(phase="app deps", total=sum(map(len, plan.values())))
    stale = app_deps_stale()
    deps_err = night.install_app_deps(stale) if stale else None
    s["deps"] = deps_err or (f"installed ({stale})" if stale else "up to date")
    for phase, names in plan.items():
        t0 = time.time()
        if deps_err:
            rows = [{**row_of(phase, n, None, 0, 3), "infra": deps_err} for n in names]
        elif phase == "map":
            rows, s["map"] = _map_phase(night, names, why, args.names)
        else:
            rows = []
            for name in names:
                night.mark(phase=phase, scenario=name)
                rows.append(night.run(phase, name))
                night.mark(done=night.status["done"] + 1)
            for i, r in enumerate(rows):
                if r["verdict"] == "FAIL":
                    night.mark(phase=f"{phase} rerun", scenario=r["scenario"])
                    rows[i] = merge_rerun(r, night.run(phase, r["scenario"]))
        s["rows"] += rows
        s["phases"][phase] = {"wall_s": round(time.time() - t0, 1), "n": len(rows)}
    s["prev"], prev_rows = _prev(night.out, args.smoke, list(plan))
    s["changes"] = changes(s["rows"], prev_rows)
    s.update(load_end=os.getloadavg()[0], ended=time.strftime("%Y-%m-%d %H:%M %Z"))
    s["infra"] = deps_err
    s["headline"] = headline(stamp, [r["verdict"] for r in s["rows"]], bool(deps_err))
    s["exit"] = exit_code([r["verdict"] for r in s["rows"]], bool(deps_err))
    write_atomic(night.out / "summary.json", json.dumps(s, indent=1) + "\n")
    md = digest(s)
    write_atomic(night.out / "summary.md", md)
    night.say("", md.rstrip(), "", s["headline"])
    return s["exit"]


def apply_map(arg: str) -> int:
    """--apply-map=<nightly folder>: its map.json entries for summary.json's map.mapped into slop/map.json."""
    d = Path(arg) if Path(arg).is_dir() else EVIDENCE / arg
    try:
        names = json.loads((d / "summary.json").read_text())["map"]["mapped"]
        got = json.loads((d / "map.json").read_text())
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"slop: --apply-map: {d}: no map phase result ({type(e).__name__}: {e})")
        return 2
    doc, replaced, added, missing = merge_map(covmap.load_map(), got, names)
    write_atomic(covmap.MAP, covmap.dump(doc))
    print(f"slop: --apply-map {d.name} -> {covmap.MAP.relative_to(SLOP.parent)}: replaced {len(replaced)}, "
          f"added {len(added)}" + "".join(f"\n  replaced {n}" for n in replaced) + "".join(f"\n  added {n}" for n in added)
          + (f"\nslop: WARN not in its map.json: {', '.join(missing)}" if missing else ""))
    return 0


def main(argv: list[str], all_s: dict[str, Path]) -> int:
    ap = argparse.ArgumentParser(prog="slop/run nightly", allow_abbrev=False)  # --det must not mean --detach
    ap.add_argument("--dry", action="store_true", help="print the plan, run nothing, write nothing")
    ap.add_argument("--phases", default=",".join(PHASES), help="comma list of all,volume,map")
    ap.add_argument("--smoke", action="store_true", help="2 UI scenarios, 1 volume, the unmapped: the mechanics")
    ap.add_argument("--detach", action="store_true", help="run in the background; print the folder, return")
    ap.add_argument("--apply-map", metavar="FOLDER", help="merge that nightly's map entries into slop/map.json")
    ap.add_argument("--folder", help=argparse.SUPPRESS)  # the detached child's: the parent made it
    args = ap.parse_args(argv)
    if scrub_gate_env(os.environ):  # children get a clean env anyway; the driver itself never holds the gate
        print("slop: nightly: ignoring inherited SLOP_GATED")
    os.setpriority(os.PRIO_PROCESS, 0, max(10, os.getpriority(os.PRIO_PROCESS, 0)))  # nice 10, as gate holders
    if args.apply_map:
        return apply_map(args.apply_map)
    phases = [p for p in args.phases.split(",") if p]
    if not phases or set(phases) - set(PHASES):
        ap.error(f"--phases: comma list of {','.join(PHASES)}")
    args.names = list(all_s)
    if args.dry:
        plan, why, sha = _plan(args, phases)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        print(_plan_text(stamp, sha, args.smoke, plan, why) + f"gate now:\n{gate_status()}\n"
              f"app deps: {app_deps_stale() or 'up to date'}"
              f"{' (would pnpm install)' if app_deps_stale() else ''}\nslop: nightly --dry: nothing run, nothing written")
        return 0
    if args.folder:
        out = Path(args.folder)
    else:
        out = EVIDENCE / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-nightly-{secrets.token_hex(2)}"
        out.mkdir(parents=True)
    stamp = out.name.split("-nightly-")[0]
    if args.detach:  # the child does everything else, under its own `done` guard
        child = [str(SLOP.parent / "venv" / "bin" / "python"), "-u", "-m", "slop.lib.nightly",  # not cli.py: the
                 *child_argv(args, out)]  # venv hook would gate it
        with open(out / "run.log", "a") as log:
            p = subprocess.Popen(child, cwd=SLOP.parent, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)  # setsid: no SIGHUP from the caller's shell
        print(f"slop: nightly detached (pid {p.pid}) -> {out}\n"
              f"slop: progress {out}/status.json; done when {out}/done exists (holds the exit code)")
        return 0
    code, night, why_infra = 3, None, None

    def term(*_):
        raise SystemExit(3)
    signal.signal(signal.SIGTERM, term)  # `finally` runs: the child stopped, `done` written
    try:
        try:
            night = Night(out, tee=not args.folder)
            night.mark(phase="plan")
            plan, why, sha = _plan(args, phases)
            write_atomic(out / "plan.txt", _plan_text(stamp, sha, args.smoke, plan, why)
                         + f"\ngate at start (`python3 ~/.slop/gate.py status`):\n{gate_status()}\n")
            code = sweep(night, args, plan, why, stamp, sha)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 3
            why_infra = f"stopped (SIGTERM or exit {code})" + (
                f" during {night.status['phase']} {night.status['scenario'] or ''}" if night else "")
        except BaseException as e:
            code, why_infra = 3, f"crashed: {type(e).__name__}: {e}"
            msg = traceback.format_exc()
            night.say(msg) if night else print(msg, file=sys.stderr)
        finally:
            try:
                if night:
                    if why_infra:
                        night.say(f"slop: nightly {why_infra}: exit {code}")
                    night.stop_child()
                    night.mark(phase="done", scenario=None)
            except BaseException:
                code = 3
                traceback.print_exc()
    finally:
        try:
            if why_infra and not (out / "summary.md").exists():
                write_atomic(out / "summary.md", f"NIGHTLY INFRA {stamp}: {why_infra} (see run.log)\n")
        finally:
            write_atomic(out / "done", f"{code}\n")
    return code


def _plan(args, phases: list[str]) -> tuple[dict, str, str]:
    doc = covmap.load_map()  # this worktree's map: unmapped = what it lacks now
    plan, why = build_plan(args.names, doc, phases, args.smoke, _map_ages(doc), time.localtime().tm_wday)
    return plan, why, covmap.git("rev-parse", "--short", "HEAD").strip()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


if __name__ == "__main__":  # slop/run nightly and --detach: `venv/bin/python -m slop.lib.nightly` from the root
    from slop.lib.cli import scenarios
    sys.exit(main(sys.argv[1:], scenarios()))
