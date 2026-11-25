from __future__ import annotations

import contextlib
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
from slop.lib import recovery, selection

ROOT = Path(__file__).resolve().parents[2]
PY = Path(os.environ.get("SLOP_PY") or ROOT / "venv/bin/python")
DEMO = ROOT / "scripts/demo-shots"
RESTORE = recovery.APP_FILES
APP_LOCK = ROOT / recovery.APP_LOCK
APP_STATE = ROOT / recovery.APP_STATE



def _lock_app() -> int:
    # shared app/.next/slop* and tsconfig rewrites: a second `next dev` stack breaks the first (measured)
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
    return f"s{i + 1:02d}"


class Stack:
    def __init__(self, *, ui: bool, fault: str | None, logdir: Path, profile: bool = False,
                 shards: int = 1, apps: tuple[int, ...] = (), boxes: dict[str, tuple[int, ...]] | None = None,
                 shards_per_box: int | None = None, app_mode: str = "dev",
                 sidecars: dict[str, tuple[str, str, str]] | None = None):
        self.ui, self.fault, self.logdir, self.profile = ui, fault, logdir, profile
        self.sidecars = sidecars or {}
        self.sidecar_procs: dict[str, subprocess.Popen] = {}
        if app_mode not in ("dev", "prod") or (app_mode == "prod" and shards > 1):
            raise SystemExit(f"slop: app_mode {app_mode!r} (dev, or prod on one shard)")
        self.app_mode = app_mode
        self.shards = max(1, int(shards))
        recovery.sweep()
        self._run_state = recovery.RunState()
        self._app_files = recovery.AppFiles(ROOT / "app", RESTORE, APP_STATE)
        fleet = self.shards > 1
        self.apps = tuple(sorted({i for i in apps if 0 <= i < self.shards})) if fleet else ((0,) if ui else ())
        self.tmp = Path(tempfile.mkdtemp(prefix="slop."))
        self.procs: list[subprocess.Popen] = []
        port_names = tuple(dict.fromkeys((p for _, p, _ in self.sidecars.values())))
        ports = _ports(2 * self.shards + 1 + len(port_names))
        self.relay_ports, self.app_ports, dead = ports[:self.shards], ports[self.shards:2 * self.shards], ports[2 * self.shards]
        self.extra_ports = dict(zip(port_names, ports[2 * self.shards + 1:]))
        self.shard_ids = [sid(i) for i in range(self.shards)]
        self.shard_urls = [f"http://127.0.0.1:{p}" for p in self.relay_ports]
        self.boxes = {b: tuple(ix) for b, ix in (boxes or {}).items()} if fleet else {}
        self.shards_per_box = shards_per_box
        self.shard_box = {i: b for b, ix in self.boxes.items() for i in ix}
        if self.boxes and sorted(self.shard_box) != list(range(self.shards)):
            raise SystemExit(f"slop: boxes {self.boxes} must place each of the {self.shards} shards exactly once")
        if self.boxes:
            self.shard_tmps = [self.box_root(self.shard_box[i]) / "shards" / s for i, s in enumerate(self.shard_ids)]
            self.shard_dbs = [t / "data" / "chatterly.db" for t in self.shard_tmps]
            self.shard_svc = [t / "service" for t in self.shard_tmps]
        else:
            self.shard_tmps = [self.tmp / s for s in self.shard_ids] if fleet else [self.tmp]
            self.shard_dbs = [t / "relay.db" for t in self.shard_tmps]
            self.shard_svc = list(self.shard_tmps)
        self.shard_sessions = [t / "sessions" for t in self.shard_svc]
        self.offhost_dirs = list(self.shard_svc)
        self.app_urls = {i: f"http://127.0.0.1:{self.app_ports[i]}" for i in self.apps}
        self.relay_env: dict[int, dict[str, str]] = {i: {} for i in range(self.shards)}
        self.app_env: dict[int, dict[str, str]] = {i: {} for i in self.apps}
        self.shard_pids: list[int] = []
        self._relay_envs: list[dict[str, str]] = []
        self.relay, self.db, self.sessions = self.shard_urls[0], self.shard_dbs[0], self.shard_sessions[0]
        self.app = self.app_urls.get(0) if not fleet and ui else None
        self._relay_port, self._dead = self.relay_ports[0], dead
        self._lock: int | None = None
        self.waits: list[dict] = []
        self.teardown_s: float | None = None

    def box_root(self, box: str) -> Path:
        return self.tmp / box

    def _log(self, kind: str, i: int) -> str:
        return f"{kind}.log" if self.shards == 1 else f"{kind}-{self.shard_ids[i]}.log"

    def __enter__(self) -> "Stack":
        if not PY.exists():
            raise SystemExit(f"slop: {PY} not found (needs the repo venv: uvicorn, FastAPI, Playwright; or SLOP_PY)")
        if (ROOT / "service/secrets.json").exists() and not (ROOT / "service/secrets/secrets.json").exists():
            raise SystemExit("slop: service/secrets.json without service/secrets/secrets.json; see docs/ui-shots.md")
        try:
            self._start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _start(self) -> None:
        if self.apps:
            self._lock = _lock_app()
            self._app_files.save()
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
                TYPESAFE_API_KEY="slop-fake", TYPESAFE_BASE_URL=f"{self.shard_urls[i]}/__slop/fake/typesafe",
                UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN="5",
            )
            if os.environ.get("SLOP_LIVE") == "1":
                env.update(DEMO_SHOTS_ALLOW_HOSTS="api.typesafe.ai,api.deepseek.com", SLOP_LIVE="1",
                           DEEPSEEK_API_KEY=os.environ.get("DEEPSEEK_API_KEY", ""),
                           HELP_ASSISTANT_DEEPSEEK_KEY=os.environ.get("DEEPSEEK_API_KEY", ""),
                           TYPESAFE_API_KEY=os.environ.get("TYPESAFE_API_KEY", ""))
                env.pop("TYPESAFE_BASE_URL", None)
            env.update(self.relay_env.get(i, {}))
            self._relay_envs.append(env)
            if self.boxes:
                (t / ".env").write_text("".join(f"{k}={env[k]}\n" for k in ("SESSION_SECRET", "CHATTER_SESSION_SECRET")))
            p = self._spawn(self.py_cmd("slop/lib/relay.py"), env, self._log("relay", i), cwd=ROOT)
            self.shard_pids.append(p.pid)
            # /livez, not /health: /health is 503 until an OF account is loaded, which a slop stack never has
            waits.append((f"relay {self.shard_ids[i]}" if self.shards > 1 else "relay",
                          f"{self.shard_urls[i]}/livez", 60 if self.shards == 1 else 180, p))
        dead = f"http://127.0.0.1:{self._dead}"
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
            # one `next dev` at a time: three compiling /login at once beside ten booting relays missed 300 s
            self._wait(f"next dev {self.shard_ids[i]}" if self.shards > 1 else "next dev",
                       f"{self.app_urls[i]}/login", 300, p, app=True)
        for name, url, timeout, p in waits:
            self._wait(name, url, timeout, p)
        for name in self.sidecars:
            self.start_sidecar(name, mode="w")

    @property
    def relay_pid(self) -> int:
        return self.shard_pids[0]

    def crash_relay(self, i: int = 0) -> float:
        return self.kill_group(self.shard_pids[i])

    def stop_relay(self, i: int = 0, grace_s: float = 75.0) -> tuple[float, float | None]:
        pid = self.shard_pids[i]
        return self._stop_proc(pid, grace_s)

    def _stop_proc(self, pid: int, grace_s: float) -> tuple[float, float | None]:
        t = time.time()
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        took: float | None = None
        p = next((p for p in self.procs if p.pid == pid), None)
        if p is not None:
            try:
                p.wait(timeout=grace_s)
                took = time.time() - t
            except subprocess.TimeoutExpired:
                self.kill_group(pid)
                return t, None
            if p in self.procs:
                self.procs.remove(p)
        return t, took

    def kill_group(self, pid: int) -> float:
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

    def py_cmd(self, script: str) -> list[str]:
        relay = str(ROOT / script)
        cov = os.environ.get("SLOP_COVERAGE")
        if not cov:
            return [str(PY), relay]
        return [str(PY), "-m", "coverage", "run", "--parallel-mode", f"--data-file={cov}/.coverage",
                f"--source={','.join(str(ROOT / r) for r in selection.PY_ROOTS)}",
                f"--omit={ROOT / 'slop/evidence'}/*", relay]

    def relay_cmd(self) -> list[str]:
        return self.py_cmd("slop/lib/relay.py")

    def _prod_app(self, nenv: dict[str, str], i: int) -> None:
        nenv = dict(nenv, NEXT_DIST_DIR=".next/slop-prod", NODE_ENV="production")
        t0 = time.time()
        build = self._spawn(["node", "node_modules/next/dist/bin/next", "build", "--turbopack"], nenv,
                            "next-build.log", cwd=ROOT / "app")
        deadline = time.monotonic() + 900
        try:
            while build.poll() is None:
                if self._lock is not None:
                    self._app_files.note_written()
                if time.monotonic() > deadline:
                    self.kill_group(build.pid)
                    build.wait()
                    raise SystemExit(f"slop: next build not done after 900s; see {self.logdir}/next-build.log")
                time.sleep(0.5)
        finally:
            if self._lock is not None:
                self._app_files.note_written()
        with open(self.logdir / "next-build.log", "a") as fh:
            fh.write(f"\nslop: next build exit {build.returncode} in {time.time() - t0:.1f}s\n")
        r = build
        if r.returncode != 0:
            raise SystemExit(f"slop: next build failed (exit {r.returncode}); see {self.logdir}/next-build.log")
        p = self._spawn(["node", "node_modules/next/dist/bin/next", "start", "-H", "127.0.0.1",
                         "-p", str(self.app_ports[i])], nenv, self._log("next", i), cwd=ROOT / "app")
        self._wait("next start", f"{self.app_urls[i]}/login", 120, p, app=True)

    def relay_env_of(self, i: int) -> dict[str, str]:
        return dict(self._relay_envs[i])

    def spawn(self, cmd: list[str], env: dict[str, str], log: str, *, mode: str = "a") -> subprocess.Popen:
        if env.get("DEMO_SHOTS_TMP"):
            d = Path(env["DEMO_SHOTS_TMP"])
            if d not in self.offhost_dirs:
                self.offhost_dirs.append(d)
        return self._spawn(cmd, env, log, cwd=ROOT, mode=mode)

    def wait_ready(self, name: str, url: str, timeout: int, proc: subprocess.Popen) -> None:
        self._wait(name, url, timeout, proc)

    def start_relay(self, i: int = 0, timeout: int = 60) -> None:
        p = self._spawn(self.relay_cmd(), self._relay_envs[i],
                        self._log("relay", i), cwd=ROOT, mode="a")
        self.shard_pids[i] = p.pid
        self._wait(f"relay {self.shard_ids[i]}", f"{self.shard_urls[i]}/livez", timeout, p)

    def stop_sidecar(self, name: str, grace_s: float = 45.0) -> tuple[float, float | None]:
        p = self.sidecar_procs[name]
        return self._stop_proc(p.pid, grace_s)

    def start_sidecar(self, name: str, timeout: int = 60, *, mode: str = "a") -> None:
        script, port_env, health = self.sidecars[name]
        env = dict(self._relay_envs[0], **{port_env: str(self.extra_ports[port_env])})
        p = self._spawn(self.py_cmd(script), env, self._log(name, 0), cwd=ROOT, mode=mode)
        self.sidecar_procs[name] = p
        self._wait(name, f"http://127.0.0.1:{self.extra_ports[port_env]}{health}", timeout, p)

    def _spawn(self, cmd, env, log, cwd, mode: str = "w") -> subprocess.Popen:
        fh = open(self.logdir / log, mode)
        p = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        self._run_state.record(p.pid)
        return p

    def _wait(self, name: str, url: str, timeout: int, proc: subprocess.Popen, *, app: bool = False) -> None:
        last, m0, polls, delay = "no answer", time.monotonic(), 0, 0.1
        deadline, note = m0 + timeout, app and self._lock is not None
        try:
            while (left := deadline - time.monotonic()) > 0:
                if note:
                    self._app_files.note_written()
                if proc.poll() is not None:
                    raise SystemExit(f"slop: {name} exited during startup; see {self.logdir}")
                try:
                    polls += 1
                    r = httpx.get(url, timeout=min(60.0, left))
                    if r.status_code < 500:
                        return
                    last = f"HTTP {r.status_code}"
                except httpx.HTTPError as e:
                    last = type(e).__name__
                time.sleep(max(0.0, min(delay, deadline - time.monotonic())))
                delay = min(delay * 2, 1.0)
            raise SystemExit(f"slop: {name} not ready at {url} after {timeout}s (last: {last}); see {self.logdir}")
        finally:
            if note:
                self._app_files.note_written()
            self.waits.append({"name": name, "seconds": round(time.monotonic() - m0, 3), "polls": polls})

    def __exit__(self, *exc) -> None:
        t0 = time.monotonic()
        # only unreaped leaders: a reaped leader's pid may lead someone else's group by now
        procs = [p for p in self.procs if p.poll() is None]
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):  # macOS: EPERM for a group of zombies
                pass
        deadline = time.time() + (45 if self.sidecars else 10)
        for p in procs:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.wait(timeout=5)
        left = recovery.kill_groups(self._run_state.groups)
        if left:
            print(f"slop: WARN {len(left)} process group(s) of this run survived SIGKILL "
                  f"({', '.join(str(g['pid']) for g in left)}); kept for the next Stack's sweep", file=sys.stderr)
        if self._lock is not None:
            self._app_files.restore()
        refused = b"".join(p.read_bytes() for t in self.offhost_dirs if (p := t / "server-offhost.jsonl").exists())
        if refused or (self.tmp / "server-offhost.jsonl").exists():
            (self.logdir / "relay-offhost-refused.jsonl").write_bytes(refused)
        shutil.rmtree(self.tmp, ignore_errors=True)
        self._run_state.close(left)
        self.procs = []
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None
        self.teardown_s = round(time.monotonic() - t0, 3)
