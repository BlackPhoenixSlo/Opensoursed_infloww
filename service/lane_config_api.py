# Unauthenticated and writing, by explicit owner choice for a friends-only deployment (no password to retune a cap): not a bug, don't "fix".
# Cap numbers only: per-account lane stats are keyed by account id and would publish the roster.
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import container_limits
import lane_config
import restart_budget

log = logging.getLogger("of-relay.lane-config-api")

PAGE_PATH = "/lanes-panel"
# Routes stay under the page path, never /admin/: the Next rewrite exposes /admin/* publicly, and a no-auth route that ends the process would be a remote kill switch; it also keeps them out of server.py's /admin/ tenant pre-filter.
PATH = "/lanes-panel/config"
# Every value applies at restart; bounded by restart_budget.LIMIT per hour (counted in a file that outlives the restart) and pid-1 only.
RESTART_PATH = "/lanes-panel/restart"

router = APIRouter(tags=["lane-config"])

# Long enough for the 200 (with the budget the panel renders) to reach the browser before the process goes away.
_RESTART_DELAY_S = 0.5
# Graceful shutdown waits for in-flight requests, then for any automation run that claimed a mass send (DRAIN_S); the hard exit waits past both, since cutting the drain turns a clean stop into a crash.
_RESTART_GRACE_S = 25.0 + float(os.environ.get("RELAY_DRAIN_S", "45"))
# Identifies this process: polling the port alone can land before the SIGTERM and report a restart that had not happened.
_BOOT_ID = f"{os.getpid()}-{time.time():.3f}"


class LaneConfigBody(BaseModel):
    """`{"values": {"IMG_FETCH_CONCURRENCY": 12, "HEALTH_ALL_CONCURRENCY": null}}`

    `null` deletes an override and falls the knob back to its code default —
    "reset" without a second endpoint to keep in sync with this one.
    """
    values: dict[str, int | None]


def _payload() -> dict[str, Any]:
    knobs = lane_config.describe()
    return {
        "knobs": knobs,
        "restart_required": any(k["pending"] for k in knobs),
        "path": lane_config.path(),
        "history": lane_config.history(50),
        "container": container_limits.describe(),
        "restart": _restart_state(),
    }


def _restart_state() -> dict[str, Any]:
    # Cheap on purpose: polling _payload() every 2s during boot cost ~280 file reads per restart.
    return {
        "budget": restart_budget.budget(),
        "path": restart_budget.path(),
        "boot_id": _BOOT_ID,
        "can_restart": _can_self_restart(),
    }


def _can_self_restart() -> bool:
    # PID 1 only: docker restarts the container; at any other pid exiting stops the relay for good, so fail closed.
    return os.getpid() == 1


@router.get(PATH)
def get_lane_config() -> dict[str, Any]:
    """Every tunable ceiling, what it is set to, and where that came from.

    🚨 Unauthenticated — see the module docstring."""
    return _payload()


@router.post(PATH)
def set_lane_config(body: LaneConfigBody = Body(...)) -> dict[str, Any]:
    """Persist new ceilings. Applies at the next restart, never live.

    🚨 Unauthenticated WRITE — see the module docstring.

    The only rejections are an unknown knob and a non-integer, which is what the
    env vars these replaced already accepted.
    """
    try:
        lane_config.set_many(body.values)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        # The store lives on a mount: if it is gone, a 200 would say "saved" for a value that won't survive the restart.
        log.exception("lane_config write failed")
        raise HTTPException(status_code=500, detail=f"could not write store: {e}")
    return _payload()


def _exit_soon() -> None:
    # SIGTERM first so uvicorn runs the lifespan teardown (SQLite close, WS pumps stop); the hard exit exists because graceful shutdown waits on in-flight requests with no timeout.
    time.sleep(_RESTART_DELAY_S)
    log.warning("lane-restart: operator-requested restart — SIGTERM to self (pid %s)",
                os.getpid())
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except OSError:
        log.exception("lane-restart: SIGTERM to self failed — exiting hard")
        os._exit(0)
    time.sleep(_RESTART_GRACE_S)
    # _exit, not sys.exit: this is a daemon thread and SystemExit would be swallowed.
    log.warning("lane-restart: graceful shutdown unfinished after %ss — exiting hard",
                _RESTART_GRACE_S)
    os._exit(0)


def _schedule_exit() -> None:
    # Test seam: rebinding this makes the exit structurally unreachable.
    threading.Thread(target=_exit_soon, name="lane-restart", daemon=True).start()


@router.get(RESTART_PATH)
def restart_status() -> dict[str, Any]:
    """Just enough to answer "is it back yet" — see `_restart_state`."""
    return _restart_state()


class RestartBody(BaseModel):
    """`{"confirm": true}` — and the BODY IS THE POINT, not the field.

    🚨 THIS IS THE CSRF GUARD, AND IT IS THE ONLY ONE. A bodyless POST is a CORS
    "simple request": any page the operator happens to have open can fire
    `fetch("http://127.0.0.1:8797/lanes-panel/restart", {method:"POST",
    mode:"no-cors"})` with NO preflight, get an opaque response it cannot read,
    and land the side effect anyway. Moving off `/admin/` closed the public
    internet; it does not close the operator's own browser, because localhost is
    reachable from every page in it.

    Requiring `application/json` forces a preflight, and there is no CORS
    middleware in this service to answer one — so the cross-origin call dies
    before the handler runs. `POST PATH` was incidentally protected by this all
    along (it needs a values body); the restart route needed nothing, which is
    what made it the sharper edge of the two.

    Do not make this field optional to "simplify" the endpoint. The requirement
    that a body exists at all is the whole mechanism.
    """
    confirm: bool


@router.post(RESTART_PATH)
def restart_relay(body: RestartBody = Body(...)) -> dict[str, Any]:
    """Restart the relay so saved caps take effect. Bounded to
    `restart_budget.LIMIT` per hour.

    🚨 Unauthenticated, like the rest of this module — and this one is the
    destructive verb, so it carries three guards the others do not need:

    • **A JSON body** (`RestartBody`), which is what stops a cross-origin page
      in the operator's browser from firing it preflight-free.
    • **PID 1 only** (`_can_self_restart`), checked BEFORE the budget is spent
      so a relay that cannot restart never burns a restart discovering it.
    • **A budget on disk**, spent BEFORE the exit. The event being limited is
      this process ending, so an in-memory counter would reset on the very
      thing it counts and bound nothing.

    What it costs, stated plainly because the panel says it too: in-flight work
    is dropped. Automation runs mid-send, open WS pumps and anything queued
    behind them do not survive. That is the trade for not needing a terminal,
    and it is why the number is two an hour and not twenty.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    if not _can_self_restart():
        raise HTTPException(status_code=409, detail=(
            "this relay is not pid 1, so exiting would stop it for good rather "
            "than cycle it — restart it the way it was started"
        ))
    spent = restart_budget.spend()
    if spent is None:
        budget = restart_budget.budget()
        raise HTTPException(status_code=429, detail=(
            f"{budget['limit']} restarts per hour is the limit — "
            f"{budget['retry_after_s']}s until the next one frees"
        ))
    try:
        lane_config.note_restart()
    except Exception:      # noqa: BLE001 — the restart is already paid for
        # _append_history swallows OSError, but anything else escaping would burn a restart from the budget and never schedule one.
        log.warning("lane-restart: history note failed", exc_info=True)
    _schedule_exit()
    return {"restarting": True, **_restart_state()}


with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "panels",
                       "lane_config_panel.html"), encoding="utf-8", newline="") as _f:
    _PAGE = _f.read()


@router.get(PAGE_PATH, include_in_schema=False)
def lanes_panel() -> HTMLResponse:
    """The Concurrency panel, as a page the relay serves itself.

    🚨 Unauthenticated, like the API it fronts — see the module docstring.
    Linked from the README and from nowhere in the app, on purpose."""
    return HTMLResponse(_PAGE)
