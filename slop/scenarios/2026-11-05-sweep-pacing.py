"""Background OnlyFans list walks, paced (service/of_pacing.py): the hourly link prewarm pass
(link_prewarm.prewarm_all: tracking links, trials, promotions), the lifecycle roster crawl
(subscribers), four passes of the 900 s ledger supervisor (transaction_ingest.supervisor_cycle,
payouts transactions: the first fill (backfill), the full 7-day walk of a period turned over (the
backfilled Creators' last_full_at backdated one period by SQL before it), then recent 24 h walks) and a Growth page's claimer refresh (link_metrics.maybe_refresh) run at
once, against OF's own rate limit, while `--users` chatters work half the Creators and their Fan
List fills names in the background.

World: `agency_inbox` (an Agency, its Creators, fans, threads) with a captured session per
Creator (seed/of_sessions.py), so the relay's REAL OFClient talks to lib/of_wire.py (`OF_WIRE`).
OF's side per Creator (lib/sweep_pacing_wire.py, set here): `--set promos=` promotions (350 small,
1,150 medium: the prewarm's 12-page cap is 1,200), `--set subscribers=` active subscribers (500 /
2,400 / 5,000, OF's 50 a page: 48 pages at medium) and `--set transactions=` ledger rows of the
last 6 days (400 / 1,000 / 2,000; the backfill's marker walk reads them all, past OF's offset cap of
TX_CAP = 600). More Creators hold only a ledger, at every scale, outside every other check but
pages_spaced: DEEP, cold but its failure streak at 2 (one more counted failure pauses it), DEEP_ROWS rows over 80 days, every 3 in the same second so they span pages,
1 in 7 pending (`loading`), DEEP_BELOW rows older than its 90-day window; OF answers its marker page
number DEEP_FAIL_AFTER + 1 429 twice. REACT, recorded complete (SQL: scan row, REACT_HELD rows and
their fans' lifetime, REACT_FLIPS of them old and pending that OF now says done, one 2 h old too), then
deactivated and reactivated through the real endpoint with its gap backdated to REACT_GAP_D days, its
ledger REACT_ROWS rows over that gap + REACT_BELOW older than it; OF answers its marker page number
REACT_BLANK_AFTER + 1 empty, hasMore false. BLANK, recorded complete on rows older than its gap,
reactivated the same way after BLANK_GAP_D days; OF answers its first page blank, then BLANK_ROWS rows over the gap. GAP, a walk
caught mid-way (SQL: scan row and GAP_HELD rows, the rows of its two pages) by GAP_ROWS rows landing above its
top in 14 days off, past OF's offset cap, GAP_BELOW still to walk. CROWD_N Creators of CROWD_ROWS rows,
cold, on ONE OF bucket (`share`: a proxy's, a guess). Proxies as on AE (lib/sweep_pacing_proxy.py `bind`,
through the product's own routes, before any walk): CROWD on one fake proxy (its shared bucket's IP), every
other Creator PER_PROXY (5) a proxy, PX direct until its stage (ledger pages are paced per bound proxy: all
direct, they would share the host's one slot). Half the Creators are busy (chatters + their Fan List), half
idle. On every idle Creator OF answers one page 429 once whatever the pace: promotions offset 100
("Please allow 2 seconds"), subscribers offset 100 ("... allow 1 seconds"), transactions offset
100 ("Too many requests": no wait named); on the first busy Creator its first background
/users/list ("... allow 1 seconds"). The last idle Creator (TERMINAL) holds a roster mirror from a
crawl 2 h ago (TERMINAL_SNAPSHOT subscriber_snapshot rows, by SQL) and OF answers its subscribers
offset 100 429 TWICE (the first send and the retry). The last busy Creator (GROWTH) has GROWTH_PROMOS
promotions (3 pages: its Promotions page reads them unpaced, as a person's), the first
GROWTH_CLAIMED of them with GROWTH_CLAIMS claimers each (5 claimer pages each: 25 pages, so even
unpaced the refresh outlasts OF's bucket and meets the other walks).
Every profile Creator has its promotion List on (promo_list_settings, SQL), so the prewarm, which
under LINK_PREWARM_SCOPE=list_sync (the product default) walks only Creators with a List, walks
them all. The first idle Creator (LISTED) has one promotion with LISTED_CLAIMS claimers; OF gains
LISTED_CLAIMS more between the passes. DISPLAY, one more Creator (an empty ledger), has Growth links
and no List: DISPLAY_PROMOS promotions, the first DISPLAY_CLAIMED with DISPLAY_CLAIMS claimers each,
one OF tracking link with subscribers and a Source on it (link_meta, no list_id). The ledger-only
Creators, CAP and PX hold no List either.

Flow: prewarm_all's spread is compressed to 0 (`POST /__slop/sweep-pacing/knobs`; prod 30 min);
of_pacing.USER_WINDOW_S is the product's 10 s. `--users` chatters (actors/chatter.py) read and answer the busy Creators' threads; every reply is a real
`POST /api/of/v2/chats/{fan}/messages`, a person's OF request. The owner opens GROWTH's Promotions
page (`GET /admin/promotions`: its claimer refresh starts in the background) and, from then on,
GROWTH's tracking-link earnings (`GET /admin/of-tracking-links/earnings`, the Growth page's read)
EARNINGS_N times EARNINGS_EVERY_S apart. GROWTH_SETTLE_S later (OF's bucket refills after the
page's 3 reads), each busy Creator's Fan List fires BURSTS bursts, BURST_EVERY_S apart, of BURST_N
background name lookups at once (`GET /api/of/v2/users/list?view=x`, `X-Priority: background`, as
useChatList / useSubscribeDateFill do) and, from 3 s into each, USER_AT_S lookups of a person's own
(`view=m`, no header: useOFUser); a prewarm pass, every Creator's roster crawl and TX_CYCLES
supervisor passes start (`POST /__slop/sweep-pacing/run`: the production functions); the scenario
waits for all of them, stops the people, waits USER_WINDOW_S (+ IDLE_SLACK_S) and runs the next
prewarm pass.

Checks (names in lib/sweep_pacing_faults.py):
  pages_spaced           per Creator, every background walk GET OF saw (campaigns, trials,
                         promotions, subscribers incl. claimers, transactions), across all its
                         jobs, left >= PAGE_GAP_S after the one before (SPACE_SLACK_S for the wire).
                         GROWTH's Promotions page reads are a person's (not counted).
  retry_once_per_429     every first 429 OF gave a background request (walk page or name-fill
                         lookup) was followed by exactly one request for the SAME page (same
                         query) within RETRY_WINDOW_S, no sooner than OF asked; a retry's 429 by none; every injected
                         429 fired.
  no_429_on_user_reads   zero 429s on a person's reads: every view=m lookup and every Promotions
                         page read reached OF and got 200, and the relay answered each 200.
  prewarm_skips_busy_creators  pass 1 logged one skip per busy Creator (a person's read < 10 s
                         ago) and none for an idle one, sent no prewarm GET for a busy Creator and
                         walked every idle one; pass 2 (everyone idle) skipped none and walked every
                         busy one.
  prewarm_scope          in both prewarm passes no Creator without a List (DISPLAY, the ledger-only
                         ones, PX, CAP) had a Growth list read (campaigns, trials, promotions) or a
                         claimer page sent to OF, and the relay logged DISPLAY's link_prewarm_skip in
                         each; LISTED's promotion went into the List once in each pass (OF's add-to-list,
                         pass 1 at LISTED_CLAIMS, pass 2 after the gain), link_meta's list_added_count
                         at the gain. List adds keep the background cadence; display-only reads go.
  growth_refresh_walked  the Promotions page answered refreshing; OF saw every claimer page of
                         GROWTH's claimed promotions; link_claimers holds GROWTH_CLAIMS rows each.
  growth_route_not_blocked  every earnings read answered 200 within EARNINGS_MAX_MS, at
                         least one while GROWTH's claimer walk was on OF (between its first and
                         last claimer GET): no walk holds the lock that read takes.
  terminal_429_keeps_mirror  TERMINAL's subscribers offset 100 was sent exactly twice, both 429;
                         its roster crawl failed (an error, never an empty roster); its
                         subscriber_snapshot rows and their newest seen_at are unchanged.
  walk_counts_match      every run ended (TERMINAL's roster crawl with its 429); per Creator,
                         link_meta promo rows == OF's promotions, subscriber_snapshot rows == OF's
                         subscribers (TERMINAL: its mirror), new transactions rows == every ledger
                         row OF holds, past TX_CAP at medium (a failed page never looks empty).
  no_5xx                 no 5xx or transport error on any call, apart from a name-fill lookup
                         whose OF answer stayed 429 after its retry (retry_once_per_429 owns it).
  user_read_p95          the person's lookup p95 <= USER_READ_P95_MS (budget).
  background_lookup_p95  the name fill's lookup p95 <= BACKGROUND_LOOKUP_P95_MS (budget): it is
                         user-triggered, never paced (paced, it measured 11-13 s).
  tx_calls_budget        per Creator whose full walk ended (ingest_tx_scan_end mode=refresh) before
                         the last pass (at least one must), its payouts `transactions` GETs in its recent walk (pass mode
                         from the relay's ingest_tx_scan_start line) x 3600 / the relay's
                         _TICK_INTERVAL_S + those of its full 7-day walk x 3600 / _FULL_EVERY_S
                         (`tick_interval_s`, `full_every_s` in /__slop/sweep-pacing/runs; 429 retries
                         included; the backfill pass is a one-off, not counted) <= (ceil(rows on or
                         after the recent walk's startDate, the day before the last TX_RECENT_H /
                         TX_PAGE) x 3600 / TX_TICK_S + ceil(min(rows, TX_CAP) / TX_PAGE) x 3600 /
                         TX_FULL_S) x TX_HEADROOM. INFERRED, not a measurement of the loop:
                         pages per walk (measured) x the walks an hour the constants imply; the
                         passes run back to back here, so the real sleep and the 2 h period are
                         never observed, and tx-cadence-300 sets that same module var. A regression
                         guard on pages-per-walk and the constants. 900 / 7200 s passes; 300 s (3x
                         the recent walks) and OF ignoring `startDate` (a recent walk = a full one)
                         do not.
                         walk_counts_match's ledger half is the "earnings unchanged" invariant.
  tx_recent_catches_new_row  between the full pass and the recent one OF gains, per Creator, a row
                         10 h old and one 3 days old (NEW_ROW_AGO); every Creator whose full walk
                         ended walked recent in the last pass and landed the 10 h row (the 3-day
                         one is before its startDate: the next full walk's, not required), and the
                         relay never logged ingest_tx_recent_walk_empty. The added rows are left
                         out of walk_counts_match.
  tx_recent_window_kept  every Creator whose full walk ended before the last pass had a recent walk
                         (at least one such Creator) and the relay never logged
                         ingest_tx_recent_window_ignored (its guard: a recent page held a row more
                         than a day older than its startDate, i.e. OF ignored it).
  tx_backfill_nothing_dropped  DEEP's and REACT's held provider ids == OF's rows on or after the
                         startDate of their floor: every row, past OF's offset cap, the pending ones,
                         the row added mid-walk; none below the window. Both recorded complete.
  tx_backfill_exactly_once  each provider id once, SUM(amount_cents) == OF's sum, and rows of each kind as OF's.
  tx_backfill_lifetime_once  SUM(fans.lifetime_spend_cents) per Creator == OF's sum: pages re-read
                         across ticks and ties, and REACT's held rows, add nothing.
  tx_backfill_partial_not_complete  after pass 1: DEEP (twice-429'd page) not complete, its cursor
                         saved, the 429 in last_error, its streak still 2 and not paused, a real walk
                         resumes; REACT (blank page) and BLANK (blank FIRST page, OF's no-filter
                         limit=1 names a row in the window) not complete, status backfill_stalled, the
                         stop in last_error. After pass 2: DEEP refreshed (a full walk due), cursor
                         kept. After pass 3: DEEP (page cap) not complete, cursor lower. At the
                         end all complete, none paused. Reactivation reopened REACT and BLANK.
  tx_backfill_calls_bounded  per pass, DEEP's and REACT's walk pages <= the tick cap, recent-read
                         pages <= its cap, every walk page offset 0, date-only startDate, no
                         start / end anywhere; DEEP's walk pages in all <= DEEP_ROWS / 97 + 1 per pass;
                         DEEP's disputes calls == 2 (its full walk's, its complete walk's: nothing took
                         a row out of a reversal).
  tx_backfill_fresh_rows_land  a row 1 h old OF gains after pass 2 is held after pass 3, read before
                         that pass's first marker page, and the cursor still only went down.
  tx_backfill_no_flip_burst  REACT's REACT_FLIPS old flips are cleared in the DB; of the SSE
                         stream's transaction_recorded for REACT (the dispute's aside) only the
                         2 h old flip arrived.
  tx_backfill_dispute_stands  REACT's row REACT_DISPUTED, seeded as the disputes path leaves it
                         (chargedback, off lifetime), which OF's ledger still calls `done` and its
                         disputes list `undo` (a disagreement never measured, the worst case):
                         chargedback after pass 1's stopped tick (it took the row out of a reversal, so
                         it polled) and at the end, its amount off tx_backfill_lifetime_once's sum once, the
                         poll's flip announced once; a recent pass sends no disputes call
                         (tx_calls_budget counts ledger calls only).
  tx_backfill_gap_rewalked  GAP's refresh (a fresh process: pass 1) left newest_seen and the cursor,
                         its resumed read (pass 2) logged the cap, read FRESH_PAGES pages, its walk
                         started from the top, and it completed (held rows: tx_backfill_nothing_dropped).
  tx_backfill_shared_bucket  CROWD on one bucket: every Creator complete, no terminal 429 on its backfill walks (a
                         retry's 429 ends a tick; full walks' are reported as refresh_terminal_429s), each
                         Creator's ledger GETs (200s) and disputes calls <= what its rows imply.
  stock "p95 within 1.25x (+50ms) of the last green run": both lookups (P95_VS_LAST).
  tx_restart_keeps_full_schedule  then (lib/sweep_pacing_watermark.py, its docstring): backfilled
                         Creators' persisted watermarks seeded mixed on their real crc32 phases, the
                         relay SIGKILLed and restarted on the same DB: only the due ones walk full.
  tx_failed_full_consumes_period  one Creator's full walk failed on a terminal second 429 (injected
                         twice): error kept, the period spent (same-period ticks recent), the next
                         period's tick walks full again.
  promo_cap_once         then (lib/sweep_pacing_promo_cap.py, its docstring): CAP, 1,300 promotions past
                         the 12-page cap, no promotion List, a finished mirror past the cap: its owner's
                         Promotions page (`GET /admin/promotions`) read 1 reads the cap, reads 2 and 3
                         each fewer pages (of_promos' memo), every read all 1,201 rows, the live one active.
  tx_proxy_pages_spaced  last (lib/sweep_pacing_proxy.py, its docstring): PX_N Creators bound 2 a proxy
                         through the real pool assign, simultaneous full walks, an ADR-0030 move, again:
                         per egress at OF every ledger GET >= PAGE_GAP_S apart, each Creator through its
                         bound proxy, proxies independent, ledger totals == OF's and unchanged.
Pacing covers OF's API list pages only: CDN, media and /img fetches are not walks here.
Measured: metric `tx_supervisor`, each supervisor pass's walk modes, wall time and pages per Creator
(the first fill, the full walk, a recent one); tx_calls_budget checks the pages per hour they imply.

Bypasses (declared):
  transaction_ingest.full_phase_s is pinned (`/knobs`): no Creator crosses a full-walk period mid-run
  (the watermark stages unpin it). Before pass 2 the backfilled Creators' last_full_at is backdated one
  period by SQL (a period turned over, not waited). The watermark and proxy stages' bypasses: their docstrings.
  - OF's rate limit is a GUESS (lib/sweep_pacing_wire.py), not OF's measured policy: a token bucket
    per Creator across its four list routes (10 deep, 2 a second); an empty one answers 429 with OF's measured body ("Too many
    requests. Please allow 1 seconds"); its injected 429s too. Latency is lib/of_wire.py's 50 ms.
    The people's load is sized to that guess: a person's lookups + the name fill (~0.9/s per busy
    Creator) beside a paced walk (~0.9/s) stay under the refill. of_wire.py is not edited:
    the extension swaps its server's handler class for a subclass (harness side).
  - The jobs' cadences (hourly prewarm_all with its spread, the 30 min lifecycle sweep, the 900 s
    ledger supervisor's sleep and its 2 h full-walk period) are `POST /__slop/sweep-pacing/run` (lib/sweep_pacing_relay.py),
    which runs the production functions in fresh contexts (no request around them); the spread is
    compressed (above). USER_WINDOW_S, PAGE_GAP_S, JITTER_S and the 429 retry are the product's.
  - DEEP and REACT are seeded by SQL (creators.extra, fans.seed, REACT's rows, scan row), REACT's
    `account_health.deactivated_at` is backdated by SQL between its real off and on (the gap's 30 days
    are not waited). Admin /run resumes REACT after pass 1 through the real endpoint. OF's limit is per
    Creator here (CROWD's shared bucket aside): the Creators sharing a fake proxy share no OF bucket.
  - The promotion Lists and DISPLAY's link_meta row are SQL (the rows PUT /admin/promo-list and the
    Edit dialog's save write; the save's own first add is not run). OF's add-to-list is
    lib/sweep_pacing_wire.py's, answering the claimers the link has (OF answers the new ones).
  - The tracking links and trials are of_wire's empty ones (DISPLAY's one tracking link aside); only
    GROWTH's, LISTED's and DISPLAY's claimed promotions have claimers. A GROWTH /campaigns GET OF saw during an earnings read is that read's (a person's),
    not a walk's. Chatters reach the relay directly (no Next proxy); the Fan List's lookups are httpx
    calls, not a browser.

Break-it-once (verified, not assumed): sweep-unpaced (the scenario's FAULT: no gap, retry kept)
turns pages_spaced and walk_counts_match red: unpaced, a Creator's walks drain its bucket within a
second, the single retry meets a second 429 and the roster crawls fail. A person's lookup can also
meet GROWTH's empty bucket (no_429_on_user_reads, no_5xx), and GROWTH's refresh can lose the race
for the retry (growth_refresh_walked): noise, not targets (red in some runs only, measured). A Creator
whose backfill the 429s failed walks its full pass one pass late and is left out of the tx checks.
sweep-no-429-retry
(`--fault=`: gap kept, no retry) turns retry_once_per_429, terminal_429_keeps_mirror and
walk_counts_match red. The lookups' p95s and growth_route_not_blocked stay. tx-cadence-300
(`--fault=`: the supervisor's interval 300 s, pages unchanged) turns tx_calls_budget red only.
tx-recent-window-ignored (`--fault=`, harness side: OF ignores startDate) turns tx_calls_budget
and tx_recent_window_kept red; every row still lands. tx-recent-startdate-iso (`--fault=`, harness
side: the startDate reaches OF as ISO, answered empty) turns tx_recent_catches_new_row red.
tx-backfill-* (`--fault=`, lib/sweep_pacing_faults.py): the walk's own, each to its tx_backfill_ checks.
tx-full-watermark-forgotten / tx-failed-full-not-stamped / tx-full-failure-hidden (`--fault=`):
tx_restart_keeps_full_schedule / tx_failed_full_consumes_period (both of the latter).
tx-proxy-pacing-bypassed (`--fault=`): tx_proxy_pages_spaced.
promo-memo-cleared-on-need-ids (`--fault=`): promo_cap_once.
prewarm-all-accounts (`--fault=`: LINK_PREWARM_SCOPE=all, today's pass): prewarm_scope.
"""
from __future__ import annotations

import asyncio
import itertools
import re
import sys
import time
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slop.actors import chatter
from slop.actors.manager import SseListener
from slop.lib.client import Recorder
from slop.lib.procmon import pct
from slop.lib import sweep_pacing_backfill
from slop.lib.sweep_pacing_evidence import TX_START as _TX_START, held, scan_one, tx_status as _tx_status
from slop.lib.sweep_pacing_faults import (BG_P95, COUNTS, GROWTH, GROWTH_ROUTE, NO_429_USER, NO_5XX,
                                          PAGES_SPACED, PREWARM_SCOPE, RETRY_ONCE, SKIPS, STARTDATE_ISO, TERMINAL, TX_BUDGET,
                                          TX_NEW_ROW, TX_WINDOW, USER_P95, WINDOW_IGNORED)
from slop.lib import sweep_pacing_promo_cap, sweep_pacing_proxy, sweep_pacing_watermark
from slop.lib.sweep_pacing_ledger import (CROWD_N, CROWD_ROWS, DEEP_BELOW, DEEP_FAIL_AFTER, DEEP_ROWS, LEDGER_ID,
                                          LEDGER_ID_STRIDE, REACT_BELOW, REACT_BLANK_AFTER, REACT_DISPUTED,
                                          REACT_FLIP_FROM, REACT_FLIPS, REACT_GAP_D, REACT_HELD, REACT_ROWS, TX_CYCLES,
                                          iso as _iso, pages as _pages, sale as _sale, tx_row as _tx_row)
from slop.lib.sweep_pacing_wire import TOO_MANY, TX_CAP, SweepWire
from slop.seed import creators, fans, of_sessions, ts

sys.path.append(str(Path(__file__).resolve().parents[2] / "service"))   # a stdlib leaf: the pace itself
from of_pacing import JITTER_S, PAGE_GAP_S  # noqa: E402

PROFILE = "agency_inbox"
UI = False
OF_WIRE = True
FAULT = "sweep-unpaced"
KNOBS = {"PREWARM_SPREAD_S": 0.0}
IDLE_SLACK_S = 1.0           # past USER_WINDOW_S before pass 2: every Creator idle
SPACE_SLACK_S = 0.1          # a GET's send-to-arrival time varies by a few ms under load
RETRY_SLACK_S = 0.1
RETRY_WINDOW_S = 15.0        # a retry leaves within OF's wait (<= 10 s) + a pacer turn; later = another walk
BURSTS, BURST_N, BURST_EVERY_S = 6, 8, 15.0
USER_AT_S = tuple(round(3.0 + 1.6 * k, 1) for k in range(5))   # a person's lookups, into each burst
GROWTH_SETTLE_S = 2.5        # after GROWTH's Promotions page (3 reads), before the first burst (8)
EARNINGS_N, EARNINGS_EVERY_S, EARNINGS_MAX_MS = 24, 0.5, 2_000
NEW_ROW_AGO = (timedelta(hours=10), timedelta(days=3))   # rows OF gains before the recent pass: caught / not needed
TX_TICK_S, TX_FULL_S, TX_RECENT_H = 900, 7200, 24   # the cadence the budget is sized for
TX_HEADROOM = 1.5            # its slack over the pages those imply
LEDGER_FANS = 40
NEW_ROWS_STRIDE = 10
BLANK_ROWS, BLANK_OLD, BLANK_GAP_D = 900, 20, 6   # past the full walk's 600 in under its 7 days: only the walk lands them
GAP_ROWS, GAP_HELD, GAP_BELOW = 1_540, 200, 300   # 110 rows a day, measured shape of the review's case
ADMIN_RUN_TIMEOUT_S = 120
GROWTH_PROMOS, GROWTH_CLAIMED, GROWTH_CLAIMS = 250, 5, 100
CLAIMER_PAGE = 20            # link_metrics._PAGE: claimers OF answers a page
LISTED_CLAIMS = 20           # LISTED's promotion: one claimer page; as many again before pass 2
DISPLAY_PROMOS, DISPLAY_CLAIMED, DISPLAY_CLAIMS = 3, 2, 20
PROMO_LIST_ID = "910000001"  # the profile Creators' promotion List (an OF custom list's number)
TERMINAL_SNAPSHOT = 120
RUN_TIMEOUT_S = 900
USER_READ_P95_MS = 1_000     # measured 66-68 ms small / 20 users, 99-635 ms medium / 200 users
BACKGROUND_LOOKUP_P95_MS = 3_000   # one OF wait (1 s) + the retry; paced at the route it was 11-13 s
P95_VS_LAST = (1.25, 50)
P95_VS_LAST_MIN_N = 10
# A walk OF cut short with a 429 logs its failure with the traceback.
EXPECTED_TRACEBACKS = tuple((m, '"code": 429') for m in (
    "OF fetch failed", "ingest_tx_scan failed", "ingest_tx_scan_failed", "ingest_tx_backfill failed",
    "link_metrics refresh failed", "link_prewarm failed"))
TX_COLS = ("account_id, fan_id, kind, message_id, amount_cents, currency, occurred_at, ingested_at, "
           "provider_transaction_id, status, net_cents, fee_cents, vat_cents, source, description")
WALK_ROUTES = ("campaigns", "trials", "promotions", "subscribers", "transactions")
PREWARM_ROUTES = ("campaigns", "trials", "promotions")
_SKIP = re.compile(r"bg_walk_skip account=(\S+) kind=link_prewarm")
_NO_LIST = re.compile(r"link_prewarm_skip account=(\S+) reason=no_list_sync")
_TX_FULL_OK = re.compile(r"ingest_tx_scan_end account=(\S+) mode=refresh ")
_TX_IGNORED = "ingest_tx_recent_window_ignored"
_TX_EMPTY = "ingest_tx_recent_walk_empty"
_ALLOW = re.compile(r"allow\s+(\d+(?:\.\d+)?)\s*sec", re.I)


def _asked(text: str | None) -> float:
    m = _ALLOW.search(text or "")
    return float(m.group(1)) if m else 1.0


def _seed_of(sw: SweepWire, w, aids: list[str], n_promo: dict[str, int], n_sub: int, n_tx: int,
             growth: str) -> None:
    """OF's side, deterministic from the world's seed."""
    rng = w.rng("scenario:sweep-pacing:of")
    fans = w.data["fans"]
    for i, a in enumerate(aids):
        base = 10_000_000_000 + i * 1_000_000
        n = n_promo[a]
        sw.promos[a] = [{"id": base + k, "message": f"slop promo {k}", "price": 4.99, "type": "all",
                         "claimsCount": GROWTH_CLAIMS if a == growth and k < GROWTH_CLAIMED else 0,
                         "subscribeCounts": 10, "subscribeDays": 0,
                         "createdAt": _iso(w.now - timedelta(days=n - k)), "finishedAt": None,
                         "isFinished": True, "canClaim": False} for k in range(n)]
        ids = [f["id"] for f in fans[a]]
        ids += [base + 500_000 + k for k in range(max(0, n_sub - len(ids)))]
        sw.subs[a] = [{"id": fid, "name": f"Fan {fid}", "username": f"u{fid}",
                       "subscribedOnData": {"status": "Active" if rng.random() < 0.7 else "Cancelled",
                                            "subscribeAt": _iso(w.now - timedelta(days=rng.randint(1, 300))),
                                            "expiredAt": _iso(w.now + timedelta(days=rng.randint(1, 30))),
                                            "renewedAt": None}} for fid in ids[:n_sub]]
        if a == growth:
            for k in range(GROWTH_CLAIMED):
                sw.claims[(a, base + k)] = [
                    {"id": base + 700_000 + k * 1_000 + j, "name": f"Claimer {j}", "username": f"c{k}_{j}",
                     "subscribedOnData": {"subscribeAt": _iso(w.now - timedelta(days=j + 1))}}
                    for j in range(GROWTH_CLAIMS)]
        rows = []
        for k in range(n_tx):
            fan = rng.choice(ids)
            cents = rng.randint(5, 50) * 100
            # base + 900_000 + k is k mod 4: DESCRIPTIONS[k % 4], the row's write path
            rows.append(_tx_row(base + 900_000 + k, fan, cents, w.now - timedelta(minutes=1 + k * 6 * 24 * 60 // max(n_tx, 1))))
        sw.txs[a] = rows   # newest first


def _ledger(rng, base: int, fan_ids: list[int], n: int, top, span: timedelta, *, ties: int = 1,
            loading_every: int = 0) -> list[dict]:
    """`n` rows newest first from `top` back over `span`, `ties` rows to a second."""
    step = span / max(n // ties, 1)
    return [_tx_row(base + k, rng.choice(fan_ids), rng.randint(5, 50) * 100, top - step * (k // ties),
                    "loading" if loading_every and k % loading_every == 0 else "done") for k in range(n)]


def _hold_by_sql(con, w, aid: str, rows: list[dict], status=lambda _k: "cleared") -> Counter:
    """`rows` as a past walk wrote them; the fans' lifetime is the caller's. Each fan's spend."""
    spend: Counter = Counter()
    tx = []
    for k, r in enumerate(rows):
        cents, fan = round(r["amount"] * 100), r["user"]["id"]
        st = status(k)
        spend[fan] += 0 if st == "chargedback" else cents
        tx.append((aid, fan, _sale(r)[0], None, cents, "USD", ts(datetime.fromisoformat(r["createdAt"]).replace(tzinfo=None)),
                   ts(w.now), str(r["id"]), st, round(r["net"] * 100), round(r["fee"] * 100), 0, "ledger", r["description"]))
    con.executemany(f"INSERT INTO transactions ({TX_COLS}) VALUES ({','.join('?' * 15)})", tx)
    con.executemany("UPDATE fans SET lifetime_spend_cents = ? WHERE account_id = ? AND fan_id = ?",
                    [(c, aid, f) for f, c in spend.items()])
    return spend


def _seed_ledger_creators(w, sw: SweepWire) -> tuple[str, str, str, str, list[str], dict[str, list[dict]], str, str]:
    """DEEP, REACT, BLANK, GAP, CROWD (module docstring): Creators, fans, sessions, OF's ledger, the held rows.
    And PX's Creators (lib/sweep_pacing_proxy.py), an empty ledger until their stage: its rows, by Creator.
    And CAP (lib/sweep_pacing_promo_cap.py), an empty ledger. And DISPLAY, the last, an empty ledger."""
    extras = creators.extra(w, 4 + CROWD_N + sweep_pacing_proxy.PX_N + 2)
    keep = w.data["fans"]
    pool = fans.seed(w, extras, LEDGER_FANS)
    w.data["fans"] = keep
    of_sessions.seed(w, [*w.data["creators"], *extras])
    deep, react, blank, gap = (extras[k]["id"] for k in range(4))
    crowd = [c["id"] for c in extras[4:4 + CROWD_N]]
    px = [c["id"] for c in extras[4 + CROWD_N:-2]]
    cap, display = extras[-2]["id"], extras[-1]["id"]
    rng = w.rng("scenario:sweep-pacing:ledger")
    ids = {c["id"]: [f["id"] for f in pool[c["id"]]] for c in extras}
    sw.txs[deep] = [*_ledger(rng, LEDGER_ID["deep"], ids[deep], DEEP_ROWS, w.now - timedelta(hours=3), timedelta(days=80),
                             ties=3, loading_every=7),
                    *_ledger(rng, LEDGER_ID["deep_below"], ids[deep], DEEP_BELOW, w.now - timedelta(days=100), timedelta(days=20))]
    rows = _ledger(rng, LEDGER_ID["react"], ids[react], REACT_ROWS, w.now - timedelta(hours=2),
                   timedelta(days=REACT_GAP_D - 2))
    sw.txs[react] = [*rows, *_ledger(rng, LEDGER_ID["react_below"], ids[react], REACT_BELOW,
                                     w.now - timedelta(days=REACT_GAP_D + 3), timedelta(days=7))]
    blank_old = _ledger(rng, LEDGER_ID["blank_old"], ids[blank], BLANK_OLD, w.now - timedelta(days=BLANK_GAP_D + 3),
                        timedelta(days=7))
    sw.txs[blank] = [*_ledger(rng, LEDGER_ID["blank"], ids[blank], BLANK_ROWS, w.now - timedelta(hours=2),
                              timedelta(days=BLANK_GAP_D - 1)), *blank_old]
    day = timedelta(days=1) / 110
    gap_rows = _ledger(rng, LEDGER_ID["gap"], ids[gap], GAP_ROWS + GAP_HELD + GAP_BELOW, w.now - timedelta(hours=1),
                       day * (GAP_ROWS + GAP_HELD + GAP_BELOW))
    sw.txs[gap] = gap_rows
    gap_held = gap_rows[GAP_ROWS:GAP_ROWS + GAP_HELD]
    for k, a in enumerate(crowd):
        sw.txs[a] = _ledger(rng, LEDGER_ID["crowd"] + k * LEDGER_ID_STRIDE, ids[a], CROWD_ROWS, w.now - timedelta(hours=4), timedelta(days=30))
        sw.share[a] = "crowd-proxy"
    px_rows = {a: sweep_pacing_proxy.ledger_rows(rng, LEDGER_ID["px"] + k * LEDGER_ID_STRIDE, ids[a], w.now)
               for k, a in enumerate(px)}
    sw.honest |= {deep, react, blank, gap, *crowd, *px}
    sale = rows[REACT_DISPUTED]
    sw.disputes[react] = [{"id": 0, "createdAt": _iso(w.now - timedelta(days=1)), "paymentType": _sale(sale)[1],
                           "payment": sale | {"id": f"dispute-{sale['id']}", "status": "undo"}}]
    pending = {0, *range(REACT_FLIP_FROM, REACT_FLIP_FROM + REACT_FLIPS)}
    held = rows[:REACT_HELD]

    def at(r: dict) -> str:
        return ts(datetime.fromisoformat(r["createdAt"]).replace(tzinfo=None))

    con = w.sql()
    with con:
        con.execute(f"UPDATE fans SET lifetime_spend_cents = 0 WHERE account_id IN ({','.join('?' * len(extras))})",
                    [c["id"] for c in extras])
        _hold_by_sql(con, w, react, held,
                     lambda k: "chargedback" if k == REACT_DISPUTED else "pending" if k in pending else "cleared")
        _hold_by_sql(con, w, blank, blank_old)
        _hold_by_sql(con, w, gap, gap_held)
        scan = ("INSERT INTO transaction_scan_history (account_id, fully_backfilled, backfill_floor, oldest_seen_occurred_at, "
                "newest_seen_occurred_at, current_status, consecutive_failures, last_scan_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        for a, done, floor, oldest, newest, st, streak in (
                (react, 1, ts(w.now - timedelta(days=90)), at(held[-1]), at(held[0]), "ok", 0),
                (blank, 1, ts(w.now - timedelta(days=90)), at(blank_old[-1]), at(blank_old[0]), "ok", 0),
                (gap, 0, ts(w.now - timedelta(days=40)), at(gap_held[-1]), at(gap_held[0]), "backfill_partial", 0),
                (deep, 0, None, None, None, "error", 2)):
            con.execute(scan, (a, done, floor, oldest, newest, st, streak, ts(w.now), ts(w.now)))
    con.close()
    return deep, react, blank, gap, crowd, px_rows, cap, display


def _seed_lists(w, sw: SweepWire, aids: list[str], listed: str, display: str) -> int:
    """Every profile Creator's promotion List on (SQL, PUT /admin/promo-list's row); LISTED's claimed
    promotion; DISPLAY's display-only links on OF and its Source (link_meta, no list_id). LISTED's promotion id."""
    con = w.sql()
    with con:
        con.executemany("INSERT INTO promo_list_settings (account_id, enabled, list_id, list_name, updated_at)"
                        " VALUES (?, 1, ?, 'slop promo fans', ?)", [(a, PROMO_LIST_ID, ts(w.now)) for a in aids])
    lp = sw.promos[listed][0]
    lp["claimsCount"] = LISTED_CLAIMS
    sw.claims[(listed, lp["id"])] = [{"id": lp["id"] + 800_000 + j, "name": f"Listed {j}", "username": f"l{j}",
                                      "subscribedOnData": {"subscribeAt": _iso(w.now - timedelta(days=j + 1))}}
                                     for j in range(LISTED_CLAIMS)]
    base = 60_000_000_000
    sw.promos[display] = [{"id": base + k, "message": f"slop display promo {k}", "price": 4.99, "type": "all",
                           "claimsCount": DISPLAY_CLAIMS if k < DISPLAY_CLAIMED else 0, "subscribeCounts": 10,
                           "subscribeDays": 0, "createdAt": _iso(w.now - timedelta(days=k + 1)), "finishedAt": None,
                           "isFinished": False, "canClaim": True} for k in range(DISPLAY_PROMOS)]
    for k in range(DISPLAY_CLAIMED):
        sw.claims[(display, base + k)] = [{"id": base + 900_000 + k * 1_000 + j, "name": f"Shown {j}",
                                           "username": f"s{k}_{j}",
                                           "subscribedOnData": {"subscribeAt": _iso(w.now - timedelta(days=j + 1))}}
                                          for j in range(DISPLAY_CLAIMS)]
    cid = base + 500_000
    with sw.fake.lock:
        sw.fake.campaigns[display] = [{"id": cid, "campaignCode": 1, "campaignName": "slop IG", "countTransitions": 40,
                                       "countSubscribers": 5, "createdAt": _iso(w.now - timedelta(days=9)),
                                       "endDate": None}]
    con = w.sql()
    with con:
        con.execute("INSERT INTO link_meta (account_id, kind, of_id, source, updated_at) VALUES (?, 'campaign', ?, 'IG', ?)",
                    (display, cid, ts(w.now)))
    con.close()
    return lp["id"]


def _seed_mirror(w, aid: str, fans: list[dict]) -> str:
    """TERMINAL's roster as a complete crawl 2 h ago wrote it (subscriber_snapshot). Its seen_at."""
    seen = ts(w.now - timedelta(hours=2))
    con = w.sql()
    con.executemany(
        "INSERT INTO subscriber_snapshot (account_id, fan_id, subscribe_at, expired_at, renew_on, seen_at,"
        " resubscribed_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
        [(aid, int(f["id"]), ts(w.now - timedelta(days=30)), ts(w.now + timedelta(days=5)), 1, seen)
         for f in fans[:TERMINAL_SNAPSHOT]])
    con.commit()
    con.close()
    return seen


def _snapshot(w, aid: str) -> tuple[int, str | None]:
    con = w.sql()
    n, last = con.execute("SELECT COUNT(*), MAX(seen_at) FROM subscriber_snapshot WHERE account_id = ?",
                          (aid,)).fetchone()
    con.close()
    return n, last


async def run(ctx) -> None:
    with ExitStack() as wires:   # the fake proxies (sweep_pacing_proxy.bind): alive past the last walk
        await _run(ctx, wires)


async def _run(ctx, wires: ExitStack) -> None:  # noqa: C901  one flow, its checks in order
    w = await ctx.build(PROFILE)
    aids = [c["id"] for c in w.data["creators"]]
    busy, idle = aids[::2], aids[1::2]
    growth, terminal = busy[-1], idle[-1]
    n_promo_all = int(ctx.param("promos", w.size["sweep_pacing_promos"]))
    n_promo = {a: GROWTH_PROMOS if a == growth else n_promo_all for a in aids}
    n_sub = int(ctx.param("subscribers", w.size["sweep_pacing_subscribers"]))
    n_tx = int(ctx.param("transactions", w.size["sweep_pacing_transactions"]))
    fake = ctx.of_wire
    sw = SweepWire(fake)
    sw.window = ctx.fault != WINDOW_IGNORED
    deep, react, blank, gap_a, crowd, px_rows, cap, display = _seed_ledger_creators(w, sw)   # every Creator's session too
    px = list(px_rows)
    ledger_only = (deep, react, blank, gap_a, *crowd)
    _seed_of(sw, w, aids, n_promo, n_sub, n_tx, growth)
    listed = idle[0]
    listed_promo = _seed_lists(w, sw, aids, listed, display)
    for a in idle:
        sw.inject[(a, "promotions")] = {"offset": 100, "text": "Too many requests. Please allow 2 seconds"}
        sw.inject[(a, "subscribers")] = {"offset": 100, "text": TOO_MANY}
        sw.inject[(a, "transactions")] = {"offset": 100, "text": "Too many requests"}
    sw.inject[(terminal, "subscribers")] = {"offset": 100, "text": TOO_MANY, "times": 2}
    sw.inject[(busy[0], "users_list")] = {"offset": 0, "view": "x", "text": TOO_MANY}
    sw.inject[(deep, "transactions")] = {"offset": 0, "marker": True, "skip": DEEP_FAIL_AFTER - 1, "text": TOO_MANY,
                                         "times": 2}
    sw.inject[(react, "transactions")] = {"offset": 0, "marker": True, "skip": REACT_BLANK_AFTER, "empty": True}
    sw.inject[(blank, "transactions")] = {"offset": 0, "empty": True}
    sw.install()
    mirror_seen = _seed_mirror(w, terminal, sw.subs[terminal])
    mirror0 = _snapshot(w, terminal)
    con = w.sql()
    tx0 = dict(con.execute("SELECT account_id, COUNT(*) FROM transactions GROUP BY account_id").fetchall())
    con.close()
    ctx.metric("world", {"creators": len(aids), "busy": busy, "idle": idle, "growth": growth, "terminal": terminal,
                         "listed": listed, "display": display,
                         "promos": n_promo_all, "subscribers": n_sub, "transactions": n_tx, "users": ctx.users})

    r = await ctx.owner.post("/__slop/sweep-pacing/knobs", json=KNOBS)
    r.raise_for_status()
    knobs = r.json()
    gap, jitter = PAGE_GAP_S, JITTER_S
    # ── proxies, as on AE: CROWD on one (its shared bucket), the rest PER_PROXY a proxy; PX direct until its stage ──
    rest = [*aids, deep, react, blank, gap_a]
    per = sweep_pacing_proxy.PER_PROXY
    bound = await sweep_pacing_proxy.bind(ctx, wires, [list(crowd), *(rest[k:k + per] for k in range(0, len(rest), per))])
    ctx.metric("proxies", {"bound": bound, "per_proxy": dict(Counter(bound.values()))})

    # ── REACT: off, its gap backdated, on: the real reactivation queues the backfill ─
    sse_http = ctx.owner.share()
    sse = SseListener(sse_http, states=("transaction_recorded",))
    await sse.start()
    for a, gap_d in ((react, REACT_GAP_D), (blank, BLANK_GAP_D)):
        (await ctx.owner.post(f"/admin/accounts/{a}/active", json={"active": False})).raise_for_status()
        con = w.sql()
        with con:
            con.execute("UPDATE account_health SET deactivated_at = ? WHERE account_id = ?",
                        (ts(w.now - timedelta(days=gap_d)), a))
        con.close()
        (await ctx.owner.post(f"/admin/accounts/{a}/active", json={"active": True})).raise_for_status()
    react0, blank0, gap0 = scan_one(w, react), scan_one(w, blank), scan_one(w, gap_a)

    # ── people on the busy Creators ─────────────────────────────────────────
    ur, br = Recorder(), Recorder()            # a person's lookups / the Fan List's background ones
    users_http, bg_http = ctx.owner.share(rec=ur, limits=50), ctx.owner.share(rec=br, limits=100)
    look_ids = itertools.count(20_000_000_000)
    lookups: list[dict] = []

    async def lookup(a: str, background: bool) -> None:
        ids = [next(look_ids) for _ in range(10)]
        hdr = {"X-Account-Id": a, **({"X-Priority": "background"} if background else {})}
        q = "&".join(f"ids={i}" for i in ids) + f"&view={'x' if background else 'm'}"
        t0 = time.perf_counter()
        try:
            st = (await (bg_http if background else users_http).get(f"/api/of/v2/users/list?{q}", headers=hdr)).status_code
        except Exception:  # noqa: BLE001  recorded as 599 by the client
            st = 599
        lookups.append({"account": a, "background": background, "status": st, "t": time.time(),
                        "ms": (time.perf_counter() - t0) * 1000})

    await asyncio.gather(*(lookup(a, False) for a in busy))   # the busy Creators are busy before any walk
    chat_http = ctx.owner.share(limits=max(10, ctx.users))
    chatters = chatter.Chatters({a: chat_http for a in busy}, {a: 1.0 for a in busy},
                                w.rng("scenario:sweep-pacing:chatters"))
    chatters.start(max(1, ctx.users))

    async def fan_list(a: str) -> None:
        for _ in range(BURSTS):
            t0 = time.monotonic()

            async def person(d: float) -> None:
                await asyncio.sleep(d)
                await lookup(a, False)

            await asyncio.gather(*(lookup(a, True) for _ in range(BURST_N)), *(person(d) for d in USER_AT_S))
            await asyncio.sleep(max(0.0, BURST_EVERY_S - (time.monotonic() - t0)))

    # ── every walk at once ──────────────────────────────────────────────────
    earn_http = ctx.owner.share(limits=4)
    earnings: list[dict] = []

    async def earnings_reads() -> None:   # the Growth page's read, while GROWTH's claimer walk runs
        for _ in range(EARNINGS_N):
            t0 = time.time()
            try:
                st = (await earn_http.get(f"/admin/of-tracking-links/earnings?account_id={growth}")).status_code
            except Exception:  # noqa: BLE001  recorded as 599 by the client
                st = 599
            t1 = time.time()
            earnings.append({"t0": t0, "t1": t1, "status": st, "ms": round((t1 - t0) * 1000, 1)})
            await asyncio.sleep(max(0.0, EARNINGS_EVERY_S - (t1 - t0)))

    ctx.rec.stage = "walks"
    t_walks = time.time()
    gr = await ctx.owner.get(f"/admin/promotions?account_id={growth}")   # its claimer refresh starts
    t_growth = time.time()
    growth_page = {"status": gr.status_code, **({k: gr.json().get(k) for k in ("of_available", "metrics_refreshing")}
                                                if gr.status_code == 200 else {})}
    earn = asyncio.ensure_future(earnings_reads())
    await asyncio.sleep(GROWTH_SETTLE_S)
    bursts = asyncio.gather(*(fan_list(a) for a in busy))
    for job, extra in (("link_prewarm", {}), ("subscribers", {"account_ids": aids}),
                       ("tx_cycles", {"cycles": 1})):
        (await ctx.owner.post("/__slop/sweep-pacing/run", json={"job": job, **extra})).raise_for_status()
    deadline = time.monotonic() + RUN_TIMEOUT_S
    new_rows: dict[str, list[str]] = {}   # Creator -> provider ids OF gained before the recent pass
    passed, admin = {}, {}
    fresh = _tx_row(LEDGER_ID["fresh"], sw.txs[deep][0]["user"]["id"], 1_700, datetime.now(timezone.utc) - timedelta(hours=1))

    async def runs_until(done) -> dict:   # /runs once `done(runs)` or past the deadline
        while True:
            got = (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()
            if done(got["runs"]) or time.monotonic() > deadline:
                return got
            await asyncio.sleep(0.5)

    async def tx_pass() -> bool:   # the next supervisor pass, run to its end (False: the deadline came first)
        return (await sweep_pacing_watermark.tx_pass(ctx.owner, sw, max(0.0, deadline - time.monotonic())))["ended"]

    async def supervisor_passes() -> None:   # pass 1 started beside the other jobs; 2..TX_CYCLES one after another
        got = await runs_until(lambda runs: any(x["job"] == "tx_cycles" and x["t1"] for x in runs))
        if time.monotonic() > deadline:
            return
        # After the first fill: an operator resumes REACT, unless it reads complete (a person
        # sees nothing to resume).
        passed[1] = {deep: scan_one(w, deep), react: scan_one(w, react), blank: scan_one(w, blank), gap_a: scan_one(w, gap_a),
                     "disputed": _tx_status(w, react, sw.txs[react][REACT_DISPUTED]["id"])}
        if not passed[1][react]["done"]:
            admin["t0"] = time.time()
            admin["status"] = (await ctx.owner.post(f"/admin/ingest/transactions/{react}/run",
                                                    json={"mode": "backfill"})).status_code
            until = time.monotonic() + ADMIN_RUN_TIMEOUT_S
            while not scan_one(w, react)["done"] and time.monotonic() < until:
                await asyncio.sleep(0.5)
            admin["t1"] = time.time()
        # A period turned over: the backfilled Creators' full walk is due (last_full_at persists).
        con = w.sql()
        with con:
            con.execute("UPDATE transaction_scan_history SET last_full_at = ? WHERE fully_backfilled = 1",
                        (ts(datetime.utcnow() - timedelta(seconds=got["full_every_s"])),))
        con.close()
        if not await tx_pass():
            return
        passed[2] = {deep: scan_one(w, deep)}
        sw.add_tx(deep, fresh)   # a row above DEEP's walk: its next tick's recent read lands it
        # Between the full pass and the recent one: OF gains a row 10 h old (the recent walk must
        # land it) and one 3 days old (before its startDate: the next full walk's, not its).
        sw.startdate_iso = ctx.fault == STARTDATE_ISO
        at = datetime.now(timezone.utc)
        for i, a in enumerate(aids):
            fan = sw.txs[a][0]["user"]["id"]
            for j, ago in enumerate(NEW_ROW_AGO):
                pid = LEDGER_ID["new"] + i * NEW_ROWS_STRIDE + j
                sw.add_tx(a, _tx_row(pid, fan, 1_200, at - ago, description=f"Tip from u{fan}"))
                new_rows.setdefault(a, []).append(str(pid))
        if not await tx_pass():
            return
        passed[3] = {deep: scan_one(w, deep), "fresh_held": str(fresh["id"]) in held(w, deep)[0]}
        await tx_pass()

    await supervisor_passes()
    await runs_until(lambda runs: all(x["t1"] for x in runs))
    walls = time.time() - t_walks
    await bursts
    await earn
    await chatters.stop()
    # ── pass 2: everyone idle past the window, the next prewarm pass walks the skipped ──────────
    lp = next(p for p in sw.promos[listed] if p["id"] == listed_promo)
    with sw._lock:   # OF gains LISTED_CLAIMS claimers on LISTED's promotion: the pass's add takes them in
        sw.claims[(listed, listed_promo)] = [*sw.claims[(listed, listed_promo)], *(
            {"id": listed_promo + 850_000 + j, "name": f"Listed late {j}", "username": f"ll{j}",
             "subscribedOnData": {"subscribeAt": _iso(datetime.now(timezone.utc))}} for j in range(LISTED_CLAIMS))]
        lp["claimsCount"] = 2 * LISTED_CLAIMS
    await asyncio.sleep(knobs["USER_WINDOW_S"] + IDLE_SLACK_S)
    (await ctx.owner.post("/__slop/sweep-pacing/run", json={"job": "link_prewarm"})).raise_for_status()
    got = await runs_until(lambda runs: all(x["t1"] for x in runs))
    timed_out = time.monotonic() > deadline
    ctx.rec.stage = None
    await sse.stop()
    for h in (users_http, bg_http, chat_http, earn_http, sse_http):
        await h.aclose()
    runs, plog = got["runs"], got["log"]
    log = [e for e in sw.snapshot() if e["t"] >= t_walks - 5]

    def person_read(e) -> bool:   # GROWTH's Promotions page / an earnings read: their own OF reads, unpaced
        if e["account"] != growth:
            return False
        if e["route"] == "promotions":
            return t_walks <= e["t"] <= t_growth
        return e["route"] == "campaigns" and any(x["t0"] <= e["t"] <= x["t1"] for x in earnings)

    def walk_get(e) -> bool:
        return e["route"] in WALK_ROUTES and not person_read(e)

    def bg(e) -> bool:
        return walk_get(e) or (e["route"] == "users_list" and e["view"] == "x")

    # ── pages_spaced ────────────────────────────────────────────────────────
    per: dict[str, list[dict]] = defaultdict(list)
    for e in log:
        if walk_get(e):
            per[e["account"]].append(e)
    floor = gap - SPACE_SLACK_S
    space = {}
    for a in (*aids, *ledger_only):
        ts_ = sorted(e["t"] for e in per[a])
        gaps = [b - x for x, b in zip(ts_, ts_[1:])]
        space[a] = {"gets": len(ts_), "min_gap_s": round(min(gaps), 3) if gaps else None,
                    "under": sum(1 for g in gaps if g < floor)}
    ctx.check(PAGES_SPACED, all(v["gets"] > 1 and v["under"] == 0 for v in space.values()),
              page_gap_s=gap, floor_s=round(floor, 3), relay_knobs=knobs, per_creator=space)

    # ── retry_once_per_429 ──────────────────────────────────────────────────
    # A supervisor pass is another walk: its first request may repeat the page a failed tick ended on.
    pass_starts = sorted(c["t0"] for x in runs if x["job"] == "tx_cycles" for c in ((x.get("result") or {}).get("cycles") or []))
    same: dict[tuple, list[dict]] = defaultdict(list)
    for e in log:
        if bg(e):
            same[(e["account"], e["route"], e["query"])].append(e)
    bad_retry, n429, terminal_429s = [], 0, 0
    for e in log:
        if e["status"] != 429 or not bg(e):
            continue
        n429 += 1
        page = same[(e["account"], e["route"], e["query"])]
        before = [x for x in page if x["t"] < e["t"]]
        cut = min((t for t in pass_starts if t > e["t"]), default=float("inf")) if e["route"] == "transactions" else float("inf")
        nxt = [x for x in page if e["t"] < x["t"] <= min(e["t"] + RETRY_WINDOW_S, cut)]
        if before and before[-1]["status"] == 429:   # this is the retry: OF's second 429 ends the page
            terminal_429s += 1
            ok = not nxt
        else:
            ok = len(nxt) == 1 and nxt[0]["t"] >= e["t"] + _asked(e["asked"]) - RETRY_SLACK_S
        if not ok:
            bad_retry.append({"account": e["account"], "route": e["route"], "offset": e["offset"],
                              "asked_s": _asked(e["asked"]),
                              "after": [(x["status"], round(x["t"] - e["t"], 2)) for x in nxt][:3]})
    unfired = [f"{a} {r_}" for (a, r_), v in sw.inject.items() if not v.get("done")]
    ctx.check(RETRY_ONCE, n429 > 0 and not bad_retry and not unfired, of_429s=n429, retry_429s=terminal_429s,
              wrong=len(bad_retry), e_g=bad_retry[:5], injected=len(sw.inject), unfired=unfired)

    # ── no_429_on_user_reads ────────────────────────────────────────────────
    user_of = [e for e in log if e["route"] == "users_list" and e["view"] == "m"]
    user_relay = [x for x in lookups if not x["background"]]
    page_of = [e for e in log if person_read(e) and e["route"] == "promotions"]
    of_bad = Counter((e["route"], e["status"]) for e in user_of + page_of if e["status"] != 200)
    relay_bad = sum(1 for x in user_relay if x["status"] != 200)
    why = [{"account": e["account"], "route": e["route"], "t": round(e["t"] - t_walks, 2), "tokens": e.get("tokens")}
           for e in user_of + page_of if e["status"] != 200]
    ctx.check(NO_429_USER, bool(user_of) and len(user_of) == len(user_relay) and bool(page_of) and not of_bad
              and relay_bad == 0 and growth_page.get("status") == 200,
              of_saw=len(user_of), asked=len(user_relay), page_reads=len(page_of),
              of_not_200={f"{r} {st}": n for (r, st), n in of_bad.items()}, relay_not_200=relay_bad, e_g=why[:4])

    # ── prewarm_skips_busy_creators ─────────────────────────────────────────
    passes = [x for x in runs if x["job"] == "link_prewarm"]
    def in_pass(t, x) -> bool:
        return x["t0"] <= t <= (x["t1"] or float("inf"))

    def skips(x) -> Counter:
        return Counter(m.group(1) for y in plog if in_pass(y["t"], x) and (m := _SKIP.search(y["msg"])))

    def prewarm_gets(x, a) -> int:
        return sum(1 for e in per[a] if e["route"] in PREWARM_ROUTES and in_pass(e["t"], x))
    sk = {}
    if len(passes) == 2:
        p1, p2 = passes
        s1, s2 = skips(p1), skips(p2)
        sk = {
            "pass1_busy_not_skipped_once": [a for a in busy if s1.get(a) != 1],
            "pass1_idle_skipped": sorted(a for a in s1 if a in idle),
            "pass1_busy_walked": {a: n for a in busy if (n := prewarm_gets(p1, a))},
            "pass1_idle_not_walked": [a for a in idle if not prewarm_gets(p1, a)],
            "pass2_skipped": sorted(s2),
            "pass2_busy_not_walked": [a for a in busy if not prewarm_gets(p2, a)],
        }
    ctx.check(SKIPS, len(passes) == 2 and bool(busy) and not any(sk.values()), passes=len(passes), **sk,
              pass_s=[round(x["t1"] - x["t0"], 1) if x["t1"] else None for x in passes])

    # ── prewarm_scope ───────────────────────────────────────────────────────
    no_list = (display, *ledger_only, *px, cap)

    def growth_read(e) -> bool:   # a Growth list read or a claimer page
        return e["route"] in PREWARM_ROUTES or (e["route"] == "subscribers" and "filter" in (e["query"] or ""))
    scope: dict = {"passes": len(passes)}
    if len(passes) == 2:
        reads = {f"pass{i + 1}": dict(Counter(f"{'DISPLAY' if e['account'] == display else e['account']} {e['route']}"
                                              for e in log if e["account"] in no_list and growth_read(e)
                                              and in_pass(e["t"], x)))
                 for i, x in enumerate(passes)}
        no_skip = [i + 1 for i, x in enumerate(passes)
                   if not any(in_pass(y["t"], x) and (m := _NO_LIST.search(y["msg"])) and m.group(1) == display
                              for y in plog)]
        adds = [[e["count"] for e in log if e["route"] == "list_add" and e["account"] == listed
                 and e["link"] == listed_promo and in_pass(e["t"], x)] for x in passes]
        con = w.sql()
        lm_row = con.execute("SELECT list_id, list_added_count FROM link_meta WHERE account_id = ? AND kind = 'promo'"
                             " AND of_id = ?", (listed, listed_promo)).fetchone()
        con.close()
        scope |= {"no_list_reads": reads, "display_skip_missing_in_pass": no_skip,
                  "listed_adds_per_pass": adds, "listed_meta": list(lm_row) if lm_row else None,
                  "display_list_adds": sum(1 for e in log if e["route"] == "list_add" and e["account"] == display)}
        ok = (not any(reads.values()) and not no_skip and adds == [[LISTED_CLAIMS], [2 * LISTED_CLAIMS]]
              and scope["listed_meta"] == [PROMO_LIST_ID, 2 * LISTED_CLAIMS] and not scope["display_list_adds"])
    else:
        ok = False
    ctx.check(PREWARM_SCOPE, ok, display=display, listed=listed, listed_promo=listed_promo,
              no_list_creators=len(no_list), **scope)

    # ── growth_refresh_walked ───────────────────────────────────────────────
    claimed = [p["id"] for p in sw.promos[growth] if p["claimsCount"]]
    claim_gets = Counter()
    for e in per[growth]:
        m = re.search(r"filter%5BpromoId%5D=(\d+)|filter\[promoId\]=(\d+)", e["query"])
        if e["route"] == "subscribers" and m:
            claim_gets[int(m.group(1) or m.group(2))] += 1
    con = w.sql()
    rows = dict(con.execute("SELECT of_id, COUNT(*) FROM link_claimers WHERE account_id = ? AND kind = 'promo'"
                            " GROUP BY of_id", (growth,)).fetchall())
    con.close()
    pages_each = -(-GROWTH_CLAIMS // CLAIMER_PAGE)
    gw = {p: {"of_gets": claim_gets.get(p, 0), "rows": rows.get(p, 0)} for p in claimed}
    ctx.check(GROWTH, growth_page.get("status") == 200 and growth_page.get("metrics_refreshing") is True
              and all(v["of_gets"] >= pages_each and v["rows"] == GROWTH_CLAIMS for v in gw.values()),
              page=growth_page, pages_each=pages_each, per_promo=gw)

    # ── growth_route_not_blocked ────────────────────────────────────────────
    cts = sorted(e["t"] for e in per[growth] if e["route"] == "subscribers" and "filter" in e["query"])
    walk_span = (cts[0], cts[-1]) if cts else None
    during = [x for x in earnings if walk_span and x["t0"] < walk_span[1] and x["t1"] > walk_span[0]]
    slow_e = [x for x in earnings if x["status"] != 200 or x["ms"] > EARNINGS_MAX_MS]
    ctx.check(GROWTH_ROUTE, len(earnings) == EARNINGS_N and not slow_e and bool(during),
              reads=len(earnings), during_walk=len(during), claimer_pages=len(cts),
              walk_s=round(walk_span[1] - walk_span[0], 1) if walk_span else None, budget_ms=EARNINGS_MAX_MS,
              max_ms=max((x["ms"] for x in earnings), default=None),
              max_ms_during_walk=max((x["ms"] for x in during), default=None),
              p50_ms=pct([x["ms"] for x in earnings], 0.5) if earnings else None,
              not_ok=[(x["status"], x["ms"], round(x["t0"] - t_walks, 1)) for x in slow_e][:5])

    # ── terminal_429_keeps_mirror ───────────────────────────────────────────
    tpage = [e for e in log if e["account"] == terminal and e["route"] == "subscribers" and e["offset"] == 100
             and "filter" not in e["query"]]
    trun = [x for x in runs if x["job"] == "subscribers" and x["account"] == terminal]
    mirror1 = _snapshot(w, terminal)
    ctx.check(TERMINAL, [e["status"] for e in tpage] == [429, 429] and len(trun) == 1
              and bool(trun[0]["error"]) and "429" in (trun[0]["error"] or "") and mirror1 == mirror0,
              sends=[(e["status"], round(e["t"] - tpage[0]["t"], 2)) for e in tpage], run=trun[:1],
              mirror_before=mirror0, mirror_after=mirror1, seeded_seen_at=mirror_seen)

    # ── walk_counts_match ───────────────────────────────────────────────────
    con = w.sql()
    meta = dict(con.execute("SELECT account_id, COUNT(*) FROM link_meta WHERE kind='promo' GROUP BY account_id"))
    snap = dict(con.execute("SELECT account_id, COUNT(*) FROM subscriber_snapshot GROUP BY account_id"))
    added = [pid for ids in new_rows.values() for pid in ids]
    tx1 = dict(con.execute("SELECT account_id, COUNT(*) FROM transactions WHERE provider_transaction_id NOT IN "
                           f"({','.join('?' * len(added)) or 'NULL'}) GROUP BY account_id", added))
    landed = {str(r[0]) for r in con.execute(
        f"SELECT provider_transaction_id FROM transactions WHERE provider_transaction_id IN "
        f"({','.join('?' * len(added)) or 'NULL'})", added)}
    con.close()
    errs = [{k: x[k] for k in ("job", "account", "error")} for x in runs
            if (x["error"] and not (x["job"] == "subscribers" and x["account"] == terminal))
            or (x["job"] == "subscribers" and x["account"] != terminal
                and (x["result"] or {}).get("roster") != "crawled")]
    cnt_bad = {}
    for a in aids:
        got_ = {"promos": meta.get(a, 0), "subscribers": snap.get(a, 0), "transactions": tx1.get(a, 0) - tx0.get(a, 0)}
        want = {"promos": n_promo[a], "subscribers": mirror0[0] if a == terminal else n_sub,
                "transactions": n_tx}
        if got_ != want:
            cnt_bad[a] = {"got": got_, "want": want}
    ctx.check(COUNTS, not errs and not cnt_bad and not timed_out and len(runs) == 3 + TX_CYCLES - 1 + len(aids),
              runs=len(runs), failed=errs[:6], n_failed=len(errs), wrong=cnt_bad, timed_out=timed_out)

    # ── no_5xx ──────────────────────────────────────────────────────────────
    lost = sum(1 for k, page in same.items() if k[1] == "users_list" and page[-1]["status"] == 429)
    look5 = sum(1 for x in lookups if x["status"] >= 500)
    other5 = {k: v["5xx"] for rec in (ctx.rec,) for k, v in rec.summary().items() if v["5xx"]}
    ctx.check(NO_5XX, not other5 and look5 <= lost and not any(x["status"] == 599 for x in lookups),
              other_5xx=other5, lookup_5xx=look5, lookups_left_429=lost, chatter_actions=chatters.actions)

    # ── user_read_p95 / background_lookup_p95 ───────────────────────────────
    lat = [x["ms"] for x in user_relay if x["status"] == 200]
    p95 = pct(lat)
    ctx.check(USER_P95, p95 is not None and p95 <= USER_READ_P95_MS, budget=True,
              p95_ms=p95, n=len(lat), budget_ms=USER_READ_P95_MS)
    bgl = [x["ms"] for x in lookups if x["background"]]
    bg95 = pct(bgl)
    ctx.check(BG_P95, bg95 is not None and bg95 <= BACKGROUND_LOOKUP_P95_MS, budget=True,
              p95_ms=bg95, n=len(bgl), budget_ms=BACKGROUND_LOOKUP_P95_MS,
              not_200=dict(Counter(x["status"] for x in lookups if x["background"] and x["status"] != 200)))
    ctx.metric("p95_vs_last_green", {"user lookup": p95, "background lookup": bg95})
    ctx.metric("p95_vs_last_green_n", {"user lookup": len(lat), "background lookup": len(bgl)})

    # ── the ledger supervisor's passes (measured) ───────────────────────────
    cycles = [c for x in runs if x["job"] == "tx_cycles" for c in ((x.get("result") or {}).get("cycles") or [])]
    sup, pass_pages, pass_modes = [], [], []
    for i, c in enumerate(cycles):
        pages = Counter(e["account"] for e in log if e["route"] == "transactions" and c["t0"] <= e["t"] <= c["t1"])
        modes = {m.group(1): m.group(2) for y in plog
                 if c["t0"] <= y["t"] <= c["t1"] and (m := _TX_START.search(y["msg"]))}
        pass_pages.append(pages)
        pass_modes.append(modes)
        sup.append({"pass": i + 1, "wall_s": round(c["t1"] - c["t0"], 1), "creators": len(pages),
                    "modes": dict(Counter(modes.values())),
                    "pages_per_creator": sorted(pages.values()), "pages": sum(pages.values())})
    ctx.metric("tx_supervisor", sup)
    # Only Creators whose full walk ended before the last pass are due a recent one (a Creator whose
    # backfill the 429s failed runs one pass late).
    full_ok = sorted({m.group(1) for c in cycles[:-1] for y in plog
                      if c["t0"] <= y["t"] <= c["t1"] and (m := _TX_FULL_OK.search(y["msg"]))} & set(aids))
    tick, full_s = got.get("tick_interval_s"), got.get("full_every_s")
    walk = {a: {md: max((p.get(a, 0) for p, ms in zip(pass_pages, pass_modes) if ms.get(a) == md), default=0)
                for md in ("recent", "refresh")} for a in full_ok}
    per_h = ({a: round(v["recent"] * 3600 / tick + v["refresh"] * 3600 / full_s, 1) for a, v in walk.items()}
             if tick and full_s else {})
    since = (w.now.replace(tzinfo=None) - timedelta(hours=TX_RECENT_H, days=1)).date().isoformat()   # startDate
    budget_h = {}
    for a in full_ok:
        recent_rows = sum(1 for r in sw.txs[a] if r["createdAt"][:10] >= since)
        budget_h[a] = round((_pages(recent_rows) * 3600 / TX_TICK_S
                             + _pages(min(n_tx, TX_CAP)) * 3600 / TX_FULL_S) * TX_HEADROOM, 1)
    cb_on_recent = sum(1 for c, ms in zip(cycles, pass_modes) for e in log if e["route"] == "chargebacks"
                       and c["t0"] <= e["t"] <= c["t1"] and ms.get(e["account"]) == "recent")
    cb_on_full = Counter(e["account"] for c, ms in zip(cycles, pass_modes) for e in log if e["route"] == "chargebacks"
                         and c["t0"] <= e["t"] <= c["t1"] and ms.get(e["account"]) == "refresh" and e["account"] in full_ok)
    ctx.check(TX_BUDGET, len(cycles) == TX_CYCLES and bool(full_ok) and len(per_h) == len(full_ok)
              and all(v["recent"] and v["refresh"] for v in walk.values())
              and all(per_h[a] <= budget_h[a] for a in full_ok) and cb_on_recent == 0,
              creators=len(aids), full_ok=len(full_ok), tick_interval_s=tick, full_every_s=full_s, pages_per_walk=walk, calls_per_hour=per_h,
              budget_per_hour=budget_h, disputes_calls_on_recent_passes=cb_on_recent, disputes_calls_on_full_passes=dict(cb_on_full))
    ignored = [y["msg"] for y in plog if _TX_IGNORED in y["msg"]]
    recent_walks = sorted({a for ms in pass_modes for a, md in ms.items() if md == "recent"})
    ctx.check(TX_WINDOW, bool(full_ok) and set(full_ok) <= set(recent_walks) and not ignored,
              recent_walks=len(recent_walks), full_ok=len(full_ok), creators=len(aids), warnings=len(ignored), e_g=ignored[:3])
    empty = [y["msg"] for y in plog if _TX_EMPTY in y["msg"]]
    last_modes = pass_modes[-1] if pass_modes else {}
    missed = [a for a in full_ok if new_rows.get(a, [""])[0] not in landed or last_modes.get(a) != "recent"]
    ctx.check(TX_NEW_ROW, bool(full_ok) and not missed and not empty,
              full_ok=len(full_ok), missed=missed, empty_walk_warnings=len(empty), e_g=empty[:3],
              rows_3d_old_landed=sum(1 for a in full_ok if new_rows[a][1] in landed))
    sweep_pacing_backfill.check(
        ctx, w, sw, deep=deep, react=react, blank=blank, gap_a=gap_a, crowd=crowd, passed=passed, react0=react0,
        blank0=blank0, gap0=gap0, admin=admin, pass_modes=pass_modes, plog=plog, log=log, cycles=cycles, same=same,
        t_walks=t_walks, since=since, sse=sse)

    slow = sorted((x for x in user_relay if p95 is not None and x["ms"] >= p95), key=lambda x: x["t"])
    ctx.metric("user_lookups_at_or_over_p95", [{"s_into_walks": round(x["t"] - t_walks, 1), "ms": round(x["ms"]),
                                               "account": x["account"]} for x in slow])
    ctx.metric("walks", {"wall_s": round(walls, 1), "of_gets": len(log), "of_429": n429,
                         "background_lookup_p95_ms": bg95,
                         "runs": [{k: x[k] for k in ("job", "account", "error")} |
                                  {"s": round(x["t1"] - x["t0"], 1) if x["t1"] else None} for x in runs]})
    ctx.note(f"{len(aids)} Creators ({len(busy)} busy), walls {walls:.0f} s, {len(log)} list GETs at OF, "
             f"{n429} 429s, user lookup p95 {p95} ms over {len(lat)}, background lookup p95 {bg95} ms over "
             f"{len(bgl)}, {sum(chatters.actions.values())} chatter actions",
             *(f"ledger supervisor pass {s['pass']} {s['modes']}: {s['wall_s']} s, {s['pages']} pages over "
               f"{s['creators']} Creators ({s['pages_per_creator']})" for s in sup),
             f"ledger calls/h per Creator at {tick}/{full_s} s (inferred): {per_h} vs budget {budget_h}")

    # ── a capped promotions history: reads 2 and 3 read less than the cap (before the restart below) ──
    await sweep_pacing_promo_cap.run(ctx, w, sw, cap)
    # ── the full walk's persisted watermark: restart, failed full walk (after every check above) ──
    await sweep_pacing_watermark.run(ctx, w, sw, shared=set(crowd) | set(px) | {cap, display})
    # ── ledger pages per bound proxy: shared / separate proxies, an ADR-0030 move (lib/sweep_pacing_proxy.py) ──
    await sweep_pacing_proxy.run(ctx, w, sw, px, px_rows, gap=gap, slack=SPACE_SLACK_S)
