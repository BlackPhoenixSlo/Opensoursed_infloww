# Phase 05 — Fan insights panel

**Objective.** Fan insights shows Infloww's Insights blocks in the Clone's order, with the Clone's labels and Geometry and our colours. Every Messages Basic field the plan names is present, with a real value or "—". Our extras sit behind the Legacy flag or the Extras overflow. `FanDrawer`'s data wiring is unchanged, and below 1024px Fan insights is still the slide-over sheet.

## Gap table

Sources. The Clone's right pane is `ui-redesign/infloww-exact/messages.html:769-848` (CSS at `:292-327` and `:486-498`), wired by `messages.js:1372-1634`. `_shared/components.html` has no Fan insights selectors: its `.fx-card` (`components.html:42`, padding 20px 22px) belongs to the Inflowwww kit, not this pane. §3.3 "Fan insights panel" (`docs/infloww-screens.md:242-257`) lists blocks and fields but gives no numbers. Ours is `app/components/chat/FanDrawer.tsx`. Colours are never taken from the Clone (ADR 0001).

| # | Clone selector · CSS (file:line) | Ours (file:line) | Gap | Change |
|---|---|---|---|---|
| G1 | `.right` width 280px, min-width 280px, border-left 1px, flex column (`messages.html:292`) | pinned column `hidden lg:flex w-[360px]` (`FanDrawer.tsx:332`) | 80px too wide | Pinned column becomes 280px. The overlay sheet (`FanDrawer.tsx:333`) is unchanged (`docs/routes.md:42`) |
| G2 | `.right-head` padding 16px 16px 10px, 16px/700, text "Fan insights", which becomes "Sales"/"Notes" with the tab (`messages.html:293`, `:770`; `messages.js:1614`) | header `p-4 border-b`: 48px avatar, 14px name, @username, account · id, AI seller chip, × (`FanDrawer.tsx:336-372`) | No title. The identity block is not in the Clone | The head is the title only, with padding 16/16/10, 16px/700 and no rule. × stays (overlay, and pinned unless `alwaysOn`). The Extras overflow "+" sits to its right. Identity moves into the Extras overflow, and the AI seller chip goes behind the Legacy flag |
| G3 | `.right-body` padding 0 12px 12px, gap 12px, overflow-y auto (`messages.html:294`) | `p-4 gap-4` (`FanDrawer.tsx:374`) | 16px padding where the Clone has 0 on top and 12px elsewhere; 16px gap where the Clone has 12px | Padding 0 12px 12px, gap 12px |
| G4 | `.card` border 1px, radius 12px, padding 14px (`messages.html:295`) | Only the AI profile is boxed: `rounded-lg` (8px), `p-3` (12px) (`FanDrawer.tsx:1728`). The other sections are bare, split by `border-t` (`:527`, `:791`, `:896`) | Blocks are not boxed | Every Insights block gets 12px radius, 14px padding and a 1px border |
| G5 | `.card-head` gap 8px, margin-bottom 12px. `.drag svg` 14px, `.ct` 14px/600 flex 1, `.chev svg` 15px (`messages.html:296-301`) | Section labels are 11px uppercase with letter-spacing, and there is no grip or chevron (`FanDrawer.tsx:635`, `:699`, `:793`, `:897`, `:1730`) | Size and case differ; grip and chevron missing | Head row: a 14px grip (not wired), the title at 14px/600 in sentence case, and a 15px chevron that collapses the block |
| G6 | `.mrow` padding 6px 0, space-between, align flex-start. `.k` 13.5px, `.v` right-aligned, `.vt` 13.5px/600, `.va` 12px muted, `.mrow.plain .v` 13.5px (`messages.html:310-316`) | `Stat`: label stacked over value, 11px, in a 2-column grid (`FanDrawer.tsx:643-662`, `:527`) | Layout and type size | Rows put the key on the left and the value on the right, at 13.5px, with padding 6px 0 |
| G7 | `.spend-top` gap 24px, margin-bottom 6px. `.lbl` 12px with margin-bottom 5px, `.big` 22px/700, `.sub` 15px (`messages.html:304-307`, `:780-783`) | "Lifetime spend" and "Last purchase" are 11px Stats in two separate strips (`FanDrawer.tsx:528`, `:385`) | No headline pair | Total spend at 22px/700 and Last spend at 15px, side by side with a 24px gap |
| G8 | `.tiny-line` 12px, margin 10px 0 4px (`messages.html:308`, `:784`) | none | Missing | None. Out of Scope (a line only the Clone has) |
| G9 | `.hr` 1px, margin 10px 0 (`messages.html:309`, `:785`) | `border-t pt-3` (`FanDrawer.tsx:527`) | Spacing | A 1px rule with 10px above and below, inside Spending behavior |
| G10 | Rows "PPV" (Total / Avg), "Tip" (Total / Avg), "Highest spend" (`messages.html:786-788`) | "Messages" Stat (`FanDrawer.tsx:548`), "Tips" Stat (`:544`), Max/Avg in the chart heading (`:703-704`) | Labels and grouping | PPV, Tip and Highest spend rows built from those same values. Tip Avg is "—" (the Clone does the same, `messages.js:1434`) |
| G11 | "Purchases over time" with "Full history ↗" (`messages.html:791`). `.bars` height 62px, gap 3px, radius 2px 2px 0 0. `.axis` 10px (`messages.html:493-496`) | Heading "PPV purchases by fan" (`FanDrawer.tsx:700`). SVG line chart `h-28`, which is 112px (`:1609`). Axis 9px (`:1654`) | Label, height, link and chart kind | Label "Purchases over time". "Full history ↗" opens the Sales tab. The line chart becomes the Clone's bars: 12 gross-cent buckets from the first purchase to now (`messages.js:1472-1490`), from the same `useFanPpvHistory().items`, 62px tall, gap 3px, radius 2px 2px 0 0, axis 10px |
| G12 | Organization metrics: "Spending power" ⓘ and "Chargeback risk". `.badge-val` 11.5px/600, padding 3px 9px, radius 7px (`messages.html:800-804`, `:315`) | none | Block missing | Add the block with both rows. Values are "—", using the badge Geometry |
| G13 | Subscription: "Status", "Cost", "Duration", "Auto-renewal" (`messages.html:810-816`) | "Sub status" and "Sub price" Stats (`FanDrawer.tsx:529-534`). No Duration, no Auto-renewal | Labels; two rows missing | Relabel. Duration comes from `subscribedOnData.duration`, and Auto-renewal is derived from the status |
| G14 | Profile rows in order: Nickname ⓘ, Tags, Language, Birthday, then `.loc-box` with margin-top 10px (`messages.html:822-834`) | Field order Custom nickname, Notes, Tags, Language (`FanDrawer.tsx:406`, `:429`, `:451`, `:479`). Location appears only inside the AI profile (`:1711`) | Order differs; Notes is mixed in; Birthday, Source and Location missing | Profile order: Nickname, Tags, Language, Birthday, Source, then the Location box. Notes moves to its own block |
| G15 | `.nick-edit` gap 8px, pencil 13px. `.info-i` 14px (`messages.html:320-321`, `:302`) | A full-width bordered input, with the hint as 10px text below it (`FanDrawer.tsx:406-427`, `:638`) | Inline value and pencil versus an open input | The input stays rendered at all times, because the freshness test focuses it (`fanDrawerEditFreshness.test.tsx:104`). It is restyled right-aligned at 13.5px with a 13px pencil, and the hint becomes the title of a 14px ⓘ |
| G16 | `.cal-i` 15px with "Select date" (`messages.html:831`) | none | Missing | "Birthday" with "—" and no picker. There is no field, and the Clone marks it "NO FIELD" (`messages.js:3393-3396`) |
| G17 | `.loc-box` gap 8px, border 1px, radius 8px, padding 8px 10px, 13px, icons 15px, chevron (`messages.html:317-319`, `:833`) | "Location: city, country" at 11px inside the AI profile (`FanDrawer.tsx:1711`) | Missing | A box with a pin icon and "city, country", or "—". No chevron, because it is read-only |
| G18 | `.right-tabs` border-top 1px. `.rtab` flex 1, column, gap 4px, padding 11px 0, 12px/600, icon 20px, the active tab coloured (`messages.html:324-327`, `:843-847`) | none | Missing | A bottom tab bar with Insights, Sales and Notes. The active tab uses the accent token |
| G19 | Sales tab: a "Purchases over time" box; a "Sales (N)" table with Date / Gross / Net / Sent by at 12px; a "Vault history" box (`messages.js:1532-1545`; `.stab` `messages.html:488-492`) | `PpvSalesSection` under the heading "Sales", with media rows, ↻ and Load more (`FanDrawer.tsx:725-883`, `:793`) | Table versus media rows; the count | Sales tab: a Purchases over time block, then a Sales block holding the Buy rate row, the Clone's table (Date / Gross / Net / Sent by at 12px) built from `useFanPpvHistory().items` (`purchased_at`, `price_cents`, `net_cents`, `employee_name`, all on `PpvHistoryItem` in `useFanPpvHistory.ts`), then the existing purchased-media rows. No count, and no Vault history |
| G20 | Notes tab: a "Fan note" box. `.note-ta` min-height 132px, radius 9px, padding 10px, 13px/1.5 (`messages.js:1560-1576`; `messages.html:497-498`) | A "Notes" textarea, rows=6, 12px (`FanDrawer.tsx:429-449`) | Size and location | The Fan notes textarea moves to Insights › Notes block, with `.note-ta` Geometry. The Notes tab holds Creator notes |
| G21 | Block order: Spending behavior, Organization metrics, Subscription, Profile (`messages.html:777`, `:800`, `:810`, `:822`) | Recency strip, chart, AI profile, nickname/notes/tags/language/persona, mass-exclude, stats grid, Sales, Unsold, with `order-*` overrides for mobile (`FanDrawer.tsx:384-596`) | Order | The Clone's order, then Lists and Notes (§3.3 six blocks, C[H523936]). One order at every width |

ASSUMPTION: the Lists block, its OF list chips and the Extras overflow have no Clone or §3.3 numbers. They reuse the `.card`, `.card-head` and `.mrow` values above, and the chips reuse our tag-chip style (`FanDrawer.tsx:465-469`). This is overturned by a Clone or help screenshot that shows them.
ASSUMPTION: colour mapping per ADR 0001 is: block background `bg-bg-elev-1`, borders `border-border`, keys and muted text `text-fg-dim`, badge background `bg-bg-elev-2`, active tab `text-accent`. This is overturned by Phase 6's token table if it maps these differently.
ASSUMPTION: Phase 5 writes the measured numbers inline as Tailwind classes, and Phase 6 lifts them into `app/lib/messagesPro.ts`. If that module already exists when this Phase is built, Phase 5 reads it instead.
ASSUMPTION: G11 and G19 follow the Clone's bars and table even though the rewired Clone built both from our own ledger fields (`messages.js:1472-1545`), because the plan makes the Clone the layout reference and both need only data `FanDrawer` already reads. This is overturned if Phase 7's parity review shows Infloww's own chart or sales list differs.
ASSUMPTION: the purchased-media rows (↻, Load more, lightbox) stay in the Sales block under the table as our rendering of the plan's PPV timeline, because §3.3's help list describes the PPV timeline per PPV (`docs/infloww-screens.md:255`) and the table alone would drop the media. This is overturned if Phase 7 classifies them as an extra, in which case they move into the Extras overflow.

### Field table

The plan's fields (Messages Basic widget, C[H262111]) mapped to what `FanDrawer` already reads. "—" means no source exists, and the field renders "—".

| Plan field | Our source field | Rendered as |
|---|---|---|
| Creator notes | — | Notes tab › "Creator notes": — |
| Fan notes | `OFUser.notice`, falling back to `FanRecord.notes` (`useOFUser.ts:83`, `relay.ts:559`; merged at `FanDrawer.tsx:233`) | Insights › Notes › "Fan notes" textarea |
| Country/Region | `FanRecord.home_city`, `FanRecord.home_country` (`relay.ts:553-554`) | Profile › Location box |
| Auto-renew Status | `subscribedOnData.status` or else `FanRecord.subscription_status`, with `expiredAt`, through `interpretSubStatus` (`useOFUser.ts:50`, `relay.ts:563`, `utils.ts:91`) | Subscription › "Auto-renewal": On / Off / — |
| Last paid | `useFanActivity().lastPurchase` (`FanDrawer.tsx:153`) | Spending behavior › "Last spend" |
| Buy rate | — (`PpvHistorySummary` has no sent count, `useFanPpvHistory.ts:42-53`) | Sales tab › "Buy rate": — |
| Spending habits | — (no field by that name) | The Spending behavior block as a whole |
| Purchasing trends | `useFanPpvHistory().items` (`FanDrawer.tsx:157`) | "Purchases over time" bars |
| PPV timeline | `useFanPpvHistory().items` plus `useFanChatMedia({purchased: true})` (`FanDrawer.tsx:157-168`) | Sales tab › Sales table and purchased-media rows |
| Source | — (`FanRecord.source`, `relay.ts:566`, is a relationship class such as "fan" or "creator_we_follow", per `service/automations/_common.py:440`. It does not record how the Fan was acquired) | Profile › "Source": — |
| Birthdate | — | Profile › "Birthday": — |
| Infloww name | `OFUser.displayName`, falling back to `FanRecord.custom_nickname` (`useOFUser.ts:80`, `relay.ts:549`; merged at `FanDrawer.tsx:232`) | Profile › "Nickname" input |
| Fan lists | `OFUser.listsStates[].name` where `hasUser` (`useOFUser.ts:62-70`, `:85`) | Lists block chips |

Clone rows that are not plan fields read existing values. Total spend is the `spendCents` max (`FanDrawer.tsx:517`). PPV Total is `messagesSumm` or else `summary.messages_cents`. PPV Avg is `summary.avg_cents`. Tip Total is `tipsSumm` or else `summary.tips_cents`. Tip Avg is "—". Highest spend is `summary.max_cents`. Spending power and Chargeback risk are "—". Status is `interpretSubStatus().short`. Cost is `subscribedOnData.price`. Duration is `subscribedOnData.duration` (`useOFUser.ts:53`). Tags is `FanRecord.tags`, and Language is `FanRecord.language`.

ASSUMPTION: "Spending habits" is Infloww's Messages Basic name for what Messages Pro shows as the Spending behavior block, so it gets no row of its own. This is overturned if a help source defines Spending habits as a separate metric.
ASSUMPTION: "Infloww name" is the per-Fan nickname, which is our OF-synced custom name. This is overturned if Infloww keeps a name separate from OF's custom name.
ASSUMPTION: "Source" renders "—", even though `FanRecord.source` exists, because the two mean different things. This is overturned if Infloww's Source turns out to mean the platform or relationship.
ASSUMPTION: Fan lists come from `listsStates`, the only list data `FanDrawer` already reads. It carries OF's system lists only (`ChatActionsMenu.tsx:356-360`), so custom OF lists will be missing until a later change adds the folders read. The block is therefore incomplete by construction, and Phase 7 records Lists as partial. This is overturned if the human prefers "—" to a partial list.
ASSUMPTION: Auto-renewal reads On for "Active", Off for "Won't renew" and for "Expired", and "—" when there is no status or OF reports any other status string (the fall-through at `utils.ts:126`). The basis is `utils.ts:84-90`: "active" means auto-renew is on, and "Set to Expire" means it is off. The Clone instead derives it from `renewedAt` being in the future (`messages.js:1443`); OF's documented status semantics are house precedent and win. This is overturned if OF reports renewal separately for expired Fans.

## Problem Statement

An Employee who comes from Infloww opens Fan insights and finds a different pane. It is a 360px column that starts with the Fan's avatar and name. Below that come a line chart, an "AI profile", a stack of uppercase form fields, two mass-exclude switches, a ten-cell stats grid, a sales list and the unsold PPVs. It is one long scroll, with no blocks, no tabs, and labels Infloww doesn't use ("Lifetime spend", "Sub status", "Custom nickname"). Fields Infloww shows are absent: Auto-renewal, Duration, Birthday, Source, Lists, Creator notes, Buy rate, Spending power and Chargeback risk. So the Employee cannot tell whether we lack the data or the pane hides it. AI-automation surfaces (the AI seller chip, AI profile and Persona claims) show even when the Legacy flag is off. On a phone it opens as a slide-over, which must stay that way.

## Solution

Fan insights opens the way it does in Infloww. Its head reads "Fan insights". Under it are collapsible Insights blocks in the Clone's order: Spending behavior, Organization metrics, Subscription and Profile, followed by Lists and Notes. A bottom tab bar switches between Insights, Sales and Notes. Every Infloww field is present and shows either our real value or "—", never an invented number. Editing the nickname, tags, language and Fan notes works as before, including the OF write-through and the edit-freshness re-read. Our own controls stay one click away in the "+" Extras overflow. The AI surfaces appear only with the Legacy flag on. From 1024px up the pane is a 280px column, and below 1024px it is the same content in the existing slide-over sheet.

## User Stories

1. As an Employee, I want the pane headed "Fan insights", so that I recognise Infloww's right pane.
2. As an Employee, I want the head to read "Sales" or "Notes" when I switch to those tabs, so that I always know which view I am in.
3. As an Employee, I want a bottom tab bar with Insights, Sales and Notes in that order, with the active tab highlighted, so that I move between views the way I do in Infloww.
4. As an Employee, I want the Insights tab's blocks in the order Spending behavior, Organization metrics, Subscription, Profile, Lists, Notes, so that my eyes land where they do in Infloww.
5. As an Employee, I want each Insights block to have a grip, a title and a chevron, so that it looks like Infloww's.
6. As an Employee, I want the chevron to collapse and expand its block, so that I can hide what I don't need right now.
7. As an Employee, I want the grip to say "not wired" when I hover it, so that I know reordering isn't built rather than broken.
8. As an Employee, I want Total spend as a large number with Last spend beside it (the plan's "Last paid"), so that I judge the Fan's value at a glance.
9. As an Employee, I want PPV Total and Avg, Tip Total and Avg, and Highest spend in Spending behavior (the plan's "Spending habits"), so that I see how the Fan spends.
10. As an Employee, I want Tip Avg to show "—", so that I am not shown an average our ledger cannot compute.
11. As an Employee, I want a "Purchases over time" chart in Spending behavior (the plan's "Purchasing trends") with a "Full history ↗" link to the Sales tab, so that I see the trend and can drill in.
12. As an Employee, I want Organization metrics with Spending power and Chargeback risk showing "—", so that I see where Infloww's metrics live and that we do not have them.
13. As an Employee, I want Subscription to show Status, Cost, Duration and Auto-renewal (the plan's "Auto-renew Status"), so that I know whether the Fan will renew.
14. As an Employee, I want Profile to show Nickname (the plan's "Infloww name"), Tags, Language, Birthday, Source and Location in that order, so that the identity facts sit where Infloww puts them.
15. As an Employee, I want to edit the Nickname inline and have it saved to OnlyFans and our mirror when I leave the field, so that renaming a Fan works as it does today.
16. As an Employee, I want the Nickname's sync hint behind an ⓘ, so that the row stays one line.
17. As an Employee, I want to edit Tags and Language in Profile, so that those edits keep working.
18. As an Employee, I want Birthday (the plan's "Birthdate") and Source to show "—", so that I know we hold no such data.
19. As an Employee, I want Location (the plan's "Country/Region") as a box with a pin and "city, country", or "—" when it is unknown.
20. As an Employee, I want a Lists block showing the OF lists the Fan is on (the plan's "Fan lists"), or "—", so that I see list membership in Fan insights.
21. As an Employee, I want a Notes block with the Fan notes textarea (the plan's "Fan notes"), synced to OnlyFans' private note when I leave it, so that I keep notes where Infloww keeps them.
22. As an Employee, I want the Notes tab to show Creator notes (the plan's "Creator notes") as "—", so that I see the field exists in Infloww but is not stored by us.
23. As an Employee, I want the Sales tab to show Purchases over time, then a Sales block that opens with Buy rate (the plan's "Buy rate") as "—" and shows the Date / Gross / Net / Sent by table and the purchased-media rows (the plan's "PPV timeline") with refresh, load more and the media lightbox, so that the full purchase history is one tab away.
24. As an Employee, I want any field we have no data for to read "—", never an invented value, so that I can trust every number I see.
25. As an Employee, I want our own extras in a "+" Extras overflow next to the title, collapsed by default and labelled "Inflowwww extra": the Fan's avatar, name, @username, Creator and id; Last message in; Last seen; Subscribed at; Renewed at; Expires or Expired; Posts; the MASSppvEXCLUDE and MASSdmEXCLUDE switches; and the unsold PPVs with "Send to chat". That way they never push an Infloww block aside, and they are still one click away.
26. As an Employee with the Legacy flag off, I want no AI seller chip, AI profile or Persona claims in Fan insights, so that the pane matches Infloww.
27. As an Employee with the Legacy flag on, I want the AI seller chip (with its cancel) at the end of the Insights tab, and the AI profile and Persona claims in the Notes tab, each labelled "Inflowwww extra", so that the automation surfaces are back without displacing Infloww blocks.
28. As an Employee on a screen 1024px or wider with Fan insights pinned, I want a 280px column that Esc does not close, so that the three panes fit and stay put.
29. As an Inflowwww maintainer, I want the × hidden whenever a render site passes `alwaysOn`, so that today's render sites keep working until Phase 0 retires the prop. This is prop compatibility, not a product rule: under ADR 0002 the Pop-out window is a full Messages Pro whose Fan insights can be closed (Phase 0 spec, Implementation Decisions › `ChatSurface`).
30. As an Employee below 1024px, I want Fan insights to stay a slide-over sheet with the same tabs and blocks, closed by ×, a backdrop tap or Esc, so that phones keep one pane at a time.
31. As an Employee with the media lightbox open, I want Esc to close only the lightbox, so that one key press closes one layer.
32. As an Employee, I want opening Fan insights with a cached Fan profile to cost no OnlyFans user-profile read (`/users/`; the purchased-media and unsold gallery reads run as they do today, `FanDrawer.tsx:163-181`), and focusing Nickname or Fan notes to re-read at most once per stale window without overwriting my typing, so that the edit-freshness guarantees survive the restyle.
33. As an Employee, I want my unsaved Nickname or Fan notes text kept when I switch tabs, so that a tab click never loses typing.
34. As an Employee, I want "Loading fan profile…" while the Fan record loads, and save errors (including "OnlyFans rejected…") shown under the content, so that I know when something did not stick.
35. As an Employee, I want Fan insights in Inflowwww's colours, so that it matches the rest of the app (ADR 0001).
36. As an Inflowwww maintainer, I want `FanInsights.test.tsx` to pin the tab order, block order, row labels, "—" fields, the flag split and the Extras overflow, so that a later change cannot silently drift from Infloww.
37. As an Inflowwww maintainer, I want `fanDrawerEditFreshness.test.tsx` to stay unchanged and green, so that the restyle provably kept the edit-freshness contract.
38. As an Inflowwww maintainer, I want `messages-pro-insights.png` compared with `clone-messages-pro.png` through the Visual loop, so that leftover differences are recorded as `VISUAL GAP:` lines rather than forgotten.

## Implementation Decisions

- **Owns.** `FanDrawer` (restyled in place: layout, labels, blocks, tabs, extras placement) and the new test suite `FanInsights.test.tsx` beside it. Nothing else changes. `ChatSurface`, `useFanDrawerDefault`, `useOFUser`, the other hooks and the relay are untouched.
- **Interfaces.** `FanDrawer`'s props stay exactly as they are (`open`, `onClose`, `accountId`, `fanId`, `chat`, `pinned`, `alwaysOn`, `overlayHideOnDesktopWhenPinned`, `onComposeWith`), so both render sites in `ChatSurface`, and whatever Phase 0 does with them, keep working. The accessible structure is new, and it is what the test reads:
  - The overlay keeps `role="dialog"` named "Fan insights". The pinned column becomes a complementary landmark named "Fan insights" (its `aside` gets that `aria-label`), the contract Phase 0 sets and asks this Phase to keep (Phase 0 spec, Implementation Decisions › `FanDrawer`, and Contracts › Fan insights).
  - The head title is text.
  - The tabs are a `tablist` of three `tab`s with `aria-selected`.
  - Each Insights block is a headed section whose chevron is a button with `aria-expanded`, named "Collapse <title>" or "Expand <title>".
  - Rows are description-list term/value pairs.
  - The Extras overflow is a button named "Inflowwww extras" with `aria-expanded` and the title "Inflowwww extra".
- **Schema.** None.
- **Contracts.** None crosses a boundary. Data wiring is unchanged (binding, plan Phase 5): the same hooks run at the top of `FanDrawer`, with the same query keys, `enabled` conditions, pre-edit re-read (`refreshBeforeEdit`), blur saves and OF write-through, and the same ↻ invalidation set. No relay endpoint is added. No new runtime import from `@/lib/relay`, because the freshness test's module mock provides only `relay`, `proxyImage` and `proxyScrubFrame` (`fanDrawerEditFreshness.test.tsx:26-30`).
- **Tabs.** Tab state is local to `FanDrawer`, starts on Insights, and is not persisted. Only the active tab's blocks render. The nickname, notes and tags form mirrors stay in `FanDrawer`, so a tab switch does not drop typing. Blur fires before the tab button takes focus.
ASSUMPTION: tab state resets on mount and is not saved; overturned if Phase 0's deep link must reopen a remembered tab.
- **Insights tab.** The blocks run Spending behavior, Organization metrics, Subscription, Profile, Lists, Notes. The first four follow the Clone's order and the last two follow §3.3's six blocks (C[H523936]). Fan notes sits in the Notes block of this tab, not in the Clone's Notes tab. This is forced by observation: the freshness test needs the Nickname input and the Fan notes textarea on screen together (`fanDrawerEditFreshness.test.tsx:104-106`, `:132-141`), and §3.3 lists Notes as an Insights block. The plan's parenthetical (identity, subscription/renew, spend summary, notes, lists/tags, timeline) maps onto these blocks: identity → Profile, subscription/renew → Subscription, spend summary → Spending behavior, notes → Notes, lists/tags → Lists and Profile › Tags, timeline → the Sales tab. The plan's "as the clone lays them out" sets the order, so identity does not come first.
ASSUMPTION: the plan's "identity" is the Clone's Profile block, not today's avatar header; overturned if the human meant the avatar and name to lead the pane.
- **Notes tab.** It holds the "Creator notes" block, with "—". Under the Legacy flag it also holds the AI profile and Persona claims, matching the Clone's Notes tab, which carries the generated note and known facts (`messages.js:1572-1574`).
ASSUMPTION: Creator notes goes in the Notes tab, because the Clone's Fan note moved to the Insights tab; overturned if Infloww's bottom tabs turn out to differ.
- **Sales tab.** In the Clone's order (`messages.js:1532-1545`): a Purchases over time block, then a Sales block that opens with the "Buy rate: —" row, then the Date / Gross / Net / Sent by table (G19), then the existing purchased-media rows, including their refresh, load more and lightbox. The heading carries no count, because `summary.count` counts only the loaded page (`service/fans.py:1009`).
ASSUMPTION: Buy rate goes in the Sales tab because §3.3 puts it in the PPVs / PPV timeline block; overturned if it belongs in Spending behavior.
ASSUMPTION: Highest spend and PPV Avg keep today's page-bounded meaning (max and average over the loaded ledger page, `service/fans.py:1007-1011`), because the wiring is frozen; overturned if all-time figures are wanted, which needs a relay change outside this Phase. The review left this needs-human (see ## Review).
- **Cost.** Cost keeps today's format, "$x.xx" or "—", rather than the Clone's "free".
ASSUMPTION: the existing format wins over the Clone's "free" for price 0; overturned if parity review asks for "Free".
- **Collapse and grip.** The chevron collapses or expands its block, using local state that defaults to expanded and is not persisted. The grip is drawn with the title "not wired". Drag reorder is not built.
ASSUMPTION: collapse is built and reorder is not, because collapse costs local state while reorder needs per-Employee storage that the plan does not ask for; overturned if the plan adds reorder.
- **Nickname.** The Nickname input is always rendered, styled as an inline right-aligned value with a pencil. A click-to-edit pattern is out because the freshness test focuses the input directly.
ASSUMPTION: an input styled as text with a pencil is close enough to `.nick-edit`; overturned by the visual loop if the difference reads as a different control.
- **Extras overflow.** One Extras overflow for the Fan insights Region: a "+" in the head, left of ×, collapsed by default, that renders an "Inflowwww extras" section after the active tab's blocks. It holds, in this order:
  1. identity (avatar, name, @username, Creator label · id)
  2. Last message in, Last seen, Subscribed at, Renewed at, Expires or Expired, and Posts
  3. the MASSppvEXCLUDE and MASSdmEXCLUDE switches
  4. Unsold PPVs sent, with "Send to chat"

  Each item's tooltip says "Inflowwww extra". Its contents mount only when expanded, so the mass-exclude switches' own query waits until then. `FanDrawer`'s top-level hooks are unaffected.
ASSUMPTION: the "+" sits in the head and the section is the same on every tab; overturned if Phase 7 settles on a different Extras overflow pattern.
ASSUMPTION: the identity header counts as an extra (the Clone's head is the title only, and the Chat header already names the Fan); overturned if phone users need the name in the sheet.
ASSUMPTION: Unsold PPVs is a non-automation extra, not part of Infloww's PPV timeline; overturned if parity review matches it to Infloww's "Copy as draft".
ASSUMPTION: mounting the extras lazily, which delays the mass-exclude read until the overflow opens, is acceptable; overturned if that state must be warm when the pane opens.
- **Automation extras.** The AI seller chip, AI profile and Persona claims render only when `useLegacyAutomations()` is true (ADR 0003). Each has the tooltip "Inflowwww extra". The chip goes after the Notes block in the Insights tab, and the other two go in the Notes tab.
ASSUMPTION: the AI profile (gen_info output) and Persona claims count as automations; overturned if Phase 7 classifies them as non-automation extras, in which case they move into the Extras overflow.
- **Responsive.** From `lg` up, the pinned column is 280px (G1). Below `lg`, the overlay sheet keeps its width, backdrop, `aria-modal`, Esc and the lightbox's Esc precedence unchanged (`docs/routes.md:42`). The mobile `order-*` overrides are dropped, so one block order holds at every width. The below-`md` hiding of the chart (`FanDrawer.tsx:707`) is removed, so Purchasing trends shows its bars or its empty text at every width.
- **Esc with two instances.** On desktop with keep-open on, `ChatSurface` mounts the overlay (hidden only by `lg:hidden`) and the pinned column together (`ChatSurface.tsx:1175-1202`), and the hidden overlay's window Esc listener closes both (`FanDrawer.tsx:301-306`, `:619-620`), even while the pinned column's lightbox is open. The overlay instance given `overlayHideOnDesktopWhenPinned` therefore registers no Esc listener while `window.matchMedia("(min-width: 1024px)")` matches. Below 1024px Esc still closes the sheet, and the lightbox still owns Esc while it is open.
ASSUMPTION: the guard lives in `FanDrawer`, which this Phase owns, rather than in `ChatSurface`, which Phase 0 owns; overturned if Phase 0 stops mounting the overlay at lg+, in which case the guard is dead and is removed.
ASSUMPTION: dropping the phone-only reorder is fine, because the Clone's order is the parity target at every width; overturned if the phone shot review wants recency first.
- **Clone values.** Where the Clone shows a placeholder for data we lack ("Insufficient data", "Unknown", "Select date"), we render "—" (binding, plan Phase 5).
- **Missing is not zero.** Highest spend and PPV Avg render "—" when the ledger page has no items, instead of `fmtUsd`'s "$0" for a missing value (`FanDrawer.tsx:664-667`). Last spend renders "—" when there is no purchase. The summed totals keep `fmtSummDollars`, which already renders "—" when neither source has a positive value (`:675-679`).

## Testing Decisions

- **One seam: the `FanDrawer` component.** It is rendered with `@testing-library/react` under a `QueryClientProvider`, plus a `FlagsProvider` for the flag-on cases. The data hooks are mocked at their module boundary exactly as `fanDrawerEditFreshness.test.tsx` does: `useFan`, `useAccounts`, `useMassExclude`, `useLastPurchases`, `useFanPpvHistory`, `useFanChatMedia`, `useCatalog`, `PersonaClaims`, and `@/lib/relay`. `of-user` is seeded with `setQueryData`, which works because `useOFUser` does not refetch on mount (`useOFUser.ts:113`). Both suites hit this one seam. Because the hooks are mocked, writes are asserted at the mocked boundary (`update.mutate`, `relay.put`), not through real hooks.
ASSUMPTION: hook-level mocks over real hooks with a mocked relay, by house precedent (`fanDrawerEditFreshness.test.tsx:26-60`); overturned if a wiring regression slips past them, in which case the suite moves to the relay boundary.
- **`FanInsights.test.tsx` (new) checks external behaviour only:**
  - tabs read Insights, Sales, Notes, and Insights is selected
  - the head text follows the tab
  - Insights block headings in order
  - row terms in order inside each block, including every plan field's label
  - "—" for Creator notes, Buy rate, Birthday, Source, Spending power, Chargeback risk and Tip Avg on a sparse Fan
  - real values for Total spend, Location, Auto-renewal (On, Off, —), Duration and the Lists chips when seeded
  - "Full history ↗" selects the Sales tab
  - a chevron collapses its block and toggles `aria-expanded`
  - with the flag off, the AI profile, Persona claims and AI seller chip are absent; with the flag on, all three are present
  - the Extras overflow starts collapsed (no MASSppvEXCLUDE switch); expanded, it shows the identity, the extra stats and both switches
  - the overlay renders a dialog named "Fan insights" that × and Esc close
  - pinned renders a complementary landmark named "Fan insights", no dialog, and ignores Esc
  - an overlay given `overlayHideOnDesktopWhenPinned` and a pinned instance rendered together with one shared `onClose`, `matchMedia` stubbed to match 1024px: Esc does not call `onClose`; with the lightbox open, Esc closes only the lightbox
  - writes: blur on Nickname calls `update.mutate({ custom_nickname })` and `relay.put` to OF; blur on Fan notes calls `update.mutate({ notes })` and `relay.put`; blur on Tags calls `update.mutate({ tags })`; changing Language calls `update.mutate({ language })`; a rejected OF write shows "Saved locally, but OnlyFans rejected…"
  - moved controls work: Send to chat calls `onComposeWith`; ↻ invalidates the same query families as today (`FanDrawer.tsx:196-215`); Load more re-calls `useFanPpvHistory` with limit 32; with the flag on, the AI seller chip's cancel calls its mutation
  - the Sales table shows Date, Gross, Net and Sent by for a seeded ledger item; Highest spend and PPV Avg read "—" with no ledger items
  - typing in Fan notes, switching to Sales and back keeps the text
- **`fanDrawerEditFreshness.test.tsx` (existing) runs green, unchanged by this Phase.** It needs the Nickname input (placeholder from `chat.withUser.name`) and the Fan notes textarea (placeholder "loves bondage, German, paid $500 last week…") both rendered in the default tab, with `onFocus` re-reads, and a sparse Fan record (`tags: []`, no location, no `listsStates`) that must render without throwing.
- **Not unit-tested.** Pixel Geometry and the 1024px breakpoint switch are not checked here, because jsdom has no layout. The Visual loop (`messages-pro-insights.png`) and the manual phone check cover them.
- **Prior art:** `app/components/chat/fanDrawerEditFreshness.test.tsx` (same seam and mocks), `app/components/chat/AiStatusStrip.test.tsx`, and `app/test-utils.tsx` (`renderWithProviders`).
ASSUMPTION: "stays green" means this Phase's own diff leaves `fanDrawerEditFreshness.test.tsx` untouched, so its assertions run unweakened (review D9). The check compares against the merge base with `main`, the house idiom (Phase 3's Acceptance: `git diff --quiet "$(git merge-base HEAD main)" -- service/`), not against a pinned commit. Phase 3 legitimately extends the file (its seam 3), and a pinned `e97a517` would fail in whichever order the two land. This assumes each Phase lands from its own branch off `main`. It is overturned if Phases are committed straight to `main`, in which case the base is the commit before this Phase's first commit.

## Acceptance

```sh
set -e
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
test -f app/components/chat/FanInsights.test.tsx
pnpm -C app exec vitest run components/chat/FanInsights.test.tsx components/chat/fanDrawerEditFreshness.test.tsx
git diff --quiet b8aeaa988e2765167751c62cc1a458021eb33c0f -- app/components/chat/fanDrawerEditFreshness.test.tsx
test -z "$(grep -nE '[" :]order-' app/components/chat/FanDrawer.tsx)"
scripts/ui-shots.sh
test -s docs/screenshots/messages-pro-insights.png
test -s docs/screenshots/clone-messages-pro.png
test -s docs/screenshots/messages-pro-report.json
# manual: Read docs/screenshots/messages-pro-insights.png and docs/screenshots/clone-messages-pro.png side by side; write the visual diff list for the Fan insights Region (position, size, label, order, missing element); fix and re-run scripts/ui-shots.sh, up to three rounds; record what remains as VISUAL GAP: lines with the reason.
# manual: record the messages-pro-report.json summary in the Phase result and commit the final PNGs with the code.
# manual: at 390x844 open a Thread, tap "Fan insights"; the slide-over sheet shows the Insights/Sales/Notes tabs and the same blocks, Spending behavior shows Purchases over time (bars or its empty text), and ×, a backdrop tap and Esc each close it (docs/routes.md).
```

## Depends on

- **Phase 0.** It provides `scripts/ui-shots.sh` and `docs/ui-shots.md`, and the shots `messages-pro-insights.png`, `clone-messages-pro.png` and `messages-pro-report.json`. Only the Visual loop and the last four commands of Acceptance need it. The `FanDrawer` restyle and both vitest suites can land before it. Phase 0 also sets two contracts this Phase keeps: the lg+ pane is a complementary landmark named "Fan insights" (Phase 0 spec, Implementation Decisions › `FanDrawer`, and Contracts › Fan insights), and the lg+ pane can be closed, with `forceDrawerOpen` dropped from `ChatSurface` (Implementation Decisions › `ChatSurface`). The vitest suites do not depend on either, because they render `FanDrawer` directly.
ASSUMPTION: Phase 0's harness opens Fan insights for one of its mocked Fans when it takes `messages-pro-insights.png`, and this Phase does not extend the harness's mocks; overturned if the shot shows Fan insights closed or empty, in which case the gap goes to Phase 0.

## Out of Scope

- **Drag reorder and a per-Employee saved block order** (C[H418759]). No plan line asks for it, and it needs per-Employee storage. The grip says "not wired".
- **Saving which blocks are collapsed.** No plan line asks for it.
- **The Lists block's ⚙️ quick editor** (add, remove, create). No plan line; the wiring is frozen; Phase 3's Avatar menu owns "add to lists".
- **The Notes template** (Age, Job, Preferences…, ⚙️ template editor) and the 13,000-character limit. No plan line, and nothing stores them.
- **Editing Creator notes**, with autosave and the 10,000-character limit. There is no field, and the wiring is frozen. It renders "—".
- **The Profile fields from the help list** (Local time, Salary frequency, Last pay date, Salary). They are not plan fields and not in the Clone. §3.3 says to prefer the help list's Profile over the Clone's (`docs/infloww-screens.md:260`), but the plan binds "the clone's block order and labels" (plan Phase 5, Decisions), so the Clone's Profile rows win.
ASSUMPTION: the plan's Decision outranks §3.3's note for Profile rows; overturned if the human wants the help list's Profile rows, which would each render "—".
- **The PPV timeline's Highest price, Lowest price, "Copy as draft" and "See chart".** They are not plan fields.
- **Spending power and Chargeback risk classifiers**, and per-role visibility. The relay has no data for them, and they would be backend work. They render "—".
- **The Clone's tiny line** ("N purchases | $X last 30d"). Only the rewired Clone has it (`messages.js:1421-1428`), and its Infloww meaning is unknown.
- **The Clone's "Vault history" box** ([CL ?]). It needs `/admin/vault/fan-history`, which `FanDrawer` does not read, and the wiring is frozen.
- **A purchase count in the Sales heading.** The count covers only the loaded page (`service/fans.py:1009`).
- **The Messages Pro token module.** Phase 6 owns it.
- **The "Ours" entries in `docs/messages-pro-parity.md`.** Phase 7 owns them.
- **The Chat header's "Fan insights" button and the windowed insights toggle.** Phases 3 and 0 own them.
- **The "Keep open by default" setting** (`useFanDrawerDefault`, toggled from `ChatList`). It belongs to the Fan List Region (Phase 2).
- **Two defects in the frozen wiring, recorded and not fixed.** (1) An empty OF nickname or note falls back to the local mirror, so a clear made on OnlyFans shows the old text (`FanDrawer.tsx:232-233`). (2) The PATCH response carries no `profile` (`service/fans.py:1062`) and `useFan` writes it straight into the cache (`useFan.ts:39-40`), so with the Legacy flag on the AI profile blanks after an edit until the next refetch. Both need wiring or relay changes this Phase may not make.
- **Retiring the `alwaysOn` and `forceDrawerOpen` props.** That follows Phase 0's Deep link work, and Phase 5 keeps the props stable.

## Further Notes

Every open question is decided above except the page-bounded Highest spend and PPV Avg, which the review left needs-human (B11). Each decision that did not come from observation or a human's written instruction carries an ASSUMPTION line where it is made. In short:

- Block order and the Fan notes placement were settled by observation (the freshness test) and by §3.3.
- The field mapping, the extras placement, the chart kind and the Geometry ownership were settled by the ladder's later rungs: house precedent, reversibility and the smallest change.
- The only items that could reopen this Phase are the parity review in Phase 7 and the Visual loop's `VISUAL GAP:` list.
- Phase 7's parity table should mark Fan insights partial, not done: reorder, the Lists editor and custom OF lists, the Notes template, Creator notes, Organization metrics and the help list's Profile rows are absent.

## Review

codex · 2026-10-12. Blind call (B) without the spec, then draft call (D) with it, both `codex exec --sandbox read-only`, reasoning effort high, exit 0, non-empty output. The blind call's log shows no read of `docs/spec/`.

- B1 (§3.3 prefers the help list's Profile over the Clone's) — **partial**: the Clone's Profile rows stay, because the plan binds "the clone's block order and labels". Out of Scope now answers §3.3's note (`docs/infloww-screens.md:260`) with an ASSUMPTION.
- B2 (alternative: extract presentation and keep the data controller) — **reject**: "restyled in place" does not forbid in-file sub-components, which `FanDrawer` already has (`PpvSalesSection`, `Stat`). Nothing shows that the in-place restyle breaks the controller.
- B3 (presentation parity is not capability parity) — **accept**: Further Notes tells Phase 7 to mark Fan insights partial and lists the gaps.
- B4 (the plan's parenthetical puts identity first) — **accept**: the Insights tab decision maps each plan category onto a block, with an ASSUMPTION that "identity" is the Profile block. The order stays the Clone's, per "as the clone lays them out".
- B5 (collapse, reorder and per-Employee persistence; `CONTEXT.md:64-65` says reorderable) — **reject**: no plan line asks for reorder or persistence. The glossary defines Infloww's term, not this Phase's scope. The "not wired" grip and Out of Scope already record it.
- B6 (Creator notes are Creator-scoped, so relabelling the textarea would be wrong) — **reject**: the spec never relabels the textarea. Creator notes renders "—" (Field table).
- B7 (list data is partial: `listsStates` holds system lists only, and the folder preview is capped) — **partial**: `listsStates` stays, because `useAllChatFolders` would be a new query and the wiring is frozen. The ASSUMPTION now says the block is incomplete by construction, and Phase 7 marks Lists partial.
- B8 (`source="onlyfans"` is not acquisition Source) — **reject**: the spec already renders Source "—" for this reason.
- B9 (`his_age` cannot fill a Birthdate) — **reject**: this agrees with the spec, which renders Birthday "—".
- B10 (the Auto-renewal derivation is unproven; the Clone uses `renewedAt`) — **partial**: the status-based rule stays, by house precedent (`utils.ts:84-90`). The ASSUMPTION now cites the Clone's rule (`messages.js:1443`), and any other status string renders "—" (`utils.ts:126`).
- B11 (Highest spend and PPV Avg are page-bounded, include pending payments, and change on Load more) — **needs-human**. Spec position: keep today's summary, because the plan freezes data wiring, and the number is real, not invented. Reviewer position: the labels read as lifetime figures, but `max_cents`/`avg_cents` cover only the loaded ledger page (`service/fans.py:1006-1011`). Load more grows that page (`FanDrawer.tsx:156-157`, `:571`), so Insights numbers change when the Employee pages Sales, and PPV Avg is not PPV Total ÷ count, because PPV Total is all-time. What settles it: the human picks one of (a) page-bounded as specced, (b) "—" whenever the page is full (`items.length === salesLimit`), or (c) a relay change to all-time max/avg in `service/fans.py:1006-1011`, which the plan allows only for a proven-missing endpoint. Help-center text defining Highest spend's window (H418759) would also settle it.
- B12 (missing versus zero: `fmtUsd` renders a missing value as "$0") — **accept**: a new "Missing is not zero" decision, plus a test that Highest spend and PPV Avg read "—" with no ledger items.
- B13 (13,000/10,000-character limits, Notes template, autosave, clear-versus-omitted) — **reject**: these are already Out of Scope with reasons. Clear semantics belong to the frozen wiring (see B19).
- B14 (per-role visibility of Organization metrics; classifying the extras) — **reject**: per-role visibility is already Out of Scope, and the Extras overflow and Automation extras decisions already place every current extra.
- B15 (Phase 6 does not lift Phase 5's geometry obligations) — **reject**: the spec already opens with the measured gap table and binds the Visual loop in Acceptance.
- B16 (test through real hooks with a mocked relay) — **partial**: hook-level mocks stay, by house precedent. Writes are now asserted at the mocked boundary, with an ASSUMPTION naming what would move the seam.
- B17 (`ChatSurface` mounts the pinned and overlay drawers together) — **accept**: merged into D1.
- B18 (DOM order is not visual order while `order-*` classes exist) — **accept**: Acceptance now greps `FanDrawer.tsx` for `order-` classes, so the asserted DOM order is the visual order.
- B19 (an empty OF nickname or note brings the local mirror's text back, `FanDrawer.tsx:232-233`) — **partial**: confirmed. Recorded in Out of Scope as a defect in the frozen wiring, not fixed here.
- B20 (the PATCH response lacks `profile`, so the AI profile blanks after an edit) — **partial**: confirmed (`service/fans.py:1062`, `useFan.ts:39-40`). Recorded in Out of Scope, not fixed here.
- B21 (Acceptance cannot run: no node_modules, no `scripts/ui-shots.sh`) — **reject**: node_modules is missing only from the sparse review worktree. `ui-shots.sh` is a declared Phase 0 deliverable (Depends on).
- D1 (Esc on the hidden overlay twin closes the pinned column, even with the lightbox open) — **accept**: confirmed (`ChatSurface.tsx:1175-1202`, `FanDrawer.tsx:301-306`, `:619-620`). Added the "Esc with two instances" decision (a `matchMedia` guard in `FanDrawer`) and a two-instance test.
- D2 (the unlabelled pinned column breaks Phase 0's landmark contract; US29 contradicts ADR 0002) — **accept**: confirmed in the Phase 0 spec (Implementation Decisions › `ChatSurface` and › `FanDrawer`, Contracts › Fan insights). The pinned column is now a complementary landmark named "Fan insights". US29 is now prop compatibility, and Depends on lists both Phase 0 contracts.
- D3 (all four editors could stop saving and the tests would still pass) — **accept**: tests now assert the `update.mutate` payloads, `relay.put`, and the "OnlyFans rejected…" message.
- D4 (US32's "no live OnlyFans read" is false; gallery reads run on open) — **accept**: US32 is narrowed to the cached `/users/` read.
- D5 (G11 and G19 keep our presentation against the Clone) — **accept**: G11 is now the Clone's 12-bucket bars and G19 the Date / Gross / Net / Sent by table. Every column is on `PpvHistoryItem`, so the wiring is unchanged. The media rows stay under the table, with an ASSUMPTION.
- D6 (Purchasing trends is hidden below md) — **accept**: the below-md hiding is removed, and the phone manual check names the chart.
- D7 (moved Sales and Extras controls get presence tests only) — **accept**: added tests for Send to chat → `onComposeWith`, ↻ invalidation, Load more limit, and the chip's cancel.
- D8 (Acceptance does not fail fast) — **accept**: `set -e` added. The new grep uses `test -z`, because a `!` pipeline is exempt from errexit.
- D9 (the byte-identity gate on the freshness test exceeds "stays green") — **reject**: the plan names the *existing* test, and only an unchanged file proves its assertions ran unweakened. New tests go in `FanInsights.test.tsx`, and the ASSUMPTION already names the overturn.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: the check `git diff --quiet e97a517 -- …fanDrawerEditFreshness.test.tsx` (`:199`) clashes with Phase 3's seam 3, which extends that file (`phase-03-chat-header-message-list.md:245`). **accept**: checked against both lines. The check is now "unchanged by Phase 5", against the merge base (rung 3, the house idiom), and the ASSUMPTION is rewritten. D9's reason (the existing assertions must run unweakened) still holds.
- Green: this Phase lands before Phase 3, which avoids the test-file clash. **accept**: it lands in Wave 1 (`plan-review.md`). Phase 3 then makes `focusNotesRequest` switch to the Insights tab and expand the Notes block.
- Yellow: this Phase stands alone after Phase 0. **accept**: Depends on names only Phase 0, so nothing changes.
- White: B11 (Highest spend and PPV Avg are page-bounded) still needs the human. **accept**: it is listed verbatim under "Needs the human" in `plan-review.md`. This spec does not change.
- Black: Phase 6's rows FI18–FI32 contradict G11 (`:21`) and G19 (`:29`). **accept**: the fix is in Phase 6, whose rows now follow G11's bars and G19's table. This spec does not change.

## Amended 2026-10-21

At the owner's request, Fan insights shows every extra by default. The "+" Extras overflow of story 25 is gone. Fan identity, Mass exclude and Unsold PPVs are Insights blocks, and each Insights block can be dragged, removed and re-added from the head's "+". This overturns G21's order: by default the Insights tab reads Fan, Spending behavior, Unsold PPVs sent, Notes, Mass exclude, Subscription, Profile, Lists, and Organization metrics is removed (the "+" adds it back). The extra Fan stats (Last message in, Last seen, Subscribed at, Renewed at, Expires or Expired, Posts) are dropped. Stories 26-27 and the Automation extras rule are overturned for the AI profile and Persona claims, which show in the Notes tab with the flag off too (the AI seller chip is already gone). The MASSppvEXCLUDE and MASSdmEXCLUDE switches are now one switch, "MASSdmEXCLUDE — Never include in any mass send", because MASSppvEXCLUDE was merged into MASSdmEXCLUDE. See ADR-0003's 2026-10-21 amendment.
