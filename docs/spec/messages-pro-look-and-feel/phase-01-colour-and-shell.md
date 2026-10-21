# Phase 01 — Colour and shell

**Objective.** Messages Pro draws in the Infloww palette (blue accent, grey bubbles and PPV card, near-black shell, Infloww's dividers and text) under either app theme while every other screen keeps the App accent, and at desktop width in the app the Window header is Messages Pro's first row, holding the Top bar's sidebar toggle, clock and avatar, with the Top bar's other controls placed as decided below.

## Problem Statement

Someone who knows Infloww's Messages Pro opens ours at 1440 and sees two things that are not Infloww before they read a word. First, the colours are Inflowwww's purple accent and blue-grey panels (ADR-0001), not Infloww's blue on near-black. Second, there is a 56px Inflowwww Top bar above the Window header (`app/components/shell/AppShell.tsx:58-63`), so the Creator tabs are the second row, not the first. The person also switches the app to light mode on another screen and comes back to a half-light Messages Pro, because today every Messages Pro colour follows `html[data-theme="light"]` (`app/app/globals.css:119-133`).

## Solution

Messages Pro's root re-declares the app's colour variables to the Infloww palette for everything rendered inside it, so its own components and the shared ones it uses (menus, the switch, the bell's panel, the vault picker) all take Infloww's values, and nothing outside it changes. Where the Colour inventory maps one token class to two different Infloww values (for example, the shell and the PPV card), the element gets its own literal in its JSX. Outgoing bubbles turn blue, incoming bubbles grey, and the PPV card grey with its price line. Messages Pro looks the same under the light and the dark app theme: Infloww's dark palette.

At desktop width (lg and up), on Messages Pro and its Deep links in the app, the Top bar is not rendered and the panes take the full window height. The Window header's right end then reads SFW, the Extras overflow, then the sidebar toggle, the clock and the avatar, in the Top bar's order. The Top bar's SFW is already there. Its bell has a home in Messages Pro, the Notifications Fan List button, which opens the same panel. The scope switcher and the error badge become two more Inflowwww extras of the Window header: in its Extras overflow with the Legacy flag off, and in the header itself with it on, like All Models. Below lg, and on every other screen, the Top bar is unchanged. A Pop-out window is unchanged: it has no Top bar today and gains none of the moved controls.

## User Stories

1. As an Employee who knows Infloww, I want Messages Pro's accent to be Infloww's blue, so that selected rows, active tabs, links and primary buttons read as Infloww.
2. As an Employee, I want my outgoing bubbles blue and the Fan's incoming bubbles grey, so that the Thread reads like Infloww's.
3. As an Employee, I want the PPV card grey with its price line in Infloww's colours, so that a PPV looks like Infloww's PPV card.
4. As an Employee, I want the shell (Window header, Fan tabs strip, pane backgrounds) near-black as in Infloww, so that the whole screen reads as Infloww's.
5. As an Employee, I want dividers and primary, dim and muted text in Infloww's values, so that borders and labels match Infloww's contrast.
6. As an Employee, I want the menus, popovers, switches and pickers that open inside Messages Pro (Extras overflows, Kebab menu, Notifications panel, vault and template pickers, emoji bar, gallery) in the Infloww palette too, so that nothing opened from Messages Pro flashes back to purple.
7. As an Employee who opens a portal-mounted picker from Messages Pro (vault, templates, tag Creators, gallery, emoji, split inbox, the message list's portals), I want it in the Infloww palette even though it mounts outside the pane, so that it matches the screen it came from.
8. As an Employee on any other screen (Dashboard, Settings, Inbox, Group chat, vault), I want the App accent and the app's tokens unchanged, even where that screen reuses a component that Messages Pro also uses, so that the colour switch stays inside Messages Pro (ADR-0010).
9. As an Employee who uses the light app theme, I want Messages Pro to show the same Infloww palette as under the dark theme, so that the screen is never half light and half Infloww.
10. As an Employee who uses the light app theme, I want the scrollbars and native inputs inside Messages Pro drawn dark, so that they match the near-black shell.
11. As an Employee at desktop width, I want no Inflowwww Top bar above Messages Pro, so that the Window header with the Creator tabs is the first row, as in Infloww.
12. As an Employee at desktop width, I want the panes to reach the bottom of the window once the Top bar is gone, so that the 56px is given to the panes and does not become a gap.
13. As an Employee at desktop width on Messages Pro, I want the sidebar toggle at the Window header's right end, opening the menu drawer over the panes as today, so that I can still reach every other screen.
14. As an Employee at desktop width, I want the time zone label (the Top bar's clock) at the Window header's right end, so that I still see which offset the times are in.
15. As an Employee at desktop width, I want the avatar at the Window header's right end, opening the same menu (switch Employee, light/dark mode, log out), so that I can still switch Employee, change the theme or log out from Messages Pro.
16. As an Employee, I want the Window header's right end to keep Infloww's own controls first (SFW, then the Extras overflow) and ours after them, so that the Infloww skeleton reads first.
17. As an Employee at desktop width, I want the Top bar's bell to have Messages Pro's Notifications Fan List button as its home, so that the notifications panel stays one click away without a second bell.
18. As an Owner on Messages Pro at desktop width with the Legacy flag off, I want the scope switcher inside the Window header's Extras overflow, so that I can still choose which Creators take part in All Models without leaving Messages Pro.
19. As an Owner with the Legacy flag on, I want the scope switcher in the Window header itself, next to the other inline extras, so that it behaves like All Models does (ADR-0003).
20. As an Owner on Messages Pro at desktop width, I want the error badge's 24-hour error count and its triage popover reachable from the Window header (Extras overflow with the flag off, inline with it on), so that I can still triage errors without leaving the inbox.
21. As an Employee, I want the scope switcher and the error badge, where they now sit in Messages Pro, to carry the "Inflowwww extra" tooltip and appear in the extras catalogue, so that they are marked as ours like every other extra.
22. As an Employee on a phone or below lg, I want the Top bar exactly as today on Messages Pro, so that phone navigation is unchanged.
23. As an Employee in a Pop-out window, I want Messages Pro exactly as today (no Top bar, no sidebar toggle, no avatar), so that the Pop-out window stays the full-window Messages Pro of ADR-0002.
24. As an Employee on a Messages Pro Deep link at desktop width, I want the same shell as on the Messages Pro index, so that both routes look alike.
25. As a reviewer, I want the colour check in the Messages Pro test file to still find no colour class and no colour literal in the Geometry token module or in our literals, so that ADR-0001's Geometry rule keeps holding.
26. As a reviewer, I want the Visual loop harness to stay `ok=True` and to check the shell and the palette in a real browser, so that a regression in either fails the run.
27. As a reviewer, I want every colour row on the Compare page to read "matched" once this Phase lands, so that the colour gap is visibly closed.
28. As a maintainer, I want the Messages Pro palette written in one Messages Pro component, so that the next colour change is one edit and not a hunt across the Regions.

## Implementation Decisions

- **Owns.**
  - The app shell (`AppShell`) and the Top bar module (`TopBar`).
  - The Window header (`WindowHeader`) and its Extras overflow (`WindowHeaderExtras` in `MessagesProExtras`).
  - A new Messages Pro component, the Infloww palette (`InflowwPalette`, in `app/components/chat/`), and the Messages Pro root (`MessagesPro`) that wraps its tree in it.
  - Every Messages Pro element whose Colour inventory row maps its token class to an Infloww value the palette does not already give it (the bubbles, the PPV card, any token split in two).
  - The portal roots under `app/components/chat/` (gallery, tag Creators picker, template picker, split inbox, message list, vault picker, emoji bar).
  - The scope switcher (`ScopeSwitcher`) and the error badge (`ErrorBadge`), for their Messages Pro placement only.
  - The extras catalogue (`openinflowwwwExtras`), which gains two entries.
  - Our literals (`messagesProOurs`), which gain the Geometry of the moved controls.
  - The Visual loop harness's desktop and phone shot checks (`scripts/ui-shots.sh`). The harness gains no new shot and no new state.
  - The Compare page's colour rows (status only, `docs/screenshots/messages-pro-compare.md`).
  - The Messages Pro section of `docs/messages-pro-parity.md`, if it describes the Top bar or the colours.

- **Interfaces.**
  - `InflowwPalette` exposes a wrapper component that renders its children inside an element whose inline style re-declares the app's colour variables (`--color-bg`, `--color-bg-elev-1`, `--color-bg-elev-2`, `--color-panel`, `--color-fg`, `--color-fg-dim`, `--color-muted`, `--color-border`, `--color-border-light`, `--color-accent`, `--color-accent-hover`, and any other `--color-*` the Colour inventory maps) to their Infloww palette values, and sets `color-scheme: dark`. It also exposes a hook that returns that same style inside the wrapper and nothing outside it, for portal roots. The values are literals in this one component file, taken from the Colour inventory. No other module reads them.
  - `MessagesPro` wraps its root in `InflowwPalette`. Because the index route, the Deep link route and the Pop-out window all render `MessagesPro` (ADR-0002), all three take the palette.
  - Each portal root under `app/components/chat/` spreads the hook's style onto its outermost element. Used outside Messages Pro (Settings, vault, compose), the hook returns nothing and the portal keeps the app's tokens.
  - `AppShell` gains a small shell-controls context, provided only in its non-Pop-out branch. It exposes the sidebar toggle's handler, its expanded state and the id of the element it controls, which are the three values the Top bar receives as props today. On an in-app Messages Pro route (`isPopoutRoute`) at desktop width (`useIsDesktop`), `AppShell` does not render the Top bar and sets `--shell-top` to 0 on its main element, as the Pop-out window branch already does. Everywhere else it renders the Top bar as today. Because `useIsDesktop` follows the media query, resizing below lg brings the Top bar back and `--shell-top` returns to its default, with no reload.
  - `TopBar` exports its avatar menu and its time zone label as components, so that the Window header renders the same ones. The Top bar's own rendering is unchanged.
  - `WindowHeader` reads the shell-controls context. When the context is present and the view is desktop, its right end renders, after SFW and the Extras overflow, the sidebar toggle (accessible name "Toggle sidebar", with `aria-expanded` and `aria-controls` from the context), the time zone label, then the avatar menu (accessible name "Account menu"). When the context is absent, which means a Pop-out window, it renders none of them.
  - `WindowHeaderExtras`, with the Legacy flag off and the shell-controls context present (in the app, never in a Pop-out window), gains two rows after Group chat. "Scope switcher" opens the scope switcher's list (include toggles and scope pick). "Errors" shows the 24-hour error count, with "none" at zero, and opens the error badge's popover. With the flag on and the context present, the Window header renders `ScopeSwitcher` and `ErrorBadge` inline, after All Models' place on the right-hand side and before SFW. The error badge keeps its own rule there and hides at zero. Each one's tooltip is `extraTitle(...)`. With the context absent (a Pop-out window) neither appears, overflow or inline, so the Pop-out window keeps today's header (User Story 23; it has no Top bar today, so it loses nothing).
  - The extras catalogue gains `{ name: "Scope switcher", automation: false, off: ["Window header overflow"], on: ["Window header"] }` and `{ name: "Error badge", automation: false, off: ["Window header overflow"], on: ["Window header"] }`. The comment's count of extras goes up by two.
  - Our literals gain a `WindowHeader` entry for the moved controls' Geometry: the sidebar toggle and the avatar reuse the Window header's icon-button size, and the gap is the right-hand group's gap. These are class strings only, with no colour.

- **Schema.** None. This Phase reads no new data and stores nothing. The theme stays in its existing `chatterly:theme` key, and the scope include-set in its existing key.

- **Contracts.** None cross a process boundary. Two in-app contracts stay fixed: the `--shell-top` custom property (0 means no shell row above the page, `app/app/globals.css:244-247`), and the accessible names "Toggle sidebar", "Account menu" and the `#app-sidebar-drawer` id, which the harness's sidebar check reads (`scripts/ui-shots.sh:636-644`).

- **How the palette is placed.** The palette works by re-declaring the variables for Messages Pro's subtree, not by swapping every class for a literal. Rung 1 settles this. 22 files outside Messages Pro import components from `app/components/chat/` (`grep -rln "@/components/chat/" app/app app/components`, excluding chat and messages-pro), so swapping classes for literals would recolour Settings, vault and compose screens and break ADR-0010's App accent rule. The variable approach is how the light theme already works (`app/app/globals.css:115-133`, a non-inline `@theme`, so every utility reads `var(--color-*)`). The shared tokens in `globals.css` are not changed, the `--if-*` tokens are not read (ADR-0009), and the Geometry token module holds no colour.
  This is the "one shared block" case ADR-0010's first ASSUMPTION names. It reads no `--if-*` token, so ADR-0009's scope is unchanged; ADR-0010 gains one sentence, when this Phase lands, recording that its values sit in `InflowwPalette`'s inline style.
  ASSUMPTION: ADR-0010's "values written in Messages Pro's JSX" is met by one Messages Pro component that writes them as inline custom properties, plus per-element literals where a token splits. Overturned if the human reads ADR-0010 as per-element literals only, in which case shared chat components need a colour prop from every Messages Pro caller (precedent: `NotificationBell`'s `classNames`).

- **Light theme.** Under `html[data-theme="light"]`, Messages Pro shows the same Infloww dark palette as under dark. The wrapper's inline declarations are nearer to every Messages Pro element than the `html` rule is, so they win. `color-scheme: dark` keeps native controls dark. Outside Messages Pro the theme works as today, and the avatar menu's "Light mode / Dark mode" row still flips it, for the rest of the app.
  ASSUMPTION: Messages Pro stays Infloww-dark under the light theme, because the plan names the near-black shell as the default and the Clone is dark-only (`ui-redesign/infloww-exact/messages.html:13-29`). That is rungs 3 and 5: one value set per Colour inventory row. Overturned if the human wants Infloww's light palette under the light theme. The Infloww stylesheet does carry `.theme-light` and `.theme-dark` sets. In that case `InflowwPalette` gains a second value set keyed on `useTheme`, and the Colour inventory gains a light column.

- **Where the Top bar's controls go.**
  - Sidebar toggle, clock and avatar go to the Window header's right end. The plan settles this (rung 2). Their order is the Top bar's own order (rung 3), placed after the Infloww controls (plan: "the Infloww skeleton reads first"). The "clock" is the Top bar's UTC-offset time zone label (`TopBar.tsx:28-35`), reused as is.
    ASSUMPTION: the moved controls go after SFW and the Extras overflow, not between them. Overturned if the human wants the avatar at the very end with the overflow last.
  - SFW: not moved. The Window header's SFW uses the same store (`WindowHeader.tsx:38`), so the Top bar's copy has nothing to add.
  - Bell: not moved. Messages Pro's Notifications Fan List button is the bell's `messages-pro` variant, with the same panel and filters (`app/components/NotificationBell.tsx:22-28`). What the Top bar variant counts (arrivals since load) is not shown at desktop on Messages Pro. Phase 2's Notifications toggle governs that button.
    ASSUMPTION: losing the arrival counter on Messages Pro at desktop is acceptable, because the Notifications button shows the Creator's OnlyFans count instead (rung 3, the existing variant). Overturned if the human wants the arrival counter kept, in which case it becomes a third Window header extra.
  - Scope switcher and error badge become Window header extras, overflow with the flag off and inline with the flag on (rung 3: ADR-0003 and All Models' own placement). The scope switcher's own comment asks for a persistent home for the include toggles (`app/components/ScopeSwitcher.tsx:13-15`), and `useChatList` reads that include set for Messages Pro's All Models fan-out, so dropping it would strand the setting.
    ASSUMPTION: these two shell controls are catalogued as Inflowwww extras of the Window header rather than left only on other screens. Overturned if the human prefers them off Messages Pro at desktop, which is smaller (one fewer catalogue entry each) and reachable from any other screen's Top bar.
    ASSUMPTION: in the overflow, the error badge is a row that is always present, showing "none" at zero, so the catalogue's host count does not depend on live error data. Overturned if the human wants it hidden at zero there too, in which case the extras audit's fixture stubs a non-zero count.
- **No flash.** The Top bar is dropped through `useIsDesktop`, the same hook that already mounts the Window header only on desktop (`MessagesPro.tsx:406`). The server render, and the first client render before the media query resolves, show the Top bar as today.
  ASSUMPTION: the one-frame Top bar on first desktop load is accepted (rung 3, the Window header has the same frame). Overturned if the visual loop shows a visible jump, in which case the hide moves to a pathname-keyed `lg:hidden` and an `lg:` `--shell-top` class.
- **Toasts.** `NotificationToaster` keeps its `top-14` offset. At desktop on Messages Pro, toasts start 56px down, below the 46px Window header, which is acceptable and not changed.
- **Language box and pop-out icon.** The plan says SFW, language and pop-out "already live" at the Window header's right end. Observation: our Window header has SFW and the Extras overflow only (`WindowHeader.tsx:32-50`). The Clone has a language box and a picture-in-picture button there (`messages.html:600-605`). This Phase does not build them. See Out of Scope.

## Testing Decisions

The highest seam is the Visual loop harness (`scripts/ui-shots.sh`). It runs the real app in a real browser, so it is the only seam that sees computed colours, the light theme and the shell's height. It carries the colour and layout checks. One component seam carries the shell wiring jsdom can see, and the existing guards keep running unchanged.

- **Visual loop harness, existing shots, new checks.** No new shot or state.
  - The `messages-pro-desktop` shot gains:
    - "no Top bar above the Window header": the "Window header" region's top is 0 and no `banner` landmark is visible.
    - "Toggle sidebar, the time zone and Account menu sit in the Window header": the existing sidebar check must keep passing against the moved toggle.
    - "CO1–CO7 match the Colour inventory": one `getComputedStyle` sample per colour Compare row, compared with the inventory's Infloww value: the selected Fan List row's accent (CO1), the fixture's own message (CO2), the Fan's message (CO3), the PPV bubble and its price line (CO4), the Window header and the pane backgrounds (CO5), a Fan List row divider (CO6), and a Fan name and its preview for the primary and dim text (CO7). Each check's name carries its row ID, so a "matched" status on the Compare page has a named passing check behind it.
    - "same colours under `data-theme=light`": set the attribute in the page, re-read the same samples, restore it.
    - "App accent outside Messages Pro": open the sidebar drawer (it is rendered by `AppShell`, outside the palette's subtree, as `check_sidebar` already does) and read the active link's accent; it is the App accent, not Infloww's blue.
    - The existing `check_panes_full_height`, so the panes end at the viewport's bottom.
  - The `messages-pro-phone-list` shot gains "the Top bar is shown below lg".
  - The `messages-pro-popout` shot's `check_no_chrome` stays as is. It now also proves that the moved controls are absent in a Pop-out window.
- **Component seam, `app/app/messages-pro/page.render.test.tsx`.** Today's `pageTree` renders the page without the shell (`page.render.test.tsx:220-237`; `page.tsx` and `layout.tsx` add none), so this Phase adds one describe that renders `<AppShell>{pageTree(url)}</AppShell>` with the existing harness (relay mocked by path, `matchMedia` stubbed to desktop, pathname `/messages-pro`).
  ASSUMPTION: wrapping the existing `pageTree` in `AppShell` for one describe is the page-through-shell seam (rung 3, `AppShell.test.tsx` already renders `AppShell` around a child). Overturned if `AppShell`'s providers clash with `renderWithProviders`, in which case these cases move into `AppShell.test.tsx` with `MessagesPro` as the child. The Top bar is absent. The Window header region holds "Toggle sidebar", the time zone and "Account menu", in that order after SFW. The toggle opens the "Menu" dialog over the panes, and Escape closes it. Below lg the Top bar is present and the Window header is not. `AppShell.test.tsx`'s Messages Pro desktop describe is updated to match: no `banner` at desktop on `/messages-pro`, `--shell-top` 0 on main, the Top bar as today on `/` and below lg, and the Top bar back after the `matchMedia` stub flips to below lg and the tree re-renders (its existing `rerender` pattern, `AppShell.test.tsx:48-53`).
- **Palette seam, new `app/components/chat/InflowwPalette.test.tsx`.** The hook returns the palette style inside `InflowwPalette` and nothing outside it, and a real portal root (`VaultPicker`) carries the palette's custom properties on its outermost element when rendered inside the wrapper and none when rendered outside it. This is the jsdom half of User Stories 7 and 8; the harness's drawer check is the browser half.
- **Pop-out seam, `app/app/messages-pro/windowed.test.tsx`.** A Pop-out window's Window header Extras overflow has no "Scope switcher" or "Errors" row, and with the flag on the header renders neither inline.
- **Extras audit, `app/app/messages-pro/extras.test.tsx`, unchanged code, new entries.** The catalogue's two new entries are found in the Window header Extras overflow with the flag off and in the Window header with it on, with the "Inflowwww extra" tooltip.
- **Colour check, `app/lib/messagesPro.test.ts`, unchanged.** It must still pass. It walks every Geometry leaf and every `ours` leaf, including the new `WindowHeader` entry, for colour classes and literals (`messagesPro.test.ts:278-294`). The palette's literals live in `InflowwPalette`, which is not a token module and is not walked. The Acceptance block greps both token files directly, as the parent effort's Phase 6 did.

Prior art: the parent effort's Phase 6 Acceptance (`docs/spec/phase-06-geometry-pass.md`), the Pop-out window's `--shell-top` override (`AppShell.tsx:48-56`), `NotificationBell`'s `classNames` for shared components, and the harness's `check_sidebar` and `check_no_chrome`.

## Acceptance

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
# the Geometry token module and our literals still hold no colour (ADR-0001, ADR-0010)
if grep -nE '(^|[ "`:])(bg|text|border|ring|fill|stroke|outline|shadow|divide|placeholder|caret|decoration|from|via|to)-(bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current)([-/ "`]|$)' app/lib/messagesPro.ts app/lib/messagesProOurs.ts; then echo "colour class in a token module"; exit 1; fi
if grep -nEi '#[0-9a-f]{3,8}([^0-9a-z]|$)|rgba?\(|hsla?\(|oklch\(' app/lib/messagesPro.ts app/lib/messagesProOurs.ts; then echo "colour literal in a token module"; exit 1; fi
# the shared tokens are untouched: the App accent stays everywhere else
git diff --quiet "$(git merge-base HEAD main)" -- app/app/globals.css
# the palette lives in one Messages Pro component, and Messages Pro wraps its tree in it
test -f app/components/chat/InflowwPalette.tsx
grep -q "InflowwPalette" app/components/chat/MessagesPro.tsx
# the two shell controls are catalogued extras
grep -q '"Scope switcher"' app/lib/openinflowwwwExtras.ts
grep -q '"Error badge"' app/lib/openinflowwwwExtras.ts
# the Phase's seams: colour check, shell, page, extras audit, Pop-out window
ALLOW_ANONYMOUS_ADMIN=1 pnpm -C app exec vitest run lib/messagesPro.test.ts components/chat/InflowwPalette.test.tsx components/shell/AppShell.test.tsx app/messages-pro/page.render.test.tsx app/messages-pro/extras.test.tsx app/messages-pro/windowed.test.tsx
# full suite (typecheck, lint, vitest)
.scratch/messages-pro-look-and-feel/suite.sh
# no relay/service change in this Phase
git diff --quiet "$(git merge-base HEAD main)" -- service/
# Visual loop harness: ok=True, with the shell and palette checks present and passing
scripts/ui-shots.sh
python3 -c 'import json,sys; r=json.load(open("docs/screenshots/messages-pro-report.json")); d=next(s for s in r["shots"] if s["name"]=="messages-pro-desktop"); n=" ".join(c["name"] for c in d["checks"]); need=["Top bar","data-theme=light","App accent outside"]+[f"CO{i}" for i in range(1,8)]; miss=[k for k in need if k not in n]; print("missing checks:",miss); sys.exit(0 if r["ok"] and not miss else 1)'
# flag-on run: the inline scope switcher and error badge do not overflow the Window header
OPENINFLOWW_LEGACY_AUTOMATIONS=1 UI_SHOTS_SWEEP=1 scripts/ui-shots.sh
# the Compare page: rows CO1-CO7 and SH1-SH2 are all present and read "matched" (Status is the last cell, Phase 0's format)
python3 -c 'import sys; need=[f"CO{i}" for i in range(1,8)]+["SH1","SH2"]; st={}
for l in open("docs/screenshots/messages-pro-compare.md"):
  c=[x.strip() for x in l.strip().strip("|").split("|")]
  if l.startswith("|") and c[0] in need: st[c[0]]=c[-1]
bad={k:st.get(k,"absent") for k in need if st.get(k)!="matched"}; print("not matched:",bad); sys.exit(0 if not bad else 1)'
# manual: open messages-pro-desktop.png beside clone-messages-pro.png and the real Infloww thread capture; confirm blue outgoing, grey incoming, grey PPV card, near-black shell, and the Window header as the first row
# manual: switch the app to light mode from the avatar menu, reload /messages-pro at 1440 and confirm Messages Pro is unchanged while / is light with the purple App accent
# manual: at 1440 open the Window header Extras overflow; the Scope switcher row toggles a Creator out of All Models and the Errors row opens the error popover
```

## Depends on

- Phase 0 — Measure and pin: the Colour inventory (each token class mapped to its Infloww value), which the palette's values, the per-element splits and the harness's expected colours are read from, and the Compare page whose colour rows this Phase flips to "matched".

## Out of Scope

- Infloww's light palette under the light theme. One value set meets the plan, which names the near-black shell. See the light-theme ASSUMPTION.
- The language box and the pop-out (picture-in-picture) button at the Window header's right end. The plan says they already live there, but they do not (`WindowHeader.tsx:32-50`). The app has no language setting to drive a language box, and the sidebar's "Messages Pro ↗" already opens a Pop-out window (`Sidebar.tsx:89`), so a second entry point is not needed (YAGNI).
  They stay visible as Compare rows with ticket `unowned` (Phase 0, User Story 16), so Phase 6's sign-off sees them; this Phase's Acceptance does not grade them.
  ASSUMPTION: the plan's "language, pop-out already live there" is read as a mistaken premise, not as a request to build them. Overturned if the human wants them, in which case the Compare page's Window header rows carry them as unmatched and a later ticket adds them.
- Hiding the Top bar below lg. The plan says "at desktop width", and the phone layout keeps it.
- Changing the shared `--color-*` tokens or the `--if-*` tokens. ADR-0010 and ADR-0009 forbid both.
- Any Geometry change beyond the moved controls' own sizes. Phases 2–5 own the Regions' Geometry.
- The Notifications toggle. Phase 2 owns it.
- Recolouring Group chat (`app/app/group/page.tsx`). It is not Messages Pro and keeps the App accent.

## Further Notes

Every open question is decided above, where it arises, with its ASSUMPTION line. In summary:
- The palette is placed by re-declaring variables on the subtree, not by swapping classes. Rung 1 (the shared chat components) and rung 3 (the light theme's own mechanism).
- Under the light theme, Messages Pro stays Infloww-dark. Rungs 3 and 5.
- Sidebar toggle, clock and avatar go after SFW and the Extras overflow, in Top bar order. Rungs 2 and 3.
- The bell's home is the Notifications Fan List button, with no move. Rung 3.
- The scope switcher and the error badge become catalogued Window header extras. Rung 3 (ADR-0003).
- The Top bar is hidden through `useIsDesktop` and the one-frame flash is accepted. Rung 3.
- The language box and the pop-out icon are not built. Rung 5.

## Review

Reviewer: codex, 2026-10-15. Blind call (B) and draft call (D), both exit 0 within the 15-minute bound, outputs fresh and non-empty.

- B1 (alternatives: keep app colours, scoped block, reuse `--if-*`, change shared tokens): **reject**, no change. The spec already takes the scoped block and rules out the other three on ADR-0010, ADR-0009 and the plan.
- B2 (light-theme behaviour unspecified by the plan): **reject**. Already decided under "Light theme" with its ASSUMPTION; ADR-0010 hands this question to this spec.
- B3 (colour reaches Messages Pro through utility classes, and the colour test checks only token leaves): **reject** as a gap in this spec. Re-declaring `--color-*` on the subtree recolours the utility classes, and the harness reads computed colours; the colour test keeps its narrower ADR-0001 job.
- B4 (control inventory, breakpoint and resize): **partial**. The spec already places scope, status (error badge), SFW and bell, and the breakpoint is lg. Resize was missing: "Interfaces" now says resizing below lg brings the Top bar back, and `AppShell.test.tsx` gains a re-render case.
- B5 (`ok=True` has no colour assertion, so "matched" must be backed by a check): **accept**. The harness colour check is now one sample per CO1–CO7, named by row ID, and the Acceptance requires every ID among the check names.
- B6 (test at the integrated shell seam, including the App accent on a non-Messages-Pro surface): **accept**. Added the drawer's "App accent outside Messages Pro" check, the page-through-`AppShell` describe and the palette seam.
- B7 (TopBar/AppShell absent from the workspace): **reject**. The workspace path list named `app/components/{TopBar,AppShell}.tsx`; the files are `app/components/shell/AppShell.tsx` and `TopBar.tsx` in the repo. A review-workspace defect, not a spec defect, but it means codex did not read the shell source.
- B8 (premise falsified if geometry or controls still dominate after the palette matches): **reject**. The plan's colour decision binds (constraint), and Phases 2–5 own the geometry gaps.
- B9 (the real reference may be theme-dependent): **reject**. Already recorded: Infloww's stylesheet has `.theme-light`/`.theme-dark`, and the light-theme ASSUMPTION names that as its overturn.
- D1 (language box and pop-out still missing, so Phase 1 passes with an incomplete header): **partial**. Still out of scope (the plan's premise is false, `WindowHeader.tsx:32-50`), but now they stay on the Compare page as `unowned` rows so sign-off sees them.
- D2 (new extras would change the Pop-out window, against User Story 23): **accept**. Observed: `WindowHeader` is shared with the Pop-out window. The two extras now render only when the shell-controls context is present, and `windowed.test.tsx` asserts their absence in a Pop-out window.
- D3 (homing the scope switcher and error badge goes beyond the plan): **reject**. Hiding the Top bar, which the plan does ask for, strands both controls, and the scope include-set drives All Models (`ScopeSwitcher.tsx:13-15`). The header's "evidence never shrinks the goal" rule says spec and flag it, and the ASSUMPTION lines already give the smaller alternative.
- D4 (`page.render.test.tsx` does not render `AppShell`): **accept**. Observed `pageTree` at `page.render.test.tsx:220-237` with no shell. The spec now adds a describe wrapping `pageTree` in `AppShell`, with an ASSUMPTION and a fallback into `AppShell.test.tsx`.
- D5 (five samples leave divider, text, portals and other screens untested): **accept**. Seven samples now (CO1–CO7), plus the drawer accent check and a new `InflowwPalette.test.tsx` covering the hook and `VaultPicker` inside and outside the wrapper.
- D6 (the Compare grep passes on a page with most colour rows deleted): **accept**. The Acceptance now requires CO1–CO7 and SH1–SH2 by ID, each with Status `matched` in Phase 0's table format. The page's absence from this checkout is expected, because Phase 0 writes it (Depends on).
- D7 (the wrapper overturns ADR-0010's "one shared block" ASSUMPTION, and ADR-0009 must be addressed): **partial**. "How the palette is placed" now says this is that case, that ADR-0009's scope is unchanged because no `--if-*` token is read, and that ADR-0010 gains one sentence when the Phase lands.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- White, CO2 blue vs grey: **accept** (decided in Phase 0). Phase 0's Clone px rule now says a colour the plan names beats the capture, so CO2's inventory value is the Clone's `#4166f6` (`messages.html:246`) and this Phase's CO2 harness sample compares against it. No change here: Story 2 and the Solution already say blue.
- Green/Black, gate strictness: **accept, unchanged here**. CO1–CO7 and SH1–SH2 keep strict `matched` (plan:43-44); the relaxed "named remainder" applies only to Phases 2–5.
- Red, "matched" is self-set and only the CO rows have a browser check: **reject** for this Phase. Its colour rows are exactly the ones with a named, passing harness check per row ID (Testing Decisions); SH1–SH2 have the "no Top bar" and sidebar checks.
- Yellow, palette scoping and the scope switcher / error badge homes: **accept** (no change), they are the decisions.
- Blue, CONTEXT.md's stale "language, pop-out already live there": **accept**. CONTEXT.md's Window header entry now says they do not exist today (`WindowHeader.tsx:32-50`) and are `unowned` Compare rows, matching this spec's Out of Scope.
- Black/Green, Phase 4's raw hex: **accept** (decided in Phase 4). Phase 4 now writes its colours through `InflowwPalette`'s variables where one holds the value, so the "one edit" promise of Story 28 holds; a literal only where none does.
