"use client";


import { useEffect, useReducer, useRef } from "react";

import { useDragPress } from "./useDragPress";
import { DEFAULT_DOCK, readDock, writeDock, type DockState, type Surface } from "@/lib/moneyRailStorage";

const PANEL_W = 290;
export const ROW_H = 68;

export function anchorFor(top: number, height: number, viewportH: number): "top" | "bottom" {
  return top + height / 2 > viewportH / 2 ? "bottom" : "top";
}

export function clampToViewport(
  x: number, y: number, panelH: number,
  viewportW = window.innerWidth, viewportH = window.innerHeight,
): { x: number; y: number } {
  const maxX = Math.max(0, viewportW - PANEL_W);
  const maxY = Math.max(0, viewportH - Math.min(panelH, 80));
  return {
    x: Math.min(Math.max(0, x), maxX),
    y: Math.min(Math.max(0, y), maxY),
  };
}

export interface RailDockState {
  dock: DockState;
  viewportH: number;
  mounted: boolean;
  saves: number;
}

export const initialRailDock: RailDockState = { dock: DEFAULT_DOCK, viewportH: 0, mounted: false, saves: 0 };

export type RailDockAction =
  | { type: "load"; dock: DockState; viewportH: number }
  | { type: "dragMove"; x: number; y: number; panelH: number; viewportW: number; viewportH: number }
  | { type: "drop"; rect: { top: number; bottom: number; height: number } | null; viewportH: number }
  | { type: "resize"; viewportW: number; viewportH: number; panelH: number }
  | { type: "toggle" };

// Drag positions from the top; the anchor is decided on drop.
export function railDockReducer(state: RailDockState, a: RailDockAction): RailDockState {
  switch (a.type) {
    case "load":
      return { ...state, dock: a.dock, viewportH: a.viewportH, mounted: true };
    case "dragMove": {
      const { x, y } = clampToViewport(a.x, a.y, a.panelH, a.viewportW, a.viewportH);
      return { ...state, dock: { ...state.dock, x, y, anchor: "top" } };
    }
    case "drop": {
      let dock = state.dock;
      if (a.rect) {
        const anchor = anchorFor(a.rect.top, a.rect.height, a.viewportH);
        dock = {
          ...dock,
          anchor,
          y: anchor === "bottom"
            ? Math.max(0, a.viewportH - a.rect.bottom)
            : Math.max(0, a.rect.top),
        };
      }
      return { ...state, dock, saves: state.saves + 1 };
    }
    case "resize": {
      const cur = state.dock;
      let next = state.viewportH === a.viewportH ? state : { ...state, viewportH: a.viewportH };
      if (cur.x == null || cur.y == null) return next;
      const h = a.panelH;
      // clampToViewport works in top-space: convert a bottom-anchored offset in and back out.
      const top = cur.anchor === "bottom" ? a.viewportH - cur.y - h : cur.y;
      const c = clampToViewport(cur.x, top, h, a.viewportW, a.viewportH);
      const y = cur.anchor === "bottom"
        ? Math.max(0, a.viewportH - (c.y + h))
        : c.y;
      if (c.x === cur.x && y === cur.y) return next;
      next = { ...next, dock: { ...cur, x: c.x, y }, saves: state.saves + 1 };
      return next;
    }
    case "toggle":
      return { ...state, dock: { ...state.dock, open: !state.dock.open }, saves: state.saves + 1 };
  }
}

export function useRailDock(surface: Surface) {
  const [state, dispatch] = useReducer(railDockReducer, initialRailDock);
  const { dock, mounted, viewportH, saves } = state;
  useEffect(() => {
    // Per-surface dock can't be read in first render (SSR): load in an effect keyed by surface.
    dispatch({ type: "load", dock: readDock(surface), viewportH: window.innerHeight });
  }, [surface]);

  useEffect(() => {
    if (saves > 0) writeDock(surface, dock);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saves]);

  const panelRef = useRef<HTMLDivElement | null>(null);

  const { onPointerDown: onHeaderPointerDown, swallowClick } = useDragPress({
    begin: () => {
      const rect = panelRef.current?.getBoundingClientRect();
      return rect ? { x: rect.left, y: rect.top } : null;
    },
    move: (o, dx, dy) => dispatch({
      type: "dragMove",
      x: o.x + dx, y: o.y + dy,
      panelH: panelRef.current?.offsetHeight ?? ROW_H,
      viewportW: window.innerWidth, viewportH: window.innerHeight,
    }),
    drop: () => {
      const r = panelRef.current?.getBoundingClientRect();
      dispatch({
        type: "drop",
        rect: r ? { top: r.top, bottom: r.bottom, height: r.height } : null,
        viewportH: window.innerHeight,
      });
    },
  });

  const toggle = () => {
    // The pointerup that ended a drag also lands as a click: eat it.
    if (swallowClick()) return;
    dispatch({ type: "toggle" });
  };

  useEffect(() => {
    if (!mounted) return;
    const onResize = () => dispatch({
      type: "resize",
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
      panelH: panelRef.current?.offsetHeight ?? ROW_H,
    });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [mounted]);

  return { dock, mounted, viewportH, panelRef, swallowClick, onHeaderPointerDown, toggle };
}
