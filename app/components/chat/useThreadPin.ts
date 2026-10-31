"use client";

/**
 * useThreadPin — the Thread's scroll: scroll-only-if-at-bottom, the first
 * load's auto-pin to the latest message, the load-older anchor, the "↓ Latest"
 * button and the top sentinel's auto-load. The decisions are threadPin.ts's;
 * this hook owns the refs, the listeners and the two pieces of state.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { OFMessage } from "@/lib/relay";
import {
  afterRender, AUTO_PIN_BACKSTOP_MS, distanceFromBottom, mayLoadOlder, onScrollDecision, PIN_POLL_MS,
  touchReleases, type Point, type Scroll,
} from "./threadPin";

export function useThreadPin({ messages, hasOlder, loadingOlder, onLoadOlder }: {
  messages: OFMessage[];
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const topSentinelRef = useRef<HTMLDivElement | null>(null);
  const lastLenRef = useRef(0);
  // True until the first non-empty message render has been pinned to the
  // bottom. Without this, the IntersectionObserver below fires the
  // moment the top sentinel becomes visible during the initial render
  // (when scrollTop is still 0), which yanks the view back to old
  // messages instead of letting the user see the newest ones.
  const firstLoadPendingRef = useRef(true);
  // "↓ Latest" affordance: shown when the user is scrolled more than
  // AT_BOTTOM_PX * 4 up from the bottom (onScrollDecision's `showJump`).
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  // The "Jumping to latest…" label: true while the first load's auto-pin
  // holds, false once releasePin lets go.
  const [autoPinActive, setAutoPinActive] = useState(true);
  // The container's geometry snapshot (scrollHeight, scrollTop,
  // clientHeight): afterRender reads at-bottom and the load-older anchor
  // off it. Null until the first commit with a container.
  const scrollSnapshotRef = useRef<Scroll | null>(null);
  // Set true immediately before every programmatic `scrollTop = scrollHeight`
  // write (the 60Hz pin poll + the media-load RAF repin). The `scroll` event
  // those writes emit is indistinguishable from a user scroll, so the scroll
  // release handler consumes this flag to ignore our own writes — letting
  // genuine user scrolls (scrollbar-thumb drag, gutter click, momentum fling)
  // release the auto-pin even though they emit no wheel/touchmove/keydown.
  const programmaticScrollRef = useRef(false);

  /** Let go of the first load's auto-pin: the 5s backstop, a user-only
   *  gesture (wheel/vertical touchmove/keydown) and a user scroll out of the
   *  bottom band all end here. Stable identity, so listing it as an effect
   *  dep never re-runs an effect. */
  const releasePin = useCallback(() => {
    firstLoadPendingRef.current = false;
    setAutoPinActive(false);
  }, []);

  // Snapshot the container's geometry. Deps-less, so this runs after EVERY
  // commit, including the one that inserted new messages, and before that
  // commit's [messages] effect below. So the snapshot (and the at-bottom
  // read off it) is taken AFTER the insert, not before it: by the time the
  // effect below compares, scrollHeight has usually not moved since, the
  // anchor delta is ~0 and the anchor branch rarely fires. Kept as-is on
  // purpose (behaviour-neutral split); fixing it is a separate change.
  useLayoutEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    scrollSnapshotRef.current = { scrollHeight: c.scrollHeight, scrollTop: c.scrollTop, clientHeight: c.clientHeight };
  });

  // After render: decide between "stick to bottom" (initial / new message)
  // and "preserve anchor" (older page loaded at top).
  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const d = afterRender({
      prevLen: lastLenRef.current, len: messages.length,
      pre: scrollSnapshotRef.current, scrollHeight: c.scrollHeight,
    });
    lastLenRef.current = messages.length;
    if (d.kind === "initial") {
      // Initial paint: hard-pin to the bottom now + next frame. The effect
      // below keeps re-pinning while firstLoadPendingRef stays true, so
      // late-loading media that grow the container after this point still
      // land us at the bottom.
      const pinBottom = () => { c.scrollTop = c.scrollHeight; };
      pinBottom();
      requestAnimationFrame(pinBottom);
      // Hard backstop: release the auto-pin after 5s regardless of user
      // interaction, so a chat with media that never settles can't keep
      // yanking the view forever. 5s (was 2s) covers the common case of
      // 4-5 image thumbs loading sequentially on a cold tab — fix #11.
      const t = setTimeout(releasePin, AUTO_PIN_BACKSTOP_MS);
      return () => clearTimeout(t);
    }
    // Older page came in at the top: `anchor` keeps the previously-visible
    // message in view by the height delta.
    if (d.kind === "pin") c.scrollTop = c.scrollHeight;
    else if (d.kind === "anchor") c.scrollTop = d.top;
  }, [messages, releasePin]);

  // Late-arriving media (large images, video posters) grow the *content*
  // after the initial pin. A ResizeObserver on the container itself
  // doesn't fire (the container's borderBox stays constant — flex-1
  // inside a fixed-height column; only `scrollHeight` grows).
  //
  // Two-track re-pin for the first 5s of pendingRef:
  //   1. Per-frame poll (60Hz). Cheap, idempotent (scrollTop = scrollHeight
  //      is a no-op when already at bottom). Catches every layout shift
  //      including ones the load listener might race past — browser
  //      scroll anchoring, font swap, late-arriving DOM, mediastrip
  //      relayout. This was the bug behind fix #11's "bounce to middle".
  //   2. Capture-phase `load` listener on the container. <img>/<video>
  //      `load` doesn't bubble; capture phase lets us catch them all.
  //      Triggers an extra RAF pin so the visual snap happens the same
  //      frame the image paints, not at the next 16ms tick.
  const hasMessages = messages.length > 0;
  useEffect(() => {
    if (!hasMessages) return;
    const c = containerRef.current;
    if (!c) return;
    let rafId: number | null = null;
    const repin = () => {
      if (!firstLoadPendingRef.current) return;
      if (rafId != null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (firstLoadPendingRef.current) {
          programmaticScrollRef.current = true;
          c.scrollTop = c.scrollHeight;
        }
      });
    };
    // Image/video load events don't bubble — use capture-phase listener.
    const onMediaLoad = (e: Event) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.tagName === "IMG" || t.tagName === "VIDEO") repin();
    };
    c.addEventListener("load", onMediaLoad, true);
    // 60Hz poll for the first 5s. Stops as soon as pendingRef flips false.
    const pollId = window.setInterval(() => {
      if (!firstLoadPendingRef.current) {
        window.clearInterval(pollId);
        return;
      }
      programmaticScrollRef.current = true;
      c.scrollTop = c.scrollHeight;
    }, PIN_POLL_MS);
    // `wheel` / `touchmove` / `keydown` are user-only signals that release
    // the auto-pin immediately. They don't cover scrollbar-thumb drag,
    // scrollbar-gutter clicks or momentum/inertial flings the browser
    // dispatches only as `scroll` — those are handled by the guarded scroll
    // path in onScroll below (onScrollDecision tells our own pin writes from
    // a real user scroll via programmaticScrollRef).
    const release = (e: Event) => {
      if (!e.isTrusted) return;
      releasePin();
    };
    // A sideways swipe (the Thread's swipe back, kept or cancelled) is not a
    // scroll: touchReleases.
    let touch0: Point | null = null;
    const onTouchStart = (e: TouchEvent) => {
      const t = e.touches[0];
      touch0 = t ? { x: t.clientX, y: t.clientY } : null;
    };
    const onTouchMove = (e: TouchEvent) => {
      const t = e.touches[0];
      if (!touchReleases(touch0, t ? { x: t.clientX, y: t.clientY } : null)) return;
      release(e);
    };
    c.addEventListener("wheel", release, { passive: true });
    c.addEventListener("touchstart", onTouchStart, { passive: true });
    c.addEventListener("touchmove", onTouchMove, { passive: true });
    c.addEventListener("keydown", release);
    // "↓ Latest" affordance: passive scroll listener tracks distance from
    // bottom so we can surface the jump button when the user scrolls up.
    // Toggling via state is fine — the button only re-renders, not the
    // bubble list.
    //
    // Also doubles as a release signal for scroll-only gestures (scrollbar
    // drag/gutter, momentum). Our own pin writes emit `scroll` too, but they
    // set programmaticScrollRef just before the write — so we consume that
    // flag and ignore them (onScrollDecision).
    const onScroll = () => {
      const d = onScrollDecision({
        programmatic: programmaticScrollRef.current,
        pending: firstLoadPendingRef.current,
        distance: distanceFromBottom(c),
      });
      setShowJumpLatest(d.showJump);
      programmaticScrollRef.current = false;
      if (d.release) releasePin();
    };
    c.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.clearInterval(pollId);
      if (rafId != null) cancelAnimationFrame(rafId);
      c.removeEventListener("load", onMediaLoad, true);
      c.removeEventListener("wheel", release);
      c.removeEventListener("touchstart", onTouchStart);
      c.removeEventListener("touchmove", onTouchMove);
      c.removeEventListener("keydown", release);
      c.removeEventListener("scroll", onScroll);
    };
  }, [hasMessages, releasePin]);

  // Auto-load older when the top sentinel scrolls into view. Same pattern
  // as ChatList's infinite scroll, just inverted (top instead of bottom).
  // mayLoadOlder ignores intersections while `firstLoadPendingRef` is true.
  useEffect(() => {
    const el = topSentinelRef.current;
    if (!el || !hasOlder) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (mayLoadOlder({
          pending: firstLoadPendingRef.current, intersecting: entries.some((e) => e.isIntersecting),
          hasOlder, loadingOlder,
        })) onLoadOlder();
      },
      { root: containerRef.current, rootMargin: "200px 0px 0px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasOlder, loadingOlder, onLoadOlder]);

  /** The "↓ Latest" button's click: a smooth scroll to the bottom. */
  const jumpToLatest = () => {
    const c = containerRef.current;
    if (!c) return;
    c.scrollTo({ top: c.scrollHeight, behavior: "smooth" });
  };

  /** A quote card's tap: smooth-scroll the quoted message into view. The id
   *  is matched as a string against `data-msg-id`, never Number()'d. */
  const jumpToMessage = (id: number | string) => {
    const el = containerRef.current?.querySelector(
      `[data-msg-id="${CSS.escape(String(id))}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return { containerRef, topSentinelRef, showJumpLatest, autoPinActive, jumpToLatest, jumpToMessage };
}
