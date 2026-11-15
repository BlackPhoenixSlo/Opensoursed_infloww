"""The View lease / purchases poll tiers' break-it-once faults (phase-01 1a; service/view_lease.py,
service/transaction_ingest.py `_seller_account_ids` / `_SELLING_KINDS` / `live_account_ids`,
service/purchase_poll_decide.py `after` / `held` / `catch_up`, service/app_open_warm.py, all looked
up in their modules at call time; the warm's page fault and the strip's lease fault in the browser): lib/faults.py
merges `register(Fault)`
into FAULTS. The check names live here and
scenarios/2026-11-09-view-lease-purchases-tiers.py imports them (a leg's own faults: lib/view_lease_<leg>_faults.py).
"""
from __future__ import annotations

LEASED_FAST = "LEASED_FAST: a Creator an owner, chatter or All-view tab leases is polled every PURCHASES_POLL_FAST_S"
SELLER_FAST = ("SELLER_FAST: a Creator with an enabled Seller (a rule of the scenario's SELLER_KINDS) "
               "is polled every PURCHASES_POLL_FAST_S with no client connected")
IDLE_SLOW = ("IDLE_SLOW: an Idle Creator (no Seller, nobody's lease) is polled every PURCHASES_POLL_SLOW_S "
             "only, with an admin and a chatter signed in, and its seeded purchase still flips")
ALL_VIEW_NO_LEASE = ("ALL_VIEW_NO_LEASE: an All-view tab leases only its on-screen Creators, never the rest it "
                     "can access (answer and Relay registry)")
SELECT_REFRESH = ("SELECT_REFRESH: a newly leased Creator, and a Creator another holder leases when a tab selects "
                  "it, get a purchases read within 2 s of the renewal (Caller kind select_refresh)")
FAN_WRITES_KEPT = ("FAN_WRITES_KEPT: sends and automation runs during the tiers are kept: every send OF got, every "
                   "seeded job ran once, counts match")
CLICK_SETTLED = "UI: every Creator-tab click settles (tab selected, rail and badge reads done) within CLICK_TIMEOUT_S"
WARM_ONCE = ("WARM_ONCE: opening a non-Messages-Pro page (Settings) with a Creator selected warms every accessible "
             "Creator once (one feed read each: the selected one its Select refresh, the rest Caller kind "
             "walk:app_open_warm); a second open inside the reuse window (Messages Pro) is `reused` and adds no OF read")
WARM_STAGGER = ("WARM_STAGGER: the warm's reads on one proxy start at least APP_OPEN_WARM_GAP_S apart (after the "
                "selected Creator's Select refresh on its proxy too), leased Creators first, proxies in parallel")

BACKOFF_429 = ("BACKOFF_429: a 429 on a Creator's purchases feed holds its next poll for the longer of OF's asked "
               "wait and the ladder (PURCHASES_BACKOFF_BASE_S doubling; OF's \"allow 1 seconds\" still climbs), never "
               "past PURCHASES_BACKOFF_DEMAND_MAX_S for a leased or Seller Creator (a longer Retry-After included)")
UNAUTH_NOT_DEAD = ("UNAUTH_NOT_DEAD: a plain 401 on the feed backs the Creator off on the same ladder and never flags "
                   "it a Dead session")
DEAD_SILENT = ("DEAD_SILENT: a Creator its feed flagged a Dead session (OF's 2FA answer) gets no feed call after the "
               "flag, while its recovery probe still runs")
DEAD_RESUME = "DEAD_RESUME: once a re-capture clears the flag, the Creator's feed is read again within one cycle"
UI_LEASE_VISIBLE = ("UI_LEASE_VISIBLE: in the browser, the All view's posted lease set (its own POST /admin/view-lease "
                    "bodies) equals the on-screen Creators (strip + rail + open chat + OF Manager's column), scrolling "
                    "the strip or the column changes it, an open chat's Creator stays posted off the strip, and a "
                    "hidden tab posts nothing (its lease lapses within the TTL) until shown again, when it posts at once")
FEED_CATCHUP = ("FEED_CATCHUP: an Idle Creator with 25 purchases inside one slow gap gets all 25 flipped (its poll "
                "pages back after a gap)")

_OLD_SELLING_KINDS = ("welcome_chatter_for_info", "ppv_send", "reengage_buyers")


def _admin_online_all_fast() -> None:
    """The pre-1a gate's admin branch: any admin seen in the last 10 min makes every Creator fast
    (transaction_ingest._online_account_ids before phase-01), unioned into the Seller set (so every Creator polls fast)."""
    from datetime import datetime, timedelta

    from sqlalchemy import select

    import transaction_ingest as ti
    from db.engine import get_session
    from db.models import Account, User

    real = ti._seller_account_ids

    async def wanted() -> set[str]:
        out = set(await real())
        cutoff = datetime.utcnow() - timedelta(seconds=600)
        async with get_session() as s:
            admin = (await s.execute(select(User.id).where(User.last_seen_at >= cutoff,
                                                           User.is_admin.is_(True)).limit(1))).first()
            if admin:
                out |= {r[0] for r in (await s.execute(select(Account.id))).all()}
        return out

    ti._seller_account_ids = wanted


def _seller_kinds_old() -> None:
    """The pre-1a Seller list: two kinds with no runner and one that never sells."""
    import transaction_ingest as ti

    ti._SELLING_KINDS = _OLD_SELLING_KINDS


def _all_view_leases_every_creator() -> None:
    """An All-view renewal (no `selected`) leases every Creator its principal can access, not
    the ids it named (the "All" scope as a lease, ADR-0031's rejected option)."""
    import accounts as account_registry
    import view_lease
    from chatters import get_request_chatter
    from relay_host import get_request_user

    real = view_lease.renew

    def renew(holder, account_ids, selected, now=None):
        if selected is None and account_ids:
            p = get_request_user() or get_request_chatter()
            account_ids = [a for a in (p.account_ids or ()) if not account_registry.is_watcher(a)]
        return real(holder, account_ids, selected, now)

    view_lease.renew = renew


def _select_refresh_on_gain_only() -> None:
    """The Select refresh only for a Creator nobody leased before: a tab selecting a Creator
    another holder already leases gets no immediate read."""
    import view_lease

    real = view_lease.renew

    def renew(holder, account_ids, selected, now=None):
        before = view_lease.leased_ids(now)
        return [a for a in real(holder, account_ids, selected, now) if a not in before]

    view_lease.renew = renew


# The heartbeat as if it lived in Messages Pro only (the warm the owner did not want): a page's view-lease post
# carries `opened: true` only on /messages-pro. Wraps fetch in the page, before the app's code.
_WARM_MESSAGES_PRO_ONLY_JS = r"""
(() => {
  const real = window.fetch;
  window.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.includes("/admin/view-lease") && init && typeof init.body === "string"
          && !location.pathname.startsWith("/messages-pro")) {
        const b = JSON.parse(init.body);
        if (b.opened) init = Object.assign({}, init, { body: JSON.stringify(Object.assign(b, { opened: false })) });
      }
    } catch (_e) { /* not ours */ }
    return real.call(this, input, init);
  };
})();
"""


def _warm_unstaggered() -> None:
    """Every Creator its own group and no gap: an open reads every Creator at once, whatever proxy it shares."""
    import app_open_warm

    app_open_warm._egress = lambda aid: (f"each:{aid}", f"each-{aid}")
    app_open_warm.GAP_S = 0.0


def _feed_429_ignored() -> None:
    """The pre-ladder feed: a 429 changes nothing, the Creator is polled again on its next cycle."""
    import purchase_poll_decide as d

    real = d.after

    def after(state, outcome, started, answered):
        if outcome.kind == "rate_limited":
            outcome = d.Outcome("error")
        return real(state, outcome, started, answered)

    d.after = after


def _dead_still_polled() -> None:
    """The live set without the dead-session filter: a flagged Creator keeps being polled (every caller looks
    `transaction_ingest.live_account_ids` up at call time: the loop, poll_now, the supervisor, the warm)."""
    import accounts as account_registry
    import account_health
    import transaction_ingest as ti

    async def live() -> list[str]:
        off = await account_health.deactivated_ids()
        return [m["id"] for m in account_registry.list_accounts() if m.get("has_session") and m["id"] not in off]

    ti.live_account_ids = live


def _dead_held_in_poll_state() -> None:
    """`dead` remembered in the poll's own memory (a hold nothing clears): a cleared flag never resumes."""
    import dataclasses

    import purchase_poll_decide as d

    real_after, real_held = d.after, d.held

    def after(state, outcome, started, answered):
        if outcome.kind == "dead":
            return dataclasses.replace(state or d.PollState(), step=-1)
        return real_after(state, outcome, started, answered)

    def held(state, t, now, ahead):
        return (state is not None and state.step == -1) or real_held(state, t, now, ahead)

    d.after, d.held = after, held


def _feed_no_catchup() -> None:
    """No paging back after a gap: the poll reads its newest page only."""
    import purchase_poll_decide as d

    d.catch_up = lambda state, now: False


# The strip leasing every open tab, not the ones on screen (CreatorTabs' `useOnScreenLease("strip")` joined by a
# `useViewLease` of every open tab). `next dev` (webpack) serves the module inside an eval string, its quotes escaped
# (\"): the group keeps them.
_STRIP_LEASES_ALL_TABS = ((r'\(0,\s*([\w$]+)\.useOnScreenLease\)\((\\?)"strip\2"\)',
                           r'((0, \1.useViewLease)(open.map((a) => a.id)), (0, \1.useOnScreenLease)(\2"strip\2"))'),)


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-09-view-lease-purchases-tiers --break (the scenario's FAULT)
        "admin-online-all-fast": Fault(_admin_online_all_fast, (IDLE_SLOW,)),
        # ... --break --fault=<name>
        "seller-kinds-old": Fault(_seller_kinds_old, (SELLER_FAST,)),
        "all-view-leases-every-creator": Fault(_all_view_leases_every_creator, (ALL_VIEW_NO_LEASE,)),
        "select-refresh-on-gain-only": Fault(_select_refresh_on_gain_only, (SELECT_REFRESH,)),
        "warm-messages-pro-only": Fault(None, (WARM_ONCE,), browser_js=_WARM_MESSAGES_PRO_ONLY_JS),
        "warm-unstaggered": Fault(_warm_unstaggered, (WARM_STAGGER,)),
        "feed-429-ignored": Fault(_feed_429_ignored, (BACKOFF_429,)),
        "dead-still-polled": Fault(_dead_still_polled, (DEAD_SILENT,)),
        "dead-held-in-poll-state": Fault(_dead_held_in_poll_state, (DEAD_RESUME,)),
        "feed-no-catchup": Fault(_feed_no_catchup, (FEED_CATCHUP,)),
        "strip-leases-all-tabs": Fault(None, (UI_LEASE_VISIBLE,), browser=_STRIP_LEASES_ALL_TABS),
    }
