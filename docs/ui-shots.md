# UI shots harness

`scripts/ui-shots.sh` renders Messages Pro to PNGs without a live account, and fails
loudly when the screen is broken. Every UI ticket in `docs/plans/messages-pro-parity.md`
runs it (the Visual loop below). Contract: `docs/spec/phase-00-pop-out-window.md`,
Contracts › Harness and Harness: processes / network / fixtures and login / shots / self-test.

## Running

```sh
scripts/ui-shots.sh                        # real run: exit 0 only when every gated shot and flow passes
UI_SHOTS_SELFTEST=1 scripts/ui-shots.sh    # self-test: injects faults and MUST exit non-zero
UI_SHOTS_SWEEP=1 scripts/ui-shots.sh       # overflow sweep only (Sweep below)
```

It takes no arguments. `UI_SHOTS_SELFTEST=1` and `UI_SHOTS_SWEEP=1` are its switches. A run takes about a
minute, most of it `next dev` compiling the route for the first time.

What one run does:

1. Deletes the previous run's PNGs and report under `docs/screenshots/`, so a stale
   file cannot pass.
2. Checks that Playwright's Chromium is already cached. The harness installs nothing.
3. Makes one `mktemp -d` directory and picks free 127.0.0.1 ports.
4. Starts a throwaway relay through `service/_run_ui_safe.py`'s patches with a temp
   SQLite database, `CHATTERLY_TEST_MODE=1`, an empty `SHARE_TOKEN`, fake session and LLM
   secrets, `OPENINFLOWW_LEGACY_AUTOMATIONS` unset, and the secret store redirected into
   the temp directory. Your own `service/secrets/secrets.json` is neither read nor written.
   `dotenv.load_dotenv` and `dotenv.dotenv_values` are no-ops in the relay, so your
   `service/.env` is never loaded either.
   - If `service/secrets.json` exists and `service/secrets/secrets.json` does not, the
     harness exits 3 before starting anything. Importing `service/secrets_store.py` would
     copy the first into the second (`_adopt_legacy_file`) before any redirect can run.
     Move the file into `service/secrets/` (or start your own relay once, which does that),
     then re-run.
5. Starts `next dev --webpack -H 127.0.0.1` from `app/` with `NEXT_DIST_DIR=.next/ui-shots`,
   so a dev server you already run from `app/` (which holds `.next`) does not block it.
6. Waits for the relay's `/health` and the app's root, then drives headless Chromium:
   registers a throwaway owner through `/auth/register`, picks the fixture Employee in
   "Who's chatting?", puts each shot into its state, runs its checks and screenshots it,
   then runs each flow (Flows below).
7. Writes `docs/screenshots/messages-pro-report.json`. A trap stops both servers and
   removes the temp directory on every exit (pass, fail or Ctrl-C). It also restores
   `app/tsconfig.json` and `app/next-env.d.ts` if `next dev` rewrote them, and prints a
   line for each file it restores.

## Prerequisites

- `venv/bin/python` with uvicorn, FastAPI and Playwright (the repo's relay venv).
  Without it the harness exits 3 before it deletes anything under `docs/screenshots/`,
  and its stderr line points here.
- Playwright's Chromium in the local cache (`~/Library/Caches/ms-playwright/` on macOS).
  Without it the harness exits 3 and prints the command to run yourself:
  `venv/bin/python -m playwright install chromium`.
- `app/node_modules` installed (`pnpm -C app install`).
- No network. Nothing leaves the machine:
  - **Browser.** Service workers are blocked and the router denies by default. A request
    to any origin other than the harness's app or relay is aborted and listed in
    `offHostRequests` (Google Fonts are answered locally with an empty 200 and listed
    in `stubbedRequests`). A WebSocket to any other origin is never connected to a server
    and is listed in `offHostRequests` too. A WebSocket on the app or relay origin connects
    only when its path is not relay-bound (the dev server's live reload); one on a
    relay-bound path is never connected and is listed in `unmatchedRequests`. Under the
    router, Chromium runs with `--host-resolver-rules` that resolve no name except
    `localhost`. Of the relay-bound
    paths (`/admin`, `/api`, `/auth`, `/chatter`, `/img`, `/events`, `/ws`, `/health`)
    only `/auth/*` and `/events` reach the temp relay.
    Everything else is answered from fixtures, or with `{}` and listed in
    `unmatchedRequests`. `/api/of/*` never reaches the relay.
  - **Next.** `NEXT_TELEMETRY_DISABLED=1`, `HTTP(S)_PROXY` pointing at a closed loopback
    port, and a `NODE_OPTIONS` preload that makes global `fetch` and
    `http(s).request`/`get` refuse non-loopback hosts and log each refusal.
    - `next/font` downloads Sora through `https.request`, so it is refused, and shots use
      `'Sora Fallback'`. Next compiles the font once and keeps it in the webpack cache under
      `app/.next/ui-shots`, so the refusal is logged only on a run that compiles the font
      again.
  - **Relay.** Before the server is imported, a Python guard refuses non-loopback
    `socket.getaddrinfo`, `gethostbyname(_ex)`, `socket.connect(_ex)` and
    `socket.create_connection`. A name is refused before it is resolved, so no DNS query
    leaves either. The relay runs on the stdlib asyncio loop (`loop="asyncio"`), because
    uvloop resolves and connects through libuv, past these guards.
  - Every connection either server guard refuses is listed in `serverOffHostAttempts`.
    Next's npm version check lands there on every run. Refusal is the enforcement, so
    this list does not gate.

### Worktrees

The harness resolves `venv/bin/python` from the repository root, and a git worktree has no
`venv`. Before a run, from the worktree root, link the main checkout's relay venv:

```sh
ln -s "<main checkout>/venv" venv   # <main checkout> is the path of the repo's main checkout
bash scripts/ui-shots.sh
rm venv                             # remove the link after the run
```

The link is never committed; remove it after the run.

## Fixtures

One Creator "Ella" (account `424242`), one Employee "Sam", five Fans with distinct names
and no avatars (Bella Hart, Chloe Rivers, Dana Brooks, Eva Stone, Faye Monroe; Chloe is
unread), and a seven-message Thread for Bella that mixes Fan and Creator messages and
includes one $15 PPV. They live in the driver embedded in `scripts/ui-shots.sh`; response
shapes follow `app/lib/relay.ts` and the hooks that read them.

The Fans vary in the facts Phase 2's rows show (Phase 2 ticket 55). Every time is relative to
the run's start, so the 7-day and 72-hour windows hold on any day:

| Fan | Row facts | Spend (`/admin/fans/424242/spend-batch`) |
|---|---|---|
| Bella Hart | online | $12,480, active, renews in 20 days |
| Chloe Rivers | unread; a $25 PPV two days ago in the transactions feed (`/api/of/v2/payouts/transactions`, a "Payment for message from " row) | $45, active, renews in 12 days |
| Dana Brooks | subscription expired three days ago, renewal was off | $230 |
| Eva Stone | renewal off ("Set to Expire"), ends in 9 days | a known $0 |
| Faye Monroe | last message four days ago | no spend entry |

Both reads are answered from fixtures; the transactions feed holds only that one row.

Two local reads are fixtured. `/admin/chats/recent` is the app's first-paint
seed (`app/components/chat/ChatList.tsx:279-283`), shown only while `/chats` is pending, so
the app shots' settled state does not change. `/admin/session/status` has no caller left; it goes with
its route. `/admin/accounts/roster-counts` is the app's:
the Creator tab's unread total, counted from the fixture chats by the relay's rule (one unread,
Chloe). Shapes follow `service/server.py`
(`session_status`, `admin_chats_recent`). No fixture Fan is pinned or
priority, so `/api/of/v2/chats?filter=pinned|priority` is empty.

## Shots

| Shot | Viewport | State | Gated checks | Status |
|---|---|---|---|---|
| `messages-pro-desktop` | 1440×900 | `/messages-pro`; the second fixture Fan clicked and "Open in new tab" clicked in the Chat header, then the first fixture Fan clicked and "Open in new tab" clicked again | state reached; `#app-sidebar` in the DOM but hidden, and "Toggle sidebar" has `aria-controls="app-sidebar-drawer"` and `aria-expanded="false"` (the in-app sidebar is the drawer, spec D3); the five Fan names visible; exactly one element on the page has `aria-current="true"`, and it is the clicked row (holds Bella Hart); seven messages in the Thread; the $15 PPV visible in the Thread (its bubble visible, and a `$15.00` price visible on the page); the Fan insights pane (complementary landmark "Fan insights") visible, naming Bella Hart; Row badges: only Eva Stone's row shows "Off", only Chloe Rivers's row shows 🔥 (the img "Bought a PPV within 7 days", from the fixture's "Payment for message from " row in the transactions feed), only Faye Monroe's row shows ❄️ (the img "No message for over 72 hours"), and only Dana Brooks's row shows the expired ✕ avatar (the img "Subscription expired"), each waiting up to 30s for its element because spend, status and Fan activity load after the Fan List's deferred delay; the spend display, waiting the same way: only Bella Hart's row shows the orange figure "$12.5k" (her $12,480 in place of the avatar), only Dana Brooks's row shows a "$230" pill, in the slot of her ✕ avatar, and only Eva Stone's row shows a "$0" pill, and then Faye Monroe's row, with no spend entry, shows no spend pill; Fan tabs: the tablist "Fan tabs strip" holds two tabs, Chloe Rivers then Bella Hart, and only the second is `aria-selected="true"`; the Chat header (the `<header>` holding the "Fan insights" toggle) shows Bella Hart and "Available now" (her chat row says she is online), and the element holding "Available now" and its parent are each at least as wide as their content (`scrollWidth <= clientWidth`), so a presence line cut to "Available …" fails; the Chat header's icon row names Priority, Mute notifications, Notes, Pinned chat, Gallery and Find, in that order (buttons in that header by exact accessible name, each found once and visible, each after the one before it in the DOM); the Chat header's right group names Open in new tab, Refresh, Fan insights and More actions, in that order, after the name (buttons in that header by exact accessible name, each found once and visible, the first after the button titled "Avatar menu" and each after the one before it in the DOM); the Chat header is two lines and line 2 follows the presence line (that header's box 52px tall, 1px; Priority's drawn icon's left edge 0 to 24px right of the "Available now" text's right edge; the drawn icons of Priority, Gallery and Find each starting at or below the bottom of Bella Hart's name (a line-2 button is measured by its icon, since its 24px target's padding draws nothing); Open in new tab, Refresh and More actions inside the header with vertical centres at most 1px apart; the height, the gap and the centres are recorded); no 'Inflowwww extras' or 'Message statistics' button in the Chat header, and no translate toggle (no button in that header by either exact accessible name, and no text matching 🌐 or "translate" anywhere in it); no Persona button and no AI strip in the Chat header (the run leaves the Legacy flag off, so that header holds no button named exactly "Persona" and no note named "AI status"); the first fixture message's time sits under its bubble (the `<time>` whose `datetime` is that message's `createdAt`, in the `data-time-row` that is the bubble box's next sibling, has a bounding box starting at or below the bottom of the box carrying its `data-msg-id` and lying within the bubble's column; the row's gap under the bubble and its font size are recorded, with the bubble's computed radii, padding, font size and line height and the gap from its line to the next line); an outgoing fixture bubble shows a receipt named 'Delivered' in its column (the first Creator message's bubble column, the parent of its `data-msg-id` box, holds one visible element with `aria-label="Delivered"` reading "✓"; the fixture chat rows carry no `lastReadMessageId`, so no bubble is Seen); the fixture PPV reads '· not paid' once, inside its card (the column holding the $15 PPV's bubble holds exactly one element reading "$15.00 · not paid", and it is a visible element inside the bubble, its last line as the old Infloww overlay's `.ppv-mini .paid-tag`: the fixture PPV is ours, `isOpened` false and no `isPaid`, so it is not paid); the fixture PPV shows no 'UNLOCK FOR' bar (no element in that column contains "UNLOCK FOR": that bar is the Fan's view, not the Creator's); the first incoming bubble's Message actions show on hover only (the pointer moved to 0,0, the `role="group"` named "Message actions" in the first Fan message's bubble line has computed opacity 0; with the bubble hovered it is 1, its buttons' `aria-label`s are Pin, Reply, Like and Translate in that order, and each button's box lies within the visible `[data-mp-pane="thread"]` root's box; the first drawn glyph's gap after the bubble, the glyph pitch, the box widths and the row's vertical offset from the bubble's centre are recorded); the first incoming bubble's Message actions show on focus (the pointer moved away and that row's Pin focused: opacity 1; blurred again: opacity 0; the list's scroll is restored, so the shot shows no row); every run's last bubble has its avatar (a run ends where the next fixture message is on the other side or in another minute, so with the fixture's alternating sides every message ends one: each bubble line, the flex row two levels above its `data-msg-id` box, holds exactly one `data-msg-avatar` child, `fan` as its first child on the Fan's lines and `creator` as its last on ours; the first slot of each side's box, its gap from the bubble and its bottom's offset from the bubble's are recorded); a Date separator sits above the first fixture message (the element just before that message's bubble line has `role="separator"`, an `aria-label` and label text reading "Today", or the short month and day when the fixture spans midnight, computed in the page from the message's `createdAt`, and its box ends at or above the bubble's top); the Date separator label is not uppercase (that separator's label `span` has computed `text-transform: none`; its font size is recorded); the pane row (below): one visible `[data-mp-pane]` root each for `fan-list`, `thread` and `insights`, the Fan List 390px and Fan insights 280px wide (0.5px), side by side in that order with tops level (1px); the Chat header's 'More actions' kebab sits inside the thread pane's box (its box wholly within the visible `[data-mp-pane="thread"]` root's box, no tolerance; below); CO1–CO7 match the Colour inventory (one opaque computed-colour sample per colour Compare row, a translucent colour reading as no match, each check named with its row ID and the inventory's Infloww value: CO1 the Online Fans button's fill #4166f6; CO2 our first free bubble #4166f6; CO3 the Fan's first bubble #262626; CO4 the PPV bubble #232323, its outline #2f2f2f and its "not paid" line #8a8a8a; CO5 the Window header #0d0d0d, the Fan tabs row #2b2c30, the Fan List root #151515, the Thread surface #151515, the Fan insights pane #0d0d0d and the selected Fan row #353535; CO6 the selected row's bottom border #444444; CO7 Bella Hart's name #d9d9d9 and her preview #999999); same colours under data-theme=light (the page's `html` gets `data-theme="light"`, the same samples are re-read and must be equal, Messages Pro's `color-scheme` is read as dark while the attribute is still set, then the attribute is restored); App accent outside Messages Pro ("Toggle sidebar" opens `#app-sidebar-drawer`, whose active link, or the drawer when none is active, resolves `--color-accent` to the App accent #8b5cf6; Escape closes it before the screenshot) | built (ticket 03), landmark name (ticket 07), selected row (ticket 09), Row badges (Phase 2 ticket 55), 🔥 (Phase 2 ticket 56), spend display (Phase 2 ticket 57), Fan tabs (Phase 1 ticket 70), Chat header name and presence (Phase 3 ticket 85), Chat header icon row (Phase 3 tickets 86, 87, 88), Chat header right group (Phase 3 tickets 90, 91), two-line Chat header (look-and-feel ticket 141), Chat header Extras overflow (Phase 3 ticket 92), Legacy flag off in the Chat header (Phase 3 ticket 93), time under the bubble (Phase 3 ticket 97, moved by look-and-feel ticket 146), receipt in the bubble's column (Phase 3 ticket 98, look-and-feel ticket 146), PPV status line (Phase 3 ticket 99; moved into the card and the unlock bar removed after look-and-feel), Bubble action row on hover and focus (look-and-feel ticket 143), run avatars and the Date separator (look-and-feel ticket 144), pane row (Phase 6 ticket 106), sidebar as the drawer (Phase 6 ticket 107), kebab inside the Thread (Phase 6 ticket 108), Infloww palette CO1–CO7, light theme and App accent (look-and-feel ticket 133) |
| `messages-pro-popout` | 1440×900 | `/messages-pro?window=1`, first fixture Fan clicked | state reached; no `#app-sidebar` and no "Toggle sidebar" button in the DOM; the five Fan names visible; seven messages in the Thread; the Fan insights pane (complementary landmark "Fan insights") visible, naming Bella Hart; the Fan List, Thread and Fan insights panes each end within 1px of the viewport's bottom edge and sit inside it horizontally; the pane row (below): one visible `[data-mp-pane]` root each for `fan-list`, `thread` and `insights`, the Fan List 390px and Fan insights 280px wide (0.5px), side by side in that order with tops level (1px); the Chat header's 'More actions' kebab sits inside the thread pane's box (its box wholly within the visible `[data-mp-pane="thread"]` root's box, no tolerance; below) | built (ticket 01), chrome and height checks (ticket 05), landmark name (ticket 07), pane row (Phase 6 ticket 106), kebab inside the Thread (Phase 6 ticket 108) |
| `messages-pro-insights` | 1440×900 | `/messages-pro`, first fixture Fan clicked (no Fan tabs); the PNG is an element shot (`locator.screenshot()`) of the visible Fan insights pane (complementary landmark "Fan insights") only | state reached; the Fan insights pane visible, naming Bella Hart | built (ticket 03), landmark name (ticket 07) |
| `messages-pro-phone-list` | 390×844 | `/messages-pro`, nothing selected | state reached; the five Fan names visible; no Thread visible (no message bubble and no "Back to chat list") | built (ticket 03) |
| `messages-pro-phone-thread` | 390×844 | `/messages-pro`, first fixture Fan clicked | state reached; seven messages in the Thread; "Back to chat list" visible (the Chat header's back button, by its title); the Fan List not visible (none of the other four Fan names visible); 'Back to chat list' and 'Fan insights' are visible, and 'Open in new tab' and 'Refresh' are not (buttons in the Chat header by exact accessible name; the overflow gate already checks that nothing scrolls sideways); the Chat header is two lines on a phone (Priority's drawn icon starting at or below the bottom of Bella Hart's name, Find's icon's vertical centre within 1px of Priority's, and the header's `scrollWidth <= clientWidth`; its height is recorded); an incoming bubble's Message actions show with no hover (the last Fan message's "Message actions" group has computed opacity 1 and its box lies within x 0 to 390; its button names are recorded); the phone Message actions buttons are at least 24px (each of that group's buttons' boxes at least 24×24; the sizes are recorded) | built (ticket 03), phone Chat header (Phase 3 ticket 90), two-line Chat header (look-and-feel ticket 141), Bubble action row with no hover (look-and-feel ticket 143) |
| `messages-pro-composer-ppv` | 1440×900 | `/messages-pro`, first fixture Fan clicked (no Fan tabs), then the Composer's "PPV" pill clicked (which opens the PPV row) and `25` typed into its "PPV price" control | state reached; exactly one visible "PPV price" control, holding `25`; the Composer (`[data-composer-area]`) inside the viewport (1px tolerance); row 1 is 44px (the Composer's "Composer buttons" toolbar box 44px tall, 1px, its rule included); Send is 32px (the Composer's "Send" button box 32px tall, 1px); Send 16px above Composer bottom (the Composer box's bottom less Send's, 16px within 2px); PPV row between input and toolbar (the "PPV row" group's top at or below the input's bottom and its bottom at or above the "Composer toolbar" top, 1px tolerance); each measured value is recorded | built (ticket 03), the three-row Composer (look-and-feel ticket 147), the PPV row between rows 2 and 3 (look-and-feel ticket 148) |

Phone shots set only the 390×844 viewport (no device emulation): the app's one-pane
layout below lg is CSS breakpoints only (`app/app/messages-pro/page.tsx`). "Visible" is
Playwright's `is_visible()`: rendered with a non-empty box, not necessarily scrolled into
the viewport.

A pane, for the height check, is the topmost ancestor of its anchor that holds no other
pane's anchor, so the check reads no class names. The anchors are the last Fan's name
(Faye Monroe, shown only in the Fan List), the Composer (`[data-composer-area]`, the
Thread's bottom row) and the Fan insights pane.

The pane row check (desktop and popout shots, Phase 6 ticket 106) finds the three panes by the
`data-mp-pane` marker on each pane root (`fan-list`, `thread`, `insights`; the Thread empty state
carries `thread` too), not by class names, and measures their boxes: the widths are the token
module's `MP.panes` (Gap rows PN2 and PN4).

The kebab check (desktop and popout shots, Phase 6 ticket 108) reads the same `thread` box and
the Chat header's button named exactly "More actions", and fails unless the button's box lies
wholly inside the Thread's, with no tolerance. Both shots have Fan insights open, so the Thread is
770px, below Gap row CH14's 886px: the header shows "Gallery", "Find" and "Open in new tab" as
icons (`MP.chatHeader.labelText`) and must fit. The check records `kebabRight` and `threadRight`
in the report.

The desktop, popout and insights shots find the Fan insights pane by its landmark: the
visible complementary region named "Fan insights" (one locator, `insights_pane`). The
slide-over below lg is a dialog of the same name and never matches it. "Naming Bella Hart"
means the pane's Nickname field (the textbox whose label holds "nickname") has Bella Hart as
its value or placeholder: the Fan's identity block sits in the collapsed Extras overflow
(Phase 5 ticket 16), and the shot keeps that overflow collapsed.

The desktop shot reads the selected Fan's row by its `aria-current="true"` marker, the
contract Phase 2 keeps when it rebuilds the Fan List (the sidebar's `aria-current="page"`
never matches). The desktop shot opens its two Fan tabs through the real Chat header, so a
missing "Open in new tab" fails its `state reached`. It opens the first fixture Fan last, so
that Fan's conversation is the open one and the checks that read Bella Hart stand; only the
desktop shot opens Fan tabs. Later Phase 0 tickets add the spec's remaining checks in the change that
builds each behaviour. A step that cannot reach its state fails that shot's
`state reached` check and the run goes on, so the report still lists every shot.

## Flows

A flow is a gated browser sequence with no PNG: steps and checks in order, in one page. It
gates like a shot (no console error, no off-host request, at least one check and all ok);
it has no file and no `overflowX`. A step that cannot reach its state adds a failed
`<step> reached` check and ends that flow; the run goes on.

| Flow | Viewport | Sequence (each check gates) | Status |
|---|---|---|---|
| `phone-popout` | 390×844 | `/messages-pro?window=1`: no `#app-sidebar` and no "Toggle sidebar" button in the DOM; the five Fan names visible. Tap the first Fan: seven messages visible, and the Thread pane ends within 1px of the viewport's bottom edge. Tap "Fan insights": the slide-over (dialog "Fan insights") is visible. Its "Close": the slide-over is gone, and seven messages visible. "Back to chat list": the five Fan names visible, and no Thread visible (no message bubble, no "Back to chat list") | built (ticket 05) |
| `phone-composer-overflow` | 390×844 | `/messages-pro`, the Employee picked and the first Fan tapped. Row 1 on one line (every visible button in the Composer's "Composer buttons" toolbar shares one top, 1px, at least seven of them); row 1 in viewport (each of those boxes within x 0 to 390). The "+" overflow is gone (TODO.md A2, d90e424f), so its items are checked where they moved: quick emojis after ⚙ (the "Quick emojis" group's first button starts at or after ⚙'s right edge, centres within 1px) and quick emojis in viewport (the group's box within x 0 to 390); ⏱ ("Timed message"): ⏱ panel in viewport (its region's box within x 0 to 390 and y ≥ 0, 1px) and Send at presets in ⏱ (its "Send at presets" group holds +5m, +10m, +15m, +30m, +60m, each within x 0 to 390), then ⏱ again closes it; free previews show inline in the PPV row only with media attached, which the flow has no fixture for, so they are unchecked. ⚙ ("Emoji favourites"): ⚙ panel in viewport, the same way, then closed. The "PPV" pill: PPV row in viewport (the "PPV row" group's box within x 0 to 390 and its scrollWidth ≤ clientWidth); Send unmoved by PPV (Send's box within 1px of its box before the toggle), then "PPV" again. "Fan insights": slide-over in viewport (the dialog's box within x 0 to 390); slide-over no overflow (neither the dialog nor a card's sideways-clipping ancestor has scrollWidth > clientWidth); slide-over padding visible (each visible card, `section[aria-labelledby]`, ends at least the padding-right of its ancestors up to the dialog inside the dialog's right edge, 0.5px); then its "Close". Each measured value is recorded | built (look-and-feel ticket 149, Compare CP6 and CP7) |
| `desktop-edit-name` | 1440×900 | `/messages-pro`, the `messages-pro-desktop` state's steps (the second fixture Fan and "Open in new tab", then the first fixture Fan and "Open in new tab"): the Fan insights pane visible, naming Bella Hart. The Chat header's "Fan insights" toggle: no visible `[data-mp-pane="insights"]` root. The Chat header's "Edit name" pencil (button by exact accessible name): a visible `[data-mp-pane="insights"]` root again, and `document.activeElement` is a visible `input` inside it whose label reads "Nickname" (waiting up to 10s) | built (look-and-feel ticket 142, Compare CH1) |

## Report

`docs/screenshots/messages-pro-report.json`, fixed shape:

```json
{ "ok": true, "startedAt": 1791770000,
  "shots": [ { "name": "messages-pro-popout", "file": "docs/screenshots/messages-pro-popout.png",
               "url": "/messages-pro?window=1", "viewport": [1440, 900], "gated": true,
               "overflowX": false, "consoleErrors": [], "offHostRequests": [],
               "stubbedRequests": [], "unmatchedRequests": [],
               "checks": [ { "name": "Thread shows 7 messages", "ok": true } ] } ],
  "flows": [ { "name": "phone-popout", "url": "/messages-pro?window=1", "viewport": [390, 844],
               "gated": true, "consoleErrors": [], "offHostRequests": [],
               "checks": [ { "name": "no Thread visible", "ok": true } ] } ],
  "serverOffHostAttempts": [ { "process": "next", "via": "fetch",
                               "target": "https://registry.npmjs.org/-/package/next/dist-tags",
                               "refused": true } ] }
```

- `startedAt`: Unix seconds when the run began. Every PNG's mtime must be at or after it.
- `overflowX`: `document.documentElement.scrollWidth > innerWidth`.
- `consoleErrors`: console messages of type `error` plus uncaught page errors. No allowlist.
- `unmatchedRequests`: recorded, not gated. A shot's content is proven by its checks.
- `flows`: browser flows with no PNG (Flows above). A flow record has no `file`, no
  `overflowX`, and no `stubbedRequests` or `unmatchedRequests`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every gated shot and flow passed: for a shot, PNG present, non-empty and fresh and no overflow; for both, no console error, no off-host request, at least one check and all ok |
| 1 | A gate failed. The report and the printed summary say which |
| 2 | Usage: the script was given arguments |
| 3 | A prerequisite is missing or unsafe: `venv/bin/python`, Chromium (install command printed), or a legacy `service/secrets.json` that the relay would adopt |
| 4 | The relay or `next dev` did not start in time; the last log lines are printed |
| 130 / 143 | Interrupted (Ctrl-C / SIGTERM); servers stopped, temp directory removed |

## Sweep

`UI_SHOTS_SWEEP=1 scripts/ui-shots.sh` (Phase 6 ticket 109, `docs/spec/phase-06-geometry-pass.md` D5) runs
only the overflow sweep on the same stack, fixtures and request blocking, and leaves the default run's
PNGs and report alone. It makes eight runs, `inapp-` (`/messages-pro`) and `window-`
(`/messages-pro?window=1`), each at 1440×900, 1280×800, 768×1024 and 390×844. Each run clicks the first
Fan row and waits for the Composer's textbox, then checks:
(a) no sideways page scroll;
(b) under `main`, no element at least half the viewport tall is wider inside than out (1px), and every
visible button and textbox in a `[data-mp-pane]` root lies inside that pane (1px), where a scroller
inside the pane exempts only the axis it really scrolls on (its content larger than its box);
(c) from 1024px up, the three panes visible, side by side in order with tops level and each at least
half the viewport tall, with Fan insights opened first if it was closed;
(d) below 1024px, exactly one of the Fan List and the Thread visible;
(e) no console error and no off-host request;
(f) from 1024px up, (a) and (b) again with Fan insights closed;
(g) at 1440, the word "Gallery" visible with Fan insights closed and with it open, both Threads wider
than the 448px word fold (Compare CH3, messages-pro-look-and-feel ticket 141; it was Gap row CH14's
886px fold, which hid the word with Fan insights open);
(h) in `inapp-1280`, with the Chat header's Fan name set to 60 characters in the page, (b) again, and the
name ends in an ellipsis with the name's and presence line's painted text starting inside the "Avatar menu"
button, the presence text ending before Priority's drawn icon and the name before the right group.
It writes `docs/screenshots/messages-pro-sweep.json` (`{ok, runs: [{name, url, viewport, file,
overflowX, wide, panes, consoleErrors, offHostRequests, failures, ok}]}`; `panes` is `three`, `one` or
`bad`), plus `messages-pro-1280.png` and `messages-pro-768.png` from those in-app runs (Fan insights open
at 1280), and exits 1 unless every run is ok. `OPENINFLOWW_LEGACY_AUTOMATIONS=1` reaches `next dev`, so
the same command with it set runs the sweep with the Legacy flag on (the Persona button
shows). The flag-on run is a check only: the committed outputs come from the flag-off run. In sweep mode
only, the error badge's `/admin/errors` read is answered with one synthetic error, so the flag-on run measures
the Window header with the inline error badge shown (it hides at zero).

## Self-test

`UI_SHOTS_SELFTEST=1` adds an init script to the popout shot that logs one
`console.error`, appends a 2000px-wide element and opens a WebSocket to an off-host
origin. That run must exit non-zero, and its report must show `ok: false`,
`overflowX: true`, the injected error and the WebSocket in `offHostRequests` on
`messages-pro-popout`. Run it once before the real run whenever the gate logic changes;
the real run then replaces its outputs.

## Visual loop

Binding for every UI ticket (`docs/plans/messages-pro-parity.md`, "Visual loop"):

1. Run `scripts/ui-shots.sh` until it exits 0.
2. Read the ticket's shot and the matching Infloww capture side by side.
   Write a short visual diff list for the ticket's region (position, size, label, order,
   missing element), fix what you can, and re-run.
3. Up to three rounds. Whatever still differs after round three goes into the ticket as a
   `VISUAL GAP:` line with the reason and the owning Phase.
4. Commit the final PNGs and the report with the code.
