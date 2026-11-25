"use client";


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
  // Status colours pinned to the app's dark values so Messages Pro keeps them under the light theme.
  "--color-ok": "#58a744",
  "--color-warn": "#ffa15f",
  "--color-err": "#ff7c71",
  "--color-pink": "#fb609f",
  "--color-info": "#05a2dc",
  "--inf-accent-text": "#7d97ff",
  "--inf-rule": "#444444",
  "--inf-pane": "#151515",
  "--inf-row-selected": "#353535",
  "--inf-window": "#0d0d0d",
  "--inf-insights": "#0d0d0d",
  "--inf-tab": "#232323",
  "--inf-fan-tab": "#191919",
  "--inf-tabs-row": "#2b2c30",
  "--inf-chip": "#262626",
  "--inf-chip-hover": "#353535",
  "--inf-card": "#232323",
  "--inf-card-border": "#2a2a2a",
  "--inf-insights-tab-on": "#ffffff",
  "--inf-insights-tab-off": "#666666",
  "--inf-idle-fill": "#2c2c2c",
  "--inf-send-idle": "#666666",
  "--inf-send-idle-text": "#979797",
  "--inf-ai-pill": "#243b42",
  "--inf-scripts-pill": "#353535",
  "--inf-composer-glyph": "#b8b8b8",
  "--inf-offline": "#6f6f6f",
  "--inf-bubble-in": "#262626",
  "--inf-ppv": "#232323",
  "--inf-ppv-border": "#2f2f2f",
  "--inf-unpaid": "#8a8a8a",
  "--inf-date-rule": "#333639",
  "--inf-on-accent": "#ffffff",
  "--inf-glyph-stroke": "#3467ff",
  "--inf-glyph-fill": "#1990ff",
  "--inf-online": "#2ad4ac",
  "--inf-presence-text": "#8a8a8a",
  "--inf-presence-online": "#4aaa1a",
  "--inf-action": "#666666",
  "--inf-liked": "#f0483e",
  "--inf-chip-text": "#e5e5e5",
  "--inf-fan-avatar": "#262626",
  "--inf-creator-avatar": "#666666",
  "--inf-list-avatar": "#666666",
  colorScheme: "dark",
  color: "var(--color-fg)",
} as CSSProperties;

// Slot-to-token mapping is inferred where there is no light capture (Messages Pro .theme-light).
const LIGHT = {
  ...PALETTE,
  "--color-bg": "#ffffff",
  "--color-bg-elev-1": "#f5f5f5",
  "--color-bg-elev-2": "#e4e4e4",
  "--color-panel": "#ffffff",
  "--color-fg": "#151515",
  "--color-fg-dim": "#999999",
  "--color-muted": "#9e9e9e",
  "--color-border": "#e6e6e6",
  "--color-border-light": "#d9d9d9",
  "--color-ok": "#52b03b",
  "--color-pink": "#ff5c9e",
  "--color-info": "#00a4e1",
  "--inf-accent-text": "#3467ff",
  "--inf-rule": "#e6e6e6",
  "--inf-pane": "#ffffff",
  "--inf-row-selected": "#e4e4e4",
  "--inf-window": "#f2f2f2",
  "--inf-insights": "#f2f2f2",
  "--inf-tab": "#dcdcdc",
  "--inf-fan-tab": "#e5e5e5",
  "--inf-tabs-row": "#f2f2f2",
  "--inf-chip": "#f0f0f0",
  "--inf-chip-hover": "#e4e4e4",
  "--inf-card": "#ffffff",
  "--inf-card-border": "#e6e6e6",
  "--inf-insights-tab-on": "#151515",
  "--inf-insights-tab-off": "#999999",
  "--inf-idle-fill": "#e8e8e8",
  "--inf-send-idle": "#e8e8e8",
  "--inf-send-idle-text": "#999999",
  "--inf-ai-pill": "#e6ecff",
  "--inf-scripts-pill": "#f0f0f0",
  "--inf-composer-glyph": "#999999",
  "--inf-offline": "#9e9e9e",
  "--inf-bubble-in": "#f5f5f5",
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

// Kept out of the hook: an inline background on a portal root would beat its own fill (bg-panel) and cover a transparent backdrop.
const background = { background: "var(--color-bg)" };

const PaletteContext = createContext<CSSProperties | undefined>(undefined);

export function InflowwPalette({ className, children }: { className?: string; children: ReactNode }) {
  const palette = useTheme().theme === "light" ? LIGHT : PALETTE;
  return (
    <PaletteContext.Provider value={palette}>
      <div className={className} style={{ ...palette, ...background }}>{children}</div>
    </PaletteContext.Provider>
  );
}

export function useInflowwPalette(): CSSProperties | undefined {
  return useContext(PaletteContext);
}
