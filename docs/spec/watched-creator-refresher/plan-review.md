# Plan review: watched-Creator refresher (Phases 1–3)

2026-11-20 · design only · inputs: `.scratch/watched-creator-refresher/goal.md` (D1–D10, Q1), the three specs, codex
adversary (each spec's `## Review`), six-hats report (31 bullets, set-wide). Labels: m measured, i inferred, g guess.
Seams between Phases: Phase 1's `### Contract (frozen for Phases 2 and 3)` only ("P1 C<n>").

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 1 Shared refresher | `phase-01-shared-refresher.md` | proof: `fix/bg-lane-money-deadlock` (scenario); Netting slice only: `fix/all-models-open-cost` |
| 2 | 2 Unread total on first paint | `phase-02-unread-total-first-paint.md` | P1 C1, C3–C9, C11, C12 |
| 2 | 3 No-live-connection mark | `phase-03-data-age-live-connection-mark.md` | P1 C2 (`live`) only; can ship right after slice 1 |
| 3 | 3 Data age | `phase-03-data-age-live-connection-mark.md` | P1 C1–C7, C10–C12; Phase 2's `badgeUnread` / `unreadBadgeSources` |

### Recommended build order (tracer first)

One PR per slice; stories split along it (P1/P2/P3 story numbers). OF Δ = calls/min at 50 Creators, group
`shared_refresher` unless noted. Slop per slice = owner opt-in (CLAUDE.md), 1 green + 1 `--break`, each < 15 min
(scenario ≈ 726–843 s with all slices, i).

| # | Slice | Stories | OF Δ at 50 | Proof |
|---|---|---|---|---|
| 1 | Tracer: P1 core (Open-tab set, tiers + floor, single-flight on the warm gate, `/users/me` only, Last refresh, `creator_refreshed`, accounts-row seed, `fresh` ping, eviction, Caller kind + Watch check + re-pin runbook) + P2 basic badge (observer, slot, selectors, known-prior `dm_in` / `read_flip`) | P1 1–21, 27–29, 32–38, 40–43, 45–51; P2 1, 2, 5, 7–13, 15, 16 + 18 (known prior), 19, 23–26, 32, 33 | +9.5 (i) | decide + reducer tables; green `REFRESHER_FLAT_IN_N`, `REFRESH_WITHIN_CYCLE`, `REFRESHER_STOPS_WITHOUT_TABS`, `FRESH_BADGE_TRUE`; `--break --fault=refresher-per-subscriber` CAUGHT |
| 2 | P3 No-live-connection mark (amber / red dot, picker row, any-scope dead) | P3 16–24, 25 + 29 + 30 (mark part), 28, 31, 33 | 0 | `dataAge.test.ts` mark rows; ui-shots `live-mark-on`, `live-mark-dead` + fixture payloads; no slop |
| 3 | Netting (after the sibling merges) | P1 22–25 | ≤ 0 (i): later opens' warm reads → ~0 within a Cycle (AE `walk:app_open_warm` 67.4/h, m) | `test_shared_refresher_netting.py`; green `OPEN_AFTER_CYCLE_REUSED`; `--break --fault=warm-ignores-reuse` (sibling's fault, i) |
| 4 | Row clears: window hook + `window_due` on socket gap, P2 window diff, drift slack, priors, mark-all, list drops | P1 30, 31; P2 3, 4, 6, 16–18 (rest), 20–22, 27, 28 | +2.6 (g) → total 12.1 | P2 decide tables; green `READ_ON_OF_CLEARS`, `unread_parity.mismatches` 0; `--break --fault=unread-total-frozen` CAUGHT |
| 5 | P3 data age ("as of" on the chip) | P3 1–15, 25–27, 29, 30, 32; P2 14 | 0 | age tables, `useDataAge.test.tsx` "makes no request"; ui-shots `data-age-fresh` / `data-age-stale`; optional green `QUIET_NOT_STALE` + `--break --fault=fresh-ping-off` |
| 6 | Bell `SHARED_REFRESHER_BELL=me` (after the owner's bell-pair check) | P1 26, 39, 44, 52 | 0 (same read; nets tabs' count polls, AE 15.8/h, m) | hook tests (`useOfNotifCount`, `ofReadGate` covered → once); owner bell-pair check |
| — | Parked | P2 29–31 (checks C, A/B, Step B log) | 0 | needs the human |

## Budget

The set's one table is P1 C12. Default Knobs, gross attempts, `walk:shared_refresher`:

| Creators | 10 | 30 | 50 |
|---|---|---|---|
| Total default (g) | 5.9 | 9.0 | 12.1 |
| D8 envelope (~14 at 50, scaled by mix) | 7.8 | 10.9 | 14 |
| Ceiling: window read every Cycle (i) | 21 | 30 | 38 |
| Watch trip `shared_refresher_budget` (calls/h, 1.25 × envelope, i) | ~580 | ~820 | ~1,050 |

- Rows at 50: `/users/me` 9.5 (i, mix g) · socket-gap window reads 1.3 (g) · drift window reads 1.3 (g) · Phase 3 0.
- Per day at 50: 17.4k around the clock, ~11.6k at 16 h (g), inside D8's 13k–20k. AE today (19 Creators): ~+430/h (g).
- Not default, each priced: bell `me` +0; lease cycle 60 s +5.3; lease-tier `/count` (not built) +5.3; desktop
  notifier as watching +5.3 around the clock (needs-human). All-leased worst case 26.3.
- One WATCH `of_calls_vs_baseline` line for the set (P1's), meaningful once the re-pin pins (~28 h). P2 adds one
  drift condition to `shared_refresher_budget`; P3 none (0 calls).

## Adversary

- P1: codex, 2 calls · accept 21 · partial 8 · reject 1 · needs-human 1 (D17 desktop notifier). Superseded by six
  hats: 2-read default, 3 faults, ~1,620/h Watch bound.
- P2: codex, 2 calls · accept 24 · partial 5 · reject 1 · needs-human 1 (rows below page 0). Superseded: R1–R7,
  `unread_totals_on`, `provisional`, the second store, no-old-window events on every read.
- P3: codex, 2 calls · accept 20 · partial 6 · reject 1 · needs-human 1 (40 s slack vs D7). Superseded: D13 (tab
  number), D10 runtime 940 s, the live slop step.

## Six hats

24 accept · 7 partial · 0 reject. Per-spec lines under each spec's `### Six hats (2026-11-20)`.

1. **accept** (P3) — no change; P1 C1 carries every field P3 reads.
2. **accept** (P1, P2) — check C, bell pair, drift rate, leased mix stay open, labelled g; bell pair → 0-call owner check.
3. **accept** (P1) — open-cost sibling gates only the Netting slice (stories 22–25).
4. **accept** (P2, P3) — draft-to-draft citations removed; both cite P1 C<n> only.
5. **accept** (set) — seams frozen in one Contract; set 1,608 → ~1,570 lines with this round's Review lines added.
6. **partial** (P2) — `provisional`, `source`, slot `boot`/`seq`, echo event cut; adjustment table kept (D6 push).
7. **accept** (P1) — one set budget table, P1 C12.
8. **accept** (P2, P3) — R7 / `unread_at` dropped; age from max(Last refresh, slot `at`), zero wire change.
9. **accept** (P1, P2) — `changed` compares a slot without its `at` (C3).
10. **accept** (P1, P2) — one tab store, `(boot, seq)` on the envelope (C1, C5); P2 = selectors.
11. **accept** (P1, P2) — no body hand-off; one window-reader hook (C8, C9); raw `chat_messages_count` dropped.
12. **accept** (P2) — on-signal = slot key present (`totalsOn`).
13. **accept** (P1, P3) — eviction (C6); no-pump never "down" (C2, C10).
14. **accept** (P1, P2) — `note_values` via `call_soon_threadsafe`; contributor `threading.Lock` (C8).
15. **accept** (P1, P2) — default 1 read: 12.1/min at 50 (g); Watch bound from D8 × 1.25.
16. **accept** (P2) — unknown-prior slack + down-only reads remove the every-Cycle drift trigger.
17. **partial** (P2) — list drops only on flip / downward drift; no-old-window events only on drift reads; tab
    re-reads priced outside the group (g); ≤ 25 events on a drift read accepted.
18. **accept** (P1, P2, P3) — one fault per slice; P3 live step cut; ≈ 726–843 s (i).
19. **accept** (P1) — no change; ≤ 30 open total now on `open_after_cycle`.
20. **accept** (set) — no change; every Knob off = today, nothing persisted.
21. **accept** (P3) — no change.
22. **partial** (P1) — per-tier reads and `covers` on held `notif_count` taken; `/count` not read by default (14.0
    leaves no room for window reads the study's 14 included); bell via `me` Knob.
23. **partial** (P2) — down-only window reads taken; unknown-prior DM stays +1 with slack (no 10 min lag on new chats).
24. **partial** (P1, P2, P3) — `UNREAD_TOTAL_SOURCE`, `ws_counter`, `provisional`, bell-pair log cut;
    `BELL_FROM_ME` → `SHARED_REFRESHER_BELL` kept (only in-budget bell path). 5 Knobs.
25. **accept** (P1, P2, P3) — one `shared_refresher_budget` check (D8-derived) + one `of_calls_vs_baseline` line.
26. **accept** (P1, P3) — one P1 fault; P3 slop = one opt-in check; tab-number age cut.
27. **accept** (set) — tracer-first order above; stories split along it.
28. **accept** (P1) — desktop notifier stays excluded, needs-human (+5.3/min at 50 around the clock, i).
29. **accept** (P2) — rows below page 0 stay needs-human, default page 0 only.
30. **partial** (P3) — ping-after-Cycle listed as an owner option, not taken (~5 frames/s, i); slack 40 s stays.
31. **partial** (P2) — Q1 stays parked; check C recommended before code (Needs the human), but code may proceed
    behind default-off Knobs; C still gates `UNREAD_TOTAL=1`.

## Cut (YAGNI)

- The default `/users/notifications/count` read (2 reads/Cycle, 18/min at 50) and the bell-pair Relay log.
- WS counter source: `UNREAD_TOTAL_SOURCE`, `source: "ws_counter"`, its stories (Q1 parked).
- `provisional`, the echo event, slot `boot`/`seq`, `unread_totals_on`, `unread_at` in the ping, the second store
  `["unread-totals"]`.
- `on_users_me` / `on_window`, raw `values.chat_messages_count`, the "never read since boot" window trigger, upward-
  drift window reads.
- P1's 2 extra faults (never-due, no-netting → tables); P3's live mark slop step + fault; P3's and P2's own WATCH
  lines and P2's own drift check.
- P3's tab-number age and `useCreatorUnreadAge`.

## Not yet specified

- Lease-tier `/count` read (priced, not built); bell `me` waits on the owner's check.
- WS counter as Unread total source (after checks A/B); Step B's log line ticket (P2 story 31).
- Clearing rows below page 0 after a read on OF web.
- Age on the bell, the tab's Roster-count number, the platform sum.
- Inbox bundle as first-paint carrier (only if P1 C4's ASSUMPTION fails).
- Desktop notifier as watching (if the owner says yes).
- Baseline re-pin execution and AE switch-on (human, after deploy; runbook in P1 Acceptance).

## Open questions

ASSUMPTIONs, sharpest first. Each spec carries its overturn clause.

Source semantics
1. P2: `chatMessagesCount` counts unread chats (incl. muted) and drops on an OF web read (g; check C).
2. P1: `notificationsCount` = `/count` `all` (g; bell-pair check, gates `BELL=me`).
3. P1 C7: D5 "publish only on change" = no event for an unchanged Cycle; confirmations ride the ping (rung 2).
4. P1 C12: leased mix L = min(C, 10) behind every budget cell (g).
5. P1 C12: socket-gap and drift rates ~0.5/h per Creator (g; Watch measures).
6. P2: a reply into an unread chat makes it read on OF (rung 3).
7. P2: unknown-prior DM counts +1 with one unit of slack (rung 5).
8. P2: badge may exceed painted rows / differ from the tab's Roster count until reload (ADR-0043 cost).
9. P2: the Relay computes no chats count of its own; OF's counter taken as is (rung 5).

Contract and wiring
10. P1 C4: the accounts lists are the first-paint carrier (rung 3).
11. P1 C7: a change between accounts answer and first stream connect waits for the next change (rung 5).
12. P1: Open-tab counts only app-tab streams; desktop excluded (rung 4; needs-human).
13. P1: Fansly tracked with `live` null, never read (rung 5).
14. P2: drift window reads in P1's Caller kind / Cost group (rung 2).
15. P1 C12: the warm's `/users/me` nets ≈ 0 in `walk:app_open_warm` (rung 5).
16. P2: single-Creator scope follows the same rules (rung 5).

Constants
17. P1: `SPREAD` 0.1, tick 5 s, job deadline 30 s, purchases-poll ladder for the 429 hold (g / rung 3).
18. P1: Watch trip 1.25 × D8 envelope (rung 3; mix g).
19. P3: down grace 60 s (i); "as of" floors to whole units (rung 3).
20. P3: chip is the Unread total's one surface; inline text over tooltip; no reducer; no Phase 3 flag.

Siblings and proof
21. Siblings keep the cited interfaces (`reuse_decision`, scenario file shapes) (rung 1 on worktrees).
22. The scenario may be extended (phases, metrics, coined check / fault names) rather than frozen (rung 5).
23. ui-shots can fixture `/admin/accounts` (else `scripts/demo-shots/fixtures.py`).
24. P2 scenario: Y leased in all three tabs (g).
25. P2: the fresh-session symptom is mostly stale Relay windows, not IndexedDB (g; both removed anyway).

## Needs the human

- **Check C** (owner's OF web, ~5 min, 0 Relay calls): Unread-tab number = rows, drops by 1 on a read. Recommended
  before any P1/P2 code (it decides whether `/users/me` is worth reading); code may proceed behind default-off Knobs;
  gates `UNREAD_TOTAL=1`.
- **Bell-pair check** (owner's devtools, 0 Relay calls): gates `SHARED_REFRESHER_BELL=me` (slice 6).
- **Desktop notifier as watching** (P1 D17): default excluded; including costs +5.3/min at 50 around the clock (i).
- **Rows below page 0** on a read on OF web (P2): default page 0 only; the badge still drops.
- **Age slack 40 s vs D7's "older than one cycle"** (P3): default 40 s; option ping-after-Cycle (~5 frames/s, i).
- **Q1 checks A/B on AE** (P2, parked): polling stays the default; nothing waits on them.
- **Slop opt-in per slice** (CLAUDE.md): 1 green + 1 `--break` each, < 15 min; no answer = no slop.
- **AE switch-on + Baseline re-pin** after deploy (P1 Acceptance runbook); ship no other OF-call change for ~28 h.
