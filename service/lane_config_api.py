"""service/lane_config_api.py — the Concurrency panel's read/write endpoints.

🚨 THESE ROUTES ARE UNAUTHENTICATED, BY EXPLICIT CHOICE, AND THEY WRITE.

They set the process-wide concurrency ceilings, and anyone who can reach the port
can change them. That is a decision the operator made knowingly for a
friends-only deployment — they asked for a panel with no password so retuning a
cap does not require signing in as admin — not an oversight. It is stated here,
and again at each gate it pierces in `server.py`, so nobody removes it as a bug.

🚨 AND ONE OF THEM RESTARTS THE RELAY. `RESTART_PATH` ends this process so
docker cycles it, because every value here applies at restart and a panel that
cannot restart is a panel that always ends at "now go find a terminal". It is
the destructive verb in this module and carries bounds the others do not need —
two per hour counted in a FILE that outlives the restart, and pid-1-only so it
can never stop a relay that nothing would bring back. `restart_relay()` has the
full reasoning; what it costs is in-flight work, and the panel says so too.

What is exposed, and what is not. The payload is cap NUMBERS only: no account
ids, no fan data, no session or key material. The per-account lane stats are
deliberately NOT exposed alongside it: they are keyed BY account id and would
publish the account roster to anyone who asked for it.

The risk being accepted. These ceilings are shared by every account on the box,
so one caller's change lands on all of them, and a large value spends threads
and descriptors the whole process shares — 2026-07-04 (thread starvation) and
2026-08-08 (descriptor exhaustion) were both that failure. Two things bound it:
saved values apply at RESTART, so a bad number costs a restart rather than an
outage; and an env var beats a saved value, so recovery never requires reaching
into the container for a file. The audit middleware records every write.

Why a module and not two handlers in `server.py`: this repo keeps endpoint
families in `*_api.py` routers — there are two dozen — and `server.py` is
already ~9.8k lines. A new config API belongs in the shape the codebase already
has for config APIs.
"""
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

# The human panel. Deliberately NOT linked from anywhere in the app — the
# operator's choice is that this lives as a direct link documented in the
# README, so using it never requires signing in as anyone.
PAGE_PATH = "/lanes-panel"
# 🚨 EVERY ROUTE HERE IS A CHILD OF THE PAGE'S OWN PATH, AND THAT IS LOAD-BEARING.
#
# These were `/admin/lane-config` and `/admin/lane-restart` until review caught
# what the prefix bought: `app/next.config.ts` rewrites `/admin/:path*` to the
# relay wholesale, and traefik puts the Next app on the public host. So an
# `/admin/` path on the no-auth allowlist is reachable from the open internet
# with no cookie — which for a route that ENDS THE PROCESS is a remote kill
# switch, published with an achievable cadence rather than protected by one.
#
# `/lanes-panel` was in no rewrite, so the page was reachable only on the relay
# port. On 2026-09-20 the operator asked for the opposite and reaffirmed it
# three times: `app/next.config.ts` now rewrites `/lanes-panel` and
# `/lanes-panel/*` to the relay, so anyone who pastes the public URL gets the
# panel with no login, no token and no key. The prefix therefore no longer
# limits reach; what it still does is keep these routes out of `server.py`'s
# `startswith("/admin/")` tenant pre-filter (they name no account). What bounds
# the exposure is on the handlers: the restart budget, the JSON-body CSRF
# guard, and restart-only application of every ceiling.
#
# Do not move these back under `/admin/` to "match the other admin routes".
PATH = "/lanes-panel/config"
# The button that makes the rest of the panel finish. Every value here applies
# at restart, so without this the panel always ended at "now go find a
# terminal". Bounded by `restart_budget.LIMIT` per hour, and see
# `restart_relay()` for the guards that make self-exit safe.
RESTART_PATH = "/lanes-panel/restart"
# There is deliberately no `/admin/` twin of these routes (the Settings card that
# read one is gone). A resource that ends the process gets one door.

router = APIRouter(tags=["lane-config"])

# Long enough for the 200 to reach the browser before the process goes away —
# the panel needs the budget in that response to render "1 left".
_RESTART_DELAY_S = 0.5
# uvicorn's graceful shutdown waits for in-flight requests (Dockerfile:
# UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN), then the shutdown hook waits for any
# automation run that claimed a send (automation_executor.DRAIN_S, the same
# RELAY_DRAIN_S). Cutting that drain would turn a clean stop into a crash, so
# the hard exit waits past both. Past this the operator asked for a restart and
# did not get one, which is worse than dropping the straggler, so we stop asking.
_RESTART_GRACE_S = 25.0 + float(os.environ.get("RELAY_DRAIN_S", "45"))
# Identifies THIS process, so the panel can tell a relay that came back from one
# that never went down. Polling for "does the port answer" is not enough: the
# first poll can land in the half-second before the SIGTERM, and the page would
# report a restart that had not happened yet.
_BOOT_ID = f"{os.getpid()}-{time.time():.3f}"


class LaneConfigBody(BaseModel):
    """`{"values": {"IMG_FETCH_CONCURRENCY": 12, "HEALTH_ALL_CONCURRENCY": null}}`

    `null` deletes an override and falls the knob back to its code default —
    "reset" without a second endpoint to keep in sync with this one.
    """
    values: dict[str, int | None]


def _payload() -> dict[str, Any]:
    """One shape for both verbs, so the panel never has to reconcile two views
    of the same state."""
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
    """The restart resource: cheap enough to poll. `_payload()` costs a jsonl
    read, four cgroup reads and a registry walk — polling THAT every 2s during a
    boot, forty times, to compare one string was ~280 file reads per restart
    against a relay that is busy starting up."""
    return {
        "budget": restart_budget.budget(),
        # Surfaced because `restart_budget.path()` otherwise documents a reader
        # it does not have — and a 429 with no way to learn the filename is a
        # dead end on a page whose whole point is not needing a terminal.
        "path": restart_budget.path(),
        "boot_id": _BOOT_ID,      # see `_BOOT_ID` for why polling needs it
        # Whether THIS process may end itself — see `restart_relay()`. The panel
        # disables the button on it rather than letting a click discover the
        # 409, because the answer never changes for the life of the process.
        "can_restart": _can_self_restart(),
    }


def _can_self_restart() -> bool:
    """PID 1 is the structural fact that makes self-exit safe, so it is the
    thing checked — not a list of hosts or an opt-in flag.

    As PID 1 this process IS the container: ending it ends the container, and
    docker's `restart: unless-stopped` (on every relay definition in this repo)
    starts a fresh one. At any other pid, exiting stops the relay and nothing
    brings it back — which is exactly what a developer running uvicorn in a venv
    would get. Fail closed there: the cost of refusing is a manual restart, the
    cost of allowing is an outage nobody is watching for.
    """
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
        # The store lives on a mount. If it is gone, say so — a 200 here would
        # mean "saved" for a value that will not survive the restart it needs.
        log.exception("lane_config write failed")
        raise HTTPException(status_code=500, detail=f"could not write store: {e}")
    return _payload()


def _exit_soon() -> None:
    """SIGTERM ourselves, then hard-exit if that does not finish.

    SIGTERM first, not `os._exit`, because a graceful uvicorn shutdown runs the
    lifespan teardown — SQLite sessions close, the WS pumps stop — and this
    process is holding a 1.7 GB database open. The hard exit exists because
    graceful shutdown WAITS on in-flight requests with no timeout of its own: a
    single stuck OF call would otherwise turn "restart" into "hang", and the
    operator would be left with a button that silently did nothing.
    """
    time.sleep(_RESTART_DELAY_S)
    log.warning("lane-restart: operator-requested restart — SIGTERM to self (pid %s)",
                os.getpid())
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except OSError:
        log.exception("lane-restart: SIGTERM to self failed — exiting hard")
        os._exit(0)
    time.sleep(_RESTART_GRACE_S)
    # Still here, so the graceful path is stuck behind something that will not
    # finish. `_exit` rather than `sys.exit`: this is a daemon thread, and
    # SystemExit raised here would be swallowed and change nothing.
    log.warning("lane-restart: graceful shutdown unfinished after %ss — exiting hard",
                _RESTART_GRACE_S)
    os._exit(0)


def _schedule_exit() -> None:
    """The one line that makes this module destructive, given its own name.

    A test can rebind THIS and the exit becomes structurally unreachable; with
    the thread spawned inline at the call site, the same test has to neutralise
    `_exit_soon`'s body and hope nothing else ever calls it. `restart_relay`
    returns before this thread does anything, so the seam is the whole safety
    story for testing the endpoint at all.
    """
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
    # The story the history exists to tell is "the cap changed, and then it was
    # applied". Without this the operator sees the first half and never the
    # second. Best-effort, like every other append: a lost row must not fail a
    # restart that is already paid for.
    try:
        lane_config.note_restart()
    except Exception:      # noqa: BLE001 — the restart is already paid for
        # `_append_history` swallows OSError, but anything else escaping here
        # would burn a restart from the budget and then never schedule one.
        log.warning("lane-restart: history note failed", exc_info=True)
    _schedule_exit()
    # `boot_id` identifies the process that ACCEPTED this, which is what the
    # page compares against while polling. Reusing the id it happened to hold
    # from an earlier load would settle the moment any other restart had
    # happened since the page was opened.
    return {"restarting": True, **_restart_state()}


# ── The panel page ──────────────────────────────────────────────────
#
# Self-contained HTML served by the relay itself: no app, no login, no build
# step, no external assets. It talks only to PATH above, so everything it can
# show or change is exactly what that endpoint already exposes.
# The page lives in `panels/lane_config_panel.html`, read once at import with
# no newline translation, so its bytes (and the JS's backslash escapes, a \n
# inside a confirm() message) reach the browser exactly as stored.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "panels",
                       "lane_config_panel.html"), encoding="utf-8", newline="") as _f:
    _PAGE = _f.read()


@router.get(PAGE_PATH, include_in_schema=False)
def lanes_panel() -> HTMLResponse:
    """The Concurrency panel, as a page the relay serves itself.

    🚨 Unauthenticated, like the API it fronts — see the module docstring.
    Linked from the README and from nowhere in the app, on purpose."""
    return HTMLResponse(_PAGE)
