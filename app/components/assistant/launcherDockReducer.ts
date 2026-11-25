export type Edge = "left" | "right" | "bottom";

export interface LauncherDock {
  edge: Edge;
  along: number;
  tucked: boolean;
}

export const SIZE = 48;
export const MARGIN = 12;
const TOP_RESERVE = 64;
export const TUCK_PAST = Math.round(SIZE * 0.4);
// Clears the chat composer below it (163px tall at 390x844, measured).
export const DEFAULT_ALONG = 180;
export const DEFAULT_LAUNCHER_DOCK: LauncherDock = { edge: "right", along: DEFAULT_ALONG, tucked: true };

export interface LauncherState {
  dock: LauncherDock;
  drag: { x: number; y: number } | null;
  vw: number;
  vh: number;
  loaded: boolean;
  saves: number;
}

export const initialLauncherState: LauncherState = {
  dock: DEFAULT_LAUNCHER_DOCK, drag: null, vw: 0, vh: 0, loaded: false, saves: 0,
};

export type LauncherAction =
  | { type: "load"; dock: LauncherDock | null; vw: number; vh: number }
  | { type: "resize"; vw: number; vh: number }
  | { type: "dragMove"; x: number; y: number }
  | { type: "drop" }
  | { type: "untuck" };

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

const sideAlong = (along: number, vh: number) => clamp(along, MARGIN, vh - SIZE - TOP_RESERVE);
const bottomAlong = (along: number, vw: number) => clamp(along, MARGIN, vw - SIZE - MARGIN);

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
