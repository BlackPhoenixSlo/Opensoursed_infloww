# Phase 02 — Growth pages match the bundle: Smart Messages, Scripts, Vault Pro, Tracking links

**Objective.** `/growth/smart-messages`, `/growth/scripts`, `/growth/vault-pro` and `/growth/tracking-links` each render the structure, labels, tabs, filters, columns, buttons and empty states of their Layout capture (`docs/infloww-layouts/<page>.md`). Every difference carries the "Inflowwww extra" label or the Not wired marker. Smart Messages' Automated Messages tab lists only per-Fan Triggers, beside Phase 2b's Mass Messages tab. Each page still reaches the Inflowwww behaviour it reached before.

## Problem Statement

An owner or chatter who knows Infloww opens the four Growth pages and none of them looks like Infloww. Smart Messages shows our old "Mass messages" / "Scheduled" tabs, an Auto-unsend card and two mass composers, where Infloww shows a list of triggered, one-to-one messages. Scripts shows our Templates card, where Infloww shows Tags, Sequences and a script manager. Vault Pro is our old `/vault` page with a long description, the import card and the review queue stacked on top of each other, where Infloww has a folder rail, media-type chips and an "Add media" action. Tracking links shows two stacked cards, where Infloww has "Links list" / "Dashboard" tabs with a filter bar and a metrics table. The previous sign-off graded the four Parity matrix rows (§3.5.1, §3.5.4, §3.5.5, §3.5.8) `unverified` because of this layout. The Nudge message, our closest equivalent of Infloww's Smart Messages, is only reachable from Legacy automation tabs. The operator cannot find it under the name Infloww uses for it.

## Solution

Each page is rebuilt from its Layout capture, the Dashboard bundle as read with REA, which wins over the Clone page (ADR-0013). The data under each page does not change. Existing panels move into the bundle's structure. A bundle control with no Relay read or write behind it is shown, but disabled and titled "not wired". Anything we keep that Infloww lacks sits under the "Inflowwww extra" label and never displaces an Infloww element (ADR-0003).

- **Smart Messages** gains the bundle's "Automated Messages" tab: the message list for per-Fan Triggers. The Nudge message is a row whose editor is the existing nudge configuration. The Delayed welcome is a row whose editor is the existing welcome message. Message on purchase and every other Trigger the capture shows appear in the Create message pop-up's Automated messages section and in the Trigger filter, Not wired. Phase 2b found that the bundle puts mass messages in a second parent tab of this same page, "Mass Messages" (`index.9f50f370.js` @14654355, as recorded in Phase 2b's spec), and mounts its `MassMessagesSection` there with `?tab=mass`. Phase 2b lands first and builds the page frame both Phases share: the header, the parent tab strip and the one Create message pop-up (bundle `xTitle:"Create message"` @14716722). This Phase fills the frame's two slots: the "Automated Messages" tab, in front of Phase 2b's tab, and the pop-up's Automated messages section. It leaves the frame, the Mass Messages tab, its key and its contents alone. Only if the capture records another placement do the mass tabs leave this page, and then only after Phase 2b has shipped them elsewhere, so they are never unreachable (ADR-0014).
- **Scripts** becomes the bundle's script manager. The saved replies are its scripts. Tags, Sequences, Import and Share are Not wired, because the store has no tag or sequence field.
- **Vault Pro** becomes the bundle's library: a creator chip, "Add media" (opening the existing import card), the existing folder rail, the media-type chips, search, sort, and the existing grid. The review queue and the AI and harvest tools move into a labelled Extras overflow.
- **Tracking links** becomes the bundle's "Links list" / "Dashboard" tabs over the existing OnlyFans tracking-link read. Columns and KPIs the read cannot fill are Not wired. Our custom redirect links stay as a labelled extra section.

## User Stories

Common to the four pages:

1. As an owner, I want each of the four Growth pages to show the same title, header controls, tabs, filters, columns, buttons and empty states as Infloww, in the same order, so that I can work in Inflowwww the way I work in Infloww.
2. As an owner, I want every control Infloww has that Inflowwww cannot perform to be visibly disabled and titled "not wired", so that I never think something was saved or sent when it was not.
3. As an owner, I want every Inflowwww control that Infloww lacks to be marked "Inflowwww extra" and kept out of Infloww's places, so that I can tell our additions from the parity surface.
4. As an owner, I want each page to keep reaching the behaviour it reached before (the nudge rules, the saved replies, the welcome message, the Vault import, browse and review, and the tracking-link reads and writes), so that the redesign removes nothing I use.
5. As a chatter whose role grants one of these pages, I want the page to keep working for me, and to answer 403 only for routes the page does not cover, so that Permission roles keep their meaning (ADR-0007, ADR-0012).
6. As an owner with several Creators, I want the bundle's creator chip or creator filter on each page to pick the Creator that every read and write below it uses, so that I never act on the wrong Creator.
7. As an owner on a phone, I want the four pages to stay usable at the Route walk's phone width, so that the redesign does not break the mobile views the walk already passes.
8. As a reviewer, I want each ticket to recheck its page against the bundle with REA before it closes, and to list every remaining difference with its label, so that an unlabelled difference is visible and rejectable.

Smart Messages:

9. As an owner, I want `/growth/smart-messages` to show the bundle's Smart Messages list (title, creator chip, "Learn", the create button, the tabs, the filter bar and the table) as the capture records them, so that the page reads like Infloww's. The header, the tab strip and the Create message pop-up are Phase 2b's frame; this Phase adds the Automated Messages tab, its filter bar and table, and the pop-up's Automated messages section.
10. As an owner, I want the tab that lists Automated Messages to show one row per configured per-Fan Trigger message, never a Mass message, so that Smart Messages means one Fan and one Trigger (ADR-0014).
11. As an owner, I want my Nudge message (the existing `nudge_online` configuration) to be a row with Trigger "Nudge", so that I find it where Infloww puts it.
12. As an owner, I want opening the Nudge row, or picking "Nudge" in the Create message pop-up, to open the existing nudge editor, with the same fields, preview and save as today, so that nothing about how the nudge works changes.
13. As an owner, I want the row's Status to reflect whether the nudge rule is on, using the bundle's status labels, so that I can see at a glance whether it runs.
14. As an owner, I want my welcome message (the existing OnlyFans welcome slot and its on/off switch) to be a row with Trigger "Delayed welcome", editable from that row and from the Create message pop-up, so that greeting new subscribers lives with the other per-Fan Triggers.
15. As an owner, I want "Purchased" (Message on purchase) to appear in the Create message pop-up and in the Trigger filter, disabled and titled "not wired", so that I can see Infloww's purchase follow-up exists and that Inflowwww does not send it yet.
16. As an owner, I want every other Trigger the capture shows (the bundle's `Triggers` table lists Not Purchased, Nearing expiry, Expired, Resubscribe and Birthday) to appear the same way, Not wired, unless an existing automation already sends exactly that per-Fan message, so that the catalogue is complete and nothing is faked.
17. As an owner, I want the filter bar's controls to filter the rows we have where our data supports it (search on the message text, Status, Trigger), and every other filter to be Not wired, so that the bar is honest.
18. As an owner, I want the table's Sent and Purchased columns to show a number only where an existing read reports it for that Trigger, and otherwise a Not wired cell, so that no count is invented.
19. As an owner, I want the bundle's "Mass Messages" parent tab (with the Priority mass message / OF mass message child tabs Phase 2b transcribes) to keep holding Phase 2b's `MassMessagesSection`, and `?tab=mass` to keep opening it, so that mass sending stays where the bundle puts it. If the capture records another placement, the tab says in one labelled line where mass messages moved, with a link to it, so that it is never a dead end.
20. As an owner, I want no mass message, mass composer, "Message online fans", Mass Nudge or Auto-unsend card inside the Automated Messages tab or its list, so that the Trigger list holds per-Fan Triggers only. They live in the Mass Messages tab (Phase 2b), and nothing is removed from the page before Phase 2b has shipped its home for it.
21. As an owner, I want the editors we reuse (the nudge editor, the welcome editor) to carry the "Inflowwww extra" label where they differ from Infloww's seven-step wizard, so that the wizard difference is labelled rather than hidden.
22. As a chatter granted Smart Messages, I want the Nudge and welcome rows to load and save for me, because their Relay routes join the page's entry in the page map, so that the page I was granted works.

Scripts:

23. As an owner, I want `/growth/scripts` to show the bundle's script manager (its sections, tabs and "+" menu as the capture records them, e.g. Tags, Sequences, Manage Scripts) instead of the Templates card, so that Scripts reads like Infloww's.
24. As an owner, I want my saved replies to be the scripts listed in the script manager, with title, text, price, media and tagged Creators, so that the scripts I already have are all there.
25. As an owner, I want to create, edit and delete a script with the existing saved-reply editor, opened from the bundle's add and edit controls, so that writing a script works as it does today.
26. As an owner, I want Tags, Sequences ("Add Sequence", "Create new", "Import from tag"), Import ("From Excel", "From other creators"), "Share to creators" and the per-script stats to be Not wired where the store has nothing behind them, so that I see Infloww's features without fakes.
27. As an owner, I want the welcome message to leave Scripts (it moves to Smart Messages' Delayed welcome) and the Scripts page to show no welcome editor, so that Scripts holds scripts only.
28. As a chatter, I want the composer's script and template picker to keep listing the same saved replies, so that the page change does not touch chatting.

Vault Pro:

29. As an owner, I want `/growth/vault-pro` to show the bundle's Vault Pro header ("Vault Pro", creator chip, "Learn", "Add media") as the capture records it, so that the page reads like Infloww's.
30. As an owner, I want "Add media" to open the existing Vault import card, unchanged inside, so that uploading works as it does today and Phase 5 can rework the card's Drive section independently.
31. As an owner, I want the left rail to be the existing folder rail (OnlyFans folders from the local mirror, with counts, search, create, rename, reorder) in the bundle's rail position and labels, so that folders sit where Infloww puts them.
32. As an owner, I want the media-type chips to be the bundle's chips, in the bundle's order and spelling, each driving the existing type filter, so that filtering by type matches Infloww.
33. As an owner, I want the bundle's search field and sort menu to drive the existing search and sort where they exist, and the options with no read behind them (for example "Most liked", "Highest tips", "Go to date") to be Not wired, so that I can see what works.
34. As an owner, I want the bundle's other controls (the "hide viewed or unlocked" toggle, the Grid / Table switch, the batch bar, media statistics) wired where an existing read or write backs them and Not wired otherwise, so that the page is complete and honest.
35. As an owner, I want the review queue, AI describe, the harvest and collect tools, the duplicates, disputes and flags reviews, and the pack picker behind one Extras overflow labelled "Inflowwww extra", so that our tools stay one click away without displacing Infloww's layout.
36. As an owner, I want the model picker's existing guarantees kept (switching Creator remounts the grid, the import card and the review queue, and a dropped session is said, not acted on), so that the redesign does not reintroduce the cross-Creator write the picker prevents.

Tracking links:

37. As an owner, I want `/growth/tracking-links` to show the bundle's "Links list" / "Dashboard" tabs, the attribution notice, the filter bar and "Create link" as the capture records them, so that the page reads like Infloww's.
38. As an owner, I want the Links list table to show my OnlyFans tracking links with the bundle's columns, filled from the existing read (name, date created, clicks, subscribers, and Subscription CVR computed from those two), and every column the read cannot fill marked Not wired, so that no metric is invented.
39. As an owner, I want "Create link" to open the bundle's "Create tracking link" pop-up, whose name field creates the link through the existing write, with channel source and List shown Not wired, so that creating a link works as it does today.
40. As an owner, I want the row Actions to follow the bundle ("Details", "Deactivate", promo cost edit), each wired only where an existing write does exactly that, and our existing delete kept as a labelled extra, so that I never deactivate when I meant to delete or the other way round.
41. As an owner, I want the Dashboard tab to show the bundle's KPI tiles and sections, with totals computed from the existing link read where they can be, and the rest Not wired, so that the Dashboard is honest.
42. As an owner, I want the "OnlyFans not reachable" and unverified share-URL notes kept, so that I still know when the numbers are missing or the link format is unconfirmed.
43. As an owner, I want my custom redirect links (internal `/t/<slug>` links with click analytics) kept as one section labelled "Inflowwww extra", so that I keep them without them looking like Infloww's.

## Implementation Decisions

- **Owns.**
  - Smart Messages: the Automated Messages tab (its filter bar, table and row editors) and the Create message pop-up's Automated messages section, both mounted in the slots of Phase 2b's frame, plus the welcome-message editor extracted from the Templates tab so that both pages can mount it. Phase 2b owns the frame (header, parent tab strip, the pop-up and its Mass messages section), the Mass Messages tab and `MassMessagesSection`. The one edit this Phase makes to the frame is to fill its slots and make `automated` the default tab.
  - Scripts: a new Scripts page component that the `/growth/scripts` route renders, reusing the saved-reply list and editor from the Templates tab.
  - Vault Pro: a Vault Pro page component that the `/growth/vault-pro` route renders. It moves the route's header and body out of the route file and reuses the Vault account provider, the Vault manage panel (layout only), the import card (placement only) and the review tab.
  - Tracking links: the tracking-links tab component, restructured into the bundle's two tabs, and the Growth tab page's header where the capture places the creator filter.
  - The `/growth/smart-messages` entry of the page map in the permissions module, and its pinning in the role-enforcement test.
  - The four Growth rows of the routes doc.
- **Interfaces.**
  - Each page component takes no props. It reads its Creator from the bundle's creator control, backed by the existing account source of that page: `AccountChips` / `useActiveAccounts` on Smart Messages and Scripts, `VaultAccountProvider` / `useVaultAccount` on Vault Pro (`app/app/growth/vault-pro/page.tsx:21,30`), and on Tracking links the header that already passes `accountId` to `TrackingLinksTab` (`app/components/growth/GrowthTabPage.tsx:65`), which keeps its `accountId` prop. The routes stay thin wrappers, as the Smart Messages route already is. The new components live at `app/components/growth/ScriptsPage.tsx` and `app/components/growth/VaultProPage.tsx`, next to `SmartMessagesPage.tsx` and `TrackingLinksTab.tsx`.
  - The welcome-message editor exposes one component, used by the Smart Messages Delayed welcome row. The Templates tab keeps its saved-reply list and editor, mounted by the Scripts page.
  - The nudge editor (`NudgeOnlineTab`, `useNudgeConfig`) is mounted unchanged inside the Smart Messages row editor. The Legacy `/automations` "Nudge Online" tab and the Auto Post panel still mount it as before.
  - Not wired controls use the house marker: `disabled`, `title="not wired"`, no handler (the Settings panel's `NotWired`, the Notifications page). A Not wired table cell or column header uses the same `title` and shows "—".
  - Extras use `EXTRA_LABEL` from `openinflowwwwExtras`.
- **Schema.** None. No table, field or migration.
- **Contracts.** No new Relay endpoint, and no change to an existing one. The pages use:
  - `GET/PUT /admin/nudge-config` and its preview, and `/admin/automation-rules`, for the Nudge message.
  - The welcome slot `GET /api/of/v2/messages/templates`, plus the `/users/me/reply-on-subscribe` toggle, for the Delayed welcome.
  - `/admin/saved-replies[/…]` for Scripts.
  - The existing `/admin/vault*`, `/admin/vault-ai*` and `/api/of/v2/vault*` routes for Vault Pro.
  - `/admin/of-tracking-links` and `/admin/tracking-links[/…/analytics]` for Tracking links.

  The page map's `/growth/smart-messages` entry gains `/admin/nudge-config`, `/api/of/v2/messages/templates`, `{_ME}/reply-on-subscribe` and `{_ME}/settings`. The last one is the welcome switch's read (`useReplyOnSubscribeFlag` → `GET /api/of/v2/users/me/settings`, `app/hooks/useTemplates.ts:151`); without it a chatter granted only Smart Messages gets a 403 on the Delayed welcome row's status. The welcome editor's vault and tag pickers are already covered by `_MASS` (`service/permissions.py:148-152`). Under Phase 2b's placement the mass panel stays on the route, so the entry keeps its mass prefixes (Phase 2b adds no page-map route; `/admin/mass-nudge` stays on Auto Post). Only if the mass panel leaves the route does the entry drop the mass prefixes, and then it keeps `/api/of/v2/messages/templates`, `/api/of/v2/posts/tagged-friend-users` and `*_PICKER`, which the welcome editor still needs. The Scripts entry is unchanged (additive).
- **Layout source.** For each page, the transcription source is its Layout capture, never the Clone (ADR-0013). Every control carries the capture's label verbatim. Its spacing and colours come from the capture's CSS citations, through the existing `--if-*` tokens where one exists (ADR-0009). Where the capture and the Inventory disagree, the capture wins on layout, and the Inventory still decides which controls exist (plan, "Match the Infloww layout").
- **Smart Messages list model.** The Automated Messages list is built on the client from the existing per-Creator reads: one row for the nudge configuration and one for the welcome slot, each present only when configured. Status maps "on" to the bundle's "Active" and "off" to "Canceled", the two labels the bundle's status set offers for a started and a stopped item, spelled as the capture spells them (the Inventory writes "Cancelled", `docs/infloww-screens.md:326`). Turning the rule back on returns the row to Active, which Infloww's terminal cancel does not allow (`docs/infloww-screens.md:316-317`); that difference carries the "Inflowwww extra" label in the recheck record. No list endpoint is added.
- **Trigger catalogue.** The Create message pop-up's Automated messages section and the Trigger filter list exactly the Triggers the capture records, in its order, with the capture's labels (the Inventory confirms only the menu label "Subscriber Welcome" for Delayed welcome, `docs/infloww-screens.md:285`). The pop-up itself and its Mass messages section (Priority mass message, OF mass message; bundle `massMsgList` @14707943, `automatedMsgList` @14708609, per Phase 2b) belong to Phase 2b, which lands first; this Phase fills the Automated messages slot Phase 2b leaves in it. Each Trigger entry is wired or Not wired:

  | Trigger | Wired to |
  |---|---|
  | Nudge | existing `nudge_online` / `nudge_online_fire` and its editor |
  | Delayed welcome | existing OnlyFans welcome slot and its editor |
  | Purchased (Message on purchase) | Not wired |
  | Not Purchased, Nearing expiry, Expired, Resubscribe, Birthday (or whatever else the capture shows) | Not wired |

  A Not wired Trigger has a Not wired item in the Create message pop-up and in the filter, and no row.
- **Message on purchase.** No new sender. `purchase_notifications` is scoped to resolution and ownership and sends nothing. No existing automation sends one Fan a message on a PPV purchase. Every new send-capable automation has to join the audited sender classification (`audience_include.AUDIENCE_SENDER_CLASSIFICATION`, enforced by its coverage test), which makes it a new sending path. So the purchase entry is Not wired, as the plan's fallback prescribes.
- **Mass tabs on Smart Messages.** The Smart Messages page never imports the mass components (`MassMessagesTab`, `ScheduledTab`, `LazyMassMessageComposer`, `MassNudgeTab`, `AutoUnsendPanel`) directly. Phase 2b's spec records the bundle placing mass messages in the page's "Mass Messages" parent tab, and Phase 2b lands first with `MassMessagesSection` mounted under the tab key `mass`. This Phase adds the "Automated Messages" parent tab in front of it, with its own key (`automated`), and makes it the default when `?tab=` is absent or unknown; `?tab=mass` (the Kebab menu's "Mass message statistics" link and the `next.config` redirects) still opens the Mass Messages tab. The Smart Messages ticket does not edit `MassMessagesSection` or anything it mounts. Fallback, only if the capture records another placement: the Mass Messages tab shows one line, labelled "Inflowwww extra", linking to Phase 2b's route, in the same change that removes the mass mount, and after Phase 2b has landed.
- **Vault Pro page.** The Vault account provider still wraps the whole page, and the `key={accountId}` remount still covers the manage panel, the import card and the review tab. "Add media" toggles the import card in place, or in the capture's pop-up position. It never edits the card's contents, which belong to Phase 5. The long description paragraph goes, unless the capture has one.
- **Tracking links page.** The Links list and Dashboard tabs live inside the tracking-links tab component. The account picker moves to the capture's creator-filter position. If that takes the tracking page out of the shared Growth tab page header, the route renders the tab component inside its own header, and the Growth tab page keeps its `tracking` key so that the assistant's link table check still holds. The OF Manager's tracking-links mirror route is not touched.
- **Legacy flag.** The Nudge message on Smart Messages shows with the Legacy flag off (ADR-0014, second ASSUMPTION). Nothing on the four pages is put behind the flag.
- **REA recheck.** Before its ticket closes, each page is compared against the bundle with REA: `inspect_web_page` or `capture_web_screenshot` on the bundle served on 127.0.0.1, or the chunk and CSS citations where the page will not render. The ticket appends its `## Phase 2 — <date> at <sha>` section to that page's recheck record, `.scratch/infloww-parity-round-2/rechecks/<page>.md` (Phase 0's recheck record contract): the REA tools run, and every remaining difference with its kind tag (`[layout]`, `[labels]`, `[states]`, …) and its disposition ("Inflowwww extra" or "not wired"). A difference without a label is a review rejection. The Layout captures stay pure bundle data and are not appended to.
- **Matrix regrade.** No edit to the Parity matrix. Each ticket writes its proposed row (the walk shot next to the REA capture, the grade and the Remaining gap) under `### Matrix row` in its recheck section. Phase 6 alone regrades rows §3.5.1, §3.5.4, §3.5.5 and §3.5.8 from it.

## Testing Decisions

- **Seam 1, the page component (vitest, jsdom).** Each of the four page components is rendered with `@/lib/relay` mocked and a fresh `QueryClient`, using two fixture Creators with placeholder names. One test file per page: `app/components/growth/SmartMessagesPage.test.tsx`, `ScriptsPage.test.tsx`, `VaultProPage.test.tsx` and `TrackingLinksTab.test.tsx`. Each test asserts external behaviour only:
  - the capture's labels, tabs and column headers appear in order;
  - every Not wired control is disabled and titled "not wired";
  - every extra carries `EXTRA_LABEL`;
  - a wired control calls the existing relay route it already used;
  - switching the creator control to the second Creator makes the next read or write carry that Creator's `account_id` (stories 6 and 36). On Vault Pro this also asserts the remount of the grid, the import card and the review tab.

  Per page:
  - **Smart Messages.** The Nudge row exists and opens the nudge editor. The Delayed welcome row exists. "Purchased" is Not wired. No mass label appears in the Automated Messages tab. "Automated Messages" is the default tab, and `?tab=mass` still opens the Mass Messages tab with `MassMessagesSection` (mocked) inside it.
  - **Scripts.** Saved replies list as scripts. Tags and Sequences are Not wired. There is no welcome editor.
  - **Vault Pro.** "Add media" reveals the import card. The type chips call the media read with the matching type. The extras sit inside the labelled overflow.
  - **Tracking links.** Both tabs render. Clicks, subscribers and CVR come from the read. Create calls the existing write. Redirect links sit in the labelled section.
- **Seam 2, the Relay page map (existing).** The role-enforcement test pins the Smart Messages entry's new routes: a chatter granted only Smart Messages reaches `/admin/nudge-config`, `/api/of/v2/messages/templates`, `/api/of/v2/users/me/reply-on-subscribe` and `/api/of/v2/users/me/settings` (story 22), and one denied it gets 403 on `/admin/nudge-config`. The test's nav-drift and every-route-mapped cases stay green. The nudge, tracking-link, account-isolation and purchase-notification tests run unchanged, as regression, with mocked OnlyFans only.
- **The walks.** The Route walk (`/tmp/route-walk-src/walk.py`, never committed; it walks every non-legacy nav href in four views, `walk.py:1,12`) shoots the four routes, and those shots sit next to the REA capture in each page's recheck section. `scripts/ui-shots.sh` shoots Messages Pro only (`scripts/ui-shots.sh:2,27-28`), so it runs as regression, not as this Phase's evidence. No test sends a live message. No fixture holds a real creator, fan or account name.
- **Prior art.**
  - Page component tests with relay mocks: `app/components/growth/autoFollowTargets.test.tsx`, `app/components/stats/ClockedHoursCard.test.tsx` (Not wired views), `app/components/settings/stickySave.test.tsx`.
  - The page map: `service/tests/test_role_enforcement.py`.
  - Regression: `service/tests/test_nudge_online.py`, `test_tracking_links.py`, `test_of_tracking.py`, `test_account_isolation_gate.py`, `test_purchase_notifications.py`.
- **Suite.** Each ticket extends `.scratch/infloww-parity-round-2/suite.sh` with a `relay` step running the tests it names, as the previous effort's suite does.

## Acceptance

```sh
cd <repo>
# Inputs from Phase 0 exist, and each page's recheck record carries this Phase's section with a proposed matrix row.
for p in growth-smart-messages growth-scripts growth-vault-pro growth-tracking-links; do
  test -f "docs/infloww-layouts/$p.md" || { echo "missing capture: $p"; exit 1; }
  sed -n '/^## Phase 2 /,/^## Phase /p' ".scratch/infloww-parity-round-2/rechecks/$p.md" 2>/dev/null | grep -q '^### Matrix row' || { echo "missing recheck: $p"; exit 1; }
done
# Smart Messages no longer imports the mass components directly.
! grep -Eq 'MassMessagesTab|ScheduledTab|LazyMassMessageComposer|MassNudgeTab|AutoUnsendPanel' app/components/growth/SmartMessagesPage.tsx
# Smart Messages keeps Phase 2b's Mass Messages tab (under the bundle placement Phase 2b recorded).
grep -qF "<MassMessagesSection" app/components/growth/SmartMessagesPage.tsx
# Scripts no longer renders the whole Templates card, nor the welcome editor, in the route or its page component.
! grep -q '<TemplatesTab' app/app/growth/scripts/page.tsx app/components/growth/ScriptsPage.tsx
! grep -Eq 'useUpsertWelcome|useToggleReplyOnSubscribe' app/components/growth/ScriptsPage.tsx
# Smart Messages' page map reaches the nudge config and the welcome routes.
python3 -I -c "import sys; s=open('service/permissions.py').read(); e=s.split('\"/growth/smart-messages\"',1)[1].split('\"/growth/smart-lists\"',1)[0]; sys.exit(0 if all(r in e for r in ('/admin/nudge-config','/api/of/v2/messages/templates','/reply-on-subscribe','/settings')) else 1)"
# The four page-component test files exist, then they and the whole effort suite pass.
for f in SmartMessagesPage ScriptsPage VaultProPage TrackingLinksTab; do test -f "app/components/growth/$f.test.tsx" || { echo "missing test: $f"; exit 1; }; done
env ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run components/growth components/vault --testTimeout=20000
sh .scratch/infloww-parity-round-2/suite.sh
# Relay tests: page map plus regression, all mocked. test_tracking_links and test_of_tracking need ALLOW_ANONYMOUS_ADMIN=1 (observed 2026-10-17: exit 1 "sign in required" without it, 0 with it).
for t in role_enforcement nudge_online tracking_links of_tracking account_isolation_gate purchase_notifications; do
  env ALLOW_ANONYMOUS_ADMIN=1 ./venv/bin/python "service/tests/test_$t.py" || exit 1
done
# Walks against the dev server on 127.0.0.1:3001: the Route walk shoots the four routes; ui-shots is Messages Pro regression.
ROUTE_WALK_OUT=/tmp/route-walk ./venv/bin/python /tmp/route-walk-src/walk.py
sh scripts/ui-shots.sh
# manual: the reviewer reads each page's Phase 2 recheck section beside its walk shot and rejects any difference without an "Inflowwww extra" or "not wired" label.
```

## Depends on

- **Phase 0.** It provides `docs/infloww-layouts/growth-smart-messages.md`, `growth-scripts.md`, `growth-vault-pro.md` and `growth-tracking-links.md`, the per-page input. `growth-smart-messages.md` also records the per-Fan Triggers the bundle shows and where it puts automated mass messages. Phase 0 also provides the baseline record (`.scratch/infloww-parity-round-2/baseline.md`), the recheck record contract and the corrected Clone pages.
- **Phase 2b, for the Smart Messages ticket only.** It provides the page frame (header, parent tab strip, the Create message pop-up with its two slots), `MassMessagesSection` already mounted on `/growth/smart-messages` under the "Mass Messages" tab with key `mass`, and its recorded placement (the bundle's Mass Messages tab on Smart Messages, or the My Automations fallback route). Both Phases edit `SmartMessagesPage.tsx`, so Phase 2b's change lands first and this ticket fills the slots. Phase 2b makes no page-map edit, so the Smart Messages page-map entry is this Phase's alone. The Scripts, Vault Pro and Tracking links tickets do not depend on it.

## Out of Scope

- **A new sender for Message on purchase, or for any other Trigger.** The plan rules out a new sending path. These become Not wired entries, not tickets.
- **Infloww's seven-step Smart Message wizard, Collections, follow-up sequences, the per-message Auto-unsend settings, and Smart Message Analytics** (`/growth/smart-messages/analytics`). The Relay cannot do these as Infloww does. They are Not wired where the capture shows a control for them, and otherwise absent.
- **Moving, rewriting or restyling the mass-message, scheduled, Mass Nudge or Auto delete code.** Phase 2b owns these.
- **The Vault import card's contents, including the Drive section.** Phase 5 owns them.
- **A tag or sequence field on saved replies, Excel import, sharing scripts to Creators, and script stats.** Each needs new schema or new writes. Not wired.
- **Tracking-link metrics OnlyFans' read does not return** (Promo costs, Earnings, Profit, CPC, EPC, CPS, AEPS, ROI, Source, Tag, List), deactivate, CSV export by email, and the 2-hour autosync. Not wired.
- **Editing the Parity matrix.** Phase 6 alone edits it, from the recheck records (coordinator ruling, 2026-10-17).
- **Editing the Inventory or the Clone pages.** The Inventory stays the control truth. Phase 0 fixes the Clone.
- **The other Growth pages** (Smart lists, Auto-follow, Profile promotion, Free trial links). They are not among the eight pages.
- **Live sends in any test or walk.**

## Further Notes

ASSUMPTION: The Delayed welcome Trigger is wired to the existing OnlyFans welcome slot (the welcome editor and its on/off switch), which moves to Smart Messages from Scripts. `send_welcome` stays as it is. Rung 5: the welcome slot is the only per-Fan subscribe greeting whose editor is reachable with the Legacy flag off. Correction from review: `send_welcome` does have an editor, the welcome lane of `BrainPanel` (preview shape `app/hooks/useAutomations.ts:207-257`), but it mounts only on the flag-only `/automations` page (`app/components/automations/AutomationsPanel.tsx:158`, `app/lib/nav.ts:140`). The OnlyFans slot is OnlyFans' own greeting, not an automation of ours, while `send_welcome` is a per-Fan automation polling new subscribers every ~5 min (`service/automations/send_welcome.py:6-15`). Overturned if the owner reads the plan's "each is wired to an existing automation or Not wired" strictly: then the row is wired to `send_welcome` (its BrainPanel lane mounted in the row editor), or it is Not wired and the welcome editor stays on Scripts with the "Inflowwww extra" label. Marked needs-human in the Review.

ASSUMPTION: The Automated Messages parent tab's key is `automated` and it is the default tab; `mass` stays Phase 2b's key. Rung 5, under Phase 2b's "Phase 2 adds its own key for Automated Messages and keeps `mass` as is". Overturned if the capture opens Smart Messages on the Mass Messages tab by default.

ASSUMPTION: "The send reuses the existing per-Fan send path; if no existing path can send it, Not wired" means that an automation which already sends on that Trigger must exist. A new automation that calls `of_client.send_message` counts as a new sending path. Rung 1 for the facts: `purchase_notifications` is "resolution + ownership only", and no purchase kind appears in `AUDIENCE_SENDER_CLASSIFICATION`. Rung 4 for the reading: Not wired is the reversible choice. Overturned if the owner wants a purchase-triggered automation built on the existing send path. That is a follow-up plan with its own audience classification and coverage test.

ASSUMPTION: The trigger list's Status maps the rule or slot being on to "Active" and off to "Canceled", from the bundle's status set (Scheduled, Active, Completed, Canceled). Rung 5. Overturned if the capture shows a different status field for Automated Messages.

ASSUMPTION: The plan's "/growth/scripts shows ladders with tabs" is read as the capture's structure (Tags, Sequences, Manage Scripts per the Inventory §3.5.5). "Ladders" are the bundle's Sequences, which are Not wired, because the ordered-script ladders were removed on 2026-08-19 (`ScriptsTab` header) and saved replies have no sequence field. Rung 2: the bundle wins over the Clone, whose "Script ladders" tab is Inflowwww (Inventory §3.5.5). Overturned if an existing saved-reply ordering (the composer's script cursor) is judged to be a sequence store. Then Sequences is wired read-only to it.

ASSUMPTION: A mass tab the capture shows on Smart Messages either mounts Phase 2b's surface or shows a labelled link to it, depending on the placement Phase 2b records. Rung 2: the owner's placement line, with ADR-0014's first ASSUMPTION. Overturned if the owner wants the bundle's mass tabs hidden entirely when Phase 2b places them under My Automations.

ASSUMPTION: Each ticket records its REA recheck and proposed regrade in `.scratch/infloww-parity-round-2/rechecks/<page>.md`, the one recheck location for the round, and never in the Parity matrix or the Layout capture; Phase 6 alone regrades the matrix. Rung 5 (coordinator ruling, 2026-10-17, adopting six-hats 13): Phase 6 regrades every row anyway, so per-Phase matrix edits are duplicate work, and the matrix carries uncommitted owner work. Overturned once the owner commits the matrix and wants tickets to regrade their own rows.

ASSUMPTION: Phase 2b owns the Smart Messages page frame (header, parent tab strip, the one Create message pop-up) and this Phase fills its two slots: the Automated Messages tab and the pop-up's Automated messages section. Rung 1 for the order (plan line 80 and Depends on put 2b first); rung 5 for the owner: the Phase that lands first builds the shared frame once (coordinator ruling 6, 2026-10-17). Overturned if the coordinator merges both Smart Messages tickets into one change.

ASSUMPTION: The Smart Messages page map entry gains the nudge and welcome routes, and the Scripts entry keeps its welcome routes (additive), so that no saved role loses access mid-change. Rung 4. Overturned if the owner wants Scripts' map trimmed to saved replies only.

ASSUMPTION: Subscription CVR (subscribers divided by clicks) and the Dashboard totals are computed on the client from the OnlyFans tracking-link read, and are not Not wired. Rung 5: they derive from fields the read returns and invent no number. Overturned if the capture defines CVR differently (for example per period). Then CVR is Not wired.

## Review

weaker (devils-advocate), 2026-10-17. Codex was tried first, both calls in parallel against the assembled workspace with a 900 s bound: both exited 1 with "You've hit your usage limit … try again at Nov 11th, 2026" and wrote no output (preflight had passed: `codex-cli 0.155.0-alpha.9.2`, "Logged in using ChatGPT"). The run header forbids spawning sub-agents, so the devils-advocate persona was run in this thread, confined to the workspace's paths plus mocked test runs. Because this thread had already read the draft, the blind call was not structurally blind. Rerun codex on this spec when the limit resets.

Blind call (alternatives, missing requirements, seam, falsifiers):

- B1. **accept.** Phase 2b (`phase-02b-auto-mass-messages.md`, Solution) found the bundle puts mass messages in a "Mass Messages" parent tab of Smart Messages (`index.9f50f370.js` @14654355; offset corrected 2026-10-17, was @14654094) and keeps them on this page. The draft assumed they leave it (Solution bullet, stories 19 and 20). That contradicts Phase 2b's "Removing the mass content from Smart Messages … Phase 2's step 4 does not apply" (2b Out of Scope). The Solution, stories 19 and 20, the Mass tabs decision and Depends on are rewritten: Automated Messages is added in front of 2b's tab, and the My Automations case is kept as the fallback.
- B2. **accept.** The draft said the "New Message" pop-up lists only Triggers. Phase 2b records that the bundle's pop-up has a Mass messages section and an Automated messages section (@14716722, `massMsgList` @14707943; corrected 2026-10-17, were @14716860 and @14707500). The Trigger catalogue now scopes itself to the Automated section.
- B3. **accept.** The tab keys were missing. Phase 2b fixes `?tab=mass` as the stable id, and the Kebab menu link and the `next.config` redirects depend on it. The Mass tabs decision now names `automated` as the default and keeps `mass`. This is flagged as an ASSUMPTION.
- B4. **reject.** Alternative: merge the Phase 2b and Phase 2 Smart Messages tickets into one change, since both edit `SmartMessagesPage.tsx` and the same page map entry. The plan orders them (Phase 2's Smart Messages ticket depends on 2b, plan line 80), and Depends on now says 2b lands first. A merge stays the coordinator's call (2b's last ASSUMPTION).
- B5. **reject.** Alternative: a Relay list endpoint for Automated Messages. No requirement needs it, and the plan forbids contract changes it did not ask for. The client-side composition from the existing reads stands.
- B6. **partial.** Falsifier: the Inventory says the Clone has no first-hand trigger catalogue and only "Subscriber Welcome" is confirmed as a menu label (`docs/infloww-screens.md:284-285`). It also has no "Not Purchased" trigger (lines 290-297, 515). The draft's catalogue already defers to the capture. The Trigger catalogue now cites the Inventory's confirmed label, and story 16's list stays an example the capture overrides.

Draft call (where the spec is wrong):

- D1. **accept.** The Acceptance relay loop fails on the current tree. Without `ALLOW_ANONYMOUS_ADMIN=1`, `test_tracking_links.py` exits 1 (2 cases "sign in required") and `test_of_tracking.py` exits 1 (5 cases). With it, both exit 0, and the other four pass either way (run 2026-10-17). The loop now sets the env.
- D2. **accept.** The walks were wrong. `scripts/ui-shots.sh` renders Messages Pro only (`scripts/ui-shots.sh:2`, OUTPUTS at :27-28) and never shoots a Growth route. The Route walk walks every non-legacy nav href in four views (`/tmp/route-walk-src/walk.py:1,12`). Testing Decisions and Acceptance now name the Route walk as the evidence and keep ui-shots as regression.
- D3. **accept.** Acceptance would pass with no new tests, because `vitest run components/growth components/vault` passes on today's tests. It now checks that the four named test files exist.
- D4. **accept.** The Scripts check grepped only the route file. A `ScriptsPage` that renders `<TemplatesTab />` whole, welcome editor included, would pass. The check now covers `ScriptsPage.tsx` and the welcome hooks.
- D5. **accept.** The page map missed a route. The welcome switch reads `GET /api/of/v2/users/me/settings` (`app/hooks/useTemplates.ts:151`), and the Smart Messages entry has only `{_ME}/stats` (`service/permissions.py:210-212`), so story 22's chatter would get a 403 on the Delayed welcome status. Contracts, seam 2 and Acceptance now add `{_ME}/settings`. The fragile `grep -A3` check is replaced by an entry-scoped check like Phase 2b's.
- D6. **accept.** Contracts said "drop the mass prefixes" without noting that the welcome editor's vault and tag pickers reach the Relay only through `_MASS` (`service/permissions.py:148-152`). The drop clause now keeps them.
- D7. **accept.** Stories 6 and 36 (creator choice drives every read and write; Vault remount on switch) had no seam, because seam 1 used one fixture Creator. Seam 1 now uses two Creators and asserts the switch.
- D8. **accept.** Interfaces said every page reads `AccountChips` / `useActiveAccounts`, but Vault Pro uses `VaultAccountProvider` (`app/app/growth/vault-pro/page.tsx:21,30`) and `TrackingLinksTab` takes an `accountId` prop (`GrowthTabPage.tsx:65`). Interfaces now name each page's account source and the new component paths.
- D9. **partial.** Status "off → Canceled": Infloww's cancel is terminal ("Editing is not allowed once active", `docs/infloww-screens.md:316-317`), and ours can be turned back on. The Inventory spells it "Cancelled" (:326). The mapping is kept as the closest label, with the capture's spelling and an extra-labelled difference in the Rechecks.
- D10. **partial.** The Delayed welcome ASSUMPTION said `send_welcome` "has no UI tab". It has one, the BrainPanel welcome lane (`app/hooks/useAutomations.ts:207-257`, mounted on the flag-only `/automations` page, `AutomationsPanel.tsx:158`, `nav.ts:140`). The fact is corrected. The choice itself is needs-human (below).
- D11. **reject.** The plan wants a matrix regrade per ticket, and the spec moves it to the Layout capture's `## Rechecks` for Phase 6 to copy. The header forbids touching `docs/infloww-parity-matrix.md` (uncommitted owner file). That binds, and Phase 2b defers the same way.
- D12. **partial.** Story 28 (the composer's picker keeps listing saved replies) has no new seam. The picker and `useSavedReplies` are unchanged code, and the whole vitest suite in `suite.sh` is its regression. No test is added.
- D13. **reject.** Scope creep from moving the welcome editor off Scripts (story 27)? The plan's Scripts goal is the bundle's script manager instead of the Templates card (plan line 70), which has no welcome editor. The move follows from the layout.

Phase 2b cross-check: after B1–B3 the specs agree on these points. The page holds both tabs, `MassMessagesSection` is Phase 2b's, `?tab=mass` is stable, Mass Nudge and "Message online fans" are in the mass tab as extras, and the bundle's "Nudge" is per-Fan `nudge_online` (2b, Mass Nudge decision). Neither spec touches the other's tab. Per-message Auto-unsend in the Smart Message editor (2b: `Unsend$1` @14979383 in `MessageEdit`; corrected 2026-10-17, was @14980997) stays Not wired here for Automated messages (Out of Scope), which 2b does not contradict.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):

- SH3 **accept.** This spec copied 2b's uncorrected offsets. The Solution, Trigger catalogue, B1, B2 and the 2b cross-check now cite the first byte of each token (@14654355, @14707943, @14708609, @14716722, @14979383), re-measured by Phase 2b's Review.
- SH8 **partial.** N2 (Message on purchase Not wired) stays needs-human below; nothing new is decided here. Premade Mass is 2b's (its Out of Scope, owner veto).
- SH9 **accept.** One recheck location: the `## Rechecks` sections appended to the Layout captures are replaced by `.scratch/infloww-parity-round-2/rechecks/<page>.md` (REA recheck, Matrix regrade, walks, Acceptance, ASSUMPTION). The frame overlap with 2b now has one owner (2b builds the frame and pop-up, this Phase fills the slots), and the page-map entry is this Phase's alone because 2b adds no route. Merge order for `PAGE_MAP` follows wave order (plan-review, Workstreams).
- SH13 **accept.** No matrix edit and no Acceptance line on the matrix file; the proposed rows go under `### Matrix row` in each recheck section, and Phase 6 alone regrades (coordinator ruling 2). D11's reject stands, now for this reason as well.
- SH14 **reject** (the fold). The plan orders the two tickets (plan line 80, rung 2) and the shared frame now has one owner, so the remaining overlap is the two slots. Premade Mass goes to the owner (2b).
- SH18 **accept.** The 2b offsets in this spec are corrected (SH3); the grading rule is Phase 6's.

needs-human:

- N1. **Delayed welcome binding.** Position A (spec): wire the row to the OnlyFans welcome slot. Its editor exists and works with the flag off. Position B: the plan says "each is wired to an existing automation or Not wired" (plan line 77). The slot is OnlyFans' own greeting, not our automation, while `send_welcome` is our per-Fan subscribe automation (`service/automations/send_welcome.py:6-15`) whose editor is legacy-only. The owner's reading of "existing automation" settles it: slot, `send_welcome`, or Not wired.
- N2. **Message on purchase.** Position A (spec): Not wired, because no automation sends a per-Fan PPV follow-up and a new one would be a new sending path that must join `AUDIENCE_SENDER_CLASSIFICATION`. Position B: the owner defines Smart Messages as "nudge and on-purchase messages" (plan line 9), and plan step 2 says "the send reuses the existing per-fan send path" (line 76). That reads as a purchase-triggered automation over `of_client.send_message`, fed by `purchase_notifications` (which names the bought message, `service/purchase_notifications.py:15-27`). As specced, half the owner's definition ships Not wired. The owner settles whether "no new sending path" forbids a new automation on the existing send call.
