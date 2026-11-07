/**
 * Where the phone help launcher sits (AssistantWidget's `PhoneLauncher` only
 * dispatches; the drag itself is useDragPress, storage stays in the widget).
 *
 *   • A drag moves the icon 1:1 (`dragMove`, top-left in px), allowed to push
 *     most of the way past a side edge so it can be tucked.
 *   • `drop` snaps to the nearest of the left, right or bottom edge — unless
 *     ≥ TUCK_PAST px of it went past a side edge: then it tucks into that side
 *     and only a chevron tab shows. `untuck` (tapping the tab) pulls it back
 *     out at the same height.
 *   • The dock is stored as an edge plus a distance ALONG it — from the
 *     viewport's bottom on a side (the composer is down there, so a rotate or a
 *     keyboard keeps the icon's clearance above it), from the left on the
 *     bottom edge — and clamped at draw time, so a resize can never park it
 *     off screen.
 *   • `saves` bumps on every change worth persisting (drop, untuck), never on
 *     a drag move or a load: the widget writes on it.
 */

export type Edge = "left" | "right" | "bottom";

export interface LauncherDock {
  edge: Edge;
  /** px. Sides: the icon's bottom above the viewport's bottom. Bottom edge: its left from the viewport's left. */
  along: number;
  /** Hidden into its side edge with only the chevron tab showing (sides only). */
  tucked: boolean;
}

/** The launcher's diameter (Intercom's 48px), its gap to the edge it snaps to,
 *  and the room kept clear under the top bar. */
export const SIZE = 48;
export const MARGIN = 12;
const TOP_RESERVE = 64;
/** Dropped with this much of the icon past a side edge: tuck it. */
export const TUCK_PAST = Math.round(SIZE * 0.4);
/** Default: right side, clear of the chat composer below it (measured at
 *  390×844: Messages Pro's composer, emoji row to Send, is 163px tall). */
export const DEFAULT_ALONG = 180;
export const DEFAULT_LAUNCHER_DOCK: LauncherDock = { edge: "right", along: DEFAULT_ALONG, tucked: false };

export interface LauncherState {
  dock: LauncherDock;
  /** Live top-left while a drag is in progress; null at rest. */
  drag: { x: number; y: number } | null;
  vw: number;
  vh: number;
  /** The saved dock has been read (client only). */
  loaded: boolean;
  saves: number;
}

export const initialLauncherState: LauncherState = {
  dock: DEFAULT_LAUNCHER_DOCK, drag: null, vw: 0, vh: 0, loaded: false, saves: 0,
};

export type LauncherAction =
  | { type: "load"; dock: LauncherDock | null; vw: number; vh: number }
  | { type: "resize"; vw: number; vh: number }
  /** The icon's top-left wants to be at (x, y) mid-drag. */
  | { type: "dragMove"; x: number; y: number }
  | { type: "drop" }
  | { type: "untuck" };

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** A side dock's `along`, kept between the bottom margin and the top bar. */
const sideAlong = (along: number, vh: number) => clamp(along, MARGIN, vh - SIZE - TOP_RESERVE);
const bottomAlong = (along: number, vw: number) => clamp(along, MARGIN, vw - SIZE - MARGIN);

/** Where an icon dropped with its top-left at (x, y) docks. */
export function snapDock(x: number, y: number, vw: number, vh: number): LauncherDock {
  const along = sideAlong(vh - (y + SIZE), vh);
  if (x < -TUCK_PAST) return { edge: "left", along, tucked: true };
  if (x + SIZE > vw + TUCK_PAST) return { edge: "right", along, tucked: true };
  const cx = x + SIZE / 2;
  const cy = y + SIZE / 2;
  const toLeft = cx;
  const toRight = vw - cx;
  const toBottom = vh - cy;
  if (toBottom < toLeft && toBottom < toRight) return { edge: "bottom", along: bottomAlong(x, vw), tucked: false };
  return { edge: toLeft <= toRight ? "left" : "right", along, tucked: false };
}

/** The icon's top-left right now: the drag if one is live, else the dock. */
export function launcherSpot(s: LauncherState): { left: number; top: number } {
  if (s.drag) return { left: s.drag.x, top: s.drag.y };
  const { edge, along } = s.dock;
  if (edge === "bottom") return { left: bottomAlong(along, s.vw), top: s.vh - SIZE - MARGIN };
  return {
    left: edge === "left" ? MARGIN : s.vw - SIZE - MARGIN,
    top: s.vh - SIZE - sideAlong(along, s.vh),
  };
}

export function launcherDockReducer(state: LauncherState, a: LauncherAction): LauncherState {
  switch (a.type) {
    case "load":
      return { ...state, dock: a.dock ?? DEFAULT_LAUNCHER_DOCK, vw: a.vw, vh: a.vh, loaded: true };
    case "resize":
      return state.vw === a.vw && state.vh === a.vh ? state : { ...state, vw: a.vw, vh: a.vh };
    case "dragMove":
      return {
        ...state,
        // Most of the icon may go past a side edge (that is how it tucks);
        // a quarter always stays grabbable.
        drag: {
          x: clamp(a.x, -SIZE * 0.75, state.vw - SIZE * 0.25),
          y: clamp(a.y, 0, state.vh - SIZE),
        },
      };
    case "drop":
      if (!state.drag) return state;
      return {
        ...state,
        dock: snapDock(state.drag.x, state.drag.y, state.vw, state.vh),
        drag: null,
        saves: state.saves + 1,
      };
    case "untuck":
      if (!state.dock.tucked) return state;
      return { ...state, dock: { ...state.dock, tucked: false }, saves: state.saves + 1 };
  }
}

/** A stored dock, or null for anything this version didn't write. */
export function parseLauncherDock(raw: string | null): LauncherDock | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<LauncherDock>;
    if (v.edge !== "left" && v.edge !== "right" && v.edge !== "bottom") return null;
    if (typeof v.along !== "number" || !Number.isFinite(v.along)) return null;
    return { edge: v.edge, along: v.along, tucked: v.edge !== "bottom" && v.tucked === true };
  } catch {
    return null;
  }
}
