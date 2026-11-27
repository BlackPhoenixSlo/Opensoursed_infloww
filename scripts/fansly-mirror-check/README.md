# fansly-mirror-check

Headless checks for Fansly Manager (the mirrored Fansly creator UI served in the frame under `/fansly-manager/`).
They fake the login and the Relay with one Playwright route on the context (`mocks.py`: `/auth/me`,
`/chatter/me`, `/admin/employees`, `/admin/accounts` with two Fansly creators, `/admin/settings/applied`,
`/api/of/v2/users/me`, `/img`, `/events`), so no Relay and no Fansly is needed. That route aborts every
request to a host other than localhost before it is sent and fails the run on it (a WebSocket off localhost is
caught by `route_web_socket` and never connected to its server, service workers are blocked); the abort is the proof nothing
leaves the machine. Needs a Next dev server (port from env `PORT`, default 3091). Each script exits non-zero on a
failed check.

They need the generated tree: `app/public/fansly-mirror/` and the filled `app/lib/fansly-mirror-pages.ts` /
`fansly-mirror-build.ts`. Those exist on private main only; the committed table is empty and render.py fails on it.
To prove the scripts without the real capture, derive a capture from the committed generator fixture
`app/lib/__fixtures__/fansly-mirror/capture` with `derive_fixture.py` (output `.scratch/fansly-mirror-check/fixture-capture`,
git-ignored). The derivation is needed because that fixture has no top-bar avatar/balance openers with their States,
no in-frame link to a mirror page and a Built page, no Fansly-style States (an `xdModal back-drop` modal, a State opened
from a sibling State's open dropdown, a `hover-visible` opener), no non-`img` profile avatar, and a stylesheet (the theme
marker) on one page only, so navigate.py, dark.py and render.py's reachability paths would have nothing to drive; the committed fixture stays as it is because the generator's tests pin it.
`cp` the two lib files first, then generate, start Next, run, stop Next, and restore:

    cp app/lib/fansly-mirror-pages.ts app/lib/fansly-mirror-build.ts <backup dir>/
    nice -n 10 venv/bin/python scripts/fansly-mirror-check/derive_fixture.py
    X=.scratch/fansly-mirror-check/fixture-capture
    nice -n 10 node scripts/fansly-mirror.mjs --capture $X --plan $X/mirror_plan.json --out app/public/fansly-mirror --lib app/lib
    cd app && nice -n 10 pnpm exec next dev --webpack -p 3091 &
    nice -n 10 venv/bin/python scripts/fansly-mirror-check/render.py --capture $X --plan $X/mirror_plan.json
    nice -n 10 venv/bin/python scripts/fansly-mirror-check/navigate.py --strict
    nice -n 10 venv/bin/python scripts/fansly-mirror-check/dark.py
    pkill -f "next dev --webpack -p 3091"
    cp <backup dir>/fansly-mirror-*.ts app/lib/ && rm -rf app/public/fansly-mirror

On the real tree, `--plan` defaults to `fansly/capture/mirror_plan.json` (the generator's default) and `--capture` is
the capture the mirror was generated from.

render.py opens every page `routableFanslyPages()` lists (`pages.mjs` reads it from `app/lib/fansly-mirror-route.ts`)
in the frame with `?creator=` and clicks every `oi-state-link` and `oi-state-backdrop` a user can reach onto its target page:
at a point inside the wire where `elementFromPoint` is the wire in the frame and the frame in the top page (several points
are tried; a covered wire is hovered first, for `hover-visible` openers). A wire that is `display:none`, zero-size or still
covered is counted as unreachable, not clicked, and the run prints `unreachable wires: N`. It fails a State page that no chain
of reachable wires from a non-State page opens (two States opened only from each other fail), a State page with no reachable
wire back to its parent, and a State page holding an overlay (`.back-drop` or `.cdk-overlay-backdrop`) whose backdrop wire
is unreachable. A dropdown State (no such overlay; its backdrop sits on `body`, under the page) needs no reachable backdrop,
only a way back: its close control or the opener toggle (ASSUMPTION, coordinator decision pending owner veto). An `[data-oi-avatar]`
must be an `img` on `/img?` or carry an inline `background-image` on `/img?`. It checks the four
shadowed landings (`scheduled`, `lists`, `notifications`, `statistics/earnings`) reach their Built pages with no
mirror frame, and fails on a request off localhost, a non-GET request from the mirror frame, a localhost 404, a page
error or an empty pages table. The rendered `innerText` (top document and frame, every opened state) goes through the
generator's `textKinds` (`scripts/fansly-mirror/kinds.mjs`, via `kinds.mjs` here; it strips `\p{Cf}` and soft hyphens
itself) with every kind on: identity (the manifest's identities plus the other people the generator collects from the
same capture docs), ipv4, ipv6, digit-run, email, amount, handle, remote, fansly-host; any hit fails. `--capture` is
required, so the identities are always the ones the mirror was generated from. Screenshots and
`requests.json` go to `.scratch/fansly-mirror-check/render/`; it prints `pages checked: N, failed: M`.

navigate.py finds its targets by structure, not by label: the top bar's openers are the visible `a.oi-state-link`s
outside `[data-oi-nav]` whose href is `home/state-avatar-menu` / `home/state-balance-menu`; an in-frame link is the first
reachable `a[target=_top]` (not a state link) to another mirror page; the generator labels a State's opener toggle
`aria-label="Toggle"` and its close controls `"Close"`. It checks the rail hidden and both openers shown; the avatar and balance menus each open
and close through a reachable state link back to home that is not the opener toggle (when the toggle is the only way back it
clicks it and says so); "close it (backdrop)" runs on the first home State opened from home whose page holds an overlay, and is
printed as skipped with the reason when none does (the dropdown rule above). The in-frame part clicks each page linked from home in turn until one links onward, then clicks onward and goes back
twice; when none does (the real tree: home links only to pages whose onward links sit in the hidden rail) it prints
"two-hop skipped" after one hop and back on each. Likewise the hand-off starts from the first mirror page with a Built
link when home has none (the real tree). Both are ASSUMPTIONs pending owner veto; `--strict` turns either into a
failure and is used on the derived fixture. A failed step does not stop the run: the next part
reloads home and carries on, and every failure is listed at the end; a modified click opens a
new tab with `?creator=` and a plain one stays in the tab; two in-frame clicks and browser back keep `?creator=` without a
reload; mirror → Built hand-off (the first reachable home link to a Built page, Scheduled Posts first);
an A → B creator switch with B's `/users/me` held 2 s never shows A's handle and shows B's after it answers;
`/fansly-manager?creator=fb2` lands on Homepage with `?creator=fb2`; flag-off and denied-role deep links show their
panel with no iframe and no `/users/me` request. Screenshots to `.scratch/fansly-mirror-check/navigate/`.

dark.py: in dark mode no screencast frame of the frame's box is light during load and `bright-theme` is off at
readyState interactive; in light mode no frame is darker than the settled page and `bright-theme` is on; toggling the
app theme light → dark → light flips `bright-theme` each time. Screenshots to `.scratch/fansly-mirror-check/dark/`.

Negative controls, each a switch that must make its run fail (`...` = render.py's `--capture`/`--plan`):

    render.py ... --plant-remote-img   # a remote <img> planted in the first page
    render.py ... --empty-table        # routableFanslyPages({})
    render.py ... --plant-ip           # <p>198.51<span hidden>x</span>.100.7</p>
    render.py ... --plant-name         # <p>velvet<span hidden>x</span>moth</p> (the fixture creator)
    navigate.py --frame-flag-off       # a mirror iframe left mounted on the flag-off panel
    dark.py --force-light-paint        # the frame's dark boot script disabled

`derive_fixture.py --sibling-cycle` adds two thread States opened only from each other; render.py on a mirror generated from it
must fail both. The derived thread's `hover-visible` opener uses Fansly's real pattern: shown only under a `.hover-zone` class
that Fansly's JS adds on mouseenter. The generator emits a `:hover` twin of every rule keyed on a class in `HOVER_CLASSES`
(`scripts/fansly-mirror/css.mjs`), so render.py reaches that opener by hovering.

The generator's own guard runs without a server: `node scripts/fansly-mirror.mjs --check`. Nothing is exported,
served or deployed until `--check` and render.py are green on the same tree.
