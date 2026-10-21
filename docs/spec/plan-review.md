# Plan review: Messages Pro parity specs

Review of the eight Phase specs for `docs/plans/messages-pro-parity.md`, 2026-10-12. Inputs: the specs `docs/spec/phase-00-*.md` to `phase-07-*.md`, their codex adversary reviews, and a six-hats report on the set. This review reconciled the six-hats report into the specs (a `### Six hats` subsection at the end of each spec's `## Review`), amended ADR-0002 and ADR-0003, and updated `CONTEXT.md`. Design only: no code, no migration and no network access.

## Workstreams

Waves follow each spec's Depends on. Phases in the same wave can be built in parallel.

| Wave | Phase | Spec | Depends on |
|---|---|---|---|
| 0 | 0. Pop-out window, Deep link, harness | `docs/spec/phase-00-pop-out-window.md` | none |
| 1 | 5. Fan insights panel | `docs/spec/phase-05-fan-insights-panel.md` | Phase 0 |
| 1 | 4. Composer, PPV and Vault | `docs/spec/phase-04-composer-ppv-vault.md` | Phase 0 |
| 1 | 2. Fan List pane (core) | `docs/spec/phase-02-fan-list-pane.md` | Phase 0 |
| 2 | 1. Window chrome and tabs | `docs/spec/phase-01-window-chrome-tabs.md` | Phases 0 and 2 (`phase-01:321`, no land-first fallback) |
| 2 | 2. Fan List pane (Split Inbox tickets) | `docs/spec/phase-02-fan-list-pane.md`, Depends on › Landing split | Phase 2 core. Must land before Phase 6 (FL50) and Phase 7 (Split Inbox row) |
| 3 | 3. Chat header and message list | `docs/spec/phase-03-chat-header-message-list.md` | Phases 0 and 1. Hand-offs with 4 and 5, which it does not need |
| 4 | 6. Geometry pass | `docs/spec/phase-06-geometry-pass.md` | Phases 0–5 merged to `main` |
| 5 | 7. Ours, kept and marked | `docs/spec/phase-07-ours-kept-marked.md` | Phases 0–6 |

Gate for every wave after 0: no UI ticket starts until Phase 0's self-test run fails as intended and its real run exits 0. This is rung 2: plan:50-51 says a UI ticket is not done until `scripts/ui-shots.sh` exits 0, and the harness does not exist yet (`ls scripts/ui-shots.sh` finds nothing).

### Recommended landing order

0 → 5 → 4 → 2 (core) → 1 (quick reply last) → 3 → 2 (Split Inbox tickets) → 6 (panes, sidebar and sweep, then the module, guard and lift) → 7.

- **5 before 3.** Phase 3's seam 3 extends `fanDrawerEditFreshness.test.tsx`, which Phase 5 must leave unchanged. With Phase 5 first, Phase 3 builds `focusNotesRequest` once, on the tabbed Fan insights (`phase-03` F23).
- **4 before 3.** Phase 3 then removes the Chat header's 🌐 toggle instead of parking it in the Extras overflow (`phase-03` F12).
- **5 before 4.** These two are independent. The six-hats order is taken as it stands (rung 6).
- **2 before 1.** Phase 1 requires it (`phase-01:321`).
- **Split Inbox tickets after 3 and before 6.** It is the only work in the set that changes the relay's database (rung 4). It cannot land later, because Phase 6 lifts its Geometry and Phase 7 grades its Region.
- **6 then 7.** The specs require it.

Rungs: 4 for Split Inbox, 5 for the rest (each earlier landing removes a fallback path from a later spec), and 6 for the 4–5 tie.

ASSUMPTION: this landing order is the cheapest one the specs allow. It is overturned if a Wave 1 Phase stalls. Phase 3 still lands without Phases 4 and 5 through its stated fallbacks (F12, F23), and Phase 5's merge-base check holds in either order.

## Adversary

Every spec had a codex review in two calls: a blind call on the plan and source, then a draft call on the spec. Both were read-only (`codex exec --sandbox read-only`, reasoning effort high, sparse worktree). The counts below come from each spec's Review, before this reconcile's `### Six hats` lines.

- **Phase 0** (`phase-00-pop-out-window.md`): codex. 12 accept, 7 partial, 13 reject. Needs-human: none.
- **Phase 1** (`phase-01-window-chrome-tabs.md`): codex. 17 accept, 10 partial, 8 reject. Needs-human: none.
- **Phase 2** (`phase-02-fan-list-pane.md`): codex. 18 accept, 12 partial, 5 reject. Needs-human: none.
- **Phase 3** (`phase-03-chat-header-message-list.md`): codex. 11 accept, 7 partial, 9 reject. Needs-human: none. The spec has no counts line, so these were counted from its Review.
- **Phase 4** (`phase-04-composer-ppv-vault.md`): codex. 6 accept, 9 partial, 9 reject, plus two own observations (O1, O2). Needs-human: none.
- **Phase 5** (`phase-05-fan-insights-panel.md`): codex. 13 accept, 6 partial, 10 reject. Needs-human: 1 (B11).
- **Phase 6** (`phase-06-geometry-pass.md`): codex. 10 accept, 6 partial, 8 reject. Needs-human: B6 and D1, which are one question (scale classes).
- **Phase 7** (`phase-07-ours-kept-marked.md`): codex. 15 accept, 7 partial, 8 reject. Needs-human: none.

Totals: 102 accept, 64 partial, 70 reject. Two open questions need the human.

## Six hats

Each spec's `### Six hats` subsection holds the lines for bullets that touch it. The lines below cover bullets about the set as a whole. Every bullet in the report is reconciled either here or in a spec.

**White**
- The order the specs allow is 0, then 2, 1, 3, with 4 and 5 free after 0; 6 needs 0–5 and 7 needs 0–6. **accept**: verified against each spec's Depends on. This is the Workstreams table.
- Two needs-human items remain: Phase 5 B11 and Phase 6's scale-class question. **accept**: both are verbatim under "Needs the human". This review adds vetoes there and asks no new question.
- ADR-0002:12 and ADR-0003:9 are overturned. **accept**: verified, and both ADRs have an `## Amended 2026-10-12` paragraph (lines in Phases 0, 3 and 7).
- `CONTEXT.md:31-32` still lists five Window header buttons. **accept**: the entry has an amended note, and "Fan List buttons" is a new term (line in Phase 1).
- There is no ticket breakdown. **accept**: it is under "Not yet specified" and is the next step.
- The harness is missing and Chromium is cached. **accept**: verified (line in Phase 0).

**Red**
- The set will break at the joins between specs. **accept**: the joins are reconciled in the specs. Phase 0 case 7 now belongs to Phase 3. Phases 3 and 7 put the automation-restrict row in the Kebab. Phase 7 lists Mark as unread and Phone focus, and Phase 3 stops calling translate an extra. Phase 5's check is "unchanged by Phase 5". Phase 2's stale Online Fans lines are fixed, and so are Phase 7's AI seller chip and AI strip hosts.
- Phase 6 is out of date. **accept**: FI18–FI32, the Vault picker entry, `ThreadEmptyState`, the "not in git" note, the landmark note and the `#tbOpen` note are refreshed (lines in Phase 6).
- The quick reply and Phase 7's moves look like churn. **partial**: the quick reply stays as Phase 1's last ticket. Phase 7's moves shrink, because Phases 2 and 3 now place three extras at their final spot (lines in Phases 1, 2, 3 and 7).

**Black**
- The four clashes (phase-05:199 against phase-03:245, phase-00:296 case 7 against H9, Restrict at phase-03:158 against phase-07:27, and phase-07:175 missing three extras). **accept**: each one was checked against its cited lines and rewritten (lines in Phases 0, 3, 5 and 7).
- Phase 6 is stale. **accept** for the stale rows and notes. **reject** for the hand-copied snapshot and for the sidebar objection. **partial** for the 234-value lift (lines in Phase 6).
- Work beyond the plan: the quick reply is **partial** (Phase 1), Phase 7 hiding AI replies is **accept** (Phase 7), and Phase 2's `init_db` is **partial** (Phase 2).
- ASSUMPTION: about 46 tickets against a budget of 40. **partial**: no ticket slice exists yet, so 46 cannot be checked, and the 40 is not in the plan (`grep -n -i budget docs/plans/messages-pro-parity.md` finds nothing). If the slice runs over, the deferral order under Blue applies.

**Yellow**
- One component tree (ADR-0002), the offline harness, "not wired" and "—" instead of fakes. **accept**: no action, because these are strengths the specs already carry.
- Phases 4 and 5 stand alone. **accept**: they are Wave 1 (lines in Phases 4 and 5).

**Green**
- Order 0 → 5 → 4 → 2 → 1 → 3 → 6 → 7. **accept** with one change: the Split Inbox tickets slot between 3 and 6 (Recommended landing order).
- Move Split Inbox last. **accept** on order, rung 4, bounded by Phases 6 and 7 (line in Phase 2).
- Trim Phase 6 to PN2/PN4, D3 and the sweep, and hold the 234-value lift. **partial**: this is now the ticket order (Phase 6 D12). Holding the lift is rejected, because the plan binds it (plan:194-199) (line in Phase 6).
- Hold the quick reply. **partial** (line in Phase 1).
- Do the docs-only reconciliation first. **accept**: done in this run.

**Blue**
- Next step: reconcile, then slice tickets. **accept**: the reconcile is done, and slicing is the next step ("Not yet specified").
- Cut order: Split Inbox, then the Phase 6 lift, then Phase 7. **partial**: the plan names all three, so this is a deferral order for a short budget, not a cut (lines in Phases 2, 6 and 7).
- Park for the human: the ADR amendments, the glossary, B11, the scale-class question and the quick reply. **partial**: this run's invocation orders the ADR amendments and the glossary note (rung 2), so they are done, not parked. B11, the scale-class question and the quick reply veto are parked under "Needs the human".
- Gate: no UI ticket starts until Phase 0's self-test fails and its real run exits 0. **accept** (Workstreams; line in Phase 0).

**Ladder decisions on the four contested bullets**
- **Sidebar drawer (Phase 6 D3).** Kept, rung 1. plan:36 names the below-1024px rules, which D3 keeps. `docs/routes.md:40` describes the docked sidebar but the plan line does not freeze it. plan:196 needs three panes at 1280, and collapsing does not persist (`AppShell.tsx:32`). Flagged in Phase 6 D3.
- **Quick reply.** Kept as Phase 1's last ticket, rungs 1 and 5 (`docs/infloww-screens.md:243`). Parked for veto.
- **Split Inbox last.** Accepted, rung 4, landing after Phase 3 and before Phase 6.
- **Trim Phase 6.** Its order is accepted (rung 5). The lift is not held (rung 4: the scale-class answer can only widen it).

## Cut (YAGNI)

These are the Out of Scope entries that no Phase builds, merged where two specs list the same thing. Hand-offs between Phases are left out, because another Phase builds them.

**Pop-out window and shell**
- Restoring the last closed window's Creator on restart (P0, P1). This is desktop-app behaviour, and a browser has no restart.
- A window limit (P0). Infloww has none.
- Mapping Multi-Window to Electron windows (P0). It is not in the plan.
- Hiding the Buys & tips rail, toasts and assistant in the Pop-out window, and the rail's "popup" surface (P0). The plan names only the sidebar and the top bar.
- Pointing bell, rail, toast and Message dashboard links at `?window=1` (P0). The plan does not name them.
- Pane resizing and user-adjustable widths, and a fit check between 1024 and 1279px (P6). The plan names 1280 and 1440 only.
- Phone layout beyond what Phases 2–4 keep (P6). The responsive rules stay as they are.

**Window header and tabs**
- Deleting `AccountRoster*` (P1). The plan keeps the roster.
- Fan tab drag reorder, cross-device tab sync and per-tab Composer drafts (P1). None is in the plan or the Clone.
- The Clone's top-right translate selector `.tr-box` and window icon (P1, P6). Neither is in §3.3's header list.
- The SFW shortcut (P1). It belongs to the global top bar.
- The "Message withdrawn" notification's "View details" (P1). Its shape can only be seen in live data (floor 2).
- Idle mode (P1). No Phase names it.
- `.nlist` and the Clone's notifications sheet (P6). Phase 1 reuses `NotificationBell`.

**Fan List**
- The gallery icon in the list header, the "Unread tips" chip, the gear's "Show only" items and the row "×" (P2). They are not in the plan, or the Clone gives them no action.
- The "Needs reply" sort label (P2, P7). It is probably ours, and the app has no such label.
- Messages Basic's sorts (P2). They belong to a different screen.
- Binding Split Inbox groups to Employees, per-role permissions and server-side group filtering (P2). ADR-0004 rules them out, and OF has no group filter.
- A `subscribed_at` field for New (P2). Badges use only fields already fetched.
- Persisting Focus mode or the chosen group (P2). YAGNI until asked.
- Restyling the folder picker, paging Chat folders past 50, and hiding mass-exclude system lists from folder chips (P2). None is a parity element.

**Chat header and message list**
- New relay routes for star, pin, Report, Special offers and an online-fans statistics view (P3). The plan allows an endpoint only when a ticket proves it missing, so these render Not wired.
- The verified tick (P3). There is no verified field.
- The large PPV card `.ppv-card` (P3, P6). It would replace the tested media strip.
- A Gallery lightbox, Find as an anchored popover, and `ChatSearch`'s 12-page cap (P3). The Clone has no tile action, and Find reuses `ChatSearch` unchanged.
- `.typing-line` (P6). We have no typing indicator.

**Composer and Vault**
- "/" script search, the Manage scripts window and AI Copilot modes (P4). They are not in the target.
- Fixing the scheduled-send gaps, and unsend from the Vault picker (P4). Both need service changes the plan does not allow ("Needs the human").
- Per-media notes, release-form listing, "Aa" formatting, a reminder sound and translation targets other than English (P4). There is no store, no endpoint or no need.
- Upload from disk (P4). It was removed on purpose in `1ccd82f`.
- The calendar's list of scheduled sends (P4). The Scheduled chip already lists them.
- Vault Pro media statistics, and changes to the other vault pickers and composers (P4). The plan says "Only Messages Pro".
- The Vault picker's own Geometry and the Vault rules (P6). `VaultPicker` has 18 importers.

**Fan insights**
- Drag reorder of blocks, saved block order and saved collapse state (P5). They need per-Employee storage the plan does not ask for.
- The Lists quick editor, the Notes template and editing Creator notes (P5). There is no plan line, and the wiring is frozen.
- The help list's Profile fields, the PPV timeline's extra figures, the Spending power and Chargeback risk classifiers, the tiny line, the Vault history box and a purchase count in the Sales heading (P5, P6). They are not plan fields, or there is no data for them.
- Two defects in the frozen nickname and note wiring (P5). They are recorded but not fixed.

**Geometry and extras**
- Colours in the token module (P6). ADR-0001 keeps colour in `globals.css`.
- Clone styling of extras no Phase adopted, `.sheet-f`, `.pop input` and `.pop .pdot` (P6). No Region uses them.
- The typeface (P6). Sora stays, because a typeface is brand.
- An ESLint rule for magic numbers (P6). The vitest guard covers the rule.
- Measuring live Infloww (P6). Nothing leaves the machine.
- Flag-on PNGs, committed or not (P0, P6, P7). The flag-on runs are checks, and the committed shots stay flag-off.
- A new flag or one toggle per extra, a custom tooltip component, and generating the parity doc from code (P7). ADR-0003 and house precedent cover them.
- Extras outside Messages Pro, the gear's unlabelled options, and touch tooltips (P7). They are outside the plan or not labelled as extras.
- Relay or service changes for the flag (P7). The flag is client-side.

## Not yet specified

- **The ticket slice.** No spec breaks its Phase into tickets. The Visual loop is per ticket (plan:50-56), and the six-hats estimate of about 46 tickets cannot be checked until this exists. It is the next step.
- **The pop-up Clone pages** (plan:12-14: `growth-smart-messages.html`, `outreach-mass-message.html`, `analytics-message-dashboard.html`). The plan lists them as references for "pop-ups Messages Pro opens", but no spec measures the pages they stand for. Those pages are `/growth/smart-messages` (Phase 3's 📈), the New menu's Mass message (Phase 2) and the Message dashboard. plan:4-5 changes nothing a Phase does not name, so they are flagged here, not specced.
- **The Group chat button's dead self-close check for `/chat/` paths.** Phase 0 hands it to Phase 7 (`phase-00-pop-out-window.md`, Out of Scope), and Phase 7 does not take it (`grep -n self-close docs/spec/phase-07-*.md` finds nothing). It is dead code, so leaving it costs nothing.

## Open questions

These are the 25 sharpest ASSUMPTIONs, sharpest first. Each says what falls if it is wrong. Line numbers are as of this review.

1. **The Fan List buttons sit in the Fan List, not the Window header** (`phase-01:159`, flagged for veto). If wrong, Online Fans and Notifications move to the Window header. Phase 1's layout, Phase 2 gap row 6, Phase 6's `.big-btns` tokens, the glossary note and the "Fan List buttons" term all change.
2. **Infloww's Chat header button adds a Fan tab** (`phase-03:310`, F1). If wrong, ADR-0002's amendment is undone, H9 opens a Pop-out window again, and Phase 0's case 7 stays as written.
3. **"No magic numbers" means rules R1–R4, so scale classes stay** (`phase-06:470`, needs-human). If wrong, about 585 more classes in five modules move into tokens or `MP.ours`.
4. **Highest spend and PPV Avg stay page-bounded** (`phase-05:136`, needs-human B11). If wrong, they become "—" on a full page, or a relay change in `service/fans.py:1006-1011` is needed.
5. **plan:36 binds only the below-1024px rules** (`phase-06:479`). If wrong, D3 becomes "docked, collapsed by default on Messages Pro routes", and the 1280 three-pane rule holds only collapsed.
6. **The Kebab's Restrict posts with `?ack=false`** (`phase-03:390`). If wrong, Restrict sends the Fan a message, marks the chat read and hides it (`service/server.py:6568-6624`), all on a live account.
7. **Default-deny to the relay keeps the harness off OnlyFans** (`phase-00:233`, with `:238` on socket-layer refusal). If wrong, a harness run could reach OnlyFans, which breaks floor 2.
8. **Broadcast is an automation** (`phase-07:46`, ADR-0003 amended). If wrong, Broadcast moves to a flag-off overflow, and the amendment is undone.
9. **The AI reply countdown is status, not an extra** (`phase-07:54`). If wrong, it returns to `EXTRAS` behind the flag, and story 24 and assertion 9 flip back.
10. **All Models and Group chat are not automations** (`ADR-0003:7`, `phase-07:49`). If wrong, they are fully hidden without the flag, and the Window header's Extras overflow may have nothing to hold.
11. **Restrict, Block and Hide chats are wired, and only Report is Not wired** (`phase-03:313`, F2). If wrong, three Kebab rows render disabled, and their tests change.
12. **Phase 1 has no land-first fallback** (`phase-01:321`). If wrong (the human orders Phase 1 first), Phase 1 must be re-cut against `ChatList`.
13. **"Flag-on shows all" means reachable** (`phase-07:145`). If wrong, every overflow extra returns to its pre-parity spot with the flag on, and assertion 3 changes.
14. **The harness passes the caller's environment through** (`phase-06:506`, evidence blocked). If wrong, both flag-on sweeps (Phases 6 and 7) silently run flag-off until the harness gains a flag option.
15. **Errors that predate Phase 0 are Phase 0's to fix** (`phase-00:387`). If wrong, Phase 0's gate blocks on unrelated errors, or the fixes move to their own tickets.
16. **The sort default becomes "Newest first"** (`phase-02:190`). If wrong, the spend ranking stays the default, for Group chat too.
17. **The quick reply stays as Phase 1's last ticket** (`phase-01:229`). If vetoed, story 39, the Reply clause and two test cases leave Phase 1.
18. **The automation-restrict row stays in the Kebab** (`phase-03:338`). If wrong, it moves to the Extras overflow, and both Phase 3 M2 and Phase 7's Gap row change.
19. **Split Inbox lands as late as Phases 6 and 7 allow** (`phase-02:360`). If wrong, it lands in Wave 1, and the schema change reaches a deploy sooner.
20. **The Vault picker's shell follows the Clone's generic sheet** (`phase-04:41`). If wrong, rows 25–27 and Phase 6's shared SH tokens fall away.
21. **The Chat header hides its words below 886px** (`phase-06:486`). If wrong, the header wraps or clips at 1280 with Fan insights open.
22. **Star is Priority and pin is Pinned chat** (`phase-03:316`, F3). If wrong, pin opens "Pin a message" over the existing pin route.
23. **The row's owe dot belongs to the Owe reply extra** (`phase-02:218`). If wrong, it shows with the flag off as plain row status.
24. **Phase 7 marks four extras that no one names** (`phase-07:278`). If wrong, those four leave `EXTRAS` and the parity doc.
25. **The recommended landing order** (this file, Workstreams). If wrong, Phase 3 takes its F12 and F23 fallbacks, and Phase 5's check still holds.

Total: `grep -c ASSUMPTION docs/spec/phase-*.md` gives 31, 43, 38, 36, 39, 38, 35 and 42, which is 302 lines across the eight specs. The count is of lines that contain the word, so it includes the reconcile lines that mention one.

## Needs the human

Quoted verbatim from each spec. Items this review added are marked.

**Phase 1** (`phase-01-window-chrome-tabs.md`)
- `:159`: "ASSUMPTION: position by observation, so Online Fans and Notifications sit in the Fan List pane, not in the Window header. This is flagged for the human's veto, and is overturned if the human wants them in the Window header as the plan's wording reads."
- Added by this review: the quick reply veto. `:228`: "The quick reply is this Phase's last ticket, and it is separable. [...] A short budget can drop that ticket without touching the others, and the human can veto it".

**Phase 2** (`phase-02-fan-list-pane.md`)
- Added by this review: deploying the Split Inbox tickets changes the production schema. `:360`: "once a deploy runs it, `init_db()` adds `account_ai_config.split_inbox_json` to the production database at relay start (`service/db/engine.py:163-194`), and no code path drops it". Nothing in this run deploys. The deploy is the human's call.

**Phase 4** (`phase-04-composer-ppv-vault.md`)
- `:420`: "For the human: the one-field service change that would wire unsend is adding the latest `VaultSend.message_id` per media to the `GET /admin/vault/fan-history` response (service/server.py:9702–9728)."
- `:422-425`: "For the human: existing scheduled-send gaps found in review. None is introduced by this Phase, and the plan does not ask for them to be fixed." The gaps: "A scheduled send ("at") with two or more GIFs sends every GIF after the first at once (Composer.tsx:329–332)." "A GIF on a send scheduled more than 15 minutes out is dropped: the app sends `giphy_id` (app/hooks/useSendMessage.ts:309), but `_ScheduleMessageBody` has no such field (service/server.py:6117–6126)." "Scheduled sends carry no `replyToMessageId` (app/hooks/useSendMessage.ts:260–315, against :184 for an immediate send), and a refused schedule loses the quote, which `ChatSurface` clears before the send resolves (ChatSurface.tsx:1145)."

**Phase 5** (`phase-05-fan-insights-panel.md`)
- B11, `:259`: "B11 (Highest spend and PPV Avg are page-bounded, include pending payments, and change on Load more) — **needs-human**. Spec position: keep today's summary, because the plan freezes data wiring, and the number is real, not invented. Reviewer position: the labels read as lifetime figures, but `max_cents`/`avg_cents` cover only the loaded ledger page (`service/fans.py:1006-1011`). Load more grows that page (`FanDrawer.tsx:156-157`, `:571`), so Insights numbers change when the Employee pages Sales, and PPV Avg is not PPV Total ÷ count, because PPV Total is all-time. What settles it: the human picks one of (a) page-bounded as specced, (b) "—" whenever the page is full (`items.length === salesLimit`), or (c) a relay change to all-time max/avg in `service/fans.py:1006-1011`, which the plan allows only for a proven-missing endpoint. Help-center text defining Highest spend's window (H418759) would also settle it."

**Phase 6** (`phase-06-geometry-pass.md`)
- B6 and D1, the needs-human block at the end of its Review: "**needs-human: do Tailwind scale classes count as "magic numbers in JSX"?** (B6, D1)" "The spec's position: R1 rejects digits inside arbitrary values only. Scale classes (`gap-2`, `rounded-md`) stay as the house scale, except beside a token (R4), and every measured token must be read (part 4)." "Codex's position (both calls): a scale class is a number in JSX too. `w-80` or `p-4` in a component that skips the token passes the guard, so Clone Geometry can live outside the module (plan `:194-195`, ADR-0001:3). Codex would ban numeric and named-size Geometry utilities in scope." "The cost of codex's position: by the regex run over five scope modules, they hold about 585 such classes (FanDrawer 192, MessageList 173, Composer 150, ChatSurface 41, PinnedPanel 29). Each would move into a token or `MP.ours`, against 234 arbitrary values today." "What settles it: the human's reading of "no magic numbers in JSX", that is, whether a Tailwind scale step is a magic number."
- Added by this review: the sidebar reading. D3 (`:479`): "ASSUMPTION: plan:36 binds only the below-1024px rules, so D3 may change the sidebar from lg up on Messages Pro routes to meet plan:196's three panes at 1280. This is overturned if the human reads plan:36 as freezing the docked sidebar at lg and up".

**Phases 0, 3 and 7**: none open. Phase 7's request that the human amend ADR-0003 is resolved by this review's amendment.
