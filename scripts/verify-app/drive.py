#!/usr/bin/env python3
"""Drive the real app (relay + Next) for verification. Usage: see .claude/skills/verify-app/SKILL.md.

    drive.py up                      start a throwaway stack (scripts/demo-shots/run.sh serve), seed
                                     Northstar Studio, start the browser daemon; prints the run id
    drive.py doctor                  read-only health check of the run
    drive.py login --as owner|manager|chatter|anon
    drive.py goto /growth/scripts
    drive.py click --role button --name "Add"          (or --text / --label / --placeholder / --testid;
                                                         --dialog "Confirm" scopes to that open dialog)
    drive.py fill --role textbox --name "Title" --value "x"
    drive.py press Enter
    drive.py wait --text "Saved"
    drive.py snapshot [--path name.yml]                 ARIA tree of the page, written to the evidence dir
    drive.py screenshot --path name.png [--phone]       --phone: same URL, same session, 390x844
    drive.py db "select ..."                            read-only SQL on the run's temp DB
    drive.py api /admin/...                             GET as the active session (status + JSON)
    drive.py of-writes                                  POST/PUT/DELETE the app sent to /api/of/* (never left the box)
    drive.py down                                       stop what `up` started; evidence stays

Every command prints one JSON object and appends it to <evidence>/log.jsonl.
Run selection: --run <id>, else $VERIFY_APP_RUN, else the newest run.
Nothing leaves the machine: the browser resolves only localhost, /api/of/* is answered from
scripts/demo-shots/fixtures.py, the relay and next run behind demo-shots' network guards.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "scripts/demo-shots"
RUNS = ROOT / ".scratch/verify-app"
PY = ROOT / "venv/bin/python"
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
PASSWORD = "demo-shots-throwaway"  # seed.py writes it for every login
ROLES = {"owner": 0, "manager": 1, "chatter": 4}  # dataset.EMPLOYEES index: Alex Morgan, Jordan Lee, Hannah Kim


def out(obj: dict, run: Path | None = None, code: int = 0):
    print(json.dumps(obj, indent=1, default=str))
    if run is not None:
        with (run / "log.jsonl").open("a") as f:
            f.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "argv": sys.argv[1:], **obj}, default=str) + "\n")
    sys.exit(code)


def fail(msg: str, run: Path | None = None, **extra):
    out({"ok": False, "error": msg, **extra}, run, 1)


def pick_run(arg: str | None) -> Path:
    rid = arg or os.environ.get("VERIFY_APP_RUN")
    if rid:
        p = RUNS / rid
        if not (p / "state.json").exists():
            fail(f"no run {rid!r} under {RUNS}; list runs with `ls {RUNS}` or start one with `drive.py up`")
        return p
    runs = sorted((p for p in RUNS.glob("*/state.json")), key=lambda p: p.stat().st_mtime)
    if not runs:
        fail("no run yet; start one with `scripts/verify-app/drive.py up`")
    return runs[-1].parent


def state(run: Path) -> dict:
    return json.loads((run / "state.json").read_text())


def save_state(run: Path, **kv):
    s = state(run) if (run / "state.json").exists() else {}
    s.update(kv)
    tmp = run / "state.json.tmp"
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(run / "state.json")


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def http_get(url: str, timeout: float = 10) -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


# ── up / down ────────────────────────────────────────────────────────────────
def cmd_up(a):
    rid = a.run or datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    run = RUNS / rid
    if (run / "state.json").exists():
        fail(f"run {rid} exists; pick another --run or `drive.py down --run {rid}` first")
    run.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "DEMO_SHOTS_DIST_DIR": f".next/verify-app-{rid}"}  # own next build dir: concurrent runs OK
    log = (run / "stack.log").open("w")
    stack = subprocess.Popen(["nice", "-n", "10", str(SHOTS / "run.sh"), "serve"], cwd=ROOT, env=env,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save_state(run, run_id=rid, stack_pid=stack.pid, dist_dir=env["DEMO_SHOTS_DIST_DIR"], started=time.time())
    urls = {}
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        text = (run / "stack.log").read_text()
        for line in text.splitlines():
            if line.startswith("demo-shots: relay "):  # "demo-shots: relay URL, app URL, temp DIR"
                parts = line.replace(",", "").split()
                urls = {"relay": parts[2], "app": parts[4], "tmp": parts[6]}
        if "demo-shots: serving." in text:
            break
        if stack.poll() is not None:
            fail(f"run.sh exited {stack.returncode} during startup; read {run}/stack.log, then `drive.py down --run {rid}`",
                 run, tail=text.splitlines()[-15:])
        time.sleep(1)
    else:
        fail(f"stack not ready after {a.timeout}s; read {run}/stack.log, then `drive.py down --run {rid}`", run)
    save_state(run, **urls, db=f"{urls['tmp']}/relay.db")
    dlog = (run / "daemon.log").open("w")
    daemon = subprocess.Popen(["nice", "-n", "10", str(PY), "-u", __file__, "_daemon", "--run", rid], cwd=ROOT,
                              stdout=dlog, stderr=subprocess.STDOUT, start_new_session=True)
    save_state(run, daemon_pid=daemon.pid)
    while time.time() < deadline:
        s = state(run)
        if s.get("ready"):
            break
        if daemon.poll() is not None:
            fail(f"browser daemon exited during seeding; read {run}/daemon.log, then `drive.py down --run {rid}`", run)
        time.sleep(1)
    else:
        fail(f"seeding not done after {a.timeout}s; read {run}/daemon.log, then `drive.py down --run {rid}`", run)
    s = state(run)
    out({"ok": True, "run": rid, "evidence": str(run), "app": s["app"], "relay": s["relay"], "db": s["db"],
         "logins": s["logins"], "thread": s["thread"], "next": f"export VERIFY_APP_RUN={rid}; scripts/verify-app/drive.py doctor"}, run)


def _kill_group(pid: int, wait: float) -> bool:
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return True
    end = time.time() + wait
    while time.time() < end:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.3)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return False


def cmd_down(a):
    run = pick_run(a.run)
    s = state(run)
    done = {}
    if s.get("daemon_pid"):
        done["daemon"] = _kill_group(s["daemon_pid"], 10)
    if s.get("stack_pid"):  # run.sh's EXIT trap stops relay + next and restores app/tsconfig.json
        done["stack"] = _kill_group(s["stack_pid"], 40)
    leftovers = []
    for key in ("relay", "app"):  # a port this run allocated still listening = our orphan (run.sh got SIGKILL)
        port = (s.get(key) or "").rsplit(":", 1)[-1]
        if port.isdigit():
            pids = subprocess.run(["lsof", "-nti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True,
                                  text=True).stdout.split()
            for p in pids:
                os.kill(int(p), signal.SIGTERM)
                leftovers.append(int(p))
    dist = s.get("dist_dir", "")
    if dist.startswith(".next/verify-app-"):
        subprocess.run(["rm", "-rf", str(ROOT / "app" / dist)])
    save_state(run, stopped=time.time(), ready=False)
    kept = sorted(p.name for p in run.iterdir())
    out({"ok": True, "run": run.name, "stopped": done, "orphans_killed": leftovers, "evidence": str(run),
         "evidence_files": kept}, run)


# ── read-only commands (no daemon needed) ────────────────────────────────────
def cmd_db(a):
    run = pick_run(a.run)
    db = state(run).get("db")
    if not db or not Path(db).exists():
        fail(f"temp DB {db} is gone (run stopped?); `drive.py up` for a new run", run)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(a.sql).fetchmany(a.limit)]
    except sqlite3.Error as e:
        fail(f"{e}; read-only DB. Tables: `drive.py db \"select name from sqlite_master where type='table'\"`, "
             "columns: `drive.py db \"pragma table_info(<table>)\"`", run)
    out({"ok": True, "sql": a.sql, "rows": rows, "count": len(rows)}, run)


def cmd_doctor(a):
    run = pick_run(a.run)
    s = state(run)
    checks = {
        "stack_pid": alive(s.get("stack_pid")),
        "daemon_pid": alive(s.get("daemon_pid")),
        "relay_livez": http_get(f"{s.get('relay')}/livez") == 200,  # /health is 503 by design: seeded sessions are fake
        "app_http": http_get(f"{s.get('app')}/login", 120) == 200,
        "db_exists": bool(s.get("db")) and Path(s["db"]).exists(),
    }
    if checks["db_exists"]:
        con = sqlite3.connect(f"file:{s['db']}?mode=ro", uri=True)
        checks["seeded_creators"] = con.execute("select count(*) from accounts").fetchone()[0]
        checks["seeded_chatters"] = con.execute("select count(*) from chatters").fetchone()[0]
    daemon = {}
    if checks["daemon_pid"]:
        daemon = _call(run, {"cmd": "_doctor"}, exit_on_error=False)
    checks["owner_session"] = daemon.get("owner_me") == 200
    checks["offhost_aborted"] = daemon.get("offhost", "?")
    checks["unmatched_of_reads"] = daemon.get("unmatched", "?")
    ok = all(checks[k] for k in ("stack_pid", "daemon_pid", "relay_livez", "app_http", "db_exists",
                                 "owner_session")) and checks.get("seeded_creators") == 20 and daemon.get("offhost") == 0
    hint = None if ok else (f"run looks broken: read {run}/stack.log and {run}/daemon.log, then "
                            f"`drive.py down --run {run.name}` and `drive.py up`")
    out({"ok": ok, "run": run.name, "app": s.get("app"), "checks": checks, "active": daemon.get("active"),
         "url": daemon.get("url"), "fix": hint}, run, 0 if ok else 1)


# ── browser commands: forwarded to the daemon ────────────────────────────────
def _call(run: Path, payload: dict, exit_on_error: bool = True) -> dict:
    s = state(run)
    if not s.get("ready") or not alive(s.get("daemon_pid")):
        if not exit_on_error:
            return {}
        fail(f"browser daemon of run {run.name} is not running; `drive.py doctor`, or `drive.py up` for a new run", run)
    req = urllib.request.Request(f"http://127.0.0.1:{s['daemon_port']}/", data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=300) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        if not exit_on_error:
            return {}
        fail(f"daemon call failed ({e}); `drive.py doctor`", run)


def cmd_browser(a):
    run = pick_run(a.run)
    payload = {k: v for k, v in vars(a).items() if k not in ("run", "fn", "sub") and v is not None}
    if payload.get("path"):
        p = Path(payload["path"]) if os.path.isabs(payload["path"]) else run / payload["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        payload["path"] = str(p)
    res = _call(run, payload)
    out(res, run, 0 if res.get("ok") else 1)


# ── the daemon: one Playwright browser, one context per session ──────────────
def daemon(rid: str):
    run = RUNS / rid
    s = state(run)
    os.environ.update(DEMO_SHOTS_ROOT=str(ROOT), DEMO_SHOTS_TMP=s["tmp"], DEMO_SHOTS_APP=s["app"],
                      DEMO_SHOTS_RELAY=s["relay"],
                      # Anchor the dataset at the real now: no browser clock override, schedules are real times.
                      DEMO_SHOTS_NOW=datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat())
    sys.path.insert(0, str(SHOTS))
    from playwright.sync_api import Error as PwError, sync_playwright
    import dataset
    from capture import LAUNCH_ARGS, Router
    from fixtures import Fixtures
    from seed import Api, seed

    app = s["app"]
    d = dataset.build()
    router = Router(Fixtures(d))
    of_writes: list[dict] = []  # what the app sent towards OnlyFans (answered by fixtures, never sent)
    plain_handle = router.handle

    def handle_route(route, request):
        path = request.url.split("?", 1)[0].split("/", 3)[-1]
        if request.method != "GET" and path.startswith("api/"):
            of_writes.append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": request.method,
                              "path": "/" + path, "body": (request.post_data or "")[:4000]})
        return plain_handle(route, request)
    pw = sync_playwright().start()
    browser = pw.chromium.launch(args=LAUNCH_ARGS)
    boot = browser.new_context()
    r = boot.request.post(f"{app}/auth/register", data={"username": dataset.OWNER_USERNAME, "password": PASSWORD})
    if not r.ok:
        raise SystemExit(f"register -> {r.status} {r.text()[:200]}")
    seed(d, db=Path(s["tmp"]) / "relay.db", sessions=Path(s["tmp"]) / "sessions", user_id=r.json()["user_id"],
         api=Api(boot.request, app))
    # Scaffolding: seeded chatters are older than the 7-day trial, so every page load would open the
    # "Free trial exceeded" nag; this is the owner's own Settings > Preferences "Disable free trial popup".
    api = Api(boot.request, app)
    api.put("/admin/settings/preferences", {**api.get("/admin/settings/preferences")["config"], "hide_trial_popup": True})
    states = {"owner": boot.storage_state(), "anon": None}
    boot.close()
    logins = {"owner": {"username": dataset.OWNER_USERNAME, "password": PASSWORD, "form": "/login"}}
    for role in ("manager", "chatter"):
        e = d.employees[ROLES[role]]
        c = browser.new_context()
        r = c.request.post(f"{app}/chatter/login", data={"username": e["username"], "password": PASSWORD})
        if not r.ok:
            raise SystemExit(f"{role} login -> {r.status} {r.text()[:200]}")
        states[role] = c.storage_state()
        c.close()
        logins[role] = {"username": e["username"], "password": PASSWORD, "name": e["name"], "form": "/login"}

    ctxs: dict = {}
    cur = {"role": "owner"}

    def ctx_for(role: str, phone: bool = False):
        k = (role, phone)
        if k not in ctxs:
            c = browser.new_context(viewport=PHONE if phone else DESKTOP, device_scale_factor=2 if phone else 1,
                                    is_mobile=phone, has_touch=phone, service_workers="block",
                                    storage_state=states[role], timezone_id="UTC", locale="en-US")
            c.add_init_script("try{localStorage.setItem('chatterly:theme','light')}catch(e){}")
            c.route("**/*", handle_route)
            c.route_web_socket("**/*", router.ws)
            c.set_default_timeout(15_000)
            ctxs[k] = (c, c.new_page())
        return ctxs[k]

    def page():
        return ctx_for(cur["role"])[1]

    def locate(p, q: dict):
        if q.get("dialog"):  # scope to one open dialog (two dialogs often share "OK" / "Cancel")
            p = p.get_by_role("dialog", name=q["dialog"], exact=True)
        if q.get("role"):
            loc = p.get_by_role(q["role"], name=q.get("name"), exact=q.get("exact", False))
        elif q.get("label"):
            loc = p.get_by_label(q["label"], exact=q.get("exact", False))
        elif q.get("placeholder"):
            loc = p.get_by_placeholder(q["placeholder"], exact=q.get("exact", False))
        elif q.get("testid"):
            loc = p.get_by_test_id(q["testid"])
        elif q.get("text"):
            loc = p.get_by_text(q["text"], exact=q.get("exact", False))
        else:
            raise ValueError("give --role [--name], --label, --placeholder, --testid or --text")
        loc = loc.filter(visible=True)
        n = loc.count()
        if n == 0:
            loc.first.wait_for(state="visible", timeout=q.get("timeout", 15) * 1000)
            n = loc.count()
        if n > 1 and q.get("nth") is None:
            raise ValueError(f"{n} visible matches; add --exact, a longer --name, or --nth 0..{n - 1} "
                             "(see `drive.py snapshot`)")
        return loc.nth(q.get("nth") or 0)

    def settle(p):
        try:
            p.wait_for_load_state("networkidle", timeout=8_000)
        except PwError:
            pass  # an open event stream keeps the network busy; the next command waits on its own target

    def handle(q: dict) -> dict:
        cmd = q["cmd"]
        p = page()
        if cmd == "_doctor":
            c = ctx_for("owner")[0]
            me = c.request.get(f"{app}/auth/me")
            return {"ok": True, "owner_me": me.status, "offhost": len(router.offhost),
                    "unmatched": len(set(router.unmatched)), "active": cur["role"], "url": p.url}
        if cmd == "login":
            if q["as_"] == "anon":  # always a fresh, signed-out browser (a form sign-in leaves cookies behind)
                for k in [k for k in ctxs if k[0] == "anon"]:
                    ctxs.pop(k)[0].close()
            cur["role"] = q["as_"]
            p = page()
            p.goto(app + q.get("goto", "/login" if q["as_"] == "anon" else "/"), wait_until="domcontentloaded")
            settle(p)
            return {"ok": True, "as": q["as_"], "login": logins.get(q["as_"]), "url": p.url}
        if cmd == "goto":
            p.goto(app + q["route"], wait_until="domcontentloaded", timeout=180_000)
            settle(p)
            return {"ok": True, "url": p.url, "title": p.title()}
        if cmd == "click":
            locate(p, q).click()
            settle(p)
            return {"ok": True, "url": p.url}
        if cmd == "fill":
            locate(p, q).fill(q["value"])
            return {"ok": True, "url": p.url}
        if cmd == "press":
            p.keyboard.press(q["key"])
            settle(p)
            return {"ok": True, "url": p.url}
        if cmd == "wait":
            locate(p, {**q, "nth": 0}).wait_for(state="visible", timeout=q.get("timeout", 15) * 1000)
            return {"ok": True, "url": p.url}
        if cmd == "snapshot":
            path = Path(q.get("path") or run / f"aria-{int(time.time())}.yml")
            text = p.locator("body").aria_snapshot()
            path.write_text(text)
            return {"ok": True, "url": p.url, "path": str(path), "lines": text.count("\n") + 1}
        if cmd == "screenshot":
            path = Path(q["path"])
            target = p
            if q.get("phone"):
                target = ctx_for(cur["role"], phone=True)[1]
                target.goto(p.url, wait_until="domcontentloaded", timeout=180_000)
                settle(target)
                if q.get("text"):
                    locate(target, {"text": q["text"], "nth": 0}).wait_for(state="visible")
                target.wait_for_timeout(800)
            target.screenshot(path=str(path), full_page=bool(q.get("full")))
            return {"ok": True, "url": target.url, "path": str(path), "viewport": target.viewport_size}
        if cmd == "of-writes":
            return {"ok": True, "count": len(of_writes), "writes": of_writes[-q.get("last", 20):]}
        if cmd == "api":
            res = ctx_for(cur["role"])[0].request.get(app + q["route"])
            try:
                body = res.json()
            except Exception:  # noqa: BLE001
                body = res.text()[:2000]
            return {"ok": res.ok, "status": res.status, "route": q["route"], "body": body}
        raise ValueError(f"unknown command {cmd!r}; see `drive.py --help`")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def do_POST(self):  # noqa: N802
            q = json.loads(self.rfile.read(int(self.headers["content-length"])))
            try:
                res = handle(q)
            except Exception as e:  # noqa: BLE001  any failure -> JSON error, the daemon keeps serving
                msg = str(e).splitlines()[0][:300]
                if "Timeout" in msg:
                    msg += " (not found in time: `drive.py snapshot` lists the real roles/names on this page)"
                res = {"ok": False, "error": msg, "url": page().url}
            body = json.dumps(res, default=str).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.timeout = 0.2
    ctx_for("owner")
    th = d.thread
    save_state(run, daemon_port=srv.server_address[1], logins=logins, ready=True, dataset_now=dataset.iso(d.now),
               thread={"route": f"/messages-pro/{th['account_id']}/{th['fan_id']}",
                       "creator": d.creator(th["account_id"])["name"], "fan": d.fans[th["fan_id"]]["name"]})
    print(f"verify-app daemon ready on {srv.server_address[1]}", flush=True)
    while True:
        srv.handle_request()
        try:
            page().wait_for_timeout(50)  # pump Playwright so route handlers answer the page between commands
        except PwError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id (default $VERIFY_APP_RUN, else newest)")
    sub = ap.add_subparsers(dest="sub", required=True)

    def sp(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--run", default=argparse.SUPPRESS)
        p.set_defaults(fn=fn, cmd=name)
        return p

    def target(p):
        p.add_argument("--role")
        p.add_argument("--name")
        p.add_argument("--label")
        p.add_argument("--placeholder")
        p.add_argument("--testid")
        p.add_argument("--text")
        p.add_argument("--exact", action="store_true", default=None)
        p.add_argument("--nth", type=int)
        p.add_argument("--dialog", help="only inside the open dialog with this exact name")
        p.add_argument("--timeout", type=int, help="seconds (default 15)")

    sp("up", cmd_up, "start stack + seed + browser daemon").add_argument("--timeout", type=int, default=600)
    sp("down", cmd_down, "stop this run's processes; evidence stays")
    sp("doctor", cmd_doctor, "read-only health check")
    p = sp("db", cmd_db, "read-only SQL on the temp DB")
    p.add_argument("sql")
    p.add_argument("--limit", type=int, default=50)
    p = sp("login", cmd_browser, "switch session (seeded logins)")
    p.add_argument("--as", dest="as_", required=True, choices=["owner", "manager", "chatter", "anon"])
    p.add_argument("--goto", help="route to open (default / ; anon: /login)")
    sp("goto", cmd_browser, "open a route").add_argument("route")
    target(sp("click", cmd_browser, "click an element"))
    p = sp("fill", cmd_browser, "fill an input")
    target(p)
    p.add_argument("--value", required=True)
    sp("press", cmd_browser, "press a key").add_argument("key")
    target(sp("wait", cmd_browser, "wait until an element is visible"))
    sp("snapshot", cmd_browser, "ARIA snapshot to a file").add_argument("--path")
    p = sp("screenshot", cmd_browser, "PNG of the page")
    p.add_argument("--path", required=True)
    p.add_argument("--phone", action="store_true", default=None)
    p.add_argument("--full", action="store_true", default=None)
    p.add_argument("--text", help="with --phone: wait for this text first")
    sp("api", cmd_browser, "GET a relay route as the active session").add_argument("route")
    sp("of-writes", cmd_browser, "non-GET /api/* requests the app sent towards OnlyFans (fixture-answered)"
       ).add_argument("--last", type=int, default=20)
    p = sub.add_parser("_daemon")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=lambda a: daemon(a.run))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
