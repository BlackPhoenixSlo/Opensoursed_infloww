# Inflowwww

Inflowwww is an open-source rebuild of Infloww, the tool OnlyFans agencies use to run their creators' chats. A full entry holds a meaning or naming rule found nowhere else. A bullet names a term, any clash to avoid, and the file that defines it.

## Language

### People and tenancy

**Creator**:
An OnlyFans or Fansly account the agency runs and chats as.
_Avoid_: model, account, page (code keeps `accountId` as the identifier)

**Fan**:
A person subscribed to or following a Creator, on the other side of a conversation.
_Avoid_: subscriber, user, customer

**Employee**:
A person who signs in to work Creators' chats. Owner, admin, manager and chatter are roles an Employee holds.
_Avoid_: chatter (a role, not the person), operator, agent

**Agency**:
The business that signs in as one `users` row and owns its Creators, Employees and Settings blobs. Infloww's labels say "organization".
_Avoid_: organization (Infloww's UI label only), user, tenant, owner, account

**Agency isolation**:
The rule that a request reads and writes only its own Agency's Creators and agency-scoped rows; Discovery is the one exception (ADR-0011).
_Avoid_: account isolation (the middleware's name, which covers Creators only; the Parity matrix's "account isolation gate"), tenancy, multi-tenancy

**Master**:
The Deployment-wide role (`users.is_admin`, set by whoever runs the app) that sees every Agency.
_Avoid_: admin (an Employee role), superuser, super admin

**Owner session**:
A request signed in as an Agency's own `users` row. It acts as the Agency, never as an Employee.
_Avoid_: owner employee, admin session, agency login

**Chatter session**:
A request signed in as a chatter linked to one or more Agencies. In each Agency it acts as that Agency's Mirror Employee.
_Avoid_: employee session, employee login, staff login

**Mirror Employee**:
The Employee row that stands for one chatter inside one Agency, created on first use.
_Avoid_: shadow employee, chatter employee, linked employee

**Agency context**:
Which Agency, which Employee, owner or Master a request is, derived from the session alone and never from a header or body field.
_Avoid_: tenant context, request scope, X-Employee-Id (the client-picked header it replaces for new endpoints)

- **Deployment** (avoid: instance, tenant, server): ADR-0011

### Messages Pro layout

**Messages Pro**:
The multi-Creator chat workspace: the Window header and the Fan tabs strip above three panes, Fan List, Thread and Fan insights.
_Avoid_: inbox, chat page

**Window header**:
Messages Pro's own top row, holding Home, All Models and the Creator tabs (`app/components/chat/WindowHeader.tsx:3-19`). Online Fans and Notifications are Fan List buttons, not Window header buttons. The look-and-feel plan's "Creator tabs row" is this row, and its "language, pop-out already live there" is stale: those are unowned Compare rows, never built.
_Avoid_: top bar (that is the app shell's), top strip, window chrome, Creator tabs row

**Top bar**:
The app shell's row above every screen (`app/components/shell/TopBar.tsx`). Messages Pro hides it at desktop width.
_Avoid_: app header, Window header, top strip

**Fan List**:
The left pane: one Creator's conversations.
_Avoid_: chat list, inbox, conversation list

**Thread**:
The center pane for one Fan: Chat header, message list and Composer.
_Avoid_: chat surface, conversation view, center pane

**Fan insights**:
The right pane: Insights blocks about the selected Fan.
_Avoid_: insights panel, fan drawer, insights rail, right panel

- **Creator tab**: `app/components/chat/CreatorTabs.tsx`
- **Fan tab**: `app/components/chat/FanTabs.tsx`
- **Insights block** (avoid: section, card): `app/components/chat/FanDrawer.tsx`
- **Deep link** ("Copy chat link" produces one): `app/app/messages-pro/[accountId]/[fanId]/page.tsx`
- **Pop-out window** (Infloww's Multi-Window): ADR-0002
- **Messages Basic** (Infloww's single-Creator screen): `docs/infloww-screens.md`
- **Region** (avoid: section, zone): `docs/messages-pro-parity.md`

### Fan List

**Pinned chat**:
A chat the Creator has pinned on OnlyFans. The Pinned filter and the Chat header's pin icon both act on it.
_Avoid_: pinned tab, Fan tab, Pinned message

**Pinned message**:
A single message pinned inside a Thread.
_Avoid_: pinned chat

**OF list**:
A named list of Fans that a Creator keeps on OnlyFans.
_Avoid_: fan list (collides with Fan List), smart list (Infloww's Growth feature)

- **Focus mode** (not the Chat header's "Focus mode" row, which is the Phone focus extra): `app/components/chat/useFocusMode.ts`
- **Fan List filter**: `app/components/chat/FanListFilters.tsx`
- **Chat folder** (an OF list pinned as a filter chip): `app/components/chat/FanListFilters.tsx`
- **Row badge**: `app/components/chat/fanRowBadges.ts`
- **Total spend** (avoid: LTV, revenue): `app/components/chat/totalSpend.ts`
- **Edge marker** (the unread or owe dot; not a Row badge): `app/components/chat/FanRow.tsx`
- **Fan List header**: `app/components/chat/FanListHeader.tsx`
- **Fan List buttons** (Online Fans, Notifications; not Window header buttons): `app/components/chat/FanListButtons.tsx`
- **Notifications panel** (ours; Infloww has none): `app/components/chat/FanListButtons.tsx`
- **Notifications badge** (Infloww's plain unread count): `docs/messages-pro-parity.md`
- **Notifications toggle** (retired; the Buys & tips switch took its place): `docs/screenshots/messages-pro-compare.md`, row FL11
- **Split Inbox**, **Split Inbox group** (avoid: lanes): ADR-0004

### Thread

**Composer**:
The Thread's writing area under the message list, including its reply strip and its PPV row.
_Avoid_: input bar, message box

**Composer row**:
One of the Composer's three stacked rows, numbered from the top (`app/components/chat/ComposerToolbar.tsx:8-18`). Plans that call the PPV row "row 4" are counting rows: it renders between rows 2 and 3.
_Avoid_: toolbar, bar, line

**PPV**:
A pay-per-view message: media locked behind a price that the Fan pays to unlock.
_Avoid_: paid message, locked message

**PPV row**:
The Composer row for the next send's price and media (`app/components/chat/PpvRow.tsx`). Only a price above 0 makes the send a PPV; price 0 sends the media free.
_Avoid_: price composer, extras row
ASSUMPTION: it sits between rows 2 and 3, keeping Send still (`docs/spec/messages-pro-look-and-feel/phase-05-composer.md:168`); overturned if the human wants it under row 3.

**Timed message**:
A send from the Composer held for 1 to 60 minutes, then sent.
_Avoid_: delayed message, scheduled message

**Scheduled message**:
A chat send queued for a chosen date and time.
_Avoid_: timed message, queued send, Scheduled post (that is an OnlyFans post)

**AI Copilot**:
Infloww's reply-suggestion assistant behind the Composer's "AI" button. It never sends anything itself.
_Avoid_: Auto-reply (Inflowwww's automation that does send), AI chatter (the retired selling engine)

- **Chat header** (avoid: thread header): `app/components/chat/ChatHeader.tsx:62-77`
- **Kebab menu** (avoid: More, Infloww's Composer menu): `app/components/chat/ChatActionsMenu.tsx`
- **Avatar menu**: `app/components/chat/AvatarMenu.tsx`
- **Bubble action row**: `app/components/chat/BubbleActions.tsx:4-13`
- **Date divider**: `app/components/chat/MessageList.tsx`
- **Jump chip** (the "Jumping to latest…" chip): `docs/screenshots/messages-pro-compare.md`
- **PPV mode**: `app/components/chat/Composer.tsx`
- **Free previews** (the look-and-feel plan's "free-preview divider" and "notice"): `app/components/chat/PpvRow.tsx`
- **Script** (avoid: template, although `TemplatePicker.tsx` is its picker): `app/components/chat/Composer.tsx`
- **Timed reminder** (sends nothing): `app/components/chat/TimedMessagePopover.tsx`
- **Vault picker** (Infloww's "Vault Pro window", not the Vault Pro screen): `app/components/chat/vaultPickerSheet.ts`
- **Fan notes**, **Creator notes**: `app/components/chat/FanDrawer.tsx`
- **SFW mode**: `docs/infloww-screens.md`

### Inflowwww extras

**Inflowwww extra**:
A Messages Pro control listed in `app/lib/openinflowwwwExtras.ts`, which gives its hosts. Infloww lacks it, and it never displaces an Infloww element (ADR-0003).
_Avoid_: addon, custom feature, legacy feature

**Extras overflow**:
The menu, named "Inflowwww extras", in which a Region holds its extras that are not automations. The Chat header's opens from the Kebab menu; the Window header has none, and since 2026-10-26 neither has the Fan List (ADR-0003).
_Avoid_: "+" menu (the Creator tabs strip's "+" adds a Creator), More, Kebab menu

- **All Models**, **Group chat** (Threads side by side, not a multi-Fan conversation), **Owe reply** (client-side; OnlyFans has no such filter), **Persona button**, **Scheduled chip**: `app/lib/openinflowwwwExtras.ts`

### Client mass messages


### OF Manager mirror

**OF mirror**:
The scrubbed static copy of the OnlyFans creator UI that `scripts/of-mirror.mjs` generates and the app shows in a same-origin frame, standing in for Infloww's OF Manager.
_Avoid_: Clone (that is the copy of Infloww's screens), OF clone, parody

**Relay**:
Inflowwww's backend (`service/server.py`) that holds each Creator's OnlyFans session and serves OnlyFans data and writes under `/api/of/v2/`.
_Avoid_: backend, proxy, API server

**Single-Creator scope**:
The OF Manager with one Creator selected. Only here do Wired controls send and Data parts show real rows.
_Avoid_: single model, single-model scope

**All-Creators scope**:
The OF Manager with all Creators selected. Nothing is sent and every Mirror page keeps its Example rows.
_Avoid_: all-models scope, All Models (that is the Messages Pro extra)
ASSUMPTION: named from **Creator** rather than the code's "all models"; overturned if the human prefers the code's word.

**Read-only note**:
"Read-only in Inflowwww for now", shown by a Mirror page control with no Known body. The control stays enabled and keeps OnlyFans's look.
_Avoid_: Not wired (the disabled control state), stub, coming soon

- **OF Manager**: `docs/routes.md`
- **Mirror page**, **State page**, **Mirror check**: ADR-0006
- **Wired control** (avoid: connector): ADR-0006; `scripts/of-mirror-check/README.md`
- **Known body** (avoid: guessed body): ADR-0005
- **Example rows**, **Silent control**: `scripts/of-mirror-check/README.md`
- **Data part**: ADR-0006; `scripts/of-mirror-check/README.md`
- **Select-model note**: `docs/spec/of-manager-connectors/phase-06-no-silent-control.md`
- **Post draft**: ADR-0006
- **Co-tag** (another OnlyFans creator, not a **Creator**): ADR-0005
- **Scheduled post**, **Queue**: `docs/spec/of-manager-connectors/phase-04-real-data-pages.md`
- **Story**: `app/lib/ofMirrorPost.ts`

### Settings layout

- **Settings tab**, **Settings header**, **Tab area**, **Tab list**, **Panel**, **Panel header**, **Panel section** (avoid: section on its own): `docs/spec/settings-tabs/phase-00-shell-tokens-blob.md`

### Settings storage

**Applied**:
The state of a Settings blob field that a Relay route or screen reads and acts on, decided field by field.
_Avoid_: enforced (only Permission roles are enforced), live, active, wired (that is Not wired's opposite)

**Not applied yet**:
The state of a value saved in a Settings blob that nothing in Inflowwww reads; its Panel says so. Which fields are still in this state: ADR-0008's status line and ADR-0012. The AI Translator prompt is stored but never read and no tier is planned to read it (ticket 28 closed, the LLM tier vetoed), so its card says "Saved for your organization, but not used" rather than "not applied yet".
_Avoid_: pending, draft, enforced, Not wired (a Not wired control saves nothing)

**Not wired**:
A control state anywhere in Inflowwww: an Infloww control we show but cannot perform, because the Relay has no endpoint for it. It is disabled with the tooltip "not wired" and never fakes success.
_Avoid_: stub, coming soon, NotBuiltYet (a whole unbuilt page), Read-only note (the OF mirror's enabled counterpart)

- **Settings blob** (avoid: config, settings row): ADR-0007
- **Blob tab**: `app/lib/settingsBlob.ts`
- **Load gate** (Save waits for the blob's load, so a failed load never overwrites it): `app/components/settings/SettingsPanel.tsx`

### Settings content

**Permission role**:
A named set of per-page permissions plus a Data scope that an Agency defines in Role Settings and assigns to Employees, Applied only under Role enforcement (ADR-0012).
_Avoid_: role on its own (the **Employee** entry's owner, admin, manager and chatter are the access the app enforces today), group, position
ASSUMPTION: Permission roles are kept apart from the roles in the **Employee** entry because they are enforced only under the opt-in Role enforcement and never replace that access (ADR-0012); overturned if the human wants Role Settings to become the app's one role system.

**Data scope**:
A Permission role's reach over data: "All data", "Self and subordinates" or "Data about self".
_Avoid_: scope on its own (that is Single-Creator or All-Creators scope), visibility

**Sales attribution**:
The rule, chosen per revenue kind in Sales Settings, that decides which Employee a sale is credited to.
_Avoid_: attribution lanes (`/admin/lanes` is concurrency), credit, commission

- **Role enforcement** (avoid: RBAC): ADR-0012
- **AI translation** (not the `/admin/translate` route, which is Google's free keyless gtx endpoint; its prompt is stored but not used): `docs/spec/phase-04-apply-stored-settings.md`
- **Referral balance** (per Creator, not per Agency): `docs/spec/settings-tabs/phase-05-billing-balance-about.md`

### Shifts and time tracking

**Shift**:
A planned work interval in one Agency, assigned to Employees and Creators, with its own timezone and an optional weekly repeat.
_Avoid_: session, slot (that is S4S), schedule entry, roster

- **Shift occurrence** (computed, not stored), **Shift schedule** (not bare "schedule"; S4S has one too), **Clock event** (not "session"), **Auto clock-out**, **Owner edit**, **Timesheet**, **Recorded earnings** (never a payroll figure): `docs/spec/phase-02-shifts-time-tracking.md`

### Share for Share

- **Share for Share** (S4S; not Infloww's app.infloww.com community), **S4S profile**, **S4S post**, **S4S request**, **S4S slot** (not a Shift), **Daily limit**: `docs/spec/phase-03-share-for-share.md`
- **Discovery**, **S4S projection**: ADR-0011

### Parity evidence

**Infloww capture**:
A real Infloww desktop screenshot under `~/Downloads/infloww-shots-2026-10-12/`, the first-ranked ground truth for look and feel. It holds real handles, so it is read, never committed and never quoted.
_Avoid_: reference shot, screenshot (ours come from `scripts/ui-shots.sh`), Clone

**Clone**:
The static copy of Infloww's screens that lived in `ui-redesign/infloww-exact/` and was served at `/infloww`. Deleted in 2026-10 (tag `legacy-ui-final` still has it); older docs and comments still cite it as the earlier Geometry reference. Infloww captures, the Infloww stylesheet and the Dashboard bundle are the references now.
_Avoid_: mockup, skin, the Infloww UI

**Infloww stylesheet**:
The CSS extracted from Infloww's desktop app (`docs/plans/messages-pro-look-and-feel.md`). Untrusted input: read, never run, it gives up only measured values.
_Avoid_: Dashboard bundle (that is Settings' source), asar, Infloww CSS

**Dashboard bundle**:
The public Infloww 5.7.20 dashboard JS and CSS, the pixel source for Settings (`docs/spec/settings-tabs/phase-00-shell-tokens-blob.md`). Untrusted input: read, never run, it gives up only measured values.
_Avoid_: Clone, Infloww source, CDN bundle

**Parity matrix**:
`docs/infloww-parity-matrix.md`, one row per Inventory section, graded by Matrix status.
_Avoid_: Parity table (Messages Pro's), route map (that is `docs/routes.md`), route matrix

- **Geometry** (colour is not part of it): ADR-0001
- **Infloww palette**, **App accent**: ADR-0010
- **Infloww token** (`--if-*`, Settings only): ADR-0009
- **Compare page**, **Compare row**, **Colour inventory**: `docs/screenshots/messages-pro-compare.md`
- **Parity table** (avoid: Parity matrix): `docs/messages-pro-parity.md`
- **Gap table**: `docs/spec/phase-06-geometry-pass.md`; `app/lib/messagesPro.ts`
- **Visual loop**: `docs/plans/messages-pro-parity.md`
- **Inventory** (the July 2026 gap analysis is evidence to re-check, not part of it): `docs/infloww-screens.md`
- **Inventory version**: `docs/infloww-parity-matrix.md`
- **Matrix status** (avoid: ours-only, the Parity table's grade): `docs/infloww-parity-matrix.md`. ASSUMPTION: Leaderboard and Referrals are graded intentionally different; overturned if the owner grades them blocked.
- **Settings walk**: `docs/spec/settings-tabs/phase-00-shell-tokens-blob.md`
- **Write list**: `scripts/settings-check/walk.py`
- **Effort suite**: `docs/plans/infloww-parity-next-steps.md`
- **Merged tree**: `docs/spec/phase-00-merge-stale-docs-route-matrix.md`
