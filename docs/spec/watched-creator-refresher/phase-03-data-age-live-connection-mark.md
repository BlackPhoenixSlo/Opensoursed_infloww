# Phase 03 — Data age and No-live-connection mark

2026-11-20 · design only · plan `.scratch/watched-creator-refresher/goal.md` (Phase 3, D7, D10) · study row 8
(`.scratch/all-models-of-budget/REPORT.md` §4 on `study/all-models-of-budget`) · ADRs 0031, 0042, 0043, 0044.
Labels: m = measured, i = inferred (from code or design), g = guess. Decision rungs: r1 observation, r2 written
instruction, r3 house precedent, r4 reversibility, r5 smallest, r6 coin flip.

**Objective.** A chatter under All Models can tell a stale Unread badge from a true one ("as of 4 min" once its
truth is older than its Creator's Cycle) and sees on each Creator tab when the Relay has no Live connection for
that Creator, at 0 OF calls.

## Problem Statement

Today every number in Messages Pro looks equally true. The Unread badge (the Fan List's Unread chip,
`app/components/chat/FanListFilters.tsx:207`, count from `FanList.tsx:452-455`) shows a count with no hint of
its age; the study saw it say 12 against 1 real unread row (owner, live) and a chat read on OF web reach no tab
in 45 s (m, slop run 1). Phase 2 makes the badge the Relay's Unread total, bounded by one Cycle, but a Cycle
can slip (429 back-off, the per-exit gate, a failing read) and a chatter cannot see that it slipped.

The Live connection is what keeps a Creator current between Shared refresher reads (DMs at 0 OF calls, ADR-0042).
When it is down, new messages reach the tab only on the next read, and nothing on screen says so: the Creator
tab shows its unread and bell badges whatever the socket does (`CreatorTabs.tsx:206-251`). A Dead-session
Creator's tab shows nothing either: the tab only stops reading its bell count (`CreatorTabs.tsx:206-209`); the
"Disconnected" word lives on other screens (`lib/sessionConnectivity.ts:24-29`, `components/setup/AccountsTable.tsx:101`,
`components/of-manager/CreatorColumn.tsx:56-58, 408, 420-429`).

## Solution

- The Unread badge shows nothing new while its truth is within one Cycle. Past one Cycle (plus a 40 s delivery
  slack, needs-human: see "When a badge is stale") for any Creator it counts, the chip adds a small dim "as of
  4 min" after its label; hovering says how old and how many Creators are behind. It goes away as soon as the
  late Creator's next confirmation arrives.
- Each Creator tab (and its row in "+ Add a Creator") gets a small dot at the foot of its avatar while the Relay
  has no Live connection for it: amber "No live connection" once the socket has been down 60 s (a routine
  reconnect never shows it), red "Disconnected" at once for a Dead session (the existing word). It clears when
  the socket is back or the session is re-captured.
- Refresher off or killed: no "as of" and no amber dot anywhere (today's screen), never everything stale forever.
- One shared clock ticks every 15 s for the whole tab; only a badge whose text changes re-renders.
- No OF call, no Relay route, no `service/` change.

## User Stories

1. As a chatter under All Models, I want the Unread badge to look exactly as today while every Creator it counts is within its Cycle, so that the normal screen stays quiet.
2. As a chatter, I want the Unread badge to show "as of N min" once any Creator it counts is older than its Cycle plus the delivery slack, so that I know the count may be off.
3. As a chatter, I want the age shown to be the oldest late Creator's, so that the text speaks for the worst Creator, not an average (whole units rounded down; the tooltip gives whole minutes).
4. As a chatter, I want the chip's tooltip to say how old and how many of the counted Creators are late ("As of 12 min ago: 1 of 10 Creators not refreshed within its Cycle"), so that I can judge how far to trust it.
5. As a chatter on one Creator, I want the same rule on that Creator's Unread badge ("As of 4 min ago: not refreshed within its 2 min Cycle"), so that one rule serves both scopes.
6. As a chatter, I want the "as of" to disappear the moment the late Creator's new value arrives, so that a recovered badge looks fresh again.
7. As a chatter, I want a Creator on the lease cycle (~120 s) judged against 120 s and one on the tab cycle (~10 min) against 10 min, so that an unleased Creator is not marked stale for being on the slow tier.
8. As a chatter whose Creator just moved from the tab cycle to the lease cycle, I want its badge to say "as of 8 min" until its next read, so that I am told its data really is that old now that I look at it.
9. As a chatter, I want no "as of" when the Shared refresher is off, killed, or not reading a Creator by design (its Cycle is unknown), so that a kill switch brings back today's screen and never paints every badge stale forever.
10. As a chatter after a Relay restart, I want no "as of" for a Creator with no Last refresh yet, so that "not read yet" is not shown as "stale".
11. As a chatter, I want a Dead-session Creator left out of the Unread badge's age, so that a Creator nobody refreshes (D2) does not keep the badge stale forever; its own mark says why.
12. As a chatter whose laptop clock is minutes off, I want the age measured in the Relay's clock, so that skew never flips a badge.
13. As a chatter whose tab replayed missed events after an Event stream gap, I want ages computed from the Relay's live clock, not the replayed events' send time, so that a replay never makes old truth look new.
14. As a chatter whose tab was hidden, I want the age correct the instant I look back, so that a throttled background timer never shows a wrong age.
15. As a chatter in Idle mode, I want nothing extra (the idle overlay already says live updates are paused), and on return the age to show until the next value lands, so that the screen stays honest after the pause.
16. As a chatter, I want a Creator tab to show a "No live connection" dot once the Relay's socket for it has been down 60 s, so that I know new DMs may arrive late.
17. As a chatter, I want a routine reconnect (socket back within 60 s, including a Relay restart's reconnect wave) to show no dot, so that the strip does not flicker.
18. As a chatter, I want a socket that flaps (down 5 s, up long enough for the Relay to see it, down 5 s) to show no dot, so that only a lasting outage marks; an "up" shorter than the Relay's 5 s sample is one outage, since such a socket keeps nothing current.
19. As a chatter, I want a Dead-session Creator's tab to show a red "Disconnected" dot at once, using the word the Creators page already uses, so that the two screens agree.
20. As a chatter, I want the Dead-session mark to win over a Live connection that still reads up, so that a flagged session never looks live (the house rule that a flagged session outranks `has_session`).
21. As a chatter, I want the dot to clear the moment the socket is up again, or the session is re-captured, so that a healed Creator looks healed.
22. As a chatter, I want a Creator with no OnlyFans socket at all (Fansly) never given the amber mark, so that it means a missing socket, not a platform without one (a Dead-session Fansly Creator still gets red "Disconnected", as on the Creators page).
23. As a chatter, I want the same mark on the Creator's row in "+ Add a Creator", so that a Creator whose tab is closed still shows it where I can find it.
24. As a chatter, I want the tab's tooltip to say "No live connection for 3 min: new messages may arrive late" or "Disconnected", so that hovering explains the dot.
25. As a screen-reader user, I want the tab's accessible name to end with "no live connection" or "disconnected", and the chip's name to read "Unread 12 as of 4 min", so that colour is never the only signal.
26. As a screen-reader user, I want no live-region announcement as ages tick, so that the reader is not interrupted every minute.
27. As an owner with 50 Creators open, I want one timer for the whole tab, not one per badge, and re-renders only for badges whose text changed, so that ticking costs nothing visible.
28. As the owner, I want Phase 3 to make 0 OF calls and add no Caller kind or Cost group, so that D8's budget and the Baseline run are untouched.
29. As a developer, I want the age and mark decisions as pure functions with vitest tables, so that every case above is pinned without a browser.
30. As a reviewer, I want screenshots of a fresh badge, a stale badge, the mark on and the mark cleared, with the snapshot payload that drove each, so that the change is proved on the real path.
31. As the owner, I want proof of no extra OF reads (no `service/` diff, a no-request hook test), so that this Phase needs no post-deploy WATCH line.
32. As a chatter on a quiet Creator (nothing changed for many Cycles), I want no "as of" while the Relay keeps confirming it, so that "unchanged" is never shown as "stale".
33. As a chatter (not the owner), I want a Creator's Dead-session mark to reach my tab even when that Creator is not my current scope, so that chatters and owners see the same dot.

## Implementation Decisions

- **Owns.**
  - `components/chat/dataAge.ts` (new, pure) + `dataAge.test.ts`: the age decision, the mark decision, the
    texts, the server-clock offset.
  - `lib/ageClock.ts` (new): the one shared tick for the tab.
  - `hooks/useDataAge.ts` (new) + `useDataAge.test.tsx`: the I/O shell joining Phase 1's store (P1 C5), Phase 2's
    badge sources, the accounts read and the clock into the pure decisions.
  - `lib/events.ts` (modified, additive): the `ping` listener also records the Relay's clock.
  - `components/chat/FanListFilters.tsx`, `FanList.tsx` (modified): the Unread chip renders the age.
  - `components/chat/CreatorTabs.tsx` (modified): the tab and picker row render the mark.
  - `hooks/useAccountStateEvents.ts` (modified, additive): `session_dead`'s KEYS gain `["chatter", "self",
    "accounts"]` (today only `["accounts"]`, `:46`, while a chatter's roster lives at that key,
    `lib/chatterAccounts.ts:10`, read by `hooks/useAccounts.ts:99-113`), so a chatter's own scope gets the dot.
  - UI proof without opt-in: `scripts/ui-shots.sh` gains four gated shots on fixture-fed `/admin/accounts`
    freshness (Testing Decisions); `docs/ui-shots.md` rows for them.
  - Slop, on the scenario's branch (opt-in): one check and one fault in `slop/lib/all_models_faults.py`, sampled in
    Phase 1's idle phases; no step of its own.
  - `service/`: no change.
- **Interfaces.**
  - `dataAge.ts` exports, all pure:
    - `SLACK_MS = 40_000` (needs-human, see "When a badge is stale"), `DOWN_GRACE_MS = 60_000`.
    - `serverOffset(serverMs, receivedAt): number` (tab clock minus Relay clock).
    - `badgeAge(sources, creators, dead, tabNow, offset): BadgeAge | null`, where
      `BadgeAge = { ageMs, late: number, of: number, text: "as of 4 min", title: string }`.
    - `liveMark(facts | undefined, isDead: boolean, tabNow, offset): LiveMark | null`, where
      `LiveMark = { kind: "down" | "dead", text, title, srText }`.
    - `asOfText(ageMs)`: "as of 2 min", "as of 1 h", "as of 3 d" (whole units, rounded down).
  - `ageClock.ts`: `subscribe(fn)`, `now()` (the tab's time at the last tick, floored to TICK_MS = 15 s so
    `useSyncExternalStore` snapshots are stable between ticks).
  - `useDataAge.ts`: `useUnreadBadgeAge(sources): BadgeAge | null` and `useLiveMark(account): LiveMark | null`. Each is a `useSyncExternalStore` over the clock and the
    stores whose snapshot is the decision's render key, `text + "\n" + title` (a string or null), so React skips
    the render only when nothing shown changed: "1 of 10" → "2 of 10" under an unchanged "as of 4 min" re-renders.
  - `lib/events.ts`: `eventBus.serverOffsetMs(): number | null`, set from each `ping`.
  - `FilterChip` gains `age?: { text, title }`; `CreatorTab` and the picker row gain `mark?: LiveMark`.
- **Schema.** None: nothing persisted, no table, no field on the Relay.
- **Contracts.** Phase 3 consumes and adds none to the wire.
  - From Phase 1, its `### Contract (frozen for Phases 2 and 3)` only ("P1 C<n>"): the store
    `["creator-freshness", principalId]` read through `of(state, aid)` (C5); `at`, `cycle_s`, `live`, `live_since`,
    `now` (C1); `live` "dead" / null / "up" / "down", a no-pump Creator never "down" (C2, C10); both accounts lists
    carry it (C4); a seed without `freshness` evicts (C6); the ping's `fresh` on its own 20 s timer (C7).
    ASSUMPTION until Phase 1 lands; overturned by its code, then the contract section is re-aligned.
  - From Phase 2: `badgeUnread(state, shownCreators, fallbackCount) → { n, fromTotal[], fallback[] }` and
    `unreadBadgeSources(state, ids) → [{ account_id, at }]`. Sources for the age = `fromTotal` Creators with their
    `at`. `fallback` Creators (no held total: today's rule over All-list flags / #881's Unread view,
    `app/lib/chatsCache.ts:236-247`) have no age. Search active (Phase 2 rule 1) → no age.
  - Which `at` ages the badge (decided, rung 1): the source's `at` = max(Last refresh, `unread_total.at`) (P1 C1).
    Every Last refresh is a landed `/users/me`, which confirms the total; the total's own `at` covers confirmations
    outside the Cycle (reconnect auth, routes). Never `creator_warmed.at`: a reused warm republishes it with `at` = now
    and no read (`service/app_open_warm.py:148-160,266-279`).
  - Quiet Creators (story 32): an unchanged total publishes nothing, but Last refresh reaches every tab on each ping
    (P1 C7) even on a busy stream, so the source's `at` stays fresh.
  - Kill switch: Phase 1 off → no `freshness` → the next seed evicts held facts (P1 C6) → no age, no amber dot.
  - From the existing Event stream: `ping`'s `{ts}` (seconds, `service/events.py:638`, `events_wire.py:79-80`,
    every 20 s, `events.py:57-65`), today freshness only, nothing dispatched (`app/lib/events.ts:167-170`).
- **Which clock (decided).**
  - Age = Relay now − `at`, where Relay now = tab now − offset. The offset comes from the latest `ping` (never
    replayed: yielded live, `service/events.py:637-639`) or the latest seed answer's `now` (`/admin/accounts`, an
    HTTP answer), whichever came later; with neither it is 0. Rung 3: the house already moves Relay stamps into the
    tab clock by the Relay's `now` (`mergeRosterCounts`, `useRosterCounts.ts:220-240`; "no `now`: no skew",
    `useRosterCounts.test.ts:149`).
  - An Event stream envelope's `now` (`creator_refreshed`, `creator_warmed`) never moves the offset, ping or no
    ping: replay runs before the first ping (`service/events.py:618-626`) and a replayed event's `now` is as old
    as its send, so it would make old truth look new (story 13).
  - Negative ages (noise) clamp to 0.
- **When a badge is stale (decided).**
  - A Creator counts as late when it has a source `at`, a known `cycle_s` and is no Dead session, and its age is
    over `cycle_s` + SLACK_MS.
  - The current `cycle_s` is used, not the one in force at the read. A tier-up shows the true age until the next
    read (story 8); a tier-down is never early.
  - Slack 40 s = how late a healthy confirmation can reach the tab: ping interval 20 s (`events.py:65`) + Phase 1's
    stated queue wait 10 s (its `refresh_staleness` bound `cycle_s + 10 s`) + an OF read ~10 s (g). Below that a
    healthy quiet Creator shows "as of" for part of every Cycle; at 10 leased Creators the chip, which shows the
    oldest, would read "as of 2 min" most of the time (i).
  - NEEDS-HUMAN: D7 says "older than one cycle", so any slack departs from its letter. Strict (slack 0) honours
    the letter and blinks as above; 40 s honours its intent. Default here: 40 s, one constant, until the owner
    rules. Settles it: the owner's word, or the scenario's measured lateness (`refresh_staleness.max_s − cycle_s`
    plus confirmation delivery) — if that is ≤ 5 s, slack goes to 5 s. A further option for the owner (not taken):
    send the `fresh` ping right after a Cycle lands, not on the 20 s timer, removing the 20 s term (one extra frame
    per Creator-Cycle per tab, ~5/s at 50 Creators and 30 tabs, i); queue wait and read time remain.
  - The badge's age is the oldest late Creator's; `late`/`of` count over its eligible Creators.
  - No source, `at` null, or `cycle_s` null → no age (stories 9, 10).
  - Event stream gap and hidden tab: no special case. The tab simply receives nothing and the age grows. The
    clock ticks at once on `visibilitychange` to visible.
  - Idle mode closes the stream and covers the window (`hooks/useIdleMode.ts:45-51`,
    `components/IdleOverlay.tsx:24-27`); nothing extra.
  - The age shows whatever the count, 0 included (a stale 0 can be wrong too); no age while the badge has no
    number yet (Phase 2's wait) or search is active.
- **Which badges (decided: the Unread total wherever it is shown).**
  - In: the Unread chip, `FanListFilters.tsx:207` (pill `:496-499`), both scopes, over the Fan List's Creator
    set (`FanList.tsx:126`). Rung 2: the plan's "the badge it annotates" is Phase 2's badge.
  - Out: a Creator tab's unread number (`CreatorTabs.tsx:250`), which stays the Roster count (Phase 2 Out of
    Scope), and the platform sum
    (`PlatformSwitcher.tsx:90-95`): the Roster count's `as_of` (`useRosterCounts.ts:33-35`) is a window read
    kept by the Live connection (`ws_kept`, `service/accounts_admin_api.py:405-426`), no Cycle-bound `at`.
  - Out: the bell. Under All Models it sums cached per-Creator counts (`NotificationBell.tsx:413-422`,
    `hooks/useOfNotifCount.ts:85-89`) written by several readers with their own TTLs (each tab's own read,
    `CreatorTabs.tsx:209`; `creator_warmed`), so it has no single `at` today.

  ASSUMPTION: the set is the Unread total's one surface, the chip (rung 2 + r1 evidence above); overturned if the owner
  wants the bell marked. It is then one `badgeAge` call site over Phase 1's `notif_count` Creators (`covers`).
- **Form and wording (decided).**
  - Inline, visible, small: `<span class="text-[10px] text-fg-dim">as of 4 min</span>` after the chip's label;
    the count pill is unchanged.
  - The chip's `title` has the long form; the chip row already scrolls (`CHIP_SCROLLER`), so a few characters fit.
  - Units and rounding follow the house age texts: `fmtAgo` "min / h / d" (`lib/format.ts:102-114`) and
    `updatedAgo`'s whole minutes rounded down (`components/growth/linkMetrics.ts:166-175`), rung 3.
  - Tooltip: "As of 12 min ago: 1 of 10 Creators not refreshed within its Cycle" / one Creator: "As of 4 min ago:
    not refreshed within its 2 min Cycle".
  - ASSUMPTION: inline text over a tooltip-only cue (r2 D7 "show data age"; no chip-age precedent exists, r1 grep
    of `app/` for "as of" / stale indicators); overturned by the owner's screenshot review.
- **The No-live-connection mark (decided).**
  - Where: on the Creator tab's avatar (`CreatorTabs.tsx:246-248`) and the picker row's avatar (`:307-309`).
  - Not on Fan List rows (one dot per row at 50 Creators is noise; YAGNI), not in OF Manager (another screen; it
    already shows "Disconnected", `CreatorColumn.tsx:420-429`).
  - Form: the house status dot (`components/ui/infloww.tsx:561-569`, `CreatorColumn.tsx:420-423`): 6 px, ringed in
    the tab background, at the avatar's foot. `bg-warn` for down, `bg-err` for dead (tokens `app/globals.css:50-52`).
    It is shown only when on: tabs get no green dot.
  - States:
    - dead: with a Phase 1 snapshot whose `live` is not null, `live` "dead"; otherwise (no snapshot, or
      `live` null: Fansly) `account.session_dead_at`. At once, no grace, label from `sessionConnectivity`
      (reused, not copied; rung 3).
      Why the snapshot first (r1): `session_dead` is not any-scope, so a tab scoped `model:A` never gets B's
      (`service/events_decide.py:289-294,342-374`; Messages Pro scopes to the picked tab, `CreatorTabs.tsx:99`),
      while `creator_refreshed` is any-scope (P1 C3). Phase 1's `live_of` takes the same dead map, so the
      two agree, and a re-capture clears red within Phase 1's 5 s sample, not on the next accounts refetch
      (owner 60 s, chatter 5 min staleTime, `hooks/useAccounts.ts:68,90`).
      Without Phase 1: the accounts read, refreshed by `session_dead` for the current scope only (KEYS fix in
      Owns); an off-scope Creator's red waits for the next accounts refetch (accepted; no `service/` change).
    - down: `live` "down" and Relay now − `live_since` ≥ DOWN_GRACE_MS (never for `live` null).
    - else none.
  - ASSUMPTION: grace 60 s (i). The pump retries at 1, 2, 4, 8, 16, 30 s (`service/of_ws_decide.py:51-53`), so a
    routine reconnect is back within ~31 s of retries, and 60 s is the pump's own "really worked" bar (RESET_AFTER_S).
    Overturned if Phase 1 or the sweep shows routine reconnects over 60 s.
  - Clears: `live` "up", or dead no longer true. At once, no grace on clearing.
  - Wording: "No live connection" (plan, glossary); title "No live connection for 3 min: new messages may arrive
    late"; dead: "Disconnected". The sr-only text sits in the tab button, as `UnreadMiniBadge` does
    (`UnreadMiniBadge.tsx:19-29`).
  - No aria-live.
- **Ticking (decided).**
  - One module clock (`ageClock`): one `setInterval` of TICK_MS = 15 s (rung 3: `IDLE_CHECK_MS`,
    `useIdleMode.ts:24`). It runs only while it has a subscriber and the document is visible.
  - Each hook's snapshot is its decision's render key (text + title), so a tick re-renders only badges whose shown
    text or tooltip changed. Age texts change at most once a minute, marks rarely.
  - At 50 Creators: 51 snapshot calls per tick and ≤ 1 re-render a minute in steady state (i).
  - Not the per-component interval pattern (one `setInterval` per row), which would be 50 timers.
- **Reducer rule (CLAUDE.md).** No component gains coupled `useState`: the facts live in Phase 1's store and
  Phase 2's sources, the clock and offset in module singletons (house precedent: `eventBus`, `lib/events.ts:264`).
  So the rule is met with pure decide functions and tables, not a reducer.

  ASSUMPTION: no reducer is needed (r2 reading: the rule binds ≥ 2 coupled `useState`s); overturned if the
  implementation needs component state, which then goes in a reducer in `dataAge.ts`.
- **Flags and reversibility.** No new Knob. Everything derives from Phase 1's and Phase 2's data: their Knobs off
  give no snapshot / no held total, so no age and no amber dot (Contracts, kill switch). Only the Dead-session dot
  remains, from data the tab already has. Revert = revert the PR (rung 4: additive UI, no state).
- **OF-call budget.** 0 OF calls, no Caller kind, no Cost group: P1 C12's "data age, No-live-connection mark" row
  (i). Asserted by `hooks/useDataAge.test.tsx` › "makes no request" and by no `service/` diff (Acceptance). No WATCH
  line: the sweep's thresholds (+25 % and ≥ 5/h, `of_calls.py:34,607`) cannot prove 0.

## Testing Decisions

- **Seams (two, both existing; the rendered app reached two ways).**
  1. The pure module `components/chat/dataAge.ts` (`badgeAge`, `liveMark`, `asOfText`, `serverOffset`) with
     vitest tables. Almost every story is a row here.
  2. The rendered app: `scripts/ui-shots.sh` (throwaway loopback stack, temp DB, off-host requests refused,
     `scripts/ui-shots.sh:1-16`) with fixture-fed snapshots: same app code, fixed facts, no opt-in. On the real
     Relay, opt-in only: one check in Phase 1's idle phases (Slop, below).
  - Thin hook/component tests only where the pure seam cannot see: one clock, re-render count, no fetch, DOM text.
- **`dataAge.test.ts` (tables).** (SLACK 40 s.)
  - Age: no source → null; `cycle_s` null → null; `at` null → null; no snapshot at all (Knob off) → null.
  - Lease 120 s: age 160 s → fresh; 160.001 s → "as of 2 min". Tab 600 s: 640 s → fresh; 11 min → "as of 11 min".
  - Tier-up 600 → 120 at age 8 min → "as of 8 min"; tier-down 120 → 600 at 5 min → fresh.
  - Which `at`: only the source's `at` counts; a `creator_warmed.at` of now beside a 5 min old source (lease) →
    "as of 5 min".
  - Quiet Creator: source `at` advanced by a ping with `n` unchanged → fresh (story 32).
  - Independent signals: `live` "down" past grace + `at` fresh → mark, no age; `live` "up" + `at` late → age, no mark.
  - `fallback` Creator (no held total) → no age; search active → no age; count 0 and late → age shown.
  - Tab clock +5 min with ping offset → same verdicts as no skew; no ping, seed `now` → same; neither → tab clock.
  - Replayed event envelope `now` (before or after a ping) → offset unchanged; only seed `now` and pings move it.
  - Negative age → 0, fresh.
  - Dead Creator excluded. 10 Creators with 1 late → `late 1, of 10`, its age; 2 late → the oldest.
  - Texts: 150 s → "as of 2 min"; 59 min 59 s → "as of 59 min"; 60 min → "as of 1 h"; 25 h → "as of 1 d"; title
    whole minutes ("As of 119 min ago" for 119 min).
  - Mark: up → null; down 59.9 s → null; 60 s → down; down then up → null.
  - Mark: flap seen by the Relay (down 5 s, up, down 5 s, `live_since` reset) → null; flap unseen (one `live_since`
    55 s ago) → down at 60 s (story 18); no `live_since` → since first seen.
  - Mark: live "dead" → dead at once; snapshot `live` "up" + stale `session_dead_at` → none (snapshot wins:
    re-capture); no snapshot + `session_dead_at` → dead; Fansly (`live` null) + `session_dead_at` → dead, never down.
  - Mark: live null → null; no snapshot and not dead → null; restart wave (all down, since = boot) → null for 60 s.
  - Prior art: `app/components/chat/fanDrawerForm.test.ts` (the house table template),
    `useRosterCounts.test.ts:134-149` (skew table), `components/stats/IngestHealthBanner.test.ts:37-56` (`relTime`
    table), `lib/format.test.ts` (`fmtAgo`), `lib/chatsCache.test.ts` (`badgeUnreadView` age).
- **`useDataAge.test.tsx`.**
  - "one timer": 50 hooks mounted → 1 interval.
  - "re-renders only on change": 4 ticks with unchanged texts → 0 re-renders; one Creator turns late → only its
    subscriber re-renders; a second Creator turns late under an unchanged "as of 4 min" → the chip re-renders
    ("2 of 10" in its title).
  - "hidden tab": no interval while hidden; `visibilitychange` → an immediate tick.
  - "idle return": `eventBus` paused then resumed with a late `at` → age shown at once, gone on the next
    confirmation (story 15).
  - "kill switch": a seed without `freshness` after one with it → no age, no amber dot.
  - "makes no request": fetch stubbed (as `CreatorTabs.test.tsx:330-334`). 50 Creators, 10 ticks, a ping and a
    visibility return → fetch called 0 times and the query cache gains no query.
- **Component tests (existing files).**
  - `FanListFilters.test.tsx`: with `age` → "Unread", the count and "as of 4 min" in the button's name, title
    as given, no `aria-live` on the chip or its ancestors (story 26); without → today's DOM.
  - `FanList.test.tsx`: single-Creator scope with a late source → the chip carries the age (story 5).
  - `CreatorTabs.test.tsx`: down past grace → dot, title suffix, sr text "no live connection"; dead → "disconnected",
    from `sessionConnectivity`; up → no dot; picker row likewise; the unread number → today's DOM.
  - `useAccountStateEvents.test.tsx`: `session_dead` invalidates `["chatter", "self", "accounts"]` too.
  - `lib/events.test.ts`: a `ping` frame sets `serverOffsetMs`.
- **UI shots, no opt-in (`scripts/ui-shots.sh`, gated like its other shots).** Fixture `/admin/accounts` answers
  with `freshness` (+ `unread_total`) per Creator and `now`, served by the harness's fixture router as it already
  serves `/admin/accounts/roster-counts` (`docs/ui-shots.md:121-127`):
  - `data-age-fresh` (trigger): all `at` fresh → chip without "as of", no dot.
  - `data-age-stale` (settled): one Creator's `unread_total.at` 5 min old → chip "as of 5 min", title "1 of N".
  - `live-mark-on`: one Creator `live` "down" for 3 min → amber dot, tab title "No live connection for 3 min…".
  - `live-mark-dead`: one Creator `live` "dead" → red dot, "Disconnected".
  - Side-effect check: the report JSON records the fixture payload each shot was fed beside the DOM text it gated.
  - ASSUMPTION: the harness can fixture `/admin/accounts` like its other local reads; overturned if not, then
    `scripts/demo-shots/fixtures.py` (already answers `/admin/*` reads, `scripts/demo-shots/README.md:43`) is used.
- **Slop (scenario `2026-11-20-all-models-shared-inbox`, opt-in; the Phase's slice gets 1 green + 1 `--break`).**
  No step of its own (+0 s runtime). Check `QUIET_NOT_STALE` ("a Creator read within its Cycle shows no 'as of' in
  any tab"): tab A's Unread chip sampled every 5 s across Phase 1's `idle` and `idle_one_tab` (240 s at the 60 s
  floor; stale = over ~100 s). New metric `data_age.quiet_stale_samples`: null → 0. Fault `fresh-ping-off` (the ping
  carries no `fresh`) turns it red: the confirmation path, the one cross-Phase seam the tables cannot see. The
  mark's live drop / recover is proven by the ui-shots on fixtures and Phase 1's `live_of` table, not slop.
  Precondition: the scenario's shared env (P1 C11) with `UNREAD_TOTAL=1`.

## Acceptance

```sh
# pure decisions, hooks, components (iterating)
cd app && pnpm exec vitest related --run components/chat/dataAge.ts lib/ageClock.ts hooks/useDataAge.ts lib/events.ts components/chat/FanListFilters.tsx components/chat/FanList.tsx components/chat/CreatorTabs.tsx
cd app && pnpm exec vitest run components/chat/dataAge.test.ts hooks/useDataAge.test.tsx components/chat/FanListFilters.test.tsx components/chat/FanList.test.tsx components/chat/CreatorTabs.test.tsx hooks/useAccountStateEvents.test.tsx lib/events.test.ts
# the new checks and fault register cleanly (slop/lib pytest suite)
venv/bin/python scripts/run_tests_parallel.py --pytest slop/lib -j 8
# before PR: the whole suite
scripts/run-tests.sh
# no service/ change in this Phase
test -z "$(git diff --name-only origin/main...HEAD -- service/)"
# manual: owner opt-in only (CLAUDE.md): scenario 2026-11-20-all-models-shared-inbox --scale=small green with QUIET_NOT_STALE; then --break --fault=fresh-ping-off --baseline=<green run> reports CAUGHT on QUIET_NOT_STALE
# UI proof without opt-in (throwaway loopback stack, nothing leaves the machine): exit 0, the report holds data-age-fresh, data-age-stale, live-mark-on, live-mark-dead with their fixture payloads
scripts/ui-shots.sh
```

## Depends on

- **Phase 1 (Shared refresher):** must land first. P1 C1–C7, C10, C11 (the scenario's lease Knob), C12. Only the
  No-live-connection mark needs nothing but `live` (C2), so it can ship right after Phase 1's first slice.
- **Phase 2 (Unread total):** must land first for the age: `badgeUnread`'s `fromTotal` / `fallback` split and
  `unreadBadgeSources`.
- **In flight, netted:**
  - `fix/bg-lane-money-deadlock` ships the scenario, `all_models_wire.py` and `all_models_faults.py` (today only
    `warm-ignores-reuse`, seen in the study worktree). Phase 3's check and fault are added on top after it
    merges, and count as proof only on a run whose existing checks and the relay Traceback invariant are green
    (both study runs were red on it, `STUDY-REPORT.md` §1, §6). ASSUMPTION: its file shapes stay as seen.
  - `fix/all-models-open-cost`: no dependency. `creator_warmed.now` is already on main
    (`service/app_open_warm.py:156-159`); this Phase's offset comes from the seed and pings.
  - `fix/reply-reaches-other-chatters` touches `chatsCache.ts` / `useInboxRealtime.ts`; no overlap with the files
    this Phase owns.
- PR #881 (merged): `badgeUnreadView`'s live Unread list, which Phase 2 keeps for `fallback` Creators (no age).

## Out of Scope

- The bell's age, and "as of" on the tab's Roster-count fallback number and the platform sum. None has a
  Cycle-bound Relay-confirmed `at` (Implementation Decisions); the bell is one call site later.
- An age on a Creator tab's unread number: it stays the Roster count (Phase 2 Out of Scope), no Cycle-bound `at`.
- A live slop step for the mark (socket drop, failing reads, recovery, flap) and its fault: over the 15 min cap with
  Phases 1–2 (≈ +400 s, i); the pure table and the ui-shots carry it.
- A post-deploy WATCH line: 0 OF calls, which the sweep cannot prove.
- An age or mark on Fan List rows: noise at 50 Creators; the tab and picker carry the mark.
- OF Manager's creator column: another screen, already shows "Disconnected".
- A tab-level "Event stream reconnecting" pill (`lib/events.ts:163-164` invites one; none exists): not in D7; the
  age already grows during a gap.
- A green "live" dot on healthy tabs: adds 50 dots for no information.
- Any Relay change (a `due_at` field, Relay-side debounce of flaps): the client rule suffices; Phase 1 may
  coalesce flaps on its own.
- The WS counter frame (Q1): parked. If it later moves the Unread total's `at`, this Phase reads it unchanged.
- A Knob for slack, grace or tick: constants in one module; YAGNI until the owner asks.
- An ADR: no hard-to-reverse decision here (pure client rules, additive UI).

## Further Notes

- The age rule reads Phase 2's per-value `at`, not Last refresh, so a later frame-driven total (Q1) ages
  correctly with no change here.
- A Creator whose Event stream holder left (no Open-tab Creator anymore) stops being refreshed (D1). Only a tab
  that cannot receive events could see it, and its age grows truthfully until its stream returns.
- After a Relay restart every `at` is null and every `live` down at boot. Nothing shows for up to the grace or
  the first read: unknown is not stale (stories 10, 17).

ASSUMPTION: no Phase 3 flag; Phase 1's / Phase 2's Knobs off remove the snapshot / held total and with them the age
and amber dot (rung 4/5); overturned if the owner wants the Dead-session dot behind a flag too.

ASSUMPTION: the "as of" text floors to whole units (rung 3, `updatedAgo`), so it understates by under one unit
(up to 59 min at "1 h"); the title gives whole minutes. Overturned if the owner prefers rounding up.

## Review

codex · 2026-11-20 · call 1 blind (B1-B10), call 2 on the draft (D1-D18). Every finding re-checked in the repo.
Totals: accept 20 · partial 6 · reject 1 · needs-human 1.

- B1 age and connection need independent signals — **partial**: already separate (age from Phase 2's `at`, mark
  from `live`); added the two cross rows to the table.
- B2 `creator_warmed.at` cannot certify the total — **accept**: confirmed, a reused warm republishes with `at` = now
  and no read (`service/app_open_warm.py:148-160,275-277`). Contracts: "Which `at` ages the badge" = `unread_total.at`.
- B3 equal-value confirmations / cold seed — **accept**: Contracts "Confirmations (REQUIRED)" + Depends on (1).
- B4 define "live" at the socket — **partial**: boundary = auth frame sent (rung 3, `of_ws.py:169,181`), OF ack
  rejected (no reader trusts it today); no-pump Creator must not read "down" (added).
- B5 surfaces, zero, pending, search — **accept**: tab's unread number added; age shows at 0; none while pending
  or searching ("When a badge is stale", "Which badges").
- B6 Dead-session delivery gaps — **accept**: confirmed `session_dead` not any-scope (`events_decide.py:289-294`)
  and KEYS miss the chatter roster (`useAccountStateEvents.ts:46`, `chatterAccounts.ts:10`). Dead now from the
  any-scope snapshot first; KEYS fix owned; off-scope gap without Phase 1 stated.
- B7 expiry and recovery without traffic — **partial**: local tick already decided; 429 keeps `at` (Phase 2 draft
  (c)); monotonic `at` is Phase 1's reducer. Added the idle-return hook test.
- B8 seam: two tabs + ungranted control, zero increment — **partial**: per-kind rate for Y accepted (OF-call
  budget); ungranted control rejected: grant routing is Phase 1's (`creator_refreshed` clamp), not this Phase.
- B9 scenario not green, not on main — **accept**: Depends on: proof only on a green run (`STUDY-REPORT.md` §1, §6).
- B10 falsify with an independent oracle — **partial**: reused-warm row and `QUIET_NOT_STALE` added; out-of-band
  total change is Phase 2's parity metric; a user-comprehension study rejected (owner judges UI, screenshot review).
- D1 30 s slack overrides D7 — **needs-human**: D7's letter is "older than one cycle". Evidence for a slack:
  confirmations ride a 20 s ping (`events.py:65`) after Phase 1's ≤ 10 s queue wait, so strict 0 blinks "as of"
  on healthy Creators (i). Default now 40 s, derived, one constant. Settles it: owner's word, or the scenario's
  measured `refresh_staleness.max_s − cycle_s` plus delivery.
- D2 unchanged totals stale forever — **accept**: Phase 1 draft heartbeat carries Last refresh only, Phase 2
  publishes on change; Contracts now REQUIRE option (a) or (b); story 32, table row, `QUIET_NOT_STALE`.
- D3 wrong Phase 2 interface — **accept**: mapped onto `badgeUnread` `fromTotal` / `fallback`, search → no age,
  `provisional` ignored (ASSUMPTION).
- D4 acceptance passes with the wrong clock — **accept**: table row (Last refresh fresh, `unread_total.at` old →
  stale), snapshot metric records `unread_total.at`, recovery measured from fault clear. Client wiring has no
  Relay fault; the table pins it.
- D5 kill-switch contract — **accept**: Phase 1 off = no snapshot (draft "Knobs"); rule "no snapshot → no age, no
  amber"; eviction on a seed without `freshness` REQUIRED; hook test added.
- D6 text-only key freezes the tooltip — **accept**: render key = text + title; test row "1 of 10" → "2 of 10".
- D7 budget checks pass with extra calls — **accept**: confirmed thresholds (`of_calls.py:34,607`). Per-kind Y rate
  vs idle; WATCH line labelled coarse.
- D8 flap missed between 5 s samples — **partial**: true (Phase 1 draft tick 5 s); story 18 redefined (an unseen
  "up" is one outage, truthfully), table rows added; no client debounce (it cannot see what the Relay missed).
- D9 earlier phase closes B and C — **accept**: precondition reopens tabs.
- D10 fault window too short — **accept**: hold 150 s, thresholds recomputed (stale ≤ 120 s, cleared ≤ 70 s
  from clear), runtime ≈ 940 s (i) under 15 min.
- D11 ping not every 20 s — **accept**: confirmed `last_beat` reset per frame (`events.py:637-641,655`) and replay
  before the loop (`:618-626`). Offset: seed `now` or ping only, never envelopes; confirmation timer REQUIRED.
- D12 recapture and Fansly — **accept**: snapshot `live` wins when not null; Fansly gets red only; rows added;
  story 22 clarified.
- D13 tab blue badge uses the same total — **accept**: Phase 2 draft makes it the held total; added to "Which badges"
  (story 33). Roster-count fallback and platform sum stay out.
- D14 stories without a seam test — **accept**: single-Creator scope (`FanList.test.tsx`), idle return, no
  `aria-live` added.
- D15 UI proof waived on a false premise — **accept**: `scripts/ui-shots.sh` is a throwaway guarded loopback stack
  (`scripts/ui-shots.sh:1-16`); four fixture-fed shots + payloads in Acceptance, no opt-in needed.
- D16 picker is unrequested scope — **reject**: every accessible Creator is an Open-tab Creator (`CONTEXT.md:400-401`),
  so closed-tab Creators are refreshed and counted; the picker row is their only per-Creator place in Messages Pro.
- D17 "upper bound" is false — **accept**: story 3 reworded; flooring stated (up to 59 min at "1 h"), title in minutes.
- D18 `fix/all-models-open-cost` false dependency — **accept**: removed; `now` is on main (`app_open_warm.py:156-159`).

### Six hats (2026-11-20)

Report `/tmp/wcr/sixhats.md`; lines for the bullets touching this spec (tally: `plan-review.md` "Six hats").
Supersedes codex D13 (tab number) and D10's runtime above.

- 1 **accept** — no change: P1 C1 carries every field this Phase reads; Contracts cite it.
- 4 **accept** — three stale claims about Phase 1/2 drafts (warm reads no `/users/me`, `/admin/accounts` only, the
  tab's blue number as Unread total). Contracts now cite P1 C<n> and Phase 2's selectors only.
- 8 **accept** — age from max(Last refresh, `unread_total.at`), no `unread_at` in the ping, zero wire change
  ("Which `at`").
- 13 **accept** — eviction (P1 C6) and a no-pump Creator never "down" (P1 C2, C10) are now in Phase 1; this Phase
  cites them, mark table rows kept.
- 18 **accept** — the live mark step (≈ +400 s) cut; one check `QUIET_NOT_STALE` in Phase 1's idle phases (+0 s),
  one fault `fresh-ping-off`; set ≈ 726–843 s (i).
- 21 **accept** — no change: 0 OF calls, any-scope dead mark, UI proof via `ui-shots.sh`.
- 24 **partial** — `provisional` cut in Phase 2, so the rule ignoring it is gone; the Knob cuts are Phases 1/2's.
- 25 **accept** — this Phase's WATCH line dropped (0 calls, the sweep cannot prove 0).
- 26 **accept** — slop step cut to one opt-in check (no step of its own); tab-number age cut (story 33 deleted, Out
  of Scope).
- 30 **partial** — "ping right after a Cycle lands" listed as the owner's further option (When a badge is stale),
  not taken: ~5 frames/s at 50 Creators × 30 tabs (i). Slack stays 40 s, needs-human.
