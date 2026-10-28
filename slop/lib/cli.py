"""slop/run entrypoint. See slop/README.md."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import importlib.util
import json
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

SLOP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLOP.parent))  # so `slop.seed...` and `slop.actors...` import

from slop.lib.client import Http, Recorder  # noqa: E402
from slop.lib.faults import FAULTS  # noqa: E402
from slop.lib.procmon import ProcMon, pool_bent, render  # noqa: E402
from slop.lib.report import EVIDENCE, Report, run_dir  # noqa: E402
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


class Shard:
    """One relay of a fleet run (`--shards=N`): its id (s01..), relay URL, app URL
    (None where no `next dev` runs), temp DB, seed World (own RNG stream and
    usernames) and owner session. `mon` is its ProcMon."""

    def __init__(self, stack, i: int, rec, args):
        self.idx, self.id = i, stack.shard_ids[i]
        self.url, self.app = stack.shard_urls[i], stack.app_urls.get(i)
        self.db, self.sessions, self.pid = stack.shard_dbs[i], stack.shard_sessions[i], stack.shard_pids[i]
        self.owner = Http(self.url, rec)
        self.world = World(db=self.db, sessions=self.sessions, seed=args.seed, scale=args.scale, owner=self.owner,
                           stream=self.id, user_prefix=f"{self.id}o")
        self.mon: ProcMon | None = None


class Ctx:
    """What a scenario gets: the stack, the owner session, the knobs, check/metric.
    A fleet run (`--shards=N`, N > 1) also gets `shards` (one Shard each; shard 0
    is `owner` / `world`) and `fleet` (lib/edge.py: the Caddy edge and the map)."""

    def __init__(self, name, stack, report, rec, args, params, *, ui=False, fault=None, fleet=None):
        self.name, self.stack, self.report, self.rec = name, stack, report, rec
        self.scale, self.users, self.seed = args.scale, args.users, args.seed
        self.relay, self.app, self.out = stack.relay, stack.app, report.out
        self.params, self.ui, self.fault, self.fleet = params, ui, fault, fleet
        self.shards = [Shard(stack, i, rec, args) for i in range(stack.shards)] if stack.shards > 1 else []
        if self.shards:
            self.owner, self.world = self.shards[0].owner, self.shards[0].world
        else:
            self.owner = Http(stack.relay, rec)
            self.world = World(db=stack.db, sessions=stack.sessions, seed=args.seed, scale=args.scale,
                               owner=self.owner)
        self.check, self.metric, self.note, self.skip = report.check, report.metric, report.note, report.skip

    def param(self, key: str, default):
        v = self.params.get(key, default)
        return type(default)(v) if default is not None else v

    async def build(self, profile: str):
        """The profile's World; a fleet profile (`build_fleet`) gets every shard's
        World and returns them as a list."""
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
    """Invariants every scenario gets for free."""
    report.check("no 5xx or transport error on any actor call", rec.count(lambda s: s >= 500) == 0,
                 count=rec.count(lambda s: s >= 500))
    unexpected = offline = 0
    expected = tuple(getattr(mod, "EXPECTED_TRACEBACKS", ()))
    for log in sorted(out.glob("relay*.log")):  # relay.log, or relay-sNN.log per fleet shard
        u, o = _tracebacks(log, expected)
        unexpected, offline = unexpected + u, offline + o
    report.metric("relay_tracebacks", {"unexpected": unexpected, "offline_expected": offline})
    report.check("relay logged no unexpected Traceback", unexpected == 0, count=unexpected,
                 offline_expected=offline)
    if mod is not None and getattr(mod, "P95_VS_LAST", None) and not report.infra:
        _p95_vs_last_green(report, out, mod.P95_VS_LAST, getattr(mod, "P95_VS_LAST_MIN_N", 0))


# Knobs that must match for a previous run to be "the same run" (baseline, last green).
def _same_knobs(have: dict, want: dict) -> dict:
    diff = {k: (have.get(k), v) for k, v in want.items() if have.get(k) != v}
    diff |= {k: (have[k], None) for k in have if k not in want and k not in ("git_sha", "git_dirty")}
    return diff


def _p95_vs_last_green(report: Report, out: Path, tol, min_n: int = 0) -> None:
    """Stock: each p95 the scenario put in metric `p95_vs_last_green` ({key: ms})
    against the newest earlier run of the same scenario with the same knobs, no
    fault, no infra and every check pass/skip. FAIL when cur > max(r * last,
    last + a) for `P95_VS_LAST = (r, a)` in the scenario. The first such run sets
    the baseline (SKIP). With `P95_VS_LAST_MIN_N = n` the scenario also records
    metric `p95_vs_last_green_n` ({key: samples}); a key is compared only when
    both runs have >= n samples (the rest are listed as skipped), and an earlier
    run without that metric is not a candidate."""
    r, a = float(tol[0]), float(tol[1])
    name = f"p95 within {r:g}x (+{a:g}ms) of the last green run"
    cur = report.metrics.get("p95_vs_last_green") or {}
    if not cur:
        report.skip(name, "scenario recorded no p95_vs_last_green metric")
        return
    want = {k: v for k, v in report.params.items() if k not in ("git_sha", "git_dirty")}
    last = None
    for d in sorted(EVIDENCE.glob(f"*-{report.scenario}-*"), reverse=True):
        if d == out or d.is_symlink() or not d.is_dir():
            continue
        try:
            meta = json.loads((d / "metrics.json").read_text())
            checks = json.loads((d / "invariants.json").read_text())
        except (OSError, ValueError):
            continue
        if meta.get("infra") or _same_knobs(meta.get("params", {}), want) or not meta.get("p95_vs_last_green"):
            continue
        if min_n and not meta.get("p95_vs_last_green_n"):
            continue
        if all(c.get("status") in ("pass", "skip") for c in checks):
            last = (d, meta["p95_vs_last_green"], meta.get("p95_vs_last_green_n") or {})
            break
    if last is None:
        report.skip(name, "no earlier green run with these knobs: this run is the baseline")
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


# Log lines that announce a traceback the offline stack causes by design: the
# seeded Creators have stub OF sessions and the network guard refuses OnlyFans,
# so any relay-side OF read fails. Add a marker only for that cause.
OFFLINE_MARKERS = ("OF read failed",)


def _tracebacks(log: Path, expected: tuple[tuple[str, str], ...] = ()) -> tuple[int, int]:
    """(unexpected, expected) Tracebacks. Expected: the line before names an
    OFFLINE_MARKERS cause, or matches a scenario's EXPECTED_TRACEBACKS pair
    (marker in the line before, text in the traceback's last line: the error a
    scenario's fake makes OnlyFans answer)."""
    if not log.exists():
        return 0, 0
    lines = log.read_text(errors="replace").splitlines()
    unexpected = offline = 0
    for i, line in enumerate(lines):
        if line.startswith("Traceback"):
            prev = lines[i - 1] if i else ""
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()
                                      or lines[j].startswith(("During handling", "The above exception"))
                                      or lines[j].startswith("Traceback")):
                j += 1
            last = "\n".join(lines[j:j + 2])  # the exception line (an OFAPIError's body is on the next)
            if any(m in prev for m in OFFLINE_MARKERS) or any(m in prev and t in last for m, t in expected):
                offline += 1
            else:
                unexpected += 1
    return unexpected, offline


async def _fleet_resources(report: Report, mons: dict[str, ProcMon], mod, out: Path) -> None:
    """A fleet run: per shard resources-sNN.json and table rows; the CPU budget
    over every shard (the max); the decision-5 pool gate if the scenario sets
    POOL_GATE = {"spills": 0, "wait_p95_ms": 100} (procmon.pool_bent, shared with chatter-crowd)."""
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
        per = {f"{sid} {s}": summs[sid][s]["cpu_mean_pct"] for sid in mons for s in stages if s in summs[sid]}
        report.check(f"relay process CPU mean <= {budget}% of one core in every stage",
                     bool(per) and all(v is not None and v <= budget for v in per.values()), budget=True,
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
    """procmon's table once, its rows per shard."""
    out: list[str] = []
    for sid, mon in mons.items():
        t, n = mon.table(), len(mon.summary())
        if not out:
            out = ["per shard: " + t[0], *t[1:len(t) - n]]
        out += [f"  [{sid}]", *t[len(t) - n:]]
    return out


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


class ScenarioTimeout(BaseException):
    """--timeout ran out. A BaseException, so a scenario's `except Exception` cannot swallow it."""


@contextlib.contextmanager
def _deadline(seconds: int):
    """SIGALRM after `seconds` raises ScenarioTimeout in the main thread, wherever it is: an
    await (asyncio.run then cancels the scenario, so its finally blocks and the stack's
    teardown run) or a blocking call. Fires again every 120 s while a teardown hangs too."""
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
    """One scenario run on its own stack, at most `--timeout` seconds. `report.infra` is
    set when the stack or the scenario itself broke, or it timed out (no verdict possible)."""
    mod = load(path)
    ui, shards = _knobs(mod, args, params)
    out = run_dir(name, tag)
    p = {"scenario": name, "scale": args.scale, "users": args.users, "seed": args.seed, "ui": ui,
         "fault": fault, **({"shards": shards} if shards > 1 else {}),
         **({"profile": True} if args.profile else {}), **_git(), **params}
    report, rec = Report(name, out, p), Recorder()
    print(f"slop: {name} scale={args.scale} users={args.users} seed={args.seed} ui={ui} fault={fault}"
          f"{f' shards={shards}' if shards > 1 else ''} -> {out}")
    t0, live = time.time(), {}
    with _deadline(args.timeout):
        try:
            asyncio.run(_run_stack(name, mod, out, report, rec, args, params, ui, shards, fault, t0, live))
        except ScenarioTimeout:
            signal.alarm(0)
            stack = live.get("stack")
            if stack is not None and stack.tmp.exists():  # its teardown never finished: finish it
                stack.__exit__(None, None, None)
            report.infra = f"timed out after {args.timeout}s (slop/run --timeout); stack torn down, run moves on"
            report.check("scenario finished within --timeout", False, timeout_s=args.timeout)
    _stock_checks(report, rec, out, mod)
    report.metric("seconds", round(time.time() - t0, 1))
    report.write(rec.summary(), rec.errors)
    print((out / "summary.txt").read_text())
    return report


async def _run_stack(name, mod, out, report, rec, args, params, ui, shards, fault, t0, live) -> None:
    try:
        stack = Stack(ui=ui, fault=fault, logdir=out, profile=args.profile, shards=shards,
                      apps=tuple(getattr(mod, "APPS", ())) or (tuple(getattr(mod, "UI_APPS", ())) if ui else ()),
                      boxes=getattr(mod, "BOXES", None),
                      shards_per_box=getattr(mod, "SHARDS_PER_BOX", None))
        for i in range(stack.shards):  # a scenario's RELAY_ENV: extra env for every relay it starts
            stack.relay_env[i].update(getattr(mod, "RELAY_ENV", {}))
        fleet = None
        if shards > 1:
            from slop.lib.edge import Fleet  # fleet runs only: the Caddy edge from deploy/fleet/fleet.py
            fleet = Fleet(stack, out, fault)
        of_wire, wire = None, contextlib.ExitStack()  # entered once, here: the relays need its origin to start
        if getattr(mod, "OF_WIRE", False):  # OnlyFans' API on loopback (lib/of_wire.py), the relay's OF_API_ORIGIN
            from slop.lib.of_wire import FakeOF
            of_wire = wire.enter_context(FakeOF())
            for i in range(stack.shards):
                stack.relay_env[i]["OF_API_ORIGIN"] = of_wire.origin
        with wire, stack, (fleet or contextlib.nullcontext()):  # the fake OF outlives the relays it serves
            live["stack"] = stack  # entered: a timeout that cuts its teardown short finishes it (run_one)
            print(f"slop: stack up in {time.time() - t0:.0f}s (relay {stack.relay}{', app ' + stack.app if stack.app else ''}"
                  f"{f', {shards} shards, apps on ' + ','.join(stack.shard_ids[i] for i in stack.apps) if shards > 1 else ''}"
                  f"{', edge ' + fleet.edge_url if fleet and fleet.edge_url else ''})")
            ctx = Ctx(name, stack, report, rec, args, params, ui=ui, fault=fault, fleet=fleet)
            ctx.of_wire = of_wire
            pids = [(s.id, s.pid, s.url) for s in ctx.shards] or [(None, stack.relay_pid, stack.relay)]
            hooks = [Http(url, Recorder()) for _, _, url in pids]  # /__slop/loop-cpu and /profile: not actor calls
            mons = {sid: ProcMon(pid, rec, h, profile=args.profile) for (sid, pid, _), h in zip(pids, hooks)}
            for sh in ctx.shards:
                sh.mon = mons[sh.id]
            mon = next(iter(mons.values()))
            ctx.mon = mon  # a scenario may read mon.intervals (per-second relay CPU) for a windowed check
            for m in mons.values():
                m.start()
            try:
                await mod.run(ctx)
            except Exception as e:  # a crashed scenario has no verdict, but keeps its evidence
                report.infra = f"scenario crashed: {type(e).__name__}: {e}"
                report.check("scenario ran to completion", False, error=f"{type(e).__name__}: {e}")
                (out / "scenario-traceback.txt").write_text(traceback.format_exc())
            finally:
                _client_fault_applied(report, ctx, fault)
                for m in mons.values():
                    await m.stop()
                if ctx.shards:
                    await _fleet_resources(report, mons, mod, out)
                else:
                    await _resources(report, mon, mod, out)
                for h in hooks:
                    await h.aclose()
                for sh in ctx.shards:
                    await sh.owner.aclose()
                await ctx.owner.aclose()
    except (SystemExit, Exception) as e:  # the stack did not come up (or died tearing down)
        report.infra = f"stack: {e}"
        report.check("stack started", False, error=str(e))


def _client_fault_applied(report: Report, ctx, fault: str | None) -> None:
    """A client fault (lib/faults.py `browser=`) ran as declared, else INFRA, never a verdict:
    every rewrite matched the JS the browser loaded or the app modules lib/app_ts.py ran in
    node (else a stale pattern, or a run with no UI and no such check), and in each of the two
    that it hit the matches landed in exactly the fault's `browser_files` distinct files (else
    the pattern is not unique to the function it breaks: a red check could be another module's)."""
    f = FAULTS.get(fault or "")
    if not f or not f.browser:
        return
    hits = getattr(ctx, "browser_fault_hits", {})
    files = getattr(ctx, "browser_fault_files", {})
    ts_files = getattr(ctx, "app_ts_fault_files", {})
    report.metric("browser_fault_hits", {rx: hits.get(rx, 0) for rx, _ in f.browser})
    report.metric("browser_fault_files", files)
    if ts_files:
        report.metric("app_ts_fault_files", ts_files)
    missed = [rx for rx, _ in f.browser if not hits.get(rx)]
    if report.infra:
        return
    if missed:
        report.infra = f"client fault {fault}: its rewrite never matched the app's served JS: {missed}"
    elif any(len(fs) not in (0, f.browser_files) for fs in (files, ts_files)):
        report.infra = (f"client fault {fault}: its rewrites matched {len(files)} served files and "
                        f"{len(ts_files)} node modules, expected {f.browser_files} each: "
                        f"{sorted(files)} {sorted(ts_files)}")


def _knobs(mod, args, params: dict | None = None) -> tuple[bool, int]:
    """(ui, shards) a run of `mod` uses: UI unless --no-ui; --shards, else the scenario's
    `shards_for(params)` (a layout knob that changes the shard count), else its SHARDS, else 1."""
    n = args.shards or (mod.shards_for(params or {}) if hasattr(mod, "shards_for") else getattr(mod, "SHARDS", 1))
    return bool(getattr(mod, "UI", False)) and not args.no_ui, int(n or 1)


def _status(checks: list[dict]) -> dict[str, str]:
    return {c["name"]: c.get("status") or ("pass" if c["ok"] else "fail") for c in checks}


def _load_baseline(d: Path, name: str, ui: bool, args, params, shards: int = 1) -> tuple[dict, str | None]:
    """(statuses, problem) from a previous no-fault run of the same scenario and knobs."""
    try:
        checks = json.loads((d / "invariants.json").read_text())
        meta = json.loads((d / "metrics.json").read_text())
    except (OSError, ValueError) as e:
        return {}, f"baseline {d} unreadable: {e}"
    bp = meta.get("params", {})
    want = {"scenario": name, "scale": args.scale, "users": args.users, "seed": args.seed, "ui": ui,
            "fault": None, **({"shards": shards} if shards > 1 else {}),
            **({"profile": True} if args.profile else {}), **params}
    diff = _same_knobs(bp, want)
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
        ui, shards = _knobs(mod, args, params)
        base, problem = _load_baseline(base_dir, name, ui, args, params, shards)
    else:
        print(f"slop: break-it-once {fault}: green baseline first")
        b = run_one(name, path, args, params, tag="baseline")
        base_dir, base, problem = b.out, _status(b.checks), (f"baseline infra failure: {b.infra}" if b.infra else None)
    broken_dir, broken, broken_problem = None, {}, None
    if not problem:
        r = run_one(name, path, args, params, fault=fault, tag="break")
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
    ap.add_argument("--shards", type=int, default=None,
                    help="a fleet: N relays behind the real Caddy edge (lib/edge.py); default the scenario's SHARDS")
    ap.add_argument("--timeout", type=int, default=1800, metavar="SECONDS",
                    help="wall clock per scenario run (stack up to teardown); past it the run is INFRA and "
                         "the next one starts. 0 = none. Default 1800 (the slowest green run, big-model "
                         "medium/200, takes ~830 s)")
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
    reports = {n: run_one(n, p, args, params) for n, p in picked.items()}
    for n, r in reports.items():
        print(f"slop: {'INFRA' if r.infra else 'OK  ' if r.ok else 'FAIL'} {n}")
    if any(r.infra for r in reports.values()):
        return 3
    return 0 if all(r.ok for r in reports.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
