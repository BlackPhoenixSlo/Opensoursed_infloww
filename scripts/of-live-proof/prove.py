"""The Live proof driver (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md, "The driver"): one command
starts the loopback stack, runs each selected proof on the running app, and leaves one evidence folder.

  run.sh --of fake [--proof tracer.create-list] [--fault delete-500|lost-reply|cdn-src|trial-delete-500|rename-ignored|
         post-drop-label|post-drop-expiry|post-drop-target|email-off|wrong-creator|
         tip-filter|strip-miss|highlight-field|payout-field|no-stored-order|sort-restore-500|audience-list|
         audience-second|unsend-refused|queue-500-foreign|dup-id-refused|post-commit-500|composer-once|
         publish-other|post-lost-hidden|hidden-refused|publish-lost|publish-500|unsend-delete-500|cotag-extra]
         [--proof-fan <id>|none] [--cotag-partner <id>|none] [--lockout]
  run.sh --of fake capture [--abort] --proof <id>
  run.sh --of live --session-dir <dir> [--proof-fan <id>] [--cotag-partner <id>] [capture [--abort]] --proof <id>
  run.sh --of fake|live [--session-dir <dir>] serve
  run.sh --of fake|live [--session-dir <dir>] reverify --evidence <folder>

Fake mode: soak's FakeOF (fake_layer.py) on loopback; relay_live.py (relay_guarded.py's sandbox + the Live guard)
with OF_API_ORIGIN at it and a session bootstrapped from FakeOF's signed curl; `next dev` under fetch-guard with dead
proxies; Playwright Chromium resolving no name but loopback, aborting and recording every other origin. Everything
runs at nice >= 10.

Live mode and `serve` (ticket 09, live_entry.py): `--of live` refuses to start without `--session-dir`, copies it into
the run's temp dir (never printed, deleted at teardown) and runs the Relay at OnlyFans's own origin with that copy and
the Creator 80000112 linked to a throwaway owner; the capture browser opens on demand only (D27). The
preflight (live_entry `preflight`) refuses the run before any proof on any mismatch. Live mode is built here and never
run unattended (ticket 11). The driver's OnlyFans-side reads (`Stack.of_get`) are a signed GET through the run's own
Relay in both modes (`/__proof/of-read`, origin `driver` in wire.jsonl). `serve` starts the stack, prints the app and
Relay URLs, and waits for SIGINT or SIGTERM before the same teardown.

`reverify` (ticket 67 follow-up, read only): no app, no proof, nothing armed; after the preflight it reads the cover
OnlyFans serves now and compares it with the one an earlier run kept (`--evidence`'s
settings--profile-cover-avatar/undo-3-before.*) by the undo's own rule (undo_driver.reverify). Exit 0 only when it
matches and every harness check held.

Capture browser (ticket 07, of_browser.py, capture.py): opened after preflight when a proof has capture-browser
steps, or for `capture`; signed in from the session in the run's temp dir, every request through the Relay's Live
guard (`/__proof/decide`). `capture` plays one proof's capture steps (no app) and writes the raw capture and its
scrubbed capture record into the evidence folder; `--abort` records the write and aborts it before it leaves, and a
Critical control's capture is refused without it. The run fails when any session value is found in the evidence
folder, the report or the run's own output.

Drills (ticket 04): fake-only proofs that arm a mass message to an OF list and a withdrawal through the Relay's
existing routes, passing only when the Live guard refuses them with their class and FakeOF never sees them; a
fake-only proof selected under --of live refuses the run before anything starts. After every fake run the census
(`proof_core.census`) fails the run on any FakeOF hit that is neither a forwarded wire line nor a tagged harness
read, and on any refused entry among the hits.

Failure paths (ticket 05): a failed undo stops the run (later proofs `<id>: not run`, the FAILED row printed with the
change left); a write whose reply was lost is never retried, found by its proof's `find` in the after-write read and
undone, or its row closes FAILED. One run per Creator holds a lock file in the system temp dir; a stale one (dead
pid) is taken over and reported, and any earlier run's `pending` row (the stale holder's included) refuses every new
run until cleared by hand; under --of live so does an earlier live run's FAILED or not-reversible row (follow-up #6).

Evidence: slop/evidence/<UTC>-ofm-<of>-<sha>/ (screenshots, wire.jsonl, undo-log.jsonl + .md, OnlyFans-side reads,
fake-hits.jsonl, app-offhost.jsonl, report.json + .md, relay.log, next.log). Exit 0 only when every proof passed and
every harness check held.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import capture as capture_cmd  # noqa: E402
import live_entry  # noqa: E402
from of_browser import (LAUNCH_ARGS, AppBrowser, CaptureBrowser, _call_ctx, _dom_snapshot,  # noqa: E402
                        _mirror_frame, _Parked, evidence_texts, hand_off_problems, load_session,
                        session_leaks, session_secrets)
from expects import Park, expect_problems, expect_waits, park_problems, resolve_expects  # noqa: E402
from proof_core import (NOT_REVERSIBLE_REFUSED, census, fake_only_refused, fill_text, order, pace_problems,  # noqa: E402
                        redact_text, step_family, undo_deadline, wire_problems)
from proofs import ALL, ORDER, PENDING  # noqa: E402
from run_lock import _index_path, holds_lock, index_logs, index_update, release_lock, take_lock  # noqa: E402
import undo_driver  # noqa: E402
from ui_steps import click_confirm, collect_tiles, goto_target  # noqa: E402
from undo_log import (append_jsonl, check_undo_log, needs_row_id, pending_rows, read_undo_log,  # noqa: E402
                      reads_equal, undo_markdown, undo_order, unresolved_rows)

NICE = 10
PY = sys.executable
TREES = ("service", "app", "soak")
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _free_ports(n: int) -> list[int]:
    ss = [socket.socket() for _ in range(n)]
    for s in ss:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in ss]
    for s in ss:
        s.close()
    return ports


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def _trees_state() -> str:
    """Status plus the diff of service/, app/, soak/: compared before and after the run."""
    return _git("status", "--porcelain", "--", *TREES) + _git("diff", "--", *TREES)


def _niceness_of_tree(root_pid: int) -> list[dict]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,nice=,comm="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit():
            procs[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    kids, seen = [root_pid], []
    while kids:
        pid = kids.pop()
        for p, (pp, ni, comm) in procs.items():
            if pp == pid:
                seen.append({"pid": p, "nice": ni, "comm": os.path.basename(comm)})
                kids.append(p)
    return seen


def _wait_http(url: str, timeout: float, proc: subprocess.Popen, log: Path, name: str) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with _DIRECT.open(url, timeout=60) as r:
                r.read(1)
                return
        except urllib.error.HTTPError:
            return
        except Exception:  # noqa: BLE001  (not up yet)
            pass
        if proc.poll() is not None:
            break
        time.sleep(1)
    tail = log.read_text(errors="replace").splitlines()[-30:] if log.exists() else []
    raise RuntimeError(f"{name} not ready at {url}:\n" + "\n".join(tail))


class Stack:
    """The loopback stack. `close()` stops everything, restores app/ files and deletes the temp dir.
    `session_src` (live mode): the --session-dir copied into the temp dir, the Relay at OnlyFans's own origin, no
    FakeOF. A stack that fails to start closes itself, so the temp dir (and a session copy) never outlives it."""

    def __init__(self, evidence: Path, fault: str | None = None, app: bool = True, session_src: Path | None = None):
        self.evidence, self.of, self.fake, self.login = evidence, "live" if session_src else "fake", None, None
        self.account = None   # the Creator `bootstrap` binds; `of_get` names it to the Relay
        # ticket 97: an app-side fault (`AppFault`) is the app browser's route hook `app_route`, FakeOF runs
        # unfaulted; each time it fired is kept in `planted` (the fault-fired check)
        self.fault, self.planted, self.app_route = fault, [], None
        self.tmp = Path(tempfile.mkdtemp(prefix="ofm-live-proof."))
        self.procs: list[subprocess.Popen] = []
        self.app_files = {}
        for f in ("tsconfig.json", "next-env.d.ts"):
            p = ROOT / "app" / f
            self.app_files[f] = p.read_bytes() if p.exists() else None
        try:
            self._start(fault, app, session_src)
        except BaseException:
            self.close()
            raise

    def _start(self, fault, app, session_src) -> None:
        if session_src:   # ticket 09: before the Relay starts, so its registry finds the account dir
            live_entry.copy_session(session_src, self.tmp)
        else:
            from fake_layer import FAULTS, AppFault, Fake
            app_side = FAULTS[fault].hook if isinstance(FAULTS.get(fault), AppFault) else None
            self.fake = Fake(seed=1, fault=None if app_side else fault)
            self.app_route = app_side(self.planted) if app_side else None
            if seed := getattr(FAULTS.get(fault), "seed", None):   # ticket 99: the fault's own FakeOF state
                seed(self.fake.of)
            self.fake.start()
        relay_port, app_port, dead_port = _free_ports(3)
        self.relay, self.app = f"http://127.0.0.1:{relay_port}", f"http://127.0.0.1:{app_port}"
        dead = f"http://127.0.0.1:{dead_port}"
        for d in ("home", "tmp", "img", "storyboard", "vault/thumbs", "vault/posters", "vault/images",
                  "vault/spool", "data"):
            (self.tmp / d).mkdir(parents=True, exist_ok=True)
        t = self.tmp
        env = {k: v for k, v in os.environ.items() if k != "OPENINFLOWW_LEGACY_AUTOMATIONS"}
        env.update({
            "DATABASE_URL": f"sqlite+aiosqlite:///{t}/relay.db", "CHATTERLY_DB_URL": f"sqlite:///{t}/relay.db",
            "RELAY_DB_PATH": str(t / "relay.db"), "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
            "SESSION_SECRET": os.urandom(16).hex(), "CHATTER_SESSION_SECRET": os.urandom(16).hex(),
            "ADMIN_PASSWORD": "ofm-live-proof-not-for-prod", "DEEPSEEK_API_KEY": "ofm-live-proof-fake",
            "DEEPINFRA_API_KEY": "ofm-live-proof-fake", "GOOGLE_DRIVE_API_KEY": "ofm-live-proof-fake",
            "DEMO_SHOTS_ROOT": str(ROOT), "DEMO_SHOTS_TMP": str(t), "DEMO_SHOTS_RELAY_PORT": str(relay_port),
            "OFM_PROOF_EVIDENCE": str(self.evidence),
            "OF_API_LOG_PATH": str(t / "of-api.log"), "IMG_CACHE_DIR": str(t / "img"),
            "STORYBOARD_DIR": str(t / "storyboard"), "VAULT_THUMB_DIR": str(t / "vault/thumbs"),
            "VAULT_POSTER_DIR": str(t / "vault/posters"), "VAULT_IMAGE_DIR": str(t / "vault/images"),
            "VAULT_SPOOL_DIR": str(t / "vault/spool"), "LANE_CONFIG_PATH": str(t / "data/lane_config.json"),
            "PRIORITY_LANE_STATS_PATH": str(t / "data/priority_lane_stats.json"),
            "HTTP_PROXY": dead, "HTTPS_PROXY": dead, "http_proxy": dead, "https_proxy": dead,
            "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1",
            "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "TZ": "UTC",
            # the proofs drive the ofm-not-yet controls: their routes stay 404 unless the switch is on (runtime_switches)
            "OFM_NEW_WRITES_ENABLED": "1",
        })
        if self.fake:
            from fake_layer import CDN_HOST
            env.update(OF_API_ORIGIN=self.fake.origin, OFM_FAKE_CDN_HOST=CDN_HOST)
        else:   # live: the Relay's OnlyFans calls leave direct (curl_cffi, under the Live guard); net_guard stays on
            # ASSUMPTION: no proxy means the operator's IP; ADR-0030 (IP change != session loss) is unobserved; ticket 11
            # decides the live egress
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env.pop(k)
        self.relay_log, self.next_log = t / "relay.log", t / "next.log"
        self.procs.append(subprocess.Popen([PY, "-u", str(HERE / "relay_live.py")], env=env, cwd=ROOT,
                                           stdout=open(self.relay_log, "w"), stderr=subprocess.STDOUT,
                                           start_new_session=True))
        nenv = {k: v for k, v in os.environ.items()}
        nenv.update({
            "RELAY_URL": self.relay, "NEXT_DIST_DIR": ".next/ofm-live-proof", "NEXT_TELEMETRY_DISABLED": "1",
            "HTTP_PROXY": dead, "HTTPS_PROXY": dead, "http_proxy": dead, "https_proxy": dead,
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
            "NODE_OPTIONS": f"--require {ROOT / 'scripts/demo-shots/fetch-guard.cjs'}", "DEMO_SHOTS_TMP": str(t),
        })
        node = shutil.which("node") or "node"
        if app:   # `capture` drives no app
            self.procs.append(subprocess.Popen(
                [node, "node_modules/next/dist/bin/next", "dev", "--webpack", "-H", "127.0.0.1", "-p", str(app_port)],
                env=nenv, cwd=ROOT / "app", stdout=open(self.next_log, "w"), stderr=subprocess.STDOUT,
                start_new_session=True))
        _wait_http(f"{self.relay}/health", 90, self.procs[0], self.relay_log, "relay")

    def wait_app(self) -> None:
        _wait_http(f"{self.app}/", 300, self.procs[1], self.next_log, "next dev")

    def session_dir(self, creator: str) -> Path:
        """The Creator's bootstrapped session in the run's temp dir (relay_guarded.py's SESSIONS_DIR)."""
        return self.tmp / "sessions" / "accounts" / creator

    def fake_sign(self, path_qs: str) -> dict:
        """The capture browser's signing in fake mode: FakeOF's signed headers, untagged (the page's own request,
        not the driver's read), plus the build header OnlyFans's web app sends."""
        from fake_layer import TAG
        return {**{k: v for k, v in self.fake.signed_headers(path_qs).items() if k != TAG}, "x-of-rev": self.fake.of.rev}

    def of_get(self, path: str, query: dict) -> dict:
        """The driver's own OnlyFans-side read (story 12, ticket 11), the same path in both modes: one GET to the run's
        Relay (`/__proof/of-read`, relay_live.py), which signs it with the Creator's session in the temp dir, decides
        it under the Live guard and logs it in wire.jsonl with origin `driver` (fake mode: tagged for FakeOF). No
        header, cookie or session value passes here; OnlyFans's JSON comes back as it came.
        ASSUMPTION: fake mode reads through the Relay too, never straight to FakeOF (rung 5: the smallest change that
        lets every fake run drive the live code path); overturned if a fake read's extra wire lines break a check."""
        if not self.account:   # before bootstrap the Relay would fall back to its active account: fail loudly
            raise RuntimeError("of_get before bootstrap: no Creator to read as")
        url = f"{self.relay}/__proof/of-read?" + urlencode({"path": path, "query": urlencode(query)})
        req = urllib.request.Request(url, headers={"X-Account-Id": self.account})
        try:
            with _DIRECT.open(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OnlyFans-side read {path}: the Relay answered {e.code}: "
                               f"{e.read()[:200].decode('utf-8', 'replace')}") from None

    def close(self) -> dict:
        try:
            return self._close()
        finally:   # the temp dir (and a live session copy) goes whatever happened above
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _close(self) -> dict:
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        end = time.time() + 10
        for p in self.procs:
            try:
                p.wait(timeout=max(0.1, end - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if self.fake:
            self.fake.stop()
        for name in ("relay.log", "next.log", "server-offhost.jsonl"):
            if (self.tmp / name).exists():   # copied redacted: a log can hold a presigned URL or an S3 error body
                (self.evidence / name).write_text(
                    redact_text((self.tmp / name).read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        restored = []
        for f, data in self.app_files.items():
            p = ROOT / "app" / f
            now = p.read_bytes() if p.exists() else None
            if now != data:
                if data is None:
                    p.unlink()
                else:
                    p.write_bytes(data)
                restored.append(f"app/{f}")
        shutil.rmtree(self.tmp, ignore_errors=True)   # here too, so the report below sees it gone
        return {"temp_dir": str(self.tmp), "temp_deleted": not self.tmp.exists(), "restored": restored}


def _relay_client(stack: Stack, ab: AppBrowser):
    """`call(method, route, data=None, account=None) -> (status, body)` on the Relay with the owner's cookies, over
    urllib: the forced-undo thread (story 10) cannot use Playwright's sync objects, so the undo path uses this too."""
    cookie = "; ".join(f"{c['name']}={c['value']}" for c in ab.ctx.cookies(stack.relay))

    def call(method, route, data=None, account=None, form=None):
        headers = {"Cookie": cookie} if cookie else {}
        if account:
            headers["X-Account-Id"] = account
        if data is not None:
            headers["Content-Type"] = "application/json"
        payload = json.dumps(data).encode() if data is not None else None
        if form is not None:   # ticket 67: a multipart body, (content type, bytes) as undo_driver.multipart makes it
            headers["Content-Type"], payload = form
        r = urllib.request.Request(stack.relay + route, method=method, headers=headers, data=payload)
        try:
            with _DIRECT.open(r, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    return call


# ticket 67: the "file" trigger step's picture, a synthetic grey 1280x720 PNG (never a real image). Every chunk's CRC
# must hold: OnlyFans's convert answers 400 "Image is corrupted" otherwise (live 2026-11-21, the old hand-typed 1x1).
def _grey_png(w: int, h: int) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = (b"\x00" + b"\x80" * w) * h
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


PIXEL_PNG = _grey_png(1280, 720)


def _pick_file(page, loc, name: str) -> None:
    """Click `loc`, which opens a file picker, and choose PIXEL_PNG as `name` (ticket 67: Edit profile's cameras)."""
    with page.expect_file_chooser(timeout=30_000) as chooser:
        loc.click(timeout=30_000)
    chooser.value.set_files(files=[{"name": name, "mimeType": "image/png", "buffer": PIXEL_PNG}])


def _wait_text(fr, sel: str, want: str, marker: str, proof_fan) -> None:
    """Wait for `want` in `sel`'s text, `{marker}` / `{fan}` filled (`fill_text`); a `{fan}` with no Proof fan is
    refused (it would wait for any text)."""
    if "{fan}" in want and not proof_fan:
        raise ValueError(f"wait for {want!r}: no Proof fan to fill {{fan}}")
    fr.wait_for_function("([s, w]) => (document.querySelector(s)?.textContent || '').includes(w)",
                         arg=[sel, fill_text(want, marker, proof_fan)], polling=50, timeout=30_000)


def run_proof(proof, stack: Stack, ab: AppBrowser, creator: str, evidence: Path, run_id: str,
              proof_fan: str | None = None, cb: CaptureBrowser | None = None, capture_abort: bool = False,
              lockout: bool = False, cotag_partner: str | None = None) -> dict:
    """Steps 2-14 of the driver for one proof. Returns its result; `state` FAILED stops the run.

    Story 10: an allowed write with an undo deadline (`undo_deadline`: delete-at-once, a Scheduled post) is watched
    by a timer thread that forces its after-write read and undo at the deadline, whatever step the proof is on.
    `cb`: the capture browser for `fetch` / `hand-off` steps; a fetch step expected aborted is checked on its own and
    left out of the step-9 window. `capture_abort`: armed in capture-abort mode, and OnlyFans's side must read the
    same after the steps as before. `cotag_partner` (ofm-not-yet ticket 98): the run input naming the Co-tag proofs'
    partner, given to a `call` step as `ctx["cotag_partner"]` (None: they park)."""
    req = ab.ctx.request
    call = _relay_client(stack, ab)
    res = {"proof": proof.id, "problems": [], "screens": []}
    t0 = time.time()   # ticket 98: the proof's own window (`res["t"]`) for harness_checks' read-first check
    marker = f"oi-proof-{run_id}"
    shots = evidence / proof.id
    shots.mkdir(exist_ok=True)

    def read(tag):
        if proof.of_read is None:
            return None
        value = proof.of_read(stack.of_get, proof_fan)
        (evidence / f"of-read-{proof.id}-{tag}.json").write_text(json.dumps(value, indent=1))
        return value

    def wire():
        status, body = call("GET", "/__proof/wire")
        if status != 200:
            raise RuntimeError(f"/__proof/wire answered {status}")
        return json.loads(body)["wire"]

    # ASSUMPTION (ticket 100): a fake run declares its quiet hour as the hour from the run's start, so a fan-visible
    # publish can pass against FakeOF (rung 5: fake mode has no owner to declare one); a live run sends none, and the
    # Relay refuses one armed in any other mode (relay_live `arm`).
    quiet = datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    r = req.post(f"{stack.relay}/__proof/arm", data={"proof": proof.id, "of": stack.of, "proof_fan": proof_fan,
                                                     "capture_abort": capture_abort, "lockout": lockout,
                                                     **({"quiet_hour": quiet} if stack.of == "fake" else {}),
                                                     "cotag_partner": cotag_partner,   # ticket 98: the guard's too
                                                     "marker": marker})   # round 2 #22: payloads bind to this run's
    if not r.ok:
        res["problems"].append(f"arm failed: {r.status} {r.text()[:200]}")
        res["state"] = "FAILED"
        return res
    rows_before = {x["row"] for x in read_undo_log(evidence / "undo-log.jsonl")}

    def mine() -> list:
        return [x for x in read_undo_log(evidence / "undo-log.jsonl")
                if x["row"] not in rows_before and x["proof"] == proof.id]

    before = after = after_undo = effect = None
    keys = {}   # ticket 131: the undo keys registered with the Relay (`register_keys`), shared by the proof's rows
    kept = {}   # ticket 67: the pictures an undo puts back, by undo index (undo_driver.keep)
    lock, stop, done, step_now = threading.RLock(), threading.Event(), set(), ["start"]
    sent = {}   # (Relay method, route) -> its reversal record: an undo request several rows share goes out once

    def find_lost(row):
        """Story 53: a write counted as sent, never retried, its id found by the proof's own finder in the after-write
        read and handed to the Relay; the row as found (unchanged when not: it closes FAILED)."""
        try:
            found = proof.find(before, after_write(), marker) if proof.find else None
        except Exception as e:  # noqa: BLE001  (not found: the row closes FAILED below)
            found = None
            res["problems"].append(f"finding row {row['row']}'s write failed: {type(e).__name__}: {e}")
        if found is None:
            res["problems"].append(f"row {row['row']}: {row['write']['method']} {row['write']['path']} has no "
                                   f"OnlyFans id and {proof.id} " + ("its finder found none in the after-write read"
                                                                      if proof.find else "declares no finder"))
            return row
        status, text = call("POST", "/__proof/found", {"row": row["row"], "of_id": str(found)})
        if status == 200:
            return {**row, "of_id": str(found), "found_by": "after-write read"}
        text = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text or "")
        why = f"the Relay refused found id {found}: {status} {text[:200]}"
        res["problems"].append(f"row {row['row']}: {why}")
        return {**row, "found_refused": why}   # named by check_undo_log's owner action

    def after_write():
        """The after-write read, taken once (with the declared effect on it)."""
        nonlocal after, effect
        if after is None:
            after = read("after-write")
            effect = bool(proof.effect(before, after))
        return after

    def settle(rows, forced=""):
        """Steps 10-12 and 14 for these Undo log rows (`undo_order`): the after-write read when not yet taken, a lost
        reply's finder (story 53, never retried), the undo keys of each key-source row registered first, then the rows
        undone together (`settle_rows`: ticket 30's DELETEs before the shared hide) and closed. Called under `lock`, by
        the main thread or the timer (one row)."""
        nonlocal after_undo
        rows = list(rows)
        if not rows:   # nothing written: nothing to undo (an undo sequence is never sent for no row)
            return
        # ticket 96: an undo sequence's rows close on the after-write read too, so a step that raised still gets one
        if (forced or proof.undo_steps is not None) and proof.arm:
            after_write()
        for i, row in enumerate(rows):
            if row.get("of_id") is None:
                res["reply_lost"] = res.get("reply_lost") or str(row.get("write_status") or "").startswith("reply lost")
                if needs_row_id(proof, row):   # an upload row is reversed by the hide keyed on the post: no id to find
                    rows[i] = find_lost(row)
        for row in rows:
            if undo_driver.is_key_source(proof, row):
                undo_driver.register_keys(proof, row, before, after_write, call, res["problems"], keys, creator)
        done.update(r["row"] for r in rows)   # before the undo: an attempted undo is never retried (story 53's rule)
        try:
            closed = undo_driver.settle_rows(proof, rows, call, wire, read, creator=creator, before=before, after=after,
                                             effect=effect, keys=keys, sent=sent, res=res, fan=proof_fan, kept=kept,
                                             folder=shots)
        except Exception as e:  # noqa: BLE001  (an undo that raised closes FAILED: the run stops, story 19)
            res["problems"].append(f"rows {[r['row'] for r in rows]}: undo raised {type(e).__name__}: {e}")
            shut = {x["row"] for x in res.get("closed", [])}
            closed = [{**row, "reads": {"before": before, "after_write": after, "after_undo": None}, "state": "FAILED",
                       "closed": datetime.now(timezone.utc).isoformat()} for row in rows if row["row"] not in shut]
            res.setdefault("closed", []).extend(closed)
        after_undo = closed[-1]["reads"]["after_undo"] if closed else after_undo
        for c in closed if forced else ():
            c["forced"] = forced
            res["forced"] = [*res.get("forced", []), f"row {c['row']}: {forced}"]
            append_jsonl(evidence / "undo-log.jsonl", c)   # closed now, not at disarm: the proof goes on

    def watch():
        """Story 10's timer: each pending row of this proof with an undo deadline is settled once it is due."""
        try:
            while not stop.wait(0.25):
                for row in mine():
                    if row["row"] in done or row.get("state") != "pending":
                        continue
                    body = _wire_folded(evidence).get(row.get("wire_seq"), {}).get("body")
                    due = undo_deadline(proof, row["write"]["method"], row["write"]["path"], body,
                                        datetime.fromisoformat(row["opened"]))
                    if due is None or datetime.now(timezone.utc) < due:
                        continue
                    with lock:
                        if stop.is_set() or row["row"] in done:
                            return
                        settle([row], forced=f"undo forced by the deadline timer (due {due.isoformat()}) during "
                                           f"step {step_now[0]!r}")
        except Exception as e:  # noqa: BLE001  (the main thread's finally still settles every row)
            res["problems"].append(f"deadline timer: {type(e).__name__}: {e}")

    def settle_now():
        """Ticket 99: a ("call", fn) step's `settle()`: the rows written so far undone and closed now, as at the end
        (each against its own after-write read), so the proof goes on in phases (a Remove from vault is undo-only)."""
        nonlocal after, effect
        with lock:
            after_write()
            settle(undo_order(proof, [r for r in mine() if r["row"] not in done]))
            after = effect = None   # the next phase takes its own after-write read and registers its own keys
            keys.clear()
            sent.clear()

    def fan_visible_spent():
        """Ticket 99: the proof id of every fan-visible attempt in the Undo log (this proof's open rows included)."""
        return [r["proof"] for r in read_undo_log(evidence / "undo-log.jsonl") if r.get("fan_visible")]

    timer = threading.Thread(target=watch, name=f"deadline-{proof.id}", daemon=True)
    if proof.arm:
        timer.start()
    # relay-only triggers (the drills) and capture-browser steps open no app page; Proof rejects a mix of families
    ui = step_family(proof.trigger[0]) == "ui"
    shown, offhost0, images, dom = proof.page, len(ab.offhost()), [], []
    # page: closed in `finally`: an open page keeps its event stream, and six fill the per-host limit
    page = seq0 = park_window = None
    aborted_seqs, h0 = set(), len(cb.hand_offs) if cb else 0
    reupload = any(w.relay_upload for w in proof.undo)   # ticket 67
    try:
        seq_start = max((e["seq"] for e in wire()), default=0)   # a Park checks nothing left after this (park_problems)
        # ticket 61: text waits read from OnlyFans (Expect), resolved and guarded OF-side before the page opens (Park)
        wants = resolve_expects(expect_waits(proof), stack.of_get)
        if wants:
            res["wants"] = {str(k): v for k, v in wants.items()}
        before = read("before")
        why = proof.precheck(before) if proof.precheck else None
        if why:   # ticket 96: refused on the before read; no page opens, nothing is written
            raise _Parked(why)
        if proof.ready and (why := proof.ready(before)):   # ticket 60: OnlyFans's side is not set for the trigger
            raise Park(why)
        kept = undo_driver.keep(proof, before, call, creator, shots)   # ticket 67: before any write, or not at all
        # the window opens before the first page load: what the page sends while it loads is the proof's too
        seq0 = max((e["seq"] for e in wire()), default=0)
        ab.responses, ab.errors, ab.writes = [], [], []
        if ui:
            page = ab.ctx.new_page()
            page.goto(f"{stack.app}/of-manager/{proof.page.replace('/index', '')}", wait_until="load", timeout=180_000)
            res["scope"] = page.evaluate("() => localStorage.getItem('chatterly:scope')")
            if res["scope"] != f"model:{creator}":
                res["problems"].append(f"not in Single-Creator scope: chatterly:scope is {res['scope']!r}")
            fr = _mirror_frame(page, proof.page)
            if proof.trigger[0][0] != "call":   # a ("call", fn) step waits for its own page state (ticket 100)
                fr.locator(proof.trigger[0][1]).first.wait_for(state="visible", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)   # the page's own reads land before the shot
            except Exception:  # noqa: BLE001  (an open event stream can keep the network busy; the shot still counts)
                pass
            page.screenshot(path=str(shots / "trigger.png"))
            res["screens"].append(f"{proof.id}/trigger.png")
        step_errors = []
        for i, step in enumerate(proof.trigger):
            step_now[0] = " ".join(map(str, step))
            if step[0] == "relay":   # an existing Relay route, called as the scoped Creator
                _, method, route, body = step
                r = req.fetch(f"{stack.relay}{route}", method=method, headers={"X-Account-Id": creator},
                              data=body(before) if callable(body) else body)
                res.setdefault("relay", []).append({"method": method, "route": route, "status": r.status})
                if r.status >= 400:
                    step_errors.append((method, route, r.status))
                continue
            if step_family(step) == "browser":   # a fetch or an OAuth hand-off in the capture browser
                aborted_seqs |= capture_cmd.play(step, cb, before, marker, wire, res)
                continue
            if step[0] == "wait":   # UI: hold the proof on this step for N seconds
                page.wait_for_timeout(step[1] * 1000)
                continue
            if step[0] == "text":   # UI: wait for a text, as `settled` does (a note that fades before the end)
                _wait_text(fr, step[1], wants.get(i, step[2]), marker, proof_fan)
                continue
            if step[0] == "goto":   # UI: another Mirror page in the same tab (Phase 6: New post's vault dialog)
                shown = goto_target(fill_text(step[1], marker, proof_fan), mine)   # ticket 33: {fan}
                page.goto(f"{stack.app}/of-manager/{shown.replace('/index', '')}", wait_until="load", timeout=180_000)
                fr = _mirror_frame(page, shown.split("?", 1)[0])
                continue
            if step[0] == "frame":   # UI: the Mirror page a click navigated the tab to (tickets 34, 96, 131)
                shown = step[1]
                fr = _mirror_frame(page, shown)
                fr.wait_for_load_state("load", timeout=60_000)
                continue
            if step[0] == "call":   # ticket 100: the proof's own steps (Relay calls, reads, clicks) on `ctx`
                problems = step[1](_call_ctx(page, fr, shown, stack, call, creator, marker, proof_fan, shots, res,
                                             proof.id, extra={"settle": settle_now,
                                                              "fan_visible_spent": fan_visible_spent,
                                                              "cotag_partner": cotag_partner})) or []
                res["problems"] += problems
                if problems:
                    break
                continue
            if step[0] == "images":   # UI: every matching <img> once loaded or failed, for the proof's check
                images.append({"page": shown, "tiles": collect_tiles(fr, step[1])})
                continue
            if step[0] == "dom":   # UI: the shown items under a container, for the proof's check (tickets 95, 96)
                dom.append(_dom_snapshot(page, fr, shown, *step[1:]))
                continue
            # ticket 96
            if step[0] == "drag":   # UI: pointer drag of one element onto another (a drag handle)
                fr.locator(step[1]).first.drag_to(fr.locator(step[2]).first, timeout=30_000)
                continue
            if step[0] == "gone":   # UI: wait until no element matches (or the frame went with it)
                try:
                    fr.locator(step[1]).first.wait_for(state="detached", timeout=30_000)
                except Exception:  # noqa: BLE001
                    if not fr.is_detached():
                        raise
                continue
            loc = fr.locator(step[1]).first
            if step[0] == "click":
                loc.click(timeout=30_000)
            elif step[0] == "fill":
                loc.fill(fill_text(step[2], marker, proof_fan), timeout=30_000)
            elif step[0] == "accept":   # a click whose confirm() holds step[2] is accepted (ticket 34)
                click_confirm(page, loc, step[2])
            elif step[0] == "press":   # a key on the control (ticket 61: one behind an open modal takes no click)
                loc.press(step[2], timeout=30_000)
            elif step[0] == "select":   # ticket 69: a native <select> (Social media's Button) set to the option's value
                loc.select_option(fill_text(step[2], marker, proof_fan), timeout=30_000)
            elif step[0] == "file":   # ticket 67: the control opens a file picker; the synthetic grey PNG is chosen
                _pick_file(page, loc, step[2])
            else:
                raise ValueError(f"unknown trigger step {step!r}")
        shot = "settled.png"
        step_now[0] = "settled"
        if proof.settled:
            kind, sel, want, *landed = proof.settled
            assert kind == "text" and len(landed) <= 1, proof.settled
            if landed:   # ticket 61: the trigger led to another mirror page (a State page's link); it settles there
                fr = _mirror_frame(page, landed[0])
            try:
                _wait_text(fr, sel, wants.get("settled", want), marker, proof_fan)   # `{marker}`: only this run's write
            except Exception:  # noqa: BLE001
                # Story 53: an app that got no reply never settles; that symptom is expected only when the Relay logged
                # the write's reply as lost. The step-9 checks below still run. The shot is named unsettled so a
                # lost-reply pass is never read as the app confirming the control (live proof needs a settled shot).
                if not any(str(x.get("write_status") or "").startswith("reply lost") for x in mine()):
                    raise
                shot = "unsettled.png"
        if ui:
            page.screenshot(path=str(shots / shot))
            res["screens"].append(f"{proof.id}/{shot}")
        elif cb is not None and step_family(proof.trigger[0]) == "browser":
            cb.page.screenshot(path=str(shots / "drill.png"))
            res["screens"].append(f"{proof.id}/drill.png")
        # in-flight wire lines complete (the page's wait also delivers its pending response events)
        page.wait_for_timeout(500) if ui else time.sleep(0.5)
        relay_errors, ab.errors = ab.errors + step_errors, None
        res["app_writes"], ab.writes = ab.writes, None
        responses = ab.responses
        for method, path, account in res["app_writes"]:
            if account != creator:   # every write the app sends is for the scoped Creator (story 29)
                res["problems"].append(f"{method} {path} carried X-Account-Id {account!r}, not {creator}")
        window = [e for e in wire() if e["seq"] > seq0 and e["seq"] not in aborted_seqs]
        res["problems"] += wire_problems(proof, window, relay_errors) + expect_problems(proof, window)
        if proof.check:   # what the browser saw goes to the evidence folder; the report keeps its path
            seen = {"origins": list(ab.allowed), "images": images, "responses": responses,
                    "offhost": ab.offhost()[offhost0:], "dom": dom, "of_read": before,
                    "wire": window}   # wire: ticket 96
            shots.mkdir(parents=True, exist_ok=True)
            (shots / "seen.json").write_text(json.dumps(seen, indent=1))
            res["seen"] = f"{proof.id}/seen.json"
            got = proof.check(seen)   # {problems, parked, record} (ticket 95)
            res["record"] = got["record"] or {}
            if got["parked"]:
                res["parked"] = got["parked"]
            res["problems"] += got["problems"]
        if proof.kind == "oauth":
            res["hand_offs"] = cb.hand_offs[h0:] if cb else []
            res["problems"] += hand_off_problems(res["hand_offs"], window)
        if capture_abort:   # the aborted write left OnlyFans's side as it was
            after = read("after-write")
            if not reads_equal(before, after):
                res["problems"].append("capture --abort: OnlyFans's side changed between the before and after reads")
        with lock:
            # a drill has no effect to read (it passes only refused); taken already when the timer forced the undo; a
            # proof whose undo uploads a picture again reads after the app's writes landed (finally, `_app_quiet`)
            if proof.arm and proof.refused_as is None and after is None and not reupload:
                after = read("after-write")
                effect = bool(proof.effect(before, after))   # judged with the row by verify_undo
    except _Parked as e:   # tickets 96, 100: parked before any write
        res["parked"], res["read_first"] = str(e), True
    except Park as e:   # tickets 60, 61: a precondition unmet before the page opened; checked below: nothing sent
        res["parked"] = str(e)
        park_window = [x for x in wire() if x["seq"] > seq_start]
    except Exception as e:  # noqa: BLE001  (a failed step fails the proof; the undo below still runs)
        res["problems"].append(f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}")
        res["traceback"] = traceback.format_exc()
    finally:
        ab.errors = ab.writes = ab.responses = None
        if proof.arm and page is not None:   # before the timer stops: a `delete_at_once` deadline still fires meanwhile
            _app_quiet(page, wire, seq0, res)
        stop.set()   # the timer starts no new undo; one under way finishes first
        if timer.is_alive():
            timer.join(timeout=120)
        if reupload:   # ticket 67: the after-write read (a cover URL the undo's wait skips) after the app's writes
            try:
                with lock:
                    if proof.arm and after is None and mine():
                        after_write()
            except Exception as e:  # noqa: BLE001  (no after-write read: the undo is sent, the after-undo read decides)
                res["problems"].append(f"after-write read: {type(e).__name__}: {e}")
        with lock:
            # ticket 30: the post's DELETE and hide before the upload rows
            settle(undo_order(proof, [row for row in mine() if row["row"] not in done]))
        req.post(f"{stack.relay}/__proof/arm", data={"proof": None})   # disarm
        if kept and ui and res.get("closed"):   # ticket 67: after the disarm, so the fresh page's writes are not this proof's
            _after_undo_shot(ab, stack, proof, shots, res)
        for closed in res.get("closed", []):
            if not closed.get("forced"):
                append_jsonl(evidence / "undo-log.jsonl", closed)
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001  (a page the browser already lost is closed enough)
                pass
    res["undo"] = [c["state"] for c in res.get("closed", [])] or ["none"]
    if park_window is not None:   # tickets 60, 61: a Park left nothing sent
        res["problems"] += park_problems(res["parked"], park_window, res["undo"])
    # a sent message no unsend took back (ticket 100) stops the run as a FAILED undo does (story 19); a park (tickets
    # 60, 61, 95, 96): never a pass, only when nothing failed or was written
    res["state"] = ("FAILED" if {"FAILED", NOT_REVERSIBLE_REFUSED} & set(res["undo"]) else "fail" if res["problems"]
                    else "parked" if res.get("parked") and res["undo"] == ["none"] else "pass")
    # ticket 99: a branch the proof parked after its writes were all undone (the cap spent before a re-run)
    parked = [v for v in ((res.get("record") or {}).get("branches") or {}).values() if str(v).startswith("parked:")]
    if parked and res["state"] == "pass" and set(res["undo"]) <= {"undone", "none"}:
        res["state"], res["parked"] = "parked", "; ".join(parked)
    res["reads"] = {"before": before, "after_write": after, "after_undo": after_undo}
    res["t"] = [t0, time.time()]
    return res


def revision() -> dict:
    """The app and Relay revision a run proved (story 33): HEAD, the app/ and service/ trees at HEAD, and whether
    either had uncommitted changes; `harness_dirty`: the driver (scripts/of-live-proof/) or FakeOF (soak/) had, so the
    evidence is not HEAD's."""
    def dirty(*trees):
        return bool(_git("status", "--porcelain", "--", *trees).strip())
    return {"head": _git("rev-parse", "HEAD").strip(), "app": _git("rev-parse", "HEAD:app").strip(),
            "app_dirty": dirty("app"), "relay": _git("rev-parse", "HEAD:service").strip(), "relay_dirty": dirty("service"),
            "harness_dirty": dirty("scripts/of-live-proof", "soak")}


def bootstrap(stack: Stack, ab: AppBrowser) -> str:
    """A throwaway owner, then the Creator: live, the copied session linked as seed.py links one (live_entry); fake,
    from FakeOF's signed curl (soak/runner.py `_boot`). Returns its id."""
    req = ab.ctx.request
    user_id, password = live_entry.register_owner(req, stack.relay)
    stack.login = (live_entry.OWNER, password)   # printed by `serve` only
    if stack.fake is None:
        live_entry.link_account(stack.tmp / "relay.db", user_id)
        stack.account = live_entry.PROOF_CREATOR
        return stack.account
    r = req.post(f"{stack.relay}/admin/session/bootstrap", timeout=60_000, data={
        "mode": "paste-curl", "curl": stack.fake.of.signed_curl(), "nickname": "ofm-proof", "make_active": True})
    if not r.ok:
        raise RuntimeError(f"paste-curl bootstrap failed: {r.status} {r.text()[:500]}")
    account = str(r.json()["account_id"])
    want = str(stack.fake.of.world.creator_id)
    if account != want:
        raise RuntimeError(f"bootstrap bound account {account}, expected FakeOF's creator {want}")
    stack.account = account
    return account


def _app_quiet(page, wire, seq0, res) -> None:
    """Before any undo: the proof's app page is left, so it sends no more writes, and the ones under way land
    (`_writes_quiet`), so an undo is never overtaken by a late write (a Save that timed out or raised still counts, and
    FakeOF's row check counts a write after the undo went out as a problem)."""
    try:
        page.goto("about:blank")
        if seq0 is not None and not _writes_quiet(wire, seq0):
            res["problems"].append("the app's writes were still under way 60 s after its page closed")
    except Exception as e:  # noqa: BLE001  (the undo still runs; the after-undo read decides)
        res["problems"].append(f"leaving the app page before the undo: {type(e).__name__}: {e}")


def _after_undo_shot(ab, stack, proof, shots, res) -> None:
    """Ticket 67: the proof's page as the undo left OnlyFans, in a fresh context (`AppBrowser.fresh_context`), saved
    as after-undo.png beside the trigger and settled shots and named in each closed row's evidence. Evidence only:
    a failed shot is a note, the after-undo read decides."""
    ctx = None
    try:
        ctx = ab.fresh_context()
        page = ctx.new_page()
        page.goto(f"{stack.app}/of-manager/{proof.page.replace('/index', '')}", wait_until="load", timeout=180_000)
        _mirror_frame(page, proof.page).locator(proof.trigger[0][1]).first.wait_for(state="visible", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:  # noqa: BLE001  (an open event stream can keep the network busy; the shot still counts)
            pass
        page.screenshot(path=str(shots / "after-undo.png"))
        res["screens"].append(f"{proof.id}/after-undo.png")
        for closed in res["closed"]:
            closed["evidence"] = [*closed.get("evidence", []), f"{proof.id}/after-undo.png"]
    except Exception as e:  # noqa: BLE001
        res.setdefault("notes", []).append(f"after-undo shot: {type(e).__name__}: {str(e)[:200]}")
    finally:
        if ctx is not None:
            ctx.close()


def _writes_quiet(wire, seq0, limit=60.0, still=6.0) -> bool:
    """Ticket 67: whether the Relay's writes after `seq0` all completed (no `intent` line left) and no new one came for
    `still` seconds (longer than the guard's 5 s write pace, so a write held for its turn is seen), within `limit`."""
    end, last, since = time.time() + limit, None, time.time()
    while time.time() < end:
        lines = [e for e in wire() if e["seq"] > seq0 and e.get("verdict") != "read"]
        busy = any(e.get("phase") == "intent" for e in lines)
        now = (len(lines), busy)
        if now != last:
            last, since = now, time.time()
        elif not busy and time.time() - since >= still:
            return True
        time.sleep(0.5)
    return False


def _wire_folded(evidence: Path) -> dict:
    wire = {}
    for line in (evidence / "wire.jsonl").read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            wire[e["seq"]] = e
    return wire


def harness_checks(evidence: Path, hits: list, results: list) -> list:
    """Fake mode's external checks (Testing Decisions seam 1), from each proof's own arm and undo Writes. `results`:
    every proof the run started, a parked one included."""
    wire = _wire_folded(evidence)
    out = census(list(wire.values()), hits)
    out += pace_problems(list(wire.values()))   # story 22: forwarded writes at least 5 s apart
    plain = [h for h in hits if not h["tagged"]]
    for r in results:
        p = ALL[r["proof"]]
        if p.refused_as is not None:   # a drill: FakeOF received none of its requests (story 39)
            out += [f"{p.id}: FakeOF received {h['method']} {h['path']}" for h in plain if undo_driver.arm_hit(p.arm, h)]
        if r.get("read_first"):   # tickets 96, 100: parked before any write, so FakeOF received none of its writes
            t0, t1 = r.get("t") or (float("-inf"), float("inf"))   # ticket 98: in its own window (proofs share arms)
            out += [f"{p.id}: parked, yet FakeOF received {h['method']} {h['path']}" for h in plain
                    if t0 <= h["t"] <= t1 and (undo_driver.arm_hit(p.arm, h) or undo_driver.arm_hit(p.undo, h))]
        out += [m for c in r.get("closed", []) if (m := undo_driver.row_problem(p, c, r["closed"], plain))]
    return out


def proof_ok(r: dict) -> bool:
    """A proof that needs no retry and fails no run: passed, or parked (nothing written; never a pass). The run's exit
    and accept.py's `retry_ids` both judge proofs by it."""
    return r.get("state") in ("pass", "parked")


def run_ok(rep: dict, n_ids: int, have_secrets: bool) -> bool:
    """The run-level verdict: everything a run's exit needs apart from its proofs' states."""
    return ("error" not in rep and not rep["preflight"] and not rep["harness"] and not rep.get("offhost")
            and have_secrets and not rep["session_leaks"]
            and not rep.get("niceness_low") and not rep["trees_changed"] and not rep["not_run"]
            and rep.get("teardown", {}).get("temp_deleted") is True
            and not rep["refused"] and len(rep["proofs"]) + len(rep["parked"]) == n_ids
            and not rep["undo_log"])


def _report_md(rep: dict) -> str:
    lines = [f"# Live proof run {rep['folder']}", "", f"- of: {rep['of']}  sha: {rep['sha']}  exit: {rep['exit']}",
             f"- account: {rep.get('account')}  revision: {json.dumps(rep.get('revision'))}"]
    for r in rep["proofs"]:
        lines.append(f"- {r['proof']}: {r['state']}" + (" — its write's reply was lost, never retried"
                                                         if r.get("reply_lost") else "")
                     + (f" ({'; '.join(r['problems'])})" if r["problems"] else "")
                     + (f" ({r['parked']})" if r.get("parked") and not r["problems"] else ""))
    for p in rep["parked"]:
        lines.append(f"- {p['proof']}: {p['reason']}")
    for p in rep["not_run"]:
        lines.append(f"- {p}: not run (an earlier undo FAILED)")
    for p in rep.get("undo_log", []):
        lines.append(f"- Undo log: {p}")
    if rep.get("reverify"):
        lines.append(f"- reverify: {json.dumps(rep['reverify'], default=str)[:600]}")
    for k in ("lock", "fault", "refused", "preflight", "harness", "offhost", "niceness_low", "trees_changed", "session_leaks"):
        if rep.get(k):
            lines.append(f"- {k}: {json.dumps(rep[k], default=str)[:600]}")
    for f in (x for r in rep["proofs"] for x in r.get("forced", [])):
        lines.append(f"- forced undo: {f}")
    lines += ["", "## Undo log", "", (Path(rep["evidence"]) / "undo-log.md").read_text()]
    return "\n".join(lines) + "\n"


def earlier_pending(of: str, folder: str, creator: str | None = None) -> list:
    """Every `pending` row in an earlier run's Undo log (story 52), named with its file; under --of live also every
    FAILED or NOT_REVERSIBLE_REFUSED one (follow-up #6, `unresolved_rows`: an undo that did not take may have left the
    item on the Proof Creator's account; a fake run's FakeOF is fresh each run). Round 2 #23: under --of live with
    `creator`, also the logs the Creator's shared Undo index lists (run_lock, beside its lock: other worktrees' live
    runs); a listed log with no unresolved row drops out of the index; a listed log that is gone blocks (check by
    hand, then drop its path from the index file).
    ASSUMPTION: only runs of the same mode count (a fake run's pending row says nothing about the Proof Creator's
    account, and the reverse; rung 5); overturned if the owner wants any pending row to block every run."""
    out, resolved = [], []
    local = {log.resolve(): f"slop/evidence/{log.parent.name}/undo-log.jsonl"
             for log in (ROOT / "slop" / "evidence").glob(f"*-ofm-{of}-*/undo-log.jsonl")}
    try:
        listed = index_logs(creator) if creator and of == "live" else []
    except ValueError as e:
        out.append(f"{e}: check it by hand")
        listed = []
    shared = {log: str(log) for log in listed if f"-ofm-{of}-" in log.parent.name and log not in local}
    for log, name in sorted({**local, **shared}.items()):
        if log.parent.name == folder:
            continue
        if not log.exists():
            out.append(f"{name}: listed in the shared Undo index {_index_path(creator)} but gone: check by hand")
            continue
        try:
            rows = read_undo_log(log)
            left = [f"{name}: {p}" for p in (unresolved_rows(rows) if of == "live" else pending_rows(rows))]
        except (ValueError, KeyError, OSError) as e:
            left = [f"{name}: unreadable ({type(e).__name__}): check it by hand"]
        out += left
        if not left and log in shared:
            resolved.append(log)
    if resolved:
        index_update(creator, drop=resolved)
    return out


def _index_settle(creator: str, log: Path) -> None:
    """Round 2 #23, at a live run's end: its Undo log leaves the shared index unless it holds an unresolved row."""
    try:
        left = unresolved_rows(read_undo_log(log)) if log.exists() else []
    except (ValueError, KeyError, OSError):
        left = ["unreadable"]
    if not left:
        try:
            index_update(creator, drop=[log])
        except ValueError:
            pass   # an unreadable index already blocks the next live run (earlier_pending)


def prove(proof_ids: list[str], fault: str | None = None, proof_fan: str | None = None,
          capture: str | None = None, of: str = "fake", session_src: Path | None = None, serve: bool = False, *,
          expected: str, lockout: bool = False, reverify: Path | None = None, cotag_partner: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    sha = _git("rev-parse", "--short", "HEAD").strip() or "nosha"
    run_id = _utc()
    folder = f"{run_id}-ofm-{of}-{sha}"
    # ASSUMPTION: a fake run's folder says `fake` where the spec's live folder says `live` (story 33 names the live
    # run's folder only; rung 5), so a fake run is never quoted as a live one. Overturned by the coordinator.
    taken, lock_msg = take_lock(expected, folder)   # 80000112 live; FakeOF's Creator fake
    if not taken:
        print(f"ofm-live-proof: refused: {lock_msg}", flush=True)
        return 1
    if lock_msg:
        print(f"ofm-live-proof: {lock_msg}", flush=True)
    log = ROOT / "slop" / "evidence" / folder / "undo-log.jsonl"
    listed = False
    try:
        pending = earlier_pending(of, folder, expected)
        if pending:
            for p in pending:
                print(f"ofm-live-proof: refused: earlier run's Undo log has an unresolved row: {p}", flush=True)
            return 1
        if of == "live":   # round 2 #23: listed from the start, so a crashed live run still blocks other worktrees
            index_update(expected, add=log)
            listed = True
        return _prove(proof_ids, fault, sha, run_id, folder, lock_msg, sync_playwright, proof_fan, capture,
                      of=of, session_src=session_src, expected=expected, serve=serve, lockout=lockout,
                      reverify=reverify, cotag_partner=cotag_partner)
    finally:
        if listed:
            _index_settle(expected, log)
        release_lock(expected)


def _prove(proof_ids, fault, sha, run_id, folder, lock_msg, sync_playwright, proof_fan=None, capture=None, *,
           of="fake", session_src=None, expected: str, serve=False, lockout=False, reverify=None,
           cotag_partner=None) -> int:
    """`capture`: None (prove), "send" or "abort" (`capture [--abort]`, one proof, no app). `serve`: no proof; the
    stack waits after preflight until interrupted. `reverify`: an earlier evidence folder; no proof, no app, the served
    cover compared with its kept one after preflight. `expected`: the Creator the preflight must find."""
    evidence = ROOT / "slop" / "evidence" / folder
    evidence.mkdir(parents=True)
    (evidence / "wire.jsonl").touch()
    (evidence / "undo-log.jsonl").touch()
    trees0 = _trees_state()
    rep = {"folder": f"slop/evidence/{folder}", "evidence": str(evidence), "of": of, "sha": sha,
           "fault": fault, "expected": expected, "lock": lock_msg, "proof_fan": proof_fan, "cotag_partner": cotag_partner,
           "proofs": [], "parked": [],
           "refused": [], "not_run": [],
           "preflight": [], "harness": [], "revision": revision(),
           "cmd": "serve" if serve else "reverify" if reverify else f"capture ({capture})" if capture else "prove"}
    secrets: list = []
    print(f"ofm-live-proof: evidence {rep['folder']}" + (f" (fault {fault})" if fault else ""), flush=True)
    stack = cb = None
    started = []   # every proof run_proof ran, a parked one included (harness_checks)
    code = 1
    try:
        stack = Stack(evidence, fault, app=not capture and not reverify, session_src=session_src)
        fake = stack.fake
        print(f"ofm-live-proof: {f'fake {fake.origin}' if fake else 'live'}, relay {stack.relay}, app {stack.app}",
              flush=True)
        with sync_playwright() as pw:
            ab = AppBrowser(pw, stack, evidence)
            creator = rep["account"] = bootstrap(stack, ab)
            secrets = session_secrets(load_session(stack.session_dir(creator)))   # held in memory for the leak check
            ab.ctx.add_init_script(f"try {{ localStorage.setItem('chatterly:scope', 'model:{creator}'); }} catch (e) {{}}")
            if not capture and not reverify:
                stack.wait_app()
            rep["preflight"] = live_entry.preflight(ab.ctx.request, stack.relay, [stack.relay, stack.app] + (
                [fake.origin] if fake else []), expected, holds_lock(expected))
            for why in rep["preflight"]:
                print(f"ofm-live-proof: refused before any proof: preflight: {why}", flush=True)
            proofs = order([ALL[i] for i in proof_ids if i in ALL], canon=ORDER)
            if not rep["preflight"]:   # parked and refused first: the capture browser opens for startable proofs only
                proofs = live_entry.startable(proofs, [x for x in proof_ids if x in PENDING], of, proof_fan, rep,
                                              capture=capture)
            if capture_cmd.opens_capture_browser(capture, proofs, rep["preflight"]):   # on demand only (D27)
                cb = capture_cmd.start(pw, stack.session_dir(creator), _relay_client(stack, ab), creator, evidence, rep,
                                       fake_origin=fake.origin if fake else None,
                                       fake_sign=stack.fake_sign if fake else None, launch_args=LAUNCH_ARGS)
            if serve and not rep["preflight"]:
                live_entry.serve_wait(stack.app, stack.relay, stack.login)
            if reverify and not rep["preflight"]:   # read only: one OnlyFans read and one /img GET, nothing armed
                cover = ALL["settings--profile-cover-avatar"]
                rep["reverify"] = undo_driver.reverify(cover, reverify, lambda: cover.of_read(stack.of_get, None),
                                                       _relay_client(stack, ab), creator, out=evidence)
                v = rep["reverify"]
                print(f"ofm-live-proof: reverify {v['kept_file']}: {'match' if v['ok'] else 'NO MATCH'}"
                      + (f" (mean abs pixel diff {v['mean_abs_diff']})" if v.get("mean_abs_diff") is not None else "")
                      + (f" ({v['why']})" if v.get("why") else ""), flush=True)
            if not rep["preflight"]:
                for i, p in enumerate(proofs):
                    print(f"ofm-live-proof: {'capture ' if capture else ''}{p.id}"
                          + (" --abort" if capture == "abort" else "") + " ...", flush=True)
                    if capture:   # one proof (main)
                        r = capture_cmd.run_capture(p, lambda q, abort: run_proof(
                            q, stack, ab, creator, evidence, run_id, proof_fan, cb=cb, capture_abort=abort,
                            lockout=lockout, cotag_partner=cotag_partner),
                            cb, creator, evidence, run_id, proof_fan, capture == "abort")
                    else:
                        r = run_proof(p, stack, ab, creator, evidence, run_id, proof_fan, cb=cb, lockout=lockout,
                                      cotag_partner=cotag_partner)
                    started.append(r)   # harness_checks: every proof that ran, a parked one included
                    if r["state"] == "parked":   # tickets 60, 61, 95, 96, 99: found at run time, reported parked
                        rep["parked"].append({"proof": p.id, "reason": r["parked"], "screens": r["screens"],
                                              **({"read_first": True} if r.get("read_first") else {})})
                        print(f"ofm-live-proof: {p.id}: {r['parked']}", flush=True)
                        continue
                    rep["proofs"].append(r)
                    lost = (" — never retried; " + ("found and undone" if set(r["undo"]) == {"undone"} else "not undone")
                            if r.get("reply_lost") else "")
                    print(f"ofm-live-proof: {p.id}: {r['state']}{lost}"
                          + (f" ({'; '.join(r['problems'])})" if r["problems"] else "")
                          + (f" ({r['parked']})" if r.get("parked") and not r["problems"] else ""), flush=True)
                    for f in r.get("forced", []):
                        print(f"ofm-live-proof: {p.id}: forced undo: {f}", flush=True)
                    if r["state"] == "FAILED":
                        rep["not_run"] = [q.id for q in proofs[i + 1:]]   # story 19: a failed undo stops the run
                        for q in rep["not_run"]:
                            print(f"ofm-live-proof: {q}: not run (an earlier undo FAILED)", flush=True)
                        break
            rep["niceness"] = _niceness_of_tree(os.getpid())
            rep["niceness_low"] = [p for p in rep["niceness"] if p["nice"] < NICE]
            rep["offhost"] = ab.offhost()
            done_cb, cb = cb, None
            capture_cmd.finish(done_cb, evidence, rep)
            try:
                ab.browser.close()
            except Exception:  # noqa: BLE001
                if not serve:   # a terminal's Ctrl-C reaches Playwright's driver too: the browser is already gone
                    raise
    except KeyboardInterrupt:   # SIGINT, or SIGTERM via `_interrupt`, before serve's wait or during a proof
        rep["error"] = "interrupted"
        print("ofm-live-proof: interrupted; tearing down", file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {e}"
        rep["traceback"] = traceback.format_exc()
        print(rep["traceback"], file=sys.stderr)
    finally:
        sigs = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)}   # teardown runs whole
        try:
            if stack is not None:   # first: the temp dir and session copy go even if what follows raises
                rep["teardown"] = stack.close()
            capture_cmd.finish(cb, evidence, rep)   # a run that raised still keeps the capture browser's exchanges
            if stack is not None and stack.fake:
                hits = stack.fake.recorder.snapshot()
                with open(evidence / "fake-hits.jsonl", "w") as f:
                    for h in hits:
                        f.write(json.dumps(h, default=str) + "\n")
                if "error" not in rep:
                    rep["harness"] = harness_checks(evidence, hits, started)
                from fake_layer import STATES, start_state_problems
                if fault in STATES:   # ticket 60: a start state faults no request; its proof must park instead
                    rep["harness"] += start_state_problems(fault, rep["parked"])
                elif fault and not any(h.get("fault") for h in hits) and not stack.planted:   # ticket 97: app fault
                    rep["harness"].append(f"fault {fault} never fired: no proof sent the request it targets")
                rep["harness"] += [f"fault did not fire as designed: {h['method']} {h['path']}: {h['fault']}"
                                   for h in hits if h.get("fault") and h["fault"] != fault]
            elif stack is not None and "error" not in rep:   # live: no FakeOF to census; the pacing check still holds
                rep["harness"] = pace_problems(list(_wire_folded(evidence).values()))
            rows = read_undo_log(evidence / "undo-log.jsonl")
            md = undo_markdown(rows)
            (evidence / "undo-log.md").write_text(md)
            rep["undo_log"] = check_undo_log(list(_wire_folded(evidence).values()), rows)
            for p in rep["undo_log"]:
                print(f"ofm-live-proof: Undo log: {p}", flush=True)
            print(md, flush=True)
            rep["trees_changed"] = _trees_state() != trees0
            # one check, over everything the run leaves: the evidence folder, the report about to be written, its output
            rep["exit"] = None
            rep["session_leaks"] = session_leaks({**evidence_texts(evidence), "<run output>": capture_cmd.OUT.text(),
                                                  "report.json": json.dumps(rep, default=str), "report.md": _report_md(rep)},
                                                 secrets)
            for p in rep["session_leaks"]:
                print(f"ofm-live-proof: session leak: {p}", flush=True)
            rep["run_ok"] = run_ok(rep, len(proof_ids), bool(secrets))   # accept.py reads it (ticket 77)
            ok = (rep["run_ok"] and all(proof_ok(r) for r in rep["proofs"])
                  and (not reverify or bool(rep.get("reverify", {}).get("ok"))))
            code = 0 if ok else 1
            rep["exit"] = code
            (evidence / "report.json").write_text(json.dumps(rep, indent=1, default=str))
            (evidence / "report.md").write_text(_report_md(rep))
            print(f"ofm-live-proof: {'PASS' if ok else 'FAIL'} — {rep['folder']}", flush=True)
        finally:
            for s, h in sigs.items():
                signal.signal(s, h)
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/of-live-proof/run.sh")
    ap.add_argument("cmd", nargs="?", default="prove", choices=("prove", "capture", "serve", "reverify"))
    ap.add_argument("--of", required=True, choices=("live", "fake"))
    ap.add_argument("--proof", default="tracer.create-list", help="comma-separated proof ids")
    ap.add_argument("--fault", choices=("delete-500", "lost-reply", "cdn-src", "trial-delete-500", "rename-ignored",
                                        "post-drop-label", "post-drop-expiry", "post-drop-target",   # ticket 35
                                        "email-off",   # ticket 60
                                        live_entry.WRONG_CREATOR,
                                        "tip-filter", "strip-miss", "highlight-field", "payout-field",   # ticket 95
                                        "no-stored-order", "sort-restore-500",   # ticket 96
                                        "audience-list", "audience-second", "unsend-refused",   # ticket 100
                                        "queue-500-foreign",
                                        "dup-id-refused", "post-commit-500", "composer-once",   # ticket 97
                                        "publish-other", "post-lost-hidden", "hidden-refused",   # ticket 99
                                        "publish-lost", "publish-500",
                                        "unsend-delete-500",   # ofm-not-yet ticket 33
                                        "cotag-extra"),   # ofm-not-yet ticket 98
                    help="fake only: FakeOF answers the tracer's (or a post's, ticket 101) DELETE 500, or applies its create and drops the reply; "
                         "or plants a vault tile src on a CDN host; or the run expects another Creator than FakeOF's; "
                         "trial-delete-500: the trial link's DELETE 500 (ticket 64); rename-ignored: a vault folder "
                         "PATCH answered 200, not applied (ticket 34); post-drop-*: a post stored without that field, "
                         "answered 200 (ticket 35); email-off: the account starts with Email notifications and New "
                         "Likes Summary off (ticket 60); or plants a read proof's wrong answer (ticket 95, "
                         "fake_layer.py); or (ticket 96) answers the vault folder read without its "
                         "stored order, or the folder order restore 500; or (ticket 100) a list or second Fan in a "
                         "queued item's audience read, or refuses a released item's queue unsend, or answers the queue "
                         "write 500 with another user's item queued instead; or (ticket 97) "
                         "refuses a post holding one media id twice, or makes a post then answers 500, or plants an app "
                         "composer sending each id once; or (ticket 99) plants an app Publish now sending another "
                         "queued post's schedule id, or makes the post holding a hidden medium then drops the reply, "
                         "or refuses publishing a post whose medium is hidden, or publishes a post then drops the "
                         "reply or answers 500; unsend-delete-500: a message DELETE 500 (ofm-not-yet ticket 33); "
                         "or (ticket 98) plants an app post adding a second Co-tag creator "
                         "(lost-reply also drops the immediate Co-tagged post's reply)")
    ap.add_argument("--session-dir", help="live only, required there (no default): the Proof Creator's account "
                                          "session dir, copied into the run's temp dir and never printed")
    ap.add_argument("--proof-fan", help="the Proof fan message and PPV proofs may reach; fake mode defaults to "
                                         "FakeOF's fan, `none` unsets it (those proofs then park)")
    # ofm-not-yet ticket 98: the Co-tag proofs' partner is run input only
    ap.add_argument("--cotag-partner", help="the OnlyFans creator id the Co-tag proofs tag; fake mode defaults to "
                                            "FakeOF's taggable creator, `none` unsets it; live never defaults (those "
                                            "proofs then park: owner sheet item 4)")
    ap.add_argument("--abort", action="store_true", help="capture only: record the write and abort it before it "
                                                         "leaves")
    # ticket 66: the Run's `lockout` (proof_core.Run, rung 4) had no flag; a Lockout control's write still needs its
    # pinned body, and its proofs still run last (order)
    ap.add_argument("--lockout", action="store_true", help="arm Lockout control writes (tag lockout, pinned body): "
                                                           "Block by country and Block by IP")
    ap.add_argument("--evidence", type=Path, help="reverify only, required there: the earlier run's evidence folder "
                                                  "whose kept cover the served one is compared with")
    a = ap.parse_args(argv)
    why = live_entry.session_dir_refusal(a.of, a.session_dir)   # before anything starts (story 2)
    if why:
        print(f"ofm-live-proof: refused: {why}", file=sys.stderr)
        return 2
    if a.abort and a.cmd != "capture":
        print("ofm-live-proof: --abort is for `capture` only", file=sys.stderr)
        return 2
    if a.fault and a.of != "fake":
        print("ofm-live-proof: --fault is fake mode only", file=sys.stderr)
        return 2
    if (a.cmd == "reverify") != (a.evidence is not None):
        print("ofm-live-proof: --evidence <folder> is for `reverify` only, and required there", file=sys.stderr)
        return 2
    if a.cmd == "reverify" and not undo_driver.kept_files(ALL["settings--profile-cover-avatar"], a.evidence):
        print(f"ofm-live-proof: refused: no kept picture settings--profile-cover-avatar/undo-*-before.* in "
              f"{a.evidence}", file=sys.stderr)
        return 2
    ids = [] if a.cmd in ("serve", "reverify") else [x for x in a.proof.split(",") if x]
    unknown = [x for x in ids if x not in ALL and x not in PENDING]   # a PENDING id is parked by the run
    if (not ids and a.cmd not in ("serve", "reverify")) or unknown:
        print(f"ofm-live-proof: unknown proof {unknown or ids!r}; known: {sorted(ALL)}", file=sys.stderr)
        return 2
    why = (capture_cmd.cli_refusal(ALL[ids[0]], len(ids), a.fault, a.abort)
           if a.cmd == "capture" and ids[0] in ALL else None)
    if why:   # story 26: a Critical control's capture without --abort, before anything starts
        print(f"ofm-live-proof: {why}", file=sys.stderr)
        return 2
    refused = fake_only_refused([ALL[i] for i in ids if i in ALL], a.of)   # before anything starts (story 39)
    for why in refused:
        print(f"ofm-live-proof: refused: {why}", file=sys.stderr)
    if refused:
        return 2
    cur = os.getpriority(os.PRIO_PROCESS, 0)   # os.nice(0) raises EPERM on macOS once already niced
    if cur < NICE:
        os.setpriority(os.PRIO_PROCESS, 0, NICE)   # inherited by FakeOF, the Relay, next dev and the browsers
    # ASSUMPTION: `--proof-fan none` is how a fake run leaves the Proof fan unset (rung 5: fake mode otherwise names
    # FakeOF's fan, so parking needs an explicit way to be exercised). A live run never defaults it (ticket 09).
    fan = None if a.proof_fan is None or a.proof_fan.strip().lower() in ("", "none") else a.proof_fan.strip()
    if a.proof_fan is None and a.of == "fake":
        from fake_layer import PROOF_FAN
        fan = str(PROOF_FAN)
    # ofm-not-yet ticket 98: digits only; `none` unsets it in fake mode, as --proof-fan
    partner = None if a.cotag_partner is None or a.cotag_partner.strip().lower() in ("", "none") \
        else a.cotag_partner.strip()
    if partner is not None and not partner.isdigit():
        print("ofm-live-proof: --cotag-partner is an OnlyFans user id (digits) or `none`", file=sys.stderr)
        return 2
    if a.cotag_partner is None and a.of == "fake":
        from fake_layer import COTAG_PARTNER
        partner = str(COTAG_PARTNER)
    expected = live_entry.expected_creator(a.of, a.fault)   # wrong-creator ends here: FakeOF never sees it
    fault = None if a.fault == live_entry.WRONG_CREATOR else a.fault
    signal.signal(signal.SIGTERM, _interrupt)   # SIGTERM tears down like Ctrl-C (temp dir and session copy go)
    return prove(ids, fault, fan, capture=("abort" if a.abort else "send") if a.cmd == "capture" else None,
                 of=a.of, session_src=Path(a.session_dir) if a.session_dir else None, serve=a.cmd == "serve",
                 expected=expected, lockout=a.lockout, reverify=a.evidence, cotag_partner=partner)


def _interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


if __name__ == "__main__":
    sys.stdout, sys.stderr = capture_cmd.OUT.wrap(sys.stdout), capture_cmd.OUT.wrap(sys.stderr)
    sys.exit(main())
