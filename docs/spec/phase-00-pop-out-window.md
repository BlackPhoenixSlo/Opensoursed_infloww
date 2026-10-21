# Phase 00 — Pop-out window is a full Messages Pro

**Objective.** The sidebar's "↗" (`/messages-pro?window=1`) and every Deep link (`/messages-pro/<accountId>/<fanId>`) render the one Messages Pro tree (Fan List, Thread, Fan insights), and the Pop-out window shows it without the app sidebar or top bar. `scripts/ui-shots.sh` renders that screen next to the Clone, so this ticket and every later UI ticket can run the Visual loop.

## Gap table

Measured at `3542606` from the Clone (`ui-redesign/infloww-exact/messages.html`, `messages.js`) and from `docs/infloww-screens.md` §1.1 and §3.3. Phase 0 changes which panes and chrome exist. It changes no Geometry numbers. Numbers that a later Phase owns are listed anyway, so the Visual loop knows which gaps to expect, and the Change column names the owning Phase.

| # | Clone selector and CSS value | Ours (`file:line`) | Gap | Change in Phase 0 |
|---|---|---|---|---|
| 1 | Window: `.app{display:flex;flex-direction:column;height:100vh;width:100vw;overflow:hidden}` (`messages.html:47`). Multi-Window opens "another window" of Messages Pro (§3.3 C[H545992]; §1.1 row 4) | Every route, the one-Fan page included, renders inside `AppShell` (`app/app/layout.tsx:167`, `AppShell.tsx:46-58`): top bar `h-14` = 56px (`TopBar.tsx:54`), sidebar `w-[252px]` (`Sidebar.tsx:106`). Panes are sized by `.h-chat` = `calc(var(--vvh) - 3.5rem)` (`globals.css:187`) | A popped-out window gives up 56px of height and 252px of width to app chrome that the Clone's window does not have | `?window=1` drops the top bar, the sidebar and the menu drawer, and the panes take the full viewport height |
| 2 | Pop-out content: `body.ft-popout .topstrip,body.ft-popout .hometabs,body.ft-popout .list,body.ft-popout .thread-tabs{display:none!important}` (`messages.html:85`), so the Clone pops out one Thread. Infloww opens a full Messages Pro (§3.3 Multi-Window, C[H545992]) | `[accountId]/[fanId]/page.tsx:205-222` renders only `ChatSurface`, with `forceDrawerOpen` and `forcePinnedPanelOpen` (`:218-219`): the Thread, Fan insights pinned open and not closable, and a pinned-messages column. The plan's "no insights" (Phase 0 Target) is wrong by observation | The pop-out has no Fan List, so the Employee cannot reach another Fan | The Deep link renders the full tree. This follows Infloww over the Clone (ADR-0002) |
| 3 | Panes: `.body{flex:1;display:flex;min-height:0}` (`messages.html:113`); `.list{width:390px;min-width:390px}` (`:116`); `.center{flex:1;…min-width:0}` (`:193`); `.right{width:280px;min-width:280px}` (`:292`) | `page.tsx:189` grid `lg:grid-cols-[var(--roster-w)_320px_minmax(0,1fr)]`, with the roster at 44px or 260px (`page.tsx:29-30`); pinned insights `w-[360px]` (`FanDrawer.tsx:332`) | The list is 320px against 390px, insights are 360px against 280px, and we have an extra roster column | None. The widths belong to Phase 6 and the roster column to Phase 1. The Pop-out window reuses whatever the in-app tree has |
| 4 | Chrome above the panes: `.topstrip{height:46px;min-height:46px}` (`messages.html:50-51`) and `.hometabs{height:34px;min-height:34px}` (`:82`), 80px in all (Window header, Creator tabs, Fan tabs) | Windowed: nothing. In-app: the top bar at 56px (`TopBar.tsx:54`) | The Pop-out window has no Window header and no tab strips | None (Phase 1) |
| 5 | Sidebar "↗" beside "Messages Pro" "opens an additional window" (§1.1 row 4, C[BS], C[H545992]) | `Sidebar.tsx:86-96`: `href={l.href}` = `/messages-pro` (`nav.ts:92`), `target="_blank"` | It opens the in-app page, chrome included | The href becomes `/messages-pro?window=1` |
| 6 | Deep link: `messages.html?account=<aid>&fan=<id>[&popout=1]` (`messages.js:3417-3421`), "scoped to one creator (do not persist)" (`messages.js:3431`), with the Fan selected at boot (`messages.js:3471`) | A separate one-Fan page (`[accountId]/[fanId]/page.tsx:28`). It has no list and does not touch scope | No list and no selection | The Deep link opens the tree with the Fan selected and the link's Creator as the scope for this window only |
| 7 | Selected row: `.conv.selected{background:var(--hover)}` (`messages.html:161`) | `ChatList.tsx:1042` `isSelected && "bg-bg-elev-1"`. The row has no ARIA state and is never scrolled into view | Tests and assistive tech cannot see the selection, and a deep-linked row can sit off-screen | The selected row gets `aria-current="true"` and is scrolled into view |
| 8 | Right pane: `.right` is shown when a Fan is selected and hidden when the selection clears, with no toggle (`messages.js:1659`, `:1681`). Heading "Fan insights" (`messages.html:770`) | In-app passes `forceDrawerOpen` (`page.tsx:212`), so insights are open and closing does nothing (`ChatSurface.tsx:1192-1197`). The "Fan insights" button is `lg:hidden` (`ChatSurface.tsx:1008-1018`) | The plan needs insights closed when a Deep link arrives, and a toggle. At lg+ ours cannot close | A "Fan insights" toggle at every width. Insights start open, except when a Deep link arrives |
| 9 | Thread pop-out: `#tbOpen` "Pop out" (`messages.html:707`) | `ChatSurface.tsx:981-993` "↗ pop out" opens `/messages-pro/<acc>/<fan>` with `target="_blank"` | It opens a page with app chrome | It targets `…?window=1`. The label and position belong to Phase 3 |
| 10 | Pinned messages: a `.pinbar` inside the Thread (`messages.html:538`, `:715`), and no pinned column | `PinnedSidePanel`, a `w-[280px]` left column (`PinnedPanel.tsx:247`, `:261`). Only the one-Fan page uses it (`ChatSurface.tsx:870-876`), and it hides `PinnedBar` and `PinnedPopover` there (`ChatSurface.tsx:1056`, `:1095`) | It takes the Fan List's place | Retired. `PinnedBar` and `PinnedPopover` always render (ADR-0002) |
| 11 | The window has no context strip | `[accountId]/[fanId]/page.tsx:207-212` shows "← Back to inbox · popout · <account> · fan <id>" | An extra row | Removed together with the one-Fan page |
| 12 | `<title>Messages Pro</title>` (`messages.html:6`) | Layout metadata "Messages Pro" (`layout.tsx:3`). ChatList sets "(N) Inbox · Inflowwww" (`ChatList.tsx:370-373`). The one-Fan page sets "(n) <fan> · Inflowwww" (`[accountId]/[fanId]/page.tsx:190-193`) | Two title schemes | The Deep link uses ChatList's title |
| 13 | Empty Thread: "Select any conversation to start" (`messages.html:721`) | "Pick a conversation on the left." (`page.tsx:216-218`) | The label differs | None (Phase 1 names this text) |

## Problem Statement

An Employee who works several Fans at once opens Messages Pro in a second window, as Infloww's Multi-Window allows. Today that does not work:

- The "↗" beside Messages Pro in the sidebar opens the ordinary page in a new tab, with the app sidebar and top bar still taking space.
- The Thread's "↗ pop out", the notification bell, the Buys & tips rail, the money toasts and the Message dashboard rows all land on a one-Fan page. That page has a single Thread, Fan insights that cannot be closed, a column of pinned messages where the Fan List should be, and a "← Back to inbox" strip. The Employee cannot get to the next Fan without leaving it.
- The two layouts drift apart, and every later parity Phase would have to change both.

Nobody can compare our screen with the Clone without a live account either. The screenshot harness that the plan relies on does not exist: there is no `scripts/ui-shots.sh` and no `docs/ui-shots.md`, and Playwright is not in `app/package.json`.

## Solution

There is one Messages Pro, wherever it opens:

- **The sidebar's "↗"** opens `/messages-pro?window=1`. That is the same three panes as in-app, filling the window, with no app sidebar and no top bar.
- **Any link to a Fan** (`/messages-pro/<creator>/<fan>`) opens that same Messages Pro. The Fan is selected and scrolled into view in the Fan List, the Thread is open, and Fan insights stay closed until the Employee opens them with the "Fan insights" toggle. From there the Employee can click any other Fan.
- **The Thread's own "↗ pop out"** opens such a link as a Pop-out window.
- **Pinned messages** stay in the Thread's pinned bar.
- **Below 1024px**, nothing changes: one pane at a time.

For implementers, `scripts/ui-shots.sh` starts a throwaway relay and the app on localhost and serves fixture Fans. It screenshots six Messages Pro states and the Clone, checks that each shot shows the state it claims, and fails when a shot is missing or not in its state, anything overflows sideways, a console error is logged, or a request tries to leave the machine. Every UI ticket then compares its shot with the Clone and fixes what it can before it is done.

## User Stories

1. As an implementer of a UI ticket, I want one command, `scripts/ui-shots.sh`, that renders Messages Pro and the Clone to PNGs, so that I can compare our screen with Infloww's layout without a live account.
2. As an implementer, I want the harness to start a relay backed by a throwaway SQLite database, and the Next app, both bound to 127.0.0.1 on free ports, so that it never touches the production database and never collides with a dev server I already have running.
3. As an implementer, I want the harness relay to run in the house safe mode (test mode on, no pumps, no ingest, no automations, no sends) with a throwaway secret store, so that a screenshot run can never reach OnlyFans or a Fan, and never reads or writes my own stored keys.
4. As an implementer, I want the harness to register a throwaway owner and pick an Employee in "Who's chatting?", so that the shots show the signed-in app.
5. As an implementer, I want the harness to answer the app's relay calls from fixtures (one Creator, five Fans, one Employee, a seven-message Thread for the first Fan), so that the shots are deterministic and contain no live data.
6. As an implementer, I want any browser request to a host other than localhost to be aborted and recorded, and any outbound connection the Next or relay process attempts to be refused and recorded, so that "no network beyond localhost" is enforced and not just promised.
7. As an implementer, I want the harness to write `messages-pro-desktop.png`, `messages-pro-popout.png`, `messages-pro-insights.png`, `messages-pro-phone-list.png`, `messages-pro-phone-thread.png` and `messages-pro-composer-ppv.png` to `docs/screenshots/`, each in a fixed state, so that every Phase has the same artefacts to look at.
8. As an implementer, I want the Clone rendered with the same fixtures at the desktop viewport to `docs/screenshots/clone-messages-pro.png`, so that the comparison is like for like.
9. As an implementer, I want `docs/screenshots/messages-pro-report.json` to give each shot's horizontal overflow, console errors, off-host requests and state checks, plus the connections the server processes had refused, so that I can see why a run failed without opening the browser.
10. As an implementer, I want the harness to exit non-zero on horizontal overflow, a console error, an off-host request, a failed state check or a missing file in any shot or flow, the Clone's included, so that a broken or blank screen cannot pass.
11. As an implementer, I want the harness never to install browsers or packages, and to exit non-zero with the exact install command when Chromium is missing, so that a run never downloads anything.
12. As an implementer, I want the harness to delete the previous run's PNGs and report when it starts, and to stop both processes and delete its temp database and secret store on every exit, so that a failed run cannot leave stale files that look like a pass, and runs leave nothing behind but the screenshots and the report.
13. As a future implementer, I want `docs/ui-shots.md` to explain how to run the harness, what each shot shows, the report format, the exit codes, and the Visual loop steps for a ticket (up to three rounds, `VISUAL GAP:` lines, commit the final PNGs), so that every Phase follows the same loop.
14. As a Phase reviewer, I want each Phase's acceptance to run the harness once more and to record the report's summary in the Phase result, so that the final state is on file.
15. As the Phase 0 implementer, I want to run the Visual loop on `messages-pro-popout.png` against `clone-messages-pro.png` (three-pane layout), record what is still different after round three as `VISUAL GAP:` with the owning Phase, and commit the final PNGs, so that Phase 0 meets the plan's visual bar.
16. As an Employee, I want the "↗" beside Messages Pro in the sidebar to open `/messages-pro?window=1`, so that I get a second Messages Pro next to the first.
17. As an Employee, I want the Pop-out window to show the Fan List, the Thread and Fan insights, behaving exactly as in-app, so that a second window is a full workspace and not a reduced view.
18. As an Employee, I want the Pop-out window to have no app sidebar, no top bar and no menu drawer, and its panes to fill the whole window height, so that the window's space goes to the conversation.
19. As an Employee on a narrow window (below 1024px), I want the Pop-out window to show one pane at a time like in-app Messages Pro (Fan List, then Thread, then the Fan insights slide-over), so that it stays usable when narrow.
20. As an Employee, I want in-app Messages Pro to keep the sidebar and top bar, so that only the Pop-out window changes.
21. As an Employee, I want `?window=1` to carry through a Deep link and the username redirect, so that any link opened as a Pop-out window stays one.
22. As an Employee following a link to a Fan (notification bell, Buys & tips rail, money toast, Message dashboard row), I want `/messages-pro/<creator>/<fan>` to open the full Messages Pro with that Fan selected in the Fan List, so that I can move on to other Fans without leaving.
23. As an Employee arriving by Deep link, I want the Fan's row scrolled into view and marked as selected, so that I can see where I am in the Fan List.
24. As an Employee arriving by Deep link, I want the Fan's Thread to open at once, even before the Fan List has loaded, so that a link is never slower than the one-Fan page was.
25. As an Employee arriving by Deep link, I want Fan insights closed and openable with the "Fan insights" toggle, so that the Thread gets the room first.
26. As an Employee arriving by Deep link, I want the Fan List scoped to the link's Creator without changing the scope I saved for my other windows, so that the Fan is in the list and my main window is undisturbed.
27. As an Employee opening a money link (`?refresh=media`), I want the Thread, the Fan's media and PPV history, recent purchases and the Fan's profile refetched once, and then `refresh` removed from the URL with the other parameters kept, so that money I was just told about shows up and a reload does not refetch again.
28. As an Employee opening a malformed link, I want "Invalid fan id: <id>" instead of an empty Thread, so that I know the link is wrong.
29. As an Employee whose deep-linked Fan is not among the loaded Fan List rows, I want the Thread to open anyway, with no row marked, so that a link to an older chat still works.
30. As an Employee who selects another Fan in a deep-linked window, I want Messages Pro to behave as it does in-app (insights open on selection, scope switching as usual), so that the arrival rules apply only to arrival.
31. As an Employee, I want a "Fan insights" toggle in the Thread at every width that opens and closes the Fan insights pane and reports its state, so that I can close insights on a desktop and reopen them after a Deep link.
32. As an Employee, I want a Fan selected in-app or in the Pop-out window to open with Fan insights open, as today, but closable, so that the default does not change and the toggle works everywhere.
33. As an Employee, I want the Thread's "↗ pop out" to open a Pop-out window at that Fan's Deep link, so that popping a chat out gives me a full Messages Pro.
34. As an Employee, I want pinned messages in the Thread's pinned bar and popover everywhere, with the one-Fan page's pinned-messages column gone, so that the left pane is always the Fan List.
35. As a maintainer, I want `docs/routes.md` to describe `?window=1` and the Deep link as they now behave, so that the route doc matches the code.
36. As a maintainer, I want `app/app/messages-pro/windowed.test.tsx` to cover the windowed render, the in-app render and the Deep link, so that a regression in any of them fails `test:run`.
37. As an implementer, I want `UI_SHOTS_SELFTEST=1 scripts/ui-shots.sh` to inject one console error and one over-wide element into the popout shot and exit non-zero with both in the report, so that the gate has been seen to fail at least once.
38. As an Employee arriving by a Deep link that names a message (`?msg=<id>`), I want the Thread to open on that message, and the link's message to be dropped once I select another Fan, so that switching Fans never pages through another Fan's history looking for it.

## Implementation Decisions

- **Owns.**
  - The Messages Pro route modules: the layout (gains the windowed variant), the index page and the Deep link page. The username redirect page is untouched.
  - A new `MessagesPro` component that holds the one tree.
  - Modified: `ChatSurface`, `PinnedPanel`, `ChatList`, `FanDrawer` (an accessible name only), `ScopeContext`, `AppShell`, `Sidebar`, `nav`, the global stylesheet's `.h-chat` rule, the Next config (`distDir`), and the navigation mock in the existing `AppShell` test.
  - New: `app/app/messages-pro/windowed.test.tsx`, `scripts/ui-shots.sh`, `docs/ui-shots.md`, and the seven PNGs plus the report under `docs/screenshots/`.
  - Edited: `docs/routes.md`.

  ASSUMPTION: the harness is specced and built in Phase 0, as its first stories. It is work the plan needs but did not list, and Phase 0 is the first UI Phase, so every later Phase depends on it (rung 5: the first consumer builds it). Overturned if the human gives the harness its own Phase or ticket.

  ASSUMPTION: the plan names `scripts/ui-shots.sh` itself, and that named path (rung 2) wins over its own rule that nothing outside `app/` and `docs/` changes. To keep that exception to one file, the Python driver and the fixtures are embedded in the script, and nothing else is added outside `app/` and `docs/` (rung 5). Overturned if the human wants the harness somewhere else or split into several files.

- **Interfaces.**
  - **`MessagesPro`** takes an optional `deepLink: { accountId: string; fanId: FanId }`. Without it, it is today's index page: the Creator roster, the Fan List, the Thread, Fan insights inside the Thread, realtime, and the vault warm-up. These all move here unchanged. With it, it adds the Deep link arrival rules below.
  - **The index page** renders `MessagesPro` with nothing else.
  - **The Deep link page** parses the fan id the way the one-Fan page did, which keeps big Fansly ids as exact strings. An invalid id shows "Invalid fan id: <id>". A valid one renders `MessagesPro` with `deepLink`. Everything else the one-Fan page did is deleted from that module. The Fan profile lookup and the `?refresh=media` one-shot move into `MessagesPro`.
  - **The Messages Pro layout** keeps its "Messages Pro" metadata and wraps the route in a client frame. When the window is a Pop-out window, the frame zeroes the shell offset so its subtree is full height. Otherwise it renders children as today. The layout cannot remove chrome on its own, because the root layout mounts `AppShell` above it (`app/app/layout.tsx:167`). That is why `AppShell` reads the same predicate.
  - **`nav`** gains two helpers. `popoutHref(link)` returns the link's href plus `?window=1`. `isPopoutWindow(pathname, searchParams)` is true when `window=1` and the pathname is a `popout` link's href or sits under it. Only Messages Pro is a `popout` link.

    ASSUMPTION: the predicate lives in `nav` because `nav` already owns the `popout` flag (rung 3). Overturned if a second module needs the predicate and `nav` turns out to be the wrong home.
  - **`AppShell`** renders only the page's main element when `isPopoutWindow` is true: no top bar, no sidebar, no drawer. Otherwise it is unchanged.
  - **`Sidebar`** points its popout anchor at `popoutHref(link)`. The anchor keeps `target="_blank"` and its label.

    ASSUMPTION: whether the browser opens a tab or a window is left to the browser, as today. §5 says "Web: … Messages Pro opens in a new tab", and a `window.open` popup would add script for no gain (rung 5). Overturned if the human wants a real separate window on the web.
  - **`ChatSurface`** drops `forceDrawerOpen` and `forcePinnedPanelOpen`. It gains `insightsOpenAtStart: boolean`.
    - At lg+, Fan insights are always the in-flow column. They start open or closed according to the prop, and they can be closed.
    - Below lg they start closed and open as the slide-over, as today.
    - The header's "Fan insights" button is visible at every width. It toggles the pane and reflects the state in `aria-expanded`.
    - The header's "↗ pop out" targets the Fan's Deep link plus `?window=1`.
    - `PinnedBar` and `PinnedPopover` render unconditionally.
  - **`PinnedPanel`** removes `PinnedSidePanel`. `PinnedBar` and `PinnedPopover` are unchanged.
  - **`FanDrawer`**: its pinned column carries the accessible name "Fan insights", so that the column is a named complementary landmark for the test and the harness. Nothing else changes, because content belongs to Phase 5.
  - **`ChatList`**: the selected row carries `aria-current="true"`. When a selection's row first appears in the rendered list, the row is scrolled into view (nearest edge) once for that selection.
  - **`ScopeContext`**: `setScope(scope, options?: { persist?: boolean })`, where the default `persist: true` is today's behaviour. With `persist: false`, the scope changes for this window, including the realtime event scope, but the stored scope is not written. A scope set before the stored scope finishes loading is not overwritten by it.

    ASSUMPTION: an additive option on the existing context, not a second scope provider. A nested override would leave the realtime event scope on the old Creator (rung 4: additive, default unchanged). Overturned if a later Phase replaces scope with Creator tabs (Phase 1) in a way that makes this option dead.
  - **Global stylesheet**: `.h-chat` subtracts `var(--shell-top, 3.5rem)` instead of the literal `3.5rem`. The windowed frame sets `--shell-top: 0px`.

    ASSUMPTION: a CSS variable whose default is today's value (rung 4: additive, nothing changes off the Pop-out window). Overturned if Phase 6's token module takes over Messages Pro heights.
  - **Next config**: `distDir` is read from `NEXT_DIST_DIR`, defaulting to `.next`.

- **Schema.** None. No table, no field and no relay change. No backend file changes.

- **Contracts.**
  - **URL.**
    - `window=1` on any `/messages-pro` route means a Pop-out window.
    - `/messages-pro/<accountId>/<fanId>` is a Deep link.
    - `refresh=media` on a Deep link is a one-shot. It is stripped after it runs, and every other query parameter and the hash are kept.
    - `msg=<id>` on a Deep link applies to the deep-linked Fan only. It is removed from the URL when another Fan is selected.
    - Links that already point at `/messages-pro/<accountId>/<fanId>` (bell, Buys & tips rail, toasts, Message dashboard rows, the username redirect) keep their URLs and now land on the full tree, in-app.
  - **Selected Fan row.** The row carries `aria-current="true"`. Later Phases keep this marker when they rebuild the Fan List (Phase 2), because both the test and the harness rely on it.
  - **Fan insights.** The toggle is a button named "Fan insights" with `aria-expanded`. The lg+ pane is a complementary landmark named "Fan insights". Later Phases keep both names (Phase 3 for the Chat header, Phase 5 for the pane).
  - **Harness.** `scripts/ui-shots.sh` takes no arguments and reads one switch, `UI_SHOTS_SELFTEST=1`. It returns exit 0 only when every shot and flow passes, the Clone's included. It deletes its previous outputs when it starts. Its outputs are the seven PNGs and the report under `docs/screenshots/`. The report's shape is fixed:

    ```json
    { "ok": true, "startedAt": 1791770000,
      "shots": [ { "name": "messages-pro-popout", "file": "docs/screenshots/messages-pro-popout.png",
                   "url": "/messages-pro?window=1", "viewport": [1440, 900], "gated": true,
                   "overflowX": false, "consoleErrors": [], "offHostRequests": [],
                   "stubbedRequests": [], "unmatchedRequests": [],
                   "checks": [ { "name": "no #app-sidebar", "ok": true } ] } ],
      "flows": [ { "name": "phone-popout", "url": "/messages-pro?window=1", "viewport": [390, 844],
                   "gated": true, "consoleErrors": [], "offHostRequests": [],
                   "checks": [ { "name": "Back to chat list shows the Fan List", "ok": true } ] } ],
      "serverOffHostAttempts": [] }
    ```

    Later Phases may add fixture data, and change the steps that put a shot into its state and the checks that prove it. The shot names, the report shape and the exit rule stay fixed.

- **Pop-out window.**
  - It is the same tree as in-app. The Creator roster rail stays at lg+ until Phase 1 replaces it.
  - Root-level overlays outside the shell (impersonation banner, notification toaster, Buys & tips rail, assistant widget) still render. Auth and the Employee picker still gate the window.

    ASSUMPTION: "without the app sidebar and top bar" is read as exactly those two (rung 5). Overturned if the human wants the Pop-out window bare of the rail and toasts too, as the Clone's one-Fan pop-out is (`messages.html:86`).

  - Until Phase 1's Window header lands, the Pop-out window has no SFW toggle and no Notifications bell. Below lg it has no scope switcher and no menu drawer, because both lived in the top bar. At lg+ the roster still switches Creators.

    ASSUMPTION: this gap is accepted, not patched with a stopgap header (rung 5: Phase 1 builds the Window header). Overturned if the human wants a stopgap header before Phase 1.

- **Deep link arrival.**
  - Selection, scope and insights:
    - `MessagesPro` starts with the Deep link's Fan selected.
    - It switches this window's scope to the link's Creator with `persist: false`.
    - It never clears that selection while that switch settles. This holds both on first load and when arriving from another page.
    - The Thread starts from the Fan profile lookup (`/api/of/v2/users/list`) that the one-Fan page used, so it renders before the Fan List loads. Fan insights start closed for that Fan.

    ASSUMPTION: a Deep link always scopes the window to its Creator, without persisting, even when the saved scope is All Models. This follows the Clone's deep link, "scoped to one creator (do not persist)" (`messages.js:3431`) (rung 3). Overturned if the human wants a Deep link to keep an All Models scope.

  - If the Fan's row is not among the loaded rows, the Thread opens anyway. No row is marked, and no further pages are fetched to look for it.

    ASSUMPTION: no hunting through older pages, because each page is a live OnlyFans call (rung 5). Overturned if Employees report deep links to old chats landing unmarked.

  - Insights start closed only for the Deep link's own Fan on arrival. Any later selection follows the in-app default, which is open.

    ASSUMPTION: the in-app default governs everything after arrival, because the plan only specifies the arrival state (rung 3: today's in-app behaviour). Overturned if the human wants a closed pane to stay closed across Fans.

  - Selecting another Fan does not rewrite the URL, except that it removes `msg` (next item).

    ASSUMPTION: no URL sync (rung 5). Overturned when Phase 3's "copy chat link" needs the current Fan in the URL.

  - `msg=<id>` on a Deep link (the `/customs` tip rows produce it, `CustomsTab.tsx:463`) is read by `ChatSurface` from `window.location.search` (`ChatSurface.tsx:730-745`), which pages back up to `ANCHOR_MAX_PAGES` = 6 pages, each a live OnlyFans call, to find it (`ChatSurface.tsx:100`). On the one-Fan page that URL only ever showed its own Fan. In the shared tree the URL outlives the selection, so the handler that selects another Fan removes `msg` from the URL (`history.replaceState`, other parameters and the hash kept) before that Fan's Thread mounts. The deep-linked Fan's own Thread still opens on the message.

    ASSUMPTION: the strip happens in the select handler and not in an effect, because the new `ChatSurface`'s effect runs before a parent's effect and would read the stale `msg` (rung 5). Overturned if Phase 3's URL sync takes ownership of `msg`.

  - The one-Fan page's per-Fan unread count in a hidden tab's title is retired. The window takes ChatList's Messages Pro title.

    ASSUMPTION: the unread count is retired with the page it belonged to (rung 5). Overturned if Employees relied on it.

- **Fan insights toggle.** It is not an Inflowwww extra.

  ASSUMPTION: the toggle is not an extra. The plan requires it (Phase 0 acceptance), §3.3 does not tag it "ours", and the Clone simply always shows the pane (rung 5). Overturned if Phase 3 or Phase 7 finds that Infloww has no such control, in which case it moves into the Chat header's Extras overflow.

- **Thread pop-out.** The Thread's "↗ pop out" opens `…/<accountId>/<fanId>?window=1`.

  ASSUMPTION: the Thread pop-out opens a Pop-out window. This follows the consequence recorded in ADR-0002 and the one-Fan page's own header comment (rung 3). Overturned if Phase 3 finds that Infloww's "Open new" opens a Fan tab instead.

  This overturn has fired: Phase 3 F1 finds that the Chat header button is "Open in new tab" and adds a Fan tab (`phase-03-chat-header-message-list.md:21`, `:304-307`), and ADR-0002 carries the amendment. Phase 0 still ships the link, because Phase 0 lands before Phase 3 and today's Thread has it. Phase 3 removes it and takes over case 7.

- **Harness: processes.** The harness is a bash script with an embedded Python driver, run with `venv/bin/python`. That interpreter has uvicorn, FastAPI and Playwright, as observed with `venv/bin/python -c "import uvicorn, fastapi; from playwright.sync_api import sync_playwright"`.
  - **Relay.** The relay runs by importing the safe-runner patches in `service/_run_ui_safe.py` and serving `server.app` on 127.0.0.1. Its environment mirrors `service/tests/_harness.py`:
    - `DATABASE_URL` and `CHATTERLY_DB_URL` point at a SQLite file in a `mktemp -d` directory.
    - `CHATTERLY_TEST_MODE=1`.
    - `SHARE_TOKEN` is empty.
    - `SESSION_SECRET`, `CHATTER_SESSION_SECRET` and the LLM keys are fake.
    - `OPENINFLOWW_LEGACY_AUTOMATIONS` is unset.
    - Before serving, the driver points `secrets_store._DIR` and `_PATH` into the temp directory and clears `_CACHE`, as `service/tests/_harness.py:75-80` does. The stored value outranks the environment: `_effective_share_token` reads the store before `SHARE_TOKEN` (`service/server.py:444-454`), so without the redirect the relay would read, and could write, the developer's own `secrets.json`.

    ASSUMPTION: the redirect copies `_harness.py`'s, by house precedent (rung 3). Overturned if `secrets_store` gains an environment override for its path, which then replaces the patch.

    No `service/` file changes.
  - **Next app.** The app runs as `next dev --webpack -H 127.0.0.1` with `RELAY_URL` set to the harness relay and `NEXT_DIST_DIR=.next/ui-shots`.
  - **Startup.** Both processes take free ports chosen at start. The harness waits for the relay's `/health` and the app's root, with a timeout. On exit, a trap stops both processes and removes the temp directory.

  ASSUMPTION: free ports chosen at start, and a separate Next `distDir` nested under `.next/`. When observed, a `next-server` from this `app/` held 3001 and relays held 8787 and 8788, and Next 16 refuses a second dev server in the same `distDir` ("Another … server is already running in this directory", `node_modules/next/dist/esm/build/lockfile.js:157`). A path under `.next/` is already ignored by git, ESLint and `tsc` (rung 4: additive, the default is unchanged). Overturned if Next refuses a nested `distDir` or the lock turns out to be global.

  ASSUMPTION: the relay starts through the existing safe runner's patches with `_harness`-style env, not a new launcher in `service/` (rung 3). Overturned if `_run_ui_safe` changes so that importing it no longer neuters the background loops.

- **Harness: network.**
  - **Browser.** The browser context blocks service workers so that every request passes the harness's router, and the router applies default-deny:
    - A request to a host other than 127.0.0.1 or localhost is aborted and recorded in `offHostRequests`.
    - Relay-bound paths (`/admin`, `/api`, `/auth`, `/chatter`, `/img`, `/events`, `/ws`, `/health`) reach the temp relay only for `/auth/*` and `/events`.
    - Every other relay-bound path is answered from fixtures, or with an empty JSON body when no fixture matches, and that request is listed in the shot's `unmatchedRequests`. Above all, `/api/of/*` never reaches the relay's OnlyFans proxy.
    - The Clone's requests to `fonts.googleapis.com` and `fonts.gstatic.com` (`messages.html:8-10`) are answered locally with an empty 200 response and listed in `stubbedRequests`, so the Clone loads without a failed-resource console error and nothing leaves the machine. Every other off-host request, from any shot, is aborted.

    ASSUMPTION: default-deny to the relay. It guarantees that no request can reach OnlyFans through the relay (rung 4). An empty body does not fail loudly, because consumers read `{}` as an empty list (`app/hooks/useChatMessages.ts:150`, `app/hooks/useLastPurchases.ts:56`). So the content each shot must show is asserted by its state checks (Harness: shots), and `unmatchedRequests` is recorded without gating, so that endpoints no shot depends on need no fixture (rung 5). Overturned if broken wiring passes the state checks while an unmatched request explains it; then unmatched requests gate.
  - **Server processes.** `next dev` makes two outbound calls of its own: the npm registry version check (`node_modules/next/dist/server/dev/hot-reloader-shared-utils.js:33`) and the Google Fonts download for Sora (`app/app/layout.tsx:2`). Both processes run with `NEXT_TELEMETRY_DISABLED=1` and with `HTTP_PROXY` and `HTTPS_PROXY` pointing at a closed loopback port, which `next/font` honours (`…/@next/font/dist/google/get-proxy-agent.js:15-19`). Next also gets a `NODE_OPTIONS` preload that makes global `fetch` refuse hosts that are not loopback. Shots therefore use Sora's fallback font.
  - **Relay process.** The driver patches `socket.socket.connect` and `socket.create_connection` to refuse addresses that are not loopback before it imports the server, which covers the relay's Python HTTP clients. The one client that bypasses Python sockets, the OnlyFans `curl_cffi` session with its own proxies (`service/of_client.py:298-300`), is unreachable by construction: test mode skips every pump, supervisor and network spawn at startup (`service/server.py:1117-1127`), the temp database holds no OnlyFans account or session, and the router never forwards `/api/of/*`.
  - Every connection either guard refuses is appended to a file in the temp directory and copied into the report as `serverOffHostAttempts`. Refusal is the enforcement, so the list is recorded and does not gate: Next's own version check lands there on every run.

    ASSUMPTION: refusal at the Node `fetch` and Python socket layers, plus the unreachable `curl_cffi` path, is enough without an OS-level sandbox (rung 5: no new tool). Overturned if `serverOffHostAttempts` or a packet capture shows a connection the guards did not refuse; then both processes run under an OS-level deny-outbound sandbox. Fallback-font shots are acceptable for Geometry comparison (rung 5). Overturned if the fallback font throws the Visual loop off by enough to matter.
  - **Missing browser.** The harness never installs anything. If Chromium is not cached, it exits non-zero and prints `venv/bin/python -m playwright install chromium` for the human.

- **Harness: fixtures and login.**
  - The harness registers a throwaway owner through `/auth/register` on the app origin, so that the session cookie lands there, and then picks the fixture Employee in "Who's chatting?".
  - Fixtures: one Creator named "Ella", five Fans with distinct names and no avatar URLs (so no `/img` traffic), one of them unread, and a seven-message Thread for the first Fan. The Thread mixes Fan and Creator messages and includes one PPV.
  - Response shapes follow the types in the app's relay client.

  ASSUMPTION: the Creator is named "Ella", after the Clone's Fan List header (`messages.html:628`), so that both shots read alike. The other fixture details are a coin flip (rung 6). Overturned if a later Phase needs different fixture data, which it may add.

- **Harness: shots.**

  | Shot | Viewport | State | State checks (each gates) |
  |---|---|---|---|
  | `messages-pro-desktop` | 1440×900 | `/messages-pro`, first fixture Fan clicked | `#app-sidebar` visible. The five fixture Fan names in the Fan List, the clicked row with `aria-current="true"`. Seven messages in the Thread, the PPV among them. The "Fan insights" pane visible |
  | `messages-pro-popout` | 1440×900 | `/messages-pro?window=1`, first fixture Fan clicked | No `#app-sidebar` and no "Toggle sidebar" button in the DOM. The five Fan names, seven messages and the "Fan insights" pane visible. The Fan List, Thread and Fan insights panes each end within 1px of the viewport's bottom edge and sit inside it horizontally |
  | `messages-pro-insights` | 1440×900 | Element shot of the "Fan insights" pane in the desktop state | The pane is visible and names the first fixture Fan |
  | `messages-pro-phone-list` | 390×844 | `/messages-pro` | The five Fan names visible, no Thread visible |
  | `messages-pro-phone-thread` | 390×844 | `/messages-pro`, first fixture Fan tapped | Seven messages and "Back to chat list" visible, the Fan List not visible |
  | `messages-pro-composer-ppv` | 1440×900 | Desktop state with a price typed into the Composer's "PPV price" control | The control holds the typed price, and the Composer sits inside the viewport |
  | `clone-messages-pro` | 1440×900 | The temp relay's `/infloww/messages.html?account=<fixture Creator>&fan=<first Fan>`, same fixtures | `.list`, `.center` and `.right` visible |

  - **Flow `phone-popout`** (390×844, no PNG, gates): `/messages-pro?window=1` has no `#app-sidebar` and no "Toggle sidebar" button, and the Fan List is visible. Tapping the first Fan shows its Thread, ending within 1px of the viewport's bottom edge. "Fan insights" opens the slide-over, and closing it returns to the Thread. "Back to chat list" shows the Fan List. This covers story 19 without adding a shot name.
  - A step that cannot reach its state (a click target missing, a timeout) fails that shot's checks. It does not abort the run, so the report still lists every shot.

  - The popout shot is the windowed index with a Fan clicked, not a Deep link, because a Deep link arrives with Fan insights closed and the plan wants three panes in that shot.
  - `overflowX` means `document.documentElement.scrollWidth > innerWidth`.
  - Console errors are console messages of type `error` plus uncaught page errors, with no allowlist.

  ASSUMPTION: the viewports are 1440×900, one of the two desktop sizes Phase 6 names, and 390×844 (the phone size in `docs/routes.md`). The insights shot is an element shot, and the PPV state is a typed price (rung 3 for the phone size, rung 5 for the rest). Overturned by the Phase that owns a shot (Phase 4 for the PPV row, Phase 5 for insights) changing its state step.

  ASSUMPTION: the state checks are the content each shot exists to show, read from the plan's fixture list (five Fans, a seven-message Thread) and the panes this Phase builds (rung 5). Overturned by the Phase that owns a region changing what its shot must show, which it may.

  ASSUMPTION: horizontal overflow and the state checks are the only layout gates, and console errors have no allowlist. `docs/routes.md` says "the page itself never scrolls sideways" and Phase 6 checks horizontal scroll (rung 5). Overturned if pre-existing dev-only noise makes the gate unusable, in which case the noise is fixed and not allowlisted.

  - The Clone shot gates like the app shots, because the plan's exit rule names console errors and a missing shot without exempting the Clone (`docs/plans/messages-pro-parity.md:42-48`, rung 2). Its Google Fonts are answered locally (Harness: network), and its relay calls are answered from the same fixtures.

    ASSUMPTION: a Clone console error that only an edit under `ui-redesign/` could remove is parked with its text, not allowlisted, because the plan forbids that edit (rung 2 for the boundary, rung 4 for parking over allowlisting). Overturned if the human allows the edit or exempts the Clone.

- **Harness: self-test.** `UI_SHOTS_SELFTEST=1` adds an init script to the popout shot that logs one `console.error` and appends a 2000px-wide element. That run must exit non-zero, and its report must show the error and `overflowX: true` on that shot. Acceptance runs it once before the real run, which then replaces its outputs.

  ASSUMPTION: one self-test switch, not a test suite for the harness (rung 5). Overturned if a later Phase changes the gate logic, which then extends the self-test.

- **Docs.**
  - The `docs/routes.md` Messages Pro row now reads: in-app, Pop-out window (`?window=1`), and Deep link into the same tree. The responsive section gains one line: a Pop-out window has no top bar and no drawer, and is still one pane at a time below `lg`.
  - `docs/ui-shots.md` covers running the harness, its prerequisites, the shot table, the report, the exit codes, and the Visual loop.

## Testing Decisions

- **Seam 1: the Messages Pro route as the app renders it.** `app/app/messages-pro/windowed.test.tsx` renders `AppShell`, then the Messages Pro layout, then the index or Deep link page, inside `renderWithProviders` with the real `ScopeProvider`.
  - The only stubs are the relay client at its module boundary (fixture Creator, Fans and Thread), `next/navigation` set per case (pathname and search params), the user, chatter and employee contexts as the `AppShell` test stubs them, and the browser APIs jsdom lacks (`matchMedia` set to desktop or phone per case, `scrollIntoView`, observers).
  - `ChatList`, `ChatSurface` and `FanDrawer` render for real.
  - Assertions read only what a user or assistive tech sees: landmarks, names, `aria-current`, `aria-expanded`, link hrefs, the URL and the stored scope.
  - The cases:
    1. **Windowed.** `/messages-pro?window=1`: no `#app-sidebar` and no "Toggle sidebar" button. The fixture Fans are listed. Clicking one opens its Thread, and the "Fan insights" toggle shows `aria-expanded="true"` next to the "Fan insights" pane. Clicking the toggle closes the pane (`aria-expanded="false"`, no pane), and clicking it again reopens it.
    2. **In-app.** `/messages-pro`: `#app-sidebar` is present, and its "Open Messages Pro in a new tab" link points at `/messages-pro?window=1`. The same Fan List and Thread render.
    3. **Deep link.** `/messages-pro/<acc>/<fan>`: that Fan's row has `aria-current="true"` and was scrolled into view. The Thread header shows the Fan, and the "Fan insights" toggle shows `aria-expanded="false"` with no pane. Clicking the toggle opens the pane. Selecting another Fan then opens that Fan with the pane open (`aria-expanded="true"`).
    4. **Deep link scope.** The stored scope is a different Creator: the Fan List is the link's Creator's, the Fan is selected, and the stored scope is still the other Creator. This holds both on first render and after re-rendering from the index page into the Deep link.
    5. **Deep link refresh.** `?window=1&foo=1&refresh=media#h`, with all six query families the one-Fan page invalidated (`[fanId]/page.tsx:151-156`) seeded in the cache: the Thread and every other query mounted at arrival are fetched from the relay again at once. Opening "Fan insights" fetches the media, PPV history and recent purchases again instead of painting the seeded data. Each is fetched once. The URL ends as `?window=1&foo=1#h`, and a re-render with that URL fetches nothing more.
    6. **Deep link invalid.** A non-numeric fan id: "Invalid fan id: …" shows, and no Thread renders.
    7. **Thread pop-out.** In any case with a Thread, its "↗ pop out" points at `/messages-pro/<acc>/<fan>?window=1`. Phase 0 ships this case as written. Phase 3 owns it from then on: when Phase 3 replaces the link with "Open in new tab", Phase 3 rewrites this case in the same change (`phase-03-chat-header-message-list.md`, Testing Decisions, seam 4).
    8. **Pinned messages.** No "Pinned messages" complementary region renders in any case. In the Deep link case, a fixture message with `isPinned` shows the Thread's pinned bar ("1 pinned message", `PinnedPanel.tsx:66`; the list is derived at `ChatSurface.tsx:801`), and clicking it opens the popover.
    9. **Deep link before the list.** The Fan List request is held pending: the Thread header shows the Fan from the profile lookup, and no row exists yet.
    10. **Deep link, Fan not in the list.** The Fan List resolves without the Fan: the Thread still shows the Fan, and no row has `aria-current`.
    11. **Deep link with `msg`.** `?msg=<id>`: selecting another Fan removes `msg` from the URL before that Fan's Thread requests messages, and that Thread requests one page only.

  The persister's restore wait in case 5 is not exercised, because `renderWithProviders` mounts a plain `QueryClientProvider` (`app/test-utils.tsx:30-34`). The `refresh=media` effect moves with its `useIsRestoring` guard unchanged.

  ASSUMPTION: the Deep link cases live in the plan's `windowed.test.tsx`, not in a second file, because both exercise the same seam and one seam is the goal (rung 5). Overturned if the file grows past easy reading, in which case the Deep link cases move to a sibling file at the same seam.
- **Seam 2: the browser, through `scripts/ui-shots.sh`.** jsdom cannot measure layout, so overflow, full-height panes and "no chrome on screen" are proven by the report's state checks on the popout shot and the `phone-popout` flow, and the three panes are seen again in `messages-pro-popout.png` in the Visual loop. The harness has no unit tests of its own. Its self-test run proves the gate can fail, and its exit code against its report is its test.
- **Existing tests that must stay green:** `AppShell.test.tsx` (its `next/navigation` mock gains `useSearchParams`, because `AppShell` now reads it), `nav.test.ts`, `chatPopout.test.ts`, `MessageList.test.tsx`, `fanDrawerEditFreshness.test.tsx`, and the rest of `test:run`.
- **Prior art:**
  - `app/components/shell/AppShell.test.tsx`: `AppShell` under mocked navigation and contexts.
  - `app/app/analytics/message-dashboard/page.render.test.tsx`: a route page rendered for real with the relay stubbed at its module boundary and jsdom gaps stubbed.
  - `app/lib/chatPopout.test.ts`: pop-out links.
  - `app/test-utils.tsx` `renderWithProviders`.
  - For the harness: `scripts/make-extension-screenshots.py`, which uses Python Playwright.

## Acceptance

```sh
set -eu
cd "$(git rev-parse --show-toplevel)"
pnpm -C app typecheck
pnpm -C app lint
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app test:run
test -f app/app/messages-pro/windowed.test.tsx
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run app/messages-pro/windowed.test.tsx
if grep -rnE "PinnedSidePanel|forcePinnedPanelOpen|forceDrawerOpen" app/app app/components app/lib; then exit 1; fi
test -x scripts/ui-shots.sh
test -s docs/ui-shots.md
# the gate must be seen to fail: the self-test run exits non-zero and reports both injected faults
if UI_SHOTS_SELFTEST=1 scripts/ui-shots.sh; then echo "self-test passed: the gate is broken"; exit 1; fi
venv/bin/python - <<'PY'
import json
r = json.load(open("docs/screenshots/messages-pro-report.json"))
s = {x["name"]: x for x in r["shots"]}["messages-pro-popout"]
assert r["ok"] is False and s["overflowX"] is True and s["consoleErrors"], s
PY
# the real run: every shot and flow fresh from this run, present and passing
scripts/ui-shots.sh
venv/bin/python - <<'PY'
import json, os
want = ["messages-pro-desktop", "messages-pro-popout", "messages-pro-insights", "messages-pro-phone-list",
        "messages-pro-phone-thread", "messages-pro-composer-ppv", "clone-messages-pro"]
r = json.load(open("docs/screenshots/messages-pro-report.json"))
shots = {x["name"]: x for x in r["shots"]}
assert sorted(shots) == sorted(want), sorted(shots)
assert [f["name"] for f in r["flows"]] == ["phone-popout"], r["flows"]
for x in list(shots.values()) + r["flows"]:
    if "file" in x:
        assert os.path.getsize(x["file"]) > 0 and os.path.getmtime(x["file"]) >= r["startedAt"], x["file"]
    assert x["gated"] and not x.get("overflowX") and not x["consoleErrors"] and not x["offHostRequests"], x
    assert x["checks"] and all(c["ok"] for c in x["checks"]), x["checks"]
    print(x["name"], "overflowX=%s" % x.get("overflowX"), "errors=0 offhost=0 checks=%d" % len(x["checks"]))
assert r["ok"] is True
print("serverOffHostAttempts=%d (recorded, refused)" % len(r["serverOffHostAttempts"]))
PY
# manual: Read docs/screenshots/messages-pro-popout.png beside docs/screenshots/clone-messages-pro.png. It must show three panes (Fan List, Thread, Fan insights) and no app sidebar or top bar. Record the Visual loop's diff list per round (up to three) and any VISUAL GAP: lines with the owning Phase in the ticket, then commit the final PNGs with the code.
# manual: paste the report summary printed above into the Phase result.
```

## Depends on

None. Phase 0 is the first Phase, and it builds the harness that every later UI Phase depends on.

## Out of Scope

- **Window header, Creator tabs, Fan tabs, and right-click "Open in a new window" on Creator tabs and Fans** (§3.3 Multi-Window): Phase 1 builds them.
- **Pane widths and chrome heights** (390px list, 280px insights, 46px plus 34px strips): measured in the Gap table, but changed in Phase 6.
- **The empty-Thread text "Select any conversation to start"**: Phase 1 names it.
- **The Thread pop-out's label and position** ("Pop out", or "Open new" for Infloww): Phase 3 owns the Chat header. Phase 0 changes only its target.
- **The content and order of Fan insights**: Phase 5.
- **Restoring the last closed window's Creator on restart** (§3.3 Multi-Window): this is desktop-app behaviour, and a web tab has no restart (YAGNI).
- **A window limit**: Infloww has none (§3.3), so there is nothing to build.
- **Mapping Multi-Window to Electron `BrowserWindow`s** (§5): not in the plan.
- **Hiding the Buys & tips rail, toasts and assistant in the Pop-out window**: the plan names only the sidebar and the top bar (see the assumption under Pop-out window).
- **Pointing bell, rail, toast and Message dashboard links at `?window=1`**: not named by the plan. They keep their URLs and now get the full tree in-app.
- **The Buys & tips rail's "popup" surface for `/messages-pro/*`** (`moneyRailStorage` surfaces): this is only a rail-placement preference, and the plan does not name it.
- **The Group chat button's dead self-close check for `/chat/` paths**: Group chat is an Inflowwww extra and belongs to Phase 7.
- **ChatList's "keep insights open" setting**: Messages Pro already ignored it because of `forceDrawerOpen`. Phase 2 rebuilds the Fan List header and its settings.
- **Flag-on (Legacy flag) shots and the 1280, 768 and 390 overflow sweep**: the plan's shot list is fixed. Phase 7 tests flag-on by rendering, and Phase 6 runs the sweep.

## Further Notes

- **Is the "↗" result a tab or a window?** Decided under Interfaces, by the Sidebar assumption: the browser decides.
- **Should the Deep link scope persist?** Decided under Deep link arrival: no, as the Clone does.
- **Will the first harness run fail on console errors that predate Phase 0?** If any Messages Pro console error predates Phase 0, the Phase 0 ticket fixes it, because the gate has no allowlist.

  ASSUMPTION: errors that predate Phase 0 in Messages Pro are Phase 0's to fix, because the harness gate is part of Phase 0's acceptance (rung 5). Overturned if one turns out to need a backend change. That would be parked with its evidence, under the plan's rule for proven-missing relay endpoints.
- **What if the relay has no fixture-free way to log in?** It does. `/auth/register` creates the user and sets the session cookie (`service/auth.py:508-527`), so no seeded user is needed.

## Review

codex, 2026-10-12 (codex-cli 0.155.0-alpha.9.2, reasoning effort high, read-only sparse worktree without `docs/spec/`; the blind call exited 0 after 212s, the draft call exited 0 after 206s, both outputs fresh and non-empty).

Blind call (before the spec was shown):

- B1, the plan's "no insights" is false, because the one-Fan page passes `forceDrawerOpen` (`[fanId]/page.tsx:218-219`). **accept.** Gap row 2 and the Problem Statement now say the page has Fan insights pinned open and not closable.
- B2, compare with the Clone's normal three-pane layout and not its pop-out (`messages.html:85`). **reject.** Already the case: the Clone shot's URL has no `popout=1`, and Gap row 2 follows ADR-0002 over the Clone.
- B3, "full Messages Pro" needs a Phase 0 definition, since the Window header and tabs are Phase 1's. **reject.** Already defined under Pop-out window, and in the first Out of Scope item.
- B4, the alternatives: a shared workspace with thin route adapters and a window-aware `AppShell`, a redirecting Deep link, route groups, or keeping the one-Fan page. **reject.** The spec already takes the first, the one codex recommends. A redirect would still need the arrival rules and would rewrite URLs that the bell, rail, toasts and `/customs` produce. Route groups would move `AppShell` out of the root layout (`app/app/layout.tsx:163-167`), which is beyond the plan's "nothing else changes". ADR-0002 rejects the one-Fan page.
- B5, URL semantics for every entry point, the named-window money links included (`chatPopout.ts:21`). **reject.** Contracts (URL) and Out of Scope name each entry point. Money links keep their named-tab URL (`chatPopout.ts:20-33`) and land on the full tree in-app, which ADR-0002's one-tree rule allows.
- B6, precedence between the URL's selection and the restored scope (`ScopeContext.tsx:48`, `:72`). **reject.** Already decided: `setScope(…, { persist: false })`, a scope set before the stored scope loads is not overwritten, and the selection is never cleared while that settles. Seam 1 case 4 tests it.
- B7, a bounded strategy for a Fan outside the loaded rows. **reject.** Already decided: no further pages are fetched, following the bounded-paging precedent at `ChatSurface.tsx:97-100`. The missing tests are added under D6.
- B8, a Deep link starts with insights closed, but the shot must show three panes. **reject.** Already decided: the popout shot is the windowed index with a Fan clicked.
- B9, Creator switching below lg and usable height once the top bar is gone (`TopBar.tsx:72`, `globals.css:187`). **partial.** The height is already handled by `--shell-top`, which keeps `--vvh`. The missing Creator switch below lg stays an accepted gap, with its ASSUMPTION, because the plan removes the top bar and Phase 1 builds the Window header and Creator tabs.
- B10, carry forward the cold-link profile, the invalid id, the hidden-tab unread title, `refresh=media` after restore, `msg` navigation, and one title writer. **partial.** All except `msg` were already decided. `msg` is accepted as a new Deep link arrival item, a Contracts line, story 38 and Seam 1 case 11, because in the shared tree a stale `msg` would make another Fan's Thread page through up to 6 live OnlyFans calls (`ChatSurface.tsx:100`, `:730-745`).
- B11, remounting loses unsent Composer state. **reject.** Remounting on a Fan switch is today's in-app behaviour (`page.tsx:208` key), and Phase 0 does not change it.
- B12, the auth and Employee gates and the global surfaces in the window, and owner versus chatter sessions. **reject.** Already decided under Pop-out window. The Creator lists come from `useAccounts`, unchanged.
- B13, pinned messages must stay usable through `PinnedBar` and `PinnedPopover` (ADR-0002, Consequences). **accept.** Seam 1 case 8 now asserts the pinned bar and its popover from a pinned fixture message, not just that the column is gone.
- B14a, stale PNGs or a stale report can pass. **accept.** The harness deletes its outputs when it starts, the report carries `startedAt`, and Acceptance checks every file's mtime against it.
- B14b, negative tests for the harness (console error, overflow, missing shot). **partial.** `UI_SHOTS_SELFTEST=1` injects a console error and an overflow, and Acceptance requires that run to fail. There is no missing-shot injection, because outputs are deleted at start and every file is checked against `startedAt`.
- B15, page-level `scrollWidth` misses clipped content, and a blank or signed-out page would pass. **accept.** Each shot now has state checks that gate: its content, panes inside the viewport, and the Composer inside the viewport.
- B16, test at the composed route, shell and workspace. **reject.** Seam 1 already renders `AppShell`, then the layout, then the page.
- B17, a browser layer that clicks the real links and covers reload, Back, a second window, 1023/1024 and the phone list → Thread → insights → Back path. **partial.** The phone path is added as the gated `phone-popout` flow. The rest is rejected: Seam 1 asserts the hrefs, opening them is the browser's job, and Phase 6 owns the width sweep.
- B18, Geometry differences must be recorded, not passed off as parity. **reject.** Already in Gap rows 3-4 and Out of Scope.
- B19, falsifier: Infloww's Chat header "Open new" may pin a Fan tab. **reject.** Already carried as ADR-0002's assumption under Thread pop-out, to be overturned by Phase 3.
- B20, an explicit policy for the Clone's Google Fonts and `infloww-rea.js` relay calls (`messages.html:8`, `_shared/infloww-rea.js:133`). **accept.** The fonts are answered locally and listed in `stubbedRequests`, and the relay calls are answered from the same fixtures. Merged with D2.
- B21, browser interception cannot prove the relay makes no external calls. **accept.** Merged with D1: the test-mode startup guard, the router never forwarding `/api/of/*`, and a socket guard in the relay process.
- B22, loopback bindings, an isolated temp database, readiness timeouts and cleanup. **reject.** Already decided under Harness: processes.

Draft call (with this spec):

- D1, the harness relay reads the developer's real secret store (`service/server.py:444-454`; the precedent redirects it at `service/tests/_harness.py:75-80`), and proxy variables plus a `fetch` override are not network isolation for the relay (`service/of_client.py:298-300`). **partial.** Accepted: the secret store is redirected into the temp directory, the relay process gets a Python socket guard, refused connections are recorded as `serverOffHostAttempts`, and stories 3 and 6 are rewritten. Not adopted: an OS-level sandbox. The `curl_cffi` path is unreachable by construction, because test mode skips every network spawn (`server.py:1117-1127`), the temp database has no OnlyFans session, and the router never forwards `/api/of/*`. The ASSUMPTION names what overturns this.
- D2, a Clone exempt from gating contradicts the plan's exit rule (`docs/plans/messages-pro-parity.md:42-48`). **accept.** The Clone now gates like every other shot, with its fonts stubbed locally. A Clone error that only a `ui-redesign/` edit could fix is parked, not allowlisted.
- D3, the empty-JSON fallback hides broken wiring, because consumers read `{}` as an empty list (`useChatMessages.ts:150`, `useLastPurchases.ts:56`). **partial.** The assumption's false "fails loudly" is corrected, and the content each shot needs is asserted by gated state checks. Unmatched requests are recorded in `unmatchedRequests` but do not gate, so that endpoints no shot depends on need no fixture.
- D4, the Acceptance block can succeed after a failure (`sh -c 'false; true'` exits 0), and the validator passed `{"ok":true,"shots":[]}`. **accept.** Acceptance now runs under `set -eu`, uses `if grep …; then exit 1; fi` (a `!` pipeline is exempt from `set -e`), and validates the seven names, the flow, every field, every check and file freshness instead of trusting `ok`.
- D5, the refresh test lets most of story 27 be deleted (`[fanId]/page.tsx:132-164`). **partial.** Case 5 now covers all six query families, a single fetch each, and preserving parameters and the hash. The persister's restore wait is not exercised, because `renderWithProviders` has no persister (`app/test-utils.tsx:30-34`). The effect moves with its `useIsRestoring` guard unchanged.
- D6, no case covers the Thread before the list loads, or a Fan missing from the list (`[fanId]/page.tsx:49-72`). **accept.** Seam 1 cases 9 and 10 are added.
- D7, no test closes insights, and none covers what happens after arrival (`ChatSurface.tsx:1192-1197`). **accept.** Case 1 now closes and reopens the pane, and case 3 selects another Fan and expects the pane open.
- D8, Seam 2 cannot prove full height or missing chrome, and neither phone shot is windowed (`globals.css:187`, `docs/routes.md:42`). **accept.** The popout shot's state checks assert no sidebar, no top bar and panes that end at the viewport's bottom edge, and the gated `phone-popout` flow covers story 19 without a new shot name.
- D9, no missing dependency, and leaving the username redirect untouched is correct (`[accountId]/u/[username]/page.tsx:45-50`). **accept.** This agrees with the spec, so nothing is rewritten.

Needs-human: none. Every objection raised in the draft call is either answered by the evidence cited above or rewritten into the spec.

### Six hats

Reconcile of the six-hats report, 2026-10-12. Only the bullets that touch this spec are listed. Bullets about the whole set are in `docs/spec/plan-review.md`.

- Black: case 7 (`:298`, `:296` before this reconcile) asserts the "↗ pop out" link that Phase 3 H9 removes (`phase-03-chat-header-message-list.md:21`). **accept.** Phase 0 ships case 7 as written, and Phase 3 takes it over and rewrites it when it replaces the link. The note on case 7 and the overturn note under the Thread pop-out decision record this, and Phase 3's Owns and Acceptance now list `windowed.test.tsx`.
- White: ADR-0002:12 is overturned by Phase 3 F1. **accept.** ADR-0002 has an `## Amended 2026-10-12` paragraph. The full-window decision stands, so nothing else in this spec moves.
- White: the harness is missing and Chromium is cached. **accept.** Verified: `ls scripts/ui-shots.sh docs/ui-shots.md` finds neither, and `~/Library/Caches/ms-playwright` holds `chromium_headless_shell` builds. Building the harness is this Phase's job, and no image pull or new dependency is needed.
- Blue: no UI ticket starts until this Phase's self-test fails as intended and its real run exits 0. **accept.** This is rung 2: plan:50-51 says a UI ticket is not done until `scripts/ui-shots.sh` exits 0. The Acceptance block above already runs the self-test (which must fail) before the real run (which must pass), so nothing in this spec changes. `plan-review.md` records the gate.
