"""Throwaway local stack per run: the slop relay on a temp SQLite DB and, when a
scenario needs the UI, `next dev` behind demo-shots' fetch guard. Free loopback
ports, own process groups, torn down on exit; app/tsconfig.json and
app/next-env.d.ts (which `next dev` rewrites) are restored. Same safety model as
scripts/demo-shots/run.sh: nothing leaves the machine.

`shards=N` (N > 1, a fleet): N relays, each on its own temp dir `tmp/sNN/` (DB,
sessions, secrets, off-host log), port, process group and SESSION_SECRET;
`apps` lists the shard indexes that also get a `next dev` (own NEXT_DIST_DIR
`.next/slop-sNN`, own port). `relay_env[i]` / `app_env[i]` are extra env the
caller fills in before `__enter__` (e.g. FLEET_SECRET, FLEET_PEERS from
lib/edge.py). `shards=1` is the stack as before.

`boxes={"b1": (0, 1), "b2": (2,)}` (a two-box fleet, lib/box.py): each shard's
dir is a box's real layout, `tmp/<box>/shards/sNN/` with `data/chatterly.db`,
`service/` (DEMO_SHOTS_TMP: sessions/, secrets/) and `.env` (the shard's
SESSION_SECRET / CHATTER_SESSION_SECRET, as fleet.py's deploy writes it), so the
box-side scripts (oi-backup, oi-restore, oi-epoch) run on it unchanged.
`app_mode="prod"` (a scenario's `APP_MODE`) serves the app as production does instead of
`next dev`: `next build` into `.next/slop-prod` with the run's RELAY_URL (the rewrites are
baked into the build's routes-manifest), then `next start`; minified, split chunks, so a
page-load measurement sees the bundle a phone downloads. One shard only.

`spawn()` / `wait_ready()` / `kill_group()` let a scenario start a relay
elsewhere (a restored shard on the other box) and SIGKILL a process group.

`SLOP_PY` overrides the Python that runs the relay (default the repo venv), so
the harness also runs inside the relay image (deploy/fleet/calibrate.sh).
"""
from __future__ import annotations

import fcntl
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PY = Path(os.environ.get("SLOP_PY") or ROOT / "venv/bin/python")
DEMO = ROOT / "scripts/demo-shots"
RESTORE = ("tsconfig.json", "next-env.d.ts")
APP_LOCK = ROOT / "app/.next/slop.lock"


def _lock_app() -> int:
    """One stack with `next dev` per checkout: they share app/.next/slop* and
    rewrite (and restore) app/tsconfig.json and next-env.d.ts, so a second one
    breaks the first (measured: a concurrent fleet-200 run's `next dev s01`
    exited). An flock, so a killed run never leaves it held. Returns the fd."""
    APP_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(APP_LOCK, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.pread(fd, 512, 0).decode(errors="replace").strip() or "unknown"
        os.close(fd)
        raise SystemExit(f"slop: another slop stack with `next dev` is running in this checkout ({holder}); "
                         f"they share app/.next and app/tsconfig.json. Run one at a time, or wait ({APP_LOCK}).")
    os.ftruncate(fd, 0)
    os.pwrite(fd, f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}: {' '.join(sys.argv)}\n".encode(), 0)
    return fd


def _ports(n: int) -> list[int]:
    ss = [socket.socket() for _ in range(n)]
    for s in ss:
        s.bind(("127.0.0.1", 0))
    out = [s.getsockname()[1] for s in ss]
    for s in ss:
        s.close()
    return out


def sid(i: int) -> str:
    """Shard id of shard index i: s01, s02, ..."""
    return f"s{i + 1:02d}"


class Stack:
    def __init__(self, *, ui: bool, fault: str | None, logdir: Path, profile: bool = False,
                 shards: int = 1, apps: tuple[int, ...] = (), boxes: dict[str, tuple[int, ...]] | None = None,
                 shards_per_box: int | None = None, app_mode: str = "dev"):
        self.ui, self.fault, self.logdir, self.profile = ui, fault, logdir, profile
        if app_mode not in ("dev", "prod") or (app_mode == "prod" and shards > 1):
            raise SystemExit(f"slop: app_mode {app_mode!r} (dev, or prod on one shard)")
        self.app_mode = app_mode
        self.shards = max(1, int(shards))
        fleet = self.shards > 1
        self.apps = tuple(sorted({i for i in apps if 0 <= i < self.shards})) if fleet else ((0,) if ui else ())
        self.tmp = Path(tempfile.mkdtemp(prefix="slop."))
        self.procs: list[subprocess.Popen] = []
        ports = _ports(2 * self.shards + 1)
        self.relay_ports, self.app_ports, dead = ports[:self.shards], ports[self.shards:-1], ports[-1]
        self.shard_ids = [sid(i) for i in range(self.shards)]
        self.shard_urls = [f"http://127.0.0.1:{p}" for p in self.relay_ports]
        self.boxes = {b: tuple(ix) for b, ix in (boxes or {}).items()} if fleet else {}
        self.shards_per_box = shards_per_box
        self.shard_box = {i: b for b, ix in self.boxes.items() for i in ix}
        if self.boxes and sorted(self.shard_box) != list(range(self.shards)):
            raise SystemExit(f"slop: boxes {self.boxes} must place each of the {self.shards} shards exactly once")
        if self.boxes:  # a box's real layout (deploy/fleet: /opt/oi/shards/sNN/{data,service,.env})
            self.shard_tmps = [self.box_root(self.shard_box[i]) / "shards" / s for i, s in enumerate(self.shard_ids)]
            self.shard_dbs = [t / "data" / "chatterly.db" for t in self.shard_tmps]
            self.shard_svc = [t / "service" for t in self.shard_tmps]
        else:
            self.shard_tmps = [self.tmp / s for s in self.shard_ids] if fleet else [self.tmp]
            self.shard_dbs = [t / "relay.db" for t in self.shard_tmps]
            self.shard_svc = list(self.shard_tmps)
        self.shard_sessions = [t / "sessions" for t in self.shard_svc]
        self.offhost_dirs = list(self.shard_svc)  # DEMO_SHOTS_TMP of every relay ever started (spawn() adds)
        self.app_urls = {i: f"http://127.0.0.1:{self.app_ports[i]}" for i in self.apps}
        self.relay_env: dict[int, dict[str, str]] = {i: {} for i in range(self.shards)}
        self.app_env: dict[int, dict[str, str]] = {i: {} for i in self.apps}
        self.shard_pids: list[int] = []
        self._relay_envs: list[dict[str, str]] = []
        # shard 0 under the names a one-relay scenario uses
        self.relay, self.db, self.sessions = self.shard_urls[0], self.shard_dbs[0], self.shard_sessions[0]
        self.app = self.app_urls.get(0) if not fleet and ui else None
        self._relay_port, self._dead = self.relay_ports[0], dead
        self._lock: int | None = None

    def box_root(self, box: str) -> Path:
        """A box's /opt/oi (boxes= runs)."""
        return self.tmp / box

    def _log(self, kind: str, i: int) -> str:
        return f"{kind}.log" if self.shards == 1 else f"{kind}-{self.shard_ids[i]}.log"

    def __enter__(self) -> "Stack":
        if not PY.exists():
            raise SystemExit(f"slop: {PY} not found (needs the repo venv: uvicorn, FastAPI, Playwright; or SLOP_PY)")
        if (ROOT / "service/secrets.json").exists() and not (ROOT / "service/secrets/secrets.json").exists():
            raise SystemExit("slop: service/secrets.json without service/secrets/secrets.json; see docs/ui-shots.md")
        if self.apps:  # only `next dev` rewrites these
            self._lock = _lock_app()
            for f in RESTORE:     # a fresh worktree has no next-env.d.ts until `next` writes one
                if (ROOT / "app" / f).exists():
                    shutil.copy(ROOT / "app" / f, self.tmp / f"{f}.orig")
        self.logdir.mkdir(parents=True, exist_ok=True)
        base = {k: v for k, v in os.environ.items() if k != "OPENINFLOWW_LEGACY_AUTOMATIONS"}
        waits = []
        for i in range(self.shards):
            t, db, svc = self.shard_tmps[i], self.shard_dbs[i], self.shard_svc[i]
            for d in (t, db.parent, svc):
                d.mkdir(parents=True, exist_ok=True)
            tag = "" if self.shards == 1 else f"-{self.shard_ids[i]}"
            env = dict(base)
            env.update(
                DATABASE_URL=f"sqlite+aiosqlite:///{db}", CHATTERLY_DB_URL=f"sqlite:///{db}",
                CHATTERLY_TEST_MODE="1", SHARE_TOKEN="",
                SESSION_SECRET=f"slop-session{tag}-not-for-prod",
                CHATTER_SESSION_SECRET=f"slop-chatter{tag}-not-for-prod",
                ADMIN_PASSWORD="slop-admin-not-for-prod", DEEPSEEK_API_KEY="slop-fake",
                DEEPINFRA_API_KEY="slop-fake", GOOGLE_DRIVE_API_KEY="slop-fake",
                DEMO_SHOTS_ROOT=str(ROOT), DEMO_SHOTS_TMP=str(svc), DEMO_SHOTS_RELAY_PORT=str(self.relay_ports[i]),
                SLOP_FAULT=self.fault or "", SLOP_PROFILE="1" if self.profile else "",
                # TypeSafe answers from the relay's loopback fake when a flow's relay plugin
                # (lib/<flow>_relay.py) serves one, as DeepSeek does (the plugin points it there).
                TYPESAFE_API_KEY="slop-fake", TYPESAFE_BASE_URL=f"{self.shard_urls[i]}/__slop/fake/typesafe",
                # The Dockerfile's: on SIGTERM open streams (/events) are cut after 5 s and the
                # shutdown hook runs (lib/relay.py passes it to uvicorn.run).
                UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN="5",
            )
            if os.environ.get("SLOP_LIVE") == "1":
                # A declared live single run (README "Live runs"): the real TypeSafe
                # and DeepSeek with the caller's test keys, the guard opened to those
                # two names only; nothing else changes.
                env.update(DEMO_SHOTS_ALLOW_HOSTS="api.typesafe.ai,api.deepseek.com", SLOP_LIVE="1",
                           DEEPSEEK_API_KEY=os.environ.get("DEEPSEEK_API_KEY", ""),
                           TYPESAFE_API_KEY=os.environ.get("TYPESAFE_API_KEY", ""))
                env.pop("TYPESAFE_BASE_URL", None)
            env.update(self.relay_env.get(i, {}))
            self._relay_envs.append(env)
            if self.boxes:  # what deploy's shard .env carries (and restic backs up)
                (t / ".env").write_text("".join(f"{k}={env[k]}\n" for k in ("SESSION_SECRET", "CHATTER_SESSION_SECRET")))
            p = self._spawn([str(PY), str(Path(__file__).with_name("relay.py"))], env, self._log("relay", i), cwd=ROOT)
            self.shard_pids.append(p.pid)
            waits.append((f"relay {self.shard_ids[i]}" if self.shards > 1 else "relay",
                          f"{self.shard_urls[i]}/livez", 60 if self.shards == 1 else 180, p))
        dead = f"http://127.0.0.1:{self._dead}"
        try:
            for i in self.apps:
                dist = ".next/slop" if self.shards == 1 else f".next/slop-{self.shard_ids[i]}"
                nenv = dict(os.environ, RELAY_URL=self.shard_urls[i], NEXT_DIST_DIR=dist, NEXT_TELEMETRY_DISABLED="1",
                            HTTP_PROXY=dead, HTTPS_PROXY=dead, http_proxy=dead, https_proxy=dead,
                            NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
                            NODE_OPTIONS=f"--require {DEMO / 'fetch-guard.cjs'}", DEMO_SHOTS_TMP=str(self.shard_tmps[i]))
                nenv.update(self.app_env.get(i, {}))
                if self.app_mode == "prod":
                    self._prod_app(nenv, i)
                    continue
                p = self._spawn(["node", "node_modules/next/dist/bin/next", "dev", "--webpack", "-H", "127.0.0.1",
                                 "-p", str(self.app_ports[i])], nenv, self._log("next", i), cwd=ROOT / "app")
                # One `next dev` at a time: each compiles /login on its first request, and three
                # compiling at once beside ten booting relays missed 300 s (fleet-200 under
                # `slop/run all`: 20261026T000937Z-2026-10-24-fleet-200-bdc0, s02 ReadTimeout).
                self._wait(f"next dev {self.shard_ids[i]}" if self.shards > 1 else "next dev",
                           f"{self.app_urls[i]}/login", 300, p)
            # /livez, not /health: /health is 503 until an OF account is loaded, which a slop stack never has.
            for name, url, timeout, p in waits:
                self._wait(name, url, timeout, p)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    @property
    def relay_pid(self) -> int:
        """Shard 0's relay; also its process group id (start_new_session)."""
        return self.shard_pids[0]

    def crash_relay(self, i: int = 0) -> float:
        """SIGKILL relay `i`'s process group (no shutdown hook runs: what it held in
        memory is gone, as in an OOM kill or a host reboot). Returns the epoch time."""
        return self.kill_group(self.shard_pids[i])

    def stop_relay(self, i: int = 0, grace_s: float = 75.0) -> tuple[float, float | None]:
        """SIGTERM relay `i`'s process group, as `docker stop` does, and wait up to
        `grace_s` (docker-compose.yml's stop_grace_period) for it to exit; past that
        SIGKILL, as docker does. Returns (epoch time of the SIGTERM, seconds until
        it exited, or None when it had to be killed)."""
        pid, t = self.shard_pids[i], time.time()
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        p = next((p for p in self.procs if p.pid == pid), None)
        took: float | None = None
        if p is not None:
            try:
                p.wait(timeout=grace_s)
                took = time.time() - t
            except subprocess.TimeoutExpired:
                self.kill_group(pid)
                return t, None
            self.procs.remove(p)
        return t, took

    def kill_group(self, pid: int) -> float:
        """SIGKILL the process group `pid` leads (one this stack spawned); reaped. Returns the epoch time."""
        t = time.time()
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        p = next((p for p in self.procs if p.pid == pid), None)
        if p is not None:
            p.wait(timeout=10)
            self.procs.remove(p)
        return t

    def relay_cmd(self) -> list[str]:
        return [str(PY), str(Path(__file__).with_name("relay.py"))]

    def _prod_app(self, nenv: dict[str, str], i: int) -> None:
        """`next build` (the Dockerfile's `pnpm build`) into .next/slop-prod against this run's relay,
        then `next start` (its `pnpm start`). The build's wall time lands in next-build.log."""
        nenv = dict(nenv, NEXT_DIST_DIR=".next/slop-prod", NODE_ENV="production")
        nm = ROOT / "app" / "node_modules"
        if nm.is_symlink():  # a worktree's `slop/run --list` link: Turbopack refuses one pointing out of the project
            raise SystemExit(f"slop: APP_MODE=prod builds with Turbopack (as `pnpm build`), which refuses a symlinked "
                             f"app/node_modules; replace the link with an APFS clone: rm {nm} && cp -cR {nm.resolve()} {nm}")
        t0 = time.time()
        # `next build` adds its dist dir's type paths to tsconfig.json and rewrites next-env.d.ts: put both back.
        kept = {f: f.read_bytes() for f in (ROOT / "app" / "tsconfig.json", ROOT / "app" / "next-env.d.ts") if f.exists()}
        try:
            with open(self.logdir / "next-build.log", "w") as fh:
                r = subprocess.run(["node", "node_modules/next/dist/bin/next", "build", "--turbopack"], env=nenv,
                                   cwd=ROOT / "app", stdout=fh, stderr=subprocess.STDOUT, timeout=900)
                fh.write(f"\nslop: next build exit {r.returncode} in {time.time() - t0:.1f}s\n")
        finally:
            for f, b in kept.items():
                f.write_bytes(b)
        if r.returncode != 0:
            raise SystemExit(f"slop: next build failed (exit {r.returncode}); see {self.logdir}/next-build.log")
        p = self._spawn(["node", "node_modules/next/dist/bin/next", "start", "-H", "127.0.0.1",
                         "-p", str(self.app_ports[i])], nenv, self._log("next", i), cwd=ROOT / "app")
        self._wait("next start", f"{self.app_urls[i]}/login", 120, p)

    def relay_env_of(self, i: int) -> dict[str, str]:
        """A copy of the env relay `i` was started with (to start it elsewhere with changes)."""
        return dict(self._relay_envs[i])

    def spawn(self, cmd: list[str], env: dict[str, str], log: str, *, mode: str = "a") -> subprocess.Popen:
        """Start a process in its own group, logging to the run folder; torn down with the stack."""
        if env.get("DEMO_SHOTS_TMP"):
            d = Path(env["DEMO_SHOTS_TMP"])
            if d not in self.offhost_dirs:
                self.offhost_dirs.append(d)
        return self._spawn(cmd, env, log, cwd=ROOT, mode=mode)

    def wait_ready(self, name: str, url: str, timeout: int, proc: subprocess.Popen) -> None:
        self._wait(name, url, timeout, proc)

    def start_relay(self, i: int = 0, timeout: int = 60) -> None:
        """Start relay `i` again on the same DB, port and env; its log appends to relay.log."""
        p = self._spawn([str(PY), str(Path(__file__).with_name("relay.py"))], self._relay_envs[i],
                        self._log("relay", i), cwd=ROOT, mode="a")
        self.shard_pids[i] = p.pid
        self._wait(f"relay {self.shard_ids[i]}", f"{self.shard_urls[i]}/livez", timeout, p)

    def _spawn(self, cmd, env, log, cwd, mode: str = "w") -> subprocess.Popen:
        fh = open(self.logdir / log, mode)
        p = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        return p

    def _wait(self, name: str, url: str, timeout: int, proc: subprocess.Popen) -> None:
        """Ready = an HTTP answer below 500 (a 5xx while booting is not ready)."""
        t0, last = time.time(), "no answer"
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                raise SystemExit(f"slop: {name} exited during startup; see {self.logdir}")
            try:
                r = httpx.get(url, timeout=60)
                if r.status_code < 500:
                    return
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = type(e).__name__
            time.sleep(1)
        raise SystemExit(f"slop: {name} not ready at {url} after {timeout}s (last: {last}); see {self.logdir}")

    def __exit__(self, *exc) -> None:
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):  # macOS: EPERM for a group of zombies
                pass
        deadline = time.time() + 10
        for p in self.procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        for f in RESTORE:
            orig = self.tmp / f"{f}.orig"
            cur = ROOT / "app" / f
            if not self.apps:
                break                             # no next dev: nothing was saved or rewritten
            if not orig.exists():
                cur.unlink(missing_ok=True)       # it was absent: leave it absent
            elif not cur.exists() or orig.read_bytes() != cur.read_bytes():
                shutil.copy(orig, cur)
        refused = b"".join(p.read_bytes() for t in self.offhost_dirs if (p := t / "server-offhost.jsonl").exists())
        if refused or (self.tmp / "server-offhost.jsonl").exists():
            (self.logdir / "relay-offhost-refused.jsonl").write_bytes(refused)
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._lock is not None:
            os.close(self._lock)  # releases the flock
            self._lock = None
