# Multi-platform Phase 1 — plan review

Plan: `.scratch/multi-platform-p1/plan.md` (decisions in `.scratch/multi-platform/issues/01..06`). Specs: `phase-01a-platform-registry.md`, `phase-01b-fansly-reports-only-what-it-did.md`, `phase-01c-app-capability-table-and-fansly-ui.md`, `phase-01d-messages-pro-combined.md`. Reviewed 2026-11-24 against the six-hats report on the set and the coordinator's shared-ownership rulings.

## Workstreams

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 1 | 1a — registry, Backend modules (`Shim` export, `status_code` handler), safe session ingest, recipe doc | `phase-01a-platform-registry.md` | none |
| 2 | 1b ticket A — gates + markers (verdicts, route-miss marker table, `side_effect_gate`, every gate, `delete_chat`, Capability test) | `phase-01b-fansly-reports-only-what-it-did.md` | 1a |
| 3 | 1b ticket B — money + fixtures (Banking set, tips, seen-code counter, fixtures, signer vectors, Fansly runner block, docs) | `phase-01b-fansly-reports-only-what-it-did.md` | 1b A |
| 3 | 1c — app Platform table, Drift test, gated controls, nav, setup, chatter roster `platform`, Fansly card, seed | `phase-01c-app-capability-table-and-fansly-ui.md` | 1a, 1b A |
| 3 | 1d slice — exact ids (cursor paths, head-settled, `useChatMessagesLocal`, list-add) + Relay `js_safe_id` on `/admin/chats/recent` and `/admin/messages` | `phase-01d-messages-pro-combined.md` | nothing in 1c; the list-add echo leans on 1b A's string echo |
| 4 | 1d rest — combined window, badge, composer wiring, filters, Post button, PlatformSync, real-path proof | `phase-01d-messages-pro-combined.md` | 1c (and the wave-3 1d slice) |

1b's split follows its Size and order of work: a read-only run of its scan on 2026-11-24 found 154 route-reached names missing on `FanslyShimClient`, 140 outside its verdict table (measured). Ticket A's first slice re-runs the Capability test red on the tree it starts from and records the count.

ASSUMPTION: 1c needs only 1b's ticket A, since its Drift test reads markers and `refusal` and nothing in money or fixtures (rung 5, from 1c's Depends on); overturned if 1c's proof needs a fixture from ticket B, then 1c moves to wave 4.

## Adversary

- 1a (`phase-01a-platform-registry.md`): codex, blind + draft; 12 accept, 7 partial, 3 reject; needs-human 1 (owner-run live Fansly link after merge).
- 1b (`phase-01b-fansly-reports-only-what-it-did.md`): codex, blind + draft; 13 accept, 7 partial, 2 reject; needs-human 1 (Capture session + three Proof purchases, not needed to land).
- 1c (`phase-01c-app-capability-table-and-fansly-ui.md`): codex, blind + draft; 13 accept, 5 partial, 3 reject; needs-human none.
- 1d (`phase-01d-messages-pro-combined.md`): codex, blind + draft; 16 accept, 5 partial, 1 reject; needs-human 1 (one-time check on a real Fansly session).

Counts are the codex findings in each `## Review` (merged pairs in 1d counted once per finding). The six-hats lines sit under `### Six hats` there and are not counted here. Codex lines a six-hats ruling replaced carry a "superseded" note in place.

## Six hats

Bullets about one or more specs are reconciled in those specs' `### Six hats`: White 1 (1a, 1b, 1c, 1d), White 2 (1a, 1b, 1c, 1d), Red 1 (1b), Black 1 (1c, 1d), Black 2 (1c), Black 3 (1c, 1d), Black 4 (1b, 1c), Yellow 1 (1a), Yellow 2 (1b, 1c, 1d), Green 1 (1c, 1d), Green 2 (1c, 1d), Green 3 (1a collision, 1b `get_user`, 1d `storage` and parallel run), Blue 1 (1b sizing). By bullet (14 with the Recommendation): 13 accept, 1 partial (Green 3: the collision check and the `storage` reconcile are partial, the `get_user` cut and the parallel run accepted), 0 reject. The bullets about the set:

- Red 1, the four-way cut is sound but shared parts are coordinated in prose that already disagrees — **accept**: one owner per shared part (table below), and every contradicting line was rewritten or deleted (1b Owns, Typed error, Contract with 1a, Depends on, the `Shim` ASSUMPTION; 1c Depends on, Session scope, seed bullet and its ASSUMPTION; 1d Filters, Fake Fansly Creator, `$D up`, the "19-digit" tests, roster Contracts). Earlier codex lines that the table overrides are marked superseded, not deleted.
- Blue 1, one table of shared parts — **accept**. Coordinator rulings, rung 5:

  | Shared part | Owner | Others |
  |---|---|---|
  | Backend `Shim` export + API-error handler reading `status_code` | 1a | 1b raises 501 subclasses through it; 1c's Drift test reads `Shim` |
  | `side_effect_gate.refusal`, accepting a Shim class or instance | 1b | 1c's Drift test calls it on the class |
  | `delete_chat` / Bulk Delete on Fansly: mark + gate | 1b | 1c and 1d point to it |
  | Route-miss sizing (red-first count, split into gates + markers then money + fixtures) | 1b | — |
  | verify-app Fansly seed: `--fansly` opt-in, fixed 18-digit ids, Shim-shaped fixtures, doctor 21/20 | 1c | 1d adds SQLite chats + chatter grant, passes `--fansly` |
  | One mass-sender helper `massSenders(accounts, platform)` | 1c | 1d passes its composer Platform, wires `useMassSend`; reducer plain-text switch stays a reducer table (ticket 05 item 6) |
  | `useOfRichAllowed` rule (All-models passes first sender, never `null`) | 1c | 1d names the window's first sender only |
  | Chatter roster `platform` field (Relay DTO + row mapping) | 1c (moved from 1d) | 1d reads it |
  | Fansly login card wording (`name: null`, relink expected id) | 1c | 1a's Out of Scope points there |

  ASSUMPTION: each row's owner as above (coordinator ruling on shared ownership, rung 5); overturned if the owner reassigns a part, then the other spec takes the owning lines verbatim and the table moves with them.
- Blue 1, run 1b's Capability test red first and size 1b from the count — **accept**: pre-counted read-only now (154 route misses, 140 outside the verdict table, `delete_chat` among them), which exceeds one slice, so 1b is two tickets (Workstreams). The first slice's red run is the binding count.
- Green 3, run 1d's exact-id work and Relay changes in parallel with 1c — **accept**: wave 3 in Workstreams; 1d's Depends on says so.
- Recommendation, hold all four specs for one ownership pass, then size 1b from a red-first run before implementation — **accept**: the ownership pass is this review; sizing is pre-counted and re-run as 1b's first slice before any marker is written.

## Cut (YAGNI)

Hand-offs between the four specs are not cuts and are left out.

- OnlyFans identity-before-write: OnlyFans derives its id from the signed capture, and the owner froze OnlyFans behaviour (1a).
- Account-id prefixing: parked until site #2's ids are seen, ticket 06 item 5 (1a, 1b).
- Shim split, shared Shim core, neutral marker names: rejected by ADR-0053 / ticket 06 item 2, or parked for site #2 (1a, 1b).
- Capture-rig host parameterisation: waits for site #2, ticket 06 item 4 (1a).
- Capture route, `/img` allowlist, extension hosts for a new Platform: separate edits, named in the recipe (1a).
- Loud failure on unknown `meta.platform`: ticket 01 keeps the OnlyFans fallback (1a).
- Cross-Agency relink rules: pre-existing and shared with the OnlyFans bootstrap (1a).
- A lock across concurrent captures of one id: the re-check after `identify` narrows it; a real clash waits for site #2 (1a).
- Session discovery for a blob-only directory without meta: the Fansly route always writes meta (1a).
- Tips (7001), paid-sub banking, post-unlock 2007 split, net/fee: wait for Proof purchases, ticket 03 (1b).
- Building capture-blocked methods (list members, rename, delete, block, search users, chat media, scheduled, mass history, broadcast): wait for the Capture session, ticket 04 (1b).
- Smart list sync on Fansly, and gating its activation before enqueue: waits for `list_users_in`; the job's skip leaves rows honest (1b).
- Reading past the first notification page: recorded reach limit, ticket 03 item 9 (1b).
- Pin, unpin, mark-unread success to automation callers: routes already 501 and no live automation calls them (1b).
- Fixing `cancel_scheduled`'s post-endpoint hazard: recorded only, ticket 04; automation reach closed by the auto-unsend mass-lane skip (1b).
- Reconciling transactions already banked from 2008, 32007 or chat tips: prospective rule; needs the owner's go (1b).
- Enabling the Relay broadcast path on Fansly: waits for the broadcast capture (1b).
- Fansly `get_user` by username: not in ticket 04 (1b, six hats).
- Hiding Bulk Delete in the app: not in ticket 02 item 6's control list; `delete_chat`'s 501 guards it (1b, 1c).
- A Relay-served catalog: rejected by ADR-0054 (1c).
- Disable-with-reason states: rejected by ADR-0056 (1c).
- Building any of the 12 placeholder pages: dropped, ticket 02 item 7 (1c).
- A `scheduled_messages` Capability: removed by ticket 02; the Scheduled chip is left alone (1c).
- The Thread header's "Pinned chat" icon: not wired on OnlyFans either (1c).
- mym / Fanvue as Platforms: teasers only (1c).
- Per-component render tests per gated control: verify-app and the hook table cover them (1c).
- A Relay-side relink expected-id check: the card's pre-send check needs no route change (1c).
- Platform badges on Fan rows and the Thread header: ADR-0057 leaves them off (1d).
- A faster Fansly cold load: only if measured slow, ticket 05 item 11 (1d).
- Remembered tabs and chat cache keys: already keyed by account id with string ids, ticket 05 item 12 (1d).
- Mixed-Platform mass sends and Fansly broadcast: rejected by ADR-0057; broadcast waits on its Capability (1d).
- Cold-seed and kept-previous-rows paint during a filtered read: platform-neutral today (1d).
- Combined lists outside Messages Pro: owner scope (1d).
- A new `storage`-event reconcile path or test: ticket 05 item 3 says on load; `onPlatformChange` already hears another tab (1d, six hats).
- A slop run: owner constraint (all four).

## Not yet specified

None. Each plan bullet maps to a spec: 1a's registry, ingest and recipe to 1a; 1b's list-add, gates, money and Capability test to 1b; 1c's table, Drift test, hidden controls, nav and setup to 1c; 1d's combined window, per-account Platform, exact ids, no mixed sends and badge to 1d. The plan's "fake Fansly Creator in the verify-app seed" (1d bullet) is specced in 1c by ruling, with 1d's additions in 1d.

## Open questions

Sharpest first; each with what falls if it is wrong.

1. 1b: 140 route-miss markers exceed one slice, so the A/B split applies — if the red run counts far fewer, the split is overhead and the two tickets merge back; if more, ticket A itself may need a second slice.
2. 1b: every `_get_client().` route miss is reachable and must be marked, never Unreached — if some routes cannot be hit for a Fansly Creator, 1b marks names nobody reaches, and ticket A shrinks.
3. 1c: opening the seeded Thread keeps her 18-digit string Fan id (unmeasured) — if the open path rounds it, 1c's `/chats/$FFAN/messages` check reads 0 and 1c's proof waits for 1d's wave-3 exact-id slice.
4. Workstreams: 1c needs only 1b ticket A — if its proof needs a ticket-B fixture, 1c slips to wave 4.
5. 1a: the collision check on the OnlyFans writers reads only and never changes a no-collision outcome — if the no-collision test shows any change, the frozen OnlyFans ingest moved and the check must leave those writers.
6. Shared ownership (all four specs): each part's owner per the coordinator table — if the owner reassigns one, two specs swap lines and Workstreams may reorder.
7. 1c: the seed sits behind opt-in `--fansly` — if the owner wants her in every stack, doctor's 20 becomes 21 and every verify-app recipe sees a 21st Creator.
8. 1b: route misses outside the verdict table are marked from one `{name: (verdict, reason)}` table — if a reviewer wants per-method stubs, ticket A grows by about 140 stubs.
9. 1b: `delete_chat` is Unsupported, not Blocked — if a bundle note shows a Fansly chat delete, it becomes Blocked and joins the Capture session list.
10. 1a: 400 for unproven identity, 409 for collision — if the app needs distinct codes, 1c's card wording mapping changes.
11. 1c: `filter_tips`, `filter_priority`, `filter_folders` are app-only in the Drift test — if the Shim starts honouring one, the table hides a working filter and no test notices.
12. 1c: the relink expected id is checked in the card — a non-card relink caller (script, API) could still link a different account as new.
14. 1d: with scope All and no pick the composer starts on OnlyFans — if the owner wants the switch's Platform, the composer's default and its tests change.
15. 1d: `js_safe_id` for every Platform, OnlyFans bytes unchanged — an OnlyFans id at or past 2^53 would turn into a string on the wire.
16. 1d: a Fansly message id is always a string past 2^53 — a numeric Fansly id would fall into the synthetic-band test on an unresolved Thread.
17. 1b: unmarked `returns=` raises; existing `returns=` uses stay except `resubscribe_user` — if the owner wants `recent_expired_subscribers` and friends to raise, more callers need gates.
18. 1b: `tipAmount` omitted, not zero — a frame carrying both a tip and a price would bank through the price fallback.
19. 1b: the lifecycle gate drops only discounted plans — if the owner wants expiry off on Fansly entirely, plain expiry messages stop too.
20. 1b: `add_users_to_lists` reports echoed ids — if the echo is always identical, the echo read is redundant but harmless.
21. 1b: a 2007 row without `accountMediaPrice` counts as `2007_unpriced` — if the owner wants only the six codes, one counter key goes.
22. 1b: the vault backfill keeps its `last_attempt_at` stamp on refusal — if any screen reads that stamp as a sync, a Fansly fan looks synced.
23. 1b: `mass_premade` stops on a `platform_lacks:` skip — if premade gains a per-item Platform, later items would be wrongly dropped.
24. 1b: signer vectors come from the locally observed bundle copy — if it is gone, vectors come from the public cyrb53 reference and check less.
25. 1b: fixtures are synthetic from `RECIPES.md` — a field the recipes doc gets wrong passes the shape tests.
26. 1b: the Capability test body lives in `service/tests/` with a thin `fansly/` entry point — if the owner wants one file, the entry point goes.
27. 1b: the scan keeps only names `OFClient` defines — a Shim-only method with `service/` callers is unchecked.
28. 1b: `side_effect_gate` is a new small module — if a shared home appears, it moves.
29. 1b: Blocked and Unsupported subclass `FanslyAPIError` with 501 — if 1a's handler cannot read a status, every marked route answers 502.
30. 1b: the Fansly runner block runs only without a pattern — a patterned run skips Fansly tests silently.
31. 1a: Lacks flags are a `str` Enum whose values equal their names — if 1c needs a separate name list, the Drift test reads a second source.
32. 1a: the Fansly route reuses `post_bootstrap_hooks` — if clearing the dead-session pause misfires on Fansly, a relink leaves the Creator paused.
33. 1a: `accounts` imports `platforms` at call time — if `platforms` stops importing Backend modules eagerly, the cycle-break is moot.
34. 1a: `identify(session)` is on `fansly_backend` only — site #2 may want it in the contract.
35. 1a: the scan bans comparisons on a `get_platform(...)` call — a raw-read caller that later branches slips past.
36. 1a: `automations/_outbound_guard.py` is allowlisted — a real Platform branch added there would not be caught.
37. 1a: the recipe doc is `docs/platform-recipe.md` — a rename of `docs/platforms.md` breaks the pointer grep.
38. 1a: `shared_refresher.py:274` keeps its own `SHARED_REFRESH` flag — if its cause is found, the flag may fold into another.
39. 1c: "1a flag names" means the registry's Platform keys — if 1a meant Lack names, the Drift test checks the wrong list.
40. 1c: `useAccountPlatform` reads cache only — a provider-less host shows no gated controls until something else fetches.
41. 1c: the Drift map names `OFClient` methods — if 1a's Backend contract names others, the map is rewritten.
42. 1c: the Pinned chip is gated by `pin_message` — if Fansly gains chat pinning without message pinning, the chip needs its own Capability.
43. 1c: the chatter roster reads `accounts.get_platform` — if 1a's registry exposes a different per-account read, the roster switches to it.
44. 1c: seed ids and the name "Nova Reyes" are a coin flip — nothing falls while they stay 18 digits and past 2^53.

## Needs the human

- 1a: after merge, owner-run on a local relay with a temp accounts dir: paste a junk-token Fansly blob (expect 400 in the card, no new directory), then the real blob (expect a named Creator). Calls fansly.com, so agents never run it.
- 1b: one Capture session on the owner's two accounts (list members, rename, delete, block + unblock, username search, one scheduled broadcast row) and three Proof purchases (chat PPV, paid sub not a gift code, chat tip). Not needed to land 1b.
- 1c: none.
- 1d: one-time check on a real Fansly session: mixed Creator list, a Fansly Thread opened while the switch says OnlyFans, scroll back.
- Set: any coordinator ownership ruling (Six hats table) is open to the owner's overturn; none blocks the build.
