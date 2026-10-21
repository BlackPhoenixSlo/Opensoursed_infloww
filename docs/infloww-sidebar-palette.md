# Infloww sidebar and theme palette: REA / static extraction (2026-10-18)

Infloww's sidebar (aside + HB menu) and its dark and light colour tokens, for the app shell and Messages Pro, and where
each lands in our code. Complements `docs/infloww-of-manager-rea.md` §1.4 (rail order) and §3 (dark `--tc-*` / HB tokens).

## Method and sources

- **App shell SPA:** `~/Downloads/infloww-remote-web/index.9fc9db54.css` (aside module `_dwdgg` @1740546, platform selector
  `_117te` @1743089, `.hb-menu` rules, HB `.theme-dark` @6063030 / `.theme-light` @6084086) and `index.9f50f370.js`
  (`themeColorConfig` @4453124: `default` = light, `dark` = dark).
- **Messages Pro SPA** (`embeded-infloww-messagepro2.infloww.com/35299278530/`): asset URLs read from the running Infloww
  app's HTTP cache, then `css/main-4mKZVmFO.css` (HB `.theme-dark` / `.theme-light`, 405 tokens each) and `css/ui-Btk_cOjU.css`
  (`:root` `--tc-*` light defaults @455443) fetched into a fresh `/tmp` dir and read with `python3 -I`. Nothing executed.
- **Live capture was not possible:** Infloww.app runs without a remote-debugging port and Chrome :9222 has no Infloww tab,
  so REA's browser tools had no Infloww target. Restarting the owner's Infloww session was not done.
- **Sampled** = pixel read from the owner's screenshots (expanded and collapsed sidebar, 2x). Every sampled value matched
  a token composited on `#000`, so all values below are **extracted** unless marked sampled or inferred.

## 1. Sidebar geometry (extracted)

| what | value | source |
|---|---|---|
| width expanded / collapsed rail | 256px / 60px | `body{--nav-width}`, `.navCollapsed{--nav-width:60px}` |
| aside background | `--element-reverse-emphasis-00` | `._aside_dwdgg_1` |
| menu padding | 12px (`--sizing-named-mini`) | `.hb-menu` |
| item | 8px 12px padding, 8px radius, 16px / 500 (`body1-strong`); 36px tall, 8px apart (sampled) | `.hb-menu .hb-menu-item` |
| sub-menu | 16px indent, 8px above each item | `.hb-rc-menu-sub.hb-rc-menu-inline` |
| header gap below platform card | 24px | `._asideHeader_dwdgg_43` |
| platform label | 16px strong, `--tc-T0` | `._selectPlatform_117te_1` |
| collapsed | icons only, label hidden; groups open as a pop-up submenu (we link to the group's first page instead) | `hb-menu-item-collapsed`, `_innerHbMenuPopup` |

## 2. Colours: app shell

HB tokens (sidebar, title bar):

| role | HB token | dark | light | screenshot (dark, sampled) |
|---|---|---|---|---|
| aside / chrome | `element-reverse-emphasis-00` | `#000000` | `#ffffff` | `#000000` |
| idle item text + icon | `element-emphasis-01` | `rgba(255,255,255,.62)` | `rgba(0,0,0,.62)` | `#9e9e9e` |
| selected item text, platform name | `element-emphasis-00` | `#ffffff` | `#000000` | `#ffffff` |
| hover + selected fill | `surface-level-02-emphasis-01` | `rgba(255,255,255,.055)` | `rgba(0,0,0,.055)` | `#0e0e0e` |
| platform card, divider, pop-out button | `surface-level-02-emphasis-00` | `rgba(255,255,255,.09)` | `rgba(0,0,0,.09)` | `#171717` |
| count badge | `signal-stop` | `#fb609f` | `#ff5c9e` | `#e96a9e` (anti-aliased) |
| page surface | `surface-level-00-emphasis-opaque-00` | `#0d0d0d` | `#f2f2f2` | |
| panel / menu | `surface-level-01-emphasis-opaque-00` | `#171717` | `#ffffff` | |
| signal go / guide / caution | | `#58a744` / `#05a2dc` / `#af9423` | `#52b03b` / `#00a4e1` / `#b8991a` | |
| primary action | `element-action-primary-emphasis-00` | `#f88056` | `#fe7d50` | |

Legacy `--tc-*` (pages), light column (dark is in `infloww-of-manager-rea.md` §3): T0 `#000000`, T1 `#151515`, T2 `#666666`,
T3 `#999999`, T4 `#d9d9d9`, B1 `#f5f5f5`, Home-B1 `#f5f5f5`, B-nav `#ffffff`, B-popover `#ffffff`, B-model-hover `#e4e4e4`,
B-model-active `#d7e4ff`, L1 `#e6e6e6`, M1 `#3467ff`, D1 `#ff7c71`, W1 `#ffa15f`, amount-bg `#f0f0f0`.

In our code: `app/app/globals.css` `--color-nav-*` (the four sidebar rows above, both themes) and the
`html[data-theme="light"]` block (now these light values instead of the old slate palette); `app/components/shell/Sidebar.tsx`.

## 3. Colours: Messages Pro

Messages Pro uses the same HB and `--tc-*` sets as the shell (its `.theme-dark` / `.theme-light` values equal the shell's
for every token compared). Our dark set in `app/components/chat/InflowwPalette.tsx` is unchanged (sampled earlier,
`docs/screenshots/messages-pro-compare.md`). The new light set maps each dark slot to the Infloww token whose dark value
matches it, then takes that token's light value:

| slot | dark | token (match) | light |
|---|---|---|---|
| `--color-bg`, `--inf-pane` | `#151515` | tc-B-nav | `#ffffff` |
| `--color-bg-elev-1` | `#2b2b2b` | none; inferred tc-B1 | `#f5f5f5` |
| `--color-bg-elev-2`, `--inf-row-selected`, `--inf-chip-hover` | `#353535` | tc-B-model-hover | `#e4e4e4` |
| `--color-panel` | `#1c1c1c` | inferred tc-B-popover | `#ffffff` |
| `--color-fg` | `#d9d9d9` | tc-T1 | `#151515` |
| `--color-fg-dim`, `--inf-unpaid` | `#999999` / `#8a8a8a` | tc-T3 | `#999999` |
| `--color-muted`, `--inf-offline` | `#6a6a6a` / `#6f6f6f` | element-emphasis-02 | `#9e9e9e` |
| `--color-border`, `--inf-rule`, `--inf-date-rule`, card / PPV borders | `#333`–`#444` | tc-L1 | `#e6e6e6` |
| `--color-border-light` | `#444444` | tc-T4 (light) | `#d9d9d9` |
| `--inf-accent-text` | `#7d97ff` | inferred tc-M1 | `#3467ff` |
| `--inf-window`, `--inf-insights` | `#0d0d0d` | surface-level-00-emphasis-opaque-00 | `#f2f2f2` |
| `--inf-tab` | `#232323` | surface-level-02-emphasis-00 on `#f2f2f2` | `#dcdcdc` |
| `--inf-fan-tab` | `#191919` | inferred | `#e5e5e5` |
| `--inf-tabs-row` | `#2b2c30` | tc-nav-header (light `#384360`, not used: inferred surface) | `#f2f2f2` |
| `--inf-chip` | `#262626` (sampled 2026-10-18) | tc-amount-bg | `#f0f0f0` |
| `--inf-card` | `#232323` | surface-level-01-emphasis-00 | `#ffffff` |
| `--inf-idle-fill` | `#2c2c2c` | surface-level-02-emphasis-00 on white | `#e8e8e8` |
| `--inf-bubble-in`, `--inf-ppv` | `#262626` / `#232323` | tc-B1 | `#f5f5f5` |
| `--inf-action` | `#666666` | tc-T4 (light `#d9d9d9` too faint; inferred T3) | `#999999` |
| `--inf-chip-text` | `#e5e5e5` | inferred T1 | `#151515` |
| avatars (fan / creator / list) | `#262626` / `#666666` | inferred | `#e6e6e6` / `#d9d9d9` |
| accent, on-accent, liked, glyph stroke | | unchanged | |

## 4. Messages Pro polish (2026-10-18)

Measured on Infloww's own Messages Pro window (a 1470×915 and a 395-wide
capture, CSS px). Tokens live in `app/lib/messagesPro.ts` (rows noted in
`docs/spec/phase-06-geometry-pass.md`), colours in `InflowwPalette`.

| Element | Infloww | Was |
|---|---|---|
| Window header / Fan tabs row | 44px / 32px | 46 / 34 |
| Home | folder tab 164×24 at the start of the Fan tabs row, pane fill, slanted right edge, 13px/600; goes to `/messages-pro` (`?window=1` kept) | tab in the Window header, linked to `/` |
| Fan List header | 52px with a 1px `--inf-rule` divider, title 20px/500, 11px in | 22px/700, no divider (the divider sat under the chips) |
| Online Fans / Notifications | 28px tall, radius 4, 14px/500, 28px apart, 10px sides | 42px, radius 9, 600 |
| Notifications fill, online dot | `--inf-online` `#67d1ae` (sampled; no tc/HB token matches) | `--color-ok` green |
| Inbox box, gear | 34px tall, radius 4; gear 36×34 | radius 9 / 8 |
| Chips | 26px, 12px sides, 14px/400, 10px apart, `#262626`; corner badge a 16px circle, `--color-err` | 30px, 13px/500, badge `--color-info` |
| Fan row text | name 15px/500, handle 15px, preview and time 14px | 14/700, 13, 13, 12 |
| Fan row divider | from 60px in (under the text) | full width |
| Spend pill | always orange (`$0` too), 13px/700 on `--inf-chip` | grey at `$0`, 11px on the row fill |
| Empty Thread | 100px plane, fill `#1990ff` / stroke `#3467ff`, 1px stroke; 20px `--color-fg` line | 130px, 26px dim |

Still different, on purpose: our Buys & tips switch after the two buttons (so
they are narrower), the phone layout's 36px chip tap targets, lucide's plane
shape, and the Notifications badge's count source.

## 5. Not done

- The pink unread count on Messages Pro: we have no sidebar unread source, so no badge.
- The platform card's chevron and switcher popover (one platform here).
- Infloww's hover pop-up submenu on the collapsed rail; our rail icon goes to the group's first page.
