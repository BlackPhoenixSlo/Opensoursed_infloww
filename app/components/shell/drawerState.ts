// While leaving only `slid` acts: a tap during the slide must not cut it short or reopen the drawer.
export type DrawerState = { kind: "closed" } | { kind: "open" | "leaving"; path: string };

export type DrawerAction =
  | { type: "open"; path: string }
  | { type: "toggle"; path: string }
  | { type: "close" }
  | { type: "letGo" }
  | { type: "slid" };

export const DRAWER_CLOSED: DrawerState = { kind: "closed" };

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
