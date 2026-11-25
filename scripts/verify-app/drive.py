#!/usr/bin/env python3
"""Drive the real app (relay + Next) for verification. Usage: see .claude/skills/verify-app/SKILL.md.

    drive.py up [--fansly]           start a throwaway stack (scripts/demo-shots/run.sh serve), seed
                                     Northstar Studio, start the browser daemon; prints the run id
                                     --fansly: a 21st Creator, Nova Reyes on Fansly (demo-shots/fansly_nova.py)
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
    drive.py api /admin/...                             GET as the active session (status + body or redirect Location)
    drive.py of-writes                                  POST/PUT/DELETE the app sent to /api/of/* (never left the box)
    drive.py sse [--type TYPE] [--json ENVELOPE]         queue a mocked Relay event for the next /events connection
    drive.py inbox-msg --account <id> --text "x"        a live message lands in the Relay's chats window
    drive.py reads [--match vault/lists]                GET /api/of/v2/chats (or /api/* urls containing --match) sent
    drive.py visibility hidden|visible                  emulated tab hide/return
    drive.py down                                       stop what `up` started; evidence stays

Every command prints one JSON object and appends it to <evidence>/log.jsonl.
Run selection: --run <id>, else $VERIFY_APP_RUN, else the newest run.
Nothing leaves the machine: the browser resolves only localhost, /api/of/* is answered from
scripts/demo-shots/fixtures.py for browser traffic, and the relay and next have network guards.
The api command bypasses browser routing, so it refuses /api/of routes and never follows redirects.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "scripts/demo-shots"
RUNS = ROOT / ".scratch/verify-app"
PY = ROOT / "venv/bin/python"
ROLES = {"owner": 0, "manager": 1, "chatter": 4}


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


def cmd_up(a):
    rid = a.run or datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
        fail("run id must contain only letters, digits, underscores or hyphens")
    run = RUNS / rid
    try:
        run.mkdir(parents=True)
    except FileExistsError:
        fail(f"run {rid} exists; pick another --run")
    env = os.environ.copy()
    if a.fansly:
        env["VERIFY_APP_FANSLY_NOW"] = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    else:
        env.pop("VERIFY_APP_FANSLY_NOW", None)
    save_state(run, run_id=rid, started=time.time())
    children = {}
    interrupted = False

    def interrupt(*_):
        nonlocal interrupted
        interrupted = True

    def check_interrupted():
        if interrupted:
            raise KeyboardInterrupt("startup interrupted by SIGTERM")

    previous_term = signal.signal(signal.SIGTERM, interrupt)
    try:
        stack = start_process(run, "stack", [str(SHOTS / "run.sh"), "serve"], env, children)
        urls = {}
        deadline = time.monotonic() + a.timeout
        while time.monotonic() < deadline:
            check_interrupted()
            text = (run / "stack.log").read_text()
            line = next((line for line in text.splitlines() if line.startswith("demo-shots: serving. ")), "")
            if line:
                urls = dict(re.findall(r"DEMO_SHOTS_(RELAY|APP|TMP)=([^ ]+)", line))
                if len(urls) == 3:
                    urls = {key.lower(): value for key, value in urls.items()}
                    break
            if stack.poll() is not None:
                raise RuntimeError(f"run.sh exited {stack.returncode} during startup; read {run}/stack.log")
            time.sleep(1)
        else:
            raise RuntimeError(f"stack not ready after {a.timeout}s; read {run}/stack.log")
        save_state(run, **urls, db=f"{urls['tmp']}/relay.db")
        check_interrupted()
        daemon = start_process(run, "daemon", [str(PY), "-u", __file__, "_daemon", "--run", rid], env, children)
        while time.monotonic() < deadline:
            check_interrupted()
            s = state(run)
            if s.get("ready"):
                break
            if daemon.poll() is not None:
                raise RuntimeError(f"browser daemon exited during seeding; read {run}/daemon.log")
            time.sleep(1)
        else:
            raise RuntimeError(f"seeding not done after {a.timeout}s; read {run}/daemon.log")
        check_interrupted()
    except BaseException as exc:
        cleanup = teardown(run, children=children)
        if isinstance(exc, (RuntimeError, KeyboardInterrupt)):
            fail(str(exc) or "startup interrupted", run, cleanup=cleanup)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_term)
    s = state(run)
    out({"ok": True, "run": rid, "evidence": str(run), "app": s["app"], "relay": s["relay"], "db": s["db"],
         "logins": s["logins"], "thread": s["thread"],
         **({"fansly_thread": s["fansly_thread"]} if "fansly_thread" in s else {}),
         "next": f"export VERIFY_APP_RUN={rid}; scripts/verify-app/drive.py doctor"}, run)


def group_identity(pid: int) -> str | None:
    result = subprocess.run(["ps", "-p", str(pid), "-o", "pgid=", "-o", "lstart="],
                            capture_output=True, text=True)
    fields = result.stdout.split(maxsplit=1)
    if len(fields) == 2 and fields[0] == str(pid):
        return fields[1].strip()
    return None


def start_process(run: Path, name: str, args: list[str], env: dict, children: dict) -> subprocess.Popen:
    with (run / f"{name}.log").open("w") as log:
        proc = subprocess.Popen(["nice", "-n", "10", *args], cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    identity = group_identity(proc.pid)
    if identity is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=80)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        raise RuntimeError(f"{name} process identity unavailable; read {run}/{name}.log")
    children[name] = (proc, identity)
    save_state(run, **{f"{name}_pid": proc.pid, f"{name}_identity": identity})
    return proc


def _kill_group(pid: int, identity: str, wait: float, child: subprocess.Popen | None = None) -> str | None:
    current = group_identity(pid)
    if current != identity and current is not None:
        return None
    try:
        if current is None:
            os.killpg(pid, 0)
            return "process group still exists but its leader could not be verified"
        os.killpg(pid, signal.SIGTERM)
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if child is not None:
                child.poll()
            os.killpg(pid, 0)
            time.sleep(0.2)
        if group_identity(pid) == identity:
            os.killpg(pid, signal.SIGKILL)
        return "process group did not exit after SIGTERM"
    except ProcessLookupError:
        return None
    except PermissionError:
        return "permission denied stopping process group"


def teardown(run: Path, children: dict) -> dict:
    s = state(run)
    failures = {}
    cleared = {}
    for name, wait in (("daemon", 10), ("stack", 80)):
        child, identity = children.get(name, (None, s.get(f"{name}_identity")))
        pid = child.pid if child is not None else s.get(f"{name}_pid")
        if pid and identity:
            if error := _kill_group(pid, identity, wait, child):
                failures[name] = error
        elif pid:
            failures[name] = "process identity unavailable"
        if name not in failures:
            cleared.update({f"{name}_pid": None, f"{name}_identity": None})
    tmp = s.get("tmp")
    if not tmp and (run / "stack.log").exists():
        match = re.search(r"^demo-shots: temp (.+)$",
                          (run / "stack.log").read_text(), re.MULTILINE)
        tmp = match[1] if match else None
    if tmp and Path(tmp).exists():
        failures["tmp"] = f"stack temp directory remains: {tmp}"
    save_state(run, stopped=time.time(), ready=False, cleanup=failures, **cleared)
    return failures


def cmd_down(a):
    run = pick_run(a.run)
    failures = teardown(run, {})
    out({"ok": not failures, "run": run.name, "cleanup": failures, "evidence": str(run),
         "evidence_files": sorted(p.name for p in run.iterdir())}, run, int(bool(failures)))


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
        "relay_livez": http_get(f"{s.get('relay')}/livez") == 200,
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
                                 "owner_session")) and checks.get("seeded_creators") == s.get("creators") \
        and daemon.get("offhost") == 0
    hint = None if ok else (f"run looks broken: read {run}/stack.log and {run}/daemon.log, then "
                            f"`drive.py down --run {run.name}` and `drive.py up`")
    out({"ok": ok, "run": run.name, "app": s.get("app"), "checks": checks, "active": daemon.get("active"),
         "url": daemon.get("url"), "fix": hint}, run, 0 if ok else 1)


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


def api_url(app: str, route: str) -> str:
    if not route.startswith("/") or any(ord(c) <= 32 or ord(c) == 127 for c in route):
        raise ValueError("api requires an absolute local path")
    path = urlsplit(app + route).path
    if "%" in path or "\\" in path or any(part in (".", "..") for part in path.split("/")):
        raise ValueError("api requires an unambiguous path")
    parts = path.lower().split("/")
    if [part for part in parts if part][:2] == ["api", "of"]:
        raise ValueError("api does not serve /api/of routes; use the browser fixtures")
    return app + route


def cmd_browser(a):
    run = pick_run(a.run)
    payload = {k: v for k, v in vars(a).items() if k not in ("run", "fn", "sub") and v is not None}
    if payload.get("path"):
        p = Path(payload["path"]) if os.path.isabs(payload["path"]) else run / payload["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        payload["path"] = str(p)
    res = _call(run, payload)
    out(res, run, 0 if res.get("ok") else 1)


def navigation_error(page, response) -> dict | None:
    if response is not None and response.status >= 400:
        return {"ok": False, "error": "navigation failed", "status": response.status, "url": page.url}
    return None


def daemon(rid: str):
    run = RUNS / rid
    s = state(run)
    os.environ.update(DEMO_SHOTS_ROOT=str(ROOT), DEMO_SHOTS_TMP=s["tmp"], DEMO_SHOTS_APP=s["app"],
                      DEMO_SHOTS_RELAY=s["relay"],
                      DEMO_SHOTS_NOW=os.environ.get("VERIFY_APP_FANSLY_NOW")
                      or datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat())
    sys.path.insert(0, str(SHOTS))
    from playwright.sync_api import Error as PwError, sync_playwright
    import dataset
    from capture import DESKTOP, LAUNCH_ARGS, PASSWORD, PHONE, Router
    from fixtures import Fixtures
    from seed import Api, seed

    app = s["app"]
    d = dataset.build()
    if os.environ.get("VERIFY_APP_FANSLY_NOW"):
        import fansly_nova
        fansly_nova.add(d)
        router = Router(fansly_nova.FanslyFixtures(d))
        save_state(run, fansly_thread=fansly_nova.THREAD)
    else:
        router = Router(Fixtures(d))
    of_writes: list[dict] = []
    plain_handle = router.handle

    sse_queue: list[tuple[str, dict]] = []
    sse_on = {"on": False}
    reads: list[dict] = []

    def handle_route(route, request):
        path = request.url.split("?", 1)[0].split("/", 3)[-1]
        if sse_on["on"] and request.method == "GET" and path.rstrip("/").endswith("events"):
            body = "retry: 500\n\n" + "".join(f"event: {t}\ndata: {json.dumps(e)}\n\n" for t, e in sse_queue)
            sse_queue.clear()
            return route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=body)
        if request.method != "GET" and path.startswith("api/"):
            of_writes.append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": request.method,
                              "path": "/" + path, "account": request.headers.get("x-account-id"),
                              "body": (request.post_data or "")[:4000]})
        elif path.startswith("api/"):
            reads.append({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "path": path,
                          "url": request.url.split("/", 3)[-1], "account": request.headers.get("x-account-id")})
        return plain_handle(route, request)
    pw = sync_playwright().start()
    browser = pw.chromium.launch(args=LAUNCH_ARGS)
    boot = browser.new_context()
    r = boot.request.post(f"{app}/auth/register", data={"username": dataset.OWNER_USERNAME, "password": PASSWORD})
    if not r.ok:
        raise SystemExit(f"register -> {r.status} {r.text()[:200]}")
    seed(d, db=Path(s["tmp"]) / "relay.db", sessions=Path(s["tmp"]) / "sessions", user_id=r.json()["user_id"],
         api=Api(boot.request, app))
    if os.environ.get("VERIFY_APP_FANSLY_NOW"):
        fansly_nova.seed_db(Path(s["tmp"]) / "relay.db", d, r.json()["user_id"],
                            d.employees[ROLES["chatter"]]["username"])
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

    def new_context(storage_state, phone: bool = False):
        c = browser.new_context(viewport=PHONE if phone else DESKTOP, device_scale_factor=2 if phone else 1,
                                    is_mobile=phone, has_touch=phone, service_workers="block",
                                    storage_state=storage_state, timezone_id="UTC", locale="en-US")
        c.add_init_script("try{localStorage.setItem('chatterly:theme','light')}catch(e){}")
        c.route("**/*", handle_route)
        c.route_web_socket("**/*", router.ws)
        c.set_default_timeout(15_000)
        return c

    def ctx_for(role: str):
        if role not in ctxs:
            c = new_context(states[role])
            ctxs[role] = (c, c.new_page())
        return ctxs[role]

    def page():
        return ctx_for(cur["role"])[1]

    def locate(p, q: dict):
        if q.get("dialog"):
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
            pass

    def handle(q: dict) -> dict:
        cmd = q["cmd"]
        p = page()
        if cmd == "_doctor":
            c = ctx_for("owner")[0]
            me = c.request.get(f"{app}/auth/me")
            return {"ok": True, "owner_me": me.status, "offhost": len(router.offhost),
                    "unmatched": len(set(router.unmatched)), "active": cur["role"], "url": p.url}
        if cmd == "login":
            if q["as_"] == "anon":
                if "anon" in ctxs:
                    ctxs.pop("anon")[0].close()
            cur["role"] = q["as_"]
            p = page()
            response = p.goto(app + q.get("goto", "/login" if q["as_"] == "anon" else "/"),
                              wait_until="domcontentloaded")
            if error := navigation_error(p, response):
                return error
            settle(p)
            return {"ok": True, "as": q["as_"], "login": logins.get(q["as_"]), "url": p.url}
        if cmd == "goto":
            response = p.goto(app + q["route"], wait_until="domcontentloaded", timeout=180_000)
            if error := navigation_error(p, response):
                return error
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
            if not q.get("phone"):
                p.screenshot(path=str(path), full_page=bool(q.get("full")))
                return {"ok": True, "url": p.url, "path": str(path), "viewport": p.viewport_size}
            desktop_url = p.url
            phone = new_context(p.context.storage_state(), phone=True)
            try:
                target = phone.new_page()
                response = target.goto(desktop_url, wait_until="domcontentloaded", timeout=180_000)
                if error := navigation_error(target, response):
                    return error
                settle(target)
                if q.get("text"):
                    locate(target, {"text": q["text"], "nth": 0}).wait_for(state="visible")
                target.wait_for_timeout(800)
                if urlsplit(target.url).path != urlsplit(desktop_url).path:
                    return {"ok": False, "error": "phone navigated away from the desktop path",
                            "url": target.url, "desktop_url": desktop_url}
                target.screenshot(path=str(path), full_page=bool(q.get("full")))
                return {"ok": True, "url": target.url, "path": str(path), "viewport": target.viewport_size}
            finally:
                phone.close()
        if cmd == "sse":
            sse_on["on"] = True
            if q.get("json"):
                sse_queue.append((q["type"], json.loads(q["json"])))
            return {"ok": True, "queued": len(sse_queue)}
        if cmd == "inbox-msg":
            rows = router.fx.chats(q["account"])
            i = 1 if q.get("nth") is None else q["nth"]
            r = dict(rows.pop(i))
            r["lastMessage"] = {**r["lastMessage"], "id": int(time.time()), "text": q["text"],
                                "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "fromUser": {"id": r["withUser"]["id"]}}
            r["unreadMessagesCount"] = (r.get("unreadMessagesCount") or 0) + 1
            r["hasUnread"] = True
            rows.insert(0, r)
            return {"ok": True, "fan": r["withUser"]["id"], "text": q["text"]}
        if cmd == "reads":
            m = q.get("match")
            hits = [{"t": r["t"], "url": r["url"], "account": r["account"]} for r in reads
                    if (m in r["url"] if m else r["path"].startswith("api/of/v2/chats") and r["path"].rstrip("/").endswith("chats"))]
            return {"ok": True, "count": len(hits), "reads": hits[-q.get("last", 50):]}
        if cmd == "visibility":
            # headless Chromium never hides a page on its own
            p.evaluate("""s => { Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => s});
                Object.defineProperty(document, 'hidden', {configurable: true, get: () => s === 'hidden'});
                document.dispatchEvent(new Event('visibilitychange'));
                if (s === 'visible') window.dispatchEvent(new Event('focus')); }""", q["state"])
            return {"ok": True, "state": q["state"]}
        if cmd == "of-writes":
            return {"ok": True, "count": len(of_writes), "writes": of_writes[-q.get("last", 20):]}
        if cmd == "api":
            res = ctx_for(cur["role"])[0].request.get(api_url(app, q["route"]), max_redirects=0)
            if 300 <= res.status < 400:
                return {"ok": res.ok, "status": res.status, "route": q["route"],
                        "location": res.headers.get("location")}
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
               creators=len(d.creators),
               thread={"route": f"/messages-pro/{th['account_id']}/{th['fan_id']}",
                       "creator": d.creator(th["account_id"])["name"], "fan": d.fans[th["fan_id"]]["name"]})
    print(f"verify-app daemon ready on {srv.server_address[1]}", flush=True)
    while True:
        srv.handle_request()
        try:
            page().wait_for_timeout(50)
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

    p = sp("up", cmd_up, "start stack + seed + browser daemon")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--fansly", action="store_true", help="seed a 21st Creator on Fansly (Nova Reyes)")
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
    p = sp("sse", cmd_browser, "queue one event for the page's next /events connect (the Relay stream, mocked)")
    p.add_argument("--type", default="api2_chat_message")
    p.add_argument("--json", help="the envelope; omit to only switch the mock on")
    sp("of-writes", cmd_browser, "non-GET /api/* requests the app sent towards OnlyFans (fixture-answered)"
       ).add_argument("--last", type=int, default=20)
    p = sp("inbox-msg", cmd_browser, "a live message lands in the Relay's chats window: row nth moves on top")
    p.add_argument("--account", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--nth", type=int, default=None)
    p = sp("reads", cmd_browser, "GET /api/of/v2/chats the page sent, with times (the list's poll rate); --match: "
           "every GET /api/* url containing it, query included")
    p.add_argument("--last", type=int, default=50)
    p.add_argument("--match")
    sp("visibility", cmd_browser, "emulate tab hide/return (visibilitychange; focus on visible)"
       ).add_argument("state", choices=["hidden", "visible"])
    p = sub.add_parser("_daemon")
    p.add_argument("--run", required=True)
    p.set_defaults(fn=lambda a: daemon(a.run))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
