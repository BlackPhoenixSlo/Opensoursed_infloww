# Phase 02 — Unread total on first paint, pushed on change

**Objective.** Under All Models every tab's Unread badge reads the Relay's one Unread total per Creator from first paint, the Relay pushes it on change, and a chat read on OF web clears its row and the badge in every tab within one Cycle.

Plan: `.scratch/watched-creator-refresher/goal.md` (D6, D8, D10, Phase 2, Q1 verdict). ADR-0043 (this Phase), ADR-0042 / ADR-0044 (Phase 1's). Phase 1: only its `### Contract (frozen for Phases 2 and 3)` (`phase-01-shared-refresher.md`) is used here, cited "P1 C<n>"; ASSUMPTION until it lands. Study: `.scratch/all-models-of-budget/REPORT.md` on `study/all-models-of-budget` (row 3, §1.1, §2). Labels: m = measured, i = inferred, g = guess. Rung = the ladder rung that decided it.

## Problem Statement

A chatter opens Messages Pro under All Models in a fresh session and the Unread chip says 12 while one chat is really unread (owner, live, after PR #881). The number drops only once they click the Unread chip. A chat read on OF web, on the phone or by anyone outside Inflowwww never leaves any tab: no row clears and the badge does not drop (45 s, `read_on_of.cleared_ms` all null, study run 1, m). The All list and OF's `filter=unread` disagree on the same Creator (`unread_parity.mismatches` 1, m). Each tab counts from its own aging copy, so two chatters on the same Creators see different numbers.

How today's badge is computed (traced in code; rung 1):
1. Rows. Under All Models `useChatList` fetches page 0 per Creator, 25 rows (`app/hooks/useChatList.ts:50`, `app/lib/screenBundle.ts:45`, fan-out `:416-436`), joined into the inbox bundle (`service/screens_api.py:398-399`). The Relay serves each from the `list_chats` entry: TTL 600 s plus 600 s stale-while-revalidate (`service/server.py:3240`, `:3245`, `:3352-3356`). On a reload, not a new login, rows first paint from the IndexedDB snapshot (`app/components/providers.tsx:97-98` persists `["chats"]`, max age 30 d `:72`). A login wipes it (`app/contexts/UserContext.tsx:144`, `:187`).
2. What keeps the window current. An inbound DM is patched in (+1 unread, `service/event_transcoder.py:463-500`). Our own mark-read, unread and send drop it (`service/read_flip.py:47-57`, `service/server.py:4069`). An outbound echo drops it at most once per 20 s (`event_transcoder.py:298-303`). OF pushes no frame for a read made elsewhere, so that chat "stays unread on the badge until the window expires" (`service/accounts_admin_api.py:415-418`).
3. Badge. On the All chip `allChipBase` is the loaded rows (`app/components/chat/FanList.tsx:406-408`). `unreadView` comes from `cachedUnreadView` (`FanList.tsx:434-446`), which is null unless every page of the scope's `filter=unread` list was read in this page load (`session === SESSION`, no `hasMore`, nothing partial; `app/lib/chatsCache.ts:219-224`). Nothing reads that list before the Unread chip is clicked. So the badge counts raw `hasUnread` over the loaded All rows (`app/components/chat/fanListSort.ts:108-118`, `:132-133`).
4. Clicking Unread reads `filter=unread` per Creator on a separate, cold cache key, then the view wins (`fanListSort.ts:127-138`; #881 keeps it for 5 min off the chip, `chatsCache.ts:239-247`).

So the 12 is the stale `hasUnread` flags of the cached 25-row windows, and the 1 is a live `filter=unread` read (inferred). Still unproven:
- which cache aged them: the Relay window (≤ 10 min fresh, ≤ 20 min stale) or the IndexedDB snapshot (a reload, not a login);
- whether the 1 is right, since OF's `filter=unread` once returned 0 for a Creator with an unread chat (`accounts_admin_api.py:313-316`);
- whether raw `hasUnread` and `unreadMessagesCount` ever disagree on OF (`fanListSort.ts:101-104` reads only the flag).

The study reproduced the source (All flags a chat that `filter=unread` no longer returns, `unread_parity.mismatches` 1), not the fresh-session badge itself (REPORT §5). The fresh-session metric below closes that gap, on a world where a rows-based count cannot equal the truth.

## Solution

The Relay keeps one Unread total per Creator: how many chats OF holds unread across the whole inbox. It comes from OF's own counter, `/users/me` `chatMessagesCount`, the number OF web shows on its Unread tab. It is taken from every `/users/me` body OF actually returns to the Relay, whoever asked: one observer in the OF client, beside the consent observer. Phase 1's Cycle reads `/users/me` for every Open-tab Creator, so the total is confirmed at least once per Cycle at 0 added calls. Between Cycles the Relay moves it at 0 OF calls from what it already sees: inbound DMs, our mark-read / mark-unread / mark-all, replies. Each confirmation reconciles. If OF's number is lower than the Relay could explain (a read made elsewhere), the Relay re-reads that Creator's page-0 window once (Phase 1's window hook) and sends `chat_read_changed` (#881's event) for each row that flipped. Every page-0 window read the Relay makes (drift, Phase 1's socket-gap read, the App-open warm) goes through the same hook and is diffed, so every tab clears the row with no read of its own.

A tab gets every Creator's total inside Phase 1's snapshot: on the accounts rows at first paint (owner and chatter) and in `creator_refreshed` on change. The Unread badge is the sum of the totals of the Creators the Fan List shows. A Creator with no total yet falls back to today's rule. Under a search the badge keeps today's rule. The Creator tab strip (Roster count) is unchanged. One Relay Knob turns it all on (with Phase 1's); off is today's badge.

## User Stories

1. As a chatter opening Messages Pro under All Models in a fresh session, I want the Unread badge to show the true number of unread chats before I visit the Unread chip, so that 12 never stands for 1.
2. As a chatter, I want the badge to be the same number in every tab and for every teammate on the same Creators, so that we stop disagreeing about the backlog.
3. As a chatter, I want a chat read on OF web, the phone or another tool to drop the badge in every tab within one Cycle, and to clear its row when the row is in the Creator's first 25 chats, so that nobody opens a chat already handled.
4. As a chatter, I want the badge to rise when a fan writes into a chat that was read, and to stay put when a fan writes again into a chat already unread, so that it counts chats, not messages.
5. As a chatter, I want my own mark read / mark unread / mark all read to move the badge in every tab (one Event stream push, 0 OF calls), so that #881's cross-tab flip covers the number too.
6. As a chatter, I want a reply into an unread chat to drop that chat out of the badge exactly once, even when an automation marks it read right after, so that answered chats are not counted and never counted twice.
7. As a chatter on a reload (not a new login), I want the badge never to paint from the saved browser snapshot's flags while the Relay has totals, so that a days-old copy never shows as today's count.
8. As a chatter, I want the badge to show no number until the Relay's accounts answer tells it whether totals exist, so that a stale number never flashes first.
9. As a chatter whose Creator has no total yet (Relay just restarted, Fansly Creator), I want that Creator counted by today's rule, so that the badge is never blank for a working Creator.
10. As a chatter searching the Fan List, I want the badge to count the search's rows as today, so that a whole-inbox number never labels a filtered list.
11. As a chatter, I want the Creator tab strip, the orange owe-reply number and the All and Owe reply chips to stay as today, so that only the Unread badge changes source.
12. As a chatter on the Unread chip, I want its rows to stay #881's live list while the badge shows the Relay total, so that the list stays what OF returned and the number stays whole-inbox.
13. As a chatter-only login (not the Agency owner), I want the same totals at first paint as the owner, so that the fix is not owner-only.
14. As Phase 3, I want each counted Creator's confirmation time (`unreadBadgeSources`: the later of Last refresh and the total's own `at`, P1 C1), so that "as of" shows only when the total is truly older than one Cycle.
15. As the Relay, I want the total taken from every `/users/me` body OF actually returns (route, S4S, health probes, reconnect auth, Phase 1's Cycle and the warm), never from a cache hit, so that each confirmation is real and costs nothing extra.
16. As the Relay, I want an inbound DM to move the total by the chat's prior state: read → +1, unread → 0, unknown → +1 with one unit of slack, so that between Cycles the number follows the Live connection and an unknown prior is never mistaken for a read elsewhere.
17. As the Relay, I want a chat's prior state taken first from my own record of what I did to it this Cycle, then from the held page-0 row peeked before anything is dropped, so that a reply followed by a mark-read moves the total once.
18. As the Relay, I want a read flip stamped with its pre-write time, and mark all read to set the total to the DMs that landed after that time, so that a late write never erases a newer DM.
19. As the Relay, I want a confirming read to adopt OF's number, re-apply only adjustments stamped after the read was asked, and log the drift, so that OF stays the truth and in-flight events are not lost.
20. As the Relay, when OF's number is below what my adjustments and slack explain, I want at most one page-0 window read per Creator per Cycle (shared with Phase 1's), and a `chat_read_changed` for each row whose unread state flipped (stamped at the read's ask time), so that a read on OF web clears rows in every tab without a tab read.
21. As the Relay, I want every page-0 window read diffed, and on a downward-drift read with no old window held, a `chat_read_changed {unread: 0}` for each read row of the new one, so that a tab still showing an old unread row is cleared even after my copy expired.
22. As the Relay, on a window read that found a flip or followed a downward drift, I want that Creator's other cached chat lists (deeper pages, `filter=unread`) dropped, so that the All list and the Unread list agree again (`unread_parity`) without busting them on every routine read.
23. As the Relay, I want a Dead-session Creator's total frozen at its last `at`, still counted, and never read, so that D2 holds and Phase 3 shows its age.
24. As the Relay, after a restart, I want the totals refilled from the reconnect `/users/me` reads, and tabs to accept them over the old boot's numbers (P1 C5), so that first paint after a deploy needs no extra OF call and is never shadowed by a pre-restart value.
25. As the Relay, I want a total published only when its number changed, through Phase 1's fan-out to every tab that can access the Creator and no other, so that D5 holds.
26. As an owner, I want the feature behind one Relay Knob, default off, so that turning it off restores today's badge, window busts and reads.
27. As an owner, I want the drift window read to land in Phase 1's Caller kind and Cost group, so that `of_calls_vs_baseline` rates it with the refresher and Phase 1's one re-pin covers it.
28. As an owner, I want frequent drift to raise Phase 1's post-deploy Watch check, so that a broken source shows within the 3-day watch.
29. As an owner (parked, needs-human), I want check C (below) run once in my own OF web session before the Knob goes on, so that `chatMessagesCount` is known to count chats and to drop on a read made on OF web.
30. As an owner (parked, needs-human), I want checks A and B run on AE before any WS-source ticket is written, so that Q1 is settled on evidence.
31. As a developer (parked, needs-human for go-ahead ordering), I want Step B's one log line added in its own small change, so that it can run on AE for 24 h with 0 extra OF calls.
32. As a developer, I want the slop scenario's fake OF to serve `chatMessagesCount` consistent with its chat list and its mark-as-read, and some unread chats ranked below row 25, so that the proofs measure the real path and cannot pass on today's rows.
33. As a developer, I want pure decide modules and pure client selectors, each with test tables, so that every rule above is pinned without a live stack.

## Implementation Decisions

- **Owns.**
  - Service: new pure module `unread_total_decide` and new effect module `unread_total` (in-memory per-Creator state under a `threading.Lock`; observe, adjust, reconcile, window read). It registers with Phase 1 (`register("unread_total", ...)`, `set_window_reader(unread_total.window_read)`, P1 C8/C9) and publishes only through `shared_refresher.note_values`.
  - Service hook points (calls only, no new logic there): one response observer in `of_client` (beside `_observe_consent`, `service/of_client.py:798`); the inbound path of `event_transcoder` (before the inbound patch, `:463`); `read_flip.after_write` (before its bust, `service/read_flip.py:92`); the send route's post-send step, before its bust (`service/server.py:4069`; on `fix/reply-reaches-other-chatters` the bust moves before `publish_chat_responded`, the hook stays before the bust).
  - App: new pure module `unreadBadge.ts` beside the Fan List (selectors over Phase 1's `creatorFreshness` state, no store of its own) and its vitest table; the Fan List's badge count reads its selectors.
  - Slop: `all_models_wire` (users/me counter, deep unread chats), scenario `2026-11-20-all-models-shared-inbox` (metrics, checks below), `all_models_faults` (one fault).
  - Sweep: one condition in Phase 1's Watch check `shared_refresher_budget`.
- **Interfaces.**
  - `unread_total_decide` (pure, no I/O):
    - `adjust(state, event, now) -> state`. Events: `dm_in(fan, prior)`, `read_flip(fan | all, unread, at, prior)`, `reply(fan, prior)`. Prior is `unread | read | unknown`.
    - `prior_of(state, fan, window_row) -> unread | read | unknown`: the Relay's own record for `fan` within one Cycle first, then the held row, else unknown.
    - `reconcile(state, observed, asked_at, now) -> (state, actions)`. Actions ⊆ {`publish`, `window_read`, `log_drift`}.
    - `flips(old_rows | None, new_rows, asked_at, drift_down) -> [(fan_id, unread)]`.
  - `unread_total` (effects):
    - `observe(aid, me_body, asked_at)`: from the `of_client` observer (worker threads), for each 2xx `GET /api2/v2/users/me` carrying an int `chatMessagesCount`; then `note_values(aid)` (thread-safe, P1 C8).
    - `on_dm_in(aid, fan_id)`, `on_read_flip(aid, fan_id | None, unread, at)`, `on_reply(aid, fan_id)`.
    - `window_read(aid)` (Phase 1's window reader, P1 C9): peek the page-0 rows (`relay_cache.peek`, key `_ROSTER_WINDOW_KEY`, `service/accounts_admin_api.py:321`), stamp `asked_at`, `rewarm_roster_count(aid)` (`:594-603`), peek the new rows, publish `flips`; only when a row flipped or a downward drift was pending, drop the Creator's other `list_chats` entries.
    - Contributor (P1 C8): `snapshot(aid) -> {n, at} | None`, `window_due(aid) -> bool` (a downward drift pending and no window read this Cycle).
  - `read_flip.after_write`: with the Knob on, calls `on_read_flip(aid, fan_id, unread, at)` before `bust_chat_list_and_badges`. Busting is unchanged.
  - App `unreadBadge.ts` (pure, over Phase 1's state, P1 C5):
    - `totalsOn(rows) -> boolean | null`: any row's `freshness.values` holds the `unread_total` key (null value included) → true; rows with `freshness` but no key → false; no rows → null (unknown).
    - `badgeUnread(state, shownCreators, fallbackCount) -> {n | null, fromTotal[], fallback[]}`.
    - `unreadBadgeSources(state, accountIds) -> Array<{account_id, at | null}>`, `at` = max(`Freshness.at`, `unread_total.at`) (P1 C1); Phase 3's input.
- **Schema.** None. State is in Relay memory (Phase 1's in-memory rule); a restart refills it per story 24.
- **Contracts.**
  - The total rides P1 C1: `values.unread_total = { n: int, at: int } | null` (`n`: chats OF holds unread, whole inbox; `at`: epoch ms, Relay clock, ask time of the OF read that last confirmed `n`; null: Knob on, no total yet). The key's presence is the on-signal (`totalsOn`); there is no answer-level field, since the chatter answer is a bare list (`service/chatters.py:566`).
  - Event, carriers, order, eviction, ping: P1 C3–C7. Phase 2 adds no event, field or ping key. A confirmation that leaves `n` unchanged publishes nothing (`changed` ignores the slot's `at`, P1 C3); the tab still ages it correctly from `max(at, slot.at)` because every Last refresh is a `/users/me` confirmation (P1 C1) and Last refresh rides the ping.
  - `chat_read_changed` (#881, `read_flip.publish`, `service/read_flip.py:64-77`) reused unchanged for window flips: `{fan_id, unread, at}` with `at` = the window read's ask time, so a tab never clears a newer message (#881's rule, `useAccountStateEvents.ts:210-213`).
- **What the Unread total is** (decided).
  - Whole inbox, not the Roster count's 25-chat window. Rung 2: plan Q1 verdict ("the only whole-inbox total the relay already reads is `/users/me` `chatMessagesCount`"); ADR-0043; glossary "Unread total".
  - The number is OF's `chatMessagesCount` as returned. Rung 1: it is the counter OF web's own Unread tab shows (`app/lib/ofMirrorChats.ts:187`, `:196`; ledger `.scratch/omf-messages-full/ledger.md:24`, `:31`).
  - Restricted fans: not subtracted. Rung 1: restricting a fan through the Relay marks the chat read first (`service/server.py:5487-5488`), so a restricted chat is normally read.
  - Muted chats: counted as OF counts them.
  - ASSUMPTION: `chatMessagesCount` counts unread chats, not messages, includes muted chats, and drops when a chat is read on OF web (guess from the name pair and OF's Unread-tab use). Overturned by parked check C; if it fails, the Knob stays off and this Phase is re-specced on another source.
  - ASSUMPTION: OF's `filter=unread` list is never a source (rung 2, plan: "do not trust that list alone"). Overturned only by a new owner decision.
- **Source under the polling fallback (default).**
  - One observer in `of_client`, on the success path beside `_observe_consent` and `live_rev.note` (`service/of_client.py:785-798`). Rung 3: the client already observes every response there. It sees every `/users/me` OF answers, whoever called: the route (`service/server.py:3038-3045`), S4S's `_of_me` filling the same cache key (`service/s4s_api.py:124-138`), health probes (`server.py:2883`, `:2971`), account config (`service/account_config_api.py:173`), the dead-session probe, the reconnect auth (`service/of_ws.py:115-119`), Phase 1's Cycle and the warm. A cache hit never reaches the client, so it is never a confirmation. It runs synchronously inside the read, so Phase 1's job sees a drift it found before asking `window_due` (P1 C8).
  - Known failure modes and the rule for each:
    - (a) 60 s route cache, (b) `fix/all-models-open-cost`'s `max_age` entries (up to 1800 s): a served body is not a fetch, never observed.
    - (c) OF 429 or error: no observation; `at` keeps its value; Phase 1 backs off; Phase 3 shows the age.
    - (d) Dead session: frozen (story 23).
    - (e) Fansly: no field, no total, fallback rule.
    - (f) Live connection down: no DM adjustments; Phase 1 reads the window once the socket is back (P1 C9, its story 31), and `window_read` diffs it.
    - (g) DM during a read in flight: re-applied if stamped after `asked_at`, so a double count is possible. Bounded by the next confirmation.
    - (h) `filter=unread` returned 0 once (`accounts_admin_api.py:313-316`): never read for the total.
- **Between-Cycle adjustments (0 OF calls).** Prior = `prior_of`: the Relay's own per-fan record (what our flips, replies and DMs set, kept one Cycle), else the held page-0 row (`relay_cache.peek`), taken before the path drops or patches anything.

  | Event | prior read | prior unread | prior unknown |
  |---|---|---|---|
  | inbound DM (`event_transcoder`, before its patch) | +1 | 0 | +1, slack +1 |
  | our mark read | 0 | −1 | −1 (OF is only asked when the tab saw it unread, `app/components/chat/useMarkChatRead.ts:35-40`) |
  | our mark unread | +1 | 0 | +1, slack +1 |
  | our mark all read (pre-write `at`) | n = DMs stamped after `at` | | |
  | our reply (send route, before its bust) | 0 | −1 | 0, slack +1 |

  Clamped at 0. Each adjustment is kept, stamped (flips with their pre-write `at`, `service/server.py:5278`, `:5302`, `:5314`), until the next confirmation. Slack counts the unknown-prior adjustments that could leave OF's number lower than ours; it resets at each confirmation. A reply sets the fan's record to read, so an automation's mark-read after it (`full_ai_live`, `read_flip` docstring `:1-5`) sees prior read → 0. An outbound echo (OF web, another device) names no fan and moves nothing; if it read a chat, the next confirmation drifts down.
  ASSUMPTION: a reply into an unread chat makes it read on OF (rung 3: `rosterDelta`, `app/hooks/useRosterCounts.ts:143-161`, and the send's optimistic flip); overturned by a reconcile log showing drift after replies.
  ASSUMPTION: an unknown-prior DM counts +1 (rung 5: the badge rises at once for a new chat); its error is bounded by one confirmation, and slack keeps it from asking a window read.
- **Reconcile and drift.**
  - On each observed read the total becomes OF's number plus the adjustments stamped after `asked_at`.
  - Expected = the held value at `asked_at`. Down: observed < expected − slack (a read made elsewhere): log `unread_total_drift account=<id> dir=down expected=<n> observed=<n>` and set `window_due`. Up (observed > expected): log `dir=up` only; new rows reach tabs by DM events and the head poll.
  - Phase 1 runs `window_read` in its next slot if none ran for this Creator within its Cycle (P1 C9: one per Creator per Cycle, whatever asked).
  - `window_read` diffs old vs new page-0 rows and publishes one `chat_read_changed` per flipped row. No old window held: on a downward-drift read, one `{unread: 0}` per read row of the new window (≤ 25 events, stamped at the ask time so a newer message keeps its flag); on any other read, none (after a restart the tabs' `resync` refetches their lists, `app/hooks/useAccountStateEvents.ts:215`).
  - A read and a missed DM can net to drift 0. A DM is missed only while the Live connection is down, and Phase 1 reads the window after any gap (P1 C9), which `window_read` diffs.
  - Rows new to the window reach tabs by their head poll: 90 s in the foreground with no live SSE, 5 min while SSE is live or the tab hidden (`app/hooks/useChatList.ts:90-91`, `:594`).
- **Client badge rules (which one wins).**
  1. Search active → today's rule (`chipCountsWithUnreadView`).
  2. Else, per Creator the Fan List shows: a held Unread total wins over All-list flags and over #881's Unread view. For a Creator without one, today's rule over its rows only. The badge is the sum. A Dead-session Creator's frozen total still counts (Phase 3 marks its age). ASSUMPTION: rung 5; overturned if the owner wants dead Creators out of the badge.
  3. First paint: `totalsOn` over the persisted accounts copy false → today's rule at once, as today. True or null (a fresh session) → no number until the network accounts answer seeds Phase 1's store (or errors), then rule 2. No timer. Rung 3: `useRosterCountsRead().settled` gating in `app/components/chat/useCreatorTabs.ts:83-84`.
  - The Unread chip's rows stay #881's list and its `chat_read_changed` patches. Only the number changes source.
  - Same rules in single-Creator scope. ASSUMPTION: rung 5, one selector, no scope branch; D6 names only All Models. Overturned if the owner wants single-Creator scope left as today.
  - ASSUMPTION: the badge may read more than the rows painted beside it, and may differ from the Creator tab's Roster count, until rows reload (ADR-0043's stated cost; rung 2).
- **Flag / rollback.**
  - Knob `UNREAD_TOTAL` (Relay env, default off; read in `unread_total` only; honoured only with `SHARED_REFRESHER=1`, P1 C11).
  - Off: the observer returns at once, no slot key, no reader registered (Phase 1 reads windows with `rewarm_roster_count`), `read_flip` unchanged. The client keeps today's rule (one accounts round trip of no number in a fresh session, rule 3).
  - Rollback = Knob off + Relay restart; nothing persisted, nothing to migrate.
- **Parked checks** (owner, read-only, zero OF calls by the Relay).
  - **A** (Q1, no code change). On a read-only copy / `?mode=ro` of the AE Relay SQLite, over the 2-day retention:
    ```sql
    SELECT account_id, received_at, event_type, payload_json FROM event_inbox
    WHERE payload_json LIKE '%"chat_messages"%' OR event_type IN ('chat_messages','api2_chat_message')
    ORDER BY account_id, received_at;
    ```
    Pass, per Creator:
    - a frame after connect and after each inbound fan message;
    - +1 on a fan's first message into an already-read chat, unchanged on a second message into an already-unread chat (= counts chats; an increase there = counts messages);
    - goes down after our mark-read actions;
    - goes down after a chat read on OF web with no Relay write near it (a drop in the counter with no `mark-as-read` in the Relay log within 60 s).
  - **B** (Q1, one log line, story 31, parked / needs-human for ordering). `of_ws._refresh_auth` already reads `/users/me` on every reconnect and drops `chatMessagesCount`. Log it with the first `chat_messages` frame after that connect: `ws_counter_probe account=<id> me_chat_messages=<n> frame_chat_messages=<n|none> frame_after_s=<s>`. Run 24 h on all connected Creators. Pass: equal on ≥ 95 % of samples, and never drifting for more than one frame. 0 extra OF calls.
  - **C** (source semantics, owner's own OF web session, gates the Knob). For 2–3 Creators with few unread chats: (1) the number on OF web's Unread tab = the rows in that tab, on a Creator where one chat holds ≥ 2 unread messages; (2) read one of those chats on OF web, reload: the number drops by 1.
- **OF-call budget.** The set's one table is P1 C12. This Phase's rows: Unread total confirmations 0 (Phase 1's read 1 and every existing `/users/me` fetch, observed); window read on downward drift ~0.3 / 0.8 / 1.3 calls/min at 10 / 30 / 50 Creators (g: ~0.5 per Creator per hour, 3 calls each; ceiling with Phase 1's gap reads: a window read every Cycle), in `walk:shared_refresher` → `shared_refresher`; the warm's window read 0 added (already read, `server.py:4229`). Outside the group: after a flip or downward drift, tabs that show a dropped list re-read it once (route kinds, g).
  ASSUMPTION: drift window reads take Phase 1's Caller kind and Cost group (rung 2: P1 C9, ADR-0042); overturned if Phase 1 names separate kinds, then they join its group in `of_calls.OF_COST_GROUPS`.
- **Post-deploy watch.** One condition added to Phase 1's `shared_refresher_budget`: `watch` when any Creator logs ≥ 20 `unread_total_drift` lines in the rated interval (g, no baseline; the style of `view_lease_errors`, `scripts/proxy-health/watch.py:1268`, `_w_view_lease` `:803`). WATCH.md line: `- unread-total-drift | added <date> | expires +3d | shared_refresher_budget | <PR url>`. Read failures are Phase 1's (its 429 / job-timeout logs and budget). The `dir=down` share over the 3 days is the drift rate behind P1 C12's g row.

## Testing Decisions

- **Seams** (highest first; external behaviour only):
  1. Slop scenario `2026-11-20-all-models-shared-inbox` through real tabs, the real Relay and the fake OF wire. Opt-in.
  2. The Relay's public routes plus the published events: one file `service/tests/test_unread_total_sse.py` on the harness of `service/tests/test_chat_read_changed_sse.py` (OF client faked, `events.publish` captured; no test hooks in `service/`), with that file's `if __name__ == "__main__"` runner (`:115`), since `scripts/run-tests.sh` runs each backend file as `python <file>` (`scripts/run_tests_parallel.py:42-45`). Cases:
     - the mark-read route on a held unread row → `creator_refreshed` with `values.unread_total.n` −1 and 0 OF list reads;
     - mark-unread on a read row → +1; mark-all with a DM landing after its pre-write `at` → n = 1, not 0;
     - a reply into an unread chat then a mark-read of it → −1 once;
     - two DMs into one read chat → +1 once;
     - a `/users/me` fetch through the route and through S4S's `_of_me` → observed; a cache hit → not; an unchanged `n` → no event;
     - a lower OF number beyond slack → one window read plus `chat_read_changed` for the flipped row and the other lists dropped; within slack → none; higher → log only; a second drift in the same Cycle → no read; no old window held → `{unread: 0}` per read row on a drift read, none on a routine read;
     - a tab subscribed without the Creator receives no `unread_total`;
     - the owner and the chatter accounts answers both carry `freshness.values.unread_total`;
     - Knob off → no `unread_total` key, windows dropped as today.
  3. Pure tables:
     - `service/tests/test_unread_total_decide.py` (same `__main__` runner): every row of the adjustment table; slack; `prior_of` order; reconcile with adjustments before / after `asked_at`; drift down / within slack / up → actions; one window read per Cycle; `flips` with and without old rows, never clearing a row whose `lastMessage` is newer than `asked_at`.
     - `app/components/chat/unreadBadge.test.ts`: `totalsOn` (key, null value, no key, no rows); search → fallback; mixed held / missing Creators; first-paint rule 3 (off / on / unknown); `unreadBadgeSources` takes the later `at`.
  4. Wiring: `app/components/chat/FanList.test.tsx` (badge renders Σ totals over stale All flags; no number before the seed when on). Store order, eviction and the accounts field are Phase 1's tests.
- **Prior art.**
  - `app/components/chat/fanDrawerForm.ts` + test (pure table template, CLAUDE.md);
  - `chipCountsWithUnreadView` tables in `app/lib/chatsCache.test.ts` and `FanList.test.tsx` (#881);
  - `service/tests/test_chat_read_changed_sse.py` and `test_read_flip_helper.py` (#881);
  - `scripts/proxy-health/test_watch.py`.
- **Scenario metrics that must move** (names as in the scenario file; Knob on):
  - `unread_parity.mismatches`: 1 → 0.
  - `read_on_of.cleared_ms.{a,b,c}`: all null → each ≤ 65 000 (one Cycle at the scenario's 60 s floor plus one window read, g slack). `any_cleared_ms` alone is not the bar.
  - New `read_on_of.chip_dropped_ms.{a,b,c}`: per tab, the Unread chip dropping below its value before the read (`_watch_read` already returns it, scenario `:421-433`). Today: null (i). After: each ≤ 65 000.
  - New check `READ_ON_OF_CLEARS`: every tab's row cleared and chip dropped within 65 s.
  - New `fresh_session`: the world gives K = 3 Creators more than 25 chats, with ≥ 1 unread chat ranked below row 25 (the small scale's 20 chats per Creator fit page 0, `slop/seed/__init__.py:126` on `fix/bg-lane-money-deadlock`, so a rows count could equal truth). After `read_on_of`, chats are read out of band on those K Creators. The scenario waits one Cycle, then opens a new browser context as chatter B (empty storage) on `/messages-pro` under All. It records:
    - `badge_first`: the first number the Unread chip shows;
    - `badge_ms`: navigation to that number;
    - `truth`: the fake OF's unread chats over the whole chat list of every Creator B sees;
    - `diff = badge_first − truth`.

    Today: diff ≠ 0 (i: page-0 rows miss the deep unread chats, and the 600 s window still flags the read ones). After: 0. Check `FRESH_BADGE_TRUE` ("a fresh All Models session's first Unread badge equals OF's whole-inbox unread chats"). Fault `unread-total-frozen` (the reconcile keeps the old number): `READ_ON_OF_CLEARS` and `FRESH_BADGE_TRUE` go PASS → FAIL, nothing else.
  - `of_budget_idle` by Caller kind (Relay `of_call_stats`, scenario `:12`, `:347-362`): `walk:shared_refresher` holds ≤ 1 `GET /api2/v2/users/me` per Creator per Cycle (Phase 1's) and ≤ 1 page-0 window read per Creator per Cycle. `IDLE_BUDGET` still passes.
  - Screenshots, new: `fresh-session-trigger`, `fresh-session-settled`. Existing, now showing the clear: `read-on-of-b-end`.
- **What the scenario and the fake OF must gain.**
  - `all_models_wire` keeps `fake.profiles[uid]["chatMessagesCount"]` = unread rows in the whole `chats[uid]` list. It is written under `fake.lock` in `seed_chats`, `push_dm`, `head_from_send` and `_mark`, through the existing `profiles` overlay on `/api2/v2/users/me` (`slop/lib/of_wire.py:272`, `:509-516`). Today's fake answers no counter.
  - The scenario gains: `RELAY_ENV` `UNREAD_TOTAL=1` (beside Phase 1's env); `OOB_CAP_S` 30 → 90; the `fresh_session` phase and its K deep-chat Creators; Creator Y kept on screen, so that it holds a View lease, with Y's lease state recorded in `read_on_of`.
  - ASSUMPTION: Y is leased in all three tabs (10 Creators fit the strip at 1440×900, guess). Overturned by the recorded lease state; then the scenario selects Y in tab B.
  - Run time: +120–150 s (i) on Phase 1's 606–693 s (i) ≈ 726–843 s, under the 15 min cap; one green run + one `--break` per slice (plan-review "Recommended build order").
- **Side-effect check (UI).** Beside the screenshots, one Relay answer: the accounts answer for Y shows `freshness.values.unread_total.n` = the fake OF's `chatMessagesCount` for Y; plus the `of_budget_idle` by-caller numbers above (the fake's call log carries no Caller kind, `slop/lib/of_wire.py:710-716`).

## Acceptance

```sh
# pure tables + the Relay seam (files carry their own __main__ runner)
scripts/run-tests.sh unread_total
scripts/run-tests.sh chat_read_changed
scripts/run-tests.sh read_flip
# app, while iterating
(cd app && pnpm exec vitest related --run components/chat/unreadBadge.ts components/chat/FanList.tsx)
# fake OF wire + sweep check
venv/bin/python scripts/run_tests_parallel.py --pytest slop/lib -j 8
venv/bin/python scripts/run_tests_parallel.py --pytest scripts/proxy-health -j 8
# before the PR: everything
scripts/run-tests.sh
# manual: owner opt-in, green run — slop/run 2026-11-20-all-models-shared-inbox --scale=small; tracer slice: fresh_session.diff 0, FRESH_BADGE_TRUE pass; row-clear slice adds unread_parity.mismatches 0, read_on_of.cleared_ms.{a,b,c} and chip_dropped_ms.{a,b,c} each <= 65000, READ_ON_OF_CLEARS pass; IDLE_BUDGET pass
# manual: owner opt-in, --break run — slop/run 2026-11-20-all-models-shared-inbox --scale=small --break --fault=unread-total-frozen --baseline=<green run dir>; CAUGHT on READ_ON_OF_CLEARS and FRESH_BADGE_TRUE
# manual: screenshots fresh-session-trigger / fresh-session-settled / read-on-of-b-end from the green run + the accounts answer for Y
# manual: owner runs parked check C in their own OF web session before UNREAD_TOTAL=1 on AE
# manual: after deploy, append the WATCH.md line (Post-deploy watch); Phase 1's Baseline run re-pin covers this Phase's calls
# manual (parked, needs-human): checks A and B on AE before any WS-source ticket
```

## Depends on

- **Phase 1 — Shared refresher** must land first: P1 C1 (the slot), C3 (event), C4 (both accounts lists keep `freshness`), C5–C7 (order, eviction, ping), C8 (contributor, thread-safe `note_values`), C9 (window reader, one per Creator per Cycle, its Caller kind, pacing, 429 back-off), C11 (Knobs), C12 (budget), and its Caller kind / Cost group / re-pin. ASSUMPTION (rung 2: the plan's Phase cut); overturned by Phase 1 as built, then the contract section is re-aligned, not this spec.
- **Phase 3** consumes `unreadBadgeSources` and `badgeUnread`'s `fromTotal` / `fallback`. Nothing else.
- **In-flight, netted:**
  - `fix/all-models-open-cost` (seen in its worktree, uncommitted): moves the route's fetch into `_users_me_read` and adds `max_age` identity entries up to 1800 s. The observer sits in the client, so neither needs a hook; served bodies are never observed. ASSUMPTION: that branch keeps calling `OFClient.me()`.
  - `fix/bg-lane-money-deadlock`: ships the scenario, its wire and the seed sizes. This Phase's scenario edits come after it merges.
  - `fix/reply-reaches-other-chatters`: moves the send route's bust before `publish_chat_responded` (its `service/server.py:4054-4061`). Overlap: this Phase's reply hook goes before that bust on either side of the merge.
  - PR #881 (merged): `chat_read_changed` and the Unread view are reused as is.

## Out of Scope

- The WS counter frame as any source of the total (Q1 not settled): no Knob or code path now (YAGNI); a later spec, after checks A and B pass.
- A `provisional` mark on the wire: nothing reads it (Phase 3 ignores it); the Relay keeps slack internally.
- Pushing new rows or previews on upward drift: rows arrive by DM events and the head poll. Study rows 2 and 9 cover row pushes.
- Clearing rows beyond page 0 after a read on OF web (see Review, needs-human).
- The Creator tab strip's blue number and "unread" sort: they stay the Roster count (glossary: Roster count ≠ Unread total; the Unread badge is the chip only).
- Patching the page-0 window in place on our own mark-read instead of dropping it (−3 OF calls per mark-read, i): not asked by the plan; a later ticket.
- An optimistic badge drop in the tab that marks read: the Relay's push lands in ~0.5 s (508 ms cross-tab, study run 2, m), and the row dot is already optimistic (YAGNI). The tab takes values, never deltas, so nothing double-applies.
- Owe-reply (orange) from a whole-inbox source: no whole-inbox owe-reply counter exists on OF's `/users/me` (fixture, rung 1).
- Persisting totals across Relay restarts or in the browser snapshot: the reconnect reads refill them, and a persisted total is exactly the stale first paint this Phase removes.
- The bell count, Cycle scheduling, the Open-tab Creator set and the re-pin execution: Phase 1's.
- The "as of" and no-live-connection marks: Phase 3's.
- The OF mirror's Unread tab and the assistant's unread marker: they read `/users/me` directly (`app/lib/ofMirrorChats.ts:196`, `app/components/assistant/MarkerCards.tsx:46-53`) and are unchanged.

## Further Notes

- ASSUMPTION: the Relay computes no "chats" count of its own from `unreadMessagesCount` sums or windows; OF's counter is taken as is (rung 5). Overturned by check C failing.
- ASSUMPTION: the fresh-session symptom is mostly stale Relay windows, not the IndexedDB snapshot (guess, unproven, Problem Statement). Either way this Phase removes both from the badge, and `fresh_session` measures it with empty storage. A reload variant (storage kept) is a later scenario if the owner wants it; story 7 is pinned by the vitest first-paint rule.
- ASSUMPTION: no AE number exists for how often reads happen outside Inflowwww (drift rate, P1 C12's g row). The `unread_total_drift` lines measure it after deploy.
- ASSUMPTION: the scenario names `read_on_of.chip_dropped_ms`, `fresh_session.*`, checks `READ_ON_OF_CLEARS` and `FRESH_BADGE_TRUE` and fault `unread-total-frozen` are new names this spec coins (rung 3: the scenario's own naming); overturned by the scenario's owner renaming them in the same PR.
- ASSUMPTION: the `of_client` observer is safe from worker threads: `unread_total` state behind a `threading.Lock`, publish through `note_values` (P1 C8). Rung 3: `_observe_consent` runs on the same path.

## Review

Reviewer: `codex` (exec, read-only, effort high), 2026-11-20. Call 1 blind (B1–B12), call 2 on the draft (D1–D18). Each verified against the source before deciding.

- B1 partial — first-paint bug unproven (STUDY-REPORT:43, :198). Already the spec's own gap; `fresh_session` now runs on a world where rows cannot equal truth (D9).
- B2 accept — poll `/users/me`, reuse reconnect, falsify on an OF-web read. Check C gains step (2): read on OF web, number drops by 1.
- B3 accept — check A lacked a read on OF web with no Relay write. Added as its fourth pass rule.
- B4 accept — one read plus one newly unread chat nets to 0 and clears no row. Merged with D1: every window read is diffed, and Phase 1's after-drop window read covers missed DMs (Reconcile and drift).
- B5 accept — price the read set: Phase 1 already reads `/users/me` every Cycle (phase-01 spec "A Cycle's reads" 1). Case A/B table replaced; Phase 2 adds 0 base reads (D4).
- B6 accept — first-paint carrier and states undefined. Carrier named (`Freshness.values.unread_total` on both accounts routes), `unread_totals_on` added, rule 3 covers missing / unknown / off.
- B7 accept — warm can suppress the poll. R6 rewritten: with the refresher on the warm reads `/users/me` (phase-01 story 25) and the observer takes it; the warm's window read is diffed.
- B8 accept — ordering and recovery. `(boot, seq)` order for seeds and pushes; unchanged confirmations reach tabs via heartbeat `unread_at` (R7); a new boot wins after restart.
- B9 partial — who counts. Search, restricted (`server.py:5487-5488`) and clamp (Phase 1 any-scope) were covered; dead-session rule added (frozen, counted, ASSUMPTION).
- B10 partial — #881 speed / double-apply. Tab takes values, not deltas (Out of Scope note); a real Relay-side double decrement (reply then automation mark-read after the send bust, `server.py:4069`) found while checking and fixed with `prior_of`.
- B11 partial — seam test shape. Added out-of-scope-tab and chatter-route cases; seed broken separately at vitest / pytest; slop keeps one fault (2-run cap).
- B12 reject — scenario not in this checkout. Known: it ships with `fix/bg-lane-money-deadlock` (Depends on); file present there (`ls .../t3-b143ea21-.../slop/scenarios` lists it).
- D1 accept — netting to 0 and no held window leave rows stale (`relay_cache.py:338-342` peek returns None). `window_read` publishes `{unread: 0}` per read row when no old window; after-drop window read covers missed DMs. Rows beyond page 0: needs-human below.
- D2 accept — chatter-only sessions miss the carrier: `screens_api.py:267-274` serves `/chatter/me/accounts`, `useAccounts.ts:97-113` drops extra fields. R1 extended; story 13 and a seam case added.
- D3 accept — 3 s fallback could paint persisted flags; no off signal. Timer removed; `unread_totals_on` added; rule 3.
- D4 accept — R2/R6 contradicted phase-01 (reads `/users/me` every Cycle, warm reads it, `note_values` exists). `read_due` / case B removed; R1, R2, R6 rewritten.
- D5 accept — `on_window(aid)` lacks old rows and ask time; `rewarm_roster_count` returns counts (`accounts_admin_api.py:594-603`). `window_read` takes both inside it; R3 makes Phase 1 call it; one window read per Creator per Cycle whatever asked.
- D6 accept — "a seed always replaces" let a late seed roll back a push. `(boot, seq)` order for both; test row added.
- D7 accept — unchanged confirmations never reached tabs; Phase 3 needs per-source `at` (phase-03 spec "From Phase 2"). R7 heartbeat `unread_at`; `unreadBadgeSources` added.
- D8 accept — Acceptance used `any_cleared_ms` only. Per-tab `cleared_ms` and `chip_dropped_ms` plus check `READ_ON_OF_CLEARS` now gate.
- D9 accept — small seeds 20 chats per Creator (`slop/seed/__init__.py:126` on the deadlock branch), so the old rule could pass. `fresh_session` gives K Creators > 25 chats with deep unread ones.
- D10 accept — `run-tests.sh` runs `python <file>` (`run_tests_parallel.py:42-45`). Both new service test files carry the `__main__` runner (`test_chat_read_changed_sse.py:115`).
- D11 accept — `--break` is a flag (`slop/lib/cli.py:782-788`). Now `--break --fault=unread-total-frozen --baseline=<run 1>`.
- D12 accept — `on_read_flip` dropped the pre-write `at` (`server.py:5278`, `:5302`, `:5314`). Flips stamped with it; mark-all sets n = DMs after `at`; mark-unread, mark-all race, reply, repeated-DM cases added.
- D13 accept — the reply branch moves the bust before publish (sibling `server.py:4054-4061`), so a hook beside publish reads unknown. Hook placed before the bust; overlap stated.
- D14 accept — S4S fills the same cache key with its own fetcher (`s4s_api.py:124-138`); health and account config call `me()` direct. Harvest moved to one `of_client` observer beside `_observe_consent` (`of_client.py:785-798`): every fetch, never a cache hit.
- D15 accept — window read is ≤ 5 upstream calls + 1 retry, not 3 (`chats_page.py:129-134`, `(limit // 10) + 3`); wire log has no Caller kind (`of_wire.py:710-716`). Ceiling restated; side-effect check reads `of_budget_idle` by caller. Phase 1's ~18/min is Phase 1's (noted).
- D16 accept — with live SSE the head poll is 5 min, not 90 s (`useChatList.ts:90-91`, `:594`). Wording fixed.
- D17 partial — scope beyond the cut. Creator tab blue / sort change and the in-place window patch (old story 22) moved to Out of Scope. Single-Creator scope kept: same selector, no branch (rung 5, flagged).
- D18 accept — "failed reads" alert had no trigger. Watch is drift-only; read failures are Phase 1's (ASSUMPTION, fallback named).
- **needs-human** (from D1, D6 wording) — D6 says a chat read on OF web "clears in every tab". This spec clears rows in each Creator's first 25 chats; a deeper row a tab has loaded stays until that tab re-reads it (the badge still drops). Position A (spec): page 0 only, 0 extra reads. Position B: re-read every page a tab holds, a read per page per drift. Settles it: the AE share of OF-web reads on chats ranked below 25 (a `unread_total_drift` line with no flipped page-0 row), from the 3-day watch, or the owner's word.

### Six hats (2026-11-20)

Report `/tmp/wcr/sixhats.md`; lines for the bullets touching this spec (tally: `plan-review.md` "Six hats").

- 2 **accept** — check C unrun and no AE drift rate: both stay open (Further Notes, Parked checks); drift rate is now
  measured by the Watch condition's `dir=down` share.
- 4 **accept** — R1 claimed Phase 1 named only `/admin/accounts`, but it already carried both lists. R1–R7 deleted;
  Depends on cites P1 C<n> only.
- 6 **partial** — `provisional`, `source`, `boot`/`seq` in the slot and the echo event cut (nothing read them); the
  adjustment table stays, it is what moves the badge between Cycles (D6 "pushed on change"), pinned by tables.
- 8 **accept** — R7 (`unread_at` in the ping) was overturned by its own clause: Phase 1 moves Last refresh only on a
  landed, kept `/users/me` (P1 "A Cycle's reads"). R7 and `unread_at` dropped; `unreadBadgeSources` takes
  max(Last refresh, slot `at`); zero wire change.
- 9 **accept** — the slot's moving `at` made every confirmation a change; P1 C3 now compares a slot without its `at`.
- 10 **accept** — second store `["unread-totals"]` deleted; `unreadBadge.ts` is selectors over Phase 1's store,
  ordered by envelope `(boot, seq)` (P1 C5).
- 11 **accept** — own observer kept, Phase 1's `on_users_me` gone (P1 C8); `window_read` registers as Phase 1's one
  window reader (P1 C9), so the warm's step 2 is Phase 1's call, not this Phase's hook.
- 12 **accept** — `unread_totals_on` had no place on the bare-list chatter answer (`service/chatters.py:566`).
  Inferred from the slot key's presence (`totalsOn`).
- 14 **accept** — observer threads → `note_values` thread-safe (P1 C8); state under a `threading.Lock`.
- 15 **accept** — budget table removed here; the set's one table is P1 C12 (this Phase: ~1.3/min at 50, g).
- 16 **accept** — unknown-prior +1 into an already-unread chat read as a downward miss and could ask a window read
  every Cycle. Slack (Between-Cycle adjustments) plus down-only reads (Reconcile) remove that trigger.
- 17 **partial** — list drops now only on a flip or downward drift; no-old-window events only on a drift read (a
  restart's `resync` already refetches tab lists, `useAccountStateEvents.ts:215`). Tab re-reads after a drop are
  priced as outside the group (g), not 0. A drift read may still emit ≤ 25 events per Creator: accepted, rare.
- 18 **accept** — runtime restated against Phase 1's new +210 s: ≈ 726–843 s (i), under 15 min; one fault.
- 23 **partial** — down-only window reads taken. Unknown-prior DM stays +1 (the badge should rise at once for a new
  chat) but adds slack, so it never triggers a read; same cut to drift reads, without a 10 min lag on new chats.
- 24 **partial** — `UNREAD_TOTAL_SOURCE` and `source: "ws_counter"` cut (Out of Scope); `provisional` cut.
- 25 **accept** — own `unread_total_drift` check and `of_calls_vs_baseline` line dropped; drift is one condition in
  Phase 1's `shared_refresher_budget`, one WATCH line.
- 29 **accept** — no change: rows below page 0 stay needs-human, default page 0 only.
- 31 **partial** — check C still gates the Knob; plan-review recommends the owner run it before any code. Code may
  proceed behind the default-off Knob.
