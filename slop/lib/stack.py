"""Throwaway local stack per run: the slop relay on a temp SQLite DB and, when a
scenario needs the UI, `next dev` behind demo-shots' fetch guard. Free loopback
ports, own process groups, torn down on exit; app/tsconfig.json and
app/next-env.d.ts (which `next dev` rewrites) are restored. Same safety model as
scripts/demo-shots/run.sh: nothing leaves the machine.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv/bin/python"
DEMO = ROOT / "scripts/demo-shots"
RESTORE = ("tsconfig.json", "next-env.d.ts")


def _ports(n: int) -> list[int]:
    ss = [socket.socket() for _ in range(n)]
    for s in ss:
        s.bind(("127.0.0.1", 0))
    out = [s.getsockname()[1] for s in ss]
    for s in ss:
        s.close()
    return out


class Stack:
    def __init__(self, *, ui: bool, fault: str | None, logdir: Path, profile: bool = False):
        self.ui, self.fault, self.logdir, self.profile = ui, fault, logdir, profile
        self.tmp = Path(tempfile.mkdtemp(prefix="slop."))
        self.procs: list[subprocess.Popen] = []
        relay_port, app_port, dead = _ports(3)
        self.relay = f"http://127.0.0.1:{relay_port}"
        self.app = f"http://127.0.0.1:{app_port}" if ui else None
        self._relay_port, self._app_port, self._dead = relay_port, app_port, dead
        self.db = self.tmp / "relay.db"
        self.sessions = self.tmp / "sessions"
        self.relay_env: dict[str, str] = {}  # extra relay env set before __enter__ (cli: OF_WIRE's OF_API_ORIGIN)

    def __enter__(self) -> "Stack":
        if not PY.exists():
            raise SystemExit(f"slop: {PY} not found (needs the repo venv: uvicorn, FastAPI, Playwright)")
        if (ROOT / "service/secrets.json").exists() and not (ROOT / "service/secrets/secrets.json").exists():
            raise SystemExit("slop: service/secrets.json without service/secrets/secrets.json; see docs/ui-shots.md")
        for f in RESTORE:
            shutil.copy(ROOT / "app" / f, self.tmp / f"{f}.orig")
        self.logdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "OPENINFLOWW_LEGACY_AUTOMATIONS"}
        env.update(
            DATABASE_URL=f"sqlite+aiosqlite:///{self.db}", CHATTERLY_DB_URL=f"sqlite:///{self.db}",
            CHATTERLY_TEST_MODE="1", SHARE_TOKEN="",
            SESSION_SECRET="slop-session-not-for-prod", CHATTER_SESSION_SECRET="slop-chatter-not-for-prod",
            ADMIN_PASSWORD="slop-admin-not-for-prod", DEEPSEEK_API_KEY="slop-fake",
            DEEPINFRA_API_KEY="slop-fake", GOOGLE_DRIVE_API_KEY="slop-fake",
            DEMO_SHOTS_ROOT=str(ROOT), DEMO_SHOTS_TMP=str(self.tmp), DEMO_SHOTS_RELAY_PORT=str(self._relay_port),
            SLOP_FAULT=self.fault or "", SLOP_PROFILE="1" if self.profile else "",
            # The Dockerfile's: on SIGTERM open streams (/events) are cut after 5 s and the
            # shutdown hook runs (lib/relay.py passes it to uvicorn.run).
            UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN="5",
        )
        env.update(self.relay_env)
        self._relay_env = env
        self._relay = self._spawn([str(PY), str(Path(__file__).with_name("relay.py"))], env, "relay.log", cwd=ROOT)
        app = None
        if self.ui:
            dead = f"http://127.0.0.1:{self._dead}"
            nenv = dict(os.environ, RELAY_URL=self.relay, NEXT_DIST_DIR=".next/slop", NEXT_TELEMETRY_DISABLED="1",
                        HTTP_PROXY=dead, HTTPS_PROXY=dead, http_proxy=dead, https_proxy=dead,
                        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
                        NODE_OPTIONS=f"--require {DEMO / 'fetch-guard.cjs'}", DEMO_SHOTS_TMP=str(self.tmp))
            app = self._spawn(["node", "node_modules/next/dist/bin/next", "dev", "--webpack", "-H", "127.0.0.1",
                               "-p", str(self._app_port)], nenv, "next.log", cwd=ROOT / "app")
        try:
            # /livez, not /health: /health is 503 until an OF account is loaded, which a slop stack never has.
            self._wait("relay", f"{self.relay}/livez", 60, self._relay)
            if app is not None:
                self._wait("next dev", f"{self.app}/login", 300, app)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    @property
    def relay_pid(self) -> int:
        """Also the relay's process group id (start_new_session)."""
        return self._relay.pid

    def crash_relay(self) -> float:
        """SIGKILL the relay's process group (no shutdown hook runs: what it held in
        memory is gone, as in an OOM kill or a host reboot). Returns the epoch time."""
        t = time.time()
        os.killpg(self._relay.pid, signal.SIGKILL)
        self._relay.wait(timeout=10)
        self.procs.remove(self._relay)
        return t

    def start_relay(self, timeout: int = 60) -> None:
        """Start the relay again on the same DB, port and env; its log appends to relay.log."""
        self._relay = self._spawn([str(PY), str(Path(__file__).with_name("relay.py"))], self._relay_env,
                                  "relay.log", cwd=ROOT, mode="a")
        self._wait("relay", f"{self.relay}/livez", timeout, self._relay)

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
            if orig.exists() and orig.read_bytes() != (ROOT / "app" / f).read_bytes():
                shutil.copy(orig, ROOT / "app" / f)
        offhost = self.tmp / "server-offhost.jsonl"
        if offhost.exists():
            shutil.copy(offhost, self.logdir / "relay-offhost-refused.jsonl")
        shutil.rmtree(self.tmp, ignore_errors=True)
