"""Ultra wild-input flow's checks and break-it-once fault (scenarios/2026-11-14-ultra-wild.py): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

C_5XX = "no_5xx: no Ultra route answers 5xx to any wild request, OK, cancel or pick"
C_SEND = ("no_send_without_ok: OnlyFans' queue/chat/post wire and automation_rules see only the one OK'd control "
          "send; no plan that was not OK'd sends")
C_CROSS = ("no_cross_agency: Agency B's plans, bio page, links and Creator are neither read nor changed by Agency A "
           "(no B marker in any answer A or its planner gets; B's rows unchanged; B gets 404 on A's plan)")
C_TERMINAL = "every_plan_terminal: every plan ends (awaiting_ok then cancelled, done, failed, capped or cancelled)"
C_PLAIN = ("errors_are_plain: every refusal and plan end the owner reads is non-empty human text (no Traceback, "
           "exception class name, key or token)")
C_STALE = "stale_ok_refused: an OK with a wrong or malformed sha256 is refused (409/422) and the plan stays awaiting_ok"
C_EMPLOYEE = "employee_refused: a chatter (and a signed-out caller) is refused on every Ultra route"
C_CAPS = ("caps_hold: 25-turn cap ends a planner that never stops (capped), 8 calls per reply, 20 steps per plan, "
          "4000-char request")
C_RACES = "ok_races: double OK, OK+cancel, cancel+OK, pick with no judge, two tabs: exactly one OK wins, the rest 409"
C_LIVE_CAP = "live_model_cap: leg B makes at most 30 ultra_plan model calls"


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-14-ultra-wild --break --fault=ultra-ok-ignores-sha (relay side): ultra_run.approve
        # ignores the posted sha256 and uses the row's own, so a stale card's OK starts the run: C_STALE alone
        # (the stale case's plan is read-only, so nothing is sent; the race cases post the right sha anyway).
        "ultra-ok-ignores-sha": Fault(_ok_ignores_sha, (C_STALE,)),
    }


def _ok_ignores_sha() -> None:
    import ultra_run

    orig = ultra_run.approve

    async def approve(plan_id, owner_user_id, sha256, creds):
        row = await ultra_run._row(plan_id, owner_user_id)
        return await orig(plan_id, owner_user_id, row.plan_sha256 if row is not None else sha256, creds)

    ultra_run.approve = approve
