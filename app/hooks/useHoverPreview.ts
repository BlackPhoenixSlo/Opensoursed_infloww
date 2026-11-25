import { useCallback, useEffect, useReducer, useRef } from "react";

import { resolveShareToken } from "@/lib/shareToken";

export const HOVER_DELAY_MS = 400;
// The relay keys its /img/scrub cache by mp4 hash + frame index, so every surface must ask for the same 12.
export const SCRUB_FRAMES = 12;
export const SCRUB_INTERVAL_MS = 600;
export const POSTER_ETA_SEC = 2.5;
export const POSTER_GRACE_MS = 250;
const TICK_MS = 100;

export type ScrubStatus = "loading" | "ready" | "failed";

export interface HoverPreviewState {
  id: number | null;
  sid: string;
  durationSec: number;
  url: string | null;
  frame: number;
  scrub: ScrubStatus;
  posterLoaded: boolean;
  posterGrace: boolean;
  startedAt: number;
  now: number;
}

export type HoverPreviewAction =
  | { type: "enter"; id: number; durationSec: number; url: string | null; sid: string; now: number }
  | { type: "leave" }
  | { type: "beat" }
  | { type: "tick"; now: number }
  | { type: "frameLoaded"; sid: string; idx: number }
  | { type: "frameError"; sid: string; idx: number }
  | { type: "posterLoaded"; sid: string }
  | { type: "graceElapsed"; sid: string };

export const IDLE_HOVER: HoverPreviewState = {
  id: null,
  sid: "",
  durationSec: 0,
  url: null,
  frame: 0,
  scrub: "loading",
  posterLoaded: false,
  posterGrace: false,
  startedAt: 0,
  now: 0,
};

export function etaFor(durationSec: number): number {
  const dur = Math.max(1, durationSec || 0);
  const base = dur <= 60
    ? 4.5 + 0.5 * Math.ceil(dur / 15)
    : 6.5 + (7 * (dur - 60)) / 60;
  // x1.3: measured cold builds ran longer than the piecewise estimate (full-mp4 download through the proxy).
  return Math.round(base * 1.3);
}

const elapsedSec = (s: HoverPreviewState) => (s.now - s.startedAt) / 1000;

export function scrubCountdownSec(s: HoverPreviewState): number {
  if (s.id === null) return 0;
  return Math.max(0, etaFor(s.durationSec) - elapsedSec(s));
}

export function posterCountdownSec(s: HoverPreviewState): number {
  if (s.id === null) return 0;
  return Math.max(0, POSTER_ETA_SEC - elapsedSec(s));
}

function counting(s: HoverPreviewState): boolean {
  return (!!s.url && s.scrub === "loading" && scrubCountdownSec(s) > 0)
    || (s.scrub !== "ready" && !s.posterLoaded && posterCountdownSec(s) > 0);
}

export function hoverPreviewReducer(
  state: HoverPreviewState,
  action: HoverPreviewAction,
): HoverPreviewState {
  switch (action.type) {
    case "enter":
      return {
        ...IDLE_HOVER,
        id: action.id,
        sid: action.sid,
        durationSec: action.durationSec || 0,
        url: action.url || null,
        startedAt: action.now,
        now: action.now,
      };
    case "leave":
      return state.id === null ? state : IDLE_HOVER;
    case "beat":
      if (state.id === null) return state;
      return { ...state, frame: (state.frame + 1) % SCRUB_FRAMES };
    case "tick":
      if (state.id === null || !counting(state)) return state;
      return { ...state, now: action.now };
    case "frameLoaded":
      if (action.sid !== state.sid || state.scrub === "ready") return state;
      return { ...state, scrub: "ready", frame: action.idx };
    case "frameError":
      if (action.sid !== state.sid || action.idx !== 0 || state.scrub !== "loading") return state;
      return { ...state, scrub: "failed" };
    case "posterLoaded":
      if (action.sid !== state.sid || state.posterLoaded) return state;
      return { ...state, posterLoaded: true };
    case "graceElapsed":
      if (action.sid !== state.sid || state.posterGrace) return state;
      return { ...state, posterGrace: true };
  }
}

function newSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// The relay ignores a cancel past ~90% downloaded or for an unknown session; keepalive lets it outlive an unmount.
function cancelScrubBuild(url: string, sid: string): void {
  const qs = new URLSearchParams();
  qs.set("u", url);
  qs.set("sid", sid);
  const tok = resolveShareToken();
  if (tok) qs.set("t", tok);
  fetch(`/img/scrub/cancel?${qs.toString()}`, { method: "POST", keepalive: true })
    .catch(() => { });
}

export function useHoverPreview(delayMs: number) {
  const [state, dispatch] = useReducer(hoverPreviewReducer, IDLE_HOVER);
  const timerRef = useRef<number | null>(null);
  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);
  const start = useCallback((id: number, durationSec: number, url: string | null) => {
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      dispatch({ type: "enter", id, durationSec, url, sid: newSessionId(), now: Date.now() });
    }, delayMs);
  }, [clearTimer, delayMs]);
  const stop = useCallback(() => {
    clearTimer();
    dispatch({ type: "leave" });
  }, [clearTimer]);
  useEffect(() => clearTimer, [clearTimer]);

  const { sid, url } = state;
  useEffect(() => {
    if (!sid) return;
    const beatId = window.setInterval(() => dispatch({ type: "beat" }), SCRUB_INTERVAL_MS);
    const tickId = window.setInterval(() => dispatch({ type: "tick", now: Date.now() }), TICK_MS);
    const graceId = window.setTimeout(() => dispatch({ type: "graceElapsed", sid }), POSTER_GRACE_MS);
    return () => {
      window.clearInterval(beatId);
      window.clearInterval(tickId);
      window.clearTimeout(graceId);
      if (url) cancelScrubBuild(url, sid);
    };
  }, [sid, url]);

  const frameProps = (idx: number) => ({
    onLoad: () => dispatch({ type: "frameLoaded", sid, idx }),
    onError: () => dispatch({ type: "frameError", sid, idx }),
  });
  const onPosterLoad = () => dispatch({ type: "posterLoaded", sid });

  return { state, start, stop, frameProps, onPosterLoad };
}
