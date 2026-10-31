"use client";

/**
 * useRailDock — where the Buys & tips rail sits (`MoneyRail`): the per-surface
 * dock (position, anchor edge, open bit) read from and written to
 * localStorage, the header drag, and the resize clamp that keeps it on screen.
 */

import { useEffect, useReducer, useRef } from "react";

import { DEFAULT_DOCK, readDock, writeDock, type DockState, type Surface } from "@/lib/moneyRailStorage";

const PANEL_W = 290;
/** One row's height. The body's max-height is rows × this, so "small = 1 row"
 *  is a window onto the feed, not a truncation — the list still scrolls. */
export const ROW_H = 68;
/** Pointer slop before a press on the header counts as a drag and not a click. */
const DRAG_THRESHOLD_PX = 4;

/** Which edge a panel occupying [top, top+height] should pin to: whichever the
 *  panel's centre is nearer. */
export function anchorFor(top: number, height: number, viewportH: number): "top" | "bottom" {
  return top + height / 2 > viewportH / 2 ? "bottom" : "top";
}

/** Keep the panel on screen — after a drag, a resize, or a restore into a
 *  window smaller than the one the position was saved from. Always leaves the
 *  header grabbable. The viewport defaults to the window's. */
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
  /** Needed to cap the body height against the viewport. Kept in state (not
   *  read during render) so SSR and the first client render agree. */
  viewportH: number;
  /** The saved dock has been read (client only). */
  mounted: boolean;
  /** Bumped by every change the dock must be saved after (drop, toggle, a
   *  resize that moved it) — never by a drag move. The hook writes on it. */
  saves: number;
}

export const initialRailDock: RailDockState = { dock: DEFAULT_DOCK, viewportH: 0, mounted: false, saves: 0 };

export type RailDockAction =
  | { type: "load"; dock: DockState; viewportH: number }
  /** The panel's top-left wants to be at (x, y) mid-drag. */
  | { type: "dragMove"; x: number; y: number; panelH: number; viewportW: number; viewportH: number }
  /** The drag ended; `rect` is where the panel now is (null if unmeasurable). */
  | { type: "drop"; rect: { top: number; bottom: number; height: number } | null; viewportH: number }
  | { type: "resize"; viewportW: number; viewportH: number; panelH: number }
  | { type: "toggle" };

export function railDockReducer(state: RailDockState, a: RailDockAction): RailDockState {
  switch (a.type) {
    case "load":
      return { ...state, dock: a.dock, viewportH: a.viewportH, mounted: true };
    case "dragMove": {
      // While dragging we position from the TOP — it follows the pointer 1:1
      // and needs no knowledge of the panel's height. The anchor is decided
      // once, on drop.
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
          // Re-express the offset against the edge we just pinned to.
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
      // clampToViewport works in top-space, so a bottom-anchored offset has
      // to be converted in and back out — clamping it directly would treat a
      // distance-from-bottom as a distance-from-top.
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
  // Dock state is per-surface, so it can't be read during the first render
  // (the server doesn't know the surface OR localStorage). Hydration-gate the
  // whole panel and load in an effect keyed by surface — a client-side nav
  // between /inbox and /group re-reads the other surface's saved spot.
  const [state, dispatch] = useReducer(railDockReducer, initialRailDock);
  const { dock, mounted, viewportH, saves } = state;
  useEffect(() => {
    dispatch({ type: "load", dock: readDock(surface), viewportH: window.innerHeight });
  }, [surface]);

  // Save after a drop, a toggle or a resize that moved the dock — keyed on
  // `saves` alone, so a surface change (which only loads) never writes the old
  // surface's dock under the new one's key.
  useEffect(() => {
    if (saves > 0) writeDock(surface, dock);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saves]);

  const panelRef = useRef<HTMLDivElement | null>(null);

  // A press on the header is either a drag or a click; we can't know until the
  // pointer moves. Track it, and swallow the click that a drag inevitably
  // fires so releasing the pointer over the toggle doesn't also collapse it.
  const dragRef = useRef<
    { startX: number; startY: number; origX: number; origY: number; moved: boolean } | null
  >(null);
  const draggedRef = useRef(false);

  // Drag is tracked on WINDOW listeners, never with setPointerCapture on the
  // header. Capturing the pointer also retargets the compatibility mouse
  // events — the subsequent `click` would be delivered to the capturing header
  // instead of the button under the cursor, which silently kills every button
  // in the header bar.
  const onHeaderPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      startX: e.clientX, startY: e.clientY,
      origX: rect.left, origY: rect.top,
      moved: false,
    };

    const onMove = (ev: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = ev.clientX - d.startX;
      const dy = ev.clientY - d.startY;
      if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      d.moved = true;
      draggedRef.current = true;
      dispatch({
        type: "dragMove",
        x: d.origX + dx, y: d.origY + dy,
        panelH: panelRef.current?.offsetHeight ?? ROW_H,
        viewportW: window.innerWidth, viewportH: window.innerHeight,
      });
    };

    const onUp = () => {
      const d = dragRef.current;
      dragRef.current = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      if (!d?.moved) return;
      // The click that follows this pointerup (if we released over a button)
      // must be swallowed. But a drag released over dead space fires NO click,
      // and a `draggedRef` left armed would eat the user's next real click. A
      // 0ms timer runs after click dispatch but before any later interaction.
      window.setTimeout(() => { draggedRef.current = false; }, 0);

      const r = panelRef.current?.getBoundingClientRect();
      dispatch({
        type: "drop",
        rect: r ? { top: r.top, bottom: r.bottom, height: r.height } : null,
        viewportH: window.innerHeight,
      });
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const toggle = () => {
    // The pointerup that ended a drag also lands here as a click. Eat it once.
    if (draggedRef.current) {
      draggedRef.current = false;
      return;
    }
    dispatch({ type: "toggle" });
  };

  // Restoring a saved spot into a smaller window (or resizing after a drag)
  // could park the dock off-screen with no way to grab it back.
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

  return { dock, mounted, viewportH, panelRef, draggedRef, onHeaderPointerDown, toggle };
}
