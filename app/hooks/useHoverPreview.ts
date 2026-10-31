/**
 * useHoverPreview — the video hover-preview state machine shared by the vault
 * picker's tiles (VaultPicker), the vault manager's tiles (VaultTile) and the
 * Fan drawer's PPV thumbs (FanDrawer `VideoScrubThumb`).
 *
 * A hover commits after a dwell, gets a fresh session id, and plays the
 * relay's 12-frame /img/scrub storyboard as a slideshow. Until a frame lands
 * the tile shows an ETA countdown for the cold storyboard build (and, in the
 * picker, a decimal countdown until OF's first poster frame lands). Leaving,
 * re-hovering another tile or unmounting POSTs /img/scrub/cancel for that
 * session so the relay can drop a build nobody is watching.
 *
 * Every image event carries the session id it was rendered for; the reducer
 * drops events from any other session. That is what lets a late onLoad from a
 * tile the user already left be ignored without a ref mirrored by
 * useLayoutEffect.
 */
import { useCallback, useEffect, useReducer, useRef } from "react";

import { resolveShareToken } from "@/lib/shareToken";

/** Hover dwell before a preview commits — stops a brush past 20 tiles from
 *  building 20 storyboards. The one dwell: every hover surface uses it. */
export const HOVER_DELAY_MS = 400;
/** Storyboard frames per video. The relay keys its /img/scrub disk cache by
 *  mp4 hash + frame index, so every surface must ask for the same 12. */
export const SCRUB_FRAMES = 12;
/** One slideshow beat. */
export const SCRUB_INTERVAL_MS = 600;
/** Fixed ETA for OF's first poster frame: one CDN GET through the proxy
 *  (~1-2.5s cold), independent of video length. */
export const POSTER_ETA_SEC = 2.5;
/** Grace before the picker falls back to OF poster frames. A warm storyboard
 *  reveals in ~3ms, so posters never fetch; a cold one shows them after this. */
export const POSTER_GRACE_MS = 250;
/** Countdown refresh: fine enough for the poster countdown's 0.1s decimals. */
const TICK_MS = 100;

/** Storyboard state for the current hover: still building, a frame painted,
 *  or frame 0 failed (drop the "building" affordance, fall back to the thumb). */
export type ScrubStatus = "loading" | "ready" | "failed";

export interface HoverPreviewState {
  /** Hovered item (vault media id), null when nothing is committed. */
  id: number | null;
  /** Per-hover session id, sent with every frame GET and the cancel POST so a
   *  late cancel from an old hover can't abort a fresh build. "" when idle. */
  sid: string;
  durationSec: number;
  /** Raw video url the build runs for — the cancel POST names it. */
  url: string | null;
  /** Slideshow cursor, 0..SCRUB_FRAMES-1. */
  frame: number;
  scrub: ScrubStatus;
  /** First OF poster frame painted (picker only). */
  posterLoaded: boolean;
  /** POSTER_GRACE_MS passed since commit (picker only). */
  posterGrace: boolean;
  /** Commit time and the latest tick, in ms — the countdowns derive from them. */
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

/**
 * Seconds the relay needs to build a cold storyboard for a video this long.
 * Piecewise, calibrated against real cold builds with +2s padding:
 *   ≤ 60s: 4.5 + 0.5 × ceil(dur/15)  (15s ≈ 5s, 30s ≈ 6s, 60s ≈ 7s)
 *   > 60s: 6.5 + 7 × (dur − 60)/60   (proxy throughput dominates; 7s/min)
 * then ×1.3, because measured builds still ran longer (a 34s clip took ~11.5s
 * against a ~6s estimate: the full-mp4 download through the proxy dominates).
 * Floor is 7s (any clip up to 15s). A missing/zero/NaN duration counts as 1s.
 */
export function etaFor(durationSec: number): number {
  const dur = Math.max(1, durationSec || 0);
  const base = dur <= 60
    ? 4.5 + 0.5 * Math.ceil(dur / 15)
    : 6.5 + (7 * (dur - 60)) / 60;
  return Math.round(base * 1.3);
}

const elapsedSec = (s: HoverPreviewState) => (s.now - s.startedAt) / 1000;

/** Seconds left on the storyboard ETA (0 when idle or overdue → show "…"). */
export function scrubCountdownSec(s: HoverPreviewState): number {
  if (s.id === null) return 0;
  return Math.max(0, etaFor(s.durationSec) - elapsedSec(s));
}

/** Seconds left on the first-poster ETA (0 when idle or overdue → show "…"). */
export function posterCountdownSec(s: HoverPreviewState): number {
  if (s.id === null) return 0;
  return Math.max(0, POSTER_ETA_SEC - elapsedSec(s));
}

/** A countdown may still be on screen and moving, so a tick must re-render.
 *  No url means no storyboard build (a DRM tile), so only the poster one runs. */
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
      // Any frame clears the build state — one failed frame-0 fetch can't pin
      // it — and the cursor jumps to the frame known to have painted.
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
  // crypto.randomUUID is in every browser we target; the fallback covers an
  // old WebView.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Fire-and-forget: ask the relay to abort the storyboard build for this hover
 *  session. The relay ignores it past ~90% downloaded or for an unknown
 *  session. `keepalive` lets it outlive an immediate unmount. */
function cancelScrubBuild(url: string, sid: string): void {
  const qs = new URLSearchParams();
  qs.set("u", url);
  qs.set("sid", sid);
  const tok = resolveShareToken();
  if (tok) qs.set("t", tok);
  fetch(`/img/scrub/cancel?${qs.toString()}`, { method: "POST", keepalive: true })
    .catch(() => { /* fire-and-forget */ });
}

/**
 * The hover preview for a set of tiles. `start` arms the dwell (`delayMs`);
 * `stop` disarms it and ends the hover. `frameProps(idx)` and `onPosterLoad`
 * wire the storyboard / poster <img>s to the current session.
 */
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
