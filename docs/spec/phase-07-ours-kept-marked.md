# Phase 07 — Ours, kept and marked

**Objective.** Every Inflowwww extra in Messages Pro stays reachable with "Inflowwww extra" in its tooltip, behind the Legacy flag if it is an automation or in its Region's Extras overflow if not, as one flag-off/flag-on render of the Messages Pro tree and one flag-on run of the visual harness prove, and `docs/messages-pro-parity.md` lists each extra under "Ours" and ends with the parity table for every Region of Phases 0–6.

## Gap table

"Today" means `main` at `1387781`, before Phases 1–5 move anything. The Destination column gives where the extra ends up. The Tooltip column gives the exact first line of the tooltip. The plan names eight extras:

| Extra | Today (`file:line`) | Automation? | Destination | Tooltip |
|---|---|---|---|---|
| AI strip | `app/components/chat/ChatSurface.tsx:919-923` mounts `AiStatusStrip` (`app/components/chat/AiStatusStrip.tsx:260`) under the Fan's name. It is already gated by `useLegacyAutomations()` (`ChatSurface.tsx:128`). | yes (plan Phase 3) | flag: Chat header, a band under its row (Phase 3 H14) | `Inflowwww extra — AI strip` |
| Persona button | `ChatSurface.tsx:1004-1006` mounts `ModelInfoButton` (`app/components/chat/ModelInfoButton.tsx:100`, title "Persona" at `:149`). It is not gated. | yes (plan Phase 3) | flag: Chat header, after the Infloww icons | `Inflowwww extra — Persona button` |
| Scheduled chip | `ChatSurface.tsx:930` mounts `ScheduledForChat` (`app/components/chat/ScheduledForChat.tsx:22`). It renders a "🕐 N" button (title at `:55`) and renders nothing when the Fan has no direct queued send (`:47`). It is not gated. | no (ADR-0003, ASSUMPTION below) | overflow: Chat header | `Inflowwww extra — Scheduled chip` |
| Owe reply | `app/components/chat/ChatList.tsx:874-879` puts the "↩ Owe reply" chip in the filter row. Its client-side filter is at `:55` and `:285-303`. It is not gated. | no (plan Phase 2) | overflow: Fan List | `Inflowwww extra — Owe reply` |
| Broadcast | Not in Messages Pro today. The Clone's "New" menu item (`ui-redesign/infloww-exact/messages.js:1630`) opens `outreach-broadcast.html`. That page opens on the `nudge_online` master switch (`outreach-broadcast.html:639`, `outreach-broadcast.js:246`), also edits Mass Nudge (`outreach-broadcast.html:764-766`), and lists the rule kinds `nudge_online`, `mass_nudge` and `online_blast` (`outreach-broadcast.js:287`). Our counterparts are the "👋 Nudge Online", "📣 Mass Nudge" and "📡 Blast Online" tabs (`app/components/automations/ReadyMadePanel.tsx:64-66`). A tab is chosen with `?ready=<tab>` (`useTabParam`, `ReadyMadePanel.tsx:121`). They are reachable only under `/automations`, which answers 404 with the flag off (`app/proxy.ts:16-20`, `app/lib/nav.ts:128`). | yes (ASSUMPTION below) | flag: an item at the end of the Fan List's "New" menu, linking to `/automations?ready=nudge_online` | `Inflowwww extra — Broadcast` |
| Group chat | The Chat header "👥" `GroupChatButton` (`ChatSurface.tsx:994`, defined at `:1214`, title "Add to group chat tab" at `:1258`). There is no Window header yet. The Clone's header button is `ui-redesign/infloww-exact/messages.html:612-614`. | no (ADR-0003, ASSUMPTION below) | Window header button: overflow (Window header) with the flag off, the header itself with the flag on (ADR-0003, Phase 1). Chat header "👥": overflow (Chat header). | `Inflowwww extra — Group chat` |
| Free previews | `app/components/chat/Composer.tsx:631-657` renders the "previews − N/M +" stepper in the attachment strip, shown only with a price and at least one attachment (`:195`, `:200`). Tile tooltips are at `:685` and `:737`. It is not gated. | no (plan Phase 4) | overflow: Composer | `Inflowwww extra — Free previews` |
| All Models | `AccountRoster` (mounted at `app/app/messages-pro/page.tsx:195`) renders `AllModelsRosterIcon` at `app/components/inbox/AccountRoster.tsx:224` and `:247` (title "All models", `AccountRosterIcon.tsx:226`), and `AllModelsBlock` in the expanded roster (`AccountRosterExpanded.tsx:39`, `:54`, label at `:85`). The Clone's header tab is `messages.html:589-591`. | no (ADR-0003, ASSUMPTION below) | overflow (Window header) with the flag off, the header itself with the flag on (ADR-0003, Phase 1, which also removes the roster from Messages Pro) | `Inflowwww extra — All Models` |

The repo also has these extras in Messages Pro, which the plan does not name. The plan's goal is "keep our additions as clearly marked extras", so they are specced here and flagged:

| Extra | Today (`file:line`) | Automation? | Destination | Tooltip |
|---|---|---|---|---|
| Generated profile note | `app/components/chat/FanDrawer.tsx:402` mounts `ProfileCard` (`:1707`), headed "AI profile" (`:1730`) and filled by gen_info (`:1746`). `docs/infloww-screens.md` §3.3 tags it ours. | yes (ASSUMPTION below) | flag: Fan insights | `Inflowwww extra — Generated profile note` |
| AI seller chip | `FanDrawer.tsx:360` mounts `AiSellerChip` (`:42`), which reads the AI chatter's open offers. | yes (ASSUMPTION below) | flag: Fan insights, after the Notes block in the Insights tab (Phase 5) | `Inflowwww extra — AI seller chip` |
| Persona claims | `FanDrawer.tsx:495` mounts `PersonaClaims` (`app/components/chat/PersonaClaims.tsx:88`): the claims block of the AI chatter's prompt (`:4-16`). | yes (ASSUMPTION below) | flag: Fan insights | `Inflowwww extra — Persona claims` |
| Automation restrict | Kebab items "Auto-restricted" (`app/components/chat/ChatActionsMenu.tsx:252`) and "Restrict from automations" / "Allow automations" (`:259`). | yes (ASSUMPTION below) | flag: Kebab menu, after the Infloww items | `Inflowwww extra — Automation restrict` |
| Mass exclude | Kebab items for MASSppvEXCLUDE and MASSdmEXCLUDE (`ChatActionsMenu.tsx:266`, `:280`), plus the same two toggles in Fan insights (`FanDrawer.tsx:500-503`). The manual Mass message composer honours MASSPPVEXCLUDE (`app/components/compose/MassMessageComposer.tsx:254-266`). | no (ASSUMPTION below) | Kebab copies: overflow (Chat header). Fan insights copies: overflow (Fan insights), where Phase 5 puts them (`docs/spec/phase-05-fan-insights-panel.md:143-147`). | `Inflowwww extra — Mass exclude` |
| Mark as unread | Kebab item "Mark as unread" (`app/components/chat/ChatActionsMenu.tsx:233`), which deletes the chat's read mark (`:7`). Infloww's kebab has no such item (C[H262067]). Phase 3 moves it to the Chat header Extras overflow (`docs/spec/phase-03-chat-header-message-list.md`, M2 and F10). It is not gated. | no (Phase 3 F10) | overflow: Chat header | `Inflowwww extra — Mark as unread` |
| Phone focus | The "👁 focus" toggle in the Chat header (`ChatSurface.tsx:930-947`), `lg:hidden`, which strips the header for the phone. Phase 3 moves it to the Chat header Extras overflow, still below lg only (H13). It is not gated. | no (Phase 3 H13) | overflow: Chat header. CSS hides it from lg up, and jsdom keeps it in the DOM | `Inflowwww extra — Phone focus` |

Phases 2, 4 and 5 add these extras and hand them to this Phase's catalogue:

| Extra | Source | Automation? | Destination | Tooltip |
|---|---|---|---|---|
| Quick emojis | Phase 4 puts the quick emoji row in the Composer's Extras overflow and asks Phase 7 to list it (`docs/spec/phase-04-composer-ppv-vault.md:417`). | no (Phase 4) | overflow: Composer | `Inflowwww extra — Quick emojis` |
| At presets | Phase 4 keeps the "at" presets (+5, +10, +15, +30, +60 min) in the same overflow as an extra (`phase-04-composer-ppv-vault.md:205`, `:417`). They fill "at" without sending (`Composer.tsx:547-551`). | no (Phase 4) | overflow: Composer | `Inflowwww extra — At presets` |
| Fan identity | Phase 5's Fan insights Extras overflow, item 1: avatar, name, @username, Creator label · id (`docs/spec/phase-05-fan-insights-panel.md:143-147`). | no (Phase 5) | overflow: Fan insights | `Inflowwww extra — Fan identity` |
| Extra Fan stats | The same overflow, item 2: Last message in, Last seen, Subscribed at, Renewed at, Expires or Expired, and Posts. | no (Phase 5) | overflow: Fan insights | `Inflowwww extra — Extra Fan stats` |
| Unsold PPVs | The same overflow, item 4: Unsold PPVs sent, with "Send to chat". | no (Phase 5) | overflow: Fan insights | `Inflowwww extra — Unsold PPVs` |
| Extra sort orders | Phase 2 puts Amount spent, Spend + unread on top and Spend + recency in the Fan List Extras overflow, each titled "Inflowwww extra" (`docs/spec/phase-02-fan-list-pane.md:67`, `:186-189`). Today they are at `ChatList.tsx:804-807`. | no (Phase 2) | overflow: Fan List, one entry per order | `Inflowwww extra — Extra sort orders` |

Not an extra: the Lines picker. Phase 4 makes `LinesPicker` the Composer's "AI" pill, an Infloww control, which is also how the Clone wires it (`docs/spec/phase-04-composer-ppv-vault.md:175`, `:191`; `messages.js:1938`). The Composer's "AI" button is Infloww's AI Copilot, which suggests replies and never sends (`docs/infloww-screens.md:235-236`; CONTEXT.md:158-159). Gating it would remove the Infloww "AI" pill with the flag off, so this Phase leaves it alone.
ASSUMPTION: the Lines picker is Infloww's "AI" pill, not an extra. This is overturned if the human treats its gen_info lines as an automation surface. In that case Phase 4's "AI" pill needs another source before `LinesPicker` can go behind the flag.

ASSUMPTION: Broadcast is an automation, so it goes behind the flag as a "New" menu item, not into an overflow. The Clone's Broadcast page edits the `nudge_online`, `mass_nudge` and `online_blast` rules (`outreach-broadcast.js:287`). Each of our counterparts is an automation tab under the flag-only `/automations` (`ReadyMadePanel.tsx:64-66`), so a broadcast entry visible with the flag off would link to a 404. This applies ADR-0003's own overturn clause ("overturned if the queue they show is automation-driven") to its broadcast assumption. It is overturned if the human means a manual send by "broadcast". In that case it goes into the Fan List overflow and links to Smart Messages.
ASSUMPTION: Broadcast links to `/automations?ready=nudge_online`, the tab for the rule the Clone's Broadcast page opens on (`outreach-broadcast.html:639`, `outreach-broadcast.js:246`). `useTabParam` already reads `?ready=` (`ReadyMadePanel.tsx:121`). This is overturned if the human wants Broadcast to open Mass Nudge or Blast Online.
ASSUMPTION: the Scheduled chip is not an automation (ADR-0003). Two pieces of evidence support this. The chip shows only direct one-Fan sends (`ScheduledForChat.tsx:31-33`), and `ui-redesign/infloww-exact/INFLOWW_REA_FEATURE_INVENTORY.md:45-46` says "`scheduled_send` = a 'send later' clock in the composer, not an automation". This is overturned if automations queue one-Fan sends that the chip shows.
ASSUMPTION: All Models and Group chat are not automations, and they return to the Window header with the flag on (ADR-0003's reading of Phase 1). This is overturned if the human meant them to be fully hidden without the flag.
ASSUMPTION: the Chat header "👥" is a second entry point of Group chat. It moves into the Chat header overflow under both flag states. This is overturned if Phase 3 already removed it, or if the human wants it back in the Chat header with the flag on.
ASSUMPTION: the Generated profile note, AI seller chip, Persona claims and Automation restrict are automations, because each one shows or steers the AI chatter, gen_info or the automation skip list. This is overturned item by item if the human treats one as a manual tool, in which case that item moves into its Region's overflow.
ASSUMPTION: Mass exclude is not an automation, because the manual Mass message composer uses the same list. Its Kebab copies move into the Chat header overflow. Its Fan insights copies stay in the Fan insights overflow, where Phase 5 puts them, because ADR-0003 keeps every non-automation extra visible in its Region's overflow. This is overturned if the human wants a single entry point, in which case the Kebab copies leave the Chat header overflow.
Not an extra: the AI reply countdown. `ChatSurface.tsx:785-790` appends every server-scheduled job to the Thread as a pseudo-row, and an `ai_reply` job renders "🤖 AI reply · <time> (in N min)" or "🤖 writing…" with the title `AI_PAUSE_TITLE` (`app/components/chat/MessageList.tsx:1631-1632`, `:1649-1653`). It is status text with no control: the job is ai_chatter's own deferred reply and "it is not cancellable" (`app/hooks/useServerScheduledSends.ts:28-31`). The Legacy flag gates only UI, and "No backend code is affected" (`docs/routes.md:73`), so with the flag off the AI chatter can still answer. Hiding the row would let an Employee answer a Fan the AI is about to answer. The row stays in both flag states, unchanged, and the parity table's Message list row records it in its Ours cell.
ASSUMPTION: the AI reply countdown is read-only status, not an extra, the same as the read-only free-preview text (Out of Scope). Showing it changes nothing in the app (rungs 1, 4 and 3). This is overturned if the human wants it hidden with the flag off, in which case it returns to `EXTRAS` as an automation extra with the host `Message list`.
The three extra sort orders already sit in the Fan List Extras overflow: Phase 2 puts them there from the start, as plan:30 asks (`docs/plans/messages-pro-parity.md:30`; `docs/spec/phase-02-fan-list-pane.md`, story 13 and the sort decision). This Phase only checks their label. The sort control still shows the name of the active order.

## Problem Statement

Once Phases 1–5 have rebuilt each Region to match Infloww, an Employee who knows Infloww still cannot tell which controls are Infloww's and which are ours. Nobody can check two claims in one place: that with the Legacy flag off the screen shows no extra outside a "+", and that with the flag on nothing we built was lost. Each Phase moved only the extras it knew about. Some extras sit in Regions whose Phase never named them, such as the Kebab menu's automation items and Fan insights' AI cards. Those would stay in place, unmarked, and keep displacing Infloww's layout. Contributors also have no single page that says how close each Region is to Infloww, or what we added on top of Infloww.

## Solution

Every Inflowwww extra in Messages Pro gets the same tooltip first line, "Inflowwww extra — <name>". Automation extras render only when the Legacy flag is on. Every other extra sits in its Region's Extras overflow, a "+" button named "Inflowwww extras". With the flag off, an Employee sees Infloww's Messages Pro plus a few "+" buttons. With the flag on, an Owner gets every extra back, and no Infloww control moves. A single test renders the whole Messages Pro tree twice, with the flag off and on, and fails if any extra leaks, goes missing or loses an entry point. The visual harness runs once more with the flag on, so that restored extras cannot push, wrap or clip an Infloww element unseen. `docs/messages-pro-parity.md` gives each extra a one-line entry under "Ours" and ends with a parity table that grades every Region of Phases 0–6 as done, partial or ours-only.

## User Stories

1. As an Employee who knows Infloww, I want Messages Pro with the flag off to show no Inflowwww extra outside a "+" overflow, so that the screen reads as Infloww's.
2. As an Employee, I want Owe reply, the Scheduled chip, Group chat, Free previews, All Models, Mass exclude, Mark as unread, Phone focus, Quick emojis, the At presets, Fan identity, the extra Fan stats, Unsold PPVs and the extra sort orders to stay reachable from their Region's Extras overflow with the flag off, so that I lose no tool I used before.
3. As an Owner who runs the legacy automations, I want every extra available with the flag on, including the AI strip, Persona button, Broadcast, Generated profile note, AI seller chip, Persona claims and Automation restrict, so that my workflow is unchanged.
4. As an Owner, I want automation extras with the flag off to be missing from the page, not just hidden with CSS, so that no control points at the flag-only `/automations` route, which answers 404.
5. As an Employee, I want every extra's tooltip to start with "Inflowwww extra — <name>", so that I can tell our additions from Infloww's controls.
6. As an Employee, I want an extra's old tooltip text to stay on the line under that label, so that the tooltip still says what the control does.
7. As an Employee using a screen reader, I want every Extras overflow trigger to have the accessible name and tooltip "Inflowwww extras", so that I know what the "+" holds and do not confuse it with the Creator tabs "+".
8. As an Employee, I want a Region to show no Extras overflow when it has nothing to show (for example the Window header with the flag on), so that an empty "+" never takes space from an Infloww element.
9. As an Employee, I want turning the flag on to add extras without removing or reordering any Infloww control in any Region, so that no extra displaces an Infloww element.
10. As an Owner, I want Broadcast at the end of the Fan List's "New" menu when the flag is on, linking to the Nudge Online tab of the automations page, so that I can still reach the online broadcast from Messages Pro.
11. As an Employee, I want Group chat reachable both from the Window header (or its overflow) and from the Chat header overflow, so that "add this Fan to the group tab" still works.
12. As an Employee, I want Mass exclude in the Chat header overflow and the Fan insights overflow with the flag off, so that I can keep a Fan out of manual mass PPVs, which honour MASSPPVEXCLUDE.
13. As an Owner, I want the Kebab menu's automation items (Auto-restricted, Restrict from automations) to come after the Infloww items when the flag is on, so that the Kebab keeps Infloww's order.
14. As a maintainer, I want one list in code of every extra and whether it is an automation, so that the audit test and the parity doc use the same decisions.
15. As a maintainer, I want one test that renders the whole Messages Pro tree with the flag off and with it on and checks stories 1–12 and 24, so that a later change that leaks or drops an extra fails the suite.
16. As a maintainer, I want no extra deleted (its component, hook and relay calls all stay), so that turning the flag on restores it and the plan's "No extra is deleted" holds.
17. As a contributor, I want `docs/messages-pro-parity.md` to give each extra a one-line "Ours" entry with its name, Region, placement and what it does, so that I know what we added and where it went.
18. As a contributor, I want the doc to end with the parity table (Region → Clone evidence → Ours → done / partial / ours-only) covering every Region of Phases 0–6, so that I can see how close each Region is to Infloww.
19. As a reviewer, I want the doc to state the done / partial / ours-only rule, so that two people grade a Region the same way.
20. As a reviewer, I want every partial row to name what is still missing (a `VISUAL GAP:`, a "not wired" control, a "—" field), so that the next ticket is obvious.
21. As a phone user below 1024px, I want the Extras overflows to work inside the one-pane layout, so that the responsive rules in `docs/routes.md` still hold.
22. As an Owner, I want the flag read exactly as today (per request in the root layout, handed down by `FlagsProvider`), so that no new switch, rebuild or backend change is needed.
23. As a maintainer, I want typecheck, lint (0 errors), the full test run and the screenshot harness (flag on, then flag off) all green when this Phase lands, so that the closing Phase leaves the effort releasable.
24. As an Employee, I want my own Timed message rows (with their cancel button) and the AI reply countdown to stay in the Message list whatever the flag, so that I can cancel what I queued and do not answer a Fan the AI chatter is about to answer.

## Implementation Decisions

- **Owns.**
  - New: an extras module in `app/lib` (named for the glossary term, `openinflowwwwExtras`), the extras audit test beside Phase 0's windowed test in the Messages Pro route folder, and `docs/messages-pro-parity.md`.
  - Modified, after Phases 0–6 land, and only for tooltips, flag checks and mount points:
    - the Window header (Phase 1)
    - the Fan List header, filters, sort menu, "New" menu and Extras overflow (Phase 2)
    - the Chat header in `ChatSurface`, including `GroupChatButton`
    - the Kebab menu (`ChatActionsMenu`)
    - `AiStatusStrip`, `ModelInfoButton` and `ScheduledForChat`
    - the Composer chrome and its Extras overflow (Phase 4)
    - Fan insights (`FanDrawer` with `ProfileCard`, `AiSellerChip`, `PersonaClaims`, and the items of its Extras overflow, Phase 5)
    - each Region's Extras overflow trigger (its label only)
- **Interfaces.** The extras module exposes:
  - `EXTRA_LABEL`: the literal "Inflowwww extra".
  - `EXTRAS_OVERFLOW_LABEL`: "Inflowwww extras", the accessible name and tooltip of every Extras overflow trigger.
  - `EXTRAS`: the twenty-one extras from the Gap tables, each with its name, whether it is an automation, and its hosts with the flag off and on. `ExtraName` is the union of the names, so a misspelt extra fails typecheck. A host is listed once per element the fixture Fan renders there, so an extra with two entry points lists both. Group chat is `off: ["Window header overflow", "Chat header overflow"]` and `on: ["Window header", "Chat header overflow"]`, and every automation extra has `off: []`.
  - `extraTitle(name, detail?)`: returns the tooltip, with the first line `Inflowwww extra — <name>` and the control's old tooltip (if any) as the second line.

  ```ts
  type Host =
    | "Window header" | "Window header overflow"
    | "Fan List overflow" | "New menu"
    | "Chat header" | "Chat header overflow" | "Kebab" | "Message list"
    | "Composer" | "Composer overflow"
    | "Fan insights" | "Fan insights overflow";
  type Extra = { name: ExtraName; automation: boolean; off: readonly Host[]; on: readonly Host[] };
  function extraTitle(name: ExtraName, detail?: string): string;
  ```

  The owning components change in three ways only: their `title`, a flag check for automation extras, and the mount point for overflow extras. Their props and behaviour stay the same.
- **Schema.** None. The flag is client-side, and no relay or service code changes.
- **Contracts.**
  - Tooltip: the first line is exactly `Inflowwww extra — <name>`, using an em dash with a space on each side as in the house tooltips (for example `ChatSurface.tsx:944`). It is carried by the `title` attribute, as every Messages Pro control does today.
  - Extras overflow trigger: a "+" button whose accessible name and tooltip are both "Inflowwww extras". It reveals its Region's extras the way the owning Phase built it: a menu, or in Fan insights Phase 5's collapsible section (`docs/spec/phase-05-fan-insights-panel.md:143`). It renders only when its Region has at least one extra to show. If Phases 1–5 used another label, this Phase renames it. Keyboard access, dismissal and focus belong to the Phase that built the overflow.
  - Flag: unchanged. Server code calls `legacyAutomationsEnabled()`, and client components call `useLegacyAutomations()` under `FlagsProvider`.
  - Parity doc: under the title, one line `` Graded at `<commit>` `` names the commit that the grades describe. `## Ours` holds one bullet per extra, in the form `- **<Name>** — <Region>; <behind the Legacy flag | in the <Region> Extras overflow>; <one line>.` The last section is `## Parity table`, with columns `| Region | Clone evidence | Ours | Status |`. Status is exactly `done`, `partial` or `ours-only`.
- **Gating.** An automation extra renders nothing when `useLegacyAutomations()` is false, at its mount point or by an early return (house precedent: `ChatSurface.tsx:919`). CSS hiding does not count.
- **Order.** Extras always come after a Region's Infloww controls. Turning the flag on appends them and never inserts one between Infloww controls.
- **No deletion.** Every extra's component, hook and relay call stays. Both entry points of Mass exclude and of Group chat stay.
- **Styling.** The overflow trigger and menu take their sizes from Phase 6's Messages Pro token module and their colours from the existing Tailwind tokens. This Phase adds no new dependency and no relay endpoint.
- **Parity doc.**
  - The doc is written by hand from each Phase's result (Gap table, `VISUAL GAP:` lines, the "not wired" list and the harness report).
  - Region rows: Pop-out window, Deep link, Window header, Creator tabs, Fan tabs, Fan List, Split Inbox, Chat header, Message list, Composer, Vault picker, Fan insights and Geometry. There are also two ours-only rows: Phone layout and Extras overflow.
  - Clone evidence is the Clone selector or `file:line` from the owning Phase's Gap table, or the §3.3 help-centre tag.
  - Grading reference: the Clone, except where an ADR or newer evidence overrides it. The Pop-out window is graded against ADR-0002 (the full Messages Pro), not the Clone's one-Thread pop-out (`messages.html:85`). Colours are never graded (ADR-0001). Where §3.3 marks newer help-centre evidence than the Clone, as for Fan insights, that evidence wins.
  - Status rule:
    - `done`: every Clone element in the owning Phase's Gap table is present, that Phase's acceptance checks passed, and its result lists no `VISUAL GAP:`, "not wired" control or "—" field for the Region.
    - `partial`: anything short of done, including a failed or skipped acceptance check. The Ours cell names what is missing.
    - `ours-only`: Infloww has no counterpart. It is never used for a Region where an Infloww element is missing.

ASSUMPTION: the tooltip format and the use of `title` follow house precedent. This is overturned if a Phase introduced a tooltip component, in which case the same text goes there.
ASSUMPTION: the overflow trigger is named "Inflowwww extras" and renders only when it is not empty. The name avoids the clash with the Creator tabs "+" described in CONTEXT.md. This is overturned if a Phase spec the human approved fixed a different name.
ASSUMPTION: "flag-on shows all" means every extra is reachable, either directly or one click into its Region's Extras overflow. Extras the plan moves into an overflow without a flag condition (Owe reply, Scheduled chip, Free previews, Mass exclude, Mark as unread, Phone focus, the Chat header "👥", Quick emojis, At presets, Fan identity, Extra Fan stats, Unsold PPVs, Extra sort orders) stay in the overflow with the flag on. ADR-0003 keeps non-automation extras "visible inside the Extras overflow of its Region" with no flag condition, and Phases 2, 3, 4 and 5 place them that way. This is overturned if the human wants the flag to restore the pre-parity placements.
ASSUMPTION: the parity table has one row per Region plus the ours-only rows Phone layout and Extras overflow. The extras themselves are listed under "Ours", not as table rows. This is overturned if the human wants one table row per extra.
ASSUMPTION: the done / partial / ours-only rule above is not stated in the plan. It is overturned if the human gives another grading rule.
ASSUMPTION: an open `ASSUMPTION:` line in a Phase spec does not by itself make its Region partial, because every Phase spec has them and the grade would then carry no information. This is overturned if the human wants unverified assumptions graded partial.

## Testing Decisions

- **The seam: one render of the Messages Pro tree, flag off and flag on.**
  - After Phase 0, the Messages Pro route page is the single tree used both in-app and windowed.
  - The test enters it through the Deep link for one fixture Creator and Fan. It renders with `renderWithProviders` (`app/test-utils.tsx`) inside `FlagsProvider`, first with `{ legacyAutomations: false }` and then with `true`.
  - `FlagsProvider` is the existing public provider. No test sets the flag today: `grep -rln FlagsContext --include='*.test.*' app` has no hits, and the nav tests pass `legacy` to a pure function instead (`app/lib/nav.test.ts:42-66`). The provider is the seam the root layout already uses (`app/app/layout.tsx:162`), so nothing in it is mocked.
- **Boundary.**
  - `@/lib/relay` is mocked by path and returns fixtures, and `@/hooks/useAccounts` returns the one Creator. The browser APIs jsdom lacks are stubbed.
  - Fixtures:
    - one Fan whose last message is from the Fan
    - one direct queued send to that Fan
    - two server-scheduled jobs for that Fan, one `scheduled_send` and one `ai_reply`
    - one unsold PPV sent to that Fan
    - one open AI seller offer
    - one AI status payload, copied verbatim from the captures in `AiStatusStrip.test.tsx`
    - one vault media item
- **Reach routine.**
  - The test first waits for loaded state with `findBy` queries, because the AI strip renders nothing while it loads (`AiStatusStrip.tsx:273`).
  - It then opens every host that can hold an extra: each "Inflowwww extras" trigger in turn, the Fan List's "New" menu, the Kebab menu, and Fan insights on both its Insights and Notes tabs. Phase 5 renders only the active tab's blocks and puts the AI profile and Persona claims on Notes (`docs/spec/phase-05-fan-insights-panel.md:128`, `:132`).
  - If Phase 4's Free previews entry needs a priced PPV with an attachment, the test first enters a price in the PPV row and attaches the vault item through the Vault picker.
  - The test opens one host at a time, so each labelled element it finds is attributed to the host that revealed it.
- **Assertions.** All of them are on what a user sees: tooltips, accessible names and presence in the DOM.
  1. Flag off, before any host opens: no element other than an "Inflowwww extras" trigger has a tooltip starting with "Inflowwww extra".
  2. Flag off, after the reach routine: the multiset of (name, host) pairs of labelled elements equals the `off` hosts in `EXTRAS`. So no automation extra shows, and deleting one entry point of Group chat or Mass exclude fails.
  3. Flag on, after the reach routine: the multiset equals the `on` hosts in `EXTRAS`.
  4. Old identities are gone. A table in the test holds each extra's pre-parity title or visible text from the Gap tables' Today column, such as "Persona", "Add to group chat tab", "All models", "↩ Owe reply", "AI profile" and the Scheduled chip's title (`ScheduledForChat.tsx:55`). With the flag off, no element outside an opened "Inflowwww extras" host carries one of them. This catches an extra left in place without its label.
  5. Every element other than a trigger whose tooltip starts with "Inflowwww extra" has the first line exactly `Inflowwww extra — <a name in EXTRAS>`. A bare "Inflowwww extra" left by Phases 2, 4 or 5 fails here. Where the test's table gives an old title, the second line equals it.
  6. Actions: the Broadcast item's `href` is `/automations?ready=nudge_online`. Clicking each Group chat entry point calls `openGroupTab` from `@/lib/groupChannel` (`ChatSurface.tsx:20`, `:1217`) with the fixture Creator and Fan. The spy is set by module path.
  7. Empty overflows: every "Inflowwww extras" trigger reveals at least one labelled extra. With the flag on, the Window header renders no trigger.
  8. In both renders, the sequence of accessible names of non-extra controls in each Region is identical, ignoring the overflow triggers. Turning the flag on adds and never displaces.
  9. In both renders, the `scheduled_send` pseudo-row shows with its cancel button, and the `ai_reply` row shows its countdown with the title `AI_PAUSE_TITLE` and no cancel button.
- **Not tested here.** Pixel placement with the flag off is covered by Phase 6 and the visual loop. With the flag on, Phase 6 runs its overflow sweep once (`docs/spec/phase-06-geometry-pass.md:326`, `:584`), but that is before this Phase adds Broadcast and moves any extra an earlier Phase placed differently (Further Notes, "Conflicting placements"). This Phase therefore runs the same flag-on sweep again in Acceptance. Tooltip display is the browser's job. jsdom applies no Tailwind CSS, so a CSS-hidden extra stays in the DOM and fails assertion 1 or 2. That is intended.
- **New components.** None: the module is constants plus one function, and the audit test covers it.
- **Prior art.**
  - `app/app/analytics/message-dashboard/page.render.test.tsx`: renders a whole page, mocks the relay by path and stubs jsdom gaps.
  - `app/components/chat/AiStatusStrip.test.tsx`: uses captured payloads and mocks `relay.get` so that the real hooks run.
  - `app/lib/nav.test.ts`: a flag-off/flag-on matrix.
  - Phase 0's `windowed.test.tsx` (per the plan) renders the same tree.

ASSUMPTION: this Phase writes its own fixture, following `page.render.test.tsx`. This is overturned if Phase 0's windowed test exports a reusable Messages Pro fixture, in which case that fixture is reused.
ASSUMPTION: Free previews is reached through the PPV-row path only if Phase 4 renders its overflow entry conditionally. This is overturned (and the step dropped) if the entry is always present.

## Acceptance

```sh
set -eu
cd "$(git rev-parse --show-toplevel)"

pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run

# The audit on its own, so a failure names it. The file must exist: vitest passes with no tests (app/vitest.config.ts:25).
test -f app/app/messages-pro/extras.test.tsx
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run app/messages-pro/extras.test.tsx

# The parity doc: a commit line, an Ours entry per extra and a row per Region, each inside its own
# section, every cell filled, statuses valid, the table last.
doc=docs/messages-pro-parity.md
test -f "$doc"
test "$(grep '^## ' "$doc" | tail -n 1)" = '## Parity table'
grep -q '^Graded at `[0-9a-f]\{7,40\}`' "$doc"
extras='AI strip|Persona button|Scheduled chip|Owe reply|Broadcast|Group chat|Free previews|All Models|Generated profile note|AI seller chip|Persona claims|Automation restrict|Mass exclude|Mark as unread|Phone focus|Quick emojis|At presets|Fan identity|Extra Fan stats|Unsold PPVs|Extra sort orders'
regions='Pop-out window|Deep link|Window header|Creator tabs|Fan tabs|Fan List|Split Inbox|Chat header|Message list|Composer|Vault picker|Fan insights|Geometry|Phone layout|Extras overflow'
awk -v extras="$extras" -v regions="$regions" -F'|' '
  BEGIN { ne = split(extras, E, "|"); nr = split(regions, R, "|") }
  /^## / { sec = $0; next }
  sec == "## Ours" && /^- \*\*/ {
    n = $0; sub(/^- \*\*/, "", n); sub(/\*\*.*$/, "", n)
    if ($0 !~ /^- \*\*[^*]+\*\* — [^;]+; [^;]+; .+\.$/) { print "bad Ours entry: " $0; bad = 1 }
    ours[n] = 1
  }
  sec == "## Parity table" && /^\|/ && !/^\| *Region *\|/ && !/^\|[-: |]+\|$/ {
    if (NF != 6) { print "bad row: " $0; bad = 1; next }
    for (i = 2; i <= 5; i++) { c[i] = $i; gsub(/^ +| +$/, "", c[i]); if (c[i] == "") { print "empty cell: " $0; bad = 1 } }
    if (c[5] != "done" && c[5] != "partial" && c[5] != "ours-only") { print "bad status: " $0; bad = 1 }
    rows[c[2]] = 1
  }
  END {
    for (i = 1; i <= ne; i++) if (!(E[i] in ours)) { print "Ours misses: " E[i]; bad = 1 }
    for (i = 1; i <= nr; i++) if (!(R[i] in rows)) { print "Parity table misses: " R[i]; bad = 1 }
    exit bad
  }' "$doc"

# Visual loop (plan, binding for UI tickets). First Phase 6's overflow sweep with the flag on, after this
# Phase's moves; its exit code is the check (horizontal overflow, a clipped control, missing panes).
OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 bash scripts/ui-shots.sh
# manual: Read docs/screenshots/messages-pro-desktop.png, messages-pro-insights.png and messages-pro-composer-ppv.png beside docs/screenshots/clone-messages-pro.png; with the flag on every extra sits after its Region's Infloww controls and no Infloww element moved, wrapped or clipped. Record what remains as VISUAL GAP: lines. Do not commit these PNGs.
# Then the committed default, flag off.
bash scripts/ui-shots.sh
# manual: Read docs/screenshots/messages-pro-desktop.png beside docs/screenshots/clone-messages-pro.png; with the flag off no extra shows outside a "+" and no Infloww element moved. Up to three rounds, then VISUAL GAP: lines.
# manual: copy the summary of docs/screenshots/messages-pro-report.json into the Phase 7 result.
```

## Depends on

- **Phase 0**: the single Messages Pro tree and its Deep link, which form this Phase's only test seam.
- **Phase 1**: the Window header, its Extras overflow, the placement of All Models and Group chat, and Creator tabs replacing the roster (which removes the roster's All Models icons from Messages Pro).
- **Phase 2**: the Fan List overflow holding Owe reply and the three extra sort orders, and the "New" menu that hosts Broadcast.
- **Phase 3**: the Chat header and its overflow (the Scheduled chip per ADR-0003, Group chat, Mark as unread, Mass exclude and Phone focus), the Kebab menu with the automation-restrict row last behind the flag, and the AI strip band and Persona button behind the flag.
- **Phase 4**: the Composer overflow holding Free previews, the "at" presets and the quick emoji row, and the "AI" pill that opens `LinesPicker`, which is why the Lines picker is not an extra.
- **Phase 5**: the restyled Fan insights. Its Insights tab hosts the AI seller chip after the Notes block, its Notes tab hosts the Generated profile note and Persona claims under the flag, and its Extras overflow hosts Fan identity, Extra Fan stats, the Mass exclude switches and Unsold PPVs.
- **Phase 6**: the Messages Pro token module that the overflow trigger reads, the measured Geometry for the parity table's Geometry row, and the sweep mode `UI_SHOTS_SWEEP=1` that this Phase runs again with the flag on (`docs/spec/phase-06-geometry-pass.md:326`, `:584`).
- **Phase 0** also builds the harness `scripts/ui-shots.sh` and its doc `docs/ui-shots.md` (`docs/spec/phase-00-pop-out-window.md:45`, `:49`, `:61`). Neither exists yet (observed: `ls scripts` lists no `ui-shots.sh`; `ls docs` lists no `ui-shots.md`).
  ASSUMPTION: the harness starts the Next app with the caller's environment, so `OPENINFLOWW_LEGACY_AUTOMATIONS=1` reaches the root layout. Phase 6 makes the same assumption (`phase-06-geometry-pass.md:506`). This is overturned if `docs/ui-shots.md` says otherwise. The harness then needs a flag option, which belongs to the harness's own ticket.

## Out of Scope

- **Building or merging Extras overflow components.** Phases 1–4 build them. This Phase only aligns the trigger's label.
- **A new flag, or one toggle per extra.** ADR-0003 rejects a second switch with the same meaning as the Legacy flag.
- **A custom tooltip component.** The `title` attribute is house precedent across Messages Pro.
- **Generating the parity doc from code.** A hand-written doc checked by the Acceptance shell does the job.
- **Extras outside Messages Pro.** These are the top bar's ScopeSwitcher "all models" (`app/components/ScopeSwitcher.tsx:184`), the `/group` page, and the MoneyRail dock mounted app-wide in the root layout (`app/app/layout.tsx:169`). The plan touches only Messages Pro, and the MoneyRail can already be hidden per surface.
  ASSUMPTION: the MoneyRail is app chrome, not a Messages Pro extra. This is overturned if the human counts it as one.
- **The Fan List's gear options:** the blur and compact-media toggles (`ChatList.tsx:774-799`), which Phase 2 keeps in its gear without an extra label. The extra sort orders, which Phase 2 does label, are in `EXTRAS`.
  ASSUMPTION: options inside an Infloww control that its owning Phase did not label are not extras. This is overturned if the human wants each one marked, which would add them to `EXTRAS`.
- **The "🌐 translate" header toggle (`ChatSurface.tsx:963-975`).** Infloww has an AI Translator, and Phase 4 owns it.
- **Read-only free-preview text** (`app/components/chat/MessageList.tsx:1111`, `app/components/chat/TemplatePicker.tsx:330`). This is status text, not a control.
- **Relay or service changes.** The flag is client-side, and no extra needs a new endpoint.
- **Committed flag-on screenshots.** The flag-on harness run is read and recorded as `VISUAL GAP:` lines, but the committed PNGs stay the flag-off default.
  ASSUMPTION: the committed shots stay flag-off, so each harness file name keeps one meaning. This is overturned if the human wants flag-on shots committed, which needs new shot names in the harness.
- **Tooltips on touch devices.** `title` does not show on touch. Where that matters, the house adds visible phone-only text instead (`ChatList.tsx:827-830`), and here the overflow trigger's visible "+" and accessible name carry the meaning.

## Further Notes

- **ADR-0003 is partly overturned.** Its assumption that broadcast is not an automation fails its own overturn clause (see the Gap table). The plan review appended an `## Amended 2026-10-12` paragraph to ADR-0003 that records this, so the implementer edits no ADR.
- **"Needs reply" sort.** `docs/infloww-screens.md` §3.3 tags the sort label "Needs reply" as "[CL ?, probably ours]". The app has no such label (observed: `grep -rn "Needs reply" app/components app/app` has no hits), so there is nothing to keep or mark.
- **Inclusion rule for the thirteen extras outside the plan's list.** The Generated profile note is included because the plan's constraint covers "anything tagged ours in §3.3", and §3.3 tags it. Mark as unread, Phone focus, Quick emojis, At presets, Fan identity, Extra Fan stats, Unsold PPVs and Extra sort orders are included because Phases 2, 3, 4 and 5 label them extras. Any other element a dependency Phase labels "Inflowwww extra" joins `EXTRAS` and the doc the same way, and assertion 5 fails until it does. The AI seller chip, Persona claims, Automation restrict and Mass exclude are included because the plan's goal is "keep our additions as clearly marked extras".
  ASSUMPTION: Phase 7 marks the four extras that neither the plan nor a Phase names (AI seller chip, Persona claims, Automation restrict, Mass exclude). This is overturned if the human limits Phase 7 to the named extras. In that case those four rows leave `EXTRAS` and the doc.
- **Conflicting placements.** If a parallel Phase spec placed an extra differently from the Gap table (for example, Broadcast in a flag-off overflow), this Phase lands last and moves it to the Gap table's destination. The move is a mount-point change and costs nothing to undo.
  ASSUMPTION: the Gap table wins over earlier Phase placements, because Phase 7 is the closing audit. This is overturned if the human approves the other Phase's placement, which would then be copied into `EXTRAS` and the doc.

## Review

codex (codex-cli 0.155.0-alpha.9.2, reasoning effort high), 2026-10-12. Blind call: exit 0 in 209s. Draft call: exit 0 in 237s. The workspace kept `docs/spec/` out of its checkout, but the spec commit `c7f2b131` could still be read with `git show HEAD:`. The blind call's log names no `docs/spec` path (`grep -c 'phase-07\|docs/spec'` on that log gives 0), so it stayed blind. The draft call read the other Phase specs that way, which is where D1–D3, D5 and D7 come from.

Counts: 15 accept, 7 partial, 8 reject, 0 needs-human.

### Blind call (without the spec)

- B1 **reject**: "Phase 7 is not yet a closing audit. Phases 0–1 are unbuilt (`page.tsx:195` roster, a separate pop-out), and Persona, Group chat, Scheduled and Owe reply sit outside any overflow today." The spec already measures against `main` before Phases 1–5 and lists all six Phases under Depends on. The ungated controls are the gap this Phase closes, and the Gap table records each one.
- B2 **accept**: The AI strip, Persona and Broadcast are automations. Owe reply, Free previews, All Models, Group chat and the Scheduled chip are not. Broadcast overturns ADR-0003 under the ADR's own clause. This agrees with the Gap table. The Broadcast ASSUMPTION now cites all three Clone rule kinds (`outreach-broadcast.js:287`) and our three automation tabs (`ReadyMadePanel.tsx:64-66`).
- B3 **accept**: Not every AI or scheduled feature is legacy. Timed message and the reply-suggesting AI Copilot are Infloww's (`docs/infloww-screens.md:213`, `:235-236`; CONTEXT.md:158). Rewritten: the Lines picker leaves `EXTRAS` because it is Infloww's "AI" pill, and `scheduled_send` rows stay in both flag states (assertion 9).
- B4 **partial**: "Flag-on shows all" could mean reachable or all visible at once, and the plan does not say which. The reachable reading stays as an ASSUMPTION. Its reason now cites ADR-0003's unconditional "visible inside the Extras overflow" and the unconditional placements in Phases 2, 4 and 5.
- B5 **reject**: The gate could sit at the caller, in the extra itself, or in a shared policy, and testing a policy alone proves nothing. The spec gates at the mount point or by an early return and tests the composed tree, not the module, so that failure mode does not apply.
- B6 **accept**: An audit of only eight extras cannot back "no extra outside the overflow", because FanDrawer and ChatActionsMenu carry more. The spec already added some. Together with D2, `EXTRAS` now holds twenty extras.
- B7 **accept**: The inventory missed the pending AI-reply rows (`MessageList.tsx:1651`), and the Thread queue mixes `scheduled_send` with `ai_reply` jobs (`useServerScheduledSends.ts:29-32`, `ChatSurface.tsx:785-790`). Observed. Added as the AI reply countdown: behind the flag, filtered by job kind, with human rows and their cancel button kept. A new ASSUMPTION covers it.
- B8 **partial**: An extra can render nothing in some states (a zero-count chip, an unpriced stepper, a loading strip), so an empty fixture proves nothing. The fixtures were already populated. Added a `scheduled_send` job, an `ai_reply` job, an unsold PPV, and `findBy` waits for the AI strip's loading state (`AiStatusStrip.tsx:273`). The error and loading states stay with each component's own tests.
- B9 **partial**: The overflow's keyboard, touch, dismissal and focus behaviour is unspecified. It belongs to the Phases that build each overflow (Out of Scope). The trigger contract no longer says "opens a menu", because Phase 5 built a collapsible section (`docs/spec/phase-05-fan-insights-panel.md:143`). It now leaves interaction to the owning Phase.
- B10 **reject**: Decide whether flag-off also means no automation-only requests, and do not change shared roster or scope controls. The gate already unmounts the extra, so its own hooks do not run. A request audit is scope the plan never asked for (`docs/plans/messages-pro-parity.md:214` asks for a render). ScopeSwitcher is already out of scope.
- B11 **partial**: Closure needs provenance: revision, flag state and Phase results. Added a required `` Graded at `<commit>` `` line to the doc contract and the Acceptance check. The rest is already the Phase results the doc is written from.
- B12 **reject**: Test the server flag reader (unset, `0`, `true`, `1`). This Phase does not change `flags.ts` (story 22), so a reader test belongs to whoever changes it.
- B13 **reject**: Test the main route, window variant, deep link, username redirect and `/group`. Phase 0's windowed test owns entry equivalence for the single tree, and `/group` is outside Messages Pro (Out of Scope).
- B14 **reject**: Legacy routes must really answer 404, and hiding a link is not protection. That protection already exists and does not change (`app/proxy.ts:16-20`, `app/app/automations/layout.tsx:5`). Broadcast is behind the flag, so no flag-off link points at it.
- B15 **accept**: Check the browser layout in both flag states. Merged with D7: Acceptance now runs the harness with the flag on first.
- B16 **partial**: Assert actions, not only labels. Added action checks for the destinations this Phase sets: the Broadcast `href`, and both Group chat entry points calling `openGroupTab`. Free previews' payload, queue cancellation and scope selection keep their props and behaviour (Interfaces), so their owning Phases' tests cover them.
- B17 **partial**: Tighten the grading rule. Added "a failed or skipped acceptance check" to `partial`, and `ours-only` may no longer excuse a missing Infloww element. Rejected "any unverified assumption makes a Region partial" in a new ASSUMPTION, because every Region would then be partial.
- B18 **reject**: Give the window, deep link and responsive geometry their own rows. They already have them: Pop-out window, Deep link, Geometry and Phone layout (Implementation Decisions, Region rows).
- B19 **accept**: Grade against qualified evidence. The Clone was modified, ADR-0002 overrides its pop-out (`messages.html:85`), colours differ by design (ADR-0001), and Fan insights prefers help-centre evidence. Added as a "Grading reference" decision above the status rule.
- B20 **partial**: `scripts/ui-shots.sh` and `docs/ui-shots.md` are not in the repo. The harness was already under Depends on, and `docs/ui-shots.md` is now added. The parity doc is this Phase's output, and the token module is Phase 6's.
- B21 **reject**: `pnpm -C app test:run` → `vitest: command not found`. That comes from the sparse review workspace, which has no `node_modules`, and says nothing about the spec.

### Draft call (with the spec)

- D1 **accept**: Gating `LinesPicker` would remove Phase 4's Infloww "AI" pill (`docs/spec/phase-04-composer-ppv-vault.md:175`, `:191`, `:306-314` in its current revision), and the dependency "the toolbar the Lines picker follows" was false. Observed. The Lines picker left `EXTRAS` and the Gap table, a "Not an extra" note and its ASSUMPTION were added, and the Phase 4 dependency was rewritten.
- D2 **accept**: The catalogue missed the extras Phases 2, 4 and 5 hand over: quick emojis (`phase-04:417`), Fan identity, extra stats and Unsold PPVs (`phase-05:143-147`), and the three sort orders (`phase-02:67`, `:186-189`). Observed. Phase 4's revision during this review also added the "at" presets (`phase-04:205`). All of them are in a third Gap table, `EXTRAS` grows to twenty, and the Acceptance lists are updated. Assertions 1 and 5 now also fail on a bare "Inflowwww extra" label, so an extra a Phase adds later cannot pass unlisted. The old "sort orders are not extras" exclusion now covers only unlabelled gear options. Moving the sort orders into the overflow is a new ASSUMPTION.
- D3 **accept**: Putting the Fan insights copies of Mass exclude behind the flag contradicts ADR-0003 and Phase 5 (`phase-05:143-147` and its test list). Observed. Both copies now stay in the Fan insights overflow.
- D4 **accept**: "`ReadyMadePanel` reads no tab parameter" is false (`useTabParam("ready", …)`, `ReadyMadePanel.tsx:121`), and "our only broadcast surface is `online_blast`" overlooks `nudge_online` and `mass_nudge` (`:64-65`). Observed. Broadcast now links to `/automations?ready=nudge_online` (new ASSUMPTION). The false ASSUMPTION and the Out of Scope deep-link bullet were deleted.
- D5 **accept**: The reach routine never opened the Fan insights Notes tab, where Phase 5 puts the AI profile and Persona claims (`phase-05:128`, `:132`). It now opens both tabs.
- D6 **accept**: The set-based assertions would miss an unlabelled extra left in place, a deleted second entry point, a wrong Broadcast `href`, a disconnected Group chat handler, a dropped second tooltip line and an empty overflow. The assertions are rewritten: (name, host) multisets from the new `off`/`on` hosts in `EXTRAS`, a check that old identities are gone, second-line equality, action checks and an empty-overflow check.
- D7 **accept**: Flag-on geometry had no owner. Phase 6 handed flag-on shots to Phase 7 (`phase-06:609` at HEAD), and Phase 7 had excluded them. Observed. Phase 6's revision during this review now runs a flag-on overflow sweep (`phase-06:326`, `:579`), but before Phase 7's moves. Acceptance here re-runs `OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 bash scripts/ui-shots.sh` after them, which fails on overflow or clipping, followed by a manual read for displaced elements. That the harness passes the environment through is a new ASSUMPTION, the same one Phase 6 makes. The committed PNGs stay flag-off, which agrees with `phase-06:629`.
- D8 **accept**: Acceptance could pass without the audit test, because `app/vitest.config.ts:25` sets `passWithNoTests: true`. Observed. Added `test -f app/app/messages-pro/extras.test.tsx` before the run.
- D9 **accept**: The doc check accepted empty sections; the reviewer reproduced it. It is replaced by one awk script that checks each section on its own: each extra's bullet must sit inside `## Ours` in the contract format, and each Region's row inside `## Parity table` with all four cells filled and a valid status. Run here with BSD awk: a good doc exits 0, the reviewer's empty-sections doc exits 1 ("Ours misses: AI strip"), and a doc with an empty evidence cell exits 1 ("empty cell").

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: "Restrict from automations" sits in the Kebab here (`:27`, story 13) and in Phase 3's Extras overflow (`phase-03-chat-header-message-list.md:158` before this reconcile). **accept**: the Kebab placement stands, and Phase 3 now puts the automation-restrict row last in its Kebab, behind the flag. This spec does not change.
- Black: the list misses Mark as unread, translate and focus, which Phase 3 calls extras (`:175` before this reconcile). **accept**: verified against Phase 3 H13 and F10. Mark as unread and Phone focus join the second Gap table, the stories, `EXTRAS` (now twenty-one), the "flag-on shows all" list and the Acceptance regex. The focus Out of Scope entry is gone. Translate stays out, because it is Infloww's AI Translator (Phase 4), and Phase 3 now removes the header toggle instead of calling it an extra.
- Black: this Phase hides pending AI replies with the flag off (`:52`), which is work beyond the plan. **accept**: verified at `useServerScheduledSends.ts:28-31` (not cancellable), `MessageList.tsx:1631-1632` and `docs/routes.md:73` (the flag gates no backend). The AI reply countdown leaves `EXTRAS` and stays in both flag states (new "Not an extra" note, story 24, assertion 9), and the Owns entry for the pseudo-row merge is gone. Flagged as an ASSUMPTION (rungs 1, 4 and 3).
- Red: Phase 7's moves look like churn. **partial**: earlier Phases now place three extras at their final spot (Phase 2's sort orders, Phase 3's automation-restrict row, Phase 3's Mark as unread and focus), so this Phase adds Broadcast and moves only what a Phase placed differently. The closing audit stays, because the plan names it (plan:209-215).
- Blue: Phase 7 is third in the cut order. **partial**: the plan names this Phase (plan:209-215), so it lands last and is not cut. A short budget defers it.
- White: ADR-0003:9 is overturned by Broadcast. **accept**: ADR-0003 has an `## Amended 2026-10-12` paragraph. The Further Notes entry now points to it, and its "the human amends it" ASSUMPTION is gone.
- Black, cross-check: the AI seller chip host ("Fan insights header") and the AI strip host ("under the Fan's name") disagreed with Phase 5 (`phase-05-fan-insights-panel.md:154`) and Phase 3 H14. **accept**: both Destination cells and Depends on now match those specs.

## Amended 2026-10-21

The MASSppvEXCLUDE list is merged into MASSdmEXCLUDE, which now keeps a Fan out of every mass send, priced or not. Mass exclude has one toggle in the Chat header overflow ("Add to MASSdmEXCLUDE") and one switch in Fan insights' Mass exclude block. The manual Mass message composer and the funnel launch pre-tick MASSDMEXCLUDE instead of MASSPPVEXCLUDE (story 12). Generated profile note and Persona claims are no longer flag-only: they show in Fan insights with the flag off too, and Fan insights has no Extras overflow (ADR-0003's 2026-10-21 amendment).
