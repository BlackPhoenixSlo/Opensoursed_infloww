#!/usr/bin/env python3
"""
`lane_config_api` — the Concurrency panel's routes, including the one that ENDS
THE PROCESS. Plain-assert, no pytest (repo convention).

Why this suite exists. `POST /lanes-panel/restart` is the first destructive verb
behind an unauthenticated route in this codebase, and until now nothing tested
it. Every guard on it is one line, and each fails in a way nobody would notice:

  • **The path prefix is a security control, not a naming choice.**
    `app/next.config.ts` rewrites `/admin/:path*` to this relay wholesale and
    traefik puts that app on the public host, so an `/admin/` path on the no-auth
    allowlist is a remote kill switch. Since 2026-09-20 `/lanes-panel` has its
    own rewrite too, by the operator's decision, so the prefix no longer limits
    reach — but the split still keeps these routes out of the tenant
    pre-filter, and `case_the_routes_live_under_the_page_not_under_admin`
    pins the shape (and that the public rewrite exists, so the URL works).
  • **The routes pierce TWO gates** (`server.py`'s isolation middleware and its
    share-token gate) via `_UNAUTHENTICATED_PATHS`. A rename does not fail
    closed, it fails SILENTLY: the route stays registered, the panel's fetch
    starts 401ing, and nobody learns until they need the button.
  • **The JSON body is the CSRF guard.** A bodyless POST is a CORS "simple
    request" that any page in the operator's browser can fire preflight-free at
    localhost. Making `confirm` optional would quietly delete that.
  • **PID 1 is checked BEFORE the budget is spent**, so a relay that cannot
    restart never burns a restart discovering it.

🚨 BLAST SAFETY. `_schedule_exit` is rebound at module scope BEFORE the app is
built and before any request runs, so the destructive body is structurally
unreachable for the life of this process — not merely unreached. `_can_self_restart`
is False under a test runner anyway, so the 409 case needs no patching at all.
`LANE_CONFIG_PATH` is bound to a per-run temp file first: under `_harness` the
store otherwise resolves into the shared system tempdir, where the ledger
SURVIVES BETWEEN RUNS and the second run of this file would start at 429.

Cases:
  case_the_routes_live_under_the_page_not_under_admin
  case_there_is_no_admin_twin
  case_a_relay_that_is_not_pid_1_refuses_without_spending
  case_a_bodyless_post_is_refused
  case_the_budget_is_spent_then_refuses
  case_the_payload_carries_what_the_panel_binds_to
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Order matters, and every line before the imports below is load-bearing. ──
_TMP = tempfile.mkdtemp(prefix="lane-restart-api-")
os.environ["LANE_CONFIG_PATH"] = str(Path(_TMP) / "lane_config.json")
os.environ.setdefault("ALLOW_ANONYMOUS_ADMIN", "1")

import _harness  # noqa: E402

import lane_config  # noqa: E402
import lane_config_api  # noqa: E402
import restart_budget  # noqa: E402

# THE safety line. Rebound before anything can call it; the real one spawns a
# thread that SIGTERMs this process 0.5s later.
_exits: list[int] = []
lane_config_api._schedule_exit = lambda: _exits.append(1)


def _client():
    """A FastAPI app carrying only this router — the gates live in `server.py`
    and are asserted separately, by path, in the first case."""
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
    """The prefix IS the guard — see the module docstring."""
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

    # 🚨 AND THE PAGE'S OWN JS MUST POINT AT THEM. The page hardcodes
    # `const API` / `const RESTART_API` as literals, so renaming `PATH` — the
    # NATURAL refactor, since server.py follows the constant automatically —
    # leaves every suite green while every fetch on the panel 404s. Verified in
    # review: a rename to "/lanes-panel/knobs" produced a dead page and a full
    # green run. This is the one place the module restates something a call
    # site already owns, which is exactly what its own docstrings forbid.
    for route in (lane_config_api.PATH, lane_config_api.RESTART_PATH):
        assert f'"{route}"' in lane_config_api._PAGE, (
            f"the panel's JS does not reference {route} — the page is dead "
            f"while every test passes"
        )

    # And the gates in server.py must still name all three, or the panel 401s
    # in production while every other test stays green.
    server_src = (Path(__file__).resolve().parent.parent / "server.py").read_text("utf-8")
    assert "_UNAUTHENTICATED_PATHS = frozenset({" in server_src
    for attr in ("lane_config_api.PATH", "lane_config_api.PAGE_PATH",
                 "lane_config_api.RESTART_PATH"):
        assert attr in server_src, (
            f"{attr} is not in server.py's no-auth allowlist — the route stays "
            f"registered and the panel silently starts 401ing"
        )

    # And the public door must exist, or https://<host>/lanes-panel 404s at
    # Next before it ever reaches the relay (the operator's 2026-09-20 ask).
    cfg = Path(__file__).resolve().parents[2] / "app" / "next.config.ts"
    if cfg.exists():
        text = cfg.read_text("utf-8")
        for src in ('source: "/lanes-panel"', 'source: "/lanes-panel/:path*"'):
            assert src in text, f"next.config.ts lost the {src} rewrite — the panel 404s on the public host"


def case_there_is_no_admin_twin():
    """The panel's routes live only under `/lanes-panel`. `/admin/:path*` is
    rewritten to this relay from the public host, so an `/admin/` twin of the
    config — let alone of the verb that ends the process — would be one more
    door to guard."""
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
    """The real mechanism is that no CORS-SIMPLE request shape can reach the
    handler — and that is what this asserts.

    An earlier version of this case only checked "no body -> 422" and
    "confirm:false -> 400", and review proved it a zombie for the property its
    own docstring named: making `confirm` optional left all six cases green,
    because `Body(...)` is required regardless of the field's default. The
    guard that actually matters is narrower and lives one layer down — a
    cross-origin page can only send `text/plain`, form-urlencoded, multipart,
    or NO Content-Type without tripping a preflight that nothing here answers.
    """
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

    # The header-less case above holds only because FastAPI defaults
    # `strict_content_type=True`; an older pin parses it as JSON and reopens the
    # hole. And a CORS middleware would answer the preflight that protects the
    # `application/json` shape, deleting the guard from the other direction.
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
            # The page polls against the boot_id of the process that ACCEPTED
            # the request; without it here it would compare against a possibly
            # several-restarts-stale id it happened to be holding.
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

        # The story the panel tells is "the cap changed, and then it was
        # applied" — the second half has to be in the history too.
        assert any("restart" in (row.get("event") or "")
                   for row in lane_config.history(50)), lane_config.history(10)
    finally:
        lane_config_api._can_self_restart = original


def case_the_payload_carries_what_the_panel_binds_to():
    """The JS disables the button on `can_restart` and settles the reload on
    `boot_id`. A dropped key is a button that never re-enables."""
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
    # A self-restart is a SIGTERM: uvicorn's graceful wait, then the shutdown
    # hook's drain of runs that claimed a send. The hard exit must not cut
    # that drain, or the restart becomes the crash case.
    import re
    import automation_executor as ax
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    graceful = float(re.search(r"UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=(\d+)", dockerfile).group(1))
    assert lane_config_api._RESTART_GRACE_S >= graceful + ax.DRAIN_S + 10, (
        lane_config_api._RESTART_GRACE_S, graceful, ax.DRAIN_S)


def case_every_stop_of_the_relay_waits_past_the_automation_drain():
    # docker stop / compose up (stop_grace_period) and autoheal's restart (its
    # own label) both SIGKILL past their timeout: each must outlast uvicorn's
    # graceful wait plus the drain.
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
