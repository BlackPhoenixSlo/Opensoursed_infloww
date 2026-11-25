C_BIND = "pool: ON_POOL Creators bound least-used through /admin/proxy-pool/assign, each warm-up tunneled"
C_MOVE = "dead pool proxy: its Creators are on a healthy pool proxy within budget, reads and sends answer again"
C_TIER = ("pool tiers: the dead tier-0 proxy's Creators all moved to the other tier-0 proxy, none to the idler "
          "tier-1 one (INFLOWW_PROXIES `|`)")
C_SURF = "dead pool proxy: surfaced before the move (pool bad=1, proxy_down on exactly its Creators)"
C_LOGIN = "login during the outage: bound once, to a healthy pool proxy, and never moved"
C_SENDS = "sends never duplicated: each 200 once in OnlyFans' record, each 502 never, no text twice"
C_HEALTHY = "healthy pool proxies: every read and send of their Creators answered 200 throughout"
C_BACK = ("revived proxy: the recheck brings it back within budget and the next new Creator lands on the least-used "
          "proxy (the revived one, once its Creators moved) and reads through it")
C_NOSTANDBY = "every pool proxy dead: nobody moves (bindings identical) and every pool Creator reads proxy_down"
C_LOGIN_ALL_DEAD = ("login during a pool-wide outage: no probe answers, yet the session is saved and bound to a pool "
                    "proxy within budget (a login is never lost; every-proxy-bad: test_proxy_health)")
C_REWATCH = ("re-watch: a pool proxy that dies for good right after a blip ended its watcher is watched again and "
             "surfaced within budget (its Creator reads proxy_down)")
C_RECHECK_GAP = ("recheck-gap: a bad proxy an answer brings back while its watcher sleeps before a recheck, then "
                 "DOWN_AFTER failed sends before it wakes, is confirmed bad again by that watcher within budget; "
                 "a Test click while it is bad leaves it bad")
C_WIRE = "lib/of_wire.py saw only signed calls it models"
C_PROBE_OF = ("the watcher's confirm and rechecks probe OnlyFans' API host (robots.txt) with no account and no cookie "
              "(proxy_probe.probe_of)")


def _proxy_failover_never_moves() -> None:
    import proxy_health

    def no_move(label: str) -> list:
        proxy_health.log.warning("slop fault proxy-failover-never-moves: %s not failed over", label)
        return []
    proxy_health._failover = no_move


def _pool_failover_ignores_tiers() -> None:
    import proxies
    proxies._tiers = lambda entries, first=None: [list(entries)]


def _pool_assign_drops_unanswered_login() -> None:
    import proxies

    real = proxies.assign_pool

    def assign_pool(account_id, *, bad, dead, due, geo, verify, deactivated, rng=None):
        answers: list[bool] = []

        def counted(p):
            answers.append(bool(verify(p)))
            return answers[-1]
        was_on_pool = proxies.is_pool(proxies.get_for_account(account_id))
        out = real(account_id, bad=bad, dead=dead, due=due, geo=geo, verify=counted,
                   deactivated=deactivated, rng=rng)
        if not was_on_pool and not out[1] and answers and not any(answers):
            proxies.unbind_pool(account_id)
            raise LookupError("slop fault pool-assign-drops-unanswered-login: no Inflowwww proxy answers")
        return out
    proxies.assign_pool = assign_pool


def _proxy_recheck_never_runs() -> None:
    import proxy_health
    proxy_health._arm_recheck = lambda label: proxy_health.log.warning(
        "slop fault proxy-recheck-never-runs: %s not rechecked", label)


def _proxy_confirm_probes_trace() -> None:
    import proxy_probe
    proxy_probe.probe_of = proxy_probe.probe


def _proxy_decide_recheck_answer_ignored() -> None:
    import proxy_health_decide as ph
    real = ph.decide
    ph.decide = lambda st, ev: real(st, ph.RecheckResult(ok=False, flapping=ev.flapping) if isinstance(ev, ph.RecheckResult) else ev)


# > the proxy-failover scenario's REWATCH_MS and its pool-wide outage (ALL_DEAD_S)
WATCH_RELEASE_LAG_S = 60.0


def _proxy_watch_claim_released_late() -> None:
    import time

    import proxy_health
    import proxy_health_decide as ph
    real_decide, real_watch = ph.decide, proxy_health._watch

    def decide(st, ev):
        st2, effects, nxt = real_decide(st, ev)
        return st2, [e for e in effects if not isinstance(e, ph.Unwatch)], nxt

    def watch(label: str) -> None:
        try:
            real_watch(label)
        finally:
            time.sleep(WATCH_RELEASE_LAG_S)
            with proxy_health._lock:
                proxy_health._watchers.discard(label)
    ph.decide = decide
    proxy_health._watch = watch


def _proxy_recheck_unwatches_at_threshold() -> None:
    import proxy_health_decide as ph
    real = ph.decide

    def decide(st, ev):
        st2, effects, nxt = real(st, ev)
        if isinstance(ev, (ph.RecheckWait, ph.RecheckDue, ph.RecheckResult)) and nxt == ph.Wait(0.0, ph.ConfirmDue):
            return st2, [*effects, ph.Unwatch()], None
        return st2, effects, nxt
    ph.decide = decide


def register(Fault) -> dict:
    return {
    "proxy-failover-never-moves": Fault(_proxy_failover_never_moves, (
        C_MOVE,
    )),
    "pool-failover-ignores-tiers": Fault(_pool_failover_ignores_tiers, (
        C_BIND,
        C_TIER,
    )),
    "pool-assign-drops-unanswered-login": Fault(_pool_assign_drops_unanswered_login, (
        C_LOGIN_ALL_DEAD,
    )),
    "proxy-recheck-never-runs": Fault(_proxy_recheck_never_runs, (
        C_MOVE,
        C_BACK,
    )),
    "proxy-confirm-probes-trace": Fault(_proxy_confirm_probes_trace, (
        C_PROBE_OF,
    )),
    "proxy-decide-recheck-answer-ignored": Fault(_proxy_decide_recheck_answer_ignored, (
        C_BACK,
    )),
    "proxy-watch-claim-released-late": Fault(_proxy_watch_claim_released_late, (
        C_REWATCH,
        C_NOSTANDBY,
    )),
    "proxy-recheck-unwatches-at-threshold": Fault(_proxy_recheck_unwatches_at_threshold, (
        C_RECHECK_GAP,
    )),
    }
