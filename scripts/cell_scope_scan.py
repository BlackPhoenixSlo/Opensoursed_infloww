#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service"
TESTS = SERVICE / "tests"
SCOPE = SERVICE / "cell_scope.json"
PROBE = ROOT / ".scratch" / "agency-scale-out" / "probe" / "inventory.json"

sys.path[:0] = [str(TESTS / "_cell_probe"), str(SERVICE)]
import cell_probe  # noqa: E402

ROUTE_SCOPES = ("model", "model_obj", "agency", "fanin", "cell_local", "public", "closed")
ROUTE_KEYS = ("header", "path", "query", "body", "object", "slug", "host", "share", "none")
AUTHS = ("session", "chatter", "bearer", "share", "public")
TABLE_SCOPES = ("model", "model_via", "pair", "agency", "cache", "mixed", "cell_local")
FILE_SCOPES = ("model", "cell_local", "cache")
JOB_SCOPES = ("model", "agency", "cell_local")
ITERATES = ("registry", "db", "none")
HUMAN = {
    "routes": ("scope", "key", "auth", "partial", "why"),
    "tables": ("scope", "via", "why"),
    "files": ("scope", "moves", "secret", "why"),
    "jobs": ("scope", "iterates", "why"),
}

PROFILES = {"default": {}, "fleet": {"FLEET_SECRET": "x" * 40}, "cells": "data", "cells-control": "control"}

PUBLIC = {
    "/livez": ("cell_local", "none", "liveness of this Relay"),
    "/health": ("cell_local", "header", "health of this Relay and the named Creator"),
    "/events": ("cell_local", "none", "per-Cell SSE stream; the Front door fans out per Cell (ticket 08)"),
    "/": ("cell_local", "none", "Relay banner"),
    "/t/{slug}": ("public", "slug", "tracking redirect; slug needs an agency-unique id + Front door lookup (ticket 09)"),
    "/share/{key}/data": ("public", "share", "share link; key needs a Front door lookup (ticket 09)"),
    "/img/by-hash/{h}": ("cell_local", "none", "content-addressed image cache on this Relay"),
}
CROSS_CUTTING = {
    "site": {(None, name) for name in (
        "_touch_last_seen", "_session_identity", "audit_middleware", "_write_action",
        "get_or_create_mirror_employee",
    )} | {("token_auth.py", "_touch")},
    "frames": {(None, "get_or_create_mirror_employee")},
}
AGENCY_EXCEPTION = "Agency write exception: "
AGENCY_RULES = ("agency_writes", "agency_prefix")
AGENCY_PREFIXES = (
    "/auth/", "/chatter/", "/push/", "/admin/employees", "/admin/employee-groups", "/admin/chatters",
    "/admin/users", "/admin/shifts", "/admin/clock", "/admin/payroll", "/admin/settings", "/admin/notifications",
    "/admin/roles", "/admin/permissions", "/admin/blacklist", "/admin/sensitive-words", "/admin/llm-keys",
    "/admin/owner-tokens", "/admin/bio-pages", "/admin/ultra", "/admin/me", "/admin/agency-notifications",
    "/admin/assistant", "/admin/my-llm-keys", "/admin/impersonate", "/admin/mcp",
)
FANIN_HINTS = ("all_accounts", "accounts", "account_ids")
CELL_LOCAL_PREFIXES = (
    "/lanes-panel", "/admin/diag", "/admin/perf", "/admin/lanes", "/admin/runtime-switches", "/admin/proxies",
    "/admin/proxy", "/admin/fleet", "/fleet", "/admin/img-cache", "/admin/_debug", "/admin/coalesce",
    "/admin/storyboard/stats", "/admin/events/stats", "/admin/priority-lanes", "/admin/system", "/admin/streams",
    "/img/scrub", "/admin/errors", "/admin/secrets", "/admin/automation-kinds", "/admin/reports/catalogue",
    "/admin/ingest/transactions/health",
)
CACHE_TABLE = re.compile(r"(^|_)(cache|cached|perflog|raw_json)(_|$)")
LOCAL_TABLES = {"alembic_version", "data_migrations", "cell_meta"}

JOBS = {
    "agency-copy-poll": ("cell_local", "none", "data Cell long-polls control for the Agency copy; writes only copied tables and cell_meta"),
    "reservation-activation-retry": ("cell_local", "registry", "reasserts active reservations for connected Creators owned by this data Cell"),
    "bell-notices-to-control": ("cell_local", "none", "data Cell posts its agency_notifications rows to control's bell; reads only that table"),
    "grant-age-watch": ("cell_local", "none", "data Cell past its Grant age ends open streams; reads only memory"),
    "pump-supervisor": ("model", "registry", "one WS pump per Creator with a session dir"),
    "tx-ingest-supervisor": ("model", "db", "per-Creator ledger ingest"),
    "tx-ingest-fast-poll": ("model", "db", "per-Creator purchase poll from live_account_ids"),
    "of-stats-daily": ("model", "db", "per-Creator OF stats snapshot"),
    "automation-exec": ("model", "db", "drains due automation jobs for every Creator in the DB"),
    "chat-sweep-cadence": ("model", "registry", "per-Creator chat sweep"),
    "shared-refresher": ("model", "db", "per-Creator shared fetch refresher"),
    "badge-reads": ("model", "registry", "per-Creator unread badge"),
    "full-ai-catchup-boot": ("model", "db", "per-Creator Full AI catch-up after boot"),
    "vault-collect": ("model", "registry", "per-Creator vault collect"),
    "link-figures-prewarm": ("model", "registry", "per-Creator link figures"),
    "proxy-health-probe": ("cell_local", "none", "probes this Relay's proxies"),
    "proxy-rebalance": ("cell_local", "none", "moves this Relay's Creators between its proxies"),
    "clock-in-missed": ("agency", "db", "agency shifts and clock events; control Cell only"),
    "leak-watch-sync": ("agency", "db", "pushes each Agency's Leak watches to the removal service; never started in "
                                        "cell mode (leak_tracker.jobs_on)"),
    "leak-watch-tombstones": ("agency", "db", "lands each Agency's Leak watch deletes at the removal service; never "
                                              "started in cell mode (leak_tracker.jobs_on)"),
    "push-send": ("cell_local", "none", "prunes sent push rows on this Relay"),
    "persist-worker": ("cell_local", "none", "drains this Relay's inbound event queue"),
    "vault-sweep": ("cell_local", "none", "vault spool sweep on this Relay"),
    "runtime-switches-load": ("cell_local", "none", "loads runtime switches into this process"),
    "tracking-click-classify": ("cell_local", "none", "classifies this DB's old tracking clicks"),
    "storyboard-evictor": ("cell_local", "none", "file cache eviction"),
    "img-cache-evictor": ("cell_local", "none", "file cache eviction"),
    "perflog-evictor": ("cell_local", "none", "perflog eviction"),
    "raw-json-evictor": ("cell_local", "none", "row retention on this DB"),
    "payload-size-cap": ("cell_local", "none", "row retention on this DB"),
    "audit-retention-evictor": ("cell_local", "none", "row retention on this DB"),
    "sqlite-optimize": ("cell_local", "none", "PRAGMA optimize on this DB"),
}

FILES = {
    "sessions/accounts/{account_id}/meta.json": ("model", True, False, ["lit:meta.json"], "per-Creator session meta"),
    "sessions/accounts/{account_id}/latest.json": ("model", True, False, ["lit:latest.json"], "per-Creator latest capture"),
    "sessions/accounts/{account_id}/{platform session file}": (
        "model", True, True, ["session_files"], "per-Creator platform session (platforms.SESSION_FILES)"),
    "sessions/active.json": ("cell_local", False, False, ["lit:active.json"],
                             "active-account pointer; cell mode never falls back to it (ticket 09 item 3)"),
    "sessions/.migrated": ("cell_local", False, False, ["lit:.migrated"], "legacy session migration marker"),
    "sessions/": ("cell_local", False, True, ["lit:sessions", "lit:accounts"], "session root of this Relay"),
    "proxies.json": ("cell_local", False, True, ["lit:proxies.json"], "this Relay's proxy list"),
    "lane_config.json": ("cell_local", False, False, ["lit:lane_config.json", "env:LANE_CONFIG_PATH"],
                         "this Relay's concurrency ceilings"),
    "dbdata/": ("cell_local", False, True, ["lit:dbdata", "env:RELAY_DB_PATH"], "this Cell's SQLite DB"),
    ".env": ("cell_local", False, True, ["lit:.env"], "this Relay's env file"),
    "secrets.json": ("cell_local", False, True, ["lit:secrets.json"], "this Relay's secrets store"),
    "$VAPID_KEY_FILE": ("cell_local", False, True, ["env:VAPID_KEY_FILE"], "Web Push key; one per Relay, never rotates"),
    "$SETTINGS_BACKUP_DIR/": ("cell_local", False, False, ["env:SETTINGS_BACKUP_DIR"], "settings backups"),
    "$VAULT_SPOOL_DIR/": ("cache", False, False, ["env:VAULT_SPOOL_DIR", "lit:vault_spool", "lit:locks", "lit:incoming"],
                          "vault upload spool, its locks and staging"),
    "$VAULT_SPOOL_DIR/drive_memo.json": ("cell_local", False, False, ["lit:drive_memo.json"], "Drive import memo"),
    "$VAULT_THUMB_DIR/": ("cache", False, False, ["env:VAULT_THUMB_DIR"], "vault thumbnails"),
    "$VAULT_POSTER_DIR/": ("cache", False, False, ["env:VAULT_POSTER_DIR"], "vault posters"),
    "$VAULT_IMAGE_DIR/": ("cache", False, False, ["env:VAULT_IMAGE_DIR"], "vault images"),
    "$IMG_CACHE_DIR/": ("cache", False, False, ["env:IMG_CACHE_DIR"], "image cache"),
    "$STORYBOARD_DIR/": ("cache", False, False, ["env:STORYBOARD_DIR"], "storyboard cache"),
    "$BIO_FILES_DIR/": ("cache", False, False, ["env:BIO_FILES_DIR"], "bio page uploads; bio rows are control (ticket 07)"),
    "$OF_CALL_STATS_PATH": ("cell_local", False, False, ["env:OF_CALL_STATS_PATH"], "OF call counters"),
    "$OF_API_LOG_PATH": ("cell_local", False, False, ["env:OF_API_LOG_PATH"], "OF API log"),
    "$CONVO_REVIEW_APP_DIR/": ("cell_local", False, False, ["env:CONVO_REVIEW_APP_DIR"], "convo review app build"),
}
_ENV_PATH = re.compile(r'environ(?:\.get)?\s*[\(\[]\s*"([A-Z0-9_]+_(?:DIR|PATH|FILE))"')
_LIT_PATH = re.compile(r'\b\w*(?:HERE|ROOT|DIR|adir)\w*\s*/\s*"([\w.-]+)"|_account_path\([^,]+,\s*"([\w.-]+)"')
_NOT_DATA = {"migrations"}


def _harness_env(profile: str, tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CELL_PROBE", "OI_", "FLEET_"))}
    env["TMPDIR"] = str(tmp)
    spec = PROFILES[profile]
    if isinstance(spec, str):
        placement = tmp / "placement.json"
        placement.write_text(json.dumps({"schema": 1, "agency": "acme", "min_cell_proto": 1, "cells": {"scan": {"role": spec}}}))
        env.update({"OI_CELL_MAP": str(placement), "OI_CELL_ID": "scan", "OI_CELL_ROLE": spec,
                    "OI_ACCOUNTS": "", "OI_EPOCH": "1"})
    else:
        env.update(spec)
    return env


def route_facts(app) -> dict[str, dict]:
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from starlette.routing import Mount

    out = {}
    def routes_in(routes, prefix=""):
        for route in routes:
            yield prefix, route
            if isinstance(route, Mount):
                yield from routes_in(route.routes, prefix + route.path)

    for prefix, r in routes_in(app.routes):
        path = prefix + r.path
        ep = getattr(r, "endpoint", None)
        where = {"file": _rel(getattr(ep, "__code__", None)), "func": getattr(ep, "__name__", None)}
        if isinstance(r, APIRoute):
            d = r.dependant
            facts = where | {
                "kind": "api",
                "path_params": sorted(p.name for p in d.path_params),
                "query": sorted(p.name for p in d.query_params if "account" in p.name),
                "headers": sorted(p.alias.lower() for p in d.header_params if "account" in p.alias.lower()),
                "body": _body_account_fields(d),
                "calls": _account_calls(ep),
            }
            for m in sorted(r.methods or ()):
                out[f"{m} {path}"] = facts
        elif isinstance(r, APIWebSocketRoute):
            out[f"WS {path}"] = where | {"kind": "ws"}
        elif isinstance(r, Mount):
            out[f"MOUNT {path}"] = {"kind": "mount"}
        else:
            for m in sorted(getattr(r, "methods", None) or ("GET",)):
                out[f"{m} {path}"] = where | {"kind": "docs"}
    return out


_CALLS = re.compile(r"\b(assert_account_owned|clamp_account_filter|require_actor_account_ids|_require_actor_account_ids"
                    r"|owned_account_ids|_resolve_account_id|list_accounts)\(")
_FANIN_CALLS = {"clamp_account_filter", "require_actor_account_ids", "_require_actor_account_ids", "owned_account_ids",
                "list_accounts"}


def _account_calls(ep) -> list[str]:
    import inspect
    try:
        return sorted(set(_CALLS.findall(inspect.getsource(ep))))
    except (OSError, TypeError):
        return []


def _body_account_fields(d) -> list[str]:
    out = set()
    for p in d.body_params:
        ann = getattr(p, "type_", None) or getattr(p.field_info, "annotation", None)
        out |= {f for f in getattr(ann, "model_fields", {}) if "account" in f}
        if "account" in p.name:
            out.add(p.name)
    return sorted(out)


def _rel(code) -> str | None:
    if code is None:
        return None
    try:
        return str(Path(code.co_filename).resolve().relative_to(SERVICE))
    except ValueError:
        return Path(code.co_filename).name


def table_facts(sync_url: str) -> dict[str, dict]:
    import sqlite3

    from db.models import Base

    path = sync_url.split("sqlite:///", 1)[1]
    with sqlite3.connect(path) as c:
        schema = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        cols = {t: {r[1] for r in c.execute(f'PRAGMA table_info("{t}")')} for t in schema}
        fks = {t: sorted({(r[3], r[2]) for r in c.execute(f'PRAGMA foreign_key_list("{t}")')}) for t in schema}
    models = set(Base.metadata.tables)
    for name, t in Base.metadata.tables.items():
        cols.setdefault(name, {c.name for c in t.columns})
        fks.setdefault(name, sorted({(e.parent.name, e.column.table.name) for e in t.foreign_keys}))
    out = {}
    for name in sorted(models | schema):
        out[name] = {"models": name in models, "schema": name in schema,
                     "account_col": "account_id" in cols.get(name, ()),
                     "fks": [f"{col}->{ref}" for col, ref in fks.get(name, [])]}
    return out


def job_facts(server) -> dict[str, dict]:
    import automation_registry

    out = {name: {"kind": "task"} for name in sorted(cell_probe.registered_jobs(server))}
    automation_registry.load_automation_plugins()
    for kind in automation_registry.registered_kinds():
        out[f"automation:{kind}"] = {"kind": "automation"}
    return out


def _facts_child(profile: str) -> None:
    sys.path[:0] = [str(TESTS), str(SERVICE)]
    import _harness

    _harness.bootstrap()
    import server
    from db.engine import sync_database_url

    if extra := os.environ.get("CELL_SCOPE_EXTRA_ROUTE"):
        server.app.add_api_route(extra, lambda: None, methods=["GET"])
    doc = {"routes": route_facts(server.app)}
    if profile == "default":
        doc["tables"] = table_facts(sync_database_url())
        doc["jobs"] = job_facts(server)
    print("CELL_SCOPE_FACTS " + json.dumps(doc))


def _child_python() -> str:
    venv = ROOT / "venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


@cache
def live_facts() -> dict:
    routes: dict[str, dict] = {}
    doc: dict = {}
    with tempfile.TemporaryDirectory(prefix="cell_scope_") as tmp:
        procs = {}
        for profile in PROFILES:
            (Path(tmp) / profile).mkdir()
            procs[profile] = subprocess.Popen(
                ["nice", "-n", "10", _child_python(), str(Path(__file__).resolve()), "--_facts", profile], cwd=SERVICE,
                env=_harness_env(profile, Path(tmp) / profile), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True)
        try:
            outs = {profile: (p, *p.communicate(timeout=300)) for profile, p in procs.items()}
        finally:
            for p in procs.values():
                if p.poll() is None:
                    p.kill()
                    p.wait()
    for profile, (p, stdout, stderr) in outs.items():
        line = next((ln for ln in stdout.splitlines() if ln.startswith("CELL_SCOPE_FACTS ")), None)
        if p.returncode or line is None:
            raise SystemExit(f"scan of profile {profile} failed (rc {p.returncode}):\n{stderr[-3000:]}")
        got = json.loads(line.split(" ", 1)[1])
        for k, f in got.pop("routes").items():
            routes.setdefault(k, f | {"profiles": []})["profiles"].append(profile)
        doc.update(got)
    for f in routes.values():
        if len(f["profiles"]) == len(PROFILES):
            del f["profiles"]
    doc["routes"] = routes
    doc["files"] = file_sources()
    return doc


def file_sources() -> set[str]:
    found = {"session_files"}
    for f in SERVICE.rglob("*.py"):
        rel = f.relative_to(SERVICE).parts
        if rel[0] in ("tests", "scripts") or "node_modules" in rel:
            continue
        src = f.read_text(errors="replace")
        found |= {f"env:{m}" for m in _ENV_PATH.findall(src)}
        found |= {f"lit:{a or b}" for a, b in _LIT_PATH.findall(src) if (a or b) not in _NOT_DATA}
    return found


def load_probe(paths: list[Path]) -> dict:
    if not paths:
        paths = [PROBE]
    if len(paths) == 1:
        try:
            return json.loads(paths[0].read_text())
        except FileNotFoundError:
            raise SystemExit(f"missing agency-write probe inventory: {paths[0]}") from None
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import agency_write_fold
    from send_site_inventory import inventory

    routes = inventory().route_labels(live_facts()["routes"])
    with tempfile.TemporaryDirectory(prefix="cell_scope_fold_") as tmp:
        rc = agency_write_fold.fold(paths[0], paths[1], Path(tmp), send_routes=routes)
        if rc:
            raise SystemExit("probe fold failed; fix the probe runs first")
        return json.loads((Path(tmp) / "inventory.json").read_text())


def writers_by_table(inv: dict) -> dict[str, list[dict]]:
    out: dict[str, dict[tuple, dict]] = {}
    for w in [*inv.get("writes", []), *inv.get("thread", [])]:
        site = re.sub(r":\d+:", ":", w["site"])
        row = out.setdefault(w["table"], {}).setdefault((w["op"], w["label"], site),
                                                         {"op": w["op"], "label": w["label"], "site": site, "modes": []})
        row["modes"] = sorted(set(row["modes"]) | set(w["modes"]))
    return {t: [rows[k] for k in sorted(rows)] for t, rows in out.items()}


def agency_writes_by_route(inv: dict) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for w in inv.get("writes", []):
        locations = {"site": [w["site"]], "frames": w.get("frames", ())}
        if any((module, func) in CROSS_CUTTING[field] or (None, func) in CROSS_CUTTING[field]
               for field, entries in locations.items()
               for entry in entries
               for module, func in [(entry.split(":", 1)[0], entry.rsplit(":", 1)[-1])]):
            continue
        if w["label"].startswith("http:") and w["class"] != "local":
            out.setdefault(w["label"][5:], set()).add(w["table"])
    return {k: sorted(v) for k, v in out.items()}


def _auth(path: str, unauth: set[str]) -> str:
    if path in unauth or path in PUBLIC or path.startswith(("/.well-known", "/docs", "/redoc", "/openapi")):
        return "public"
    if path.startswith("/share/"):
        return "share"
    if path.startswith("/chatter/"):
        return "chatter"
    if path.startswith(("/admin/mcp", "/fleet", "/admin/fleet", "/api/cell/reservations/")):
        return "bearer"
    if re.search(r"/(sign-in|oauth|register|invite)(/|$)", path):
        return "public"
    return "session"


def draft_route(key: str, f: dict, agency_writes: dict, unauth: set[str]) -> dict:
    method, _, path = key.partition(" ")
    writes = agency_writes.get(f"{method} {path}", [])
    hint = {k: v for k, v in f.items() if v not in (None, [], False)}
    if writes:
        hint["agency_writes"] = writes
    auth = _auth(path, unauth)

    def row(rule, scope, key_, why, partial=None):
        r = {"scope": scope, "key": key_, "auth": auth}
        if partial:
            r["partial"] = partial
        return r | {"why": why, "hint": hint | {"rule": rule}}

    if writes:
        return row("agency_writes", "agency", "none", f"probe saw agency writes: {', '.join(writes)}")
    if any(path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/") for prefix in AGENCY_PREFIXES):
        return row("agency_prefix", "agency", "none", "agency people/settings; writes go to the control Cell")
    if f["kind"] == "docs":
        return row("docs", "closed", "none", "API docs; switched off in cell mode (ticket 09 item 3)")
    if f["kind"] == "mount":
        return row("mount", "closed", "none", "static mount; not an API route")
    if path in unauth:
        return row("unauth", "cell_local", "none", "no-auth lanes panel of this Relay (_UNAUTHENTICATED_PATHS)")
    if path in PUBLIC:
        scope, k, why = PUBLIC[path]
        return row("public", scope, k, why)
    if path.startswith("/.well-known"):
        return row("public", "public", "none", "OAuth discovery document")
    if "account_id" in f.get("path_params", ()):
        return row("path", "model", "path", "names its Creator in the path")
    if any(q in FANIN_HINTS for q in f.get("query", ())):
        return row("fanin", "fanin", "query", "reads several Creators at once; total marks missing ones", "mark")
    if "account_id" in f.get("query", ()):
        return row("query", "model", "query", "names its Creator in ?account_id")
    body, calls = f.get("body", []), set(f.get("calls", ()))
    if "account_id" in body:
        return row("body", "model", "body", "names its Creator in the body (account_id)")
    if body:
        return row("body_fanin", "fanin", "body", f"names several Creators in the body ({', '.join(body)})", "mark")
    if path.startswith("/api/of/"):
        return row("api_of", "model", "header", "OF proxy route; Creator from X-Account-Id")
    if "x-account-id" in f.get("headers", ()):
        return row("header", "model", "header", "names its Creator in X-Account-Id")
    if "assert_account_owned" in calls:
        return row("owned_check", "model", "body", "checks one named Creator is the actor's (assert_account_owned)")
    if "_resolve_account_id" in calls:
        return row("resolve", "model", "header", "resolves its Creator from X-Account-Id / ?account_id")
    if calls & _FANIN_CALLS:
        return row("fanin_calls", "fanin", "none", f"reads every Creator the actor owns ({', '.join(sorted(calls & _FANIN_CALLS))})",
                   "mark")
    if path.startswith(CELL_LOCAL_PREFIXES):
        return row("cell_local", "cell_local", "none", "about this Relay process, not a Creator")
    objs = [p for p in f.get("path_params", ()) if p.endswith("id") or p in ("pid", "lid", "token")]
    if objs:
        return row("object", "model_obj", "object", f"Creator from the object behind {{{objs[0]}}}")
    return row("unclassified", "closed", "none", "no rule matched; default closed until P1 decides (ticket 09)")


def draft_table(name: str, f: dict, writers: list[dict], facts: dict) -> dict:
    cls = cell_probe.table_class(name)
    hint = {k: v for k, v in f.items() if v not in ([], False)} | ({"probe_class": cls} if cls else {})

    def row(rule, scope, why, via=None):
        r = {"scope": scope} | ({"via": via} if via else {}) | {"why": why, "hint": hint | {"rule": rule}}
        return r | ({"writers": writers} if writers else {})

    if name == "s4s_requests":
        return row("pair", "pair", "two Creators per row; cross-cell S4S closed in v1 (ticket 09)")
    if name in LOCAL_TABLES or not f["models"]:
        return row("local", "cell_local", "per-DB bookkeeping owned by migrations")
    if cls in ("copied", "control"):
        if f["account_col"]:
            return row("agency_account", "mixed", f"agency {cls} row keyed by Creator (ticket 07 item 1)")
        return row("agency_class", "agency", f"agency {cls} table (ticket 07 item 1)")
    if f["account_col"]:
        return row("account_col", "model", "has account_id")
    via = _via(name, facts)
    if via:
        return row("model_via", "model_via", f"Creator via {' → '.join(via)}", via)
    if CACHE_TABLE.search(name):
        return row("cache", "cache", "derived cache; rebuildable per Cell")
    return row("no_account", "agency", "no account link; agency-wide by default")


def _via(name: str, facts: dict) -> list[str] | None:
    seen, frontier = {name}, [(name, [])]
    while frontier:
        nxt = []
        for t, chain in frontier:
            for fk in facts[t]["fks"]:
                col, ref = fk.split("->")
                if ref in seen or ref not in facts:
                    continue
                path = chain + [f"{t}.{col}->{ref}"]
                if facts[ref]["account_col"]:
                    return path
                seen.add(ref)
                nxt.append((ref, path))
        frontier = nxt
    return None


UNREVIEWED_JOB = "new job; not reviewed yet"
UNREVIEWED_FILE = "new file kind; not reviewed yet"


def draft_job(name: str, f: dict) -> dict:
    if name.startswith("automation:"):
        return {"scope": "model", "iterates": "db", "why": "automation kind; runs per Creator rule row",
                "hint": f | {"rule": "automation"}}
    if name in JOBS:
        scope, it, why = JOBS[name]
        return {"scope": scope, "iterates": it, "why": why, "hint": f | {"rule": "named"}}
    return {"scope": "closed", "iterates": "none", "why": UNREVIEWED_JOB,
            "hint": f | {"rule": "unreviewed"}}


def draft(live: dict, inv: dict, unauth: set[str]) -> dict:
    aw, wt = agency_writes_by_route(inv), writers_by_table(inv)
    files = {}
    for key, (scope, moves, secret, sources, why) in FILES.items():
        present = sorted(s for s in sources if s in live["files"])
        if present:
            files[key] = {"scope": scope, "moves": moves, "secret": secret, "why": why, "hint": {"sources": present}}
    claimed = {s for _, _, _, srcs, _ in FILES.values() for s in srcs}
    for s in sorted(live["files"] - claimed):
        files[s] = {"scope": "closed", "moves": False, "secret": False,
                    "why": UNREVIEWED_FILE, "hint": {"sources": [s], "rule": "unreviewed"}}
    return {
        "schema": 1,
        "routes": {k: draft_route(k, f, aw, unauth) for k, f in sorted(live["routes"].items())},
        "tables": {k: draft_table(k, f, wt.get(k, []), live["tables"]) for k, f in sorted(live["tables"].items())},
        "files": dict(sorted(files.items())),
        "jobs": {k: draft_job(k, f) for k, f in sorted(live["jobs"].items())},
    }


def _has_agency_exception(row: dict) -> bool:
    why = str(row.get("why", ""))
    return why.startswith(AGENCY_EXCEPTION) and bool(why.removeprefix(AGENCY_EXCEPTION).strip())


def merge(fresh: dict, old: dict | None) -> dict:
    if not old:
        return fresh
    for m, fields in HUMAN.items():
        for k, row in fresh[m].items():
            prev = old.get(m, {}).get(k)
            if not prev or prev.get("why") in (UNREVIEWED_JOB, UNREVIEWED_FILE):
                continue
            for fld in fields:
                if fld in prev:
                    row[fld] = prev[fld]
                else:
                    row.pop(fld, None)
            fresh[m][k] = {f: row[f] for f in [*fields, "hint", "writers"] if f in row}
    return fresh


def validate(doc: dict) -> list[str]:
    bad = []
    enums = {"routes": {"scope": ROUTE_SCOPES, "key": ROUTE_KEYS, "auth": AUTHS, "partial": ("mark", "fail")},
             "tables": {"scope": TABLE_SCOPES}, "files": {"scope": FILE_SCOPES},
             "jobs": {"scope": JOB_SCOPES, "iterates": ITERATES}}
    for m, fields in enums.items():
        for k, row in doc.get(m, {}).items():
            if row.get("why") in (UNREVIEWED_JOB, UNREVIEWED_FILE):
                bad.append(f"{m} {k}: unreviewed")
            if not str(row.get("why", "")).strip():
                bad.append(f"{m} {k}: no why")
            for fld, allowed in fields.items():
                if fld in row and row[fld] not in allowed:
                    bad.append(f"{m} {k}: {fld}={row[fld]!r} not in {allowed}")
            if "scope" not in row:
                bad.append(f"{m} {k}: no scope")
            if (m == "routes" and row.get("hint", {}).get("rule") in AGENCY_RULES
                    and row.get("scope") != "agency" and not _has_agency_exception(row)):
                bad.append(f"{m} {k}: {row['hint']['rule']} requires agency scope or an explicit agency write exception")
            if m == "routes" and k.startswith("MOUNT ") and row.get("scope") != "closed":
                bad.append(f"{m} {k}: mount must be closed")
            if m == "routes" and row.get("scope") == "fanin" and "partial" not in row:
                bad.append(f"{m} {k}: fanin without partial")
            if (m == "tables" and row.get("scope") in {"agency", "mixed"}
                    and cell_probe.table_class(k) not in {"copied", "control"}):
                bad.append(f"{m} {k}: missing agency probe class")
            if m == "tables" and row.get("scope") == "model_via" and not row.get("via"):
                bad.append(f"{m} {k}: model_via without via")
    return bad


def load(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, []
    dups: list[str] = []

    def pairs(kv):
        seen: dict = {}
        for k, v in kv:
            if k in seen:
                dups.append(k)
            seen[k] = v
        return seen
    return json.loads(path.read_text(), object_pairs_hook=pairs), dups


def check(doc: dict, fresh: dict, dups: list[str] = ()) -> list[str]:
    from actor_token import is_open

    out = [f"duplicated: {k}" for k in dups] + [f"invalid: {b}" for b in validate(doc)]
    out += [f"actor gate blocks public route: {key}" for key, row in doc.get("routes", {}).items()
            if row.get("scope") == row.get("auth") == "public" and not is_open(key.partition(" ")[2])]
    for m in HUMAN:
        have, want = doc.get(m, {}), fresh[m]
        out += [f"missing: {m} {k}" for k in sorted(want.keys() - have.keys())]
        out += [f"stale: {m} {k} (gone)" for k in sorted(have.keys() - want.keys())]
        for k in sorted(want.keys() & have.keys()):
            for fld in ("hint", "writers"):
                if have[k].get(fld) != want[k].get(fld):
                    out.append(f"stale: {m} {k} ({fld} changed)")
    return out


def _unauth_paths() -> set[str]:
    src = (SERVICE / "lane_config_api.py").read_text()
    consts = dict(re.findall(r'^(PATH|PAGE_PATH|RESTART_PATH)\s*=\s*"([^"]+)"', src, re.M))
    return set(consts.values())


def dump(doc: dict) -> str:
    def one(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    parts = [f'{{"schema":{doc["schema"]}']
    for m in HUMAN:
        rows = ",\n".join(f" {one(k)}:{one(v)}" for k, v in doc[m].items())
        parts.append(f'"{m}":{{\n{rows}\n}}')
    return ",\n".join(parts) + "}\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft service/cell_scope.json from the live Relay; --check reports drift.")
    ap.add_argument("--check", action="store_true", help="exit 1 on a missing, stale or invalid row; write nothing")
    ap.add_argument("--fold-probe", nargs="+", type=Path, metavar="PATH",
                    help="probe inventory.json, or the BLOCK and RECORD run dirs (default: committed inventory)")
    ap.add_argument("--fresh", action="store_true", help="ignore decided fields in the existing file")
    ap.add_argument("--features", action="store_true",
                    help="draft service/cell_features.json + docs/cell-mode/release-1-features.md from the committed "
                         "Cell scope (no live scan); with --check report coverage, worst-member, hash and page drift")
    ap.add_argument("--out", type=Path, default=SCOPE)
    ap.add_argument("--_facts", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a._facts:
        _facts_child(a._facts)
        return 0
    if a.features:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import cell_features

        return cell_features.main(a.check, a.fresh)
    inv = load_probe(a.fold_probe or [])
    live = live_facts()
    old, dups = load(a.out)
    fresh = draft(live, inv, _unauth_paths())
    counts = ", ".join(f"{len(fresh[m])} {m}" for m in HUMAN)
    if a.check:
        problems = ([] if old else [f"missing: {a.out}"]) + check(old or {}, fresh, dups)
        for p in problems:
            print(p)
        print(f"cell scope: {counts}; {len(problems)} problem(s)")
        return 1 if problems else 0
    doc = merge(fresh, None if a.fresh else old)
    problems = validate(doc)
    if problems:
        for problem in problems:
            print(f"invalid: {problem}")
        return 1
    a.out.write_text(dump(doc))
    rules = {}
    for row in doc["routes"].values():
        rules[row["hint"]["rule"]] = rules.get(row["hint"]["rule"], 0) + 1
    print(f"wrote {a.out.relative_to(ROOT) if a.out.is_relative_to(ROOT) else a.out}: {counts}; route rules {rules}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
