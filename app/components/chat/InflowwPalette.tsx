"use client";

/**
 * InflowwPalette — Messages Pro's colours (ADR-0010). The wrapper re-declares
 * the app's `--color-*` variables on Messages Pro's subtree, so every utility
 * inside it (`bg-accent`, `text-fg-dim`, `border-border`…) and every shared
 * component it renders (menus, the switch, the bell's panel) takes Infloww's
 * value, while every other screen keeps the app's tokens and the App accent.
 * The inline declarations sit nearer to each element than the
 * `html[data-theme="light"]` rule, so the wrapper picks the set itself: under
 * the app's light theme it lays `LIGHT` over the dark values, Infloww Messages
 * Pro's own `.theme-light` (docs/infloww-sidebar-palette.md §3), with a light
 * `color-scheme` for scrollbars and native inputs.
 *
 * Each value is the Colour inventory's Infloww value for the token class's
 * main role (docs/screenshots/messages-pro-compare.md). Where the inventory
 * maps a class to a second value, that role gets an `--inf-*` variable here,
 * declared on this element only, and the element writes one class with the
 * app token as the fallback, `text-[var(--inf-accent-text,var(--color-accent))]`:
 * Infloww's value inside Messages Pro, the app's colour anywhere else. The
 * Compare page's Literals list names each one. No other module holds these
 * values, so the next colour change is one line here.
 */

import { createContext, useContext, type CSSProperties, type ReactNode } from "react";

import { useTheme } from "@/hooks/useTheme";

const PALETTE = {
  "--color-bg": "#151515",
  "--color-bg-elev-1": "#2b2b2b",
  "--color-bg-elev-2": "#353535",
  "--color-panel": "#1c1c1c",
  "--color-fg": "#d9d9d9",
  "--color-fg-dim": "#999999",
  "--color-muted": "#6a6a6a",
  "--color-border": "#333333",
  "--color-border-light": "#444444",
  "--color-accent": "#4166f6",
  "--color-accent-hover": "#4166f6",
  // Status colours: the app's dark @theme values (globals.css), pinned here so
  // Messages Pro keeps them under the light theme.
  "--color-ok": "#58a744",
  "--color-warn": "#ffa15f",
  "--color-err": "#ff7c71",
  "--color-pink": "#fb609f",
  "--color-info": "#05a2dc",
  // The split roles (Colour inventory lines whose class takes a second value).
  "--inf-accent-text": "#7d97ff", // accent text and icons; --color-accent is the fill blue
  "--inf-rule": "#444444", // pane borders, Fan row dividers, header and Composer rules
  "--inf-pane": "#151515", // Fan List, Chat header, Composer, pinned bar; an unselected Fan row
  "--inf-row-selected": "#353535", // the selected Fan row, its online-dot ring and spend pill
  "--inf-window": "#0d0d0d", // the Window header bar
  "--inf-insights": "#0d0d0d", // the Fan insights pane and slide-over
  "--inf-tab": "#232323", // the Home tab and inactive Creator tabs
  "--inf-fan-tab": "#191919", // inactive Fan tabs
  "--inf-tabs-row": "#2b2c30", // the Fan tabs row
  "--inf-chip": "#262626", // an inactive filter chip and a Fan row's spend pill (2026-10-18 capture)
  "--inf-chip-hover": "#353535", // hover on an inactive filter chip
  "--inf-card": "#232323", // Fan insights blocks and cards
  "--inf-card-border": "#2a2a2a", // Fan insights card outline
  "--inf-insights-tab-on": "#ffffff", // the active Fan insights tab tile's glyph and label (2026-10-18 capture)
  "--inf-insights-tab-off": "#666666", // an inactive tile's (2026-10-18 capture)
  "--inf-idle-fill": "#2c2c2c", // translate off, a disabled popover primary
  "--inf-send-idle": "#666666", // the Composer's Send while there is nothing to send (2026-10-18 capture)
  "--inf-send-idle-text": "#979797", // its "Send" label (2026-10-18 capture)
  "--inf-ai-pill": "#243b42", // the Composer's "AI" pill fill (2026-10-18 capture)
  "--inf-scripts-pill": "#353535", // the Composer's "Scripts" pill fill (2026-10-18 capture)
  "--inf-composer-glyph": "#b8b8b8", // the Composer toolbar's "Aa" (2026-10-18 capture)
  "--inf-offline": "#6f6f6f", // the offline presence dot and the free-preview tile marker
  "--inf-bubble-in": "#262626", // the Fan's (incoming) bubble
  "--inf-ppv": "#232323", // the PPV card fill
  "--inf-ppv-border": "#2f2f2f", // the PPV card outline
  "--inf-unpaid": "#8a8a8a", // the "not paid" PPV price line
  "--inf-date-rule": "#333639", // date divider lines
  "--inf-on-accent": "#ffffff", // text on accent fills (jump-to-latest, a picked Creator's check)
  "--inf-glyph-stroke": "#3467ff", // the Send glyph's stroke in the Thread empty state (2026-10-18 capture)
  "--inf-glyph-fill": "#1990ff", // the Send glyph's fill there (2026-10-18 capture)
  "--inf-online": "#2ad4ac", // the Fan List online dot, Notifications button and its badge, a Creator tab's notifications count (2026-10-18 capture bcd76ff7 samples #29d4ac; the HB "subs" teal)
  "--inf-presence-text": "#8a8a8a", // the Chat header's presence words, online or not (2026-10-18 capture)
  "--inf-presence-online": "#4aaa1a", // the Chat header's online presence dot (2026-10-18 capture)
  "--inf-action": "#666666", // the Bubble action row's line glyphs
  "--inf-liked": "#f0483e", // the Bubble action row's liked heart
  "--inf-chip-text": "#e5e5e5", // the Jump chip's text, on --inf-chip (the Clone's `.chip`)
  "--inf-fan-avatar": "#262626", // the Fan's avatar circle in a Thread, with no picture
  "--inf-creator-avatar": "#666666", // the Creator's avatar circle in a Thread, with no picture
  "--inf-list-avatar": "#666666", // a Fan List row's avatar circle, with no picture (selected or not)
  colorScheme: "dark",
  color: "var(--color-fg)",
} as CSSProperties;

/** Light theme: each dark slot's Infloww token, at that token's light value
 *  (REA, Messages Pro `main-*.css` `.theme-light` and the `--tc-*` light
 *  defaults; the slot-to-token mapping is inferred where the doc says so). */
const LIGHT = {
  ...PALETTE,
  "--color-bg": "#ffffff", // tc-B-nav
  "--color-bg-elev-1": "#f5f5f5", // tc-B1
  "--color-bg-elev-2": "#e4e4e4", // tc-B-model-hover
  "--color-panel": "#ffffff", // tc-B-popover
  "--color-fg": "#151515", // tc-T1
  "--color-fg-dim": "#999999", // tc-T3
  "--color-muted": "#9e9e9e", // element-emphasis-02 on white
  "--color-border": "#e6e6e6", // tc-L1
  "--color-border-light": "#d9d9d9", // tc-T4
  "--color-ok": "#52b03b",
  "--color-pink": "#ff5c9e",
  "--color-info": "#00a4e1",
  "--inf-accent-text": "#3467ff", // tc-M1
  "--inf-rule": "#e6e6e6",
  "--inf-pane": "#ffffff",
  "--inf-row-selected": "#e4e4e4",
  "--inf-window": "#f2f2f2", // surface-level-00-emphasis-opaque-00
  "--inf-insights": "#f2f2f2",
  "--inf-tab": "#dcdcdc", // surface-level-02-emphasis-00 on #f2f2f2
  "--inf-fan-tab": "#e5e5e5",
  "--inf-tabs-row": "#f2f2f2",
  "--inf-chip": "#f0f0f0", // tc-amount-bg
  "--inf-chip-hover": "#e4e4e4",
  "--inf-card": "#ffffff", // surface-level-01-emphasis-00
  "--inf-card-border": "#e6e6e6",
  "--inf-insights-tab-on": "#151515", // tc-T1
  "--inf-insights-tab-off": "#999999", // tc-T3
  "--inf-idle-fill": "#e8e8e8",
  // The Composer fills below are inferred (no light capture): the idle fill, tc-amount-bg, an accent tint.
  "--inf-send-idle": "#e8e8e8",
  "--inf-send-idle-text": "#999999",
  "--inf-ai-pill": "#e6ecff",
  "--inf-scripts-pill": "#f0f0f0",
  "--inf-composer-glyph": "#999999",
  "--inf-offline": "#9e9e9e",
  "--inf-bubble-in": "#f5f5f5", // tc-B1
  "--inf-ppv": "#f5f5f5",
  "--inf-ppv-border": "#e6e6e6",
  "--inf-unpaid": "#999999",
  "--inf-date-rule": "#e6e6e6",
  "--inf-action": "#999999",
  "--inf-chip-text": "#151515",
  "--inf-fan-avatar": "#e6e6e6",
  "--inf-creator-avatar": "#d9d9d9",
  "--inf-list-avatar": "#d9d9d9",
  colorScheme: "light",
} as CSSProperties;

/** The wrapper's own element also paints the pane background. The hook leaves
 *  it out: an inline `background` on a portal root would beat its own fill
 *  (`bg-panel`) and cover a transparent backdrop. */
const background = { background: "var(--color-bg)" };

const PaletteContext = createContext<CSSProperties | undefined>(undefined);

/** Renders `children` inside one element carrying the palette (and
 *  `className`, so it can be the caller's root). */
export function InflowwPalette({ className, children }: { className?: string; children: ReactNode }) {
  const palette = useTheme().theme === "light" ? LIGHT : PALETTE;
  return (
    <PaletteContext.Provider value={palette}>
      <div className={className} style={{ ...palette, ...background }}>{children}</div>
    </PaletteContext.Provider>
  );
}

/** The palette style inside `InflowwPalette`, `undefined` outside it. A portal
 *  root spreads it onto its outermost element, so its subtree reads the same
 *  variables as the wrapper's (every one but the wrapper's own background). */
export function useInflowwPalette(): CSSProperties | undefined {
  return useContext(PaletteContext);
}
