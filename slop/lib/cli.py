"""slop/run entrypoint. See slop/README.md."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

SLOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLOP.parent))  # so `slop.seed...` and `slop.actors...` import

from slop.lib.client import Http, Recorder  # noqa: E402
from slop.lib.faults import FAULTS  # noqa: E402
from slop.lib.procmon import ProcMon, render  # noqa: E402
from slop.lib.report import Report, run_dir  # noqa: E402
from slop.lib.stack import Stack  # noqa: E402
from slop.seed import SCALES, World  # noqa: E402

SCEN = SLOP / "scenarios"


def scenarios() -> dict[str, Path]:
    return {p.stem: p for p in sorted(SCEN.glob("*.py")) if not p.name.startswith("_")}


def load(path: Path):
    spec = importlib.util.spec_from_file_location(f"slop_scenario_{path.stem.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ctx:
    """What a scenario gets: the stack, the owner session, the knobs, check/metric."""

    def __init__(self, name, stack, report, rec, args, params):
        self.name, self.stack, self.report, self.rec = name, stack, report, rec
        self.scale, self.users, self.seed = args.scale, args.users, args.seed
        self.relay, self.app, self.out = stack.relay, stack.app, report.out
        self.params = params
        self.owner = Http(stack.relay, rec)
        self.world = World(db=stack.db, sessions=stack.sessions, seed=args.seed, scale=args.scale, owner=self.owner)
        self.check, self.metric, self.note, self.skip = report.check, report.metric, report.note, report.skip

    def param(self, key: str, default):
        v = self.params.get(key, default)
        return type(default)(v) if default is not None else v

    async def build(self, profile: str) -> World:
        t0 = time.time()
        mod = importlib.import_module(f"slop.seed.profiles.{profile}")
        w = await mod.build(self.world)
        self.metric("seed", {"profile": profile, "seconds": round(time.time() - t0, 2),
                             **{k: len(v) for k, v in w.data.items() if isinstance(v, list)},
                             "fans_total": sum(len(v) for v in w.data.get("fans", {}).values())})
        return w


def _stock_checks(report: Report, rec: Recorder, out: Path) -> None:
    """Invariants every scenario gets for free."""
    report.check("no 5xx or transport error on any actor call", rec.count(lambda s: s >= 500) == 0,
                 count=rec.count(lambda s: s >= 500))
    unexpected, offline = _tracebacks(out / "relay.log")
    report.metric("relay_tracebacks", {"unexpected": unexpected, "offline_expected": offline})
    report.check("relay logged no unexpected Traceback", unexpected == 0, count=unexpected,
                 offline_expected=offline)


# Log lines that announce a traceback the offline stack causes by design: the
# seeded Creators have stub OF sessions and the network guard refuses OnlyFans,
# so any relay-side OF read fails. Add a marker only for that cause.
OFFLINE_MARKERS = ("OF read failed",)


def _tracebacks(log: Path) -> tuple[int, int]:
    if not log.exists():
        return 0, 0
    lines = log.read_text(errors="replace").splitlines()
    unexpected = offline = 0
    for i, line in enumerate(lines):
        if line.startswith("Traceback"):
            prev = lines[i - 1] if i else ""
            if any(m in prev for m in OFFLINE_MARKERS):
                offline += 1
            else:
                unexpected += 1
    return unexpected, offline


async def _resources(report: Report, mon: ProcMon, mod, out: Path) -> None:
    """Relay CPU/RSS per stage into the evidence, the CPU budget check if the
    scenario sets CPU_BUDGET_PCT, and with --profile the peak stage's hot frames."""
    await mon.write(out)
    summ = mon.summary()
    report.metric("relay_resources", summ)
    report.note(*mon.table())
    stages = mon.stages() or ["run"]
    budget = getattr(mod, "CPU_BUDGET_PCT", None)
    if budget is not None:
        # The stage mean, not 1 s peaks: executor threads run SQLite outside the GIL,
        # so single seconds pass 100% in a healthy run. The loop thread rides along.
        per = {s: summ[s]["cpu_mean_pct"] for s in stages if s in summ}
        report.check(f"relay process CPU mean <= {budget}% of one core in every stage",
                     bool(per) and all(v is not None and v <= budget for v in per.values()), budget=True,
                     budget_pct=budget, per_stage=per,
                     p95_pct={s: summ[s]["cpu_p95_pct"] for s in stages if s in summ},
                     loop_mean_pct={s: summ[s]["loop_mean_pct"] for s in stages if s in summ})
    prof = await mon.fetch_profile(out)
    if mon.profile_errors:
        report.metric("profile_errors", mon.profile_errors)
    if prof:
        staged = [s for s in stages if s in prof.get("stages", {})]
        if staged:
            peak = max(staged, key=lambda s: summ.get(s, {}).get("cpu_mean_pct") or 0)
            report.note("", f"profile of the peak-CPU stage {peak} (measured; stack sampler in the relay "
                            f"wrapper, see lib/relay.py; full: profile-{peak}.txt, profile-{peak}-*.collapsed):",
                        *render(peak, prof["stages"][peak], 10, prof.get("hz")))


def _git() -> dict:
    def git(*a: str) -> str:
        try:
            return subprocess.run(["git", *a], cwd=SLOP.parent, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"git_sha": git("rev-parse", "--short", "HEAD").strip() or None,
            "git_dirty": bool(git("status", "--porcelain").strip())}


async def run_one(name: str, path: Path, args, params, *, fault: str | None = None, tag: str = "") -> Report:
    """One scenario run on its own stack. `report.infra` is set when the stack or
    the scenario itself broke (no verdict possible)."""
    mod = load(path)
    ui = bool(getattr(mod, "UI", False)) and not args.no_ui
    out = run_dir(name, tag)
    p = {"scenario": name, "scale": args.scale, "users": args.users, "seed": args.seed, "ui": ui,
         "fault": fault, **({"profile": True} if args.profile else {}), **_git(), **params}
    report, rec = Report(name, out, p), Recorder()
    print(f"slop: {name} scale={args.scale} users={args.users} seed={args.seed} ui={ui} fault={fault} -> {out}")
    t0 = time.time()
    try:
        with Stack(ui=ui, fault=fault, logdir=out, profile=args.profile) as stack:
            print(f"slop: stack up in {time.time() - t0:.0f}s (relay {stack.relay}{', app ' + stack.app if ui else ''})")
            ctx = Ctx(name, stack, report, rec, args, params)
            hook = Http(stack.relay, Recorder())  # /__slop/loop-cpu and /profile: not actor calls
            mon = ProcMon(stack.relay_pid, rec, hook, profile=args.profile)
            ctx.mon = mon  # a scenario may read mon.intervals (per-second relay CPU) for a windowed check
            mon.start()
            try:
                await mod.run(ctx)
            except Exception as e:  # a crashed scenario has no verdict, but keeps its evidence
                report.infra = f"scenario crashed: {type(e).__name__}: {e}"
                report.check("scenario ran to completion", False, error=f"{type(e).__name__}: {e}")
            finally:
                await mon.stop()
                await _resources(report, mon, mod, out)
                await hook.aclose()
                await ctx.owner.aclose()
    except (SystemExit, Exception) as e:  # the stack did not come up (or died tearing down)
        report.infra = f"stack: {e}"
        report.check("stack started", False, error=str(e))
    _stock_checks(report, rec, out)
    report.metric("seconds", round(time.time() - t0, 1))
    report.write(rec.summary(), rec.errors)
    print((out / "summary.txt").read_text())
    return report


def _status(checks: list[dict]) -> dict[str, str]:
    return {c["name"]: c.get("status") or ("pass" if c["ok"] else "fail") for c in checks}


def _load_baseline(d: Path, name: str, ui: bool, args, params) -> tuple[dict, str | None]:
    """(statuses, problem) from a previous no-fault run of the same scenario and knobs."""
    try:
        checks = json.loads((d / "invariants.json").read_text())
        meta = json.loads((d / "metrics.json").read_text())
    except (OSError, ValueError) as e:
        return {}, f"baseline {d} unreadable: {e}"
    bp = meta.get("params", {})
    want = {"scenario": name, "scale": args.scale, "users": args.users, "seed": args.seed, "ui": ui,
            "fault": None, **({"profile": True} if args.profile else {}), **params}
    diff = {k: (bp.get(k), v) for k, v in want.items() if bp.get(k) != v}
    diff |= {k: (bp[k], None) for k in bp if k not in want and k not in ("git_sha", "git_dirty")}
    if diff:
        return {}, f"baseline {d} was run with other knobs (have, want): {diff}"
    if meta.get("infra"):
        return {}, f"baseline {d} had an infra failure: {meta['infra']}"
    return _status(checks), None


def break_one(name: str, path: Path, args, params) -> str:
    """Break-it-once. Returns CAUGHT, NOT CAUGHT or INCONCLUSIVE."""
    mod = load(path)
    fault = args.fault or getattr(mod, "FAULT", None)
    if not fault or fault not in FAULTS:
        print(f"slop: {name} declares no known FAULT ({fault!r}); --break needs one of {', '.join(FAULTS)}")
        return "INCONCLUSIVE"
    targets = FAULTS[fault].targets
    if args.baseline:
        base_dir = Path(args.baseline).resolve()
        ui = bool(getattr(mod, "UI", False)) and not args.no_ui
        base, problem = _load_baseline(base_dir, name, ui, args, params)
    else:
        print(f"slop: break-it-once {fault}: green baseline first")
        b = asyncio.run(run_one(name, path, args, params, tag="baseline"))
        base_dir, base, problem = b.out, _status(b.checks), (f"baseline infra failure: {b.infra}" if b.infra else None)
    broken_dir, broken, broken_problem = None, {}, None
    if not problem:
        r = asyncio.run(run_one(name, path, args, params, fault=fault, tag="break"))
        broken_dir, broken = r.out, _status(r.checks)
        broken_problem = f"fault run infra failure: {r.infra}" if r.infra else None

    missing = [t for t in targets if t not in base or (broken_dir and t not in broken)]
    not_green = [t for t in targets if base.get(t) not in (None, "pass")]
    went_red = [t for t in targets if base.get(t) == "pass" and broken.get(t) == "fail"]
    stayed = [f"{t} ({base.get(t)} -> {broken.get(t)})" for t in targets if t not in went_red]
    noise = [f"{n}: {base.get(n, 'absent')} -> {st}" for n, st in broken.items()
             if n not in targets and base.get(n) != st]
    noise += [f"{n}: {st} -> absent" for n, st in base.items() if n not in targets and broken_dir and n not in broken]
    reasons = [x for x in (problem, broken_problem) if x]
    reasons += [f"fault targets check(s) the scenario never ran: {missing}"] if missing and not problem else []
    reasons += [f"targeted check(s) not green in the baseline: {not_green}"] if not_green and not problem else []
    skipped = [t for t in targets if broken.get(t) == "skip"]
    reasons += [f"targeted check(s) skipped in the fault run: {skipped}"] if skipped else []
    if reasons:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "CAUGHT" if len(went_red) == len(targets) else "NOT CAUGHT"
    base_red = sorted(n for n, st in base.items() if st == "fail" and n not in targets)

    lines = [f"break-it-once {fault}: mutation {verdict}",
             f"  baseline: {base_dir}", f"  fault run: {broken_dir}",
             f"  targeted checks PASS -> FAIL: {went_red or 'none'}"]
    lines += [f"  targeted checks NOT turned red: {stayed}"] if stayed and not reasons else []
    lines += [f"  inconclusive: {r_}" for r_ in reasons]
    lines += [f"  noise (non-targeted checks that changed; they catch nothing): {noise or 'none'}"]
    lines += [f"  note: baseline already red on non-targeted: {base_red}"] if base_red else []
    print("slop: " + "\n".join(lines))
    if broken_dir:
        with open(broken_dir / "summary.txt", "a") as f:
            f.write("\n" + "\n".join(lines) + "\n")
        (broken_dir / "break.json").write_text(json.dumps({
            "fault": fault, "verdict": verdict, "targets": list(targets), "went_red": went_red,
            "noise": noise, "inconclusive": reasons, "baseline": str(base_dir)}, indent=2))
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(prog="slop/run")
    ap.add_argument("target", nargs="?", default="all", help="scenario stem or any substring of it, or all")
    ap.add_argument("--scale", choices=list(SCALES), default="small")
    ap.add_argument("--users", type=int, default=20, help="concurrent simulated users per actor pool")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--break", dest="break_it", action="store_true",
                    help="run a green baseline, then the scenario's FAULT; CAUGHT only if every check "
                         "the fault targets goes PASS -> FAIL")
    ap.add_argument("--baseline", metavar="RUN_DIR",
                    help="with --break: reuse this no-fault run (same knobs) instead of running one")
    ap.add_argument("--fault", metavar="NAME", help="with --break: inject this lib/faults.py fault instead of "
                    "the scenario's FAULT (e.g. to prove another check can go red)")
    ap.add_argument("--profile", action="store_true",
                    help="run a stack sampler in the relay; per-stage profile-<stage>.txt in the evidence")
    ap.add_argument("--no-ui", action="store_true", help="skip Playwright/next dev even if the scenario has UI")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="scenario param")
    ap.add_argument("--list", action="store_true")
    args, extra = ap.parse_known_args()
    # Any other `--some-knob=value` is a scenario param, same as `--set some_knob=value`.
    for e in extra:
        if not (e.startswith("--") and "=" in e):
            ap.error(f"unrecognized argument: {e} (scenario knobs take --name=value)")
        k, v = e[2:].split("=", 1)
        args.set.append(f"{k.replace('-', '_')}={v}")
    all_s = scenarios()
    if args.list:
        print("\n".join(all_s))
        return 0
    picked = all_s if args.target == "all" else {k: v for k, v in all_s.items() if args.target in k}
    if not picked:
        print(f"slop: no scenario matches {args.target!r}; have: {', '.join(all_s)}")
        return 2
    params = dict(kv.split("=", 1) for kv in args.set)
    if args.fault and not args.break_it:
        ap.error("--fault needs --break")
    if args.baseline and not (args.break_it and len(picked) == 1):
        ap.error("--baseline needs --break and exactly one scenario")
    if args.break_it:
        # 0 every fault CAUGHT, 1 some NOT caught, 3 some INCONCLUSIVE (infra / bad baseline).
        verdicts = {n: break_one(n, p, args, params) for n, p in picked.items()}
        for n, v in verdicts.items():
            print(f"slop: {v} {n}")
        vs = set(verdicts.values())
        return 3 if "INCONCLUSIVE" in vs else 1 if "NOT CAUGHT" in vs else 0
    reports = {n: asyncio.run(run_one(n, p, args, params)) for n, p in picked.items()}
    for n, r in reports.items():
        print(f"slop: {'INFRA' if r.infra else 'OK  ' if r.ok else 'FAIL'} {n}")
    if any(r.infra for r in reports.values()):
        return 3
    return 0 if all(r.ok for r in reports.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
