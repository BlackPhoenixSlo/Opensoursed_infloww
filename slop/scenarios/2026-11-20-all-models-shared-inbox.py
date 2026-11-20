"""Messages Pro under All Models shared by several chatters: what it costs at OF's wire, and how stale it goes.

World: `flat_agency` with `all_models_creators` Creators (10 small) in one Agency, each a captured session (the
relay's REAL OFClient against lib/of_wire.py, `OF_WIRE`), OF's chat list per Creator (lib/all_models_wire.py:
the first `all_models_chats` seeded fans, newest first, the first `all_models_unread` unread; `filter=unread`
honoured; OF's 10-row cap per response; mark-as-read modelled; `/users/me` `chatMessagesCount` = unread chats over
the whole list). DEEP_K Creators (creators[1:4]) hold DEEP_CHATS chats instead, rows DEEP_UNREAD unread too (below
page 0's 25 rows: a rows-based count cannot equal OF's). Three chatters (A, B, C: seed/chatters.py, their own
logins), each with every Creator in its Employee setup, and a fourth, D, the same, whose tab opens only in phase 10.
Each chatter has its own Chromium context (one browser) on
`/messages-pro`, scope All (localStorage `chatterly:scope`). Nothing is routed or held: the screen bundle, the rail,
the strip and the open chat's reads all reach the relay and the fake OF.

Phases (each: the fake-OF calls by route with t0 in the phase, /api2/ ones per Creator, and the relay's own counter
by Caller kind (lib/of_call_stats.py); metric `of_budget_<phase>`, all in `of-budget.json`):
  1 open_first         A opens cold; settled = rows shown, the App-open warm read every Creator's feed (the warm's
                       first read; one Creator at a time on the one exit, ~3.3 s each, measured run 1), the wire
                       quiet. Screenshot. The window holds B's open too: `a_own_total` = total - B's attributed.
  2 open_within_reuse  B opens while A's warm still runs (a 10-Creator warm outlasts REUSE_S: run 1, B after A
                       settled, found 9 of 10 aged out): once B_AFTER_FED Creators had their feed read (>= 2 warms
                       done), cap B_OPEN_CAP_S after A's `opened` post. B's calls: the relay counter's rows by
                       Caller kind but the warm's (`walk:app_open_warm`) and the Shared refresher's
                       (`walk:shared_refresher`, its own Cycle, no tab's: `refresher_calls_in_window`), from just
                       before B's navigation until B settled (A's tab is quiet then: its reads are served from the
                       warm's entries).
  3 open_after_reuse   C opens C_AFTER_A_OPEN_S after A's open at least, and C_PAST_WARM_S + REUSE_S past phase 1's
                       end (every warm landed before it). With the Shared refresher on its warm nets against the
                       Last refreshes (ADR-0044): a Creator within its Cycle is `reused`, so this phase cannot isolate
                       the refresher (phase 10 does); a metric only.
  4 idle               the purchases loop starts (`POST /__slop/fast-poll`, LOOP_LEAD_S lead), then IDLE_S with
                       three tabs open: calls per minute, total and per Creator. `/admin/accounts` `freshness`
                       (owner, Relay memory, 0 OF calls) sampled every FRESH_EVERY_S. `of_budget_idle.
                       refresher_per_cycle`: the counter's `walk:shared_refresher` `/users/me` and chats-list calls
                       per Creator (<= 1 read and <= 1 window a Cycle; a window read only after a drift, none here).
                       Tab A's Unread chip text sampled every FRESH_EVERY_S too (DOM only, 0 OF calls): QUIET_NOT_STALE.
  5 incoming           PLAIN_DMS DMs to listed fans on as many Creators, DM_EVERY_S apart; then one DM from a fan not
                       in the list and two tips. Per event and tab, the lag until a row shows its text (polled every
                       LAG_POLL_S, cap LAG_CAP_S). OF calls per event. Screenshot.
  6 mark_read          A clicks an unread chat of Creator X; B's and C's time until that row's unread dot clears and
                       their Unread chip count drops (cap MARK_CAP_S, poll MARK_POLL_S; None: not within the cap).
                       A METRIC: a sibling PR adds the cross-chatter read event and owns that check. B's roster-counts
                       before and after. Screenshots of B at the click and at the end.
  7 reply              A replies in that chat (the composer; an HTTP send as A if the composer fails): the time until
                       B's row shows it (cap REPLY_CAP_S: no event patches a teammate's Fan List on a person's send,
                       app/hooks/useInboxRealtime.ts:86-91, `chat_responded` only feeds the bell; so B's 90 s
                       head-page poll, app/hooks/useChatList.ts). Metric. Screenshot of B.
  8 read_on_of         a chat of Creator Y read on OF's own site (`mark_read_out_of_band`): per tab the time until
                       its row clears and its Unread chip drops (`cleared_ms`, `chip_dropped_ms`, cap OOB_CAP_S), Y's
                       lease per tab (its last view-lease answer), Y's accounts `unread_total.n` before / after vs the
                       fake's counter (side effect). Screenshot of B. Then B over HTTP: the All list page 0 (the inbox
                       bundle) and the `filter=unread` list for X and Y: `unread_parity` (unread in All but not in
                       the unread list, and the reverse), metric and `unread-parity.json`.
  8b fresh_prep        one page-0 unread chat on each DEEP Creator read on OF's own site, then FRESH_PREP_S (one Cycle +
                       tick + the drift's window read) so no drift read lands in phase 9's idle count. Metric
                       `fresh_prep` (accounts totals vs the fake's counters).
  9 idle_one_tab       (after `bg_lane_wedge` end, so phases 5-8 keep all three tabs) B and C close their tabs, A
                       alone for IDLE_S, `freshness` sampled as in 4. Metric `idle_refresher_per_creator_min {n3, n1}`
                       (the counter's `walk:shared_refresher` calls per Creator per minute, `idle` vs this; lib/
                       all_models_refresher.py), `refresh_staleness` (max now - `at` over both idle phases' samples),
                       `data_age` (tab A's chip samples over both idle phases: `quiet_stale_samples` those showing "as
                       of", null when no text was read; `samples`; lib/all_models_refresher.py `quiet_stale`).
 10 open_after_cycle   (A's tab still open, the refresher still reading) D opens, at least LAST_WARM_GAP_S after the
                       last warm (phase 3's end), past every Creator's 60 s Cycle: only the refresher's Last refreshes
                       can make D's warm `reused`. Just before D's navigation one `/admin/accounts` `freshness` sample
                       (owner, 0 OF calls): the Creators within their Cycle until D's `opened` post answered
                       (lib/all_models_refresher.py `fresh_until`). Metric `of_budget_open_after_cycle` (+ D's
                       `own_total`, `warmed_per_creator`, its `warm` answers). D's open is also the fresh session
                       (empty browser storage, every Creator, > 1 Cycle after fresh_prep): metric `fresh_session`
                       {badge_first: the Unread chip's first number, badge_ms: navigation to it, truth: the fake's
                       `chatMessagesCount` summed, diff}, the accounts answer's totals vs the fake's per Creator (Y's
                       recorded), screenshots `fresh-session-trigger` (at the first number) / `fresh-session-settled`.
 11 no_tab             A and D close: NO_TAB_S with no tab open. Metric `refresher_calls_no_tab`: the counter's
                       `walk:shared_refresher` calls from NO_TAB_GRACE_S after the close (one 5 s tick, the relay's
                       <= 1 s disconnect poll, the counter's 1 s flush) to the phase's end.

Checks (names in lib/all_models_faults.py):
  SECOND_OPEN_SHARED  B's `opened` post answered `warm: reused` (accounts_admin_api.py:668: no Creator started,
                      every one warmed within REUSE_S or still queued in A's warm), B's attributed calls hold no `GET
                      /api2/v2/chats`, and at most SECOND_OPEN_MAX_PER_CREATOR other OF calls a Creator (thread reads
                      aside: get_messages_tail, prefetch). Skipped when A's oldest finished warm was already older
                      than REUSE_S - REUSE_MARGIN_S at B's post (timing, no verdict).

Metric `bg_lane_wedge` (after phase 5 and at the end): per Creator the background lane's waiters
(`GET /admin/priority-lanes/stats`, owner) and every tab read in flight longer than WEDGE_AGE_S. Run 1: two tabs'
`/api/of/v2/users/notifications/money` after a tip held both background slots of one Creator for good (the route's
two gathered `_notifications_read`s: one borrows the lease, the other blocks in `_lane_acquire`; server.py:663,
4190, 2585-2591, bg_lane.py:115-117); the relay's Traceback invariant reports it, nothing here masks it.
  IDLE_BUDGET         every Creator <= IDLE_MAX_PER_CREATOR_MIN calls a minute in phase 4.
  DM_NO_LIST_REREAD   no `GET /api2/v2/chats` from the first plain DM until all are shown + DM_TAIL_S.
  DM_ROW_LAG          p95 over the plain DMs x 3 tabs <= DM_ROW_LAG_P95_MS (a sample past the cap counts as the cap).
  REFRESHER_FLAT_IN_N n3 and n1 both in [0.8, 1.2], n3 - n1 <= 0.25 (cost flat in chatters; a refresher reading
                      nothing fails the floor).
  REFRESH_WITHIN_CYCLE every sample's every Creator has a Last refresh at most `cycle_s` + 10 s old.
  REFRESHER_STOPS_WITHOUT_TABS refresher_calls_no_tab == 0 (passes for a refresher that never reads: the floor above
                      catches that one).
  OPEN_AFTER_CYCLE_REUSED no Creator within its Cycle at D's open has a `walk:app_open_warm` call in D's window; D's
                      `opened` answer `reused` (`started` only when a Creator past its Cycle was warmed: the refresher
                      reads at the first 5 s tick past a slot, so at the 60 s floor about a third of opens meet one,
                      i; that warm is then its one read); D's own calls (the counter's rows in its window but the
                      warm's, the refresher's and the `loop:*` kinds) <= OPEN_TOTAL_MAX 40; >= half the Creators
                      within Cycle.
  READ_ON_OF_CLEARS   every tab's row cleared and Unread chip dropped within CLEAR_MAX_MS of Y's read on OF.
  FRESH_BADGE_TRUE    fresh_session.diff == 0 (no number: fail).
  QUIET_NOT_STALE     data_age.quiet_stale_samples == 0 over >= 1 chip text read (tab A's Unread chip holds no "as of":
                      the app shows it past Cycle + 40 s slack on a 15 s tick, ~100-115 s; the ping's `fresh` every
                      20 s keeps an unchanged Creator's `at` within ~Cycle + 10 + 20 s; no text read: fail).

Budgets, from the product (not measured here first):
  - app_open_warm.REUSE_S 30 (service/app_open_warm.py:73), `start` answers `reused` inside it (:274): B's open
    reads nothing the warm read; its 30 s entries (notifications count, rail tip and purchases lists:
    server.py:4232/4236) may have lapsed for the earliest Creators since: 3, + 1 slack = 4.
  - the chats window: list_chats TTL 600 s + SWR 600 s (server.py:3240/3245), the roster rewarm's key is the
    bundle's page 0 (accounts_admin_api.py:321-322): a second open, or a DM (event_transcoder.py:321 patches the
    cached window; :337 busts only roster_count, refolded from the window under _ROSTER_WINDOW_MAX_AGE_S 300,
    server.py:3254), reads no list.
  - idle, per Creator, every Creator-keyed entry at most ceil(120/TTL)+1 times in IDLE_S 120: the feed poll (FAST_S
    30, purchase_poll_decide.py:37), count, tip, purchases (30 s), users/me (60 s, server.py:3039) = 5+5+5+5+3 = 23,
    + a chats window refresh (3 reads at OF's cap) = 26, + the Shared refresher's `/users/me` (cache bypass, once a
    Cycle: both Cycle Knobs at the 60 s floor, RELAY_ENV) ceil(120/60)+1 = 3 -> 29 in 120 s ~ 14.5/min -> 15. No tab
    term: three tabs cost what one does. Measured with IDLE_S 90 and no refresher: max_per_creator 2.67/min; expected
    with it <= 3.7 (+1 read/min, i).
  - the refresher (service/shared_refresher.py, shared_refresher_decide): one read per Creator per Cycle; a Cycle at
    the 60 s floor (SPREAD 0.9-1.0 x 60 clamps to 60) read on the first 5 s tick past due -> ~1/min whatever the tab
    count (n3, n1 in [0.8, 1.2]; the window's 1-2 reads per Creator average out over 10 Creators, i); a Last refresh
    ages its Cycle + one tick + the exit's queue (GAP_S 1 s a read) <= cycle_s + 10 s; no tab, `tracked` empty: no
    job planned, a queued one dropped at its turn (`_wanted`).

Bypasses (declared): OF at its wire (lib/of_wire.py + lib/all_models_wire.py, 50 ms a call); fan DMs and tips at
the pump boundary (`POST /__slop/of-ws-frame`, actors/fan_dm.py); the purchases loop started on request
(lib/view_lease_relay.py) after phase 3, so phases 1-3 see only the warm's and the tabs' reads; `/messages-pro` is
compiled by one plain GET first (dev server).
Break-it-once: `warm-ignores-reuse` (the FAULT: `app_open_warm.start` forgets every warm first and ignores the shared
Last refresh): SECOND_OPEN_SHARED and OPEN_AFTER_CYCLE_REUSED. `refresher-per-subscriber` (`--fault=`: one refresher job per tab subscriber per Creator, each its
own exit-queue entry and cache bypass; lib/all_models_faults.py): only REFRESHER_FLAT_IN_N (n3 ~3, n1 ~1).
`unread-total-frozen` (`--fault=`: the Unread total keeps OF's first number): READ_ON_OF_CLEARS and FRESH_BADGE_TRUE.
`fresh-ping-off` (`--fault=`: the ping carries no `fresh`; an unchanged Cycle publishes nothing, so tab A's last
confirmation is its phase-1 warm's, >= ~100 s before `idle` starts): only QUIET_NOT_STALE.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from collections import Counter
from urllib.parse import urlsplit

import httpx

from slop.actors import fan_dm
from slop.lib import all_models_refresher as refresher
from slop.lib import all_models_wire, of_call_stats
from slop.lib.all_models_faults import (DM_NO_LIST_REREAD, DM_ROW_LAG, FRESH_BADGE_TRUE, IDLE_BUDGET,
                                        OPEN_AFTER_CYCLE_REUSED, QUIET_NOT_STALE, READ_ON_OF_CLEARS,
                                        REFRESH_WITHIN_CYCLE, REFRESHER_FLAT_IN_N, REFRESHER_STOPS_WITHOUT_TABS,
                                        SECOND_OPEN_SHARED)
from slop.lib.client import Http
from slop.lib.view_lease_feed import until as _until
from slop.lib.view_lease_rail_scope import read_class
from slop.seed import chatters as chatter_seed

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = "warm-ignores-reuse"
RELAY_ENV = {"OF_CALL_STATS_FLUSH_S": "1", "INGEST_FAST_BOOT_GRACE_S": "0",
             # the Shared refresher on, both Cycles at the 60 s floor: an idle phase sees whole Cycles
             "SHARED_REFRESHER": "1", "SHARED_REFRESHER_LEASE_CYCLE_S": "60", "SHARED_REFRESHER_TAB_CYCLE_S": "60",
             # the Unread total (phase 2): the badge from OF's whole-inbox counter
             "UNREAD_TOTAL": "1"}
# SLOP_AM_KNOBS=off (caller env): both Knobs unset, the relay as main runs it. The Knob-only checks are skipped; the
# rest (second open, idle budget, DMs, 5xx, Traceback) and of-budget.json are the Knob-off proof: no
# `walk:shared_refresher` row in any phase.
KNOBS_OFF = os.environ.get("SLOP_AM_KNOBS") == "off"
if KNOBS_OFF:
    RELAY_ENV = {k: v for k, v in RELAY_ENV.items() if not k.startswith(("SHARED_REFRESHER", "UNREAD_TOTAL"))}
KNOB_CHECKS = (REFRESHER_FLAT_IN_N, REFRESH_WITHIN_CYCLE, OPEN_AFTER_CYCLE_REUSED, READ_ON_OF_CLEARS,
               FRESH_BADGE_TRUE, QUIET_NOT_STALE)

CHATTERS = ("a", "b", "c")
LATE = "d"                   # the fourth chatter: its tab opens only in open_after_cycle
VIEWPORT = (1440, 900)
# Timing.
WARM_REUSE_S = 30.0          # APP_OPEN_WARM_REUSE_S default (service/app_open_warm.py:73), not scaled
REUSE_MARGIN_S = 1.0         # a Creator counts as inside B's window only this much short of REUSE_S
ROWS_TIMEOUT_S = 180.0       # the first rows (next dev compiles /messages-pro on its first hit)
OPENED_WAIT_S = 20.0         # the tab's `opened: true` view-lease post (ViewLeaseHeartbeat: once its stream is open)
WARM_SETTLE_S = 60.0         # the `opened` post to every Creator's feed read (~3.3 s a Creator on one exit, run 1)
NET_QUIET_S, NET_CAP_S = 2.0, 30.0     # the tab: no relay read in flight for NET_QUIET_S
WIRE_QUIET_S, WIRE_CAP_S = 1.5, 20.0   # the fake OF: no call for WIRE_QUIET_S
STATS_FLUSH_S = 1.5          # the counter file flushes every 1 s (RELAY_ENV)
B_AFTER_FED = 3              # B opens once this many Creators had A's warm's feed read (>= 2 warms done) ...
B_OPEN_CAP_S = 20.0          # ... or this long after A's `opened` post
C_AFTER_A_OPEN_S = 35.0      # C opens at least this long after A's open (spec: > 35 s)
C_PAST_WARM_S = 1.5          # ... and past phase 1's end + REUSE_S
WEDGE_AGE_S = 30.0           # a tab read in flight longer than this counts as stuck (bg_lane_wedge)
LOOP_LEAD_S = 3.0
IDLE_S = 120.0               # two whole 60 s Cycles (phases 4 and 9)
PUMP_UP_S = 30.0             # every Creator's pump socket connects within this (run)
FRESH_EVERY_S = 5.0          # `/admin/accounts` freshness samples and tab A's chip text in phases 4 and 9
LAST_WARM_GAP_S = 240.0      # open_after_cycle: D opens at least this long after the last warm (4 x the 60 s Cycle)
NO_TAB_S = 30.0
NO_TAB_GRACE_S = 7.0         # one refresher tick (5 s) + the stream's disconnect poll (1 s) + the counter flush (1 s)
DM_EVERY_S = 2.0
LAG_POLL_S, LAG_CAP_S = 0.25, 10.0
DM_TAIL_S = 2.0
MARK_POLL_S, MARK_CAP_S = 0.5, 75.0
SEND_WAIT_S = 15.0           # the composer's send to OF's wire (else the HTTP send)
COMPOSER_TIMEOUT_S = 15.0
REPLY_CAP_S = 95.0           # past B's 90 s head-page poll (useChatList.ts): the only path to B's row (docstring 7)
OOB_CAP_S = 90.0             # the watch of Y's read on OF (READ_ON_OF_CLEARS bars at CLEAR_MAX_MS)
CLEAR_MAX_MS = 65_000        # one 60 s Cycle + one tick (5 s): the refresher's `/users/me`, then the drift's window read
FRESH_PREP_S = 75.0          # fresh_prep: one Cycle + tick + the drift's window read, before phase 9's idle count
BADGE_POLL_S = 0.1           # fresh_session: the Unread chip read this often from D's navigation
# Events.
PLAIN_DMS = 6
DM_FAN = 10                  # chat index of the plain-DM fans: read, inside page 0
TIP_FAN = 12
TIPS = (5.0, 12.0)
CHAT_ID_BASE = 7_100_000_000
DEEP_K = 3                   # Creators creators[1:1+DEEP_K] (not 0: its unlisted DM fan is fans[n_chats]; not X, Y)
DEEP_CHATS = 30              # their chats: past page 0's 25 rows
DEEP_UNREAD = (26, 28)       # rows also unread, below page 0
DEEP_READ_FAN = 1            # fresh_prep reads this (unread, page-0) chat on OF's own site
_IDS = itertools.count(9_700_000_000_000)
# Budgets (module docstring).
SECOND_OPEN_MAX_PER_CREATOR = 4
IDLE_MAX_PER_CREATOR_MIN = 15.0
DM_ROW_LAG_P95_MS = 3000
LIST_ROUTE = "GET /api2/v2/chats"
THREAD_ROUTE = "GET /api2/v2/chats/{id}/messages"
WARM_KIND = "walk:app_open_warm"   # the counter's Caller kind of the warm's reads (lib/of_call_stats.py)
THREAD_KEY = "GET /api2/v2/chats/{}/messages"   # the counter's key for THREAD_ROUTE
COMPOSER = 'Press "/" + keyword'   # Composer.tsx placeholder (chatter-crowd)
SCOPE_ALL_JS = "try { localStorage.setItem('chatterly:scope', 'all'); } catch (e) {}"

# Keys of `items` whose marker shows in any row, or whose handle is in one of the first 3 rows (a tip's preview).
FIND_JS = """(items) => {
  const texts = [...document.querySelectorAll('[data-chat-row]')].map((r) => r.textContent || '');
  const top = texts.slice(0, 3);
  return items.filter((it) => texts.some((t) => t.includes(it.marker))
    || (it.handle && top.some((t) => t.includes(it.handle)))).map((it) => it.key);
}"""
# The row holding `handle`: present, its unread dot (FanRow EdgeMarker), and the Unread chip's count (FanListFilters).
ROW_JS = """(handle) => {
  const row = [...document.querySelectorAll('[data-chat-row]')].find((r) => (r.textContent || '').includes(handle));
  const g = document.querySelector('[role="group"][aria-label="Fan List filters"]');
  const el = g ? [...g.querySelectorAll('button')].find((b) => {
    const t = (b.textContent || '').trim();
    return /^Unread(\\s|\\d|$)/.test(t) && !/with tips/i.test(t);
  }) : null;
  let chip = null;
  if (el) { const m = (el.textContent || '').split('as of')[0].match(/(\\d+)/); chip = m ? Number(m[1]) : 0; }
  return { present: !!row, unread: row ? !!row.querySelector('[role="img"][aria-label^="Unread"]') : null,
           chip, rows: document.querySelectorAll('[data-chat-row]').length };
}"""


# The Unread chip's number; null while it shows none (FanListFilters' FilterChip: no count before the badge is ready).
CHIP_JS = """() => {
  const g = document.querySelector('[role="group"][aria-label="Fan List filters"]');
  const el = g ? [...g.querySelectorAll('button')].find((b) => {
    const t = (b.textContent || '').trim();
    return /^Unread(\\s|\\d|$)/.test(t) && !/with tips/i.test(t);
  }) : null;
  const m = el ? (el.textContent || '').split('as of')[0].match(/(\\d+)/) : null;
  return m ? Number(m[1]) : null;
}"""
# The Unread chip's whole text (CHIP_JS's locator); null while no such chip. Holds "as of" when the age shows.
CHIP_TEXT_JS = """() => {
  const g = document.querySelector('[role="group"][aria-label="Fan List filters"]');
  const el = g ? [...g.querySelectorAll('button')].find((b) => {
    const t = (b.textContent || '').trim();
    return /^Unread(\\s|\\d|$)/.test(t) && !/with tips/i.test(t);
  }) : null;
  return el ? (el.textContent || '') : null;
}"""


def _relevant(path: str) -> bool:
    if path.startswith("/admin/perflog") or path.startswith("/events"):   # never ends
        return False
    return path.startswith("/admin/") or path.startswith("/api/")


async def _answer(post: dict, req) -> None:
    try:
        resp = await req.response()
        post["answered_t"] = time.time()
        post["status"] = resp.status if resp else None
        post["answer"] = await resp.json() if resp and resp.status == 200 else None
    except Exception as e:  # noqa: BLE001 — a post still in flight when the page closes
        post["status"], post["answer"] = None, {"error": type(e).__name__}


class Tab:
    """One chatter's Chromium context on /messages-pro: its view-lease posts and its relay reads in flight."""

    def __init__(self, name: str, page) -> None:
        self.name, self.page = name, page
        self.posts: list[dict] = []
        self.inflight: dict = {}
        self.last_end = time.monotonic()
        self.answers: list[asyncio.Future] = []
        page.on("request", self._start)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._done)

    def _start(self, req) -> None:
        p = urlsplit(req.url).path
        if req.method == "POST" and p == "/admin/view-lease":
            try:
                body = json.loads(req.post_data or "{}")
            except ValueError:
                body = {}
            post = {"t": time.time(), "body": body}
            self.posts.append(post)
            self.answers.append(asyncio.ensure_future(_answer(post, req)))
        if _relevant(p):
            self.inflight[req] = time.monotonic()

    def _done(self, req) -> None:
        if self.inflight.pop(req, None) is not None:
            self.last_end = time.monotonic()

    def stuck(self, min_age_s: float) -> list[dict]:
        """Relay reads in flight for at least `min_age_s`: path, Creator header, age."""
        now = time.monotonic()
        out = []
        for req, t in list(self.inflight.items()):
            if now - t >= min_age_s:
                try:
                    aid = req.headers.get("x-account-id")
                except Exception:  # noqa: BLE001
                    aid = None
                out.append({"tab": self.name, "method": req.method, "path": urlsplit(req.url).path,
                            "account": aid, "age_s": round(now - t, 1)})
        return out

    def opened(self, since: float) -> dict | None:
        return next((p for p in self.posts if p["t"] >= since and p["body"].get("opened")), None)

    async def open(self, ctx) -> dict:
        """Navigate, then settle: rows shown, the opening post sent, no relay read in flight for NET_QUIET_S."""
        t0 = time.time()
        await self.page.goto(f"{ctx.app}/messages-pro", wait_until="domcontentloaded", timeout=ROWS_TIMEOUT_S * 1000)
        await self.page.locator("[data-chat-row]").first.wait_for(timeout=ROWS_TIMEOUT_S * 1000)
        rows_s = round(time.time() - t0, 2)
        sent = await _until(lambda: self.opened(t0) is not None, OPENED_WAIT_S, 0.1)
        quiet = await _until(lambda: not self.inflight and time.monotonic() - self.last_end > NET_QUIET_S,
                             NET_CAP_S, 0.1)
        post = self.opened(t0)
        return {"t0": t0, "rows_s": rows_s, "opened_sent": sent, "net_quiet": quiet,
                "opened_t": post["t"] if post else None,
                "warm": (post.get("answer") or {}).get("warm") if post else None}


async def _tab(ctx, browser, name: str, http: Http) -> Tab:
    from slop.actors import ui

    bctx = await browser.new_context(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]}, service_workers="block")
    ui.track(ctx, bctx)
    host = urlsplit(ctx.app).hostname
    await bctx.add_cookies([{"name": c.name, "value": c.value, "domain": host, "path": "/"} for c in http.c.cookies.jar])
    for js in (ui.INIT_JS, SCOPE_ALL_JS):
        await bctx.add_init_script(js)
    return Tab(name, await bctx.new_page())


# ── the wire ───────────────────────────────────────────────────────────────
def _calls(fake, lo: float, hi: float) -> list[dict]:
    with fake.lock:
        return [dict(c) for c in fake.calls if c["t0"] is not None and lo <= c["t0"] < hi]


def _api(c: dict) -> bool:
    return (c.get("path") or "").startswith("/api2/")


def _kinds(ctx) -> Counter:
    raw, _ = of_call_stats.read(of_call_stats.path(ctx))
    out: Counter = Counter()
    for kind, _key, _aid, _st, n in raw["rows"]:
        out[kind] += n
    return out


def _rows(ctx) -> Counter | None:
    """The counter file as (Caller kind, key, Creator) -> n; None when unreadable."""
    try:
        raw, _ = of_call_stats.read(of_call_stats.path(ctx))
    except Exception:  # noqa: BLE001 — the caller records the gap
        return None
    out: Counter = Counter()
    for kind, key, aid, _st, n in raw["rows"]:
        out[(kind, key, aid)] += n
    return out


def _fed(fake, lo: float) -> dict[str, float]:
    """Per Creator, its first feed read (the warm's first read) since `lo`."""
    out: dict[str, float] = {}
    with fake.lock:
        for c in fake.calls:
            if c["t0"] is not None and c["t0"] >= lo and read_class(c) == "feed":
                out.setdefault(c["account"], c["t0"])
    return out


async def _wedge(ctx, tabs: dict, at: str) -> dict:
    """Background lanes with waiters (the relay's lane stats, owner) and tab reads in flight >= WEDGE_AGE_S."""
    out: dict = {"at": at}
    try:
        r = await ctx.owner.get("/admin/priority-lanes/stats")
        out["stats_status"] = r.status_code
        st = r.json() if r.status_code == 200 else {}
        out["cap_background"] = st.get("cap_background")
        keep = ("bg_in_flight", "loop_waiting_background", "threads_waiting_background", "in_flight",
                "loop_waiting_background_peak", "threads_waiting_background_peak", "wait_s_max")
        out["lanes"] = {a: {k: v.get(k) for k in keep} for a, v in (st.get("accounts") or {}).items()
                        if v.get("loop_waiting_background") or v.get("threads_waiting_background")}
    except Exception as e:  # noqa: BLE001
        out["stats_error"] = f"{type(e).__name__}: {e}"[:300]
    stuck = [s for t in tabs.values() for s in t.stuck(WEDGE_AGE_S)]
    out["stuck_reads"] = stuck[:30]
    out["count"] = len(stuck)
    out["max_age_s"] = max((s["age_s"] for s in stuck), default=None)
    out["creators"] = sorted({s["account"] for s in stuck if s["account"]} | set(out.get("lanes") or {}))
    return out


class Budget:
    """Per phase: the fake-OF calls by route and per Creator, the relay's counter by Caller kind; `of-budget.json`."""

    def __init__(self, ctx, creators: list[str]) -> None:
        self.ctx, self.creators = ctx, creators
        self.phases: dict[str, dict] = {}

    def begin(self) -> dict:
        try:
            kinds = _kinds(self.ctx)
        except Exception as e:  # noqa: BLE001 — no counter file yet: by_caller says why
            kinds = {"__error__": f"{type(e).__name__}: {e}"[:200]}
        return {"lo": time.time(), "kinds": kinds}

    async def end(self, name: str, mark: dict, **extra) -> dict:
        hi = time.time()
        calls = _calls(self.ctx.of_wire, mark["lo"], hi)
        api = [c for c in calls if _api(c)]
        per = Counter(c["account"] for c in api)
        await asyncio.sleep(STATS_FLUSH_S)
        try:
            if "__error__" in mark["kinds"]:
                raise RuntimeError(mark["kinds"]["__error__"])
            k1 = _kinds(self.ctx)
            by_caller = {k: n - mark["kinds"].get(k, 0) for k, n in sorted(k1.items()) if n - mark["kinds"].get(k, 0)}
        except Exception as e:  # noqa: BLE001
            by_caller = None
            self.ctx.metric(f"of_budget_{name}_by_caller_error", f"{type(e).__name__}: {e}"[:300])
        n = len(self.creators)
        out = {"seconds": round(hi - mark["lo"], 1), "total": len(api),
               "per_creator_avg": round(len(api) / n, 2) if n else None,
               "per_creator_max": max((per.get(a, 0) for a in self.creators), default=0),
               "per_creator": {a: per.get(a, 0) for a in self.creators},
               "list_reads": sum(1 for c in api if c["route"] == LIST_ROUTE),
               "thread_reads": sum(1 for c in api if c["route"] == THREAD_ROUTE),
               "by_route": dict(sorted(Counter(f"{c['route']} {c['status']}" for c in calls).items())),
               "by_caller": by_caller, "lo": mark["lo"], "hi": hi, **extra}
        self.put(name, out)
        return out

    def put(self, name: str, out: dict) -> None:
        self.phases[name] = out
        self.ctx.metric(f"of_budget_{name}", out)
        (self.ctx.out / "of-budget.json").write_text(json.dumps(self.phases, indent=2, default=str))


# ── the DOM ────────────────────────────────────────────────────────────────
class Lags:
    """Per tab, when each watched item first shows in a Fan List row (one poll per tab every LAG_POLL_S)."""

    def __init__(self, tabs: list[Tab]) -> None:
        self.tabs = tabs
        self.items: dict[str, dict] = {}
        self.got: dict[str, dict[str, int | None]] = {}
        self.errors: list[str] = []
        self._stop = asyncio.Event()
        self._tasks = [asyncio.create_task(self._poll(t)) for t in tabs]

    def add(self, key: str, marker: str, handle: str | None, t: float) -> None:
        self.items[key] = {"marker": marker, "handle": handle, "t": t}
        self.got[key] = {}

    def done(self, key: str) -> bool:
        return len(self.got.get(key, {})) == len(self.tabs)

    async def _poll(self, tab: Tab) -> None:
        while not self._stop.is_set():
            now = time.time()
            pending = []
            for k, it in list(self.items.items()):
                if tab.name in self.got[k]:
                    continue
                if now - it["t"] > LAG_CAP_S:
                    self.got[k][tab.name] = None
                    continue
                pending.append({"key": k, "marker": it["marker"], "handle": it["handle"]})
            if pending:
                try:
                    found = await tab.page.evaluate(FIND_JS, pending)
                except Exception as e:  # noqa: BLE001 — a navigation mid-poll: the next poll reads again
                    if len(self.errors) < 10:
                        self.errors.append(f"{tab.name}: {type(e).__name__}: {e}"[:200])
                    found = []
                t = time.time()
                for k in found:
                    if tab.name not in self.got[k]:
                        self.got[k][tab.name] = round((t - self.items[k]["t"]) * 1000)
            await asyncio.sleep(LAG_POLL_S)

    async def stop(self) -> None:
        self._stop.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)


class Freshness:
    """`GET /admin/accounts` (owner) every FRESH_EVERY_S while started: each Creator's `freshness` (None: absent)."""

    def __init__(self, ctx, creators: list[str]) -> None:
        self.ctx, self.creators = ctx, set(creators)
        self.samples: list[dict] = []
        self.errors: list[str] = []
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self, phase: str) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._poll(phase))

    async def _poll(self, phase: str) -> None:
        while not self._stop.is_set():
            try:
                r = await self.ctx.owner.get("/admin/accounts")
                if r.status_code == 200:
                    rows = {a["id"]: a.get("freshness") for a in r.json().get("accounts") or []
                            if a.get("id") in self.creators}
                    self.samples.append({"t": time.time(), "phase": phase, "rows": rows})
                elif len(self.errors) < 10:
                    self.errors.append(f"{phase}: status {r.status_code}")
            except Exception as e:  # noqa: BLE001 — the next sample reads again
                if len(self.errors) < 10:
                    self.errors.append(f"{phase}: {type(e).__name__}: {e}"[:200])
            try:
                await asyncio.wait_for(self._stop.wait(), FRESH_EVERY_S)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)


class ChipAge:
    """Tab A's Unread chip text every FRESH_EVERY_S while started (DOM only, 0 OF calls): QUIET_NOT_STALE."""

    def __init__(self, tab: Tab) -> None:
        self.tab = tab
        self.samples: list[dict] = []
        self.errors: list[str] = []
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self, phase: str) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._poll(phase))

    async def _poll(self, phase: str) -> None:
        while not self._stop.is_set():
            try:
                text = await self.tab.page.evaluate(CHIP_TEXT_JS)
            except Exception as e:  # noqa: BLE001 — a missing sample, recorded; the next reads again
                text = None
                if len(self.errors) < 10:
                    self.errors.append(f"{phase}: {type(e).__name__}: {e}"[:200])
            self.samples.append({"t": time.time(), "phase": phase, "text": text})
            try:
                await asyncio.wait_for(self._stop.wait(), FRESH_EVERY_S)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)


async def _row(tab: Tab, handle: str) -> dict:
    try:
        return await tab.page.evaluate(ROW_JS, handle)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}


async def _watch_read(tab: Tab, handle: str, chip0, t0: float, cap_s: float) -> dict:
    """Until `handle`'s row shows no unread dot and the Unread chip drops below `chip0` (each in ms from t0), cap_s."""
    row_ms = chip_ms = None
    last: dict = {}
    while time.time() < t0 + cap_s and (row_ms is None or chip_ms is None):
        last = await _row(tab, handle)
        ms = round((time.time() - t0) * 1000)
        if row_ms is None and last.get("present") and last.get("unread") is False:
            row_ms = ms
        if chip_ms is None and chip0 is not None and last.get("chip") is not None and last["chip"] < chip0:
            chip_ms = ms
        await asyncio.sleep(MARK_POLL_S)
    return {"row_cleared_ms": row_ms, "chip_dropped_ms": chip_ms, "chip_before": chip0, "last": last}


async def _shot(ctx, page, name: str, shots: dict) -> None:
    from slop.actors import ui
    try:
        shots[name] = await ui.shot(ctx, page, name)
    except Exception as e:  # noqa: BLE001
        ctx.metric(f"shot_{name}_error", f"{type(e).__name__}: {e}"[:300])


def _p95(xs: list[float]) -> float | None:
    return sorted(xs)[min(len(xs) - 1, int(len(xs) * 0.95))] if xs else None


async def _roster(http: Http, aid: str) -> dict | None:
    r = await http.get("/admin/accounts/roster-counts")
    return (r.json().get("counts") or {}).get(aid) if r.status_code == 200 else {"status": r.status_code}


# ── the run ────────────────────────────────────────────────────────────────
async def run(ctx) -> None:
    w = ctx.world
    ctx.metric("knobs", "off" if KNOBS_OFF else "on")
    if KNOBS_OFF:
        check = ctx.check

        def knob_off_check(name, ok, **kw):
            if name in KNOB_CHECKS and ok is not None:
                return ctx.skip(name, "SLOP_AM_KNOBS=off: a Knob-only check", would_be=bool(ok))
            return check(name, ok, **kw)
        ctx.check = knob_off_check
    w.data["flat_creators"] = int(w.size["all_models_creators"])
    await ctx.build(PROFILE)
    creators = [c["id"] for c in w.data["creators"]]
    assert len(creators) >= 10, f"{len(creators)} Creators: the phases need 10 (6 DMs, 2 tips, X, Y)"
    n_chats, n_unread = int(w.size["all_models_chats"]), int(w.size["all_models_unread"])
    assert n_chats > TIP_FAN and len(w.data["fans"][creators[0]]) > n_chats, "a listed tip fan and an unlisted fan"
    fake = ctx.of_wire
    wire = all_models_wire.install(fake)
    deep = creators[1:1 + DEEP_K]
    assert all(len(w.data["fans"][a]) >= DEEP_CHATS for a in deep), f"the deep Creators need {DEEP_CHATS} fans"
    for ci, aid in enumerate(creators):
        if aid in deep:
            wire.seed_chats(aid, w.data["fans"][aid][:DEEP_CHATS], n_unread, base_id=CHAT_ID_BASE + ci * 100_000,
                            deep_unread=DEEP_UNREAD)
        else:
            wire.seed_chats(aid, w.data["fans"][aid][:n_chats], n_unread, base_id=CHAT_ID_BASE + ci * 100_000)
    w.data["deep_creators"] = deep
    ctx.metric("world", {"creators": len(creators), "chats_per_creator": n_chats, "unread_per_creator": n_unread,
                         "chatters": len(CHATTERS), "of_page_cap": all_models_wire.PAGE_CAP,
                         "deep_creators": deep, "deep_chats": DEEP_CHATS, "deep_unread_rows": list(DEEP_UNREAD),
                         "chat_messages_count": {a: wire.chat_messages_count(a) for a in creators}})
    if not ctx.ui or not ctx.app:
        for name in (SECOND_OPEN_SHARED, IDLE_BUDGET, DM_NO_LIST_REREAD, DM_ROW_LAG, REFRESHER_FLAT_IN_N,
                     REFRESH_WITHIN_CYCLE, OPEN_AFTER_CYCLE_REUSED, REFRESHER_STOPS_WITHOUT_TABS,
                     READ_ON_OF_CLEARS, FRESH_BADGE_TRUE, QUIET_NOT_STALE):
            ctx.skip(name, "--no-ui: no tab opens Messages Pro")
        return
    everyone = CHATTERS + (LATE,)
    seeded = await chatter_seed.seed(w, ctx.owner, w.user_id, [f"slop-am-{k}" for k in everyone],
                                     account_ids=[list(creators) for _ in everyone])
    https: dict[str, Http] = {}
    try:
        for k, s in zip(everyone, seeded):
            h = Http(ctx.relay, ctx.rec, limits=4)
            https[k] = h
            (await h.post("/chatter/login", json={"username": s["username"], "password": s["password"]})).raise_for_status()
        # Every Creator's Live connection up, as in prod (one real `_reconcile_pumps` pass, before any phase's clock):
        # down, the refresher's window step re-reads each chats window every Cycle (`decide.window_due`).
        t_pumps = time.time()
        (await ctx.owner.post("/__slop/pump-supervise")).raise_for_status()
        up: set = set()
        while time.time() - t_pumps < PUMP_UP_S and len(up) < len(creators):
            await asyncio.sleep(0.25)
            with fake.lock:
                up = {c["account"] for c in fake.ws_connects if c["t"] >= t_pumps}
        ctx.metric("pumps_up", {"connected": len(up), "creators": len(creators),
                                "seconds": round(time.time() - t_pumps, 1)})
        await _flow(ctx, creators, wire, https)
    finally:
        for h in https.values():
            await h.aclose()


async def _flow(ctx, creators: list[str], wire, https: dict[str, Http]) -> None:  # noqa: C901 — the phases in order
    from playwright.async_api import async_playwright

    from slop.actors import ui

    w, fake = ctx.world, ctx.of_wire
    budget = Budget(ctx, creators)
    shots: dict[str, str] = {}
    secs: dict[str, float] = {}
    # Next compiles each route on its first hit: not on A's clock more than it must.
    async with httpx.AsyncClient(timeout=180) as hc:
        try:
            await hc.get(f"{ctx.app}/messages-pro")
        except httpx.HTTPError:
            pass
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=ui.LAUNCH_ARGS)
        try:
            tabs = {k: await _tab(ctx, browser, k, https[k]) for k in CHATTERS}
            A, B, C = tabs["a"], tabs["b"], tabs["c"]

            # 1-2 open_first + open_within_reuse: B opens while A's warm still runs (docstring)
            m = budget.begin()
            r0 = _rows(ctx)
            a_open = await A.open(ctx)
            a_at = a_open["opened_t"] or time.time()
            await _until(lambda: len(_fed(fake, m["lo"])) >= B_AFTER_FED,
                         max(0.0, a_at + B_OPEN_CAP_S - time.time()), 0.1)
            await asyncio.sleep(STATS_FLUSH_S)          # A's own reads so far into the file before B's mark
            rb0, tb0 = _rows(ctx), time.time()
            b_open = await B.open(ctx)
            await asyncio.sleep(STATS_FLUSH_S)
            rb1, tb1 = _rows(ctx), time.time()
            all_fed = await _until(lambda: len(_fed(fake, m["lo"])) >= len(creators),
                                   max(0.0, a_at + WARM_SETTLE_S - time.time()), 0.25)
            await of_call_stats.quiet(fake, WIRE_QUIET_S, WIRE_CAP_S)
            await _shot(ctx, A.page, "open-first-a-settled", shots)
            fed = _fed(fake, m["lo"])
            b_own = _second_open(ctx, creators, fed, a_open, b_open, rb0, rb1, tb0, tb1)
            p1 = await budget.end("open_first", m, tab=a_open, all_fed=all_fed,
                                  fed_span_s=round(max(fed.values()) - min(fed.values()), 1) if fed else None,
                                  b_attributed_total=b_own.get("total"))
            p1["a_own_total"] = p1["total"] - (b_own.get("total") or 0)
            r1 = _rows(ctx)
            if r0 is not None and r1 is not None:
                p1["warm_calls_per_creator"] = {a: sum(n - r0.get(k, 0) for k, n in r1.items()
                                                       if k[0] == WARM_KIND and k[2] == a) for a in creators}
            budget.put("open_first", p1)
            budget.put("open_within_reuse", b_own)

            # 3 open_after_reuse: every warm landed before phase 1 ended
            at = max(a_open["t0"] + C_AFTER_A_OPEN_S, p1["hi"] + WARM_REUSE_S + C_PAST_WARM_S)
            await asyncio.sleep(max(0.0, at - time.time()))
            m = budget.begin()
            c_open = await C.open(ctx)
            c_at = c_open["opened_t"] or time.time()
            all_fed_c = await _until(lambda: len(_fed(fake, m["lo"])) >= len(creators),
                                     max(0.0, c_at + WARM_SETTLE_S - time.time()), 0.25)
            await of_call_stats.quiet(fake, WIRE_QUIET_S, WIRE_CAP_S)
            fed_c = _fed(fake, m["lo"])
            await budget.end("open_after_reuse", m, tab=c_open, all_fed=all_fed_c,
                             fed_span_s=round(max(fed_c.values()) - min(fed_c.values()), 1) if fed_c else None,
                             after_a_open_s=round(c_open["t0"] - a_open["t0"], 1),
                             after_phase1_s=round(c_open["t0"] - p1["hi"], 1))

            # 4 idle
            (await ctx.owner.post("/__slop/fast-poll")).raise_for_status()
            await asyncio.sleep(LOOP_LEAD_S)
            fresh = Freshness(ctx, creators)
            age = ChipAge(A)
            m = budget.begin()
            ri0 = _rows(ctx)
            fresh.start("idle")
            age.start("idle")
            await asyncio.sleep(IDLE_S)
            p4 = await budget.end("idle", m)
            await fresh.stop()
            await age.stop()
            # the refresher's `/users/me` and window reads per Creator per Cycle (phase 2: a window read only on drift)
            p4["refresher_per_cycle"] = refresher.per_cycle(ri0, _rows(ctx), creators, p4["seconds"], 60.0)
            budget.put("idle", p4)
            _idle(ctx, creators, p4)

            # 5 incoming
            await _incoming(ctx, creators, wire, tabs, budget, shots)
            wedge = {"after_incoming": await _wedge(ctx, tabs, "after_incoming")}
            ctx.metric("bg_lane_wedge", wedge)

            # 6-8b: one failing does not stop the next (a raised read_on_of fails its check)
            X, Y = creators[-1], creators[-2]
            fx, fy = w.data["fans"][X][0], w.data["fans"][Y][0]
            for name, step, checks in (
                    ("mark_read", lambda: _mark_read(ctx, wire, tabs, https, budget, shots, X, fx), ()),
                    ("reply", lambda: _reply(ctx, wire, tabs, https, budget, shots, X, fx), ()),
                    ("read_on_of", lambda: _read_on_of(ctx, wire, tabs, https, budget, shots, X, Y, fy),
                     (READ_ON_OF_CLEARS,)),
                    ("fresh_prep", lambda: _fresh_prep(ctx, creators, wire, budget), ())):
                t0 = time.time()
                try:
                    await step()
                except Exception as e:  # noqa: BLE001 — recorded as `<phase>_error`
                    ctx.metric(f"{name}_error", f"{type(e).__name__}: {e}"[:500])
                    for c in checks:
                        ctx.check(c, False, error=f"phase {name} raised: {type(e).__name__}")
                secs[name] = round(time.time() - t0, 1)
            wedge["end"] = await _wedge(ctx, tabs, "end")
            ctx.metric("bg_lane_wedge", wedge)

            # 9-11: tabs close (last, so phases 5-8 keep all three); D opens while A's tab still keeps the refresher
            # reading (before no_tab); a phase that raised fails its checks
            for name, step, checks in (
                    ("idle_one_tab", lambda: _idle_one_tab(ctx, creators, tabs, budget, fresh, age),
                     (REFRESHER_FLAT_IN_N, REFRESH_WITHIN_CYCLE, QUIET_NOT_STALE)),
                    ("open_after_cycle", lambda: _open_after_cycle(ctx, creators, wire, tabs, browser, https, budget,
                                                                   shots),
                     (OPEN_AFTER_CYCLE_REUSED, FRESH_BADGE_TRUE)),
                    ("no_tab", lambda: _no_tab(ctx, tabs, budget), (REFRESHER_STOPS_WITHOUT_TABS,))):
                t0 = time.time()
                try:
                    await step()
                except Exception as e:  # noqa: BLE001 — recorded as `<phase>_error`; its checks run last in it
                    ctx.metric(f"{name}_error", f"{type(e).__name__}: {e}"[:500])
                    for c in checks:
                        ctx.check(c, False, error=f"phase {name} raised: {type(e).__name__}")
                secs[name] = round(time.time() - t0, 1)
            ctx.metric("warm_answers", {k: [{"t": p["t"], "opened": p["body"].get("opened"),
                                             "warm": (p.get("answer") or {}).get("warm")}
                                            for p in t.posts if p["body"].get("opened")] for k, t in tabs.items()})
            ctx.metric("screenshots", shots)
            ctx.metric("phase_seconds", {**{k: v["seconds"] for k, v in budget.phases.items()}, **secs})
        finally:
            await browser.close()


def _second_open(ctx, creators: list[str], fed: dict[str, float], a_open: dict, b_open: dict,
                 rb0: Counter | None, rb1: Counter | None, tb0: float, tb1: float) -> dict:
    """B's verdict and its own budget entry: the counter's rows but the warm's over [tb0, tb1)."""
    t_b = b_open["opened_t"] or b_open["t0"]
    order = sorted(fed.values())
    # A Creator's warm ended before the next one's feed read: the second feed read bounds the oldest finished warm.
    done = [t for t in order[1:] if t < t_b]
    oldest = round(t_b - done[0], 1) if done else None
    detail: dict = {"seconds": round(tb1 - tb0, 1), "b_warm": b_open["warm"], "b_opened_sent": b_open["opened_sent"],
                    "b_after_a_opened_s": round(t_b - a_open["opened_t"], 1) if a_open["opened_t"] else None,
                    "warms_done_at_b": len(done), "oldest_done_warm_age_s": oldest, "tab": b_open,
                    "budget_max_per_creator": SECOND_OPEN_MAX_PER_CREATOR}
    if rb0 is None or rb1 is None:
        detail["counter_error"] = "of_call_stats.json unreadable"
        ctx.check(SECOND_OPEN_SHARED, False, budget=True, **detail)
        return detail
    diff = {k: n - rb0.get(k, 0) for k, n in rb1.items() if n - rb0.get(k, 0) > 0}
    own = {k: n for k, n in diff.items() if k[0] not in (WARM_KIND, refresher.KIND)}
    per = Counter()
    for (_kind, key, aid), n in own.items():
        if key != THREAD_KEY:
            per[aid] += n
    lists = sum(n for (_kind, key, _aid), n in own.items() if key == LIST_ROUTE)
    worst = max((per.get(a, 0) for a in creators), default=0)
    detail.update({"total": sum(own.values()), "list_reads": lists, "max_per_creator": worst,
                   "per_creator": {a: per.get(a, 0) for a in creators},
                   "thread_reads": sum(n for (_kind, key, _aid), n in own.items() if key == THREAD_KEY),
                   "warm_calls_in_window": sum(n for k, n in diff.items() if k[0] == WARM_KIND),
                   "refresher_calls_in_window": sum(n for k, n in diff.items() if k[0] == refresher.KIND)})
    by_caller: Counter = Counter()
    for (kind, _key, _aid), n in own.items():
        by_caller[kind] += n
    detail["by_caller"] = dict(sorted(by_caller.items()))
    if oldest is not None and oldest >= WARM_REUSE_S - REUSE_MARGIN_S:
        ctx.skip(SECOND_OPEN_SHARED, "A's oldest finished warm had aged past REUSE_S at B's open: timing, no verdict",
                 **detail)
        return detail
    ok = b_open["warm"] == "reused" and lists == 0 and worst <= SECOND_OPEN_MAX_PER_CREATOR
    ctx.check(SECOND_OPEN_SHARED, ok, budget=True, **detail)
    return detail


def _idle(ctx, creators: list[str], p4: dict) -> None:
    per_min = {a: round(n / (IDLE_S / 60), 2) for a, n in p4["per_creator"].items()}
    worst = max(per_min.values(), default=0.0)
    total_min = round(p4["total"] / (IDLE_S / 60), 2)
    ctx.metric("idle_calls_per_min", {"total": total_min, "per_creator": per_min, "max_per_creator": worst})
    ctx.check(IDLE_BUDGET, worst <= IDLE_MAX_PER_CREATOR_MIN, budget=True, max_per_creator_min=worst,
              total_per_min=total_min, budget_per_creator_min=IDLE_MAX_PER_CREATOR_MIN,
              by_route=p4["by_route"])


async def _idle_one_tab(ctx, creators: list[str], tabs: dict[str, Tab], budget: Budget, fresh: Freshness,
                        age: ChipAge) -> None:
    """B and C close, A alone for IDLE_S: the refresher's per-Creator cost vs phase 4's, both phases' staleness, and
    tab A's chip age over both (QUIET_NOT_STALE)."""
    for n in ("b", "c"):
        await tabs[n].page.close()
    m = budget.begin()
    fresh.start("idle_one_tab")
    age.start("idle_one_tab")
    await asyncio.sleep(IDLE_S)
    p = await budget.end("idle_one_tab", m, tabs_open=["a"])
    await fresh.stop()
    await age.stop()
    p4, n = budget.phases.get("idle") or {}, len(creators)
    n3 = refresher.per_creator_min(p4.get("by_caller"), n, p4.get("seconds") or 0)
    n1 = refresher.per_creator_min(p.get("by_caller"), n, p["seconds"])
    ctx.metric("idle_refresher_per_creator_min", {"n3": n3, "n1": n1})
    st = refresher.staleness(fresh.samples)
    ctx.metric("refresh_staleness", {**st, "sample_errors": fresh.errors})
    ctx.check(REFRESHER_FLAT_IN_N, refresher.flat_in_n(n3, n1), budget=True, n3=n3, n1=n1,
              n3_calls=(p4.get("by_caller") or {}).get(refresher.KIND),
              n1_calls=(p.get("by_caller") or {}).get(refresher.KIND),
              bounds=[refresher.FLAT_LO, refresher.FLAT_HI], max_gap=refresher.FLAT_GAP)
    ctx.check(REFRESH_WITHIN_CYCLE, refresher.within_cycle(st), budget=True, max_s=st["max_s"], cycle_s=st["cycle_s"],
              excess_s=st["excess_s"], worst=st["worst"], never=st["never"], missing=st["missing"],
              samples=st["samples"], queue_wait_s=refresher.QUEUE_WAIT_S, sample_errors=fresh.errors)
    da = refresher.quiet_stale(age.samples)
    ok = da.pop("ok")
    ctx.metric("data_age", {**da, "sample_errors": age.errors})
    ctx.check(QUIET_NOT_STALE, ok, **da, every_s=FRESH_EVERY_S, sample_errors=age.errors)


async def _open_after_cycle(ctx, creators: list[str], wire, tabs: dict[str, Tab], browser, https: dict[str, Http],
                            budget: Budget, shots: dict) -> None:
    """D opens long past every warm: its warm against the refresher's Last refreshes (OPEN_AFTER_CYCLE_REUSED); the
    same open is the fresh session (FRESH_BADGE_TRUE)."""
    last_warm = max((budget.phases.get(k) or {}).get("hi") or 0.0 for k in ("open_first", "open_after_reuse"))
    await asyncio.sleep(max(0.0, last_warm + LAST_WARM_GAP_S - time.time()))
    D = tabs[LATE] = await _tab(ctx, browser, LATE, https[LATE])
    t_s = time.time()                                   # before the read: the relay's `now` is never earlier
    r = await ctx.owner.get("/admin/accounts")
    rows = {a["id"]: a.get("freshness") for a in (r.json().get("accounts") or []) if a.get("id") in set(creators)} \
        if r.status_code == 200 else {}
    sample = {"t": t_s, "rows": rows}
    await asyncio.sleep(STATS_FLUSH_S)                  # earlier calls into the counter file before D's mark
    m = budget.begin()
    r0 = _rows(ctx)
    first = asyncio.create_task(_first_badge(ctx, D, creators, wire, time.time(), shots))
    try:
        d_open = await D.open(ctx)
    except BaseException:
        first.cancel()
        raise
    await of_call_stats.quiet(ctx.of_wire, WIRE_QUIET_S, WIRE_CAP_S)
    await asyncio.sleep(STATS_FLUSH_S)
    r1 = _rows(ctx)
    posts = [p for p in D.posts if p["body"].get("opened")]
    answers = [(p.get("answer") or {}).get("warm") for p in posts]
    answered = max((p.get("answered_t") or 0.0 for p in posts), default=0.0) or time.time()
    fresh = refresher.fresh_until(sample, answered)
    warmed: dict[str, int] = {}
    own_total = own_by_caller = None
    if r0 is not None and r1 is not None:
        diff = {k: n - r0.get(k, 0) for k, n in r1.items() if n - r0.get(k, 0) > 0}
        for (kind, _key, aid), n in diff.items():
            if kind == WARM_KIND:
                warmed[aid] = warmed.get(aid, 0) + n
        own = {k: n for k, n in diff.items()
               if k[0] not in (WARM_KIND, refresher.KIND) and not k[0].startswith("loop:")}
        own_total = sum(own.values())
        by: Counter = Counter()
        for (kind, _key, _aid), n in own.items():
            by[kind] += n
        own_by_caller = dict(sorted(by.items()))
    v = refresher.open_after_cycle(fresh=fresh, warmed=warmed, answers=answers, own_total=own_total,
                                   n_creators=len(creators))
    p = await budget.end("open_after_cycle", m, tab=d_open, warm_answers=answers,
                         since_last_warm_s=round(d_open["t0"] - last_warm, 1), own_total=own_total,
                         own_by_caller=own_by_caller, warmed_per_creator=warmed, fresh_at_open=fresh,
                         sample_status=r.status_code)
    ctx.check(OPEN_AFTER_CYCLE_REUSED, v.pop("ok"), budget=True, **v, answers=answers, by_caller=p.get("by_caller"),
              total=p["total"], since_last_warm_s=p["since_last_warm_s"],
              counter_error=None if own_total is not None else "of_call_stats.json unreadable")
    await _fresh_session(ctx, creators, wire, D, await first, shots)


async def _first_badge(ctx, tab: Tab, creators: list[str], wire, t_nav: float, shots: dict) -> dict:
    """From just before `tab`'s navigation: the Unread chip's first number, ms after `t_nav`, and the fake's counters
    at that moment (nothing moves them in phase 10); screenshot `fresh-session-trigger` then."""
    while time.time() < t_nav + ROWS_TIMEOUT_S:
        try:
            n = await tab.page.evaluate(CHIP_JS)
        except Exception:  # noqa: BLE001 — about:blank or mid-navigation: the next poll reads again
            n = None
        if n is not None:
            ms = round((time.time() - t_nav) * 1000)
            truth = {a: wire.chat_messages_count(a) for a in creators}
            await _shot(ctx, tab.page, "fresh-session-trigger", shots)
            return {"badge_first": n, "badge_ms": ms, "truth_per_creator": truth}
        await asyncio.sleep(BADGE_POLL_S)
    return {"badge_first": None, "badge_ms": None, "truth_per_creator": {a: wire.chat_messages_count(a)
                                                                         for a in creators}}


async def _totals(ctx, aids: list[str]) -> dict:
    """Owner `/admin/accounts` (Relay memory, 0 OF calls): per Creator `freshness.values.unread_total.n` (None: no
    total held), or `{"status": <code>}` / `{"error": ...}` (never raises: a side-effect record only)."""
    try:
        r = await ctx.owner.get("/admin/accounts")
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    if r.status_code != 200:
        return {"status": r.status_code}
    out: dict = {a: None for a in aids}
    for a in r.json().get("accounts") or []:
        if a.get("id") in out:
            t = ((a.get("freshness") or {}).get("values") or {}).get("unread_total")
            out[a["id"]] = t.get("n") if isinstance(t, dict) else None
    return out


async def _fresh_session(ctx, creators: list[str], wire, D: Tab, first: dict, shots: dict) -> None:
    """FRESH_BADGE_TRUE over D's open (empty storage, every Creator): its first badge vs the fake's whole-inbox
    counters; the accounts answer's totals vs the fake's (side effect, Y's named)."""
    await _shot(ctx, D.page, "fresh-session-settled", shots)
    try:
        settled = await D.page.evaluate(CHIP_JS)
    except Exception as e:  # noqa: BLE001
        settled = f"{type(e).__name__}"
    v = refresher.fresh_badge(first["badge_first"], first["truth_per_creator"])
    totals = await _totals(ctx, creators)
    fake_now = {a: wire.chat_messages_count(a) for a in creators}
    Y = creators[-2]
    out = {**{k: v[k] for k in ("badge_first", "truth", "diff")}, "badge_ms": first["badge_ms"],
           "badge_settled": settled, "truth_per_creator": first["truth_per_creator"], "accounts_n": totals,
           "accounts_vs_fake": sorted(a for a in creators if totals.get(a) != fake_now[a]),
           "y": {"creator": Y, "accounts_n": totals.get(Y), "chat_messages_count": fake_now[Y]},
           "deep_creators": ctx.world.data.get("deep_creators")}
    ctx.metric("fresh_session", out)
    ctx.check(FRESH_BADGE_TRUE, v["ok"], **{k: out[k] for k in ("badge_first", "truth", "diff", "badge_ms",
                                                                 "accounts_vs_fake", "y")})


async def _no_tab(ctx, tabs: dict[str, Tab], budget: Budget) -> None:
    """Every tab still open (A, D) closes: the refresher's calls from NO_TAB_GRACE_S after the close to the end of
    NO_TAB_S."""
    m = budget.begin()
    for t in tabs.values():
        if not t.page.is_closed():
            await t.page.close()
    t_close = time.time()
    await asyncio.sleep(NO_TAB_GRACE_S)
    err = None
    try:
        k0 = _kinds(ctx)
    except Exception as e:  # noqa: BLE001 — recorded, the check fails
        k0, err = None, f"{type(e).__name__}: {e}"[:300]
    await asyncio.sleep(max(0.0, t_close + NO_TAB_S - time.time()))
    p = await budget.end("no_tab", m, grace_s=NO_TAB_GRACE_S)   # its STATS_FLUSH_S wait flushes the window's end
    calls = None
    if k0 is not None:
        try:
            calls = _kinds(ctx).get(refresher.KIND, 0) - k0.get(refresher.KIND, 0)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
    ctx.metric("refresher_calls_no_tab", calls)
    ctx.check(REFRESHER_STOPS_WITHOUT_TABS, calls == 0, calls=calls, counter_error=err, grace_s=NO_TAB_GRACE_S,
              window_s=round(NO_TAB_S - NO_TAB_GRACE_S, 1),
              phase_calls=(p.get("by_caller") or {}).get(refresher.KIND))


async def _incoming(ctx, creators: list[str], wire, tabs: dict[str, Tab], budget: Budget, shots: dict) -> None:
    w, fake = ctx.world, ctx.of_wire
    n_chats = int(w.size["all_models_chats"])
    tag = f"{ctx.seed}{int(time.time()) % 100_000}"
    lags = Lags(list(tabs.values()))
    events: list[dict] = []

    async def dm(aid: str, fan: dict, text: str, kind: str, *, tip: float = 0.0, handle: str | None = None) -> dict:
        mid = next(_IDS)
        fr = fan_dm.frame(mid, fan, text, tip_dollars=tip)
        wire.push_dm(aid, fan, fr["api2_chat_message"])
        t = time.time()
        lags.add(str(mid), text, handle, t)
        r = await fan_dm.inject(ctx.owner, aid, fr)
        ev = {"key": str(mid), "kind": kind, "creator": aid, "fan": fan["id"], "text": text, "t": t,
              "inject_status": r.status_code}
        events.append(ev)
        return ev

    m = budget.begin()
    try:
        plain = []
        for i, aid in enumerate(creators[:PLAIN_DMS]):
            plain.append(await dm(aid, w.data["fans"][aid][DM_FAN], f"slopam dm{i} {tag}", "dm"))
            await asyncio.sleep(DM_EVERY_S)
        await _until(lambda: all(lags.done(e["key"]) for e in plain), LAG_CAP_S + 1, 0.1)
        await asyncio.sleep(DM_TAIL_S)
        t_plain_end = time.time()
        new_fan = w.data["fans"][creators[0]][n_chats]
        later = [await dm(creators[0], new_fan, f"slopam new {tag}", "dm_new_fan", handle=f"@{new_fan['username']}")]
        for j, dollars in enumerate(TIPS):
            await asyncio.sleep(DM_EVERY_S)
            aid = creators[PLAIN_DMS + j]
            fan = w.data["fans"][aid][TIP_FAN]
            later.append(await dm(aid, fan, f"slopam tip{j} {tag}", "tip", tip=dollars, handle=f"@{fan['username']}"))
        await _until(lambda: all(lags.done(e["key"]) for e in later), LAG_CAP_S + 1, 0.1)
    finally:
        await lags.stop()
    await _shot(ctx, tabs["b"].page, "incoming-b-settled", shots)
    hi = time.time()
    for i, ev in enumerate(events):
        nxt = events[i + 1]["t"] if i + 1 < len(events) else hi
        api = [c for c in _calls(ctx.of_wire, ev["t"], nxt) if _api(c)]
        ev["of_calls"] = len(api)
        ev["of_by_route"] = dict(Counter(c["route"] for c in api))
        ev["lag_ms"] = lags.got.get(ev["key"], {})
    lo_dm = events[0]["t"] if events else m["lo"]
    list_calls = [{"t": round(c["t0"] - lo_dm, 2), "account": c["account"], "query": c["query"]}
                  for c in _calls(fake, lo_dm, t_plain_end) if c["route"] == LIST_ROUTE]
    await budget.end("incoming", m, events=events, lag_poll_errors=lags.errors)
    ctx.check(DM_NO_LIST_REREAD, not list_calls, budget=True, list_reads=len(list_calls), calls=list_calls[:20],
              window_s=round(t_plain_end - lo_dm, 1))
    plain_ev = [e for e in events if e["kind"] == "dm"]
    samples = [(e["lag_ms"].get(t) if e["lag_ms"].get(t) is not None else LAG_CAP_S * 1000)
               for e in plain_ev for t in tabs]
    missing = [{"creator": e["creator"], "tab": t} for e in plain_ev for t in tabs if e["lag_ms"].get(t) is None]
    p95 = _p95(samples)
    ctx.metric("dm_row_lag_ms", {"p95": p95, "n": len(samples), "missing": len(missing),
                                 "by_event": {e["kind"] + ":" + e["creator"]: e["lag_ms"] for e in events}})
    ctx.check(DM_ROW_LAG, p95 is not None and p95 <= DM_ROW_LAG_P95_MS, budget=True, p95_ms=p95, n=len(samples), missing=missing, budget_ms=DM_ROW_LAG_P95_MS)


async def _mark_read(ctx, wire, tabs: dict[str, Tab], https: dict[str, Http], budget: Budget, shots: dict,
                     X: str, fx: dict) -> None:
    # A METRIC, not a check: a sibling PR adds the cross-chatter read event and owns that check.
    handle = f"@{fx['username']}"
    others = ("b", "c")
    before = {n: await _row(tabs[n], handle) for n in others}
    try:
        roster_before = await _roster(https["b"], X)
    except Exception as e:  # noqa: BLE001
        roster_before = {"error": f"{type(e).__name__}: {e}"[:200]}
    m = budget.begin()
    await _shot(ctx, tabs["b"].page, "mark-read-b-trigger", shots)
    await tabs["a"].page.locator("[data-chat-row]", has_text=handle).first.click(timeout=15_000)
    t_click = time.time()
    got = await asyncio.gather(*(_watch_read(tabs[n], handle, before[n].get("chip"), t_click, MARK_CAP_S)
                                 for n in others))
    try:
        roster_after = await _roster(https["b"], X)
    except Exception as e:  # noqa: BLE001
        roster_after = {"error": f"{type(e).__name__}: {e}"[:200]}
    await _shot(ctx, tabs["b"].page, "mark-read-b-end", shots)
    wire_marks = [r for r in wire.reads if r["account"] == X and r["fan"] == fx["id"] and r["t"] >= m["lo"]]
    out = {"creator": X, "fan": fx["id"], "before": before, "roster_b_before": roster_before,
           "roster_b_after": roster_after, "of_mark_read": [{**r, "t": round(r["t"] - t_click, 2)} for r in wire_marks],
           **{n: g for n, g in zip(others, got)}}
    ctx.metric("mark_read", out)
    await budget.end("mark_read", m, **out)


async def _reply(ctx, wire, tabs: dict[str, Tab], https: dict[str, Http], budget: Budget, shots: dict, X: str,
                 fx: dict) -> None:
    fake = ctx.of_wire
    marker = f"slopam reply {ctx.seed}{int(time.time()) % 100_000}"

    def sent() -> dict | None:
        with fake.lock:
            return next((dict(s) for s in fake.sends.get(X, ()) if marker in (s.get("text") or "")), None)

    m = budget.begin()
    via = None
    page = tabs["a"].page
    try:
        box = page.get_by_placeholder(COMPOSER).first
        await box.wait_for(timeout=COMPOSER_TIMEOUT_S * 1000)
        await box.click()
        await box.type(marker, delay=20)
        await page.keyboard.press("Enter")
        via = "composer"
    except Exception as e:  # noqa: BLE001 — the HTTP send below
        ctx.metric("reply_composer_error", f"{type(e).__name__}: {e}"[:300])
    t_send = time.time()
    if not (via and await _until(lambda: sent() is not None, SEND_WAIT_S, 0.1)):
        r = await https["a"].post(f"/api/of/v2/chats/{fx['id']}/messages", headers={"X-Account-Id": X},
                                  json={"text": marker})
        via, t_send = f"http {r.status_code}", time.time()
        await _until(lambda: sent() is not None, SEND_WAIT_S, 0.1)
    s = sent()
    if s is not None:
        wire.head_from_send(X, fx["id"], s)
    t0 = s["t"] if s else t_send
    lag = None
    while time.time() < t0 + REPLY_CAP_S:
        try:
            if await tabs["b"].page.evaluate(FIND_JS, [{"key": "r", "marker": marker, "handle": None}]):
                lag = round((time.time() - t0) * 1000)
                break
        except Exception:  # noqa: BLE001 — the next poll reads again
            pass
        await asyncio.sleep(LAG_POLL_S)
    out = {"via": via, "on_wire": s is not None, "b_row_lag_ms": lag, "cap_s": REPLY_CAP_S,
           "send_to_wire_ms": round((s["t"] - t_send) * 1000) if s else None}
    ctx.metric("reply", out)
    await _shot(ctx, tabs["b"].page, "reply-b-end", shots)
    await budget.end("reply", m, **out)


def _leased(tab: Tab, aid: str) -> bool | None:
    """`aid` in the tab's last answered view-lease post's `leased` (None: no answer yet)."""
    got = [p["answer"]["leased"] for p in tab.posts if isinstance(p.get("answer"), dict) and "leased" in p["answer"]]
    return aid in got[-1] if got else None


async def _read_on_of(ctx, wire, tabs: dict[str, Tab], https: dict[str, Http], budget: Budget, shots: dict, X: str,
                      Y: str, fy: dict) -> None:
    """READ_ON_OF_CLEARS: Y's chat read on OF's own site; per tab its row's clear and the Unread chip's drop."""
    handle = f"@{fy['username']}"
    before = {n: await _row(t, handle) for n, t in tabs.items()}
    leased = {n: _leased(t, Y) for n, t in tabs.items()}
    totals_before = await _totals(ctx, [Y])
    m = budget.begin()
    changed = wire.mark_read_out_of_band(Y, fy["id"])
    t0 = time.time()
    count_after = wire.chat_messages_count(Y)
    got = dict(zip(tabs, await asyncio.gather(*(_watch_read(t, handle, before[n].get("chip"), t0, OOB_CAP_S)
                                                for n, t in tabs.items()))))
    cleared = {n: g["row_cleared_ms"] for n, g in got.items()}
    totals_after = await _totals(ctx, [Y])
    out = {"creator": Y, "fan": fy["id"], "was_unread_on_of": changed, "before": before, "y_leased": leased,
           "cleared_ms": cleared, "chip_dropped_ms": {n: g["chip_dropped_ms"] for n, g in got.items()},
           "any_cleared_ms": min((v for v in cleared.values() if v is not None), default=None),
           "last": {n: g["last"] for n, g in got.items()},
           "y_total": {"accounts_before": totals_before.get(Y), "accounts_after": totals_after.get(Y),
                       "chat_messages_count_after": count_after}}
    ctx.metric("read_on_of", out)
    await _shot(ctx, tabs["b"].page, "read-on-of-b-end", shots)
    try:
        parity = await _parity(ctx, https["b"], wire, [X, Y])
        ctx.metric("unread_parity", parity)
        (ctx.out / "unread-parity.json").write_text(json.dumps(parity, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        ctx.metric("unread_parity_error", f"{type(e).__name__}: {e}"[:300])
    await budget.end("read_on_of", m, **out)
    v = refresher.clears_within(got, CLEAR_MAX_MS)        # last: a raise before it fails the check once (_flow)
    ctx.check(READ_ON_OF_CLEARS, v.pop("ok"), **v, cleared_ms=out["cleared_ms"], chip_dropped_ms=out["chip_dropped_ms"],
              y_total=out["y_total"], y_leased=leased)


async def _fresh_prep(ctx, creators: list[str], wire, budget: Budget) -> None:
    """One page-0 unread chat per deep Creator read on OF's own site, then FRESH_PREP_S: the drift's `/users/me` and
    window read land here, not in phase 9's idle count."""
    deep = ctx.world.data["deep_creators"]
    fans = {a: ctx.world.data["fans"][a][DEEP_READ_FAN] for a in deep}
    m = budget.begin()
    r0 = _rows(ctx)
    before = await _totals(ctx, deep)
    reads = [{"creator": a, "fan": f["id"], "was_unread": wire.mark_read_out_of_band(a, f["id"])}
             for a, f in fans.items()]
    await asyncio.sleep(FRESH_PREP_S)
    after = await _totals(ctx, deep)
    p = await budget.end("fresh_prep", m, reads=reads)
    r1 = _rows(ctx)
    lists = None if r0 is None or r1 is None else {
        a: r1.get((refresher.KIND, refresher.LIST_KEY, a), 0) - r0.get((refresher.KIND, refresher.LIST_KEY, a), 0)
        for a in deep}
    ctx.metric("fresh_prep", {"reads": reads, "accounts_n_before": before, "accounts_n_after": after,
                              "chat_messages_count": {a: wire.chat_messages_count(a) for a in deep},
                              "refresher_list_calls": lists, "seconds": p["seconds"]})


async def _parity(ctx, http: Http, wire, aids: list[str]) -> dict:
    """As B: the All list's page 0 (the inbox bundle, else the chats route) and the `filter=unread` list per Creator."""
    all_rows: dict[str, list[dict] | None] = {a: None for a in aids}
    src = "bundle"
    r = await http.get(f"/admin/screens/inbox?cursor=0&accounts={','.join(aids)}")
    if r.status_code == 200:
        for ans in r.json().get("answers") or []:
            if ans.get("read") == "chats" and ans.get("accountId") in all_rows and isinstance(ans.get("body"), dict):
                all_rows[ans["accountId"]] = ans["body"].get("list") or []
    out: dict = {"all_source": {}, "bundle_status": r.status_code}
    for a in aids:
        if all_rows[a] is None:
            src = "chats"
            rr = await http.get("/api/of/v2/chats?limit=25&offset=0&order=recent", headers={"X-Account-Id": a})
            all_rows[a] = (rr.json().get("list") or []) if rr.status_code == 200 else []
        out["all_source"][a] = src
        ru = await http.get("/api/of/v2/chats?limit=25&offset=0&order=recent&filter=unread",
                            headers={"X-Account-Id": a})
        un = (ru.json().get("list") or []) if ru.status_code == 200 else []
        all_unread = {int(x["withUser"]["id"]) for x in all_rows[a] if all_models_wire.unread(x)}
        unread_ids = {int(x["withUser"]["id"]) for x in un}
        with ctx.of_wire.lock:
            truth = {int(x["withUser"]["id"]) for x in ctx.of_wire.chats.get(a, ())[:25] if all_models_wire.unread(x)}
        out[a] = {"unread_status": ru.status_code, "all_unread": len(all_unread), "unread_list": len(unread_ids),
                  "of_unread_page0": len(truth),
                  "unread_in_all_not_in_unread_list": sorted(all_unread - unread_ids),
                  "in_unread_list_not_unread_in_all": sorted(unread_ids - all_unread),
                  "all_vs_of": sorted(all_unread ^ truth), "unread_list_vs_of": sorted(unread_ids ^ truth)}
    out["mismatches"] = sum(len(out[a]["unread_in_all_not_in_unread_list"]) +
                            len(out[a]["in_unread_list_not_unread_in_all"]) for a in aids)
    return out
