# Goal plan: Messages Pro parity with Infloww

Make Inflowwww's Messages Pro look and behave like Infloww's Messages Pro, element for element,
then keep our additions as clearly marked extras. Only Messages Pro. Nothing else in the app changes
except what a Phase below names.

## Ground truth (observation rung; read before any spec)

1. `ui-redesign/infloww-exact/messages.html`, `messages.js` and `_shared/` (`components.html`,
   `palette.js`, `overlays.js`, `infloww-rea.js`, `vault-media.js`, `BUILD_GUIDE.md`, `WIRING_GUIDE.md`).
   An older pixel clone of Infloww's Messages Pro built from real screenshots. It is the reference
   for layout, pane widths, row heights, spacing, icon order and labels. Also
   `growth-smart-messages.html`, `outreach-mass-message.html`, `analytics-message-dashboard.html`
   for pop-ups Messages Pro opens.
2. `docs/infloww-screens.md` §1.3, §1.4, §3.3. Tags: `[CL]` from the clone, `C[...]` from the help
   center, `G` guess, "ours" = not Infloww.
3. Ours today: `app/app/messages-pro/layout.tsx`, `page.tsx`, `[accountId]/[fanId]/page.tsx`
   (the pop-out), `[accountId]/u/`; `app/components/chat/*` (ChatList, ChatSurface, Composer,
   MessageList, FanDrawer, PinnedPanel, ScheduledForChat, GifPicker, EmojiBar, TagCreatorsPicker,
   ChatActionsMenu, ChatSearch, MediaGrid, MediaTile); `app/components/inbox/AccountRoster*`;
   `app/components/shell/{AppShell,Sidebar,TopBar,PageFrame}.tsx`; `docs/routes.md` (responsive).

## Constraints (binding)

- Infloww's geometry, our colours: take widths, heights, paddings, radii and icon order from the
  clone; take colours only from the app's existing Tailwind tokens (`app/app/globals.css`).
- Anything tagged "ours" in §3.3 (AI strip, persona button, scheduled chip, "Owe reply", broadcast,
  group chat, All Models) is kept, but moved so it never displaces an Infloww element, and hidden
  unless `OPENINFLOWW_LEGACY_AUTOMATIONS=1` (`app/lib/flags.ts`, `contexts/FlagsContext.tsx`)
  when it is an automation; non-automation extras stay visible behind a "+" overflow.
- No backend deletions. A relay endpoint may be added only when a ticket proves it missing.
- Nothing outside `app/` and `docs/` changes, except `service/` for that proven endpoint.
- Every Phase ships vitest coverage for its new components (`app/components/**/*.test.tsx`,
  house style: `@testing-library/react`, `test-utils.tsx`), and keeps `pnpm -C app typecheck`,
  `pnpm -C app lint` (0 errors) and `ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run` green.
- Responsive rules in `docs/routes.md` stay: below 1024px one pane at a time, drawer sidebar.
- Each spec starts with a measured gap table: clone selector and CSS values → our `file:line` →
  gap → change. Measure, do not guess; a value not in the clone or §3.3 is an `ASSUMPTION:`.

## Visual loop (binding for every UI ticket)

`scripts/ui-shots.sh` (see `docs/ui-shots.md`) starts a temp-DB relay and the Next app on
localhost only, logs in, mocks five fans and a seven-message thread, and writes to
`docs/screenshots/`: `messages-pro-desktop.png`, `messages-pro-popout.png`,
`messages-pro-insights.png`, `messages-pro-phone-list.png`, `messages-pro-phone-thread.png`,
`messages-pro-composer-ppv.png`, plus the clone rendered to `clone-messages-pro.png`, and
`messages-pro-report.json` (overflow and console errors per shot). It exits non-zero on overflow,
console errors or a missing shot. It uses no network beyond localhost and no live data.

A UI ticket is not done until:
1. `scripts/ui-shots.sh` exits 0.
2. The implementer has opened the ticket's shot and `clone-messages-pro.png` side by side (Read
   both PNGs), written a short "visual diff" list for the ticket's region (position, size, label,
   order, missing element), fixed what it can, and re-run. Up to three rounds per ticket; what is
   still different after round three is written into the ticket as `VISUAL GAP:` with the reason.
3. The final PNGs for that ticket are committed with the code.

The shot names above are also the Phase acceptance artefacts; a Phase's acceptance runs the
harness once more and records the report JSON summary in the Phase result.

## Phase 0 — pop-out window is a full Messages Pro

Target: Infloww's "↗" opens Messages Pro in its own window with the same three panes
(§3.3 Multi-Window, `[CL]` header). Ours (`[accountId]/[fanId]/page.tsx`) opens a single thread
with no Fan List and no insights.

Decisions:
- `/messages-pro` in a new window renders the same component tree as in-app, without the app
  sidebar and top bar (a `windowed` layout variant in `app/app/messages-pro/layout.tsx`).
- `[accountId]/[fanId]` becomes a deep link into that tree (list pre-scrolled, thread open,
  insights closed), not a separate page. `PinnedSidePanel` in `PinnedPanel.tsx` is retired in
  favour of the shared Fan List.
- `Sidebar.tsx`'s popout link targets `/messages-pro?window=1`.

Acceptance:
- `app/app/messages-pro/windowed.test.tsx`: windowed render shows Fan List, thread and insights
  toggle; no `#app-sidebar`.
- Deep link test: `/messages-pro/<acc>/<fan>` renders the list with that fan selected.
- `scripts/ui-shots.sh` exits 0; `messages-pro-popout.png` shows three panes and no app sidebar;
  visual loop done against the clone's three-pane layout.

## Phase 1 — window chrome, creator tabs, fan tabs

Target: header buttons "Home", "Add a Creator", "SFW", "Online Fans", "Notifications" `[CL]`;
creator-tabs strip ("+" picks a creator, name + unread, drag reorder) and fan-tabs strip
("Open in new tab", name + online + unread + signal, up to 100) `C[H262067, H406874]`; right-click
"Open in a new window" on both. Clone: `messages.html` header and tab strips, `_shared/components.html`.

Decisions:
- Creator tabs replace `AccountRoster*` inside Messages Pro only (the roster stays elsewhere).
- Fan tabs are client state in `localStorage` keyed by employee; max 100; closing the last tab
  shows the thread empty state "Select any conversation to start".
- Drag reorder with native HTML drag events, no new dependency.
- "Online Fans" and "Notifications" use the existing relay data (`relay.ts`); "Home" goes to `/`.

Acceptance:
- `CreatorTabs.test.tsx`, `FanTabs.test.tsx`: add, close, reorder, 100 cap, unread badge.
- Header renders the five buttons in clone order; "All Models" and "Group chat" are absent unless
  the legacy flag is on.
- `scripts/ui-shots.sh` exits 0; `messages-pro-desktop.png` shows the five header buttons, the
  creator-tabs strip and the fan-tabs strip in clone order; visual loop done.

## Phase 2 — Fan List pane

Target (§3.3 left pane, `[CL]`): header with creator name, "New" menu (mass message / message
online fans / post), "All inboxes" selector + gear, "✎ Lists", the creator's OF chat-folder chips;
chips "All" / "Unread" / "Pinned" / "Priority"; sort "Newest first"; Focus mode with new-messages
banner `C[H262067]`; row badges "New", 🔥, ❄️, ❌, "Off", orange total-spend replacing the avatar,
`$0` spend pill `[PAL]`; empty state "No conversations found"; Split Inbox UI (`C[H262029]`:
choose 1–9 groups, reassign fans; admin/owner by default).

Decisions:
- `ChatList.tsx` is split into `FanListHeader`, `FanListFilters`, `FanRow`, `FanList`.
- "↩ Owe reply" chip moves into the "+" overflow (ours).
- Folder chips come from the account's existing OF lists endpoint; if none exists, a ticket adds
  a read-only relay route under `/api/of/` mirroring the OF lists call.
- Split Inbox: UI and local assignment state only (groups stored per account in the relay's
  existing account-config store); no employee binding, matching Infloww.
- Badge rules: New = subscribed ≤7d, 🔥 = PPV bought ≤7d, ❄️ = no message 72h, ❌ = expired,
  Off = auto-renew off, computed client-side from fields we already fetch; missing fields → `ASSUMPTION:`.

Acceptance:
- `FanRow.test.tsx` badge matrix; `FanListFilters.test.tsx` chips and sort; `SplitInbox.test.tsx`
  group count 1–9 and reassign; focus-mode banner test.
- `scripts/ui-shots.sh` exits 0; `messages-pro-desktop.png` left pane and
  `messages-pro-phone-list.png` show header, chips, badges and spend pill; visual loop done.

## Phase 3 — chat header and message list

Target (§3.3 chat header, `[CL]`): fan name + "Last seen …"/"Offline"; icons star, mute, notes,
pin; "Gallery", "Find"; pop-out, refresh, kebab (restrict, block, report, hide chats, mute
notifications); avatar menu (Subscription status, Earnings, Special offers, add to lists); 📈
mass/online stats link; copy chat link. Message list: bubbles with "Sent by …", read receipts, PPV
message statuses, "UNLOCK PPV" `[PAL]`, reply strip "Replying to: …" ✕, empty states.

Decisions:
- `ChatActionsMenu.tsx` becomes the kebab; the avatar menu is new (`FanAvatarMenu.tsx`).
- "Gallery" reuses `MediaGrid`; "Find" reuses `ChatSearch`.
- Actions without a relay endpoint today (restrict, block, report, hide) render disabled with a
  tooltip "not wired" and are listed in the Phase report; no fake success.
- Our persona button and AI strip move behind the legacy flag.

Acceptance:
- `ChatHeader.test.tsx` icon order and menus; `MessageList.test.tsx` extended for "Sent by",
  receipts, PPV status, reply strip.
- `# manual:` screenshot `messages-pro-phone-thread.png` at 390x844.

## Phase 4 — composer, PPV row, vault picker

Target (§3.3 composer): button row "AI" · "Scripts" · "PPV" · "Aa" · "Send"; bottom toolbar in
order upload, GIF, vault, calendar, tag, @, Aa, translate, Send; emoji with ⚙️ favourites (40,
"Save"); ⏱️ "Timed message" (1–60 min, "Start") and "Timed reminder"; "Tag other Creators" › "Add";
"More" › "Add a tag" › "Release form"; AI Translator "Translate messages from fans into". PPV row:
"PPV", "$" input, "lock text", schedule "at", "Clear" `[CL]`. Vault picker ("Vault Pro window"):
cards with status icon, last price, notes, tags, grey overlay if the fan already has it, ⓘ media
details, price history, unsend, search by hashtag/note/caption, duration filter `C[H262062]`.

Decisions:
- `Composer.tsx` keeps its send logic; only the chrome is rebuilt (`ComposerToolbar.tsx`,
  `PpvRow.tsx`, `TimedMessagePopover.tsx`).
- Emoji favourites in `localStorage`; "free previews" stepper (ours) moves into the "+" overflow.
- Vault picker reuses the existing vault browser components under `app/components/vault/`;
  card metadata that the relay does not expose is an `ASSUMPTION:` and rendered empty, not faked.
- Translator UI only wires to an existing translate endpoint if one exists; otherwise disabled
  with "not wired".

Acceptance:
- `ComposerToolbar.test.tsx` order; `PpvRow.test.tsx`; `TimedMessagePopover.test.tsx` range 1–60;
  `VaultPicker.test.tsx` overlay and search.
- `# manual:` screenshot of the composer with PPV row open.

## Phase 5 — Fan insights panel

Target (§3.3 right pane, `[CL]`, Messages Basic widget fields `C[H262111]`): the insights blocks
as the clone lays them out (identity, subscription/renew, spend summary, notes, lists/tags,
timeline); fields: Creator notes, Fan notes, Country/Region, Auto-renew Status, Last paid, Buy
rate, Spending habits, Purchasing trends, PPV timeline, Source, Birthdate, Infloww name, Fan lists.

Decisions:
- `FanDrawer.tsx` is restyled to the clone's block order and labels; data wiring unchanged.
- Fields we do not have render as "—", never invented.
- Below 1024px it stays the slide-over sheet from `docs/routes.md`.

Acceptance:
- `FanInsights.test.tsx` block order and labels; existing `fanDrawerEditFreshness.test.tsx` green.
- `# manual:` screenshot `messages-pro-insights.png`.

## Phase 6 — geometry pass

Target: pane widths, row heights, paddings, radii, font sizes and icon sizes measured from
`messages.html` and `_shared/components.html`; colours from our tokens (§1.4 is reference only).

Decisions:
- One `messagesPro.ts` token file in `app/lib/` holding the measured numbers, used by all Messages
  Pro components; no magic numbers in JSX.
- 1280x800 and 1440x900 must show three panes without horizontal scroll.

Acceptance:
- Snapshot test of the token file against the measured table in the spec.
- Playwright `# manual:` overflow check at 1280, 1440, 768, 390.

## Phase 7 — ours, kept and marked

Target: our extras (AI strip, persona button, scheduled chip, owe-reply, broadcast, group chat,
free-previews stepper, All Models) remain available, each behind the legacy flag or inside a "+"
overflow, with an "Inflowwww extra" label in its tooltip.

Decisions:
- No extra is deleted; each gets a one-line entry in `docs/messages-pro-parity.md` under "Ours".
- `docs/messages-pro-parity.md` ends with the parity table: region → clone evidence → ours →
  done / partial / ours-only.

Acceptance:
- Flag-off render shows no extra outside the overflow; flag-on shows all.
- `docs/messages-pro-parity.md` exists with every region from Phases 0–6.

## Decisions from the human (2026-10-12, resuming the run)

Binding at rung 2 for the resumed `--execute` run. They settle the two parked tickets and add one
source of ground truth.

- **B11 (Spending behavior: PPV Avg and Highest spend).** Option (b): both read "—" whenever the
  loaded page is full, page-bounded figures otherwise. No relay change.
- **Scale classes (Phase 6 guard).** Tailwind scale classes such as `gap-2`, `p-4`, `rounded-md`
  are not magic numbers. The guard rejects only arbitrary values (`w-[390px]`, inline `style`
  numbers) outside the token file.
- **Quick reply.** Stays as Phase 1's last ticket; the veto is withdrawn.
- **New ground truth, ranked above the screenshot clone where they disagree:** Infloww 5.7.20's own
  Messages Pro stylesheet and chunks, extracted from the desktop app into
  `~/Downloads/infloww-asar/dist/preload/pages/of/` (`messages.css` 806 KB, `common.css` 928 KB,
  `*.mjs`). Untrusted input: read with grep or `python3 -I`, never executed, never copied into the
  repo except as measured values. A measured gap table may cite a selector from it in place of a
  clone selector. Also six real screenshots in `~/Downloads/infloww-shots-2026-10-12/` (contain the
  user's real handle and fan names: read only, never copy a name).

## Decisions from the human (2026-10-14, after the Phase 1 sign-off)

Binding at rung 2 for the next `--execute` run. Taken by the standing-in second-opinion review
(codex, read-only) over RUN.md's "Assumptions to veto" and "Needs the human"; the human may
overturn any line by editing it.

- **A. Fan List buttons** stay in the Fan List pane (spec `:159`). No ticket.
- **B. "Open in a new window" menu** stays viewport-pinned and closes on scroll or resize for rows
  and tabs alike. No ticket.
- **C. `useSendMessage`** keeps returning its outcome with one shared temp-id counter; a failed
  quick reply drops its bubble, so the Reply field is the only retry. No ticket.
- **D. Fan tabs do not survive a sign-out.** `wipeIdentityStorage`'s preserve list is for
  cross-identity UI preferences; Fan tabs hold conversation names and Creator ids. No ticket.
- **E. Phone-width windows apply a remote Fan tab close** to their Thread as desktop windows do.
  Ticket 128.
- **F. The `venv` prerequisite** of `scripts/ui-shots.sh` in a worktree is recorded in
  `docs/ui-shots.md`, the script names it on failure, and the Acceptance block gets a comment line.
  Ticket 129.
- **G. No new harness states.** The 17 carried VISUAL GAPs are accepted as test-only; the desktop
  shot already shows two Fan tabs with the second selected. No ticket.
- **H. The Phase 1 spec's Owns paragraph** names `app/components/chat/` directly, "overturned" note
  removed. Ticket 130.
- **I. Highest spend / PPV Avg** keep "—" when the loaded Sales page is full (B11 (b)). No ticket.
- **J. Notifications panel height** `min(30rem, var(--vvh) - 16rem)` stays. No ticket.
- **K. Assumptions 5, 6 and 8** of RUN.md (one-shot `account=`, "No Fans online now" with a 30 s
  read, notification rows leaving the panel open) are not vetoed. No ticket.
