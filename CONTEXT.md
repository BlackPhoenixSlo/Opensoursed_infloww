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
The Lane ownership rule that no Lane replies to a Fan for a while (default 1 h) after a human's 1:1 outbound; an outbound of unknown sender counts as human. OF-app yield feeds it from a live one-Fan read just before a send.
_Avoid_: takeover, human window, pause

**Top spend limit**:
The lifetime spend at or above which Full AI Chat stops replying to a Fan and leaves him to humans; with the per-Creator exclude list, the only exit from Full AI Chat besides its switches (owner D8).
_Avoid_: whale gate, whale cap

**Stand-down**:
The other Lanes skipping a Treatment fan whom Full AI Chat owns in live Mode: W7's `_classify`, Get to know fans (at decide and before each bubble) and Auto-reply. Holdout fans and Shadow mode stand nothing down, and funnel code never changes (ADR-0036).
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

**Route**:
What one Turn does: chat, sext, sell_now, tease, make_right, ai_dare or no_send. A tease (on price or a decline, which never blocks selling) teases now so his next Turn sells; with selling off it is chat.
_Avoid_: action (the FM off-script gate's per-reason action, ADR-0026), intent, Mode, Lane

**Route table**:
The pure first-match map from Router question answers and the Pending tease to a Route (`full_ai_decide.decide_turn`), holding no rule beyond them (ADR-0032).
_Avoid_: decide table (`_fm_relevance`'s, ADR-0026), decision table, router rules

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
The Sell executor's media for one Offer or Free item: one clip, or up to four photos from one shoot plus at most one free preview, none of them Owned media.
_Avoid_: bundle, pack

**Owned media**:
Media a Fan has bought, by any join source, or received as a Free item. It is never offered to him again; unbought media may be re-offered (owner D13).
_Avoid_: seen media (also counts sent but unbought; the Free item's pool excludes it), was_purchased (`vault_sends`')

**Free item**:
The one unseen vault item, price 0 and matched to what he wants, that a Make-it-right Turn sends. It is uncapped (ADR-0032) and becomes Owned media.
_Avoid_: gift, freebie, preview (the free photo beside an Offer), Free previews (the PPV row's)

**Claim audit**:
The check that a sell or Free item bubble's exact final text claims only what its Pick holds (count, kind, and subject words by a strict lexicon). A failure regenerates once, then sends a fallback caption built only from the Pick's counts and kinds.
_Avoid_: caption check, pack_claim (the old fastt check), word filter (`_wordfilter`)

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
A Fan's one `ai_enrolments` row, written at his first eligible inbound in live mode with selling on, on a Full AI Chat Creator (Shadow and the selling-off stage enrol no one, R8), and fixing his Arm for good (ADR-0035).
_Avoid_: enrollment (OF list enrollment, a **Functional demand**), assignment

**Arm**:
A Fan's side of the fixed Fan-hash split, on every Decision row and fixed for good by his Enrolment: treatment (about 80 %; Full AI Chat owns him) or holdout (about 20 %; today's Lanes, unchanged). A Treatment fan or Holdout fan is a Fan in that Arm.
_Avoid_: control group, slice (the **Shadow slice** is a systemd slice), bucket, cohort

**Revenue per enrolled fan**:
Net revenue from every source over 14 days per Enrolment, treatment Arm against holdout Arm: Full AI Chat's win measure (ADR-0035).
_Avoid_: **Total spend** (the Fan List's per-Fan figure), buy rate (a per-Route reading of router quality), conversion rate, LTV

**Rollout stage**:
One of S0 (offline replay) to S6 (sext) through which a Creator's Full AI Chat moves; only the owner flips one forward, after its checks pass.
_Avoid_: **Stage** (a Capacity campaign ladder step), phase (a plan's PR slice), **Gate** (the Capacity campaign's G1–G13)
ASSUMPTION: named "Rollout stage" so the Capacity campaign's Stage keeps one meaning; overturned if the specs say S0–S6 only.
