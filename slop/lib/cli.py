from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import importlib.util
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

SLOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLOP.parent))

from slop.lib import breakit, covmap, gate, identity, phases, selection  # noqa: E402
from slop.lib.client import Http, Recorder  # noqa: E402
from slop.lib.faults import FAULTS  # noqa: E402
from slop.lib import net, netloss  # noqa: E402
from slop.lib.net import PROFILES  # noqa: E402
from slop.lib.procmon import ProcMon, pool_bent, render  # noqa: E402
from slop.lib.report import EVIDENCE, FOLDER_LINE, Report, run_dir  # noqa: E402
from slop.lib.runs import RUN_FACTS, knobs, run_knobs, same_knobs  # noqa: E402
from slop.lib.stack import Stack  # noqa: E402
from slop.seed import World  # noqa: E402

SCEN = SLOP / "scenarios"


def scenarios() -> dict[str, Path]:
    return {p.stem: p for p in sorted(SCEN.glob("*.py")) if not p.name.startswith("_")}


def load(path: Path):
    name = f"slop_scenario_{path.stem.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # @dataclass under `from __future__ import annotations` looks its module up here
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def thread_limit(mod, scale: str) -> int | None:
    lim = getattr(mod, "MAX_THREADS_PROC", None) or {}
    return int(lim[scale]) if scale in lim else None


def socket_limit(mod, scale: str) -> int | None:
    lim = getattr(mod, "MAX_SOCKETS_RUN", None) or {}
    return int(lim[scale]) if scale in lim else None


class Shard:

    def __init__(self, stack, i: int, rec, args):
        self.idx, self.id = i, stack.shard_ids[i]
        self.url, self.app = stack.shard_urls[i], stack.app_urls.get(i)
        self.db, self.sessions, self.pid = stack.shard_dbs[i], stack.shard_sessions[i], stack.shard_pids[i]
        self.owner = Http(self.url, rec)
        self.world = World(db=self.db, sessions=self.sessions, seed=args.seed, scale=args.scale, owner=self.owner,
                           stream=self.id, user_prefix=f"{self.id}o")
        self.mon: ProcMon | None = None


class Ctx:

    def __init__(self, name, stack, report, rec, args, params, *, ui=False, fault=None, fleet=None, run_phases):
        self.name, self.stack, self.report, self.rec = name, stack, report, rec
        self.scale, self.users, self.seed = args.scale, args.users, args.seed
        self.relay, self.app, self.out = stack.relay, stack.app, report.out
        self.params, self.ui, self.fault, self.fleet = params, ui, fault, fleet
        self.net = args.net
        self.shards = [Shard(stack, i, rec, args) for i in range(stack.shards)] if stack.shards > 1 else []
        if self.shards:
            self.owner, self.world = self.shards[0].owner, self.shards[0].world
        else:
            self.owner = Http(stack.relay, rec)
            self.world = World(db=stack.db, sessions=stack.sessions, seed=args.seed, scale=args.scale,
                               owner=self.owner)
        self.check, self.metric, self.note, self.skip = report.check, report.metric, report.note, report.skip
        self.of_wire = None
        self.mon: ProcMon | None = None
        self.browser_fault_hits: dict[str, int] = {}
        self.browser_fault_files: dict[str, int] = {}
        self.app_ts_fault_files: dict[str, int] = {}
        self.ui_pages: set[str] = set()
        self.run_phases = run_phases

    def param(self, key: str, default):
        v = self.params.get(key, default)
        return type(default)(v) if default is not None else v

    async def build(self, profile: str):
        with self.run_phases.seed():
            t0 = time.time()
            mod = importlib.import_module(f"slop.seed.profiles.{profile}")
            if hasattr(mod, "build_fleet"):
                ws = await mod.build_fleet([s.world for s in self.shards])
                self.metric("seed", {"profile": profile, "seconds": round(time.time() - t0, 2), "shards": len(ws),
                                     "creators": sum(len(w.data.get("creators", [])) for w in ws),
                                     "fans_total": sum(len(v) for w in ws for v in w.data.get("fans", {}).values()),
                                     "threads": sum(len(w.data.get("threads", [])) for w in ws)})
                return ws
            w = await mod.build(self.world)
            self.metric("seed", {"profile": profile, "seconds": round(time.time() - t0, 2),
                                 **{k: len(v) for k, v in w.data.items() if isinstance(v, list)},
                                 "fans_total": sum(len(v) for v in w.data.get("fans", {}).values())})
            return w


def _stock_checks(report: Report, rec: Recorder, out: Path, mod=None) -> None:
    report.check("no 5xx or transport error on any actor call", rec.count(lambda s: s >= 500) == 0,
                 count=rec.count(lambda s: s >= 500))
    unexpected = offline = 0
    expected = tuple(getattr(mod, "EXPECTED_TRACEBACKS", ()))
    for log in sorted(out.glob("relay*.log")):
        u, o = _tracebacks(log, expected)
        unexpected, offline = unexpected + u, offline + o
    report.metric("relay_tracebacks", {"unexpected": unexpected, "offline_expected": offline})
    report.check("relay logged no unexpected Traceback", unexpected == 0, count=unexpected,
                 offline_expected=offline)
    if mod is not None and getattr(mod, "P95_VS_LAST", None) and not report.infra:
        _p95_vs_last_green(report, out, mod.P95_VS_LAST, getattr(mod, "P95_VS_LAST_MIN_N", 0))


def _world(metrics: dict) -> tuple:
    seed = metrics.get("seed") or {}
    return seed.get("profile"), seed.get("creators")


def _green_runs(scenario: str, exclude: Path | None = None):
    for d in sorted(EVIDENCE.glob(f"*-{scenario}-*"), reverse=True):
        if d == exclude or d.is_symlink() or not d.is_dir():
            continue
        try:
            meta = json.loads((d / "metrics.json").read_text())
            checks = json.loads((d / "invariants.json").read_text())
        except (OSError, ValueError):
            continue
        if not meta.get("infra") and all(c.get("status") in ("pass", "skip") for c in checks):
            yield d, meta


def _p95_vs_last_green(report: Report, out: Path, tol, min_n: int = 0) -> None:
    r, a = float(tol[0]), float(tol[1])
    name = f"p95 within {r:g}x (+{a:g}ms) of the last green run"
    cur = report.metrics.get("p95_vs_last_green") or {}
    if report.params.get("fault"):
        report.skip(name, "fault run: no p95 baseline")
        return
    if not cur:
        report.skip(name, "scenario recorded no p95_vs_last_green metric")
        return
    want = {k: v for k, v in report.params.items() if k not in RUN_FACTS}
    world = _world(report.metrics)
    last = None
    for d, meta in _green_runs(report.scenario, out):
        if same_knobs(meta.get("params", {}), want) or _world(meta) != world or not meta.get("p95_vs_last_green"):
            continue
        if min_n and not meta.get("p95_vs_last_green_n"):
            continue
        last = (d, meta["p95_vs_last_green"], meta.get("p95_vs_last_green_n") or {})
        break
    if last is None:
        report.skip(name, "no earlier green run with these knobs and world: this run is the baseline")
        return
    d, prev, prev_n = last
    cur_n = report.metrics.get("p95_vs_last_green_n") or {}
    both = [k for k, v in cur.items() if v is not None and prev.get(k) is not None]
    few = {k: {"now_n": cur_n.get(k, 0), "last_n": prev_n.get(k, 0)} for k in both
           if min_n and min(cur_n.get(k, 0), prev_n.get(k, 0)) < min_n}
    rows = {k: {"now": cur[k], "last": prev[k], "limit": round(max(r * prev[k], prev[k] + a), 1)}
            for k in both if k not in few}
    worse = {k: x for k, x in rows.items() if x["now"] > x["limit"]}
    report.check(name, bool(rows) and not worse, budget=True, last_green=d.name, worse=worse,
                 compared=len(rows), **({"min_n": min_n, "skipped_few_samples": few} if min_n else {}))
    report.note("", f"p95 vs the last green run {d.name} (measured; limit = max({r:g}x, +{a:g}ms)"
                    + (f"; compared only with >= {min_n} samples in both runs" if min_n else "") + "):",
                *(f"  {k:<58} now {x['now']:>8} last {x['last']:>8} limit {x['limit']:>8}"
                  f"{'  WORSE' if k in worse else ''}" for k, x in rows.items()),
                *(f"  {k:<58} skipped: n now {x['now_n']}, last {x['last_n']} (< {min_n})" for k, x in few.items()))


OFFLINE_MARKERS = ("OF read failed",)


def _tracebacks(log: Path, expected: tuple[tuple[str, str], ...] = ()) -> tuple[int, int]:
    if not log.exists():
        return 0, 0
    lines = log.read_text(errors="replace").splitlines()
    unexpected = offline = 0
    end = 0
    for i, line in enumerate(lines):
        if line.startswith("Traceback") and i >= end:
            prev = lines[i - 1] if i else ""
            j, excs = i + 1, []
            while True:
                while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()
                                          or lines[j].startswith("Traceback")):
                    j += 1
                excs.append("\n".join(lines[j:j + 2]))
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k >= len(lines) or not lines[k].startswith(("During handling", "The above exception")):
                    break
                j = k + 1
            end = j + 1
            for n, exc in enumerate(excs):
                if (n == 0 and any(m in prev for m in OFFLINE_MARKERS)) \
                        or any(m in prev and t in exc for m, t in expected):
                    offline += 1
                else:
                    unexpected += 1
    return unexpected, offline


async def _fleet_resources(report: Report, mons: dict[str, ProcMon], mod, out: Path) -> None:
    summs = {}
    for sid, mon in mons.items():
        await mon.write(out)
        (out / "resources.json").rename(out / f"resources-{sid}.json")
        summs[sid] = mon.summary()
    report.metric("relay_resources", summs)
    report.note(*_fleet_table(mons))
    stages = sorted({s for m in mons.values() for s in m.stages()}) or ["run"]
    budget = getattr(mod, "CPU_BUDGET_PCT", None)
    if budget is not None:
        name = f"relay process CPU mean <= {budget}% of one core in every stage"
        per = {f"{sid} {s}": summs[sid][s]["cpu_mean_pct"] for sid in mons for s in stages if s in summs[sid]}
        if not per:
            report.skip(name, "no relay CPU samples (the scenario ended before procmon's first interval)")
        else:
            report.check(name, all(v is not None and v <= budget for v in per.values()), budget=True,
                         budget_pct=budget, max_per_stage={s: max((summs[sid][s]["cpu_mean_pct"] or 0)
                                                                 for sid in mons if s in summs[sid]) for s in stages})
    gate = getattr(mod, "POOL_GATE", None)
    if gate is not None:
        name = (f"DB pool gate (decision 5): {gate['spills']} spills and pool-wait p95 < {gate['wait_p95_ms']}ms, "
                "every shard, every stage")
        per = {f"{sid} {s}": {"spills": summs[sid][s]["pool_spills"], "wait_p95_ms": summs[sid][s]["pool_wait_p95_ms"],
                              "n": summs[sid][s]["pool_wait_n"]}
               for sid in mons for s in stages if s in summs[sid]}
        bad = {k: v for k, v in per.items() if pool_bent(v["spills"], v["wait_p95_ms"], gate)}
        if not any(v["n"] for v in per.values()):
            report.skip(name, "no pool checkouts were timed (lib/relay.py _db_probe)")
        else:
            report.check(name, not bad, budget=True, bad=bad,
                         spills=sum(v["spills"] for v in per.values()),
                         wait_p95_max_ms=max((v["wait_p95_ms"] or 0) for v in per.values()))


def _fleet_table(mons: dict[str, ProcMon]) -> list[str]:
    out: list[str] = []
    for sid, mon in mons.items():
        t, n = mon.table(), len(mon.summary())
        if not out:
            out = ["per shard: " + t[0], *t[1:len(t) - n]]
        out += [f"  [{sid}]", *t[len(t) - n:]]
    return out


async def _resources(report: Report, mon: ProcMon, mod, out: Path) -> None:
    await mon.write(out)
    summ = mon.summary()
    report.metric("relay_resources", summ)
    report.note(*mon.table())
    stages = mon.stages() or ["run"]
    budget = getattr(mod, "CPU_BUDGET_PCT", None)
    if budget is not None:
        # stage mean, not 1 s peaks: executor threads run SQLite outside the GIL, so single seconds pass 100% when healthy
        name = f"relay process CPU mean <= {budget}% of one core in every stage"
        per = {s: summ[s]["cpu_mean_pct"] for s in stages if s in summ}
        if not per:
            report.skip(name, "no relay CPU samples (the scenario ended before procmon's first interval)")
        else:
            report.check(name, all(v is not None and v <= budget for v in per.values()), budget=True,
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


def _source_id() -> str | None:
    try:
        return identity.source_id(SLOP.parent)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"slop: WARN source_id unreadable: {type(e).__name__}: {e}")
        return None


def break_one(name: str, path: Path, args, params) -> str:
    return breakit.break_one(name, path, args, params, load=load, run_one=run_one, source_id=_source_id)


# SystemExit, not Exception: a scenario's `except Exception` must not swallow the timeout
class ScenarioTimeout(SystemExit):
    pass


class RunTerminated(SystemExit):
    pass


@contextlib.contextmanager
def _termination_signals():
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
    def terminate(signum, _frame):
        raise RunTerminated(f"signal {signal.Signals(signum).name}")
    try:
        for sig in old:
            signal.signal(sig, terminate)
        yield
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def _deadline(seconds: int):
    if not seconds:
        yield
        return

    def fire(*_):
        signal.alarm(120)
        raise ScenarioTimeout()
    old = signal.signal(signal.SIGALRM, fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def run_one(name: str, path: Path, args, params, *, fault: str | None = None, tag: str = "") -> Report:
    out = run_dir(name, tag)
    # both before the scenario module is imported
    cov = _harness_coverage(out) if args.map else None
    source_id = _source_id()
    load_error = None
    try:
        mod = load(path)
        ui, shards = knobs(mod, args, params)
    except Exception:
        mod, ui, shards = None, False, 1
        load_error = traceback.format_exc()
    p = {**run_knobs(name, args, params, ui, shards, fault), **_git(), "source_id": source_id,
         "env_id": args.env_id, "env_names": args.env_names, "timeout_s": args.timeout}
    report, rec = Report(name, out, p), Recorder()
    ph, live, terminated = phases.RunPhases(), {}, None
    print(FOLDER_LINE.format(path=out))
    if load_error:
        (out / "scenario-traceback.txt").write_text(load_error)
        _infra_first(report, f"scenario import/knobs failed: {load_error.splitlines()[-1]}")
    else:
        print(f"slop: {name} scale={args.scale} users={args.users} seed={args.seed} ui={ui} fault={fault}"
              f"{f' shards={shards}' if shards > 1 else ''} -> {out}")
        if cov:
            print("slop: --map: relay and harness under coverage.py (slower): a budget or p95 red here is not "
                  "the product's, and does not block the map update")
        try:
            with netloss.guard(args.net, wait=not args.no_wait) as facts, \
                    gate.machine_gate(wait=not args.no_wait, evidence=out,
                                      max_threads_proc=thread_limit(mod, args.scale),
                                      max_sockets_run=socket_limit(mod, args.scale),
                                      exclusive=gate.goes_alone(args.scale, args.users)) as g:
                report.params.update(facts)
                if facts.get("net_wire_stale"):
                    print(f"slop: {facts['net_wire_stale']}")
                report.params.update(g)
                ph.restart()
                with _deadline(args.timeout):
                    try:
                        asyncio.run(_run_stack(name, mod, out, report, rec, args, params, ui, shards, fault, ph, live))
                    except (ScenarioTimeout, RunTerminated) as e:
                        signal.alarm(0)
                        stack = live.get("stack")
                        if stack is not None and stack.tmp.exists():
                            stack.__exit__(None, None, None)
                        if isinstance(e, RunTerminated):
                            terminated = e
                            _infra_first(report, f"{e}; stack torn down")
                        else:
                            _infra_first(report, f"timed out after {args.timeout}s (slop/run --timeout); stack torn down, "
                                                 "run moves on")
                            report.check("scenario finished within --timeout", False, timeout_s=args.timeout)
        except gate.Busy as e:
            _infra_first(report, f"machine gate: {e}")
        except netloss.WireBusy as e:
            _infra_first(report, f"wire lock: {e}")
        except netloss.WireError as e:
            _infra_first(report, f"wire: {e}")
        except RunTerminated as e:
            terminated = e
            _infra_first(report, f"{e}; stack torn down")
    report.metric("run_phases", run_phases := ph.as_dict())
    report.metric("seconds", round(ph.elapsed(), 1))
    report.note(phases.line(run_phases, report.params.get("lock_wait_s")))
    report.params["source_id_end"] = _source_id()
    try:
        _stock_checks(report, rec, out, mod)
        report.write(rec.summary(), rec.errors)
    except RunTerminated as e:
        terminated = e
        _infra_first(report, f"{e} while writing the report")
        report.write(rec.summary(), rec.errors)
    pages = sorted(live["ctx"].ui_pages) if "ctx" in live else []
    http_pages = sorted({p for hp, p in rec.urls if hp in live.get("app_hosts", ())})
    (out / "ui-pages.json").write_text(json.dumps(pages, indent=1) + "\n")
    if http_pages:
        (out / "http-pages.json").write_text(json.dumps(http_pages, indent=1) + "\n")
    print((out / "summary.txt").read_text())
    if cov:
        _map_update(name, report, cov, out, args, ui, pages, http_pages,
                    no_ui_run=bool(getattr(mod, "UI", False)) and not ui)
    if terminated is not None:
        raise terminated
    return report


def _harness_coverage(out: Path):
    import coverage
    d = out / "cov"
    d.mkdir(exist_ok=True)
    os.environ["SLOP_COVERAGE"] = str(d)
    cov = coverage.Coverage(data_file=str(d / ".coverage.harness"), data_suffix=True, config_file=False,
                            source=[str(SLOP)], omit=[f"{EVIDENCE}/*"])
    cov.start()
    return cov


def _map_update(name: str, report: Report, cov, out: Path, args, ui: bool, pages: list[str], http_pages: list[str],
                *, no_ui_run: bool) -> None:
    cov.stop()
    cov.save()
    os.environ.pop("SLOP_COVERAGE", None)
    if report.infra:
        print(f"slop: WARN --map: {name} hit INFRA; its slop/map.json entry is kept as it was")
        return
    root = SLOP.parent.resolve()
    mods = set()
    for m in list(sys.modules.values()):
        try:
            rel = Path(getattr(m, "__file__", None) or "").resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            continue
        if rel.startswith("slop/") and rel.endswith(".py") and not rel.startswith("slop/evidence/"):
            mods.add(rel)
    e = covmap.update(name, out / "cov", sha=args.map_sha, seconds=report.metrics.get("seconds"),
                      scale=args.scale, ui=ui, pages=pages, names=set(scenarios()),
                      http_pages=http_pages, modules=sorted(mods), no_ui_run=no_ui_run)
    print(f"slop: --map: {name} @ {args.map_sha[:7]}: {len(e['py'])} Python files, "
          f"{sum(map(len, e['py'].values()))} functions, {len(e['pages'])} pages ({len(e['http_pages'])} over "
          f"HTTP{'; no UI this run: the old browser pages kept' if no_ui_run else ''}) -> "
          f"{covmap.MAP.relative_to(SLOP.parent)}")


def _with_ports(value: str, ports: dict[str, int]) -> str:
    for name, port in ports.items():
        value = value.replace("{" + name + "}", str(port))
    return value


async def _run_stack(name, mod, out, report, rec, args, params, ui, shards, fault, ph, live) -> None:
    ph.enter("startup")
    try:
        stack = Stack(ui=ui, fault=fault, logdir=out, profile=args.profile, shards=shards,
                      apps=tuple(getattr(mod, "APPS", ())) or (tuple(getattr(mod, "UI_APPS", ())) if ui else ()),
                      boxes=mod.boxes_for(params) if hasattr(mod, "boxes_for") else getattr(mod, "BOXES", None),
                      shards_per_box=getattr(mod, "SHARDS_PER_BOX", None),
                      app_mode=getattr(mod, "APP_MODE", "dev"),
                      sidecars=getattr(mod, "SIDECARS", {}))
        ph.stack = stack
        renv = {k: _with_ports(v, stack.extra_ports) for k, v in getattr(mod, "RELAY_ENV", {}).items()}
        for i in range(stack.shards):
            stack.relay_env[i].update(renv)
        fleet = None
        if shards > 1:
            from slop.lib.edge import Fleet
            fleet = Fleet(stack, out, fault)
        of_wire, wire = None, contextlib.ExitStack()
        if getattr(mod, "OF_WIRE", False):
            from slop.lib.of_wire import FakeOF
            of_wire = wire.enter_context(FakeOF())
            for i in range(stack.shards):
                stack.relay_env[i]["OF_API_ORIGIN"] = of_wire.origin
        # the fake OF outlives the relays it serves
        with wire, stack, (fleet or contextlib.nullcontext()):
            live["stack"] = stack
            print(f"slop: stack up in {ph.elapsed():.0f}s (relay {stack.relay}{', app ' + stack.app if stack.app else ''}"
                  f"{f', {shards} shards, apps on ' + ','.join(stack.shard_ids[i] for i in stack.apps) if shards > 1 else ''}"
                  f"{', edge ' + fleet.edge_url if fleet and fleet.edge_url else ''})")
            ctx = Ctx(name, stack, report, rec, args, params, ui=ui, fault=fault, fleet=fleet, run_phases=ph)
            live["ctx"] = ctx
            live["app_hosts"] = {u.split("//", 1)[-1] for u in (*stack.app_urls.values(), stack.app,
                                                                   fleet and fleet.edge_url) if u}
            ctx.of_wire = of_wire
            pids = [(s.id, s.pid, s.url) for s in ctx.shards] or [(None, stack.relay_pid, stack.relay)]
            hooks = [Http(url, Recorder()) for _, _, url in pids]
            mons = {sid: ProcMon(pid, rec, h, profile=args.profile) for (sid, pid, _), h in zip(pids, hooks)}
            for sh in ctx.shards:
                sh.mon = mons[sh.id]
            mon = next(iter(mons.values()))
            ctx.mon = mon
            for m in mons.values():
                m.start()
            sidecar_mons = {name: ProcMon(p.pid, rec, None) for name, p in stack.sidecar_procs.items()}
            for m in sidecar_mons.values():
                m.start()
            try:
                ph.enter("execution")
                await mod.run(ctx)
            except Exception as e:
                report.infra = f"scenario crashed: {type(e).__name__}: {e}"
                report.check("scenario ran to completion", False, error=f"{type(e).__name__}: {e}")
                (out / "scenario-traceback.txt").write_text(traceback.format_exc())
            finally:
                ph.enter("teardown")
                _client_fault_applied(report, ctx, fault)
                if args.map:
                    for m in mons.values():
                        await m.save_coverage()
                for m in mons.values():
                    await m.stop()
                for name, m in sidecar_mons.items():
                    await m.stop()
                    await m.write(out)
                    (out / "resources.json").rename(out / f"resources-{name}.json")
                    report.metric(f"{name}_resources", m.summary())
                if ctx.shards:
                    await _fleet_resources(report, mons, mod, out)
                else:
                    await _resources(report, mon, mod, out)
                for h in hooks:
                    await h.aclose()
                for sh in ctx.shards:
                    await sh.owner.aclose()
                await ctx.owner.aclose()
    except (ScenarioTimeout, RunTerminated):
        raise
    except (SystemExit, Exception) as e:
        _infra_first(report, f"stack: {e}")
        report.check("stack started", False, error=str(e))


def _infra_first(report: Report, why: str) -> None:
    report.infra = "; ".join(filter(None, (why, report.infra)))


def _mismatch(fault: str, what: str, files: dict, want: int) -> str | None:
    if len(files) in (0, want):
        return None
    return (f"client fault {fault}: its rewrites matched {len(files)} {what}, expected {want}: "
            + ", ".join(f"{p} ({n} matches)" for p, n in sorted(files.items())))


def _client_fault_applied(report: Report, ctx, fault: str | None) -> None:
    f = FAULTS.get(fault or "")
    if not f or not f.browser:
        return
    hits, files, ts_files = ctx.browser_fault_hits, ctx.browser_fault_files, ctx.app_ts_fault_files
    report.metric("browser_fault_hits", {rx: hits.get(rx, 0) for rx, _ in f.browser})
    report.metric("browser_fault_files", files)
    if ts_files:
        report.metric("app_ts_fault_files", ts_files)
    missed = [rx for rx, _ in f.browser if not hits.get(rx)]
    ts_want = f.browser_files if f.ts_files is None else f.ts_files
    why = "; ".join(filter(None, (_mismatch(fault, "served JS files", files, f.browser_files),
                                  _mismatch(fault, "node modules", ts_files, ts_want))))
    if report.infra:
        if why:
            report.infra += f"; {why}"
        return
    if missed:
        report.infra = f"client fault {fault}: its rewrite never matched the app's served JS: {missed}"
    elif why:
        report.infra = why


def _estimates(names, doc: dict, args, all_s: dict[str, Path], params: dict) -> tuple[dict[str, float | None], str]:
    secs, src = {}, set()
    for n in names:
        e = doc["scenarios"].get(n) or {}
        try:
            ui, shards = knobs(load(all_s[n]), args, params)
        except Exception:
            ui, shards = bool(e.get("ui")) and not args.no_ui, 1
        want = run_knobs(n, args, params, ui, shards, None)
        hit = next((m.get("seconds") for _, m in _green_runs(n) if m.get("seconds")
                    and not same_knobs(m.get("params") or {}, want)), None)
        secs[n] = hit if hit is not None else e.get("seconds")
        src.add("evidence" if hit is not None else "map")
    return secs, "|".join(sorted(src)) or "-"


def _changed(all_s: dict[str, Path], args, params: dict) -> tuple[dict[str, Path], list[str], list[str], list[str]] | None:
    doc = covmap.load_map()
    if not doc["scenarios"]:
        print(f"slop: --changed needs {covmap.MAP.relative_to(SLOP.parent)} (missing or empty): build it with "
              "slop/run all --map")
        return None
    g, picks, warns = covmap.pick_changed(doc, args.since)
    picks = {n: r for n, r in picks.items() if n in all_s}
    no_ui = sorted(n for n, r in picks.items() if args.no_ui and selection.needs_ui(r))
    secs, est_src = _estimates(picks, doc, args, all_s, params)
    vol = {n: covmap.is_volume(all_s[n]) for n in picks}
    run, skipped = selection.plan({n: r for n, r in picks.items() if n not in no_ui}, secs, args.budget * 60)
    changed = sorted(set(g["untracked"]) | {f for fs in g["changed"].values() for f in fs})
    unmapped = sorted(n for n in all_s if n not in doc["scenarios"])
    head = covmap.git("rev-parse", "HEAD").strip()
    dirty = bool(covmap.git("status", "--porcelain").strip())
    stale, stale_reason = covmap.map_stale(g["map_age"])
    base = f"{g['base'][:7]} ({g['base_how']})" if g["base"] else f"each map sha ({g['base_how']})"
    ages = ", ".join(f"{s[:7]} {n}" for s, n in g["map_age"].items())
    lines = [f"slop: --changed vs {base}; map sha(s) commits behind HEAD {head[:7]}: {ages}; "
             f"{len(changed)} changed file(s) under {' '.join(covmap.DIFF_ROOTS)}"]
    if stale:
        lines.append(f"slop: WARN {stale_reason}: rebuild with slop/run all --map")
    w = max(map(len, picks), default=0)

    def row(n: str) -> str:
        est = "%5.0fs" % secs[n] if secs[n] is not None else "    ?s"
        rs = [r for _, r in picks[n]]
        return (f"{n:<{w}}  {est}  {selection.tier(picks[n]):<6} {'volume' if vol[n] else '      '}  "
                + "; ".join(rs[:2]) + (f" (+{len(rs) - 2} more)" if len(rs) > 2 else ""))
    lines += [f"  {row(n)}" for n in run]
    lines += [f"  SKIP (budget) {row(n)}" for n in skipped]
    lines += [f"  SKIP (needs UI) {row(n)}" for n in no_ui]
    warn_lines = [f"slop: {x}" for x in warns]
    lines += warn_lines
    if unmapped:
        lines.append(f"slop: WARN unmapped (picked only when their own file changes): {', '.join(unmapped)}")
    est = sum(secs[n] or 0 for n in run)
    cap = f"--budget={args.budget:g} min" if args.budget else "no budget"
    lines.append(f"slop: --changed picks {len(run)} of {len(all_s)} scenarios (~{est / 60:.0f} min, est: {est_src}); "
                 f"{len(skipped)} skipped by budget ({cap})" + (f"; {len(no_ui)} need UI (--no-ui)" if no_ui else "")
                 if picks else f"slop: --changed picks nothing ({len(changed)} changed file(s))")
    out = EVIDENCE / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-changed-{secrets.token_hex(2)}"
    out.mkdir(parents=True)
    lines.append(f"slop: pick -> {out.relative_to(SLOP.parent)}" + (" (dry: nothing run)" if args.dry else ""))
    print("\n".join(lines))
    (out / "pick.txt").write_text("\n".join(lines) + "\n")

    def entry(n: str) -> dict:
        return {"scenario": n, "seconds": secs[n], "tier": selection.tier(picks[n]), "volume": vol[n],
                "reasons": [{"tier": t, "reason": r} for t, r in picks[n]]}
    (out / "pick.json").write_text(json.dumps({
        "git_sha": head, "git_dirty": dirty, "dry": args.dry, "budget_min": args.budget, "estimates": est_src,
        "no_ui": args.no_ui, "base": {"sha": g["base"], "how": g["base_how"]},
        "maps": {sha: {"behind_head": n} for sha, n in g["map_age"].items()},
        "run": [entry(n) for n in run], "skipped_by_budget": [entry(n) for n in skipped],
        "skipped_needs_ui": [entry(n) for n in no_ui], "warnings": warns, "unmapped": unmapped,
        "changed_files": changed}, indent=1) + "\n")
    return {n: all_s[n] for n in run}, skipped, no_ui, warn_lines


def _nice() -> None:
    gate.nice10()
    if "SLOP_PW_NODE" not in os.environ:
        try:
            from playwright._impl._driver import compute_driver_executable
        except ImportError:
            return
        os.environ["SLOP_PW_NODE"] = compute_driver_executable()[0]
        os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(SLOP / "lib" / "pw-node")


def _parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: --user=200 must not mean --users
    ap = argparse.ArgumentParser(prog="slop/run", allow_abbrev=False)
    ap.add_argument("target", nargs="?", default=None, help="scenario stem (an exact name runs only that one) or any "
                    "substring of it, or all (default all; omitted with --changed)")
    gate.add_load_args(ap)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--break", dest="break_it", action="store_true",
                    help="run a green baseline, then the scenario's FAULT; CAUGHT only if every check "
                         "the fault targets goes PASS -> FAIL")
    ap.add_argument("--baseline", metavar="RUN_DIR",
                    help="with --break: reuse this no-fault run (same knobs and Run identity) instead of running one")
    ap.add_argument("--fault", metavar="NAME", help="with --break: inject this lib/faults.py fault instead of "
                    "the scenario's FAULT (e.g. to prove another check can go red)")
    ap.add_argument("--profile", action="store_true",
                    help="run a stack sampler in the relay; per-stage profile-<stage>.txt in the evidence")
    ap.add_argument("--no-ui", action="store_true", help="skip Playwright/next dev even if the scenario has UI")
    ap.add_argument("--net", choices=list(PROFILES), default=None,
                    help="throttle every browser page actors/ui.py opens to this lib/net.py phone network (wire "
                         "profiles jp-lossy*: slow-connections only, dummynet via sudo slop/install-netloss)")
    ap.add_argument("--shards", type=int, default=None,
                    help="a fleet: N relays behind the real Caddy edge (lib/edge.py); default the scenario's SHARDS")
    ap.add_argument("--timeout", type=int, default=1800, metavar="SECONDS",
                    help="wall clock per scenario run (stack up to teardown); past it the run is INFRA and "
                         "the next one starts. 0 = none. Default 1800 (the slowest green run, big-model "
                         "medium/200, takes ~830 s)")
    ap.add_argument("--no-wait", action="store_true",
                    help="INFRA at once when the wire lock, gate slot or admission is busy, instead of waiting "
                         "(wire: SLOP_WIRE_LOCK_WAIT_S, default 900 s, waited holding the gate slot; "
                         "gate: SLOP_LOCK_WAIT_S)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="scenario param")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--map", action="store_true",
                    help="run under coverage.py and record the pages visited; update slop/map.json's entry of "
                         f"each scenario run (needs a clean tree under {' '.join(covmap.DIFF_ROOTS)})")
    ap.add_argument("--changed", action="store_true",
                    help="run only the scenarios this branch's diff (vs merge-base with origin/main) can reach, cheapest first")
    ap.add_argument("--dry", action="store_true", help="with --changed: print and record the pick, run nothing")
    ap.add_argument("--since", metavar="REF",
                    help="with --changed: diff against REF instead of `git merge-base HEAD origin/main`; "
                         "--since=map diffs against slop/map.json's sha (drift since the sweep)")
    ap.add_argument("--budget", type=float, default=15, metavar="MIN",
                    help="with --changed: own/flow picks always run; shared/layout ones only while the mapped "
                         "estimate stays within MIN minutes (default 15, 0 = no cap)")
    return ap


def _main() -> int:
    ap = _parser()
    args, extra = ap.parse_known_args()
    args.env_id, args.env_names = identity.env_id(os.environ)
    for e in extra:
        k, _, v = e[2:].partition("=")
        if not (e.startswith("--") and "=" in e and k.replace("-", "_").isidentifier()):
            ap.error(f"unrecognized argument: {e!r} (scenario knobs take --name=value, one per argument)")
        args.set.append(f"{k.replace('-', '_')}={v}")
    params = dict(kv.split("=", 1) for kv in args.set)
    all_s = scenarios()
    if args.list:
        mapped = covmap.load_map()["scenarios"]
        w = max(map(len, all_s))
        for n in all_s:
            e = mapped.get(n)
            volume = "  volume" if covmap.is_volume(all_s[n]) else ""
            print(f"{n:<{w}}  " + (f"{e.get('seconds') or 0:>6.0f}s  {e['sha'][:7]}{volume}"
                                   if e else "        unmapped" + volume))
        return 0
    if args.changed and args.target:
        ap.error("--changed picks the scenarios itself: drop the target")
    if args.changed and args.break_it:
        ap.error("--break is per scenario, by name: slop/run <scenario> --break --baseline=<its green run folder>")
    if args.dry and not args.changed:
        ap.error("--dry needs --changed")
    if args.since and not args.changed:
        ap.error("--since needs --changed")
    if args.map and (args.changed or args.break_it):
        ap.error("--map runs the scenarios as they are: not with --changed or --break")
    if args.map:
        dirty = covmap.dirty_for_map()
        if dirty:
            print(f"slop: --map needs a clean tree under {' '.join(covmap.DIFF_ROOTS)} (the map's sha must be the "
                  f"code that ran): commit or stash these first:\n{dirty}")
            return 2
        args.map_sha = covmap.git("rev-parse", "HEAD").strip()
        os.environ["COVERAGE_CORE"] = "sysmon"
    tail: list[str] = []
    if args.changed:
        got = _changed(all_s, args, params)
        if got is None:
            return 2
        picked, skipped, no_ui, warn_lines = got
        tail = [f"slop: {len(skipped)} skipped by budget (not run, not green): {', '.join(skipped)}"] if skipped else []
        tail += [f"slop: {len(no_ui)} SKIP (needs UI) (--no-ui; not run, not green): {', '.join(no_ui)}"] if no_ui else []
        tail += warn_lines
        if args.dry or not picked:
            if tail and not args.dry:
                print("\n".join(tail))
            return 0
    else:
        target = args.target or "all"
        picked = (all_s if target == "all" else {target: all_s[target]} if target in all_s
                  else {k: v for k, v in all_s.items() if target in k})
    if not picked:
        print(f"slop: no scenario matches {args.target!r}; have: {', '.join(all_s)}")
        return 2
    if net.is_wire(args.net):
        unsupported = [n for n, p in picked.items() if args.no_ui or not getattr(load(p), "WIRE_NET", False)]
        if unsupported:
            print(f"slop: --net={args.net} needs a wire-capable UI scenario: {', '.join(unsupported)}")
            return 3
        if why := netloss.wire_problem():
            print(f"slop: --net={args.net}: {why}")
            return 3
    _nice()
    if args.fault and not args.break_it:
        ap.error("--fault needs --break")
    if args.baseline and not (args.break_it and len(picked) == 1):
        ap.error("--baseline needs --break and exactly one scenario")
    if args.break_it:
        verdicts = {n: break_one(n, p, args, params) for n, p in picked.items()}
        for n, v in verdicts.items():
            print(f"slop: {v} {n}")
        vs = set(verdicts.values())
        return 3 if "INCONCLUSIVE" in vs else 1 if "NOT CAUGHT" in vs else 0
    reports = {n: run_one(n, p, args, params) for n, p in picked.items()}
    for n, r in reports.items():
        print(f"slop: {'INFRA' if r.infra else 'OK  ' if r.ok else 'FAIL'} {n}" + (f": {r.infra}" if r.infra else ""))
    if tail:
        print("\n".join(tail))
    if any(r.infra for r in reports.values()):
        return 3
    return 0 if all(r.ok for r in reports.values()) else 1


def main() -> int:
    with _termination_signals():
        try:
            return _main()
        except RunTerminated as e:
            print(f"slop: INFRA {e}; invocation stopped", file=sys.stderr)
            return 3
        except ScenarioTimeout:
            print("slop: INFRA --timeout fired outside a scenario run; invocation stopped", file=sys.stderr)
            return 3
        except covmap.MapInvalid as e:
            print(f"slop: INFRA {covmap.map_invalid_reason(e)}", file=sys.stderr)
            return 3


if __name__ == "__main__":
    sys.exit(main())
