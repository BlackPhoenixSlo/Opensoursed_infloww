#!/usr/bin/env python3
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="lane-restart-api-")
# Temp ledger: the default store survives between runs and the second run would start at 429.
os.environ["LANE_CONFIG_PATH"] = str(Path(_TMP) / "lane_config.json")
os.environ.setdefault("ALLOW_ANONYMOUS_ADMIN", "1")

import _harness  # noqa: E402

import lane_config  # noqa: E402
import lane_config_api  # noqa: E402
import restart_budget  # noqa: E402

_exits: list[int] = []
# Rebound before the app is built so the process-ending body is unreachable.
lane_config_api._schedule_exit = lambda: _exits.append(1)


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(lane_config_api.router)
    return TestClient(app)


def _reset_ledger():
    ledger = Path(restart_budget.path())
    if ledger.exists():
        ledger.unlink()


def case_the_routes_live_under_the_page_not_under_admin():
    assert lane_config_api.PAGE_PATH == "/lanes-panel"
    for name in ("PATH", "RESTART_PATH"):
        value = getattr(lane_config_api, name)
        assert not value.startswith("/admin/"), (
            f"{name}={value!r} is under /admin/, which app/next.config.ts "
            f"rewrites to this relay wholesale — that publishes an "
            f"unauthenticated route to the open internet"
        )
        assert value.startswith(lane_config_api.PAGE_PATH + "/"), (
            f"{name}={value!r} must be a child of the page whose no-password "
            f"ruling it inherits, so its reachability matches the page's"
        )

    for route in (lane_config_api.PATH, lane_config_api.RESTART_PATH):
        assert f'"{route}"' in lane_config_api._PAGE, (
            f"the panel's JS does not reference {route} — the page is dead "
            f"while every test passes"
        )

    server_src = (Path(__file__).resolve().parent.parent / "server.py").read_text("utf-8")
    assert "_UNAUTHENTICATED_PATHS = frozenset({" in server_src
    for attr in ("lane_config_api.PATH", "lane_config_api.PAGE_PATH",
                 "lane_config_api.RESTART_PATH"):
        assert attr in server_src, (
            f"{attr} is not in server.py's no-auth allowlist — the route stays "
            f"registered and the panel silently starts 401ing"
        )

    cfg = Path(__file__).resolve().parents[2] / "app" / "next.config.ts"
    if cfg.exists():
        text = cfg.read_text("utf-8")
        for src in ('source: "/lanes-panel"', 'source: "/lanes-panel/:path*"'):
            assert src in text, f"next.config.ts lost the {src} rewrite — the panel 404s on the public host"


def case_there_is_no_admin_twin():
    import server
    registered = {r.path for r in server.app.routes if hasattr(r, "path")}
    for expected in (lane_config_api.PATH, lane_config_api.RESTART_PATH,
                     lane_config_api.PAGE_PATH):
        assert expected in registered, (expected, "not registered")
    assert not any(p.startswith("/admin/") and ("restart" in p or "lane-config" in p)
                   for p in registered), (
        "a lanes-panel route must not be reachable under /admin/"
    )


def case_a_relay_that_is_not_pid_1_refuses_without_spending():
    _reset_ledger()
    client = _client()
    assert lane_config_api._can_self_restart() is False, (
        "a test runner is never pid 1 — if this is True the rest of this case "
        "would be restarting the machine it runs on"
    )

    r = client.post(lane_config_api.RESTART_PATH, json={"confirm": True})
    assert r.status_code == 409, (r.status_code, r.text)
    assert "pid 1" in r.json()["detail"], r.json()
    assert restart_budget.budget()["used"] == 0, (
        "the pid check must come BEFORE the spend, or a relay that can never "
        "restart burns its budget discovering that"
    )
    assert _exits == [], "nothing may have been scheduled"


def case_a_bodyless_post_is_refused():
    _reset_ledger()
    client = _client()
    assert client.post(lane_config_api.RESTART_PATH).status_code == 422

    body = '{"confirm": true}'
    for content_type in ("text/plain", "application/x-www-form-urlencoded",
                         "multipart/form-data", ""):
        r = client.post(lane_config_api.RESTART_PATH, content=body,
                        headers={"Content-Type": content_type} if content_type else {})
        assert r.status_code == 422, (
            f"Content-Type={content_type!r} is a CORS-simple shape — reaching "
            f"the handler with it means any page in the operator's browser can "
            f"fire a restart preflight-free (got {r.status_code})"
        )

    server_src = (Path(__file__).resolve().parent.parent / "server.py").read_text("utf-8")
    assert "CORSMiddleware" not in server_src, (
        "a CORS middleware would answer the preflight that is the only thing "
        "standing between a hostile page and POST /lanes-panel/restart"
    )

    r = client.post(lane_config_api.RESTART_PATH, json={"confirm": False})
    assert r.status_code == 400, (r.status_code, r.text)
    assert restart_budget.budget()["used"] == 0


def case_the_budget_is_spent_then_refuses():
    _reset_ledger()
    _exits.clear()
    client = _client()
    original = lane_config_api._can_self_restart
    lane_config_api._can_self_restart = lambda: True
    try:
        for i in range(restart_budget.LIMIT):
            r = client.post(lane_config_api.RESTART_PATH, json={"confirm": True})
            assert r.status_code == 200, (i, r.status_code, r.text)
            body = r.json()
            assert body["restarting"] is True, body
            assert body["boot_id"] == lane_config_api._BOOT_ID, body

        r = client.post(lane_config_api.RESTART_PATH, json={"confirm": True})
        assert r.status_code == 429, (r.status_code, r.text)
        assert "limit" in r.json()["detail"], r.json()

        assert len(_exits) == restart_budget.LIMIT, (
            f"one exit scheduled per granted restart, and none for the refusal: "
            f"{len(_exits)}"
        )
        on_disk = json.loads(Path(restart_budget.path()).read_text("utf-8"))
        assert len(on_disk) == restart_budget.LIMIT, on_disk

        assert any("restart" in (row.get("event") or "")
                   for row in lane_config.history(50)), lane_config.history(10)
    finally:
        lane_config_api._can_self_restart = original


def case_the_payload_carries_what_the_panel_binds_to():
    _reset_ledger()
    client = _client()
    payload = client.get(lane_config_api.PATH).json()
    for key in ("knobs", "restart_required", "path", "history", "container", "restart"):
        assert key in payload, (key, sorted(payload))
    for key in ("cpus", "cpus_readable", "mem_bytes", "mem_readable",
                "host_cpus", "container_id"):
        assert key in payload["container"], (key, payload["container"])

    state = client.get(lane_config_api.RESTART_PATH).json()
    for key in ("budget", "boot_id", "can_restart"):
        assert key in state, (key, sorted(state))
    assert state["can_restart"] is False
    assert state["boot_id"] == payload["restart"]["boot_id"], (
        "the cheap poll route and the page payload must agree on the boot id, "
        "or the page settles on a mismatch that never resolves"
    )
    for key in ("used", "limit", "remaining", "window_s", "retry_after_s"):
        assert key in state["budget"], (key, state["budget"])


def case_the_hard_exit_waits_past_the_automation_drain():
    import re
    import automation_executor as ax
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    graceful = float(re.search(r"UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=(\d+)", dockerfile).group(1))
    assert lane_config_api._RESTART_GRACE_S >= graceful + ax.DRAIN_S + 10, (
        lane_config_api._RESTART_GRACE_S, graceful, ax.DRAIN_S)


def case_every_stop_of_the_relay_waits_past_the_automation_drain():
    import re
    import automation_executor as ax
    root = Path(__file__).resolve().parents[2]
    graceful = float(re.search(r"UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=(\d+)",
                               (root / "Dockerfile").read_text()).group(1))
    relay = (root / "docker-compose.yml").read_text().split("\n  openinflowwww-app:")[0]
    grace = float(re.search(r"\n    stop_grace_period: (\d+)s", relay).group(1))
    heal = float(re.search(r'\n      autoheal\.stop\.timeout: "(\d+)"', relay).group(1))
    assert grace >= graceful + ax.DRAIN_S + 10, (grace, graceful, ax.DRAIN_S)
    assert heal == grace, (heal, grace)


_harness.run(
    case_every_stop_of_the_relay_waits_past_the_automation_drain,
    case_the_hard_exit_waits_past_the_automation_drain,
    case_the_routes_live_under_the_page_not_under_admin,
    case_there_is_no_admin_twin,
    case_a_relay_that_is_not_pid_1_refuses_without_spending,
    case_a_bodyless_post_is_refused,
    case_the_budget_is_spent_then_refuses,
    case_the_payload_carries_what_the_panel_binds_to,
)
