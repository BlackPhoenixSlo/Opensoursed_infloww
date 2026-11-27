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
Messages Pro's own top row, holding Home, All Models and the Creator tabs, and at its right end the "Notif" (Buys & tips rail) switch, then SFW last (`app/components/chat/WindowHeader.tsx`). The look-and-feel plan's "Creator tabs row" is this row, and its "language, pop-out already live there" is stale: those are unowned Compare rows, never built.
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

- **Fan List filter**: `app/components/chat/FanListFilters.tsx`
- **Chat folder** (an OF list pinned as a filter chip): `app/components/chat/FanListFilters.tsx`
- **Row badge**: `app/components/chat/fanRowBadges.ts`
- **Total spend** (avoid: LTV, revenue): `app/components/chat/totalSpend.ts`
- **Edge marker** (the unread or owe dot; not a Row badge): `app/components/chat/FanRow.tsx`
- **Fan List header**: `app/components/chat/FanListHeader.tsx`
- **Fan List buttons** (Online Fans, Notifications; not Window header buttons): `app/components/chat/FanListButtons.tsx`
- **Notifications panel** (ours; Infloww has none): `app/components/chat/FanListButtons.tsx`
- **Notifications badge** (Infloww's plain unread count): `docs/messages-pro-parity.md`
- **Split Inbox**, **Split Inbox group** (avoid: lanes): ADR-0004, bound per chatter by ADR-0052

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
The OF Manager with all Creators selected. Mirror pages keep their Example rows; a write follows its page's already-wired writes, so it goes to the stand-in first Creator where the page already writes that way (`STAND_IN_SRC`) and otherwise shows the Select-model note, while a Lockout, undo-less or Critical control always waits for a Creator pick.
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

### OF Manager not-yet controls

**Not-yet title**:
"Not available in Inflowwww yet", the tooltip on a Mirror page control that the generator disables (`NOT_YET_TITLE`, `scripts/of-mirror.mjs:1058`). Unlike a control with the Read-only note, it does not answer a click.
_Avoid_: Not wired (Messages Pro's disabled state), Read-only note (the enabled counterpart), coming soon

**Not-yet control**:
A Mirror page control that shows the Not-yet title or the Read-only note; the OF Manager not-yet effort (`docs/plans/ofm-not-yet.md`) turns each one into a Wired control. A control under an Empty-form disable is not one.
_Avoid_: dead control, gap, stub, Silent control (one that answers nothing, which the Mirror check already forbids)

**Empty-form disable**:
OnlyFans's own disabling of a control while its form is empty (the Not-yet sweep's `dis`); left as OnlyFans has it.
_Avoid_: disabled on its own, Not-yet title

**Unproven control**:
A Wired control that only mocked Mirror checks have shown working, never a Live proof: Co-tagged post, upload dedupe, vault thumbnails via `/img`, Tips feed, stories and highlights shapes, Statements invoice, state and reason, Queue Publish now and Send now, Vault custom order save.
_Avoid_: untested control, built-but-untested, parked connector (the older tickets 06 and 19 are two of them)

- **Not-yet sweep** (the 2026-11-20 headless sweep of 154 Mirror pages in Single-Creator scope, `ny` and `dis` per page; Release forms were not in it): `docs/of-manager/not-yet-sweep-2026-11-20.json`

**Request capture**:
OnlyFans's real request (method, path, body) for one control, recorded from the Proof Creator's signed-in session with REA or a browser capture. It is how a control's body becomes a Known body (ADR-0005).
_Avoid_: capture on its own (an Infloww capture, or the Mirror page HTML captures of ADR-0006), HAR, sniff, guessed body
ASSUMPTION: ADR-0005's "this effort adds no OnlyFans endpoint … and no Relay route" bound the connectors effort only, while its rule (a write only with a confirmed body) binds this one, a Request capture being that confirmation (rung 3); overturned if the human reads ADR-0005 as forbidding new Relay routes for good.

### OF Manager live proof

**Proof Creator**:
The owner's own OnlyFans Creator founder (80000112, session in `service/sessions/accounts/80000112`), with 59 real subscribing Fans, on which every Live proof runs.
_Avoid_: test account (the **Creator** entry rules out "account"), test model, Test chat (Full AI Chat's), founder on its own
ASSUMPTION: "Proof Creator" over the brief's "Test account", because **Creator** avoids "account" and Full AI Chat already owns "test" (Test chat, test Mode) (rung 3); overturned if the specs must say "Test account".

**Proof fan**:
The one Fan the owner names for message and PPV Live proofs, reached alone through `included_users`; a run never picks one itself.
_Avoid_: test fan, test user, dummy fan

**Live proof**:
A Not-yet control or Unproven control driven on the running app in Single-Creator scope against the Proof Creator: a screenshot of the trigger, one of the settled end state, and the result confirmed on OnlyFans's side. Each live write it makes is a Narrowed write and enters the Undo log (ADR-0042).
_Avoid_: live test, smoke test, e2e, Mirror check (mocked, ADR-0006)

**Narrowed write**:
A Live proof write whose reach is cut down before it is sent: to an OF list, to the Proof fan, or as a Scheduled post deleted before it fires; a post to all Fans only if deleted at once, and never a mass message (ADR-0042).
_Avoid_: test send, safe send, dry run

**Undo log**:
The PR's record of every live write a Live proof made on the Proof Creator, each with the write that reversed it (delete the post, list or link; unblock; restore the setting) and that reversal's confirmation (ADR-0042).
_Avoid_: audit log, change log, rollback log, cleanup list

**Lockout control**:
A control whose live write can end Inflowwww's own session on the Proof Creator: Close all sessions, block by country, block by IP. Block by country or IP is Live-proven last with a harmless value, then reverted (ADR-0042); Close all sessions cannot be reverted, so it gets a Mocked proof and runs live only on the owner's named go (ADR-0043).
_Avoid_: dangerous control, Critical control (never written live)

**Critical control**:
A control that moves money, files payout or tax data, writes to OnlyFans support, or changes the Proof Creator's sign-in or existence: Bank's payments, cards, payout types, DAC7 and support, the Statements support form, and OF settings account's password, username, email, phone, 2FA passwordless and delete. It is wired behind the owner's off-by-default Critical switch, and its only proof is a Mocked proof (ADR-0043).
_Avoid_: dangerous control, sensitive control, money control, Lockout control (block by country or IP: proven live, then reverted)

**Mocked proof**:
The proof of a control in ADR-0043's mocked-proof class (every Critical control, and the writes with no undo such as Report, Close all sessions or Send tip): its binder sends its Request capture's shape to a mocked Relay, and nothing reaches OnlyFans. It never drops the Not-yet title by itself.
_Avoid_: dry run, Shadow mode (Full AI Chat's), fake proof, Live proof

**OAuth hand-off**:
A sign-in or connect control (Google, X, Spotify in OF settings and My profile, MetaMask and NFT) that opens OnlyFans's own page for the operator rather than linking anything inside Inflowwww; a Live proof makes no live link.
_Avoid_: redirect, connect flow, Deep link (Messages Pro's chat link)

### Fansly Manager mirror

**Fansly Manager**:
The app's Fansly creator area under `/fansly-manager/`, holding Fansly mirror pages and the four Built pages, each nav child behind the `fansly_manager` flag.
_Avoid_: Fansly OF Manager, Fansly dashboard, Creator Dashboard (Fansly's own section of that name)

**Fansly mirror**:
The scrubbed static copy of the Fansly creator web UI that `scripts/fansly-mirror.mjs` generates into `app/public/fansly-mirror/` and the Fansly Manager shows in a same-origin frame; the OF mirror's sibling with its own generator (ADR-0066). Mirror page and State page (ADR-0006) mean the same for it.
_Avoid_: Fansly clone, Fansly copy, Fansly Manager (the whole area, Built pages included), OF mirror (OnlyFans's)

**Built page**:
One of the four hand-built Fansly Manager pages (Scheduled, Lists, Notifications, Earning Statistics) that read and write real Relay data; it keeps its exact URL and nav slot over the Fansly mirror's copy of that landing until the copy has its rows and writes.
_Avoid_: legacy page, native page, old page, React page

**Mirror capture**:
One read-only run through every planned Fansly page and State in the owner's signed-in creator Chrome, saving each whole rendered document, its meta and a screenshot outside the repo, with the Capture gate armed throughout. It is the only input the Fansly generator reads.
_Avoid_: Capture session (records requests for a Platform recipe), Request capture (one OnlyFans control's), capture on its own, scrape, crawl

**Capture manifest**:
A Mirror capture's `manifest.json`: every route and State it saved, with opener, settled selector and bundle hash, plus the session's own creator and fan identities. The generator publishes only when every entry produced a page.
_Avoid_: index, inventory, sitemap

**On-open write**:
A write Fansly sends only because a page or State was opened, with no click on Save: message ack, notifications ack, presence status, impression log, story view.
_Avoid_: auto-write, background write, side request

**Capture gate**:
The browser-wide process (`fansly/capture/gate.py`) that, during a Mirror capture, lets only GET, HEAD and OPTIONS reach any host, answers each known On-open write locally, and fails any other request and halts the run (ADR-0065).
_Avoid_: proxy, firewall, egress filter, recorder (`record.py`, which drops redirected POSTs)

**Gate audit**:
The check after a Mirror capture that passes only with no non-GET continued in the Capture gate's log, no outbound socket frame after arming, and every Fansly group's unread count unchanged; a failed audit feeds nothing to the generator.
_Avoid_: unread total check (`/message/unread.total` lies), smoke test

**Leak guard**:
A mirror generator's fail-hard check, re-run by `--check`, that no Mirror page carries live data: no email, IP, long digit run, real host, identity or money, and every URL sink resolving to `#`, the Manager's own path or a mirrored static asset. The Fansly mirror's must also fail on a planted-leak fixture.
_Avoid_: scrubber (removes leaks; the guard proves none are left), lint, Mirror check (renders pages in a browser)

**Identity swap**:
The frame's runtime replacement of the generator's identity placeholders (`yourmodel`, `Your Model`, `data-oi-avatar`, `data-oi-banner`) with the selected Creator's name, handle, avatar and banner from the Relay's `/users/me`.
_Avoid_: personalisation, templating, re-skin

**Stand-in Creator**:
The Creator whose identity a Mirror page shows in All-Creators scope. The OF mirror's is the first Creator with a live session, else the first Creator (`standInPick`); the Fansly mirror's is the first live Fansly Creator only, never a Watcher, and its pages then show the stand-in hint.
_Avoid_: default model, fallback Creator, first model
ASSUMPTION: coined from the All-Creators scope entry's "stand-in first Creator" (rung 3); overturned if the owner wants the code's "stand-in model".

**Never-public path**:
A path that `NEVER_PATHS` in `.claude/skills/public-sync/leak-check.sh` matches under the public and strip profiles: replay skips it as "never public" and the whole-tree gate rejects a tree holding it. `app/public/client-brand/` and `app/public/fansly-mirror` are two; `app/public/of-mirror` is not, despite its NOTICE (ADR-0067).
_Avoid_: private path, excluded path, filtered path, OPS path (one source list inside it)

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
- **AI translation** (not the `/admin/translate` route, which is Google's free keyless gtx endpoint): `docs/spec/phase-04-apply-stored-settings.md`
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

### Fetch diet

**OF call**:
One request the Relay makes to OnlyFans through `of_client.request_json`, answered or not.
_Avoid_: fetch, hit, request on its own (the app's own routes are requests too)

**Caller kind**:
What issued an OF call: a walk kind, a Relay route or an automation kind.
_Avoid_: source, origin, caller on its own

**OF call counter**:
The Relay's in-memory count of OF calls by Caller kind, normalised path, Creator and status class, flushed with a boot count to a JSON file in `service/data` beside `priority_lane_stats.json`.
_Avoid_: request log, metrics, call log (it writes no line per call)

**Demand**:
Viewing demand or Functional demand on a Creator; nothing else makes a Creator's data fetch fast (ADR-0031).
_Avoid_: activity, online, active Creator

**View lease**:
A Creator the app reports as on screen (selected Creator, visible money rail or roster strip row, open chat), renewed every 20 s and lapsing 60 s after the last renewal, unioned across tabs and Employees. It is the only Viewing demand; the "All" view never leases every Creator by itself.
_Avoid_: presence, online, SSE sub (an input, not the lease), active Creator, subscription

**Viewing demand**:
A Creator holding at least one View lease.
_Avoid_: user demand, watching, online

**Functional demand**:
Work that needs a Creator's data current whether or not anyone looks: Sellers, fan replies, welcomes, scheduled sends, list enrollment, ingestion and WS recovery. It never slows, and no fan write is capped, delayed or dropped to fund a cut.
_Avoid_: background demand, automation demand, system demand

**Idle Creator**:
A Creator with no Demand, the only one a slow cadence applies to.
_Avoid_: inactive, offline, cold, disconnected (that is a Dead session)

**Seller**:
An enabled automation whose behaviour changes the moment a fan pays, so its Creator's purchases poll stays fast around the clock. The code's list is `_SELLING_KINDS`.
_Avoid_: selling automation, money automation, sales automation

**Purchases poll**:
The read of a Creator's OnlyFans purchases notification feed (`run_fast_tick`): the fast tier (30 s) under Demand, the slow tier (5 min) for an Idle Creator.
_Avoid_: fast tick, freshness poll, ledger (that is the 15-min transaction ingest)

**App-open warm**:
One immediate refresh of purchases feed, chats window and money counters for every Creator an Employee can access, when they open Inflowwww on any page, staggered per proxy; then normal cadence.
_Avoid_: prewarm (that is Growth's link prewarm), boot warm, login refresh

**Select refresh**:
The immediate refresh of a Creator when it is opened or selected, before its first lease timer.
_Avoid_: open warm, eager poll

**Dead session**:
A Creator whose OnlyFans session answers 401 or reads expired. It gets no polls, only the recovery probe ladder.
_Avoid_: disconnected Creator, logged out, expired account

**Backoff ladder**:
The purchases-feed retry wait after a 429: Retry-After first, else 30 s doubling to 900 s, capped at 120 s under Demand.
_Avoid_: cooldown, throttle, pause (`_is_paused` is a failure pause)

**Knob**:
A named cadence or threshold read in one place with today's-safe default, an env value until a Setting flag exposes it.
_Avoid_: setting (a Settings blob field), flag, config, constant

**Setting flag**:
A Knob exposed as a per-Agency Settings blob field after Phase 4, defaulting to the fetch diet's behaviour; chosen only from Proxy-health sweep data.
_Avoid_: feature flag, toggle, knob (until exposed)

**Audience crawl** (retired 2026-11-12):
The paged OF roster read of a mass send's recipients run right after the send; deleted (docs/spec/phase-02-audience-crawl.md). Who received a send is now assumed from its `audience_filter`; members of its `excluded_user_lists` (AUTOFENCE / Auto_Exclude) are not seen and count as received.
_Avoid_: recipient resolve, mass crawl, audience fetch

**Silent mass-only chat**:
A chat holding only our mass messages and no fan reply; its deep history backfill waits until the chat is opened, the fan replies or an automation needs it.
_Avoid_: dead chat, cold chat, empty chat


### Shared Creator freshness

**Open-tab Creator**:
A Creator that at least one Employee holding a live Event stream can access. Wider than Viewing demand: a View lease says a Creator is on screen, an Open-tab Creator only that someone could look.
_Avoid_: watched Creator (a Watcher subscribes to Creators, and "watching" is Viewing demand's rejected word), Streamed Creator (Stream is taken), leased Creator (narrower), active Creator, online
ASSUMPTION: coined instead of the plan's "watched Creator" (rung 1: `accounts.py` ROLE_WATCHER, View lease's _Avoid_); overturned if the owner keeps "watched".

**Event stream**:
A tab's one `/events` connection to the Relay, over which Relay events (`creator_warmed`, `chat_read_changed`, …) reach every tab that can access their Creator.
_Avoid_: SSE sub (a View lease input), Stream (taken: a sender's word), websocket (that is the Live connection), subscription

**Live connection**:
The Relay's one OnlyFans websocket per Creator (`service/of_ws.py`), bringing DMs and counter frames at no OF call.
_Avoid_: WS pump, socket, stream, Event stream (Relay to tab)

**Shared refresher**:
The Relay loop that reads each Open-tab Creator that is no Dead session at most once per Cycle on behalf of every Employee and tab, and publishes only what changed on the Event stream (ADR-0042).
_Avoid_: watched-Creator refresher, variant C (the study's label), poller, warm loop, App-open warm (one refresh per open, not a loop)

**Cycle**:
How often the Shared refresher reads one Open-tab Creator: the lease cycle (~120 s) while it holds a View lease, else the tab cycle (~10 min), never under a 60 s floor whatever the Knobs say.
_Avoid_: tick, interval, period, fast/slow tier (the Purchases poll's)

**Last refresh**:
A Creator's one freshness clock: when the Shared refresher or the App-open warm last read it. Within its Cycle it counts as fresh for both, so neither re-reads it (ADR-0044).
_Avoid_: reuse window (the warm's old 30 s), as_of (a Roster count's own stamp), freshness on its own, two clocks

**Unread total**:
The Relay's one count per Creator of chats OnlyFans holds unread across the whole inbox, pushed to tabs on change; the Unread badge's first-paint truth (ADR-0043).
_Avoid_: Roster count (a 25-chat window), unread count (one chat's `unreadMessagesCount`), Unread badge (what a tab shows), unread flags
ASSUMPTION: whole inbox, not the Roster count's 25-chat window (rung 2 reading of the plan's "true unread total", live 12 vs 1); overturned if Q1 or the Phase 2 spec settles on the window.

**Roster count**:
A Creator tab's two counts from `/admin/accounts/roster-counts`, unread (blue) and owe reply (orange), folded from the first 25 chats of the Creator's inbox; a full window reads "N+".
_Avoid_: Unread total, badge count, tab total

**Unread badge**:
The count on the Fan List's Unread chip: unread chats among the Creators the Fan List shows.
_Avoid_: Unread total (the Relay number it is seeded from), Notifications badge (the bell's count), Roster count, chip count

**Data age**:
How old a Creator's Unread total or other Relay truth a tab shows is: now minus when the Relay last confirmed it. Past one Cycle the badge shows it as "as of".
_Avoid_: staleness, last updated, freshness, as_of on its own (the field)

**No-live-connection mark**:
The per-Creator mark a tab shows while the Relay has no Live connection for that Creator: its websocket is down or it is a Dead session.
_Avoid_: offline, disconnected badge, no connection, Dead session (one of its two causes)

- **Watcher** (a fan account the Agency subscribes to its Creators to read what they send; no Creator, never leased, warmed or refreshed): `service/accounts.py` `ROLE_WATCHER`

### Slop feedback

**Run identity**:
What makes two slop runs the same run: the knobs, the source tree (with the ignored inputs a stack loads) and the caller environment that reaches the stack. A Shared run and a reused Break baseline need an equal Run identity: knobs (`_same_knobs`, `slop/lib/cli.py`) plus source and environment (`slop/lib/identity.py`). The p95-vs-last-green comparison still matches knobs and world only.
_Avoid_: same knobs (one part of it), cache key, fingerprint

**Shared run**:
One execution that answers several exact, concurrent requests with the same Run identity; each caller gets that run's exit code, run folder, failures and cancellation as if it had started it. Never an earlier finished run.
_Avoid_: cache, cached result, reuse (that is a Break baseline's), dedup on its own

**Fresh run**:
A run that executes itself even while a Shared run with its Run identity is live: an explicit repeat or flake run, and every nightly re-run of a FAIL.
_Avoid_: retry, re-run on its own (nightly's word for the second attempt of a FAIL, `slop/lib/nightly.py`)

**Break baseline**:
The green no-fault run a `--break` compares its fault run against: run first, or read from `--baseline=<run folder>` only at an equal Run identity.
_Avoid_: Baseline (the Capacity campaign's first 24 h), Baseline run (the Fetch diet's pinned sweep), last green (`P95_VS_LAST`'s comparison run)

**Run phase**:
One of a slop run's startup, seeding, execution and teardown, each timed on its own.
_Avoid_: stage (a load step a scenario sets as `ctx.rec.stage`), step

- **Machine gate** (`~/.slop/gate.py`: slots, load and thread admission across every checkout), **`--changed` pick**, **CAUGHT / NOT CAUGHT / INCONCLUSIVE**, **run folder**: `slop/README.md`

### Full AI Chat

**Full AI Chat**:
The per-Creator automation (rule and kind `full_ai_chat`) that answers a Fan's every Turn through the Router and a Writer, merging auto convo and AI-chatter selling into one Lane; the welcome engine only hands Fans to it. Its page is titled "Full AI Chat", at `/full-ai-chatter` (`app/app/full-ai-chatter/page.tsx`).
_Avoid_: AI chatter (the retired fastt engine it re-implements; see **AI Copilot**), Full AI Chatter (the page's old title), auto convo, full_ai (a code prefix)

**Lane**:
An automation that writes to one Fan 1:1 and competes for his next reply: a funnel walk (`reply_mass_funnel`), Get to know fans (`welcome_chatter_for_info`), Auto-reply, or Full AI Chat. The Full AI Chat page already calls them "AI lanes".
_Avoid_: Split Inbox group, `/admin/lanes` (concurrency), priority lane, engine

**Lane ownership**:
Which one Lane, or none, may reply to a Fan at an Evaluation point, decided by the pure `who_owns` precedence (ADR-0036). It decides who replies, never whether to sell.
_Avoid_: owner on its own (the Agency's, as in **Owner session**), ownership on its own (`ownership.py`'s bought media), engine_active

**Human yield**:
The Lane ownership rule that no Lane replies to a Fan for a while after a human's 1:1 outbound (`manual_yield_minutes`, code default 60 s; D49's 1 h is set per Creator at the flip); an outbound of unknown sender counts as human. OF-app yield feeds it from a live one-Fan read at Full AI Chat's pre-look, again just before a Turn's first bubble and before its paid card.
_Avoid_: takeover, human window, pause

**Top spend limit**:
The lifetime spend at or above which Full AI Chat stops replying to a Fan and leaves him to humans; with the per-Creator exclude list, the only exit from Full AI Chat besides its switches (owner D8).
_Avoid_: whale gate, whale cap

**Stand-down**:
The other Lanes skipping a Fan whom Full AI Chat claims (`claims`: Full AI on for the Creator, i.e. global switch not set, rule enabled, Mode live, and the Fan on its Fans list), whatever Full AI then does (reply, `no_send`, Stop): Get to know fans (every trigger, at its candidate seam), Auto-reply, and the Welcome handoff (a claimed Fan's handoff job is `full_ai_chat`). Shadow mode stands nothing down, and funnel code never changes (ADR-0036).
_Avoid_: yield (that is **Human yield**), disable, mute

- **Welcome handoff** (the welcome engine passing a Fan to the Lane that owns him; per Creator today, per Fan once Full AI Chat goes live): `service/automations/welcome_turn.py`

### Full AI Chat routing

**Jev**:
TypeSafe's System One model, pinned at `jev-1.14.0`, which answers typed questions with calibrated probabilities. In Full AI Chat it answers the Router questions and never writes fan text; the FM off-script gate asks it too (ADR-0026).
_Avoid_: TypeSafe (the vendor and its SDK), the router (Jev answers, the Route table decides), classifier, judge

**Turn**:
A run of consecutive messages from one Fan, decided once by the Router and recorded as one Decision row.
_Avoid_: DM (one message), message, exchange, welcome turn (`welcome_turn.py`'s)

**Anchor**:
The fan message whose arrival triggered a Turn: its id is the Decision row's `trigger_key`, and a fan message newer than it at Last-look aborts the Turn.
_Avoid_: trigger_key (the row's key, which a Wake or Test chat Turn has without an Anchor), cursor

**Router**:
Full AI Chat's per-Turn decision: one Jev request answering every Router question, then the Route table. A failed request makes the Turn chat at Heat 1 with no Offer (ADR-0032).
_Avoid_: brain, classifier, gate (the FM off-script gate, ADR-0026, or a Capacity campaign **Gate**)

**Router question**:
One of the fixed questions in the Router's one Jev request: the yes/no Nouls with their thresholds, the `intensity` Score and the `asks_subject` and `asks_format` Choices. The Choices and the DRAFT Nouls `counter_offer` and `offer_moment` are asked in test Mode only until the owner OKs their wording; Shadow's request and `question_version` stay Phase 01's. Their wording and thresholds are data in one module, and each Decision row records their `question_version` (test rows the test Mode's).
_Avoid_: Noul (TypeSafe's yes/no answer type, which `intensity` and the Choices are not), signal, check, rule

**Ask cut-off**:
The probability at or above which the Router question `wants_content` counts as his ask for content: 0.7 in Shadow mode, 0.65 in test Mode (owner 2026-11-14).
_Avoid_: threshold on its own (every yes/no Router question has one), ask gate, sell threshold

**Sitting**:
One stretch of a Fan's chat with no gap of more than 120 minutes between consecutive lines; in a Test chat it is normally the whole session.
_Avoid_: session (the Test chat's, which a Sitting usually equals; or an **Owner session**), conversation, visit

**Spacing**:
The test Mode rule that she offers an Unasked piece only after at least 3 of his lines since her last Piece, and at most 3 Unasked pieces in a Sitting; an ask always overrides it. It is wording in the unasked-offer Router questions that Jev applies, never a cap in code (ADR-0032). The owner's rule (2026-11-14) is Jev wording, not a code cap, so ADR-0032's "no per-Fan offer limit" still holds.
_Avoid_: cooldown, offer cap, rate limit, pacing (a paced Turn's `wake_at`, see **Wake**)

**Route**:
What one Turn does: chat, sext, sell_now, tease, make_right, ai_dare or no_send. A tease (on price or a decline, which never blocks selling) teases now so his next Turn sells; with selling off it is chat.
_Avoid_: action (the FM off-script gate's per-reason action, ADR-0026), intent, Mode, Lane

**Route table**:
The pure first-match map from Router question answers and the Pending tease to a Route (`full_ai_decide.decide_turn`), holding no rule beyond them (ADR-0032).
_Avoid_: decide table (`_fm_relevance`'s, ADR-0026), decision table, router rules

**Route row**:
One first-match line of the Route table, named for what it reads (`haggle`, `offer_moment`, `offer_details`); several rows lead to one Route, and the Decision records the row that matched (`Decision.row`).
_Avoid_: rule, branch, case, Route (the row's outcome, not the row)

**Protected row**:
One of the five Route rows that every other row and the Pending tease sit below: promo, says_under_18, complains_now, asks_if_ai and stop.
_Avoid_: safety row, priority row, hard stop

**Evaluation point**:
A moment the Router decides afresh and asks Jev again: inbound dispatch, each bubble's Last-look and a Wake's resume. No answer carries over between them (ADR-0032).
_Avoid_: checkpoint, tick, re-check

**Last-look**:
The Evaluation point just before each bubble goes out: reload the facts, confirm Lane ownership, confirm no fan message is newer than the Anchor and ask Jev again; any miss aborts the bubble and re-routes.
_Avoid_: pre-send check, final check, `finalize_draft` (`_outbound`'s text filter)

**Wake**:
A paced Turn resuming at its `wake_at`: an Evaluation point that also re-runs Lane ownership, recorded as a Decision row whose parent is the paced row. A Wake never parents a Wake.
_Avoid_: retry, follow-up, resume job

**Heat**:
How sexual a Writer may be on a Turn, 1 to 4: the Fan's own `intensity` level (his Score rounded, a tie up) plus one, at most 4, so never below him; 1 when the Router's request failed.
_Avoid_: intensity (the Router question that measures him), intensity cap, spice

**Pending tease**:
The one piece of Router state: a fully landed tease from Full AI Chat that he answered within 15 minutes, with no other outbound and no purchase since, so his reply becomes a sell. It is derived from Decision rows, never stored (ADR-0034); the tease Route makes one once selling is on, so Shadow never has one. In the Test chat its one source is `full_ai_test.pending_tease_of` over the session's test rows: the newest row is a sent tease carrying its Pick, at most 900 s before his reply, with no Offer outcome since; its text goes first in the Pending offer.
_Avoid_: router state, pending sell, open offer, Pending offer (the Jev field carrying its text)

**Pending offer**:
The Router's `pending_offer` field, read by `says_yes_to_offer`: the Pending tease's text, or in Shadow mode her newest priced unbought outbound from any Lane, or in test Mode the session's newest Offer with no Offer outcome (its price and the caption it rode), else "none".
_Avoid_: open offer, Unconfirmed offer, Offer

**AI dare**:
The ai_dare Route's reply when he asks whether she is a bot: the old two-beat dare, a breezy joke then "send me one and I'll rate it", and a rating out of 10 with two or three specifics for the pic he sends. Never a flat denial.
_Avoid_: AI denial, "are you AI" answer

**Make-it-right**:
The make_right Route on a Turn where he complains about something he paid for: an apology plus a Free item matched to what he wants, never an Offer on that Turn. The next Turn routes as usual, so an Offer may follow at once.
_Avoid_: complaint route, refund, repair, sell block

**Writer**:
The model that writes a Turn's fan-facing text, captions included, on the old fastt prompts verbatim (`docs/prompts/`). Writers form a fallback chain, not a split (D54, D60): Euryale v2.3 on NanoGPT, then Hermes 4 405B on OpenRouter, GLM-5.3 on Z.ai and DeepSeek, in the order of the config's `writers` list; the next is tried only when the one before fails (HTTP error, 429, timeout, empty reply, code-floor reject, no key, or its provider's daily cap). Each Decision row records its Router model, and its Writer once it writes a reply (a Shadow row has none).
_Avoid_: gen model, sexting model, generator, caption LLM

### Full AI Chat selling

**Offer**:
A PPV a Decision row plans or sends at a price above 0, chosen by the Sell executor; at most one per Turn. A Free item rides the same row at price 0 and is not an Offer.
_Avoid_: PPV on its own (the message kind), sale (the purchase), pitch
ASSUMPTION: the price-0 Free item is kept out of "Offer", though the ledger ticket calls the gift "a price-0 offer"; overturned if the specs need one word for both.

**Unconfirmed offer**:
An Offer whose send outcome is unknown (its send marker reads UNCONFIRMED). It counts as sent and blocks the next Offer to that Fan until settled.
_Avoid_: Pending offer, failed send, open offer

**Open Offer**:
An Offer with no Offer outcome, not re-offered by a haggle and whose locked media he does not own (`full_ai_test.open_offer_of`); live also needs it at most 24 h old and confirmed on OF (`full_ai_owned.open_offer_live`).
_Avoid_: Pending offer (the Jev field), Unconfirmed offer, outstanding offer, live offer

**Offer outcome**:
Whether he bought or declined an Offer (`outcome` bought | declined, `outcome_at`), set once on its Decision row and never flipped, with `join_src` saying how it was known: `test` for the owner's fake Buy / Decline in the Test chat; Phase 05 adds the live sources. A bought Offer's locked media become Owned media.
_Avoid_: settled flag, is_paid (the message's), purchase (the transaction)

**Send-correctness rules**:
The only behaviour Full AI Chat hard-codes: at most one Offer per Turn, an Unconfirmed offer blocks the next, and nothing is sent twice (ADR-0032).
_Avoid_: brakes (the older word, which also covered the dropped complaint and decline stamps), safeguards, caps, may_sell

**Sell executor**:
The pure pool, price, pick and Claim audit code (`full_ai_sell.py`) that turns a sell_now or make_right Route into one Pick from the Creator's vault, or into a refusal that falls back to chat.
_Avoid_: Seller (the fetch diet's always-fast automation), resolver

**Pick**:
The Sell executor's media for one Offer or Free item: one clip, or one photo or a Bundle, plus at most one free preview, none of them Owned media.
_Avoid_: pack
ASSUMPTION: this entry was written by an earlier spec run (Phase 01, #574), so "up to four photos from one shoot" is updated for the Bundle; overturned if a human wrote it, then it stands and the Bundle entry carries the change alone.

**Bundle**:
Two to five photos sold together as one Offer at one price: photos of one shoot, filled up to three with other photos matching his ask when the shoot has too few (owner 2026-11-14: "3-5 sell better sometimes"). A video always sells alone.
_Avoid_: pack, set, album, shoot (the vault's grouping a Bundle starts from)
ASSUMPTION: the owner's line means photos per Offer, said right after a one-photo $45 Offer; overturned if he meant Pieces per Sitting.

**Chat tease**:
In test Mode (config `chat_tease`, Page switch "Chat tease", needs Sell), a teasing photo that rides her ordinary reply in a normal chat, the text never mentioning it (owner 2026-11-14, after the old teaser ladder). It fires when Jev's `chat_tease` says the moment fits (from about his 5th line, 3+ lines since her last piece), and an Unasked piece on row `offer_moment` outside a hot scene goes out this way too (owner 2026-11-14 "just one feature": the former Ride-along offer folded in). No ladder in code: a second Jev picks its price from the config list `chat_tease_prices` (free or $3-$200; default free, $3, $10, $40, $80, $120, $160, $200), reading what he bought and spent and `teases_sent` (each tease she sent this session and how he took it); free is one unlocked photo, a price up to price ÷ $5 photos. That Jev failing sends no tease that Turn; her text failing the Claim audit twice sends the text without the photos. Her free Chat tease photo ends Spacing's line count but is not a Piece.
_Avoid_: tip ladder, teaser ladder (the old repo's, which had fixed prices), Ride-along offer (retired name), silent PPV, Free item (make_right's), teaser

**Piece**:
An Offer as Spacing counts it: a Decision row of the Sitting that carried an Offer, whatever its Offer outcome. A Free item or a free preview is not a Piece.
_Avoid_: PPV on its own (the message kind), item, media, sale (the purchase)

**Unasked piece**:
A Piece he did not ask for: the Route table sold it because the moment fit (`offer_moment`, `scene_offer` or `chat_tease`), not because of an ask (`wants_content`, a yes to an offer, a Pending tease or a haggle).
_Avoid_: upsell, push, cold offer

**He likes**:
In test Mode, what turns him on, kept as a short comma list in the session fold's `fetishes` from his own lines (a wider extract than wcfi's) and given to the Router's `asks_subject` on every Turn, so a generic ask ("send me pics") is filled by what he is into; Jev's Choice decides, no code maps likes to media (ADR-0032).
_Avoid_: kinks, preferences, interests (his hobbies), fetish profile

**Asked count**:
Full AI Chat's per-Fan `asked` fold: for each get-to-know fact, how many of her sent replies actually asked for it or led to it, in pick and list modes alike; a reply that asks nothing counts nothing.
_Avoid_: asked counter, asked marks (`asked_marks`, list mode's "k" / "k:2" view of it), questions_asked (wcfi's set)

**Nearest piece**:
In test Mode, the Offer she sells when nothing in the vault matches his ask: the closest Pick (same subject, then same format, then anything), whose caption never passes it off as what he asked for.
_Avoid_: substitute, fallback, no_match (the Refusal it replaces)

**Price Jev**:
In test Mode with the sext scene on, a second Jev request on a fresh priced Pick: one Score that sets the Offer's price on a fixed ladder. A failure keeps the vault's list price; a haggle keeps its clamp.
_Avoid_: pricing model, price engine, Router question (it is not one)

**Price signals**:
The facts about the Fan that the Price Jev reads besides the Offer itself: whether he asked for this Piece, whether he has bought before, and his Heat.
_Avoid_: price rules, price factors, buyer tier

**Owned media**:
Media a Fan has bought, by any join source, or received as a Free item. It is never offered to him again; unbought media may be re-offered (owner D13).
_Avoid_: seen media (also counts sent but unbought; the Free item's pool excludes it), was_purchased (`vault_sends`')

**Free item**:
The one unseen vault item, price 0 and matched to what he wants, that a Make-it-right Turn sends. It is uncapped (ADR-0032) and becomes Owned media.
_Avoid_: gift, freebie, preview (the free photo beside an Offer), Free previews (the PPV row's)

**Heat check**:
On a sext reply, one Jev Score of how sexual her final text is (0-4, the `intensity` scale turned on her) against the Heat the Writer was given; over it, the same Writer rewrites once and the rewrite ships only if it is not over. A failed check or a second over-Heat text still sends. Runs under `floor_on` in every Mode that writes; recorded on `reply_json.heat_check`.
_Avoid_: intensity post-check, intensity cap

**Claim audit**:
The check that a sell or Free item bubble's exact final text claims only what its Pick holds (count, kind, and subject words by a strict lexicon). A failure regenerates once, then sends a fallback caption built only from the Pick's counts and kinds.
_Avoid_: caption check, pack_claim (the old fastt check), word filter (`_wordfilter`)

### Full AI Chat offer details

**Offer-details question**:
His factual question about an Offer already sent: what is in it, photo or video, how many, how long, how much it was, which one, same as before. The Router question `asks_offer_details` (test and live Mode; Shadow's request unchanged) asks Jev whether his Turn is one, and Route row `offer_details` answers it on the chat Route without touching offer or Router state (ADR-0037).
_Avoid_: factual question, offer question, product question, haggle (a discount ask), content ask (`wants_content`)

**Offer resolver**:
The pure, read-only lookup that names the one Offer an Offer-details question is about, among the Fan's Offers of the same Creator (Test chat: same session and side), or none, which makes her ask which one (ADR-0038). Its steps, first match wins: Quote-reply, a unique Quoted price and/or media type match, the newest Open Offer, none.
_Avoid_: resolver on its own (the Sell executor is not one), offer lookup, matcher, Pick (what the Sell executor chooses to send)

**Quote-reply**:
A Fan message sent as OnlyFans's reply to one earlier message (inbound `replyToMessage.id`), naming that Offer when it matches an Offer's `offer_message_id`; in the Test chat, a line the owner marks as a reply to an earlier bubble.
_Avoid_: reply on its own (any answer), quote, thread reply

**Quoted price**:
The price an Offer went out at, its Decision row's `offer_price_cents`: the only price an Offer-details answer states.
_Avoid_: price on its own, current price, catalogue price, list price (the row's `offer_list_cents`)

**Folder price**:
An Agency's price on a vault folder today (`vault_folder_prices`), the input the Sell executor and Price Jev price a new Pick from; it may change after an Offer went out and never stands in for that Offer's Quoted price.
Not the Twin folder-price override (twin-infloww_crm d1c1097, `full_ai_sell.folder_price` / `tease_price`: a saved folder price becomes the offer and list price and Jev is not asked), which is absent from private main and belongs to the separate pricing spec.
_Avoid_: catalogue price, vault price, Quoted price

**Offer facts**:
What an Offer-details answer may state about the resolved Offer, read from its Decision row and the vault: media type, locked count, free previews listed apart, duration, vault description and Quoted price.
_Avoid_: offer details (his question), caption (all a chat Writer saw of an earlier card before), metadata

**Offer answer check**:
The local check that an `offer_details` reply's counts, media type, duration and dollar amounts match the Offer facts, a free preview never counted as a paid item; one rewrite, then a short plain fallback built from the Offer facts, never another item and never no reply.
_Avoid_: Claim audit (sell and Free item bubbles against their Pick), fact check, Heat check

### Full AI Chat ledger and rollout

**Decision ledger**:
The append-only `ai_decisions` table: one Decision row per Turn and Mode, never updated by a later Turn, and the owner of the Offer→purchase join (ADR-0034).
_Avoid_: ledger on its own (the transaction ingest's), offer ledger, decision log

**Decision row**:
One `ai_decisions` row: a Turn's Mode, Jev answers, `question_version`, Route, Router model, any Writer, any Offer or Free item, and its outcome.
_Avoid_: ledger row, shadow row (only a Decision row in Shadow mode), AI decision, log line
ASSUMPTION: "Decision row" over the plan's "ledger row" and the rollout ticket's "shadow row"; overturned if the specs keep "ledger row".

**Mode**:
How a Full AI Chat Turn runs, recorded on its Decision row: shadow (decide and record, send nothing), test (the owner's Test chat) or live (sends). Off is the `full_ai_chat` rule disabled, not a Mode.
_Avoid_: Rollout stage, status

**Shadow mode**:
The Mode in which the Router decides and records on real traffic through a runner with no send path, no fan lease, no cooldown and no OF call, so no Fan sees anything (ADR-0033).
_Avoid_: Shadow relay and Shadow slice (the Capacity campaign's), shadow test

**Test chat**:
The owner chatting as a Fan with Full AI Chat on the Full AI Chat page (Mode test): no OF call, waits skippable, rows deleted after 7 days. Two sides answer the same Fan line: checkpoint (the saved config) and draft (the unsaved edit).
_Avoid_: sandbox, playground, helper chat (the assistant's config tool), left/right or L/R (the sides are checkpoint and draft; L/R only in the page's code, never in requests or UI text)

**Enrolment**:
A Fan of a Full AI Chat Creator counted for Revenue per enrolled fan, derived: his first inbound message after the Creator's first live Turn; no row. His Arm is the Fan hash's (`arm_of`), never stored for it (ADR-0035).
_Avoid_: enrollment (OF list enrollment, a **Functional demand**), assignment

**Arm**:
A Fan's side of the fixed Fan-hash split, on every Decision row (`arm`, `salt_ver`): treatment (about 80 %) or holdout (about 20 %). A label only: no holdout gate is built (Owner answers 14), so who Full AI Chat answers is its claim (*Stand-down*), never the Arm. A gate later is one fact in `claims`, landed before a Creator's first flip.
_Avoid_: control group, slice (the **Shadow slice** is a systemd slice), bucket, cohort

**Revenue per enrolled fan**:
Net revenue from every source over 14 days per Enrolment, treatment Arm against holdout Arm: Full AI Chat's win measure (ADR-0035).
_Avoid_: **Total spend** (the Fan List's per-Fan figure), buy rate (a per-Route reading of router quality), conversion rate, LTV

**Rollout stage**:
One of S0 (offline replay) to S6 (sext) through which a Creator's Full AI Chat moves; only the owner flips one forward, after its checks pass.
_Avoid_: **Stage** (a Capacity campaign ladder step), phase (a plan's PR slice), **Gate** (the Capacity campaign's G1–G13)
ASSUMPTION: named "Rollout stage" so the Capacity campaign's Stage keeps one meaning; overturned if the specs say S0–S6 only.

### Keep promos running

**Keep running**:
The per-campaign tick, one switch over `promo_campaigns.auto_reactivate` and the Creator's `promo_reactivate` rule, that has Inflowwww re-create a Creator's promo instead of letting it lapse. At most one campaign per Creator has it.
_Avoid_: auto-reactivate, Auto-activate campaign (the read-only status row's label), armed, re-arm

**Kept campaign**:
The one `promo_campaigns` row of a Creator with Keep running ticked.
_Avoid_: armed campaign, managed campaign, auto-reactivate campaign

**Live promo**:
The OnlyFans subscription promo a Creator has on offer: not finished, claimable and under its Claim cap (`of_promos.normalise_of_promo`). Taken to be at most one per Creator.
_Avoid_: active promo, current promo, running promo

**Kept promo**:
The Live promo whose OF id is the Kept campaign's current `of_promo_id`: the only promo Inflowwww ever replaces (ADR-0039).
_Avoid_: our promo, managed promo, armed promo

**Re-create**:
One create on OnlyFans with a Kept campaign's saved terms, after which the campaign points at the new promo. Both After-end re-create and Pre-emption are Re-creates.
_Avoid_: reactivate, re-arm, renew, resurrect (code keeps `reactivate` in names: `reactivate_count`, `last_reactivated_at`)

**After-end re-create**:
A Re-create when no promo is live any more: the PR #850 path, kept as the fallback.
_Avoid_: reactivation, expiry path, restore

**Pre-emption**:
A Re-create while the Kept promo is still live, so OnlyFans ends it and the profile has no gap: Fill pre-emption at 90 % of the Claim cap, Timed pre-emption shortly before the OF end time (ADR-0039).
_Avoid_: pre-emptive re-create, early re-create, rollover, swap

**Re-create at 90% filled**:
The Kept campaign's second tick, under Keep running, that allows Pre-emption; ticked by default.
_Avoid_: pre-empt flag, early re-create switch

**Claim cap**:
The most Fans who may claim one promo (OF `subscribeCounts`, the mirror's `subscribe_counts`; 0 is unlimited).
_Avoid_: Offer limit (the Create promotion form's label only), subscribe counts, limit, cap on its own
ASSUMPTION: "Claim cap" (plan, code) over the form label "Offer limit"; overturned if the specs or UI copy must say "Offer limit".

**Claims**:
How many Fans have claimed one promo (OF `claimsCount`, the mirror's `subscriber_count`).
_Avoid_: subscribers, uses, redemptions, fill

**Trusted count**:
Claims of the Kept promo that are present on the read, read ≤ 90 s ago, never went down, below the Claim cap, and whose first read of that promo id was 0, with a recovery create left in the Create budget; the only Claims a Fill pre-emption acts on.
_Avoid_: fresh count, verified claims, live count

**OF end time**:
A promo's `finishedAt` as OnlyFans returned it: the only end time a Timed pre-emption acts on.
_Avoid_: expires_at (it may hold the guessed end), guessed end (created + finish days; it times Re-checks only), expiry

**Free-trial promo**:
A promo at 100 % off, the Create promotion form's "Free trial" type. Keep running starts unticked on it, and a Kept one has a finite Re-create limit.
_Avoid_: free trial on its own (OnlyFans's Free trial links, `/trials`), free promo
ASSUMPTION: named apart from Free trial links though the form says "Free trial"; overturned if the specs never mention trial links.

**Create reservation**:
The durable per-Creator row written before every promo create, automatic or manual, and settled after it; while one is open no create runs until it is reconciled against OnlyFans's promo list or the Employee clears it (ADR-0040).
_Avoid_: lock, lease (the View lease, the fan lease), pending create, intent

**Create budget**:
How many automatic promo creates one Creator may attempt per hour and per day, failures and unknown outcomes included; the Employee's manual creates neither count nor are refused (ADR-0040).
_Avoid_: rate limit, quota, Claim cap, max re-arms (`max_reactivations`, a lifetime cycle count)

**Create back-off**:
The wait after a failed create before Keep running tries again, OnlyFans's Retry-After first.
_Avoid_: **Backoff ladder** (the purchases feed's), Cooldown, pause

**Cooldown**:
The least time between two Re-creates of the same Kept campaign (`cooldown_minutes`, default 2).
_Avoid_: Create back-off, throttle

**Zero-claim breaker**:
The stop that turns Keep running off and warns after N Re-creates in a row whose replaced promo gained no Claims or whose new promo was never seen live.
_Avoid_: circuit breaker on its own, kill switch, Create budget

**Host fence**:
The rule that a Relay makes automatic promo creates only when its own environment's host id (`PROMO_CREATE_HOST_ID`, one per box) equals the id stamped on the Kept campaign, so a copied DB never creates (ADR-0041).
_Avoid_: kill switch (a `runtime_switches` override, which a copied DB carries), host lock, Create reservation

**Takeover**:
A new campaign created with Keep running ticked taking the tick from the previous Kept campaign; the Employee is told which campaign lost it.
_Avoid_: move, unarm, untick

**Subscribe toast**:
The OnlyFans "subscribed" websocket notification on which `event_transcoder` Pokes `promo_reactivate` and `send_welcome`. Whether a promo claim fires one is not yet measured.
_Avoid_: new-subscriber event, subscriber event, sub notification

**Poke**:
An event asking an interval rule to run before its interval, no sooner than `POKE_FLOOR_S` (60 s) after its last job; one under the floor is kept for a later pass (`Repoke`) only for `promo_reactivate` and `purchase_followup`, else spent.
_Avoid_: trigger, wake, nudge (`nudge_online` is an automation)

**Backstop**:
The `promo_reactivate` rule's own hourly run.
_Avoid_: poll, tick, sweep

**Re-check**:
A `promo_reactivate` run the automation queues for itself (near_cap, expiry or cooldown), at most one pending per Creator.
_Avoid_: follow-up on its own (any `enqueue_followup` job), retry, recheck

### Script fill

**Sequence**:
A Growth > Scripts sequence: the saved replies of one Creator that share a `script_id`, run in `script_step` order. Fill works on one Sequence at a time.
_Avoid_: script (one saved reply: the Scripts page's row and the Composer's **Script**), funnel, ladder, `vault_scripts`' "script" (that is a **Shoot**)

**Step**:
One `script_step` number in a Sequence, holding one or more Options; successive Steps are what the Escalation rule climbs along.
_Avoid_: stage, rung, block (FM's word)

**Option**:
One saved reply inside a Step, shown "2.1", "2.2" when a Step holds several; Options of the same Step are alternatives, and a Fill writes per Option.
_Avoid_: script, variant, step

**Role**:
What an Option is for, read from its saved price and deterministic text cues: `chat` (text only), `free_media` or `paid_media`, with the media it wants (photo, clip, any) and a count when the text promises one.
_Avoid_: type, kind, purpose lane (`vault_scripts`' folders), Lane

**Fill**:
One write of a Creator's own vault media, and prices where none is saved, onto the empty Options of one Sequence, done by the "Fill with content" press or the Rollout driver. It sends nothing to Fans (ADR-0048, superseding ADR-0045; ADR-0046).
_Avoid_: auto-fill, populate, attach, import (the bulk import keeps prices but never media)

**Fill plan**:
The read-only answer of `fill/plan` for one Sequence: a Fill status, each Option's Role, Slice, price and flags, the Describe target counts, and a fingerprint that `fill/apply` may hold it to.
_Avoid_: preview, dry run (the Rollout driver's default mode), proposal (`plan_ai_folders`')

**Fill status**:
A Fill plan's one-word outcome: `ok`, `already_filled` (nothing to write), or a reason nothing is written: `no_paid_steps`, `not_enough_content`, `no_fit`, `price_conflict`, `price_out_of_range`, `reserved`. Only `not_enough_content` offers to describe.
_Avoid_: error, partial

**Slice**:
The media a Fill puts on one Option: on a paid Option one to four photos of the same Rung and Shoot plus one clip (clip last; photos only, flag `no_video`, when no clip is left), or one clip alone when the text asks for a clip; a free Option one free-safe photo. A paid Slice holding photos gets at most one free preview, preferring the photos' Shoot (ADR-0048).
_Avoid_: Pick (the Sell executor's), Bundle (Full AI Chat's two-to-five-photo Offer), pack, set
ASSUMPTION: "Slice" (the media-pick answer's word) is chosen over "pack" and "bundle" because both are taken or avoided elsewhere in this glossary; overturned if the specs need the Full AI word.

**Shoot**:
A group of one Creator's vault items from one outfit and room close in time (`vault_scripts.collect_outfit_scripts`). A Fill draws each Step from the Creator's whole pool and reads Shoots only as a tie-break: a Slice's photos share one, its clip and preview prefer it (ADR-0048, superseding ADR-0045's one Shoot per Sequence).
_Avoid_: folder (an OnlyFans vault folder), outfit (Jev's clothing state), set, album, script (`vault_scripts`' name for it)

**Rung**:
An item's place on a Shoot's dressed-to-explicit arc, the script rung of `vault_scripts._with_script_why`; send order and a Fill's "highest unused item last" read it.
_Avoid_: tier (`explicitness_tier`, describe's own field), band (`ladder_bands`, not used by Fill), level

**Fillable item**:
A vault item a Fill may use, checked by Fill itself over effective metadata (`vault_ai_effective`): live, described, the same Creator's, solo, on a Rung, and not Jev review, held, rejected, in the REVIEW folder or under an unpriced dispute.
_Avoid_: eligible item, sellable item, pool (`full_ai_sell.pool`, which Fill does not use)

**Fixed price**:
A saved price above 0 on an Option. A Fill never changes it; it bounds the prices Fill sets beside it (ADR-0046).
_Avoid_: existing price, locked price, typed price

**List price**:
The house's price for one vault item, `full_ai_sell.list_price_cents`: its highest Folder price, else its Jev price lane (`lane5`), clamped to $10–$200. A Fill prices a photo Slice at its highest item and caps every Slice at $200.
_Avoid_: suggested price, default price (columns Fill ignores), Quoted price, lane on its own (a **Lane** is an automation)

**Escalation rule**:
Along successive Steps, on every path through a Sequence's alternatives, paid prices never go down; ties allowed. Media order follows script send order (`_script_sort_key`), never price.
_Avoid_: ascending prices, ladder (the mass-send drop ladder, the **Backoff ladder**), price sort

**Undo list**:
What `fill/apply` returns: per written Option, the media ids, previews, the price after apply and whether Fill set it (`price_set`). `fill/undo` empties only rows still holding exactly those values in the same Sequence (ADR-0046).
_Avoid_: receipt, rollback, restore (a DB restore is never the undo)

**Reserved sequence**:
A Sequence whose `script_id` is a generated FM script name (`automations/_reserved_scripts.py`). Fill refuses it with `reserved`; the Scripts page hides the button for it.
_Avoid_: plugin source script (the UI's `isSourceScript`, the same set on this stack), FM script

**Whole-vault access**:
The right to act on a Creator's entire vault, which a folder-limited chatter lacks (`vault_ai_api.assert_owner_scope`). Fill and describe-all both need it.
_Avoid_: owner scope (the function's name; not an **Owner session**), Data scope, gate (the FM off-script gate, a Capacity campaign **Gate**)
ASSUMPTION: the plan's "whole-vault gate" is renamed because "gate" and "scope" are both taken in this glossary; overturned if the specs keep the plan's word.

- **Fill with content** (the button, before "Add step" on the Sequence header), **Fill dialog** (opens only when a Fill cannot run), **Fill notice** ("Added {n} items to {m} steps · Undo"; gone on reload): `app/components/growth/ScriptsPage.tsx`, `ScriptFillDialog.tsx`, `scriptFillState.ts`

### Describe coverage

**Describe**:
The vision pass that writes a vault item's description, tags and fields from the image and its Jev reading, and marks it `describe_status = described`.
_Avoid_: tag, caption, analyse, AI describe

**Describe sweep**:
One describe-all run for one Creator under its sweep claim, walking rail folders, then newest, then oldest; its progress lives in memory, its rows in the DB.
_Avoid_: batch, job, wave (the Rollout driver's run of sweeps across Creators)

**Describable item**:
A live vault item of a kind Describe reads, whether described yet or not.
_Avoid_: undescribed item (a describable one not yet described), vault size

**Terminal failure**:
A describable item whose last Describe attempt ended in a state no retry fixes: `refused`, `blocked_drm`, `gone` or a terminal Jev hold. A target sweep walks past it; `failed` and `fetch_failed` stay retryable.
_Avoid_: failed (the retryable status), error, skip

**Describe target**:
The described count a Creator is brought up to: 1,000, or all Describable items when the vault holds fewer. It is counted from the DB on every request (describe-all's `target`), never a lifetime counter and never "1,000 more per press".
_Avoid_: limit (describe-all's per-sweep slice, where 0 means unlimited), quota, cap
ASSUMPTION: Terminal failures come off the Describable items the target is capped by, as the rollout's done line says, though the write-path answer's formula leaves them in; overturned if the Phase 1 spec keeps that formula and accepts a sweep that can never reach its target.

**Describe cap**:
A Creator account's daily spend cap on the "describe" ledger row (`daily_cost_cap_cents`, default $1), which Describe and Jev share; it resets at 00:00 UTC.
_Avoid_: budget (the **Create budget**), Fleet ceiling, limit

### Script fill rollout

**Rollout driver**:
The resumable host-side script in `scripts/script-fill-rollout/` that runs Describe sweeps and Fills for every Eligible Creator through the product routes over loopback, with modes `measure | collect | describe | plan | apply | undo | report`; dry run unless told otherwise.
_Avoid_: all-Creators endpoint (rejected), migration, job

**Eligible Creator**:
An active OnlyFans Creator with a captured session, no Dead session mark, and not a watcher account; the rest are skipped with a reason and never chased.
_Avoid_: connected Creator, roster (the **Roster count**'s), live Creator

**Fleet ceiling**:
The Rollout driver's own spend stop for one run, $2 per Eligible Creator until the canary restates it, checked against the spend ledger before each Describe sweep. It never raises a Describe cap.
_Avoid_: cap (the **Describe cap**), budget, limit

**Apply gate**:
The machine checks a Fill plan must pass before the Rollout driver applies it: status `ok`, every media id live in that Creator's vault, valid step order and previews, every price sendable ($3–$200) and the Escalation rule held.
_Avoid_: approval, review (the owner judges taste on a sample, outside the gate)

**Rollout journal**:
The Rollout driver's host-side record of every row's values before and after a Fill, and the Undo lists it can replay through `fill/undo`.
_Avoid_: log, backup (the DB backup taken before the apply wave), ledger (the **Decision ledger**, the spend ledger)

### Persist queue priority

**Inbound DM frame**:
An OnlyFans websocket frame that the transcoder would write as a Fan's message to the Creator (an inbound `messages` row, which fires the inbound hooks); the persist queue keeps it last on overflow and transcodes it first on a graceful stop. Every other frame (typing, online, toasts, outbound echoes) only costs freshness when dropped.
_Avoid_: actionable event, important event, inbound event (toasts and purchases are inbound too)

### Model-call caps

**Run slot**:
One permit of the supervisor's shared automation run pool (`_run_sem`, `run_slot.SlotPool`); a run hands it back while it waits on a model or a typing hold, and runs of the operator kinds have reserved ones.
_Avoid_: lane (the **Lane**), worker, Model-call cap

**Model-call cap**:
The one Relay-wide limit on `llm_client.chat` calls in flight at once from automation runs that have handed back their Run slot, set from the Concurrency panel (`lane_config`) like the other caps. A call waits for it outside its Run slot and only until a deadline; Employee model calls, operator-kind runs and calls that still hold their Run slot bypass it, and Jev requests are never in it.
_Avoid_: run slot, per-Creator cap (`AUTOMATION_FULL_AI_PER_CREATOR`, Full AI Turns per Creator), rate limit

**Employee model call**:
A model call made because an Employee asked for it now (help assistant drafts, manual tools), never one an automation makes; it never queues behind automation on the Model-call cap.
_Avoid_: operator call (**Employee** is the person; operator kinds are a Run slot rule), manual call, user call
ASSUMPTION: "Employee" over the plan's "operator-initiated", by the glossary's existing Employee entry (rung 3); overturned if code naming (`operator=True`) must be mirrored in the spec.

### Creator badges

**Red circle**:
A Creator tab's count of chats OnlyFans holds unread for that Creator: the Unread counter frame's value minus R, floored at 0 (ADR-0049). It replaces the Roster count's unread on the Creator tab.
_Avoid_: blue count, Roster count (the 25-chat fold it replaces), Unread badge (the Fan List chip's), notification dot

**Amber circle**:
A Creator tab's count of Owe reply chats: read, the Fan spoke last, known not muted, not restricted, and absent from the latest Unread list.
_Avoid_: orange count, awaiting badge, owe badge, OweMiniBadge (the component that draws it)

**Grey circle**:
A circle's state when the Relay has no trusted value for that Creator; it never reads as 0. The Relay names the first cause in this order: `unseeded`, `socket_down`, `r_unknown`, `dead`, `proxy_down`, `stale`; the app adds only Relay unreachable.
_Avoid_: zero, empty badge, "as of" (Data age's label), No-live-connection mark (a cause, not the state)
ASSUMPTION: Grey circle supersedes Data age's "as of" label on Creator tabs (rung 2: plan "grey dot when unknown/stale"); overturned if the owner keeps "as of" beside grey.

**Muted chat**:
A chat the Creator muted on OnlyFans. OnlyFans leaves it out of the Unread counter frame and the Unread list; it counts in neither circle and shows no unread Edge marker.
_Avoid_: silenced chat, hidden chat

**Restricted chat**:
A chat whose Fan the Creator restricted on OnlyFans (`isRestricted`, skip_list `of_restricted`). House rule leaves it out of every count, though the Unread counter frame includes it. One predicate, `excluded_from_badges`, also drops any chat whose row says `canSendMessage` false (`only_friends` included).
_Avoid_: blocked chat, muted chat

**Restricted unread** (R):
How many chats in the latest Unread list OF's counter counts (unread, not muted, sendable or `only_friends`) and `excluded_from_badges` removes (registry-restricted or `canSendMessage` false); the Red circle subtracts it from the counter. Example: counter 11, 4 `only_friends` → red 7.
_Avoid_: blocked count

**Unread counter frame**:
A Live connection frame carrying `chat_messages`: the Creator's unread chat count as OnlyFans holds it, sent once per read-state change from any source, even when the value is unchanged.
_Avoid_: counter event, badge frame, unread event, Inbound DM frame (a message, not a count)

**Creator echo**:
A Live connection frame for a message the Creator sent from any client (Inflowwww, onlyfans.com, Infloww): no `fromUser`, carries `chatUserId`. That chat is read with the Creator last.
_Avoid_: outbound echo (the persist queue's loose phrase), recipient echo, self message

**Unread list**:
OnlyFans's answer to `GET /chats?filter=unread`: exactly the chats the Unread counter frame counts. Reading it never marks a chat read.
_Avoid_: unread page, unread scrape, unread filter (the Fan List's chip)

**Complete Unread list**:
An Unread list whose row count equals the counter or that has no further page. Only a complete one may flip a Fan to read.
_Avoid_: full list, final list

**Attribution read**:
One Unread list read, diffed against the held chats window, that finds which Fans changed read state after an Unexplained frame (ADR-0051).
_Avoid_: reconcile (the Shared refresher's word), refresh, scrape, rescan

**Explained frame**:
An Unread counter frame the Relay can already account for, so it costs no OF call: an Inbound DM frame within 0.5 s, any Creator echo within 1.5 s, or a Write intent of ours. Any other frame is an **Unexplained frame**.
_Avoid_: expected frame, known frame, own frame

**Write intent**:
The Relay's record, made before it sends a read-state write to OnlyFans, that the next counter change for that chat is ours.
_Avoid_: pending write, optimistic mark, Pending offer (Full AI's)

**Peek cursor**:
The thread read cursor `id=9223372036854775807`: OnlyFans returns the newest page and leaves the chat unread (ADR-0050).
_Avoid_: max id, silent fetch, no-read fetch

**Background read**:
Any OF thread read not made because an Employee opened that chat in Messages Pro: scrape sweep, after-blast scrape, convo review, the app's unread and hover prefetch. Every one uses the Peek cursor.
_Avoid_: scrape (one kind of it), silent read, prefetch on its own

**Click read**:
An Employee opening a chat in Messages Pro, any Creator; it marks the chat read on OnlyFans through the Relay, which records a Write intent first.
_Avoid_: open, mark seen, Background read

**Badge version**:
A per-Creator number the Event stream's ping carries; a tab whose circles are behind it refetches that Creator's counts.
_Avoid_: seq (the Shared refresher snapshot's), etag, revision

**Hover cooldown**:
One server-side 30 s window per Creator, shared by every Employee and tab, inside which hover and pick reads collapse into one OF read; `?bust=` is that shared rewarm.
_Avoid_: Cooldown on its own (Keep running's), per-chatter cooldown, debounce

**Badge reads knob**:
The one per-stack knob `BADGE_READS=full|lean|off` (Attribution gap 5 s / 15 s / no reads), default `full`. At `off`, the Red circle still follows the counter and the Amber circle moves only on events; no Attribution or hover read is made.
_Avoid_: Badge reads switch, per-user flag, header flag, kill switch on its own

- **badge_drift** (the Watch check for counter vs Unread list mismatch over 30 s, reads per Creator-hour, Grey circles over 10 min, counter drops after an un-peeked first-page GET): `scripts/proxy-health/watch.py`
- **Attribution gate** (single-flight per Creator, 5 s gap, no hourly cap, honours the 429 exit hold): ADR-0051

### Platforms

**Platform**:
A creator site whose Creators Inflowwww runs, OnlyFans or Fansly today, named by one lower-case key. A Creator has exactly one; a missing key reads as OnlyFans, a non-empty unregistered one is an Unknown platform (ADR-0068).
_Avoid_: site, network, provider, backend; surface (`docs/platforms.md`'s web, phone and desktop)
ASSUMPTION: "Platform" over the plan's "site" because Infloww's own sidebar says platform (`app/components/shell/PlatformSwitcher.tsx`) and the code already has `PLATFORMS` (rung 3); `docs/platforms.md` keeps its older surface meaning until renamed; overturned if the owner wants "site".

**Platform registry**:
The Relay's list of Platforms, one entry each (`service/platforms.py`), which every per-Platform branch in `service/` asks instead of comparing a Platform's key. A new Platform is one entry and one Backend module for Relay dispatch (ADR-0053).
_Avoid_: platform map, adapter registry, `is_fansly`

**Backend module**:
The module a registry entry names to give the Relay its Platform's client, Live connection, revenue tick, send check and API error. OnlyFans has none: its empty slot is the default path, today's code.
_Avoid_: adapter, driver, backend on its own (that is the Relay)

**Shim**:
A Platform's client that answers the OnlyFans client's methods, in OnlyFans's response shape, from that Platform's own API (`fansly/fansly_shim.py`). One whole Shim per Platform, never split into shared parts.
_Avoid_: adapter, translator, wrapper, client (OnlyFans's own)

**Lacks flag**:
A named Relay policy a registry entry opts out of because its Platform cannot meet it, one flag per observed policy (`REFERRALS`, `SERVER_SCHEDULE`, …). Free follow is the one positive opt-in.
_Avoid_: feature flag, Setting flag, Knob, Capability (the app's)

**Capability**:
Something a Creator's Platform can do that one or more app controls need (`pin_message`, `restrict`, `mass_message`, …). A Platform without it lists it in the Platform table's `lacks`.
_Avoid_: feature, permission (an Employee role's), Lacks flag (the Relay's)

**Platform table**:
The app's static `PLATFORMS` list (key, label, lacks) in `app/lib/platform.ts`, read through `can` and `useCan` and held to each Shim by the Drift test (ADR-0054).
_Avoid_: capability catalog, platform config, Platform registry (the Relay's)

**Unsupported method**:
A Shim method its Platform has no equivalent for, settled for good; the Shim marks it and returns or raises nothing that reads as success.
_Avoid_: stub, todo, not implemented, Not-yet control (the OF Manager's)

**Blocked method**:
A Shim method its Platform probably has but no Capture session has recorded yet; it raises a typed error until one does.
_Avoid_: Unsupported method (settled for good), stub, pending

**Side-effect gate**:
The check that stops a caller of an Unsupported, Blocked or Live-check method, or of a refused Branch, before it sends, claims or writes local state. Hiding a control is never the only guard (ADR-0056).
_Avoid_: fake success, skip-as-sent, soft fail, hiding

**Banking set**:
A Platform's money codes whose rows the revenue lane writes as transactions, each with the one price key it was observed carrying; Fansly's is `{2007}` from `accountMediaPrice`. A code joins only after a Proof purchase (ADR-0055).
_Avoid_: purchase types, money codes, Unlock set

**Unlock set**:
The Fansly notification codes that mark a chat purchase for unlock chips and the Buys & tips rail (2007, 2008, 32007). Being in it banks nothing.
_Avoid_: purchase set, Banking set

**Proof purchase**:
A real purchase the owner makes on a Platform from his fan account to his creator account (chat PPV, paid sub, chat tip), recorded creator side before and after, so its code can join the Banking set.
_Avoid_: test purchase, Live proof (the OF Manager's), Request capture

**Capture session**:
One sitting in which the owner's creator and fan accounts on a Platform, in two Chrome profiles, take free actions in the owner's order while every request and frame is recorded into that Platform's recipes doc. It turns Blocked methods into built or Unsupported ones.
_Avoid_: Request capture (one OnlyFans control's request), HAR, sniff, capture run

**Capability test**:
The contract test that holds every registered Backend module's Shim against every client call in `service/` and fails on a reachable method that is missing and not marked Unsupported or Blocked. It runs from `scripts/run-tests.sh`.
_Avoid_: parity test, shim test, coverage test, Drift test

**Drift test**:
The Relay-side test that reads the Platform table and fails unless each Capability is in a Platform's `lacks` exactly when every Shim method it maps to is missing or marked.
_Avoid_: sync test, snapshot test, Capability test (Shim against callers)

**Combined Messages Pro**:
Messages Pro (Pop-out window, phone, Deep link) listing every Platform's Creators together, each Creator's Platform read from the Creator, while every other surface follows the Platform switch. A send never mixes Platforms (ADR-0057).
_Avoid_: combined window, unified inbox, mixed inbox, all-platforms mode

- **Platform switch** (the sidebar's Platform picker; avoid: platform selector, Platform switches, the per-browser Preferences toggles): `app/components/shell/PlatformSwitcher.tsx`
- **Platform badge** (`PlatformLogo` beside a non-OnlyFans Creator's name on Creator tabs, pickers and the composer; never on Fan rows): ADR-0057
- **Seen-code counter** (per-tick count of unbanked codes actually seen, not a static list): `service/fansly_revenue.py`
- **Platform recipe** (the 11 steps a new Platform takes, owner's action order, Trap list of fields whose names lie): the recipe doc beside `docs/platforms.md`
- **Lacks flags for Fansly money and lifecycle** (`TIP_LEDGER`, `PURCHASE_LINKAGE`; `RENEWAL_STATE`, `LAPSE_DETECTION`, `RETURN_DETECTION`, kept separate so lifting one never opens another; avoid: Lack member, Capability): `service/platforms.py`, `.scratch/multi-platform-p2/issues/05`, `06`
- **Fansly Manager** (the static copy of Fansly's creator UI, owned by the mirror thread on `feat/fansly-mirror`; avoid: OF Manager, mirror on its own): `~/oi-fansly-mirror/.scratch/fansly-manager-mirror/`

### Platform evidence and gates

**Unknown platform**:
A Creator whose stored Platform key is a non-empty string no registry entry has. Dispatch refuses it with `platform_unknown:` and loads no client; a missing key is OnlyFans, never this (ADR-0068).
_Avoid_: fallback Platform, default Platform, OnlyFans (that is a missing key)

**Grade**:
The evidence behind one Platform action as a Provenance and a Coverage, taken from its weakest input: a write whose audience comes from a single-row read is single-row.
_Avoid_: confidence, evidence level, single-row as a Provenance, Triage mark (the triage scorecard's), Matrix status

**Provenance**:
How an action's request was seen: M (a UI click on the wire), W (a body we sent, on the wire), I (inferred) or B (read only from the JS bundle).
_Avoid_: source, bundle-derived as "captured", verified

**Coverage**:
Which cases of an action a capture showed, such as one gift-code row or one earnings type. A case outside it is unobserved, whatever its Provenance.
_Avoid_: sample size, Grade (the pair), Branch (a code path)

**Unseen value**:
A field value no capture showed. It maps to unknown or skip, never to a real bucket: an unmapped Fansly notification code stays `fansly:<n>` and never banks.
_Avoid_: default, other, fallback bucket

**Reversible write**:
A Platform write with a captured undo and no Fan-visible effect, such as list add or rename.
_Avoid_: safe write, Narrowed write (the OF Manager's)

**Fan-facing write**:
A Platform write a Fan can see or that cannot be undone: any send, broadcast, scheduled broadcast, cancel, block, unblock or list delete. A read that changes state is a write.
_Avoid_: irreversible write, dangerous write, Critical control (the OF Manager's)

**Evidence bar**:
The rule that an action's Grade and its kind (read, Reversible write, Fan-facing write, money) decide whether it is built, a Live-check method, Blocked or refused (ADR-0069).
_Avoid_: proof bar (the tests a PR must show), threshold, gate

**Stateful fake**:
The in-memory, no-network Fansly stand-in that answers the captured requests and keeps state, so a test can compare exact request bodies, read back, repeat and undo. It is the only offline proof a write accepts.
_Avoid_: mock, recorder (the gate tests' send override), Nova (the demo FixtureShim, which raises on every non-GET)

**Platform marker**:
One of the Shim's neutral decorators, `platform_unsupported`, `platform_blocked` or `platform_live_check`, that make a method Unsupported, Blocked or a Live-check method (ADR-0068). No marker carries a Platform's name.
_Avoid_: `fansly_unsupported`, `fansly_blocked`, stub, `returns=` success stand-in

**Live-check method**:
A Shim method built from M or W evidence for a Fan-facing write, marked `platform_live_check`, that refuses unless a Live-check grant names its Creator, method and audience. Until its Lift the Drift test counts it as lacking and the parity doc shows it as 🔬.
_Avoid_: pending, beta, half-built, Blocked method (no evidence yet)

**Live-check grant**:
One `<aid>:<method>[:<target id>]` entry in the default-off `PLATFORM_LIVE_CHECK` env var, matched by `side_effect_gate.live_check` at the caller against the exact effective audience: one named Fan, or one list whose Complete read holds only him (ADR-0070).
_Avoid_: grant on its own (Employee grants, Fansly purchase grants), toggle, allowlist, `confirm_live_broadcast` (folded into it)

**Live check**:
The owner's one run of a Live-check method under a Live-check grant through the real Relay route or automation, from his Fansly Creator `founder` to his fan account `fantester`, seen fan side in that browser and Creator side in the persisted row. Its pass is what lifts the method.
_Avoid_: owner check, live test, smoke, Live proof (the OF Manager's), Proof purchase (money)
ASSUMPTION: "Live check" over the plan's "owner check" (11, 14), which names the same run; rung 3 (00's term, ADR-0070). Overturned if the owner keeps two words; then "owner check" is a Live check after deploy.

**Lift**:
Moving a Blocked or Live-check method, a Branch or a Lacks flag to built once its evidence lands, always in its own follow-up PR. A Live-check method's PR 1 builds it off, the owner runs the Live check, PR 2 records the pass and drops the grant requirement.
_Avoid_: unblock (the Shim's `unblock_user`), unlock (the Unlock set), enable, go live

**Lift table**:
The `## Lift table` section of `fansly/FANSLY_PARITY_STATUS.md`: one row per refusal reason, with where it refuses, its Grade, what lifts it, the owner's action and the follow-up PR. `fansly/test_lift_table.py` holds its reasons equal to the Platform markers, Lacks flags and the Verdict table's `gated:` reasons.
_Avoid_: unblock list, gate table, Parity table (Messages Pro's)

**Branch**:
One path through an automation kind or Shim method that gates and the Verdict table judge on its own: unsend's mass and chat sides, a profile push or local write, a broadcast's single include list or its exclusions, a media post. A refused Branch reads `platform_lacks:<method>:<branch>`.
_Avoid_: lane (a **Lane** is a 1:1 automation), path, case (Coverage's)
ASSUMPTION: the Verdict table's third key is a Branch, though issue 12 writes `KIND_VERDICTS[platform][kind][lane]`, because **Lane** is taken (rung 3); overturned if the owner renames Lane, then the code key may stay `lane`.

**Platform refusal**:
A run or route stopped by a Platform gap before any side effect, stored as `skipped` with a `platform_lacks:<lack>[:<branch>]` or `platform_unknown:` reason (a route answers 501). Acceptance reads the persisted run outcome, not the response.
_Avoid_: skip, error, fake success, `audience_unresolved` (persists ok)

**Declared no-op**:
A Branch that legitimately does nothing, such as a disabled rule, an empty audience or no anchor, named with its reason in the Verdict table. A run doing nothing that is neither this nor a Platform refusal is a fake success.
_Avoid_: noop on its own, empty ok, Platform refusal

**Verdict table**:
`KIND_VERDICTS` in `service/tests/test_platform_kind_verdicts.py`: one Verdict per Platform, registered automation kind and Branch, run on the real Shim over the Stateful fake with OnlyFans as control. The parity doc links it, never copies it.
_Avoid_: parity sweep table (stale, lists unregistered kinds), Parity matrix, audit

**Verdict**:
A Verdict table cell: `same` (does what OnlyFans does), `gated:<reason>` (a Platform refusal), `noop:<reason>` (a Declared no-op) or `owner:NN` (a ticket still owns it; final acceptance fails on one).
_Avoid_: status, Grade, Matrix status

**Send refusal**:
The pure caller-side check `send_refusal(platform, payload)` that refuses a payload part the Platform lacks, such as co-performer tags or locked text, before any claim or DM group creation. The Backend's `check_sendable` stays the later backstop.
_Avoid_: `tags_refusal` (folded into it), `check_sendable`, send check (the Backend module's)

**Audience refusal**:
The typed `AudienceRefusal` an audience raises when a list is unknown, not a Complete read, or a built-in the Platform lacks ("following"). It never folds into an empty or unresolved audience.
_Avoid_: `audience_unresolved`, empty audience (a Declared no-op), `AudienceUnknown`

**Complete read**:
A list or roster read the Shim marks complete only on proof: `hasMore:false` on a list page, or distinct active ids equal to `stats.totalActive` on subscribers. A membership-driven write (list delete, sync, cleanup, broadcast) acts only on one.
_Avoid_: short page, full list, Complete Unread list (the Unread list's)

**Native welcome**:
Fansly's own welcome rule (`/message/automated`), which Fansly fires itself and Inflowwww cannot read. With it on, a Fan can get both it and our welcome, so the Fansly welcome editor warns instead of refusing.
_Avoid_: OF welcome (`after_of_welcome`), Fansly welcome, auto-welcome

- **Rules refusal** (`rules_refusal`: smart-list money, renew and return rules refused per row and at `/resolve`), **remove-first capacity** (≤49 members): `.scratch/multi-platform-p2/issues/04`
- **Branch refusal** (`side_effect_gate.branch_refusal` over a method's `platform_blocked_branches`): `.scratch/multi-platform-p2/issues/03`
- **Broadcast branch refusal** (`broadcast_branch_refusal`: only one numeric include list, text only), **Contact-guard intersection** (Complete read of that list ∩ contact-guard exclusions must be empty, else refuse with the count): `.scratch/multi-platform-p2/issues/14`
- **P1–P4** (the four Proof purchases and what each lifts): `.scratch/multi-platform-p2/issues/06`
- **Dummy Platform** (test-only third key that must fail the Drift test and the every-row-has-a-Backend check): `.scratch/multi-platform-p2/issues/09`
- **Triage scorecard**, **Triage mark** (O seen logged out, D public doc, OC owner-confirmed, P pending, U unknown; training knowledge is a note, never a mark; avoid: Grade): `docs/platform-triage.md`

### Cell mode

ASSUMPTION: the agency-scale-out plan's "model" is the glossary's Creator and its "chatter" an Employee holding the chatter role (rung 3, the entries above); overturned if the owner wants "model" in Cell-mode copy.

**Cell mode**:
The optional way to run one Agency's Creators across several Boxes, each Cell a Relay copy with its own SQLite (ADR-0058). It is on only when `OI_CELL_MAP` is set; unset means today's single Box with no new code path. Owner and installer copy say "Cells"; chatters never see the word.
_Avoid_: Ultra (the help bot), fleet mode, shard mode, scale-out, multi-box, split mode

**Cell**:
One Relay copy with its own SQLite holding some of one Agency's Creators (8–15, up to 50 small ones), named by `OI_CELL_ID`. A Cell that is not the Control cell is a data cell.
_Avoid_: shard (fleet.py's whole-Agency copy), node, partition, pod, group (Creator subgroups), team (chatter teams)

**Control cell**:
The one Cell per Agency that owns sign-in and every agency-scope write (Employees, grants, settings, shifts, clock, payroll, Creator reservations) and publishes the Agency copy (ADR-0064). It is never carved.
_Avoid_: control plane, master (the Master role), primary, hub, gateway

**Box**:
One provider VM in Cell mode, running Caddy and 2 Cells (3 once a measured run allows, never 4). One empty spare Box is always kept for Failover.
_Avoid_: server (the Deployment's avoid list), host, VPS, node, shard

**Witness box**:
The small server, on another provider than the Cells, that alone writes Placement and runs every Planned move, Failover and Carve (ADR-0059). It holds fleet.py, `fleet.toml`, the Witness journal, secrets and the fleet SSH key, and never a Cell, database, Creator session or public listener.
_Avoid_: Control cell, Conductor (Release 3's), controller, bastion, arbiter

**Witness journal**:
One append-only file per Planned move, Failover or Carve on the Witness box, one line per step. `resume` re-runs the first step not marked done; past the rollback boundary recovery only goes forward.
_Avoid_: cutover journal, Rollout journal (Script fill's), log, ops file

**Placement**:
The published map of which Cell owns each Creator, keyed `platform:account_id`, with each Cell's Box, Owner epoch and state (live, moving, down). fleet.py renders it as `placement.json` from `fleet.toml` and pushes it to every Box; a Cell takes its own Creators from `OI_ACCOUNTS`, never from Placement.
_Avoid_: cell map (`OI_CELL_MAP` is only the switch), fleet.json, routing table, shard map

**Placement generation**:
The number that goes up by one with every Placement change. A Box refuses a lower one, or the same one with different bytes; rollback means publishing a higher one.
_Avoid_: version, revision (etcd's, Release 3), Owner epoch, Data generation

**Owner epoch**:
The number in the backup bucket saying which Box may run a Cell. A Cell whose own epoch is below it is stale, and a second Box writing the same epoch is refused.
_Avoid_: generation, term, fencing token, `.fenced` marker (it only means a stop was tried)

**Fence**:
Typed, unexpired proof that a Cell's old Box can no longer reach a Platform: a confirmed stop of the VM id in Placement (power fence), or every proxy the Cell can use revoked (proxy fence, unavailable until a drill proves it). No takeover without one; SSH silence is never one (ADR-0063).
_Avoid_: Host fence (promo creates, ADR-0041), shutdown, kill, STONITH, drain

**Egress gate**:
The host firewall block on a Cell's outbound traffic, loaded before docker can start, which `oi-cell-open` lifts only when the bucket's Owner epoch equals the Cell's and names this Box.
_Avoid_: epoch gate (today's fail-open boot check), firewall (alone), egress-closed boot

**Data generation**:
A per-Cell number (`data_gen`) that goes up only on a restore not proven byte-identical. It travels as `X-Cell-Gen`; a write carrying an older one gets 409 and the app re-reads. A Planned move leaves it alone.
_Avoid_: cell gen, Placement generation, Owner epoch

**Owned Creator**:
A Creator listed in a Cell's `OI_ACCOUNTS` env. Pumps, jobs, reads and sends act only on these (`cell_owned()`); anything else gets Not owner.
_Avoid_: local account, cell account, assigned model

**Not owner**:
A Cell's `409 not_owner` answer to any read, write or send for a Creator it does not own, each account inside a bundle included. The app greys that Creator and never retries.
_Avoid_: 404, wrong cell, misroute, empty result

**Creator reservation**:
The Control cell's agency-wide row (`creator_reservations`) holding one Creator id for one Platform and one Cell, taken before any session or proxy file is written; another Cell or Platform gets 409.
_Avoid_: claim (the Send claim), lock, account registry, Placement

**Agency copy**:
The read-only copy of agency-scope tables (people, grants, settings, captions and the like) each data cell pulls from the Control cell, replaced whole per changed section. Write-block triggers refuse any local write to them.
_Avoid_: replica, mirror (the Mirror Employee), sync, agency cache, snapshot (its wire form)

**Grant age**:
How long since the Control cell last confirmed a Cell's Agency copy is current. Past the max grant age (15 min, env knob) the Cell refuses chatter requests and ends their live streams.
_Avoid_: staleness, TTL, lease
ASSUMPTION: past the max, owners and automations keep running (ticket 07) though ticket 08 says the Cell refuses everything, owner API keys included; overturned by the front-door spec.

**Actor token**:
The short-lived (≤15 min) Ed25519-signed `oi_actor` cookie the Control cell mints at sign-in, naming Agency, Employee or owner, impersonation and grant generation. Cells hold only the public key, so they check it and never mint one.
_Avoid_: session cookie, JWT, `SESSION_SECRET` (the rejected shared secret), fleet token (`FLEET_SECRET`)

**Front door**:
Caddy on the Agency's front Boxes, rendered from local Placement, sending each request to its Cell by explicit account (header, query or path), or to the Control cell by allowlist, and answering 400 `account_required` otherwise (ADR-0061). There is no gateway service.
_Avoid_: gateway (the rejected service; also the separate gateway repo), router, load balancer, edge, proxy (OnlyFans proxies)

**Cross-cell read**:
A read that spans Cells (All inbox, stats, sales, payroll), merged from each Cell's answer with every row tagged by account and a `partial` flag naming Cells that did not answer.
_Avoid_: fan-in (`cell_scope.json`'s `fanin` value only; clashes with Fan), aggregate, federated query
ASSUMPTION: "Cross-cell read" over the plan's "fan-in" because Fan is a person here (rung 5); overturned if specs must mirror the JSON value.

**Cell scope**:
`service/cell_scope.json`: one row per route, table, file and job saying who owns it (model, agency, cross-cell, cell-local, public or closed) and why. In Cell mode a route with no row is refused (default closed).
_Avoid_: ownership map (`service/ownership.py` is something else), inventory, allowlist

**Feature table**:
The owner-signed list, built from Cell scope, of every route, job and send kind as works, partial or off in Release 1. Release 1's preflight checks live rules and links against it.
_Avoid_: feature flags, Platform table (Capabilities), scope list

**Send op**:
One intended upstream send, named by its Op ID: sha256 of platform, Creator, send kind, target, Send anchor and part. Every Cell-mode send runs through `send_ops.dispatch()` (ADR-0060).
_Avoid_: op (alone; Witness journal entries are ops too), request id, idempotency key, job, message

**Send anchor**:
The value saved before a send that its Op ID is built from: an app-minted `X-Op-Id`, a stored job UUID, the triggering inbound message id, a rule's original occurrence. A send kind without one is refused in Cell mode.
_Avoid_: key, seed, nonce

**Send claim**:
The `send_ops` row a Cell commits in its own SQLite before the upstream call. One claim allows one wire attempt; if it cannot be written the send is refused, with no fallback.
_Avoid_: Claims (a promo's), lock, reservation (Creator reservation), send marker, inflight guard

**Send tripwire**:
The check in each client send method that, in Cell mode, raises `unclaimed_send` before any network call when no Send claim is in context. Until `dispatch()` exists it refuses every send.
_Avoid_: guard, assert, Side-effect gate (Capabilities)

**Unconfirmed send**:
A Send op whose outcome is unknown (`send_ops` state `uncertain`). It is listed on Unconfirmed sends for a person to mark sent or not sent; automated sends to that Fan wait, and Retry is off in Cell mode.
_Avoid_: uncertain send, outcome unknown, may-have-sent, failed send, Unconfirmed offer (Full AI's)
ASSUMPTION: "Unconfirmed" (house word: `unconfirmed_sends_api.py`, `UnconfirmedSends.tsx`, Unconfirmed offer; rung 3) over the plan's "uncertain"; overturned if specs must name the row state.

**Cell hold**:
A saved row in a Cell's own SQLite (`cell_holds`) that pauses that Cell's automations, or all its writes, across restarts; refused work gets `cell_held`. Three reasons: a lossy restore (per Creator, automations, a person releases it), a Planned move or Entry cut (whole Cell, automations, fleet clears it once live), a Carve (whole Cell, every write, fleet clears it). It copies with the DB.
_Avoid_: restore hold or move pause as separate things, freeze, lock, Hold (the capacity campaign's), Unconfirmed send (one Fan's wait), Send permit (Release 3's pause)

**Planned move**:
Moving one whole Cell to another Box: pause automations, stop, checkpoint, hash a fixed file list, copy Box to Box, verify, start. Lossless, about 90 s grey (g), and the Data generation stays.
_Avoid_: migration, transfer, relocate, Failover, Carve, split

**Failover**:
Bringing a dead Box's Cells back on the spare Box from backup after a confirmed Fence. Lossy by up to the backup lag, so it bumps the Data generation; in Release 1 a paged human starts it with the exact command.
_Avoid_: proxy failover (ADR-0030), Planned move, takeover (its fence-and-promote step), DNS repoint

**Restore manifest**:
The record (v2) tying a Cell's file snapshot to its database restore point: Cell, Owner epoch, Data generation, code SHA, DB position, and a hash for every session, proxy, secret and media file. A mismatch stops the restore.
_Avoid_: backup index, snapshot, manifest v1

**Own data**:
The tables and columns only Inflowwww holds, which no Platform read can rebuild (notes, rules, jobs, runs, claims, attribution). Drills checksum it per Creator.
_Avoid_: user data, local data, app data

**Session-folder quarantine**:
Moving every non-owned Creator's whole `sessions/accounts/<id>/` folder out of a cloned Cell before it boots, so the clone cannot act as that Creator. Removing only `SESSION_FILES` is not enough.
_Avoid_: prune (carve-prune deletes DB rows), session cleanup, `latest.json` removal

**Carve**:
Release 2's cut of one running data cell into two: clone it, apply Session-folder quarantine to each half, bump both Owner epochs (ADR-0062). Never a merge; never the Control cell.
_Avoid_: split (Split Inbox), shard, partition, merge, move

**Entry cut**:
The one-time, stopped, N-way clone of today's single Box into N data cells plus a Control cell, with Session-folder quarantine. One-way: there is no merge back.
_Avoid_: migration, Carve, onboarding, cutover, initial split

**Peak chatters (P)**:
The most Employees active at once on one Agency's Creators in its busiest 15 minutes over 4 weeks (200 until measured). The Go/no-go gate and every load target are multiples of it.
_Avoid_: concurrent users, CCU, load, seats

**Cell budget**:
The chatters at once (C) and inbound DMs per minute (D) one Cell is measured to carry, planned at 70%. A Creator too big for any Cell gets one alone.
_Avoid_: capacity, cell size, quota

**Hot cell**:
A Cell over budget at peak for 3 back-to-back 5-minute windows (CPU, pool waits, slow routes, slow inbox, send or login). In Release 1 the fix is a printed Planned move a human applies.
_Avoid_: overloaded shard, busy cell

**Go/no-go gate**:
Phase 0's measurement that decides whether Cell mode is built: one Relay carrying 200 Creators at 1.25×P in 3 of 3 runs defers it; building needs one Box to miss and two Cells to carry more per Relay.
_Avoid_: calibrate verdict (the fleet ladder's), capacity test

**Release 1, 2, 3**:
Cell mode's owner-facing steps. Release 1: one Agency across Boxes, Planned moves, a paged human for Box death. Release 2: Carve. Release 3: etcd, so Failover runs without waking the owner.
_Avoid_: v1/v2/v3 (alone), phase (the plan's build steps), MP phases (multi-platform's)

**Conductor**:
Release 3's automatic Failover process on the Witness box plus 2 voter Boxes, acting only after its etcd lease expires and a power-off is confirmed.
_Avoid_: Control cell, orchestrator, controller

**Box lease**:
Release 3's etcd lease each Box's lease agent (`oi-lease`) keeps alive (30 s, renewed every 5 s). While it holds, the agent refreshes each of its Cells' Send permits; a Box whose lease is gone and whose probe has failed 2 min may be failed over.
_Avoid_: View lease (a Creator on screen), lease (alone), heartbeat, Grant age

**Send permit**:
Release 3's short-lived local file per Cell (`/run/oi/<cell>/send_permit`, tmpfs, never under `data/`) that says this Box may send now. Missing, unreadable, naming another Box or past `until` (15 s) means paused. Cells read it and never talk to etcd; claims stay Send claims (ADR-0060).
_Avoid_: Send claim, Owner epoch, token, Cell hold

**Sending paused**:
The `writes_paused` (503) refusal a Cell gives fan sends and message writes while its Send permit is not valid. The app shows "Sending paused" with no Retry; automation jobs treat it as not run yet.
_Avoid_: `claim_failed`, `cell_held`, Not owner, outage

- **`OI_CELL_MAP`** (the switch, naming Placement's file), **`OI_CELL_ID`**, **`OI_ACCOUNTS`** (avoid: `FLEET_*`, the installer and one-Agency-per-shard login; `OI_SHARD`): ticket 01, ADR-0059
- **`X-Cell-Gen`** (carries Data generation), **`X-Op-Id`** (app-minted Send anchor), **`X-Account-Id`** (Front door routing key): ADR-0061
- **Grant generation** (bumped when the Agency copy's grants change; live streams re-check it): ADR-0064
- **Readiness** (every Owned Creator's session logs in once through its proxy; `/livez` is liveness only): ticket 03, 10
- **Kill matrix** (every send kind × kill after claim, after accept, after row update; ≤1 accept per Send op, 0 duplicates): ADR-0060
- **Acceptance run** (local 3 data cells + Control cell + Caddy + app + FakeOF + MinIO + power stub, real login, then env unset; avoid: smoke, which is the N/N+1 one): ticket 12
- **N/N+1 rule** (formats only gain fields, readers ship before writers, Control cell upgrades last, `min_cell_proto` in Placement): ticket 12

### Leak tracker

Copy, docs and code in git never name the Removal service's brand, domain or private repos; the brand arrives at runtime (ADR-0074).

**Leak tracker**:
The Creators page `/creators/leaks` and its Relay routes, a thin client that shows each Leak watch's Leaks as read from the Tracker API (ADR-0073). It holds no scraper, host rules or search keys.
_Avoid_: leak scan, leak search (the Quick scan), leak monitor, Leak gate (deploy-all's `leak-check.sh` of a pushed tree)

**Removal service**:
The owner's paid leak-removal business and its server, which runs the Tracker API, every Daily scan and the Notice feed, and alone holds Leak history (ADR-0073).
_Avoid_: the brand name in git, engine, scanner, sidecar, vendor, provider (a `tenant_keys` id)

**Tracker API**:
The Removal service's tenant-scoped `/v1/` API (`me`, creators, leaks, watches) the Relay calls with a Tracker key in a header.
_Avoid_: partner API, the Quick scan's `?key=` (it keeps its query key)

**Quick scan**:
The Removal service's existing one-off public search for a handle, used only to seed a new Leak watch's first Leaks.
_Avoid_: free scan, scan now, Daily scan
ASSUMPTION: "Quick scan" over the plan's "free scan" because "free" reads as price next to the Removal offer (rung 5); overturned if specs must mirror the service's own name.

**Tracker tenant**:
The Removal service's stable record for one Agency (`tenant_id`), which owns that Agency's watches, caps and spend; Tracker keys rotate under it and a revoke ends access without deleting it.
_Avoid_: tenant on its own (Agency and Deployment both avoid it), client (a Removal client), account
ASSUMPTION: the service's `tenant_id` keeps its name only as "Tracker tenant", since Agency's entry avoids "tenant" (rung 3); overturned if the owner wants plain "tenant" for the service side.

**Tracker key**:
An Agency's secret for the Tracker API, in `tenant_keys` under provider `leak_tracker`, outside the LLM provider list, set on an owner-only card. There is no house-key fallback.
_Avoid_: API key, partner key, LLM key, Ingest key

**Tracker gates**:
The four checks every Leak tracker route passes server-side, answering 404 when any fails: the Deployment switch (`LEAK_TRACKER_URL` plus `off_only` `LEAK_TRACKER_ENABLED`), the active Agency's `leak_tracker` flag (never through the `all` merge), a Tracker key, and the Team Leader role.
_Avoid_: feature flag alone, Leak gate, Capability (the Platform table's)

**Leak watch**:
One Agency's tracking of one Creator: the CRM's `leak_watch` row keyed (agency_user_id, account_id) holding its Leak identity, matched by the service's `watch_id` per (Tracker tenant, CRM account).
_Avoid_: watch on its own (Watch check, Watcher), subscription, tracked creator, monitor

**Leak identity**:
What a Leak watch searches for: Platform plus handle (verified from a live session, or typed and unverified), a display name that only confirms, up to 5 manual aliases, and optional Instagram and X.
_Avoid_: profile, S4S profile, search terms

**Paused watch**:
A Leak watch the CRM reports as paused (Agency flag off, Creator toggle off, or account deactivated): no new scans, every row kept, the page still readable. Hitting a cap never pauses one.
_Avoid_: pause reasons (cut), Cell hold, disabled, off

**Leak watch tombstone**:
The `leak_watch_tombstone` row (watch_id, agency_user_id, account_id, tenant_id, requested_at, attempts, last_error) the CRM writes before dropping a Leak watch, which a Relay job retries as `DELETE /v1/watches/{watch_id}` until a 2xx (ADR-0076); an agency-user delete lands them first.
_Avoid_: soft delete, cascade, unlink (the Agency grant's)

**Leak**:
One confirmed URL key (`url_key`) found for one Creator of one Agency, unique per (Agency, Creator, key); two Agencies tracking one Creator have separate Leaks.
_Avoid_: finding, hit (a search result before admission), result, link, Leak gate

**Pending hit**:
A title-only search result waiting on the Leak judge; hidden from the page and never a Leak until judged real.
_Avoid_: unconfirmed Leak, Unconfirmed send (Cell mode's), candidate

**Leak judge**:
The model check that decides whether a Pending hit is the Creator, asking Jev first, then DeepSeek.
_Avoid_: judge on its own, classifier, Jev (one model it asks)

**Leak site**:
The registrable domain a Leak lives on; sibling domains are never merged.
_Avoid_: host, mirror (the OF Manager mirror, Mirror Employee), site on its own (Platform's avoid list), domain

**Leak kind**:
What a Leak's URL is: `page`, `mega`, `telegram`, `file_host` or `media` (a Google image or video, linked to its landing-page Leak). Mega, Telegram and file-host Leaks are link-only and never probed.
_Avoid_: kind on its own (rule and notification kinds), type

**Leak source**:
How a scan found a Leak: `google_web`, `google_images`, `google_videos`, `site_search` or `mega_index`. A Leak keeps every Leak source it was found by.
_Avoid_: source on its own, Leak lane, channel (a Notice's)

**Daily scan**:
One Removal service pass per Leak watch per UTC day: Origin probes, the Mega lookup, the listing recheck and one Google fresh pass.
_Avoid_: check, run, re-check, sweep, baseline (Baseline run), Quick scan

**Weekly slot**:
The one weekday per Leak watch, the least-loaded at enable, for the full Google pass (at most 31 loads) and the registry crawl.
_Avoid_: hash slot, Run slot, S4S slot, weekly scan

**Leak lane**:
One kind of work a Daily scan or Weekly slot does (Origin probe, Mega lookup, listing recheck, Google fresh pass, full Google pass, registry crawl), each with its own last success and next attempt.
_Avoid_: Lane on its own (Full AI Chat's automation), discovery lane (Discovery is S4S's, ADR-0011), Leak source
ASSUMPTION: "Leak lane" over the plan's bare "lane" and "discovery lanes", both already taken (rung 3, the Lane and Discovery entries); overturned if specs need another word.

**Origin probe**:
A plain HTTP fetch of a known Leak's URL that updates its Probe state and, on a change, its Origin status.
_Avoid_: check, ping, recovery probe ladder (an expired session's)

**Probe state**:
The one rolling row per Leak (`probe_state`: last probe time, `last_live_at`, consecutive dead count, last status, `first_dead`, `flaps`, and `dead_since`, the first dead probe of the current dead run) that routine Origin probes overwrite; never part of the Leak event log (ADR-0075).
_Avoid_: probe log, probe history

**Origin status**:
Whether a Leak's URL still serves: `live`, `blocked`, `gone` or `unknown`. `gone` needs a 404, 410 or removal page on 2 Origin probes in a row.
_Avoid_: availability, alive, removed, Blocked method (a Shim's)

**Google visibility**:
Whether the last scan that ran a Leak's query saw it in Google; a query that did not run leaves it unknown, never missing.
_Avoid_: indexed, delisted (only a Notice outcome sets that)

**Leak pill**:
The one state a Leak row shows: Live, Cached (gone at origin, still in Google), Gone, Listed (link-only, still listed) or Not checked yet.
_Avoid_: status (Origin status), badge (Platform badge, Came back), chip

**Came back**:
The event badge on a Leak whose Origin status turned live again after gone; counted apart from New today, never a Leak pill.
_Avoid_: reappeared, regression, relapse

**Leak event log**:
The append-only per-Leak history (`seen`, origin-status change, `google_seen`, `notice`, `notice_outcome`) that every derived date and count is computed from (ADR-0075). `scan_partial` is watch-scoped, so it lives outside it, as an append-only `lane_day` row.
_Avoid_: history table, audit log, Witness journal, probe log

**New today**:
A Leak whose `first_seen_at` falls on today's UTC day, finished scan or not; a Leak watch's first Leaks read "Found on first scan" instead.
_Avoid_: new since yesterday, latest scan, fresh

**Visible Leak**:
A confirmed Leak still live at origin or still in Google.
_Avoid_: active Leak, open Leak, Live promo

**Load reservation**:
The Removal service's atomic hold, taken before each paid call, against the global daily load cap, the Tracker tenant's monthly load allowance and its Creator cap. Over a cap discovery waits and probes run.
_Avoid_: reservation on its own (Creator reservation), budget (Cell budget), quota, Model-call cap

**Notice**:
A removal request filed outside the CRM through one channel (`site`, `host`, `google_dmca`, `google_outdated`), known only from a confirmed send.
_Avoid_: takedown, DMCA (one channel), filing, Fill notice (Script fill's toast)

**Notice outcome**:
A later decision on a Notice, stored as its own event; the only source of Delisted.
_Avoid_: status, result

**Notice feed**:
The daily push of confirmed sends and decisions from the owner's laptop exporter to the Removal service with the Ingest key, replaying every ledger each run (ADR-0077).
_Avoid_: notice sync, import, pull, Notifications panel

**Service status**:
Whether a Creator of an Agency is a Removal client: `none`, `pending`, `active`, `former` or `unknown`, set by the owner in the service and never inferred from Notices.
_Avoid_: client flag, subscription, entitlement, Offer outcome

**Removal track**:
A Creator's Notice side of the page: Gone after notice, Gone with no notice on file, Delisted, and live N days after notice, always as counts.
_Avoid_: removal rate, success rate, pipeline, compliance

**Gone after notice**:
A noticed Leak whose first dead Origin probe came after its first Notice; each Leak counts once.
_Avoid_: removed by us, taken down, gone on its own (the rest are "Gone, no notice on file")

**Delisted**:
A Leak Google dropped by its own decision, known only from an imported Notice outcome; a Google miss never sets it.
_Avoid_: deindexed, missing from Google, Cached

**Removal offer**:
The one drill-in card offering the Removal service's help, shown only to Owner or Admin for Service status `none`, `former` or (with a fresh Notice feed) `unknown`. Its only CTA is "Contact us to start removal", which opens the Start removal popup. Removal is never self-serve: only the service owner's mapping CLI makes a Creator `active`.
_Avoid_: Offer (Full AI Chat's PPV), upsell, pitch, banner, ad

**Start removal popup**:
The dialog the Removal offer's CTA opens: the Removal service's generic captioned video with the Creator's own Leaks drawn over it by the CRM on the service's cue times, the Creator's results as text, a Removal preview, and the contact link as its main button. It starts nothing itself.
_Avoid_: checkout, sign-up, order form, video page

**Removal preview**:
A before/after slider in the Start removal popup: one of the Creator's Visible Leaks as recorded, against a labelled illustration of a removed page. It is always marked "Preview · not removed".
_Avoid_: mockup, simulation, removal result, screenshot

**Taken down gallery**:
Before/after sliders in the Removal area of an `active` or `former` Creator, at most 6, each a Leak that is Gone after notice, dated by its observed gone event and hidden while the feed or read is stale.
_Avoid_: success stories, removals we did, results wall

**Google view**:
The drill-in's grid of a Creator's media Leaks as Google image and video results show them, using Google's own thumbnails passed through at view time, blurred by default, never stored, behind a Deployment switch off by default.
_Avoid_: gallery (that is the Taken down gallery), Google Images tab, screenshot view, image search

**Leak disclaimer**:
The one-time dialog shown the first time a person opens the Leak tracker's results. It says every link is an automated bot scrape that may be wrong, and that the removal team personally checks each leak before any removal. It is dismissed once per person in that browser. Once Google view previews are on, it adds a line saying previews are automated matches that can be explicit or show someone else, and it shows once more.
_Avoid_: warning, terms, consent (that is the enrolment consent attestation), onboarding tour

- **Removal client** (a Creator the Removal service works for), **Removal client mapping** (the owner's two CLI maps, source-tool client → Removal client → Agency + Creator; never by handle), **withheld** (an event of an unlinked or ignored source client: counted, never stored, since Notices for non-clients are not kept): tickets 09, 10
- **Ingest key** (the owner's own key for the Notice feed, never a Tracker key), **stale banner** (shown over counts when the last ingest is over 48 h old): ticket 09
- **Strong alias** (5+ characters, queried alone), **weak alias** (4 characters, only beside the handle): ticket 05
- **Waitlist** (a new Leak watch refused because its projected peak day passes the global cap), **`scan_partial`** (a cap made discovery wait; a watch-scoped `lane_day` row, not a Leak event), **`coverage_reduced`** (the day's Google load failed): ticket 04
- **Today strip** (header counts across Creators, above the All Models view), **Leak roster** (the page's left Creator column, the house `CreatorColumn`: the All Models tag on top, then one entry with a count line per Creator the session can see, tracked or "Not tracked"; a house dropdown on phone; avoid roster alone, Roster count, roster table), **All Models view** (the default main pane: one combined Leak list across Creators with a Creator column; the label is the owner's word here, the scope is still All-Creators scope), **drill-in** (the main pane for one picked Creator, never a side panel or sheet): ticket 08
- **`leak_daily` row** (one agency-bell row per UTC day with news, a dated snapshot, owner only; avoid: digest, alert): ticket 07
- **Demo tracker** (the demo's fixture-only Tracker API, held by a zero-egress test), **consent attestation** (the required checkbox at enable): tickets 03, 10
- **Purge** (30 days after a delete request, Phase 1's daily job; or after a tenant offboard, Phase 4; backups roll off within 30 more): ADR-0076
