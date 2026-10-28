"""Relay CPU and memory, sampled from outside the process, per load stage.

Every second `ps` reports the relay process group's cumulative CPU time and RSS
(the relay is its own process group: stack.py starts it with start_new_session).
CPU% over an interval = delta CPU seconds / delta wall seconds * 100, so 100% is
one core busy; it can pass 100% when executor threads work outside the GIL. Each
interval is tagged with `rec.stage` at its start, the same tag the HTTP recorder
uses, so the per-stage table lines up with the per-stage p95s. Nothing runs inside
the relay for this.

With `--profile`, the relay wrapper (lib/relay.py, never service/) also runs a
stack sampler; this monitor tells it the current stage on every change and
fetches the per-stage profiles before the stack goes down.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

INTERVAL_S = 1.0
# Upper bounds (ms) of the pool-wait histogram lib/relay.py _db_probe reports; half-open
# (`ms < b`): bucket 100 holds [75,100) ms.
WAIT_BOUNDS_MS = (0.5, 1, 2, 5, 10, 25, 50, 75, 100, 250, 500, 1000, 2000, float("inf"))
_PS: dict = {"t": 0.0, "out": "", "lock": None, "loop": None}  # one `ps -A` per 0.5 s for every monitor (fleet)


def _proc_all() -> str:
    """`ps -A -o pgid=,time=,rss=` read from /proc, for Linux without procps (the relay
    image calibrate.sh runs the harness in): TIME as 0:<seconds>, RSS in KiB."""
    tick, page_kb = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE") // 1024
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                st = f.read().rpartition(")")[2].split()  # fields after the command name
        except OSError:
            continue  # gone meanwhile
        out.append(f"{st[2]} 0:{(int(st[11]) + int(st[12])) / tick:.2f} {int(st[21]) * page_kb}")
    return "\n".join(out)


async def _ps_all() -> str:
    loop = asyncio.get_running_loop()
    if _PS["loop"] is not loop:  # one lock per event loop: --break runs two loops in one process
        _PS.update(lock=asyncio.Lock(), loop=loop, t=0.0)
    async with _PS["lock"]:
        if time.monotonic() - _PS["t"] > 0.5 and shutil.which("ps") is None:
            _PS.update(t=time.monotonic(), out=await asyncio.to_thread(_proc_all))
        elif time.monotonic() - _PS["t"] > 0.5:
            p = await asyncio.create_subprocess_exec("ps", "-A", "-o", "pgid=,time=,rss=",
                                                     stdout=asyncio.subprocess.PIPE)
            out, _ = await p.communicate()
            _PS.update(t=time.monotonic(), out=out.decode())
        return _PS["out"]


def wait_p95(hist: list[int]) -> float | None:
    """The bucket upper bound (ms, exclusive) holding the 95th percentile pool wait."""
    n = sum(hist)
    if not n:
        return None
    k, run = 0.95 * n, 0
    for b, c in zip(WAIT_BOUNDS_MS, hist):
        run += c
        if run >= k:
            return b
    return WAIT_BOUNDS_MS[-1]


def pool_bent(spills: int, wait_p95_ms: float | None, gate: dict) -> bool:
    """Decision 5's pool gate, the one predicate every gate site calls (chatter-crowd's
    judge_stage, lib/cli.py's POOL_GATE check): bent on any spill above the gate, or a
    pool-wait p95 bucket whose (exclusive) upper bound is over the gate, so bucket 100
    ([75,100) ms) holds "< 100 ms" and bucket 250 does not. A null wait p95 (no checkout
    timed) passes; null spills never get here (missing pool data is `nodata` upstream)."""
    return spills > gate["spills"] or (wait_p95_ms is not None and wait_p95_ms > gate["wait_p95_ms"])


def _cpu_seconds(s: str) -> float:
    """ps TIME: [[dd-]hh:]mm:ss.cc."""
    days, _, rest = s.rpartition("-")
    total = 0.0
    for part in rest.split(":"):
        total = total * 60 + float(part)
    return total + (int(days) * 86400 if days else 0)


def _max(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else None


def pct(xs: list[float], q: float = 0.95) -> float | None:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * q))], 1) if xs else None


class ProcMon:
    def __init__(self, pgid: int, rec, relay_http, *, profile: bool = False):
        self.pgid, self.rec, self.http, self.profile = pgid, rec, relay_http, profile
        self.samples: list[dict] = []  # {t, stage, cpu_s, rss_mb, loop_s, loop_t}
        self._tl_i = 0  # rec.timeline read so far
        self.intervals: list[dict] = []  # {stage, wall_s, cpu_s, cpu_pct, loop_pct, rss_mb}
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.profile_stage: str | None = None
        self.profile_errors: list[str] = []
        self.nested_at: dict = {}  # top stacks of nested DB checkouts (lib/relay.py _db_probe)
        self._fresh = False  # the next sample starts a new series (follow())
        self._lost = 0  # polls by samples that left no interval (process not seen): counted lost, next interval

    def follow(self, pgid: int, relay_http) -> None:
        """Watch another process group from now on (the shard's relay restarted elsewhere, e.g.
        restored on another box). No interval spans the switch: CPU counters restart."""
        self.pgid, self.http, self._fresh = pgid, relay_http, True

    async def _ps(self) -> tuple[float, float] | None:
        out = await _ps_all()
        cpu = rss = 0.0
        hit = False
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == str(self.pgid):
                cpu += _cpu_seconds(parts[1])
                rss += int(parts[2]) / 1024
                hit = True
        return (cpu, rss) if hit else None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            stage = self.rec.stage
            t_pre, mono_pre = time.time(), time.monotonic()  # stamps around this sample's reads
            got, loop, threads = await asyncio.gather(self._ps(), self._loop_cpu(), self._threads())
            t_post, mono_post = time.time(), time.monotonic()
            # One /__slop/loop-cpu poll per sample. Lost (raised or non-200): the relay may have
            # reset its pool histogram, so that interval's waits are gone. Pool missing: answered
            # without the wait histogram or the spill counter.
            lost = loop is None
            db_now = (loop or {}).get("db") or {}
            missing = not lost and ((db_now.get("wait") or {}).get("hist") is None or db_now.get("spills") is None)
            if got is None:
                self._lost += 1
            if got is not None:
                s = {"t": time.time(), "stage": stage, "cpu_s": got[0], "rss_mb": round(got[1], 1),
                     "loop_s": loop and loop["thread_s"], "loop_t": loop and loop["mono_s"],
                     "db": (loop or {}).get("db"), "threads": threads, "load1": round(os.getloadavg()[0], 2),
                     "sched": (loop or {}).get("sched"), "t_pre": t_pre, "mono_pre": mono_pre,
                     "t_post": t_post, "mono_post": mono_post}
                if self.samples and not self._fresh:
                    prev = self.samples[-1]
                    wall = s["t"] - prev["t"]
                    if wall > 0:
                        d = s["cpu_s"] - prev["cpu_s"]
                        lw = (s["loop_t"] - prev["loop_t"]) if s["loop_t"] and prev["loop_t"] else 0
                        lp = round((s["loop_s"] - prev["loop_s"]) / lw * 100, 1) if lw > 0 else None
                        db, pdb = s["db"] or {}, prev["db"] or {}
                        q, pq = s["sched"], prev["sched"]
                        self.intervals.append({"stage": prev["stage"], "t0": round(prev["t"], 3),
                                               "wall_s": round(wall, 3), "cpu_s": round(d, 3),
                                               "cpu_pct": round(d / wall * 100, 1), "loop_pct": lp,
                                               "rss_mb": s["rss_mb"], "threads": s["threads"],
                                               "db_peak": db.get("out_peak"),
                                               "db_new": db["opened"] - pdb["opened"] if db and pdb else None,
                                               "db_nested": db["nested"] - pdb["nested"] if db and pdb else None,
                                               "db_spills": (db["spills"] - pdb["spills"]
                                                             if db.get("spills") is not None
                                                             and pdb.get("spills") is not None else None),
                                               "db_wait": (db.get("wait") or {}).get("hist"),
                                               "db_wait_max_ms": (db.get("wait") or {}).get("max_ms"),
                                               "host_load1": s["load1"], "polls": 1 + self._lost,
                                               "polls_lost": int(lost) + self._lost, "pool_missing": int(missing),
                                               # the interval's span: just before the first sample's
                                               # reads to just after the last's (epoch s, monotonic s)
                                               "t_pre": round(prev["t_pre"], 3), "t_post": round(s["t_post"], 3),
                                               "mono_pre": round(prev["mono_pre"], 3),
                                               "mono_post": round(s["mono_post"], 3),
                                               # Q: the loop thread's run-queue wait and timeslices
                                               # (schedstat deltas; null off Linux), context only
                                               "q_run_delay_ms": round((q[1] - pq[1]) / 1e6, 3) if q and pq else None,
                                               "q_slices": q[2] - pq[2] if q and pq else None,
                                               **self._requests_until(s["t"])})
                        self._lost = 0
                        if db.get("nested_at"):
                            self.nested_at = db["nested_at"]
                self.samples.append(s)
                self._fresh = False
            if self.profile and stage != self.profile_stage:
                await self._tell_profiler(stage)
            try:
                await asyncio.wait_for(self._stop.wait(), INTERVAL_S)
            except asyncio.TimeoutError:
                pass

    def _requests_until(self, t: float) -> dict:
        """Actor calls that ended since the last sample (~`t`): how many, and the slowest (ms)."""
        tl = getattr(self.rec, "timeline", None) or []
        ms = [c[3] for c in tl[self._tl_i:] if not c[1].startswith("GET /__slop")]
        self._tl_i = len(tl)
        return {"req_n": len(ms), "req_max_ms": round(max(ms), 1) if ms else None}

    async def _threads(self) -> int | None:
        """Threads in the relay process now (each pooled SQLite connection is one aiosqlite thread)."""
        if shutil.which("ps") is None:  # Linux without procps: the relay is its group's leader
            try:
                return len(os.listdir(f"/proc/{self.pgid}/task")) or None
            except OSError:
                return None
        p = await asyncio.create_subprocess_exec("ps", "-M", "-p", str(self.pgid), stdout=asyncio.subprocess.PIPE)
        out, _ = await p.communicate()
        n = len(out.decode().splitlines()) - 1
        return n if n > 0 else None

    async def _loop_cpu(self) -> dict | None:
        """The relay's loop CPU and pool counters; None for a lost poll (raised or non-200)."""
        try:
            r = await self.http.get("/__slop/loop-cpu")
            return r.json() if r.status_code == 200 else None
        except Exception:  # noqa: BLE001 — a lost poll: counted per interval (polls_lost)
            return None

    async def _tell_profiler(self, stage: str | None) -> None:
        try:
            await self.http.post("/__slop/profile", json={"stage": stage})
            self.profile_stage = stage
        except Exception as e:  # noqa: BLE001 — a profiler hiccup must not end the run
            self.profile_errors.append(f"{type(e).__name__}: {e}")

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    def summary(self) -> dict:
        """Per stage (and `run`, every interval): CPU mean / p95 / max %, cores, RSS max / end."""
        groups: dict[str, list[dict]] = {}
        for iv in self.intervals:
            groups.setdefault(iv["stage"] or "-", []).append(iv)
        groups["run"] = self.intervals
        out = {}
        for name, ivs in groups.items():
            if not ivs:
                continue
            wall = sum(i["wall_s"] for i in ivs)
            cpu = sum(i["cpu_s"] for i in ivs)
            mean = round(cpu / wall * 100, 1) if wall else None
            lps = [i["loop_pct"] for i in ivs if i.get("loop_pct") is not None]
            loop_mean = round(sum(lps) / len(lps), 1) if lps else None
            out[name] = {"intervals": len(ivs), "wall_s": round(wall, 1), "cpu_s": round(cpu, 1),
                         "loop_mean_pct": loop_mean, "loop_p95_pct": pct(lps),
                         "cpu_mean_pct": mean, "cpu_p95_pct": pct([i["cpu_pct"] for i in ivs]),
                         "cpu_max_pct": max(i["cpu_pct"] for i in ivs),
                         "cores_mean": round(mean / 100, 2) if mean is not None else None,
                         "rss_max_mb": max(i["rss_mb"] for i in ivs), "rss_end_mb": ivs[-1]["rss_mb"],
                         "threads_max": _max(i.get("threads") for i in ivs),
                         "db_conns_peak": _max(i.get("db_peak") for i in ivs),
                         "db_opened": sum(i.get("db_new") or 0 for i in ivs),
                         "db_nested": sum(i.get("db_nested") or 0 for i in ivs),
                         "host_load_max": _max(i.get("host_load1") for i in ivs),
                         **_pool(ivs)}
        return out

    def stages(self) -> list[str]:
        seen: list[str] = []
        for iv in self.intervals:
            if iv["stage"] and iv["stage"] not in seen:
                seen.append(iv["stage"])
        return seen

    def table(self) -> list[str]:
        s = self.summary()
        rows = [f"  {n:<10} {v['wall_s']:>7} {v['cpu_mean_pct']:>8} {v['cpu_p95_pct']:>7} {v['cpu_max_pct']:>7} "
                f"{v['cores_mean']:>6} {v['loop_mean_pct'] if v['loop_mean_pct'] is not None else '-':>8} "
                f"{v['loop_p95_pct'] if v['loop_p95_pct'] is not None else '-':>7} {v['rss_max_mb']:>8} {v['rss_end_mb']:>8}"
                f" {_dash(v['threads_max']):>7} {_dash(v['db_conns_peak']):>7} {v['db_opened']:>7} {v['db_nested']:>7}"
                f" {_dash(v['host_load_max']):>7} {v['pool_spills']:>6} {_dash(v['pool_wait_p95_ms']):>7}"
                f" {_dash(v['pool_wait_max_ms']):>8}"
                for n, v in s.items()]
        return ["relay CPU/RSS (measured every 1 s; 100% = one core; '-' = outside any stage). cpu = whole process",
                "(ps), loop = the event-loop thread alone (time.thread_time via /__slop/loop-cpu), the 1-core ceiling:",
                "threads = relay threads (max); dbPeak = SQLAlchemy connections checked out at once (max);",
                "dbOpen = SQLite connections opened; nested = checkouts by a task already holding one (lib/relay.py);",
                "hostLd = the machine's 1-min load average (max; other processes compete for the cores);",
                "spills = pool checkouts that waited SPILL_AFTER_S and opened an extra connection; waitP95 / waitMax =",
                "time inside the pool's checkout (ms; p95 is the bucket's exclusive upper bound, 100 = [75,100)):",
                "  stage       wall_s  cpu%mean cpu%p95 cpu%max  cores loop%mean loop%p95  rssMax   rssEnd"
                " threads  dbPeak  dbOpen  nested  hostLd spills waitP95  waitMax", *rows]

    async def write(self, out: Path) -> None:
        (out / "resources.json").write_text(json.dumps(
            {"interval_s": INTERVAL_S, "summary": self.summary(), "intervals": self.intervals,
             "db_nested_at": self.nested_at}, indent=1))

    async def fetch_profile(self, out: Path) -> dict | None:
        """The relay's per-stage stack profiles -> profile.json + profile-<stage>.txt."""
        if not self.profile:
            return None
        try:
            r = await self.http.get("/__slop/profile")
            prof = r.json()
        except Exception as e:  # noqa: BLE001
            self.profile_errors.append(f"fetch: {type(e).__name__}: {e}")
            return None
        (out / "profile.json").write_text(json.dumps(prof, indent=1))
        for stage, p in prof.get("stages", {}).items():
            (out / f"profile-{stage}.txt").write_text("\n".join(render(stage, p, 40, prof.get("hz"))) + "\n")
            for part in ("loop", "threads"):
                (out / f"profile-{stage}-{part}.collapsed").write_text("\n".join(
                    f"{k} {round(v)}" for k, v in sorted(p[part]["stacks"].items(), key=lambda kv: -kv[1])) + "\n")
        return prof


def _pool(ivs: list[dict]) -> dict:
    hist = [0] * len(WAIT_BOUNDS_MS)
    for i in ivs:
        for k, c in enumerate(i.get("db_wait") or []):
            hist[k] += c
    mx = _max(i.get("db_wait_max_ms") for i in ivs)
    return {"pool_spills": sum(i.get("db_spills") or 0 for i in ivs), "pool_wait_n": sum(hist),
            "pool_wait_p95_ms": wait_p95(hist), "pool_wait_max_ms": round(mx, 1) if mx is not None else None,
            "polls": sum(i.get("polls", 1) for i in ivs), "polls_lost": sum(i.get("polls_lost", 0) for i in ivs),
            "pool_missing": sum(i.get("pool_missing", 0) for i in ivs)}


def _dash(v) -> object:
    return "-" if v is None else v


def render(stage: str, p: dict, n: int, hz: int) -> list[str]:
    """Sample weights are wall ms (each look weighs the time since the previous one)."""
    wall = p["wall_ms"] or 1
    out = [f"stage {stage}: {wall / 1000:.1f}s sampled (~{hz} Hz target per sampler; idle = leaf blocked in "
           "select/wait/queue get; lib/relay.py _Sampler)"]
    for part, what in (("loop", "event-loop thread (SIGALRM sampler; ~ its CPU)"),
                       ("threads", "other threads (stack sampler; wall time in C incl. SQLite lock waits)")):
        q = p[part]
        busy = q["busy"] or 1
        out += ["", f"== {what}: busy {q['busy'] / 1000:.1f} thread-s = {q['busy'] / wall * 100:.0f}% of wall; by thread: "
                + ", ".join(f"{t} {c / 1000:.1f}s" for t, c in sorted(q["threads"].items(), key=lambda kv: -kv[1])[:6])]
        for title, key in ((f"top {n} self (leaf function / SQL; % of this part's busy)", "self"),
                           (f"top {n} self lines", "lines"), (f"top {n} cumulative", "cum")):
            out += [f"{title}:"] + [f"  {c / busy * 100:5.1f}%  {c / 1000:7.1f}s  {f}"
                                    for f, c in sorted(q[key].items(), key=lambda kv: -kv[1])[:n]]
    return out
