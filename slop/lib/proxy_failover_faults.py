"""Shared proxy-failover check names for scenario and fault targets."""

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
    """The failover step gone (as before the proxy failover): a pool proxy confirmed bad
    and rechecked is surfaced, but its Creators are never moved to a healthy pool proxy
    (bug class: every read and send of theirs fails until the proxy answers again)."""
    import proxy_health

    def no_move(label: str) -> list:
        proxy_health.log.warning("slop fault proxy-failover-never-moves: %s not failed over", label)
        return []
    proxy_health._failover = no_move


def _pool_failover_ignores_tiers() -> None:
    """The failover and attach as before INFLOWW_PROXIES tiers: one group, the least-used answering proxy of the
    whole pool (bug class: a Creator moved off, or a login bound, onto an idler, worse DC one)."""
    import proxies
    proxies._tiers = lambda entries, first=None: [list(entries)]


def _pool_assign_drops_unanswered_login() -> None:
    """The attach as review round 1 left it: a Creator on no pool proxy for whom no pick
    answers its probe gets a LookupError (409; a Browserbase login says "nothing was
    saved") and is bound to nothing (bug class: a finished login thrown away on a
    pool-wide probe blip)."""
    import proxies

    real = proxies.assign_pool

    def assign_pool(account_id, *, bad, dead, due, geo, verify, rng=None):
        answers: list[bool] = []

        def counted(p):
            answers.append(bool(verify(p)))
            return answers[-1]
        was_on_pool = proxies.is_pool(proxies.get_for_account(account_id))
        out = real(account_id, bad=bad, dead=dead, due=due, geo=geo, verify=counted, rng=rng)
        if not was_on_pool and not out[1] and answers and not any(answers):
            proxies.unbind_pool(account_id)
            raise LookupError("slop fault pool-assign-drops-unanswered-login: no Inflowwww proxy answers")
        return out
    proxies.assign_pool = assign_pool


def _proxy_recheck_never_runs() -> None:
    """No recheck of a bad proxy (as before the proxy failover): once confirmed bad it stays
    bad until a call through it happens to answer; with its Creators moved away nobody calls
    through it, so it never comes back as a standby (bug class: the pool shrinks for good)."""
    import proxy_health
    proxy_health._arm_recheck = lambda label: proxy_health.log.warning(
        "slop fault proxy-recheck-never-runs: %s not rechecked", label)


def _proxy_confirm_probes_trace() -> None:
    """The watcher's confirm and rechecks back on Cloudflare's trace (the pre-fix probe): a proxy
    that answers the trace yet refuses CONNECT to OF is never confirmed bad (bug class: the probe
    tests another host than the one failing)."""
    import proxy_probe
    proxy_probe.probe_of = proxy_probe.probe


def _proxy_decide_recheck_answer_ignored() -> None:
    """service/proxy_health_decide.decide (the shell calls it as `ph.decide` at each step) reads an
    answering recheck as a failed one (a reducer that lost the up transition): a revived proxy nobody
    calls through stays bad for good (bug class: the pool shrinks; the standby is lost)."""
    import proxy_health_decide as ph
    real = ph.decide
    ph.decide = lambda st, ev: real(st, ph.RecheckResult(ok=False, flapping=ev.flapping) if isinstance(ev, ph.RecheckResult) else ev)


# ── proxy watcher claim hand-off (rwl/proxy-watch-gap) ──
WATCH_RELEASE_LAG_S = 60.0   # > the proxy-failover scenario's REWATCH_MS and its pool-wide outage (ALL_DEAD_S)


def _proxy_watch_claim_released_late() -> None:
    """The watcher's claim released as before rwl/proxy-watch-gap: after the watcher returned
    (`_watch`'s finally), not in its last step's decide (every Unwatch dropped). The window between
    the two, microseconds in the relay, is widened to WATCH_RELEASE_LAG_S so traffic can land in it:
    a streak's DOWN_AFTER-th error there reads the claim, starts no watcher, and the proxy sits at
    DOWN_AFTER errors unwatched until a counted error after the release (bug class: a proxy that dies
    again right as its last watcher ended is never confirmed bad, so never surfaced or failed over)."""
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
    proxy_health._watch = watch   # `_step` spawns `_watch` by its module name


def _proxy_recheck_unwatches_at_threshold() -> None:
    """The recheck phase's not-bad exit as before rwl/proxy-watch-gap's round 1 (F1): a recheck step that
    finds the proxy back up ends the watcher (Unwatch) whatever its count, where decide now goes back to
    the confirm phase when a streak reached DOWN_AFTER meanwhile (it started no watcher: this one held the
    claim). Bug class: a proxy revived and dead again during a recheck's sleep sits at DOWN_AFTER errors
    unwatched, never confirmed bad, so never surfaced or failed over."""
    import proxy_health_decide as ph
    real = ph.decide

    def decide(st, ev):
        st2, effects, nxt = real(st, ev)
        if isinstance(ev, (ph.RecheckWait, ph.RecheckDue, ph.RecheckResult)) and nxt == ph.Wait(0.0, ph.ConfirmDue):
            return st2, [*effects, ph.Unwatch()], None
        return st2, effects, nxt
    ph.decide = decide   # the shell calls `ph.decide` at each step
# ── end proxy watcher claim hand-off ──


def register(Fault) -> dict:
    return {
    # slop/run proxy-failover --break (the scenario's FAULT)
    "proxy-failover-never-moves": Fault(_proxy_failover_never_moves, (
        C_MOVE,
    )),
    # slop/run proxy-failover --break --fault=pool-failover-ignores-tiers
    "pool-failover-ignores-tiers": Fault(_pool_failover_ignores_tiers, (
        C_BIND,
        C_TIER,
    )),
    # slop/run proxy-failover --break --fault=pool-assign-drops-unanswered-login
    "pool-assign-drops-unanswered-login": Fault(_pool_assign_drops_unanswered_login, (
        C_LOGIN_ALL_DEAD,
    )),
    # slop/run proxy-failover --break --fault=proxy-recheck-never-runs
    "proxy-recheck-never-runs": Fault(_proxy_recheck_never_runs, (
        C_MOVE,
        C_BACK,
    )),
    # slop/run proxy-failover --break --fault=proxy-confirm-probes-trace
    "proxy-confirm-probes-trace": Fault(_proxy_confirm_probes_trace, (
        C_PROBE_OF,
    )),
    # slop/run proxy-failover --break --fault=proxy-decide-recheck-answer-ignored
    "proxy-decide-recheck-answer-ignored": Fault(_proxy_decide_recheck_answer_ignored, (
        C_BACK,
    )),
    # ── proxy watcher claim hand-off (rwl/proxy-watch-gap) ──
    # slop/run proxy-failover --break --fault=proxy-watch-claim-released-late: the re-watch check, and the
    # pool-wide outage's (the proxy revived just before it dies again inside the widened window too)
    "proxy-watch-claim-released-late": Fault(_proxy_watch_claim_released_late, (
        C_REWATCH,
        C_NOSTANDBY,
    )),
    # slop/run proxy-failover --break --fault=proxy-recheck-unwatches-at-threshold: the recheck-gap check
    "proxy-recheck-unwatches-at-threshold": Fault(_proxy_recheck_unwatches_at_threshold, (
        C_RECHECK_GAP,
    )),
    # ── end proxy watcher claim hand-off ──
    }
