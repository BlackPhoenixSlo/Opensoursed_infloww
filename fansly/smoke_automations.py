#!/usr/bin/env python3
"""smoke_automations.py — prove the Fansly automation lanes with commands, not docs.

    ../venv/bin/python fansly/smoke_automations.py preflight
    ../venv/bin/python fansly/smoke_automations.py sweep
    ../venv/bin/python fansly/smoke_automations.py roundtrip

Exit 0 = pass. Every subcommand calls assert_session_alive() first: a non-NULL
`account_health.session_dead_at` is a stop, never something this script repairs.

Run from anywhere; paths resolve off this file, not the cwd.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVICE = os.path.join(ROOT, "service")
DB = os.path.join(SERVICE, "chatterly.db")
sys.path.insert(0, SERVICE)
sys.path.insert(0, os.path.join(HERE, "capture"))
os.chdir(SERVICE)  # the service modules resolve chatterly.db relative to cwd

ACCT = "700237824869654528"
FAN_ID = "900604711209099264"
GROUP = "900617058883547136"
RELAY = "http://127.0.0.1:8788"

_fail = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        _fail.append(name)
    return ok


def sql(query: str, params: tuple = ()) -> list[tuple]:
    import sqlite3
    con = sqlite3.connect(DB)
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


async def assert_session_alive(where: str) -> None:
    rows = sql("select session_dead_at from account_health where account_id=?", (ACCT,))
    dead = rows[0][0] if rows else None
    if dead:
        print(f"\n!! STOP ({where}): account_health.session_dead_at = {dead!r}")
        print(f"   row: {rows[0]!r}")
        raise SystemExit(2)
    print(f"  [PASS] session alive ({where}): session_dead_at is NULL")


def page_targets(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def relay_log_path() -> str:
    p = os.path.join(SERVICE, "relay.log")
    if os.path.exists(p):
        return p
    import glob
    cands = glob.glob("/tmp/fansly-*/relay.log")
    cands.sort(key=os.path.getmtime, reverse=True)
    if not cands:
        raise SystemExit("no relay log found")
    return cands[0]


# ── preflight ────────────────────────────────────────────────────────────
async def preflight() -> int:
    print("== preflight ==")
    await assert_session_alive("preflight start")

    # 1. relay answers 200 for THIS account. `/health` resolves the account from
    # X-Account-Id, so the bare call probes whichever account is active — here an
    # OF account behind a flaky proxy whose CONNECT-403 escapes _health_one's
    # OFAPIError catch as a 500. That says nothing about Fansly, so scope it.
    code = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30",
         "-H", f"X-Account-Id: {ACCT}", f"{RELAY}/health"],
        capture_output=True, text=True).stdout.strip()
    check(f"relay /health == 200 for account {ACCT}", code == "200", f"got {code}")

    # 2. the deepseek key belongs to THIS account's single owner. Count only.
    import tenant_keys
    owners = await tenant_keys.owners_of(ACCT)
    if not check(f"exactly one billable owner for {ACCT}", len(owners) == 1,
                 f"owners_of -> {len(owners)}"):
        key_ok = False
    else:
        n = sql("select count(*) from user_llm_keys where user_id=? and provider='deepseek'",
                (owners[0],))[0][0]
        key_ok = check("owner has exactly 1 deepseek key row", n == 1, f"count={n}")

    # 3. session_dead_at — already asserted above, recorded as a numbered check
    check("account_health.session_dead_at is NULL", True)

    # 4. both CDP ports list a fansly.com tab
    for port, who in ((9222, "fan"), (9223, "creator")):
        try:
            tabs = page_targets(port)
            hit = [t for t in tabs if "fansly.com" in (t.get("url") or "")]
            check(f"CDP :{port} ({who}) has a fansly.com tab", bool(hit),
                  (hit[0]["url"][:80] if hit else f"{len(tabs)} tabs, none fansly"))
        except Exception as e:
            check(f"CDP :{port} ({who}) has a fansly.com tab", False, repr(e)[:120])

    # 5. registry covers every kind the enabled rules name
    from automation_registry import load_automation_plugins, registered_kinds, is_registered
    load_automation_plugins()
    kinds = registered_kinds()
    print(f"  [info] registered_kinds() = {len(kinds)}")
    enabled = sql("select id, kind from automation_rules where account_id=? and is_enabled=1", (ACCT,))
    for rid, kind in enabled:
        check(f"rule {rid} kind={kind} registered", is_registered(kind))

    print(f"\npreflight: {'PASS' if not _fail else 'FAIL — ' + ', '.join(_fail)}")
    if not key_ok:
        print("LLM key not present yet — stopping. That is the user's action, not mine.")
    return 1 if _fail else 0


# ── sweep ────────────────────────────────────────────────────────────────
def honours_dry_run(kind: str) -> bool:
    from automation_registry import get_automation
    fn = get_automation(kind)
    if fn is None:
        return False
    try:
        return "dry_run" in inspect.getsource(sys.modules[fn.__module__])
    except Exception:
        return False


async def sweep() -> int:
    print("== sweep ==")
    await assert_session_alive("sweep start")
    from automation_registry import load_automation_plugins, registered_kinds
    from automation_executor import run_once
    load_automation_plugins()

    all_kinds = registered_kinds()
    swept = sorted(k for k in all_kinds if honours_dry_run(k))
    skipped = sorted(set(all_kinds) - set(swept))
    print(f"  {len(swept)} of {len(all_kinds)} kinds read dry_run; "
          f"{len(skipped)} not swept: {', '.join(skipped)}\n")

    rows = []
    for kind in swept:
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(run_once(ACCT, kind, payload={"dry_run": True}), 120)
            run_id = r.get("run_id")
        except Exception as e:
            rows.append((kind, "raised", time.monotonic() - t0, "", repr(e)[:200]))
            print(f"  {kind:28} raised  {time.monotonic()-t0:6.1f}s  {repr(e)[:100]}")
            continue
        secs = time.monotonic() - t0
        got = sql("select status, stats_json, error_text from automation_runs where id=?", (run_id,))
        status, stats, err = got[0] if got else ("?", "", "no run row")
        if err and "database is locked" in err:
            # contention with the 30s supervisor tick, not a finding — one retry
            print(f"  {kind:28} locked, retrying once")
            r = await asyncio.wait_for(run_once(ACCT, kind, payload={"dry_run": True}), 120)
            got = sql("select status, stats_json, error_text from automation_runs where id=?",
                      (r.get("run_id"),))
            status, stats, err = got[0] if got else ("?", "", "no run row")
        first = (err or "").strip().splitlines()[0] if err else ""
        rows.append((kind, status, secs, stats or "", first))
        print(f"  {kind:28} {status:7} {secs:6.1f}s  {(stats or '')[:90]}  {first[:80]}")

    await assert_session_alive("sweep end")
    out = os.path.join(HERE, "sweep_result.json")
    with open(out, "w") as f:
        json.dump({"swept": rows, "skipped": skipped}, f, indent=2)
    print(f"\nwrote {out}")
    bad = [r for r in rows if any(s in (r[4] or "") for s in
                                  ("LLMConfigError", "no 'deepseek' API key", "AttributeError"))]
    print(f"success bar (0 LLMConfigError/deepseek/AttributeError rows): "
          f"{'PASS' if not bad else 'FAIL — ' + ', '.join(r[0] for r in bad)}")
    return 1 if bad else 0


# ── roundtrip ────────────────────────────────────────────────────────────
async def drive_eval(port: int, expr: str):
    """Evaluate JS in the first fansly.com page on `port` (drive.py's own machinery)."""
    import websockets
    from drive import evaluate
    tabs = [t for t in page_targets(port) if "fansly.com" in (t.get("url") or "")]
    if not tabs:
        raise SystemExit(f"no fansly.com tab on :{port}")
    async with websockets.connect(tabs[0]["webSocketDebuggerUrl"], max_size=None) as ws:
        return await evaluate(ws, 1, expr)


async def roundtrip() -> int:
    print("== roundtrip ==")
    await assert_session_alive("roundtrip start")

    log = relay_log_path()
    print(f"  relay log: {log}")
    offset = os.path.getsize(log)
    base_msg = sql("select coalesce(max(message_id),0) from messages where account_id=? and fan_id=?",
                   (ACCT, int(FAN_ID)))[0][0]
    base_run = sql("select coalesce(max(id),0) from automation_runs where account_id=?", (ACCT,))[0][0]
    print(f"  baseline: newest message id={base_msg}  newest automation_run id={base_run}  log offset={offset}")

    await assert_session_alive("before fan DM")

    ts = int(time.time())
    js = """
    fetch('https://apiv3.fansly.com/api/v1/message?ngsw-bypass=true', {method:'POST',
      headers:{'content-type':'application/json',
        authorization: JSON.parse(localStorage.getItem('session_active_session')).token},
      body: JSON.stringify({type:1, attachments:[], likes:[], content:'prompt07 roundtrip %d',
        groupId:'%s', scheduledFor:0, inReplyTo:null, createdAt: Date.now()/1000})
    }).then(r=>r.text()).then(t=>t.slice(0,600))
    """ % (ts, GROUP)
    res = await drive_eval(9222, js)
    print(f"  fan POST -> {str(res)[:400]}")
    try:
        body = json.loads(res) if isinstance(res, str) else res
        msg_id = str(((body or {}).get("response") or {}).get("id"))
    except Exception:
        msg_id = ""
    print(f"  fan message id = {msg_id}")
    if not msg_id or msg_id == "None":
        print("  !! fan POST did not return a message id — stopping")
        return 1

    # 3. relay lines, past the offset only
    want = [f"msg={msg_id}", "w7_dispatch", "automation_run_ok"]
    kind = rid = None
    deadline = time.time() + 90
    seen = ""
    while time.time() < deadline:
        with open(log, "r", errors="replace") as f:
            f.seek(offset)
            seen = f.read()
        mine = [l for l in seen.splitlines() if ACCT in l]
        persisted = [l for l in mine if "chat_message persisted" in l and msg_id in l and "direction=in" in l]
        disp = [l for l in mine if "w7_dispatch" in l and msg_id in l]
        if persisted and disp:
            for l in disp:
                for tok in l.split():
                    if tok.startswith("kind="):
                        kind = tok.split("=", 1)[1]
            oks = [l for l in mine if "automation_run_ok" in l and (kind or "") in l]
            if oks:
                for tok in oks[-1].split():
                    if tok.startswith("run_id="):
                        rid = tok.split("=", 1)[1]
                print(f"  persisted: {persisted[-1].strip()[:200]}")
                print(f"  dispatch : {disp[-1].strip()[:200]}")
                print(f"  run_ok   : {oks[-1].strip()[:220]}")
                break
        await asyncio.sleep(5)
    print(f"  dispatched kind = {kind}   run_id = {rid}")
    if not rid:
        print("  !! timed out waiting for the relay. Last 40 lines for this account:")
        for l in [l for l in seen.splitlines() if ACCT in l][-40:]:
            print("   ", l[:220])
        return 1

    # 4. creator reply newer than baseline
    reply = None
    deadline = time.time() + 180
    while time.time() < deadline:
        rows = sql("select message_id, automation_kind, body, price_cents from messages "
                   "where account_id=? and fan_id=? and direction='out' and message_id>? "
                   "order by message_id desc limit 10", (ACCT, int(FAN_ID), base_msg))
        if rows:
            reply = rows[0]
        if reply:
            break
        await asyncio.sleep(5)
    print(f"  creator reply: {reply!r}")

    # 5. the run row, by id
    got = sql("select status, stats_json, error_text from automation_runs where id=?", (rid,))
    print(f"  run row {rid}: {got[0] if got else 'MISSING'}")

    # 6. cost line
    cost = sql("select day, provider, cost_cents, call_count from grok_daily_cost "
               "where account_id=? and provider='deepseek' order by day desc limit 1", (ACCT,))
    print(f"  cost: {cost[0] if cost else 'no deepseek row yet'}")

    await assert_session_alive("roundtrip end")

    stats = json.loads(got[0][1] or "{}") if got and got[0][1] else {}
    replies = stats.get("replies_sent")
    if got and got[0][0] == "ok" and (replies or 0) >= 1 and not stats.get("errors"):
        print("\nroundtrip: PASS")
        return 0
    print(f"\nroundtrip: FINDING — status={got[0][0] if got else '?'} stats={stats}")
    paused = sql("select automation_paused_until from fans where account_id=? and fan_id=?", (ACCT, FAN_ID))
    print(f"  fans.automation_paused_until = {paused[0][0] if paused else 'no fan row'}")
    return 1


CMDS = {"preflight": preflight, "sweep": sweep, "roundtrip": roundtrip}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in CMDS:
        raise SystemExit(f"usage: smoke_automations.py {{{'|'.join(CMDS)}}}")
    raise SystemExit(asyncio.run(CMDS[cmd]()))
