from __future__ import annotations

import _harness

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

_harness.bootstrap()

OWNED, STRAY, UNREGISTERED = "900539700124344320", "900539700124344321", "900539700124344322"
_placement = Path(tempfile.mkdtemp()) / "placement.json"
_placement.write_text(json.dumps({
    "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
    "min_cell_proto": 1,
    "cells": {"s01": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:1", "role": "control", "state": "live"},
              "s02": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:2", "role": "data", "state": "live"}},
    "accounts": {f"onlyfans:{OWNED}": "s02", f"onlyfans:{UNREGISTERED}": "s02"}}))
os.environ.update({"OI_CELL_MAP": str(_placement), "OI_CELL_ID": "s02", "OI_CELL_ROLE": "data",
                   "OI_ACCOUNTS": f"onlyfans:{OWNED},onlyfans:{UNREGISTERED}", "OI_EPOCH": "1",
                   "ALLOW_ANONYMOUS_ADMIN": "1"})

from types import SimpleNamespace  # noqa: E402

import accounts as account_registry  # noqa: E402
import cell_mode  # noqa: E402
import leak_tracker  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat  # noqa: E402

client = _harness.make_client()
import server  # noqa: E402
import accounts_admin_api  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import cell_scope_scan as scan  # noqa: E402

account_registry.list_accounts = lambda include_watchers=False: [
    {"id": a, "platform": "onlyfans", "has_session": True} for a in (OWNED, STRAY)]
accounts_admin_api._get_request_user = lambda: SimpleNamespace(user_id="u1", account_ids={OWNED, STRAY})
_DOC = json.loads(scan.SCOPE.read_text())


def _error(r) -> str | None:
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail.get("error") if isinstance(detail, dict) else None


def case_live_routes_equal_json_rows():
    from fastapi.routing import APIRoute
    live = {f"{m} {r.path}" for r in server.app.routes if isinstance(r, APIRoute) for m in r.methods}
    rows = {k for k, v in _DOC["routes"].items() if "cells" in v["hint"].get("profiles", ["cells"])}
    assert live == rows, {"no row": sorted(live - rows)[:10], "row, no route": sorted(rows - live)[:10]}
    assert not [r for r in server.app.routes if not isinstance(r, APIRoute)], "docs/mounts serve unguarded"


def case_route_without_a_row_is_refused():
    server.app.add_api_route("/api/of/__cell_scope_no_row", lambda: {"ok": True}, methods=["GET"])
    r = client.get("/api/of/__cell_scope_no_row")
    assert r.status_code == 403 and _error(r) == "cell_scope_closed", (r.status_code, r.text[:300])
    assert r.json()["detail"]["route"] == "GET /api/of/__cell_scope_no_row"


def case_closed_row_and_untagged_fanin_are_refused():
    closed = [k for k, v in _DOC["routes"].items() if v["scope"] == "closed" and k.startswith("GET /admin/")]
    fanin = [k for k, v in _DOC["routes"].items() if v["scope"] == "fanin" and k not in cell_mode.FANIN]
    assert closed and fanin, (closed, fanin)
    for key in (closed[0], "GET /admin/stats/per-employee", "GET /admin/proxies"):
        r = client.get(key.split(" ", 1)[1])
        assert r.status_code == 403 and _error(r) == "cell_scope_closed", (key, r.status_code, r.text[:300])
    assert sorted(k for k, v in _DOC["routes"].items() if v["scope"] == "fanin" and k in cell_mode.FANIN) == sorted(
        cell_mode.FANIN), "each Phase 01 fan-in has a fanin row"


def case_docs_are_off_in_cell_mode():
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 404, path


async def _seed_chats() -> None:
    async with get_session() as s:
        for aid in (OWNED, STRAY):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
        await s.flush()
        for aid, fan in ((OWNED, 11), (STRAY, 12)):
            if await s.get(Chat, (aid, fan)) is None:
                s.add(Chat(account_id=aid, fan_id=fan, last_message_id=fan, last_message_at=datetime(2026, 11, 26),
                           last_message_preview="hi", unread_count=1))


def _tags(row: dict, ok: bool = True) -> None:
    assert row["platform"] == "onlyfans" and row["account_id"] == OWNED and row["ok"] is ok, row
    assert isinstance(row["as_of"], int) and row["as_of"] > 1_700_000_000_000, row


async def case_the_three_fanin_reads_tag_rows_and_name_missing_accounts():
    await _seed_chats()
    r = client.get("/admin/accounts")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert [a["id"] for a in body["accounts"]] == [OWNED], body["accounts"]
    _tags(body["accounts"][0])
    assert body["partial"] == [f"onlyfans:{UNREGISTERED}"], body["partial"]

    r = client.get("/admin/chats/recent?limit=10")
    body = r.json()
    assert r.status_code == 200 and [c["__accountId"] for c in body["list"]] == [OWNED], body
    _tags(body["list"][0])
    assert body["partial"] == [f"onlyfans:{UNREGISTERED}"], body["partial"]
    r = client.get(f"/admin/chats/recent?account_id={OWNED}")
    assert r.json()["partial"] == [], r.json()

    r = client.get(f"/admin/screens/inbox?accounts={OWNED},{UNREGISTERED}&deadline_ms=0")
    body = r.json()
    assert r.status_code == 200, r.text[:300]
    per = [a for a in body["answers"] if a.get("accountId")]
    assert per and {a["account_id"] for a in per} == {OWNED, UNREGISTERED}, per
    assert all(a["ok"] is ("status" not in a) for a in per), per
    head = [a for a in body["answers"] if a.get("read") == "accounts"]
    assert head and [x["id"] for x in head[0]["body"]["accounts"]] == [OWNED], head
    assert f"onlyfans:{UNREGISTERED}" in body["partial"], body["partial"]


def case_agency_write_on_data_cell_refused_control_allowed():
    assert _DOC["routes"]["POST /admin/shifts"]["scope"] == "agency" == _DOC["routes"]["GET /auth/me"]["scope"]
    path = "/admin/shifts"
    r = client.post(path, json={})
    assert r.status_code == 403 and _error(r) == "agency_write_on_data_cell", (r.status_code, r.text[:300])
    assert _error(client.get("/auth/me")) is None, "agency reads stay open on a data cell"
    os.environ["OI_CELL_ROLE"] = "control"
    try:
        assert _error(client.post(path, json={})) not in ("agency_write_on_data_cell", "cell_scope_closed")
    finally:
        os.environ["OI_CELL_ROLE"] = "data"


def case_agency_jobs_tick_only_on_control():
    agency = [k for k, v in _DOC["jobs"].items() if v["scope"] == "agency"]
    assert agency == ["clock-in-missed", "leak-watch-sync", "leak-watch-tombstones"], agency
    assert not cell_mode.runs_job("clock-in-missed") and cell_mode.runs_job("pump-supervisor")
    assert not cell_mode.runs_job("no-such-job"), "a job without a Cell scope row must not run"
    os.environ["OI_CELL_ROLE"] = "control"
    try:
        assert cell_mode.runs_job("clock-in-missed")
    finally:
        os.environ["OI_CELL_ROLE"] = "data"
    src = Path(server.__file__).read_text()
    at = src.index('first_after_s=60), "clock-in-missed")')
    assert 'cell_mode.runs_job("clock-in-missed")' in src[max(0, at - 300):at], "clock-in tick not gated"
    os.environ["LEAK_TRACKER_URL"] = "https://tracker.example.test"
    try:
        assert not leak_tracker.jobs_on(), "the Leak watch sync never starts in a Cell"
    finally:
        os.environ.pop("LEAK_TRACKER_URL")
    for job in ("leak-watch-sync", "leak-watch-tombstones"):
        at = src.index(f'"{job}")')
        assert "leak_tracker.jobs_on()" in src[max(0, at - 400):at], f"{job} not gated"


_harness.run()
