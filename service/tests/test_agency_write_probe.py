#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_cell_probe"))
import cell_probe  # noqa: E402

if cell_probe.mode() is None:
    cell_probe.activate("record")
cell_probe.set_mode("record")


import _harness  # noqa: E402

_harness.bootstrap()

import asyncio  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import chatter_identity_cache  # noqa: E402
import server  # noqa: E402
from db import write_telemetry  # noqa: E402
from db.engine import get_session, sync_database_url  # noqa: E402
from db.models import Chatter, User  # noqa: E402

IDS = fx.seed_two_agencies()
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
_REPO = Path(__file__).resolve().parents[2]


@contextmanager
def _mode(m: str):
    prev = cell_probe.mode()
    cell_probe.set_mode(m)
    try:
        yield
    finally:
        cell_probe.set_mode(prev)


def _found(table: str, op: str, func: str) -> list[dict]:
    return [h for h in cell_probe.hits() if cell_probe.is_required(h, table, op, func)]


def _age(model, row_id: str) -> None:
    async def run():
        async with get_session() as s:
            await s.execute(update(model).where(model.id == row_id)
                            .values(last_seen_at=datetime.utcnow() - timedelta(days=1)))
    asyncio.run(run())


def case_canary_forbidden_write_swallowed_is_still_recorded():
    uid = IDS["agency_b_owner"]

    async def canary() -> str:
        try:
            async with get_session() as s:
                await s.execute(update(User).where(User.id == uid).values(username="canary-renamed"))
        except Exception as e:  # noqa: BLE001
            return type(e).__name__
        return "none"

    async def name() -> str:
        async with get_session() as s:
            return (await s.execute(select(User.username).where(User.id == uid))).scalar_one()

    with cell_probe.scratch():
        with _mode("block"), write_telemetry.writer("canary"):
            swallowed = asyncio.run(canary())
        hit = [h for h in cell_probe.hits() if h["label"] == "canary"]
    assert swallowed == "IntegrityError", f"block mode let the canary write through ({swallowed})"
    assert asyncio.run(name()) == "agency_b_owner", "blocked write landed"
    assert hit and hit[0]["table"] == "users" and hit[0]["op"] == "UPDATE" and hit[0]["blocked"], hit


def case_scope_agency_tables_have_a_probe_class():
    assert all(cell_probe.table_class(name) in {"copied", "control"} for name in (
        "accounts", "grok_user_daily_cost", "proxies", "push_sent"))


def case_fixture_writes_are_not_recorded():
    before = len(cell_probe.hits())

    async def seed():
        async with get_session() as s:
            await s.execute(update(User).where(User.id == IDS["agency_master"]).values(username="agency_master"))
    with _mode("block"):
        asyncio.run(seed())
    assert len(cell_probe.hits()) == before, cell_probe.hits()[before:]


_SERVICE_GEN = """
async def touch_each(uids):
    from sqlalchemy import update
    from db.engine import get_session
    from db.models import User
    for uid in uids:
        async with get_session() as s:
            await s.execute(update(User).where(User.id == uid).values(last_seen_at=User.last_seen_at))
        yield uid
"""


def case_service_write_inside_an_async_generator_the_test_drives_is_recorded():
    ns: dict = {}
    exec(compile(_SERVICE_GEN, str(_REPO / "service" / "relay_host.py"), "exec"), ns)

    async def drive():
        return [u async for u in ns["touch_each"]([IDS["agency_master"]])]

    with cell_probe.scratch(), _mode("record"):
        asyncio.run(drive())
        sites = [h["site"] for h in cell_probe.hits() if h["table"] == "users" and "touch_each" in h["site"]]
    assert sites, "service write under a test-driven async generator was skipped as a fixture write"


def case_required_writers_are_recorded():
    _age(User, IDS["agency_a_owner"])
    _age(Chatter, IDS["chatter_a"])
    chatter_identity_cache.drop(IDS["chatter_a"])
    with _mode("record"):
        OWNER_A.get("/auth/me")
        CHATTER_A.get("/chatter/me")
        CHATTER_A.get("/admin/settings/roles", headers={"x-account-id": IDS["creator_a"]})
        fx.mint_token(OWNER_A)
        import account_health
        asyncio.run(account_health.mark_session_dead(IDS["creator_a"], "wrong_user"))
        asyncio.run(account_health.clear_session_dead(IDS["creator_a"]))
    missing = [k for k, v in cell_probe.REQUIRED.items() if not _found(*v)]
    assert not missing, f"required writers missing: {missing}\n" + "\n".join(
        f"{h['table']} {h['op']} {h['label']} {h['site']}" for h in cell_probe.hits())
    route = _found("users", "UPDATE", "_touch_last_seen")[0]["label"]
    assert route.startswith("http:GET /auth/me"), route


async def _call(fn, *a):
    r = fn(*a)
    if inspect.isawaitable(r):
        r = await r
    return r


def _ticks() -> dict:
    import account_health
    import badge_reads
    import db_retention
    import diag_api
    import img_api
    import link_prewarm
    import notifications_api
    import of_stats_daily
    import proxy_health
    import purchase_poll
    import push_send
    import runtime_switches
    import settings_api
    import shared_refresher
    import storyboard
    import sweep_cadence
    import tracking_stats
    import transaction_ingest
    import ultra_run
    import vault_collect
    import vault_upload
    from automation_executor import _drain_due_jobs_once
    from automations import full_ai_catchup
    from db.engine import optimize
    from seeds.funnels import seed_defaults_once

    async def fast_poll():
        for aid in await transaction_ingest.live_account_ids():
            await purchase_poll._poll_once(aid, "fast")

    return {
        "tracking-click-classify": lambda: tracking_stats.classify_old_rows_background(sync_database_url()),
        "runtime-switches-load": runtime_switches.load,
        "vault-sweep": lambda: asyncio.to_thread(vault_upload.sweep, server._load_client),
        "pump-supervisor": server._reconcile_pumps,
        "storyboard-evictor": storyboard._storyboard_lock_sweep,
        "img-cache-evictor": img_api._img_cache_sweep,
        "perflog-evictor": diag_api._perflog_sweep,
        "raw-json-evictor": db_retention._raw_json_sweep,
        "payload-size-cap": db_retention._payload_size_cap_sweep,
        "audit-retention-evictor": db_retention._audit_retention_sweep,
        "sqlite-optimize": optimize,
        "proxy-health-probe": lambda: asyncio.to_thread(proxy_health.probe_all),
        "clock-in-missed": notifications_api.tick,
        "link-figures-prewarm": link_prewarm.prewarm_all,
        "vault-collect": vault_collect.tick,
        "tx-ingest-supervisor": transaction_ingest.supervisor_cycle,
        "tx-ingest-fast-poll": fast_poll,
        "of-stats-daily": lambda: of_stats_daily.tick(pause_s=0),
        "automation-exec": _drain_due_jobs_once,
        "chat-sweep-cadence": sweep_cadence.tick,
        "shared-refresher": shared_refresher.tick,
        "badge-reads": badge_reads.tick,
        "full-ai-catchup-boot": full_ai_catchup.boot,
        "push-send": push_send._prune_sent,
        "boot:load-write-gate": account_health.load_write_gate,
        "boot:seed-funnels": seed_defaults_once,
        "boot:role-enforcement": settings_api.migrate_role_enforcement_once,
        "boot:bookmarks-page": settings_api.migrate_bookmarks_page_once,
        "boot:ultra-recover": ultra_run.recover,
    }


NOT_TICKED = {"persist-worker": "queue consumer with no timer: drained per inbound event, which the event tests drive"}


@contextmanager
def _loopback_only():
    real_connect, real_gai = socket.socket.connect, socket.getaddrinfo

    def guard(host):
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            raise ConnectionRefusedError(f"agency write probe: no network ({host})")

    def connect(self, addr):
        guard(addr[0] if isinstance(addr, tuple) else addr)
        return real_connect(self, addr)

    def getaddrinfo(host, *a, **kw):
        guard(host)
        return real_gai(host, *a, **kw)

    socket.socket.connect, socket.getaddrinfo = connect, getaddrinfo
    try:
        yield
    finally:
        socket.socket.connect, socket.getaddrinfo = real_connect, real_gai


def case_every_registered_job_tick_runs_once_with_its_label():
    ticks = _ticks()
    with _loopback_only():
        uncovered = cell_probe.registered_jobs(server) - ticks.keys() - NOT_TICKED.keys()
    assert not uncovered, f"registered job with no tick here: {sorted(uncovered)}"
    ran, failed = [], {}

    async def run_all():
        for name, tick in ticks.items():
            with write_telemetry.writer(name if name.startswith("boot:") else f"job:{name}"):
                try:
                    await asyncio.wait_for(_call(tick), timeout=30)
                except Exception as e:  # noqa: BLE001
                    failed[name] = f"{type(e).__name__}: {e}"[:200]
            ran.append(name)

    with _mode("record"), _loopback_only():
        asyncio.run(run_all())
    assert ran == list(ticks), ran
    assert not failed, failed
    print(f"  {len(ran)} ticks run, {len(failed)} raised; not ticked: {NOT_TICKED}")


def case_thread_pool_work_carries_the_route_label():
    async def in_pool():
        loop = asyncio.get_running_loop()

        def write():
            import sqlalchemy as sa
            eng = sa.create_engine(sync_database_url())
            with eng.begin() as c:
                c.execute(sa.text("UPDATE users SET last_seen_at = last_seen_at WHERE id = :i"),
                          {"i": IDS["agency_master"]})
        await loop.run_in_executor(None, write)

    with cell_probe.scratch(), _mode("record"), write_telemetry.writer("job:pool-probe"):
        asyncio.run(in_pool())
        labels = {h["label"] for h in cell_probe.hits() if h["table"] == "users"}
    assert "job:pool-probe" in labels, labels


_THREAD_WRITER = """
def run(url, uid):
    import sqlalchemy as sa
    with sa.create_engine(url).begin() as c:
        c.execute(sa.text("UPDATE users SET last_seen_at = last_seen_at WHERE id = :i"), {"i": uid})
"""


def case_thread_hits_keep_their_stack():
    import threading
    ns: dict = {}
    exec(compile(_THREAD_WRITER, str(_REPO / "service" / "relay_host.py"), "exec"), ns)
    with cell_probe.scratch(), _mode("record"):
        t = threading.Thread(target=ns["run"], args=(sync_database_url(), IDS["agency_master"]))
        t.start()
        t.join()
        thread_hits = [h for h in cell_probe.hits() if h["label"] == "thread"]
    assert thread_hits and thread_hits[0].get("stack"), thread_hits


def case_env_unset_installs_nothing_and_drops_leftovers():
    db = Path(tempfile.mkdtemp(prefix="probe_off_")) / "t.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE users (id TEXT)")
    c.execute("CREATE TABLE fans (id TEXT)")
    for ddl in cell_probe.trigger_ddl(["users", "fans"]).values():
        c.execute(ddl)
    c.execute(f"CREATE TRIGGER {cell_probe.TRIGGER_PREFIX}gone_insert BEFORE INSERT ON fans BEGIN SELECT 1; END")
    with cell_probe._real_connect(db) as other:
        permanent = other.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        assert permanent == [(f"{cell_probe.TRIGGER_PREFIX}gone_insert",)], permanent
    assert cell_probe.sync_triggers(lambda sql: c.execute(sql).fetchall(), on=False) == 4
    left = c.execute("SELECT name FROM sqlite_master WHERE type='trigger' UNION ALL "
                     "SELECT name FROM sqlite_temp_master WHERE type='trigger'").fetchall()
    assert left == [], left
    c.close()

    env = {k: v for k, v in os.environ.items() if not k.startswith("CELL_PROBE")}
    env["PYTHONPATH"] = str(Path(cell_probe.__file__).parent)
    child = (
        "import sys, sqlite3; sys.argv=['probe_off']\n"
        "import _harness; _harness.bootstrap()\n"
        "import db.engine as e, sqlalchemy as sa\n"
        "c = sqlite3.connect(str(_harness.DB_PATH))\n"
        "n = c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'cell_probe_%'\").fetchone()[0]\n"
        "print('TRIGGERS', n, 'PATCHED', sqlite3.connect.__module__ == 'cell_probe')\n"
    )
    out = subprocess.run([sys.executable, "-c", child], cwd=Path(__file__).parent, env=env,
                         capture_output=True, text=True, timeout=120)
    line = [x for x in out.stdout.splitlines() if x.startswith("TRIGGERS")]
    assert line == ["TRIGGERS 0 PATCHED False"], (line, out.stderr[-2000:])


def case_fold_unions_runs_flags_send_path_and_fails_on_a_crashed_script():
    sys.path.insert(0, str(_REPO / "scripts"))
    import agency_write_fold as fold
    from _probe_run_fixture import seed_probe_run
    root = Path(tempfile.mkdtemp(prefix="probe_fold_"))
    req = [{"table": t, "op": op, "label": "http:GET /x", "class": "copied", "site": f"a.py:1:{fn}",
            "frames": [f"a.py:1:{fn}"], "n": 1, "test": "test_a", "mode": "record"}
           for t, op, fn in cell_probe.REQUIRED.values()]
    send = {"table": "users", "op": "UPDATE", "label": "job:x", "class": "copied", "site": "automations/autoreply.py:9:f",
            "frames": ["automations/autoreply.py:9:f"], "n": 2, "test": "test_b", "mode": "block"}
    local = send | {"table": "actions", "class": "local"}
    middleware = send | {"label": "http:POST /unrelated", "frames": ["server.py:1:audit_middleware"]}
    assert fold.send_reason(middleware, frozenset()) is None
    paid = send | {"frames": ["automations/full_ai_ppv.py:434:send_priced"]}
    assert fold.send_reason(paid, frozenset()) == "send module automations/full_ai_ppv.py"
    for m, rows in (("block", [send, local]), ("record", req)):
        seed_probe_run(root / m, m)
        (root / m / "test_cell_scope.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "block" / "test_agency_write_probe.jsonl").unlink()
    assert fold.fold(root / "block", root / "record", root, send_routes=frozenset()) == 1, "block run lost test_b's file but the fold passed"
    inv = json.loads((root / "inventory.json").read_text())
    assert inv["crashed"] == {"block": ["test_agency_write_probe"]}, inv["crashed"]
    assert inv["required_missing"] == [], inv["required_missing"]
    assert len(inv["diff"]["block_only"]) == 2 and len(inv["diff"]["record_only"]) == len(req), inv["diff"]
    sp = json.loads((root / "send_path.json").read_text())
    assert sp["replan_07"] and [h["why"] for h in sp["hits"]] == ["send module automations/autoreply.py"], sp
    (root / "block" / "test_agency_write_probe.jsonl").touch()
    assert fold.fold(root / "block", root / "record", root, send_routes=frozenset()) == 0
    rc = root / "record" / "_rc.tsv"
    rc.write_text(rc.read_text().replace("0\ttest_cell_scope\n", "1\ttest_cell_scope\n"))
    assert fold.fold(root / "block", root / "record", root, send_routes=frozenset()) == 1
    manifest = root / "block" / "_scripts.txt"
    manifest.write_text("test_cell_scope\n")
    try:
        fold.fold(root / "block", root / "record", root, send_routes=frozenset())
    except SystemExit as error:
        assert "incomplete script manifest" in str(error), error
    else:
        raise AssertionError("filtered run certified")


def case_fold_refuses_one_run_fed_as_both_modes():
    sys.path.insert(0, str(_REPO / "scripts"))
    import agency_write_fold as fold
    from _probe_run_fixture import seed_probe_run
    root = Path(tempfile.mkdtemp(prefix="probe_fold_modes_"))
    seed_probe_run(root / "record", "record")
    seed_probe_run(root / "block", "block")
    for m in ("block", "record"):
        (root / m / "_run.json").write_text(json.dumps({"mode": m, "run_id": "one-run"}))
    for block, want in ((root / "record", "want a block run"), (root / "block", "same probe run")):
        try:
            fold.fold(block, root / "record", root, send_routes=frozenset())
        except SystemExit as error:
            assert want in str(error), error
        else:
            raise AssertionError(f"{block.name} as the block run certified")


if __name__ == "__main__":
    _harness.run()
