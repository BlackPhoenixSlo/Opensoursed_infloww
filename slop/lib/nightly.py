from __future__ import annotations

import argparse
import datetime
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

from slop.lib import covmap, gate, phases, procs, selection
from slop.lib.identity import GATE_ENV, LOCK_SHA
from slop.lib.latency_acceptance import volume_knobs
from slop.lib.procs import kill_tree, stop_child
from slop.lib.report import EVIDENCE, parse_folder_line, write_atomic

SLOP = Path(__file__).resolve().parents[1]
RUN, APP = SLOP / "run", SLOP.parent / "app"
PHASES = ("volume", "all", "map")  # volume first: exclusive runs queue least before the day's sessions
VOLUME_PER_NIGHT = 3
PREV_LOOKBACK = 40  # 57 volume scenarios / 3 per night = 19 nights
KNOBS = {"all": [], "volume": ["--scale=medium", "--users=120", "--no-ui"], "map": ["--map"]}
SMOKE = {"all": ("2026-11-03-os-ping-push", "2026-10-23-inbox-unread-fan-burst"),
         "volume": ("2026-11-01-notifications-feed-volume",)}
MAP_PER_NIGHT = 10  # the laptop is never free overnight; the map refreshes over nights
P95_MOVE = 0.20
COV_RED = "RED (coverage)"
GREEN, RED = ("OK", "FLAKY", COV_RED), ("FAIL",)
FULL_TABLE_MAX = 10
INSTALL_TIMEOUT_S = 1200
GATE_PY = gate.GATE
CHILD_LOCK_WAIT_S = "7200"
GATE_INFRA = 75
INSTALL_DEADLINE_S = int(CHILD_LOCK_WAIT_S) + INSTALL_TIMEOUT_S
WALL_S = 8 * 3600  # the night ends within 8 h; the running child is stopped
LAST_START_S = 30 * 60  # the longest scenario takes ~27 min
CUT_NOT_RUN, CUT_STOPPED, CUT_NO_RERUN = "not run: 8 h limit", "stopped at the 8 h limit", "no re-run: 8 h limit"



def map_rule(ages: dict[str, int | None], picked: int, due: int) -> str:
    _stale, reason = covmap.map_stale(ages)
    left = f"; {due - picked} wait for later nights" if due > picked else ""
    return f"{reason}: {picked} of {due} unmapped + stale entries (cap {MAP_PER_NIGHT}, most behind first){left}"


def stale_entry(entry: dict, ages: dict[str, int | None]) -> bool:
    n = ages.get(entry.get("sha") or "")
    return n is None or n > covmap.MAP_STALE


def map_pick(names: list[str], mapped: dict, ages: dict[str, int | None],
             k: int = MAP_PER_NIGHT, tried: dict[str, int] | None = None) -> tuple[list[str], int]:
    due = [n for n in names if n not in mapped or stale_entry(mapped[n], ages)]
    tried = tried or {}

    def key(n: str):
        t = (0, 0) if n not in tried else (1, -tried[n])
        if n not in mapped:
            return (*t, 0, 0, n)
        a = ages.get(mapped[n].get("sha") or "")
        return (*t, 1, 0, n) if a is None else (*t, 2, -a, n)
    return sorted(due, key=key)[:k], len(due)


ALL_SOURCES = ("changed", "carry-over", "unmapped", "canary")
NIGHTLY_TIERS = ("own", "flow")


def plan_notes(line: str, why: dict | None = None, left_out: int = 0, wide: int | None = None,
               volume_carry: list[str] | None = None) -> dict:
    return {"line": line, "why": why or {}, "left_out": left_out, "wide": wide, "volume_carry": volume_carry or []}


def all_plan(names: list[str], mapped: dict, prev: dict | None, picked: dict | None,
             fallback: str | None) -> tuple[list[str], dict]:
    if fallback or prev is None or picked is None:
        why = fallback or ("no previous nightly" if prev is None else "no pick")
        return list(names), plan_notes(f"every scenario (fallback: {why})")
    have, why = set(names), {}

    def add(n: str, src: str) -> None:
        if n in have and src not in why.setdefault(n, []):
            why[n].append(src)
    for n in SMOKE["all"]:
        add(n, "canary")
    for r in prev.get("rows") or []:
        if r.get("phase") == "all" and r.get("verdict") != "OK":
            add(r["scenario"], f"carry-over ({r['phase']} {r['verdict']}" + (f": {r['cut']}" if r.get("cut") else "") + ")")
    for n, rs in picked.items():
        if selection.tier(rs) in NIGHTLY_TIERS:
            add(n, f"changed ({selection.tier(rs)}: {rs[0][1][:120]})")
    for n in names:
        if n not in mapped:
            add(n, "unmapped")
    why = {n: v for n, v in why.items() if v}
    run = [n for n in names if n in why]
    n_src = {k: sum(any(s.startswith(k) for s in why[n]) for n in run) for k in ALL_SOURCES}
    wide = sum(n in have and n not in why for n, rs in picked.items() if selection.tier(rs) not in NIGHTLY_TIERS)
    line = (f"relevant only since nightly {prev['name']} @ {prev['sha']}: {len(run)} of {len(names)} ("
            + ", ".join(f"{k} {v}" for k, v in n_src.items()) + f"); {len(names) - len(run)} left out as unaffected"
            + f" ({wide} of them shared/layout picks only)")
    return run, plan_notes(line, {n: why[n] for n in run}, len(names) - len(run), wide)


def volume_slice(names: list[str], day: int, k: int = VOLUME_PER_NIGHT) -> list[str]:
    names = sorted(names)
    if len(names) <= k:
        return names
    start = (day * k) % len(names)
    return [names[(start + i) % len(names)] for i in range(k)]


def volume_carry(prev: dict | None, volume: list[str]) -> list[str]:
    have = set(volume)
    return sorted({r["scenario"] for r in (prev or {}).get("rows") or []
                   if r.get("phase") == "volume" and r.get("verdict") != "OK" and r.get("scenario") in have})


def build_plan(paths: dict[str, Path], doc: dict, phases: list[str], smoke: bool, ages: dict[str, int | None],
               day: int = 0, *, prev: dict | None = None, picked: dict | None = None,
               fallback: str | None = None, tried: dict[str, int] | None = None,
               vol_prev: dict | None = None) -> tuple[dict[str, list[str]], str, dict]:
    names = list(paths)
    mapped = doc.get("scenarios", {})
    unmapped = [n for n in names if n not in mapped]
    to_map, due = map_pick(names, mapped, ages, tried=tried)
    why = map_rule(ages, len(to_map), due)
    if smoke:
        plan = {"all": [n for n in SMOKE["all"] if n in names],
                "volume": [n for n in SMOKE["volume"] if n in names], "map": unmapped}
        why = f"smoke: unmapped only (rule: {why})"
        notes = plan_notes("smoke set")
    else:
        run, notes = all_plan(names, mapped, prev, picked, fallback)
        vol = [n for n in names if covmap.is_volume(paths[n])]
        today = volume_slice(vol, day)
        carry = [n for n in volume_carry(vol_prev, vol) if n not in today]
        notes = {**notes, "volume_carry": carry}
        plan = {"all": run, "volume": today + carry, "map": to_map}
    return {p: plan[p] for p in PHASES if p in phases}, why, notes


def verdict(code: int, checks: list[dict] | None, meta: dict | None, *, map_run: bool = False,
            tail: str = "", gate_line: str = "") -> tuple[str, list[str], str | None]:
    failed = [c["name"] for c in checks or [] if c.get("status") == "fail"]
    if code == GATE_INFRA:
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
    if first != "FAIL" or rerun is None:
        return first
    return {"OK": "FLAKY", "INFRA": "INFRA"}.get(rerun, "FAIL")


def merge_rerun(first: dict, again: dict) -> dict:
    return {**first, "verdict": settle(first["verdict"], again["verdict"]), "first_verdict": first["verdict"],
            "rerun_verdict": again["verdict"], "rerun_folder": again["folder"],
            "failed": again["failed"] or first["failed"], "infra": again["infra"],
            "p95": again["p95"] or first["p95"], "seconds": round(first["seconds"] + again["seconds"], 1),
            "gate_wait_s": phases.add(first.get("gate_wait_s"), again.get("gate_wait_s")),
            "run_phases": phases.merge(first.get("run_phases"), again.get("run_phases")),
            "untimed": first["untimed"] + again["untimed"]}


def cut_row(phase: str, name: str, why: str = CUT_NOT_RUN) -> dict:
    return {**row_of(phase, name, None, 0, 0), "verdict": "SKIP", "untimed": [], "cut": why}


def all_skipped(verdicts: list[str]) -> bool:
    return all(v == "SKIP" for v in verdicts)


def exit_code(verdicts: list[str], infra: bool = False) -> int:
    return 3 if infra or "INFRA" in verdicts or all_skipped(verdicts) else 1 if "FAIL" in verdicts else 0


def headline(stamp: str, verdicts: list[str], infra: bool = False) -> str:
    code = exit_code(verdicts, infra)
    n = {v: verdicts.count(v) for v in ("OK", "FLAKY", "FAIL", "INFRA", "SKIP", COV_RED)}
    word = ("INFRA" if infra or "INFRA" in verdicts else "SKIPPED" if all_skipped(verdicts)
            else "RED" if code == 1 else "OK")
    return (f"NIGHTLY {word} {stamp}: "
            f"{n['OK'] + n[COV_RED]}/{n['FLAKY']}/{n['FAIL']}/{n['INFRA']}/{n['SKIP']} of {len(verdicts)}"
            + ("" if verdicts else " (no work: nothing planned ran)"))


def _gate_var(k: str) -> bool:
    return k.startswith("SLOP_GATE")


def child_env(env: dict) -> dict:
    return {**{k: v for k, v in env.items() if not _gate_var(k)}, "SLOP_LOCK_WAIT_S": CHILD_LOCK_WAIT_S,
            "SLOP_NIGHTLY": "1"}


def scrub_gate_env(env) -> bool:
    had = [k for k in env if _gate_var(k)]
    for k in had:
        del env[k]
    return bool(had)


def child_argv(args, out: Path) -> list[str]:
    return [f"--phases={args.phases}", *(["--smoke"] if args.smoke else []), f"--folder={out}"]


def merge_map(cur: dict, got: dict, names: list[str]) -> tuple[dict, list[str], list[str], list[str]]:
    sc, new = dict(cur.get("scenarios", {})), got.get("scenarios", {})
    replaced = [n for n in names if n in new and n in sc]
    added = [n for n in names if n in new and n not in sc]
    for n in replaced + added:
        sc[n] = new[n]
    return {**cur, "scenarios": sc}, replaced, added, [n for n in names if n not in new]


def effective_knobs(phase, name):
    return volume_knobs(name, KNOBS[phase]) if phase == 'volume' else list(KNOBS[phase])


def recorded_knobs(row):
    return row.get('knobs', KNOBS[row['phase']])


def changes(rows: list[dict], prev: list[dict] | None) -> dict:
    if prev is None:
        return {"newly_red": [], "newly_infra": [], "newly_green": [], "p95": [], "load_changed": [], "first": True}
    before = {(r["phase"], r["scenario"]): r for r in prev}
    red, infra, green, p95, load_changed = [], [], [], [], []
    for r in rows:
        k, b = (r["phase"], r["scenario"]), before.get((r["phase"], r["scenario"]))
        if b is not None and recorded_knobs(r) != recorded_knobs(b):
            load_changed.append(f"{k[0]} {k[1]}: {' '.join(recorded_knobs(b))} -> {' '.join(recorded_knobs(r))}; not comparable")
            continue
        if r["verdict"] in RED and (b is None or b["verdict"] not in RED):
            red.append(f"{k[0]} {k[1]}")
        if r["verdict"] == "INFRA" and (b is None or b["verdict"] != "INFRA"):
            infra.append(f"{k[0]} {k[1]}")
        if r["verdict"] in GREEN and b is not None and b["verdict"] in RED:
            green.append(f"{k[0]} {k[1]}")
        for key, now in (r.get("p95") or {}).items():
            last = ((b or {}).get("p95") or {}).get(key)
            if now is not None and last and abs(now - last) / last > P95_MOVE:
                p95.append(f"{k[0]} {k[1]} {key}: {last} -> {now} ms ({(now - last) / last:+.0%})")
    return {"newly_red": red, "newly_infra": infra, "newly_green": green, "p95": p95, "load_changed": load_changed, "first": False}


def _cell(r: dict) -> str:
    bits = []
    if r.get("failed"):
        f = r["failed"]
        bits.append("; ".join(x[:90] for x in f[:3]) + (f" (+{len(f) - 3} more)" if len(f) > 3 else ""))
    if r.get("infra"):
        bits.append(f"infra: {r['infra'][:200]}")
    if r.get("cut"):
        bits.append(r["cut"])
    return " · ".join(bits).replace("|", "/")


def _folders(r: dict) -> str:
    if "rerun_verdict" in r:
        return f"{r['folder'] or '-'} -> re-run {r['rerun_folder'] or '-'}"
    return r["folder"] or "-"


def _phase_totals(rows: list[dict], gate_s: float) -> str:
    attempts = sum(2 if "rerun_verdict" in r else 1 for r in rows)
    untimed = [x for r in rows for x in r["untimed"]]
    tot = {k: sum((r["run_phases"] or {}).get(k) or 0 for r in rows) for k in phases.KEYS}
    run_s = sum(tot.values())
    share = f"{100 * tot['seeding_s'] / run_s:.1f}%" if run_s else "-"
    return (f"run phases ({attempts - len(untimed)} of {attempts} attempts timed): "
            + " · ".join(f"{k[:-2]} {tot[k]:.0f}s" for k in phases.KEYS)
            + f"; seeding {share} of {run_s:.0f}s measured run seconds; untimed "
            + (f"{len(untimed)} attempts, {sum(untimed):.0f}s wall (no run phases)" if untimed else "none")
            + f"; gate wait {gate_s:.0f}s")


def digest(s: dict) -> str:
    v = [r["verdict"] for r in s["rows"]]
    out = [s["headline"],
           f"sha {s['sha']}{' (smoke)' if s['smoke'] else ''} · {s['started']} -> {s['ended']} · "
           f"load {s['load_start']:.1f} -> {s['load_end']:.1f} ({s['cores']} cores)",
           "walls: " + " · ".join(f"{p} {w['wall_s']:.0f}s" for p, w in s["phases"].items()),
           f"exit {exit_code(v, bool(s.get('infra')))} (0 OK/FLAKY, 1 FAIL, 3 INFRA, all SKIP or no work); counts ok/flaky/fail/infra/skip"]
    if s.get("deps"):
        out.append(f"app deps: {s['deps']}")
    if s.get("all_plan"):
        a = s["all_plan"]
        out.append(f"all plan: {a['line']}")
        for k in ALL_SOURCES:
            hit = [n for n, srcs in a["why"].items() if any(x.startswith(k) for x in srcs)]
            if hit:
                out.append(f"- {k} ({len(hit)}): " + ", ".join(hit[:20]) + (f" (+{len(hit) - 20} more)" if len(hit) > 20 else ""))
    cut = [r for r in s["rows"] if r.get("cut") in (CUT_NOT_RUN, CUT_STOPPED)]
    if cut:
        out.append(f"8 h limit: {len(cut)} scenarios not run or stopped (the next night runs them)")
    waits = [(r["gate_wait_s"], r["scenario"]) for r in s["rows"] if r.get("gate_wait_s")]
    if waits:
        out.append(f"gate wait: {sum(w for w, _ in waits):.0f}s total, max {max(waits)[0]:.0f}s ({max(waits)[1]})")
    if s["rows"]:
        out.append(_phase_totals(s["rows"], sum(w for w, _ in waits)))
    for p in s["phases"]:
        rows = [r for r in s["rows"] if r["phase"] == p]
        ok = [r for r in rows if r["verdict"] == "OK"]
        show = rows if len(rows) <= FULL_TABLE_MAX else [r for r in rows if r["verdict"] != "OK"]
        out += ["", f"## {p}: {len(ok)} OK of {len(rows)} (effective knobs per row)"]
        if show:
            out += ["| scenario | knobs | verdict | s | folder | failed / infra |", "|---|---|---|---|---|---|"]
            out += [f"| {r['scenario']} | {' '.join(recorded_knobs(r)) or 'small, UI on'} | {r['verdict']} | {r['seconds']:.0f} | {_folders(r)} | {_cell(r)} |"
                    for r in show]
        if len(show) < len(rows):
            out.append(f"{len(ok)} OK rows not listed (folders: summary.json `rows`)")
    c = s["changes"]
    out += ["", f"## changes vs previous nightly {s.get('prev') or '(none)'}"]
    if not c["first"]:
        out += [f"- newly red: {', '.join(c['newly_red']) or 'none'}",
                f"- newly infra: {', '.join(c['newly_infra']) or 'none'}",
                f"- newly green: {', '.join(c['newly_green']) or 'none'}",
                f"- p95 moved > {P95_MOVE:.0%}:" + ("" if c["p95"] else " none")]
        out += [f"- load changed: {x}" for x in c.get("load_changed", [])]
        out += [f"  - {x}" for x in c["p95"][:15]] + ([f"  - (+{len(c['p95']) - 15} more)"] if len(c["p95"]) > 15 else [])
    if s.get("map"):
        m = s["map"]
        out += ["", "## map", f"- rule: {m['rule']}"]
        if m.get("map_error"):
            out += [f"- INFRA: {m['map_error']}", "- entries refreshed: n/a"]
        else:
            out += [f"- entries refreshed: {len(m['mapped'])} -> map.json here; slop/map.json {m['restored']}; "
                    "ship: `slop/run nightly --apply-map=<this folder>` on a branch from origin/main",
                    f"- unmapped left: {', '.join(m['unmapped_left']) or 'none'}"]
    return "\n".join(out) + "\n"



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
            "gate_wait_s": ((meta or {}).get("params") or {}).get("lock_wait_s"),
            "run_phases": (meta or {}).get("run_phases"),
            "untimed": [] if phases.timed((meta or {}).get("run_phases")) else [round(seconds, 1)]}


def warm_docker() -> str:
    # a cold Docker Desktop VM timed the first 3 edge starts out at 60 s; never fatal
    from slop.lib.edge import IMAGE, docker_ok
    if (why := docker_ok(IMAGE)) and not why.startswith("docker: "):
        return f"skipped ({why})"
    t0 = time.time()
    try:
        r = subprocess.run(["docker", "run", "--rm", IMAGE, "caddy", "version"], capture_output=True, text=True,
                           timeout=180)
    except subprocess.TimeoutExpired:
        return "timed out after 180 s"
    return f"{'ok' if r.returncode == 0 else 'exit ' + str(r.returncode)} in {time.time() - t0:.0f}s"


def app_deps_stale() -> str | None:
    nm = APP / "node_modules"
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
        self.t0, self.walled = time.time(), False
        self.status = {"pid": os.getpid(), "pid_lstart": procs.lstart(os.getpid()) or "", "phase": None, "scenario": None, "done": 0, "total": 0,
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
               timeout: float | None = None) -> tuple[int, Path | None, str, bool, str]:
        folder, last, gate_line = None, deque(maxlen=4), ""
        self.proc = p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
        fired = threading.Event()
        timer = threading.Timer(timeout, lambda: (fired.set(), kill_tree(p))) if timeout else None
        if timer:
            timer.start()
        try:
            for line in p.stdout:
                line = line.rstrip("\n")
                self.say(line)
                folder = parse_folder_line(line) or folder
                if line.startswith("INFRA: "):
                    gate_line = line.strip()
                if line.strip():
                    last.append(line.strip())
            code = p.wait()
        finally:
            if timer:
                timer.cancel()
        self.proc = None
        return code, folder, " | ".join(last)[:400], fired.is_set(), gate_line

    def may_start(self) -> bool:
        return not self.walled and time.time() - self.t0 < WALL_S - LAST_START_S

    def start_wall(self) -> threading.Timer:
        def hit():
            self.walled = True
            self.say("slop: nightly 8 h limit reached: stopping the running scenario, starting no more")
            self.stop_child()
        t = threading.Timer(max(0.0, self.t0 + WALL_S - time.time()), hit)
        t.daemon = True
        t.start()
        return t

    def run(self, phase: str, name: str) -> dict:
        """One `slop/run <name> <knobs>`; its folder from report.FOLDER_LINE. Not started past the wall
        (cut_row); stopped by it: SKIP with CUT_STOPPED (a killed child proves nothing either way)."""
        if not self.may_start():
            self.say(f"slop: nightly {phase} SKIP {name} ({CUT_NOT_RUN})")
            return cut_row(phase, name)
        t0 = time.time()
        knobs = effective_knobs(phase, name)
        code, folder, tail, _, gate_line = self.stream([str(RUN), name, *knobs], SLOP.parent, env=child_env(os.environ))
        r = row_of(phase, name, folder, time.time() - t0, code, tail, gate_line)
        if self.walled and code:
            r.update(verdict="SKIP", failed=[], infra=None, cut=CUT_STOPPED)
        r["knobs"] = knobs
        self.say(f"slop: nightly {phase} {r['verdict']} {name} ({r['seconds']:.0f}s) {r['folder']}")
        return r

    def stop_child(self) -> None:
        stop_child(self.proc)

    def install_app_deps(self, why: str) -> str | None:
        nm = APP / "node_modules"
        self.say(f"slop: nightly app deps: {why}: gate.py run -- pnpm install --frozen-lockfile in app/")
        code, _, tail, killed, gate_line = self.stream(["python3", str(GATE_PY), "run", "--", "pnpm", "install", "--frozen-lockfile"],
                                            APP, env={**child_env(os.environ), "CI": "true"}, timeout=INSTALL_DEADLINE_S)
        if code == GATE_INFRA:
            return f"pnpm install preflight: machine gate: {gate_line.removeprefix('INFRA: ') or tail[:200]}"
        if killed:
            return (f"pnpm install --frozen-lockfile in app/ timed out after {INSTALL_DEADLINE_S}s "
                    f"(gate wait {CHILD_LOCK_WAIT_S}s + install {INSTALL_TIMEOUT_S}s); see run.log")
        if code:
            return f"pnpm install --frozen-lockfile in app/ failed (exit {code}): {tail[:200]}"
        (nm / LOCK_SHA).write_text(hashlib.sha256((APP / "pnpm-lock.yaml").read_bytes()).hexdigest() + "\n")
        return None


def gate_status() -> str:
    try:
        r = subprocess.run(["python3", str(GATE_PY), "status"], capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).rstrip() or f"(exit {r.returncode}, no output)"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(gate status failed: {type(e).__name__}: {e})"


def _plan_text(stamp: str, sha: str, smoke: bool, plan: dict, why: str, notes: dict | None = None) -> str:
    notes = notes or plan_notes("every scenario")
    carry = notes.get("volume_carry") or []
    lines = [f"nightly plan {stamp} @ {sha}{' (smoke)' if smoke else ''}: "
             f"{sum(map(len, plan.values()))} runs, each `slop/run <scenario> <knobs>`; a FAIL in all/volume re-runs once"]
    for p, names in plan.items():
        how = {"all": notes["line"], "volume": f"{VOLUME_PER_NIGHT} scenarios declaring volume gates (dated rotation)"
               + (f" + {len(carry)} not OK last night: {', '.join(carry)}" if carry else ""),
               "map": why}[p] if not smoke else ("smoke set" if p != "map" else why)
        lines += [f"{p} ({len(names)}): {how}; effective knobs below"]
        lines += [f"  {n} {' '.join(effective_knobs(p, n)) or 'small, UI on'}"
                  + (f"  <- {'; '.join(notes['why'][n])}" if p == "all" and n in notes["why"] else "") for n in names]
    return "\n".join(lines) + "\n"


def finished_nightlies(before: str | None = None):
    for d in sorted(EVIDENCE.glob("*-nightly-*"), reverse=True):
        if (before and d.name >= before) or not (d / "done").exists():
            continue
        try:
            s = json.loads((d / "summary.json").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(s, dict):
            yield d, s


def last_nightly(before: str | None = None, phase: str = "all") -> dict | None:
    for d, s in finished_nightlies(before):
        if not s.get("smoke") and phase in (s.get("phase_names") or []) and s.get("sha") \
                and isinstance(s.get("rows"), list):
            return {"name": d.name, "sha": s["sha"], "rows": s["rows"]}
    return None


def map_attempts(before: str | None = None, lookback: int = PREV_LOOKBACK) -> dict[str, int]:
    tried: dict[str, int] = {}
    i = 0
    for _d, s in finished_nightlies(before):
        rows = [r for r in s.get("rows") or [] if r.get("phase") == "map" and r.get("cut") != CUT_NOT_RUN]
        if not rows:
            continue
        for r in rows:
            tried.setdefault(r["scenario"], i)
        i += 1
        if i >= lookback:
            break
    return tried


def relevance(doc: dict, prev: dict | None) -> tuple[dict | None, str | None]:
    if not doc.get("scenarios"):
        return None, "no map"
    if prev is None:
        return None, "no previous nightly with summary.json"
    try:
        g, picked, _warns = covmap.pick_changed(doc, prev["sha"])
    except (Exception, SystemExit) as e:
        return None, f"pick since {prev['sha']} failed: {type(e).__name__}: {e}"
    blind = sorted(selection.unjudged(g["changed"], g["untracked"], g["map_missing"]))
    if blind:
        return picked, (f"map cannot judge {len(blind)} file(s) changed since {prev['sha']}: "
                        + ", ".join(blind[:3]) + (f" (+{len(blind) - 3} more)" if len(blind) > 3 else "")
                        + "; refresh: slop/run all --map")
    return picked, None


def _prev(out: Path, smoke: bool, phases: list[str]) -> tuple[str | None, list | None]:
    name, rows, seen, looked = None, [], set(), 0
    for d, s in finished_nightlies(out.name):
        if s.get("rows") is None or bool(s.get("smoke")) != smoke or set(s.get("phase_names") or []) != set(phases):
            continue
        for r in s["rows"]:
            k = (r["phase"], r["scenario"])
            if k not in seen and (name is None or r["phase"] == "volume"):
                seen.add(k)
                rows.append(r)
        name = name or d.name
        looked += 1
        if looked >= PREV_LOOKBACK or "volume" not in phases:
            break
    return name, (rows if name else None)


def _map_phase(night: Night, names: list[str], why: str, all_names: list[str]) -> tuple[list[dict], dict]:
    was_dirty = covmap.git("status", "--porcelain", "--", "slop/map.json").strip()
    before, rows, map_error = {}, [], None
    try:
        before = covmap.load_map()["scenarios"]
        for name in names:
            night.mark(phase="map", scenario=name)
            rows.append(night.run("map", name))
            night.mark(done=night.status["done"] + 1)
    except covmap.MapInvalid as e:
        map_error = e
    finally:
        night.stop_child()
        try:
            after = covmap.load_map()["scenarios"] if not map_error else {}
        except covmap.MapInvalid as e:
            after, map_error = {}, e
        if covmap.MAP.exists():
            shutil.copyfile(covmap.MAP, night.out / "map.json")
        if was_dirty:
            restored = "left as it was (it had local edits before this run)"
        else:
            covmap.git("checkout", "--", "slop/map.json")
            restored = "restored (git checkout)"
        night.say(f"slop: nightly map: entries -> {night.out / 'map.json'}; slop/map.json {restored}")
    if map_error:
        reason = f"nightly map invalid after phase: {covmap.map_invalid_reason(map_error)}"
        for row in rows:
            row.update(verdict="INFRA", infra=reason)
    return rows, {"rule": why, "mapped": [] if map_error else sorted(n for n in names if after.get(n) != before.get(n)),
                  "unmapped_left": [] if map_error else sorted(n for n in all_names if n not in after), "restored": restored,
                  "map_error": reason if map_error else None}


def sweep(night: Night, args, plan: dict, why: str, stamp: str, sha: str, all_names: list[str],
          notes: dict | None = None) -> int:
    if shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    night.say(f"slop: nightly {stamp} @ {sha} -> {night.out}", (night.out / "plan.txt").read_text().rstrip())
    cores = os.cpu_count() or 1
    s = {"stamp": stamp, "sha": sha, "smoke": args.smoke, "phase_names": list(plan), "cores": cores,
         "load_start": os.getloadavg()[0], "started": time.strftime("%Y-%m-%d %H:%M %Z"), "phases": {}, "rows": [],
         "all_plan": notes if "all" in plan and not args.smoke else None}
    night.mark(phase="app deps", total=sum(map(len, plan.values())))
    night.start_wall()
    stale = app_deps_stale()
    deps_err = night.install_app_deps(stale) if stale else None
    s["deps"] = deps_err or (f"installed ({stale})" if stale else "up to date")
    s["docker_warm"] = warm_docker()
    night.say(f"slop: nightly docker warm-up: {s['docker_warm']}")
    for phase, names in plan.items():
        t0 = time.time()
        if deps_err:
            rows = [{**row_of(phase, n, None, 0, 3), "infra": deps_err} for n in names]
        elif phase == "map":
            rows, s["map"] = _map_phase(night, names, why, all_names)
        else:
            rows = []
            for name in names:
                night.mark(phase=phase, scenario=name)
                rows.append(night.run(phase, name))
                night.mark(done=night.status["done"] + 1)
            for i, r in enumerate(rows):
                if r["verdict"] == "FAIL" and not night.may_start():
                    rows[i] = {**r, "cut": CUT_NO_RERUN}
                elif r["verdict"] == "FAIL":
                    night.mark(phase=f"{phase} rerun", scenario=r["scenario"])
                    rows[i] = merge_rerun(r, night.run(phase, r["scenario"]))
        s["rows"] += rows
        s["phases"][phase] = {"wall_s": round(time.time() - t0, 1), "n": len(rows)}
    s["prev"], prev_rows = _prev(night.out, args.smoke, list(plan))
    s["changes"] = changes(s["rows"], prev_rows)
    s.update(load_end=os.getloadavg()[0], ended=time.strftime("%Y-%m-%d %H:%M %Z"))
    s["infra"] = deps_err or s.get("map", {}).get("map_error")
    s["headline"] = headline(stamp, [r["verdict"] for r in s["rows"]], bool(s["infra"]))
    s["exit"] = exit_code([r["verdict"] for r in s["rows"]], bool(s["infra"]))
    write_atomic(night.out / "summary.json", json.dumps(s, indent=1) + "\n")
    md = digest(s)
    write_atomic(night.out / "summary.md", md)
    night.say("", md.rstrip(), "", s["headline"])
    return s["exit"]


def apply_map(arg: str) -> int:
    d = Path(arg) if Path(arg).is_dir() else EVIDENCE / arg
    try:
        names = json.loads((d / "summary.json").read_text())["map"]["mapped"]
        got = json.loads((d / "map.json").read_text())
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"slop: --apply-map: {d}: no map phase result ({type(e).__name__}: {e})")
        return 2
    try:
        with covmap.locked_map() as current:
            merged, replaced, added, missing = merge_map(current, got, names)
            current.clear()
            current.update(merged)
    except covmap.MapInvalid as e:
        print(f"slop: --apply-map INFRA: {covmap.map_invalid_reason(e)}")
        return 3
    print(f"slop: --apply-map {d.name} -> {covmap.MAP.relative_to(SLOP.parent)}: replaced {len(replaced)}, "
          f"added {len(added)}" + "".join(f"\n  replaced {n}" for n in replaced) + "".join(f"\n  added {n}" for n in added)
          + (f"\nslop: WARN not in its map.json: {', '.join(missing)}" if missing else ""))
    return 0


def main(argv: list[str], all_s: dict[str, Path]) -> int:
    ap = argparse.ArgumentParser(prog="slop/run nightly", allow_abbrev=False)
    ap.add_argument("--dry", action="store_true", help="print the plan, run nothing, write nothing")
    ap.add_argument("--phases", default=",".join(PHASES), help="comma list of all,volume,map")
    ap.add_argument("--smoke", action="store_true", help="2 UI scenarios, 1 volume, the unmapped: the mechanics")
    ap.add_argument("--detach", action="store_true", help="run in the background; print the folder, return")
    ap.add_argument("--apply-map", metavar="FOLDER", help="merge that nightly's map entries into slop/map.json")
    ap.add_argument("--folder", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if scrub_gate_env(os.environ):
        print("slop: nightly: ignoring inherited SLOP_GATED")
    gate.nice10()
    if args.apply_map:
        return apply_map(args.apply_map)
    phases = [p for p in args.phases.split(",") if p]
    if not phases or set(phases) - set(PHASES):
        ap.error(f"--phases: comma list of {','.join(PHASES)}")
    if args.dry:
        try:
            plan, why, sha, notes = _plan(args, phases, all_s)
        except covmap.MapInvalid as e:
            print(f"slop: INFRA {covmap.map_invalid_reason(e)}", file=sys.stderr)
            return 3
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        print(_plan_text(stamp, sha, args.smoke, plan, why, notes) + f"gate now:\n{gate_status()}\n"
              f"app deps: {app_deps_stale() or 'up to date'}"
              f"{' (would pnpm install)' if app_deps_stale() else ''}\nslop: nightly --dry: nothing run, nothing written")
        return 0
    if args.folder:
        out = Path(args.folder)
    else:
        out = EVIDENCE / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-nightly-{secrets.token_hex(2)}"
        out.mkdir(parents=True)
    stamp = out.name.split("-nightly-")[0]
    if args.detach:
        child = [str(SLOP.parent / "venv" / "bin" / "python"), "-u", "-m", "slop.lib.nightly",  # not cli.py: the venv hook would gate it
                 *child_argv(args, out)]
        with open(out / "run.log", "a") as log:
            p = subprocess.Popen(child, cwd=SLOP.parent, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=True)
        print(f"slop: nightly detached (pid {p.pid}) -> {out}\n"
              f"slop: progress {out}/status.json; done when {out}/done exists (holds the exit code)")
        return 0
    code, night, why_infra = 3, None, None

    def term(*_):
        raise SystemExit(3)
    signal.signal(signal.SIGTERM, term)
    try:
        try:
            night = Night(out, tee=not args.folder)
            night.mark(phase="plan")
            plan, why, sha, notes = _plan(args, phases, all_s, out.name)
            write_atomic(out / "plan.txt", _plan_text(stamp, sha, args.smoke, plan, why, notes)
                         + f"\ngate at start (`python3 ~/.slop/gate.py status`):\n{gate_status()}\n")
            code = sweep(night, args, plan, why, stamp, sha, list(all_s), notes)
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


def _plan(args, phases: list[str], paths: dict[str, Path], before: str | None = None) -> tuple[dict, str, str, dict]:
    doc = covmap.load_map()
    prev = None if args.smoke else last_nightly(before)
    vol_prev = last_nightly(before, "volume") if "volume" in phases and not args.smoke else None
    picked, fallback = relevance(doc, prev) if "all" in phases and not args.smoke else (None, "not needed")
    tried = map_attempts(before) if "map" in phases and not args.smoke else None
    plan, why, notes = build_plan(paths, doc, phases, args.smoke, covmap.map_ages(doc),
                                  datetime.date.today().toordinal(), prev=prev, picked=picked, fallback=fallback,
                                  tried=tried, vol_prev=vol_prev)
    return plan, why, covmap.git("rev-parse", "--short", "HEAD").strip(), notes


if __name__ == "__main__":
    from slop.lib.cli import scenarios
    sys.exit(main(sys.argv[1:], scenarios()))
