export const CHAT_AUTO_PAGES_MAX = 4;
export const AUTO_PAGES_FLOOR = 2;
export const AUTO_TARGET_ROWS = 8;

export function mayAutoPage(a: { pagesLoaded: number; visibleRows: number }): boolean {
  if (a.pagesLoaded < AUTO_PAGES_FLOOR) return true;
  return a.pagesLoaded < CHAT_AUTO_PAGES_MAX && a.visibleRows < AUTO_TARGET_ROWS;
}

export const GESTURE_GAP_MS = 400;
const DOWN_KEYS = new Set(["PageDown", "ArrowDown", "End", " "]);

export type IntentEvent = { type: string; deltaY?: number; key?: string; repeat?: boolean };

export function scrollIntent(e: IntentEvent): boolean {
  if (e.type === "wheel") return (e.deltaY ?? 0) > 0;
  if (e.type === "keydown") return !e.repeat && DOWN_KEYS.has(e.key ?? "");
  return e.type === "touchmove";
}

export const INTENT_EVENTS = ["wheel", "touchmove", "keydown"] as const;

// Scroll events also come from scrollIntoView and layout shifts while a page lands, so only user input starts a gesture: one gesture, one page.
export function scrollGesture(gapMs = GESTURE_GAP_MS): (e: IntentEvent, now: number) => boolean {
  let last = -Infinity;
  return (e, now) => {
    if (!scrollIntent(e)) return false;
    const fresh = now - last > gapMs;
    last = now;
    return fresh;
  };
}

export type ListCaller =
  | "mount" | "replay" | "warmup" | "prefetch" | "poll" | "autofill" | "fill"
  | "scroll" | "loadmore" | "search" | "refresh" | "auto";

export function isExplicitCaller(c: ListCaller): boolean {
  return c === "loadmore" || c === "scroll";
}

export function listCaller(a: {
  fetchMore: boolean; pending: ListCaller | null; refresh: boolean; cached: boolean; offset: number; query: boolean;
}): ListCaller {
  if (a.fetchMore) return a.pending ?? "auto";
  if (a.refresh) return "refresh";
  if (a.cached || a.offset > 0) return "replay";
  return a.query ? "search" : "mount";
}

export type Busy = "idle" | "walk" | "next";

export interface Pending { caller: ListCaller; explicit: boolean }

export interface LoadMoreState {
  key: string;
  pending: Pending | null;
  queued: Pending | null;
  inFlight: { offset: number; pending: Pending } | null;
}

export type LoadMoreAction =
  | { type: "reset"; key: string }
  | { type: "request"; caller: ListCaller; busy: Busy; hasMore: boolean; failed: boolean; mayAuto: boolean }
  | { type: "taken"; pending: Pending; offset?: number }
  | { type: "settled"; ok: boolean; hasMore: boolean };

export function initialLoadMore(key: string): LoadMoreState {
  return { key, pending: null, queued: null, inFlight: null };
}

export function loadMoreReducer(s: LoadMoreState, a: LoadMoreAction): LoadMoreState {
  switch (a.type) {
    case "reset":
      return a.key === s.key ? s : initialLoadMore(a.key);
    case "request": {
      if (a.busy === "next" || s.pending) return s;
      const explicit = isExplicitCaller(a.caller);
      if (a.busy === "walk") return explicit && !s.queued ? { ...s, queued: { caller: a.caller, explicit } } : s;
      if (!a.hasMore || (!explicit && (a.failed || !a.mayAuto))) return s;
      return { ...s, pending: { caller: a.caller, explicit } };
    }
    case "taken":
      if (s.pending !== a.pending) return s;
      return { ...s, pending: null, inFlight: a.offset == null ? s.inFlight : { offset: a.offset, pending: a.pending } };
    case "settled": {
      const t = s.inFlight ? { ...s, inFlight: null } : s;
      if (!t.queued) return t;
      return a.ok && a.hasMore && !t.pending ? { ...t, pending: t.queued, queued: null } : { ...t, queued: null };
    }
  }
}

export function pendingFor(s: LoadMoreState, offset: number): Pending | null {
  return s.pending ?? (s.inFlight?.offset === offset ? s.inFlight.pending : null);
}

export function startedBy(prev: LoadMoreState, next: LoadMoreState): Pending | null {
  return next.pending && next.pending !== prev.pending ? next.pending : null;
}
