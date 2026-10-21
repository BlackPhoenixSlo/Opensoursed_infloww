# Phase 2b — My Automations: Auto mass messages with auto delete

**Objective.** The mass messages and the Auto delete next to them sit where the Dashboard bundle puts them. The bundle puts them in the "Mass Messages" tab of Smart Messages, so they go on `/growth/smart-messages`, not under My Automations. They are built from the existing mass-message and unsend code. Because this Phase lands before Phase 2's Smart Messages ticket, it also builds the page frame that both share: the header, the parent tab strip and the one "Create message" pop-up, whose Mass messages section is this Phase's and whose Automated messages section Phase 2 fills. The recheck record says where the bundle puts them, and every difference from the Layout capture carries the "Inflowwww extra" label.

## Problem Statement

An owner or Chatter who wants to send to many Fans at once, or clean those sends up later, finds that work on today's Smart Messages page, under two of our own tabs ("Mass messages" and "Scheduled"), plus two header buttons. The page gives no sign that Infloww arranges mass messages differently. ADR-0014 separates one-Fan Triggers from many-Fan sends. Phase 2 will turn Smart Messages into the Trigger list. Until the mass half has its own place on the page, Phase 2 cannot add the Trigger list without either burying it under the mass list or leaving mass sending, scheduled sends, bulk unsend and the hourly Auto-unsend sweep with nowhere to live. Mass Nudge, which is a broadcast, is reachable today only from the flag-only Legacy automations page. The hourly Auto-unsend card also has a data-loss trap: saved with every class unchecked, it stores an empty policy, which the Relay reads as the old per-chat sweep of outbound DMs (`app/components/settings/MassMessagesTab.tsx:451-455`; `service/automations/unsend_messages.py:629-630`).

## Solution

The owner's placement line includes an exception: "If REA shows Infloww puts them somewhere else, follow the bundle and record where it was found" (plan line 10). The bundle observed for this spec shows that the exception applies (offsets verified by a read-only `python3 -I` byte search of `~/Downloads/infloww-remote-web/index.9f50f370.js`; each offset is the first byte of the quoted token). Infloww's Smart Messages page has two parent tabs, "Automated Messages" and "Mass Messages", in that order (`var MessageSendTitle` @14654355; the strings @14654443 and @14654486). The Mass Messages tab has child tabs by send type, Priority mass message and OF mass message (`changeSendType({parentTab:MessageSendType.Mass` @15747892; `queryOfMassMessageList` @14591116). The page-level "Create message" pop-up (`xTitle:"Create message"` @14716722) renders a Mass messages section from `massMsgList` (@14715019): "Priority mass message" / "Sent to priority inbox" and "OF mass message" / "Sent to general inbox" (`var massMsgList` @14707943). Its Automated messages section is `automatedMsgList` (@14708609). Auto-unsend is a per-message setting in the Smart Message editor: an "Auto-unsend" button opens "Auto unsend settings", with "Unsend messages" and an hours/minutes delay (`function Unsend$1` @14979383, "Auto unsend settings" @14981410, "Unsend messages" @14981830, mounted by `hasAutoUnSend(Lt.sendType)` @15013397). OF mass messages do not support it (`function hasAutoUnSend` @14776278; the OF switch modal's "will not support" @14793004).

So the user opens Growth > Smart Messages and finds the capture's header, with its create button, and a "Mass Messages" tab laid out as the capture records it.

- The create button opens the one "Create message" pop-up. Its Mass messages section holds the mass entries: OF mass message opens our existing mass composer, Priority mass message is Not wired, and "Message online fans" (the composer's online mode) is there too, labelled as an extra.
- The Mass Messages tab holds the sent history with bulk unsend (under the OF mass message child), the scheduled queue (its own labelled list, because it holds direct sends as well as mass sends), and Mass Nudge, labelled as an extra and hidden from chatter-only sessions.
- Next to the list sits the Auto delete: the composer's per-broadcast "Auto-unsend this broadcast after" field and our hourly "Auto-unsend" sweep, both labelled as extras, because Infloww offers no Auto-unsend on an OF mass message, which is what our sends are. The sweep's Save stays disabled until at least one class is on.

The page opens on this tab from `?tab=mass`, so the Chat header's "Mass message statistics" link still lands on mass messages after Phase 2 adds the Automated Messages tab in front of it. No new route and no new nav item are added. My Automations stays Auto Post + Auto Story. Nothing sends differently.

If the owner vetoes the bundle placement, the same section is mounted on a My Automations route instead (Further Notes, fallback).

## User Stories

1. As an owner, I want my mass messages to sit where Infloww puts them (Smart Messages > Mass Messages), so that a habit learned in Infloww works here.
2. As a reviewer, I want the Layout capture `growth-smart-messages.md` to record where the bundle puts mass messages and Auto-unsend, with chunk and offset, and this Phase's recheck record to say which placement was built, so that the placement can be checked rather than taken on trust.
3. As an owner, I want the Mass Messages tab's label, child tabs, order, filters, columns and empty state to come from the capture, so that the layout matches Infloww.
4. As an owner, I want each child tab of the capture that has no relay behind it rendered Not wired (`disabled` + `title="not wired"`), so that nothing fakes a send.
5. As an owner, I want "Priority mass message" in the Create message pop-up's Mass messages section shown as Not wired, so that I can see that priority-inbox sending is not built. No existing path sends to priority inboxes, and the plan forbids a new one.
6. As an owner, I want "OF mass message" to open the existing mass composer in its standard mode, so that I send through the path that already works (`send_mass_message`, OF's `messages/queue`).
7. As an owner, I want "Message online fans" (the composer's online mode) kept in the pop-up's Mass messages section and labelled "Inflowwww extra", so that the online-targeted blast I use today is still reachable.
8. As an owner, I want the scheduled-send queue (`ScheduledTab`) in the Mass Messages tab as its own list labelled "Inflowwww extra", headed so that it says it holds scheduled direct and mass sends, so that queued broadcasts are seen and cancelled where mass messages live and a one-Fan send is never presented as a mass message.
9. As an owner, I want the sent-broadcast history and bulk unsend (`MassMessagesTab`) under the OF mass message child, so that I can pull a broadcast from every recipient where I sent it.
10. As an owner, I want the Auto delete next to the mass list, so that "unsend after a time" sits beside the sends it cleans up (owner, 2026-10-17).
11. As an owner, I want the composer's per-broadcast "Auto-unsend this broadcast after" field to remain the per-message Auto delete, labelled "Inflowwww extra", so that I keep it and know that Infloww offers per-message Auto-unsend only on Priority mass and Automated messages, never on the OF mass messages our composer sends (@14776278; @14793004).
12. As an owner, I want the hourly "Auto-unsend (automation)" card (`AutoUnsendPanel`, the "Auto-unsend mass" `unsend_messages` rule per Creator) labelled "Inflowwww extra", so that I know Infloww has no per-Creator sweep by message type.
13. As an owner, I want Mass Nudge (`MassNudgeTab`) in the Mass Messages tab, labelled "Inflowwww extra", so that this broadcast to every online Fan lives with the other broadcasts and not with the per-fan Triggers.
14. As an owner, I want Mass Nudge reachable with the Legacy flag off, so that moving it does not hide it (plan line 89; ADR-0014, second ASSUMPTION).
15. As a Chatter in a chatter-only session, I want no Mass Nudge panel in the Mass Messages tab, and its relay routes to stay mapped to Auto Post only, so that moving it widens no chatter's reach: today it is on the flag-only `/automations` page, which chatters never see (`app/lib/nav.ts:140`).
16. As a Chatter whose role does not grant Smart Messages, I want the Mass Messages tab's routes refused with "Your role does not allow Smart Messages", unless another granted page serves the same route, so that the page map still holds.
17. As a user, I want `/growth/smart-messages?tab=mass` to open on the Mass Messages tab, so that a link can land on mass messages whatever the default tab is.
18. As a Chatter in Messages Pro, I want the Kebab menu's "Mass message statistics" to open `/growth/smart-messages?tab=mass` in a new tab, so that it shows mass messages and not the Trigger list.
19. As a user with an old bookmark, I want `/settings?tab=mass` and `/settings?tab=scheduled` to keep landing on Smart Messages' mass messages, so that the redirects in `next.config` still work after Phase 2 puts Automated Messages first. Next passes the source query through, so they arrive as `?tab=mass` and `?tab=scheduled`, and the page must accept both.
20. As Phase 2, I want the page frame (header, parent tab strip, Create message pop-up) already built by this Phase, with a slot for the Automated Messages tab and one for the pop-up's Automated messages section, so that I add the Trigger half without re-touching mass code or rebuilding the frame.
21. As an operator, I want the relay unchanged (`send_mass_message.py`, `mass_premade.py`, `mass_nudge.py`, `unsend_messages.py`, `mass_broadcast_cache.py`), so that no send or unsend behaves differently.
22. As an operator, I want the existing relay tests (`test_send_mass.py`, `test_mass_lifecycle.py`, `test_a12_unsend.py`, `test_unsend_mass_policy.py`) in the effort suite and green with mocked OF calls only, so that the move is proven not to change sending.
23. As a reviewer, I want a vitest that renders Smart Messages with a mocked relay and checks the frame, the Mass Messages tab, the Not wired markers, the extra labels and the Auto-delete control, so that the layout and labels are pinned.
24. As a reviewer, I want the page rechecked against the bundle with REA before the ticket closes, so that the transcription is verified.
25. As the Phase 6 grader, I want the recheck record `.scratch/infloww-parity-round-2/rechecks/growth-smart-messages.md` to carry this Phase's placement note for row 3.5.1 and the Labelled improvements lines for the Auto-unsend sweep, per-broadcast Auto-unsend, "Message online fans", the scheduled list and Mass Nudge, so that sign-off grades against the truth without this Phase touching the matrix.
26. As a test author, I want no live OnlyFans write from any test, so that the suite never sends.
27. As an owner, I want the Auto-unsend card's Save disabled, with a line saying to turn on at least one class, while every class is off, so that I can never store an empty policy that the Relay would run as a per-chat sweep of my DMs.

## Implementation Decisions

- **Owns.**
  - `growth/MassMessagesSection` (new, in `app/components/growth/`). This is the body of the bundle's "Mass Messages" tab: the child tabs, `MassMessagesTab`, `ScheduledTab`, `MassNudgeTab` (owner sessions only) and the extra labels.
  - `growth/SmartMessagesPage`, the page frame: the capture's header (title, creator chip, "Learn" and the create button, as the capture records them), the parent tab strip, and the one "Create message" pop-up. Its own "Mass messages" / "Scheduled" strip and header buttons are replaced. It seeds the tab from `?tab=` through `useTabParam`.
  - The pop-up's Mass messages section (OF mass message, Priority mass message, "Message online fans").
  - `settings/MassMessagesTab`: two edits only. The "Inflowwww extra" label on its Auto-unsend card, and that card's Save guard (disabled while no class is on, with the reason shown).
  - `compose/MassMessageComposer`: one edit only, the "Inflowwww extra" label (`title={EXTRA_LABEL}` plus the visible tag) on the "Auto-unsend this broadcast after" field.
  - `chat/MessageStatsLink`: the href.
  - One new case in `service/tests/test_role_enforcement.py` (Testing, seam 3). The page map in `service/permissions.py` is not edited by this Phase.
  - A `relay` step in `.scratch/infloww-parity-round-2/suite.sh` naming the four mass relay tests and `test_role_enforcement.py` (appended to if another Phase added the step first).
  - This Phase's entry in `.scratch/infloww-parity-round-2/rechecks/growth-smart-messages.md` (Phase 0's recheck record contract).
- **Interfaces.**
  - `SmartMessagesPage` owns the parent tab strip and the Create message pop-up. It exposes two slots that Phase 2 fills: one parent tab placed before "Mass Messages", and the pop-up's Automated messages section placed as the capture orders it. Until Phase 2 lands, both are empty and the Mass Messages tab is the only parent tab.
  - `MassMessagesSection` is a default export with no required props. The section owns everything under "Mass Messages". It takes no Creator prop, because each panel it mounts already picks its Creators (`useActiveAccounts`). It hides `MassNudgeTab` when `isChatterOnly` (`app/lib/session`) is true, the predicate the nav and Applied settings already use.
  - `SmartMessagesPage` accepts `?tab=mass`, and `?tab=scheduled` as an alias that opens the same Mass Messages tab. The tab key `mass` is the stable id. Phase 2 adds its own key for "Automated Messages" and keeps `mass` and the `scheduled` alias as they are. `useTabParam` ignores an unknown value and leaves the default tab open (`app/hooks/useTabParam.ts`), so without the alias `/settings?tab=scheduled` would land on Phase 2's Trigger list.
  - `MessageStatsRows`' link becomes `/growth/smart-messages?tab=mass`. Target and rel are unchanged.
  - `MassMessagesTab`, `ScheduledTab`, `MassNudgeTab`, `LazyMassMessageComposer` and `AutoUnsendPanel` keep their exports and behaviour, apart from the Save guard. They are mounted somewhere new, not moved on disk and not rewritten (plan: "Move, not rewrite"). Plan Work 2 says "from `SmartMessagesPage.tsx`", but `MassNudgeTab` is not mounted there today: it is mounted by `ReadyMadePanel` (`app/components/automations/ReadyMadePanel.tsx:260`) and by `compose/MassNudgeComposer`, which nothing imports. The step is read as "mount these in the new section". `MassNudgeComposer` is left as it is.
  - `ReadyMadePanel` keeps its Mass Nudge tab for the flag-only `/automations` page.
- **Schema.** None. Auto delete stays the existing `unsend_messages` `automation_rules` row named "Auto-unsend mass", plus the composer's `unsend_after_hours` body field.
- **Contracts.**
  - Relay routes are unchanged, and so is the page map. `/admin/mass-nudge` stays mapped under `/growth/auto-post` only (`service/permissions.py:235`). Owners bypass role enforcement (`granted_pages`, `service/permissions.py:89`), so the owner-only Mass Nudge panel needs no Smart Messages route. The section's other calls (`/admin/mass-messages`, `/admin/automation-rules`, the vault picker in `_MASS`) are already in the Smart Messages entry.
  - `SHARED_ONLY` in `test_role_enforcement.py` is unchanged.
  - The `next.config` redirects for `tab=mass` and `tab=scheduled` keep `/growth/smart-messages` as their target (`app/next.config.ts:87-88`). Next passes the source query through, so `SmartMessagesPage`'s `mass` key and `scheduled` alias catch them, and the redirects are not edited.
- **Layout.**
  - The header, the parent tab strip, the Create message pop-up's Mass messages section and the Mass Messages tab's labels, child tabs (Priority mass message / OF mass message, as the capture names them), order, filters, columns and empty state are transcribed from the capture. Each control carries its Inventory `C[…]` tag.
  - Our panels are mounted inside the capture's structure. The sent history goes under the OF mass message child, because our sends are OF's `messages/queue`, which Infloww calls the general inbox. The scheduled queue is not put under a send-type child: `ScheduledTab` lists direct and mass sends together (`app/components/settings/ScheduledTab.tsx:7-9`). It sits in the Mass Messages tab as its own list, labelled "Inflowwww extra", with a heading that says it holds every scheduled send, direct and mass. It is not filtered, because filtering is a rewrite and would leave scheduled direct sends with no home.
  - Where our panel shows something the capture lacks, such as the scheduled list or the bulk-unsend toolbar, that element carries a visible "Inflowwww extra" tag and `title={EXTRA_LABEL}` (`app/lib/openinflowwwwExtras.ts`; house use in `growth/AutoFollowTab`).
  - A control the capture shows that no existing read or write can back is Not wired with the house marker. Priority mass message is the known case.
- **Auto delete.**
  - The per-message Auto delete is the existing composer field. It is an extra, not a match: Infloww's per-message Auto-unsend exists for Priority mass and Automated messages only (`function hasAutoUnSend(S){return S!==MessageSendType.OF}` @14776278; the OF switch modal lists "Auto-unsend" as unsupported @14793004), and our sends are OF mass messages. It is kept, because removing it would change how mass messages unsend, and it carries the "Inflowwww extra" label. Its scheduled-send caveat stays as it is.
  - The per-Creator hourly sweep (`AutoUnsendPanel`) sits next to the mass list, as it does today inside `MassMessagesTab`, and is labelled "Inflowwww extra". It can never grade as a match: Infloww's model is a per-message step (Inventory "Unsend messages", "Auto-unsend settings"), ours is an hourly rule per Creator and class. ADR-0014's original "no auto-delete string in the bundle" came from a search for "auto delete"; the bundle does have "Auto-unsend", but only per message.
  - **Save guard.** The card's Save is disabled while text, media and price are all off, and a line under it says that at least one class must be on. An empty `policy` is never sent. The reason: the Relay treats an empty policy as the per-chat sweep (`wants_per_chat = … or not wants_mass`, `service/automations/unsend_messages.py:629-630`), which unsends outbound text DMs, and the Relay stays unchanged in this Phase.
- **Mass Nudge** is a broadcast, so it is in the mass section and not in Phase 2's Trigger list (plan line 89). It is labelled as an extra, because the bundle's "Nudge" is the per-fan "Messages fans when they come online" Automated message (`var automatedMsgList` @14708609), which Phase 2 maps to `nudge_online`. It renders for owner sessions only.
- **No new sending path.** Every send control reaches an existing hook (`useMassMessages`, `useMassNudge`, `useAutomations`, the composer's existing POST). Nothing is added to the relay.

## Testing Decisions

The seams, highest first:

1. **`SmartMessagesPage` rendered with `MassMessagesSection` inside, with `@/lib/relay` mocked**, one new vitest file, `app/components/growth/MassMessagesSection.test.tsx`. It verifies:
   - `?tab=mass` opens the Mass Messages tab, and so does `?tab=scheduled`;
   - the header, the tab strip and the child tabs show the capture's labels in the capture's order;
   - the create button opens the Create message pop-up, whose Mass messages section holds "Priority mass message" `disabled` with `title="not wired"` (calling nothing on the relay), "OF mass message", which opens the mass composer (lazy module mocked), and "Message online fans" with "Inflowwww extra";
   - the Auto-unsend card, the scheduled list and Mass Nudge each carry "Inflowwww extra";
   - with a chatter-only session, Mass Nudge is absent and the rest of the tab renders;
   - the Auto-unsend card's Save is disabled with every class off, and clicking it sends nothing; with one class on, Save issues the existing `unsend_messages` rule create (`relay.post` to `/admin/automation-rules` with kind `unsend_messages`, name "Auto-unsend mass" and a `policy` holding exactly that class);
   - no `relay` call reaches an OnlyFans write.
2. **`ChatHeader.test.tsx`'s Kebab-menu case**: the href assertion becomes `/growth/smart-messages?tab=mass`.
3. **`service/tests/test_role_enforcement.py`**: the existing cases stay (every route is mapped, the page map follows the nav, still 37 pages, a Chatter lacking only a page gets a 403), and one case is added: under enforcement, a Chatter granted only Smart Messages gets 403 on `/admin/mass-nudge/preview`, and one granted Auto Post gets 200. That pins stories 15 and 16.
4. **Relay regression**, unchanged: `test_send_mass.py`, `test_mass_lifecycle.py`, `test_a12_unsend.py`, `test_unsend_mass_policy.py`. They are `case_` scripts with no `def test_` and run only as `./venv/bin/python service/tests/<file>.py`, so the suite's new `relay` step names each one. `test_unsend_mass_policy.py` needs `ALLOW_ANONYMOUS_ADMIN=1` (observed: exit 1 without it, 0 with it). They prove sending is unchanged; they do not test the move, which the seams above do.
5. **`app/lib/nav.test.ts`**, unchanged: My Automations stays exactly Auto Post + Auto Story. It must still pass, which proves no nav move happened.
6. **`app/app/messages-pro/extras.test.tsx`**, unchanged: Messages Pro opens the same composer (`components/chat/FanListHeader.tsx:172`), and the audit fails any `title^="Inflowwww extra"` element whose name is not in `EXTRAS`. The composer field's new label must keep it green: either it renders only outside Messages Pro, or its title uses a name the catalogue already has.

Prior art: `app/components/growth/autoFollowTargets.test.tsx`, which uses `vi.mock("@/lib/relay")` with every verb stubbed so that an unexpected call fails loudly. `app/components/chat/ChatHeader.test.tsx` covers the Not wired attributes. `service/tests/test_role_enforcement.py`'s shared-route case.

## Acceptance

```sh
cd <repo>
# The capture's placement section names the Mass Messages tab, Auto-unsend, and a bundle source.
P=$(sed -n '/^## Mass messages placement/,/^## /p' docs/infloww-layouts/growth-smart-messages.md)
echo "$P" | grep -qF "Mass Messages"
echo "$P" | grep -qiF "auto-unsend"
echo "$P" | grep -qE 'index\.9f50f370\.js @[0-9]+'
# The mass half is one module, rendered by the Smart Messages frame; My Automations is untouched.
test -f app/components/growth/MassMessagesSection.tsx
grep -qF "<MassMessagesSection" app/components/growth/SmartMessagesPage.tsx
grep -qF 'href="/growth/smart-messages?tab=mass"' app/components/chat/MessageStatsLink.tsx
# Relay unchanged since the Phase 0 baseline (committed or not).
B=$(sed -n 's/^Round 2 baseline at `\([0-9a-f]\{7,40\}\)`.*/\1/p' .scratch/infloww-parity-round-2/baseline.md | head -1); test -n "$B"
git diff --quiet "$B" -- service/automations/send_mass_message.py service/automations/mass_premade.py service/automations/mass_nudge.py service/automations/unsend_messages.py service/mass_broadcast_cache.py
# Tests (mocked OF only); the suite names the mass relay tests.
env ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run --testTimeout=20000 components/growth/MassMessagesSection.test.tsx components/chat/ChatHeader.test.tsx lib/nav.test.ts app/messages-pro/extras.test.tsx
./venv/bin/python service/tests/test_role_enforcement.py
for t in test_send_mass test_mass_lifecycle test_a12_unsend test_unsend_mass_policy; do
  grep -qF "$t" .scratch/infloww-parity-round-2/suite.sh || { echo "suite lacks $t"; exit 1; }
  env ALLOW_ANONYMOUS_ADMIN=1 ./venv/bin/python service/tests/$t.py || exit 1
done
sh .scratch/infloww-parity-round-2/suite.sh
# The recheck record carries this Phase's placement note, matrix row text and Labelled improvements lines.
R=$(sed -n '/^## Phase 2b /,/^## Phase /p' .scratch/infloww-parity-round-2/rechecks/growth-smart-messages.md)
echo "$R" | grep -qF "Mass Messages"
echo "$R" | grep -q '^### Matrix row'
for w in 'Auto-unsend' 'Message online fans' 'Mass Nudge'; do echo "$R" | grep -qF "$w" || { echo "recheck lacks $w"; exit 1; }; done
# manual: with the dev server on 127.0.0.1:3001, open /growth/smart-messages?tab=mass and recheck it against the bundle with REA (served on 127.0.0.1 only); record the result in the recheck record.
```

## Depends on

- **Phase 0.** It provides `docs/infloww-layouts/growth-smart-messages.md`: the header, the Mass Messages tab's labels, child tabs, columns and empty state, the Create message pop-up, and the placement record this Phase follows. It also provides the baseline sha (`.scratch/infloww-parity-round-2/baseline.md`) the relay-unchanged check diffs against, and the recheck record contract.

Phase 2's Smart Messages ticket depends on this Phase. This Phase does not depend on Phase 2.

## Out of Scope

- **A My Automations route, nav item, page-map entry or `docs/routes.md` row for mass messages.** The bundle places them on Smart Messages, and the owner's exception says to follow the bundle. Building both would leave two homes for one list. They are the fallback, used only on an owner veto.
- **Priority-inbox sending (Infloww's Priority mass message).** It would be a new sending path, which the plan forbids. It is Not wired.
- **Rewriting `MassMessagesTab` or `ScheduledTab` into Infloww's table columns, or filtering `ScheduledTab` to mass sends.** The plan says "Move, not rewrite". The differences are labelled instead.
- **Premade Mass, Mass funnels and Online Blast** (`mass_premade` and the other mass kinds of `ReadyMadePanel`, `app/components/automations/ReadyMadePanel.tsx:62-66`). The plan's move list names `MassMessagesTab`, `ScheduledTab`, `LazyMassMessageComposer` and `MassNudgeTab` only, and its Out of scope rules out new automation kinds. They stay on the flag-only `/automations` page. See the ASSUMPTION below; listed for the owner's veto.
- **The "Automated Messages" tab, the Trigger list, the Trigger filter and the Create message pop-up's Automated messages section.** These are Phase 2's, mounted in this Phase's slots.
- **Removing the mass content from Smart Messages.** Under this placement it stays. Phase 2's step 4 does not apply to it.
- **Changing how mass messages send or unsend, and new automation kinds.** These are out of scope by the plan. The Save guard changes what the UI lets an owner store, not how the Relay unsends.
- **Editing the Parity matrix.** Phase 6 alone edits it, from the recheck record (coordinator ruling, 2026-10-17).
- **Live sends or sandbox tests.** No live OnlyFans write, by floor 2 and the plan.

## Further Notes

- Placement follows the bundle (rung 1: `index.9f50f370.js` @14654355, @14707943, @14715019, @14716722, @15747892, @14979383/@15013397; rung 2: plan line 10's exception, "If REA shows Infloww puts them somewhere else, follow the bundle and record where it was found"). The owner may veto it; it is listed under plan-review's Needs the human as an FYI, not a blocker.
ASSUMPTION: Phase 0's `growth-smart-messages.md` records the same placement this spec observed. Overturned if that capture places mass messages elsewhere, or if the owner vetoes the bundle placement and wants My Automations regardless. In that case the fallback applies:
  - mount `MassMessagesSection` on a new route `/growth/auto-mass-messages`, labelled "Auto mass messages", in My Automations after Auto Story, with an "Inflowwww extra" label because the tab is ours, and move the Create message pop-up's Mass messages section with it;
  - update `nav.test.ts`'s two My Automations pins, the page map (a new "Auto mass messages" entry taking `/admin/mass-messages` and `/admin/mass-nudge`), `test_role_enforcement.py`'s page count (37 to 38) and any `SHARED_ONLY` change it observes, `docs/routes.md`, the two `next.config` redirects and `MessageStatsLink`'s href, all to point at the new route;
  - Smart Messages keeps its mass prefixes in the page map, so no saved role loses access (rung 4: routes shared by two pages pass when either is granted, `service/permissions.py:336`); denying the new page then hides it in the UI only, and the recheck record says so;
  - My Automations is hidden from chatter sessions (`app/lib/nav.ts:132`), so chatters who use mass messages on Smart Messages today would lose the UI. The owner decides that in the same veto.
- ASSUMPTION: the child tab our sent history sits under is "OF mass message". Rung 3: `send_mass_message` posts OF's `messages/queue` (`service/automations/send_mass_message.py:8`), which is what Infloww's "Sent to general inbox" card describes. Overturned if the capture shows a single mass list with no child tabs, in which case the panels sit directly in the Mass Messages tab.
- ASSUMPTION: this Phase owns the Smart Messages page frame (header, parent tab strip, Create message pop-up) and Phase 2 adds its tab and pop-up section into slots. Rung 1 for the order (Phase 2's Depends on and plan line 80 put this Phase first); rung 5 for the owner: the Phase that lands first builds the shared frame once, and the second adds to it without editing the other's module. Overturned if the coordinator merges both Smart Messages tickets into one change.
- ASSUMPTION: Mass Nudge renders for owner sessions only, and `/admin/mass-nudge` stays mapped under Auto Post alone. Rung 4: today no chatter can see Mass Nudge (it lives on the flag-only, chatter-hidden `/automations` page), so this keeps today's exposure; showing it to chatters would let one broadcast to every online Fan across Creators, and nothing on the Relay side gates it (`service/chatters.py`, `service/nudge_config_api.py`). Overturned if the owner wants chatters granted Smart Messages to use Mass Nudge; then the page map's Smart Messages entry gains `/admin/mass-nudge` and seam 3's 403 becomes a 200.
- ASSUMPTION: the hourly sweep's Save is disabled while no class is on. Rung 4: blocking a save is cheaper to undo than unsending DMs, and the Relay stays unchanged by the plan. Overturned if the owner wants an empty policy to mean the per-chat sweep, which then needs its own labelled control.
- ASSUMPTION: Premade Mass, Mass funnels and Online Blast stay on the flag-only `/automations` page and are not shown in the Mass Messages tab. Rung 5: the plan's move list names four modules only, and the plan rules out new automation kinds; showing three more is new surface the plan did not ask for. The cheap path if the owner vetoes is `<ReadyMadePanel only="mass_premade" />` (and the other kinds), the way `app/app/growth/auto-post/page.tsx` mounts it. Overturned by the owner.
- ASSUMPTION: until Phase 2 lands, the Mass Messages tab is the only parent tab on `/growth/smart-messages`. Rung 5: Phase 2 owns "Automated Messages". Overturned if the coordinator merges both Smart Messages tickets into one change.
- Glossary terms this spec uses that CONTEXT.md lacks are for the report, not for CONTEXT.md: "Mass Messages tab" (the bundle's parent tab), "Send type" (Priority mass message / OF mass message), "Auto-unsend sweep" (the per-Creator hourly `unsend_messages` rule, as distinct from per-message Auto delete), "Create message pop-up".

## Review

**weaker (devils-advocate, top-level, blind first call)**, 2026-10-17. The coordinator ran the devils-advocate persona from the top level: a structurally blind first call, then a draft call (`.scratch/infloww-parity-round-2/review/02b-devils-advocate.md`). The earlier attempt, kept for the record: codex exited 1 on its usage limit (reset Nov 11th, 2026), and the in-run fallback could not spawn an agent.

Blind call:
- B1 **partial.** The bundle branch is already this spec's default (Objective; offsets verified locally). Folding 2b into Phase 2's Smart Messages ticket is rejected: the plan orders them (plan line 80, rung 2), and the coordinator kept two owners with 2b first. Taken instead: one owner for the shared frame (D3).
- B2 **accept.** An empty policy runs the per-chat sweep (`MassMessagesTab.tsx:451-455`; `unsend_messages.py:629-630`, re-read). Rewritten: Problem Statement, story 27, Owns (`MassMessagesTab` second edit), Auto delete › Save guard, seam 1, ASSUMPTION.
- B3 **accept.** The sweep can never grade `matched`, and ADR-0014's negative search used the wrong words. The spec already labelled both Auto deletes as extras; the Auto delete decision now says why, and ADR-0014 is amended (its "no auto-delete string" line is corrected).
- B4 **partial.** "Auto" is the plan's word; this Phase means the plan's move list (manual broadcasts, the scheduled queue, Mass Nudge). Premade Mass, Mass funnels and Online Blast are Out of Scope with a reason and an ASSUMPTION naming the `only=` shortcut, and are listed for the owner's veto. Story 1 no longer says "automated".
- B5 **partial.** True: `MassNudgeTab` is mounted by `ReadyMadePanel.tsx:260` and by the unimported `MassNudgeComposer.tsx`, not by `SmartMessagesPage` (re-read). Interfaces now reads plan Work 2 as "mount these in the new section" and leaves the dead composer alone (deleting it is not this Phase's work).
- B6 **partial.** The exposure with the Legacy flag off is the plan's own instruction (plan line 89, rung 2), so Mass Nudge stays in the section for owners. Its chatter exposure is handled by D2, and its route is not remapped.
- B7 **accept.** Decided explicitly: under the bundle placement chatters keep the mass tab exactly as today's page gives it to them, and lose nothing; Mass Nudge is hidden from chatter-only sessions (D2). Pinned by seam 1's chatter case and seam 3. The fallback's chatter loss is written into the fallback bullet.
- B8 **partial.** Moot under the bundle placement, which adds no href. For the fallback, Smart Messages now keeps its mass prefixes (shared routes, `permissions.py:336`), so no saved role is orphaned, and denying the new page only hides it, which the recheck record states. No stored-role migration.
- B9 **accept.** `ScheduledTab` mixes direct and mass sends (`ScheduledTab.tsx:7-9`, re-read). Rewritten (Layout, story 8): it is its own labelled list with an honest heading, not filed under "OF mass message". Filtering is rejected as a rewrite that would leave direct scheduled sends with no home.
- B10 **partial.** `MessageStatsLink` and the `next.config` redirects were already covered. `docs/routes.md:23` stays true under this placement ("old settings Mass + Scheduled tabs" still describes the page's mass half), and the `nav.ts` comments still describe My Automations correctly, so neither is edited; the fallback edits `docs/routes.md`.
- B11 **accept.** The four mass tests are `case_` scripts outside any runner. Owns, seam 4 and Acceptance now add a `relay` step naming each, and the Acceptance checks the suite names them. The real seams for the move stay seam 1, 3 and 5.
- B12 **partial.** The falsifier was run in the earlier offset check: the bundle's tab-title map (`MessageSendTitle` @14654355) and the parent-tab switch (`changeSendType({parentTab:MessageSendType.Mass` @15747892) are the Tabs item list the finding asks for, so the tab branch holds. The only change is the corrected body offsets (D8).

Draft call:
- D1 **accept.** Same as B2 (coordinator ruling 8): the UI blocks Save with no class on, and seam 1 tests both the disabled Save and the one-class payload.
- D2 **accept.** Mass Nudge would newly reach chatters with no Relay gate. Rewritten: story 15, Owns, Interfaces (`isChatterOnly`), Contracts (no page-map edit; `/admin/mass-nudge` stays on Auto Post), Mass Nudge decision, ASSUMPTION (rung 4, today's exposure). The earlier page-map addition is withdrawn.
- D3 **accept.** Nobody built the single Create message pop-up, and both specs claimed `SmartMessagesPage`. Coordinator ruling 6, decided by the ladder: this Phase lands first (rung 1), so it owns the frame, the parent tab strip and the pop-up, and Phase 2 fills two slots (rung 5). Rewritten: Objective, Solution, story 20, Owns, Interfaces, seam 1, Out of Scope, ASSUMPTION; Phase 2 agrees.
- D4 **accept.** The relay-unchanged check now diffs against the Phase 0 baseline sha (from `baseline.md`), working tree included. The placement greps are scoped to `## Mass messages placement`. The `MassMessagesSection` grep now needs the JSX element (`<MassMessagesSection`); the composer grep is dropped, because seam 1 and the extras audit gate the label. The recheck record's placement, matrix row and Labelled improvements lines are now checked. The page-map check went with D2.
- D5 **accept.** Seam 3 gains one case: a Chatter granted only Smart Messages gets 403 on `/admin/mass-nudge/preview`, one granted Auto Post gets 200.
- D6 **accept.** Same as B9.
- D7 **accept.** Mass funnels and Online Blast now have an Out of Scope line with Premade Mass, and story 1 no longer promises "automated mass messages" (B4).
- D8 **accept.** The Solution and Further Notes carried the uncorrected offsets. Every offset in the body is now the first byte of its token, re-measured with a read-only `python3 -I` byte search on 2026-10-17; Phase 2's copy is corrected too.
- D9 **partial.** The fallback is now fully specified for roles (Smart Messages keeps its prefixes, B8). Its chatter loss is a product question the plan is silent on, so it is put to the owner inside the placement veto rather than decided here.

Six hats (2026-10-17, `.scratch/infloww-parity-round-2/review/six-hats.md`):
- SH2 **accept.** 2b had no adversary review; the top-level devils-advocate ran, and this Review is relabelled.
- SH3 **accept.** The offsets were off by up to 600 bytes in the body; corrected (D8). ADR-0014's title is amended. CONTEXT.md's "Inflowwww extra" widening is already parked in `.scratch/infloww-parity-round-2/glossary-pending.md`.
- SH5 **reject.** Rung 2: the plan's own exception is a written instruction to follow the bundle, and the bundle puts Mass Messages as a Smart Messages tab (verified above). The owner's rejected option in ADR-0014 was today's page, where the mass list hides the trigger half; under the bundle layout Automated Messages is its own tab and the trigger list never shows a mass message. The placement and its evidence go to the owner as a veto FYI (plan-review, Needs the human).
- SH8 **partial.** Premade Mass, Mass funnels and Online Blast are now Out of Scope with a reason and an owner veto (coordinator ruling 7). Phase 2's N2 stays needs-human there.
- SH9 **accept.** The recheck record has one place (`.scratch/infloww-parity-round-2/rechecks/growth-smart-messages.md`), and this Phase no longer edits the page map.
- SH13 **accept.** No matrix edit in this Phase; the row text and Labelled improvements lines go to the recheck record, and Phase 6 alone edits the matrix (coordinator ruling 2).
- SH14 **partial.** Folding is rejected (B1); Premade Mass goes to the owner (SH8).

**Bundle offsets, verified locally** (read-only, `python3 -I` byte search of `~/Downloads/infloww-remote-web/index.9f50f370.js`, 16,931,320 bytes). Every string the spec cites is present. Re-measured 2026-10-17 to the first byte of each token, and those offsets are now in the body:
- `var MessageSendTitle=…{AutoMessage:"Automated Messages"},Mass:"Mass Messages"` @14654355 (strings @14654443, @14654486). Confirms the two parent tabs, in that order.
- `var massMsgList=[{title:"Priority mass message",desc:"Sent to priority inbox",…},{title:"OF mass message",desc:"Sent to general inbox",…}]` @14707943. `var automatedMsgList=[{title:"Nudge",desc:"Messages fans when they come online",…` @14708609. Confirms the spec's Nudge mapping.
- The modal `xTitle:"Create message"` @14716722 renders `massMsgList`, filtered by `createPriorityMassMessage`/`createOfMassMessage` (`massMsgList.filter` @14715019). The section exists; the modal's bundle title is "Create message", not "New message".
- `changeSendType({parentTab:MessageSendType.Mass,childrenTab:Tr})` @15747892, with `OfStatus`/`PriorityStatus` filter lists chosen per child. Confirms the per-send-type child tabs. Their rendered order is Phase 0's capture.
- `function Unsend$1` @14979383, `xTitle:"Auto unsend settings"` (string @14981410), "Unsend messages" @14981830. Mounted as `hasAutoUnSend(Lt.sendType)&&jsx(Unsend$1,{})` @15013397, inside the editor.
- `function hasAutoUnSend(S){return S!==MessageSendType.OF}` @14776278, and the OF switch modal's "will not support: … Auto-unsend" @14793004.
- `queryOfMassMessageList` @14591116 (first of 6). The earlier `OfMassMessage list @16215466` citation was a list-row handler block and is no longer cited.
- Conclusion: the central move holds on rung 1. The bundle puts mass messages under Smart Messages > "Mass Messages", not under My Automations, so the owner's "follow the bundle" exception applies.

**Self-check findings** (by the spec reviewer, rung 1; not an independent review; rewritten above because each is a factual error):
- accept — The per-broadcast Auto-unsend was called a match for Infloww. It is not: Infloww has no Auto-unsend on an OF mass message (@14776278, @14793004), and the spec itself files our sends under "OF mass message". Rewritten: Solution bullet, story 11, Owns (`compose/MassMessageComposer` gets the label), and Auto delete bullet 1, which now labels the field "Inflowwww extra".
- accept — The new label could break the Messages Pro extras audit. `FanListHeader.tsx:172` opens the same composer, and `app/app/messages-pro/extras.test.tsx:601` fails any uncatalogued `Inflowwww extra` title. Rewritten: Testing seam 6, and the test was added to the Acceptance vitest run.
- accept — Story 19 would fail after Phase 2. `next.config.ts:87-88` redirects `/settings?tab=scheduled` to `/growth/smart-messages` with the query passed through, and `useTabParam` ignores unknown values (`app/hooks/useTabParam.ts`), so the link would open Phase 2's default tab, the Trigger list. Rewritten: story 19, Interfaces (`scheduled` becomes an alias of `mass`), the Contracts redirect bullet, and Testing seam 1.
- reject (no change) — I checked whether the growth extras should register in `EXTRAS`. No: that catalogue is Messages Pro's (`app/lib/openinflowwwwExtras.ts:1-13`), and growth pages use `EXTRA_LABEL` directly, as `growth/AutoFollowTab` does.
- Repo claims checked and true: `MessageStatsLink.tsx:24` href; `useMassNudge.ts:48,59` routes; `/admin/mass-nudge` on Auto Post only (`service/permissions.py:235`); `test_role_enforcement.py:392` asserts 37 pages; the four relay tests exist; `SmartMessagesPage.tsx:22-27` has the "Mass messages"/"Scheduled" strip and no `useTabParam` today.

needs-human: none blocking. The placement is an FYI for the owner's veto (plan-review), together with the fallback's chatter question (D9) and Premade Mass / Mass funnels / Online Blast (B4).
