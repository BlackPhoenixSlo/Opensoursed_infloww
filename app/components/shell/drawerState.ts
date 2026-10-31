/**
 * The shell's nav drawer below lg (AppShell): `closed`; `open` on the path it
 * was opened on (any navigation changes the path, and so closes it); or
 * `leaving`: a swipe let it go, its Radix layer is closed (its focus trap let
 * go) and it stays mounted for its slide until `slid`. While it is leaving only
 * `slid` acts: open, toggle and close are ignored, so a tap during the slide
 * neither cuts it short nor brings the drawer back.
 */
export type DrawerState = { kind: "closed" } | { kind: "open" | "leaving"; path: string };

export type DrawerAction =
  /** The open swipe. */
  | { type: "open"; path: string }
  /** The top bar's button. */
  | { type: "toggle"; path: string }
  /** Esc, a backdrop click, a link in it. */
  | { type: "close" }
  /** The closing swipe's release decided it (`useSwipe` `onLetGo`). */
  | { type: "letGo" }
  /** The closing swipe is done (`onSwipe`: its slide ended; under reduced motion, its release). */
  | { type: "slid" };

export const DRAWER_CLOSED: DrawerState = { kind: "closed" };

/** What the drawer is on `path`: a state left on another path is closed. */
export function drawerOn(s: DrawerState, path: string): DrawerState["kind"] {
  return s.kind !== "closed" && s.path === path ? s.kind : "closed";
}

export function drawerReducer(s: DrawerState, a: DrawerAction): DrawerState {
  switch (a.type) {
    case "open":
    case "toggle": {
      const now = drawerOn(s, a.path);
      if (now === "leaving") return s;
      return a.type === "toggle" && now === "open" ? DRAWER_CLOSED : { kind: "open", path: a.path };
    }
    case "close":
      return s.kind === "open" ? DRAWER_CLOSED : s;
    case "letGo":
      return s.kind === "open" ? { kind: "leaving", path: s.path } : s;
    case "slid":
      return DRAWER_CLOSED;
  }
}
