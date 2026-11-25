"use client";


import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import type { OFMessage } from "@/lib/relay";
import {
  afterRender, AUTO_PIN_BACKSTOP_MS, distanceFromBottom, mayLoadOlder, onScrollDecision,
  PIN_POLL_MS, rowsPrepended, SENTINEL_MARGIN_PX, touchReleases, type Point, type Scroll,
} from "./threadPin";

export function useThreadPin({
  messages, hasOlder, loadingOlder, olderFailed = false, headSettled = false, onLoadOlder,
}: {
  messages: OFMessage[];
  hasOlder: boolean;
  loadingOlder: boolean;
  olderFailed?: boolean;
  headSettled?: boolean;
  onLoadOlder: () => void;
}) {
  const onLoadOlderRef = useRef(onLoadOlder);
  useLayoutEffect(() => { onLoadOlderRef.current = onLoadOlder; });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const topSentinelRef = useRef<HTMLDivElement | null>(null);
  const lastLenRef = useRef(0);
  // Until pinned, the top-sentinel observer would fire at scrollTop 0 and yank the view to old messages.
  const firstLoadPendingRef = useRef(true);
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const [autoPinActive, setAutoPinActive] = useState(true);
  const committedRef = useRef<OFMessage[] | null>(null);
  const snapshotRef = useRef<{ for: OFMessage[]; pre: Scroll | null } | null>(null);
  if (messages !== committedRef.current && snapshotRef.current?.for !== messages) {
    const c = containerRef.current;
    snapshotRef.current = {
      for: messages,
      pre: c ? { scrollHeight: c.scrollHeight, scrollTop: c.scrollTop, clientHeight: c.clientHeight } : null,
    };
  }
  // Our own scrollTop writes emit `scroll` like a user scroll; this flag lets onScroll ignore them.
  const programmaticScrollRef = useRef(false);

  const releasePin = useCallback(() => {
    firstLoadPendingRef.current = false;
    setAutoPinActive(false);
  }, []);

  useLayoutEffect(() => {
    const prev = committedRef.current ?? [];
    committedRef.current = messages;
    const pre = snapshotRef.current?.for === messages ? snapshotRef.current.pre : null;
    snapshotRef.current = null;
    const c = containerRef.current;
    if (!c) return;
    const d = afterRender({
      prevLen: lastLenRef.current, len: messages.length,
      pre, scrollHeight: c.scrollHeight, prepended: rowsPrepended(prev, messages),
    });
    lastLenRef.current = messages.length;
    if (d.kind === "initial") {
      const pinBottom = () => { c.scrollTop = c.scrollHeight; };
      pinBottom();
      requestAnimationFrame(pinBottom);
      return;
    }
    if (firstLoadPendingRef.current) {
      programmaticScrollRef.current = true;
      c.scrollTop = c.scrollHeight;
      return;
    }
    if (d.kind === "pin") c.scrollTop = c.scrollHeight;
    else if (d.kind === "anchor") c.scrollTop = d.top;
  }, [messages, releasePin]);

  const hasMessages = messages.length > 0;

  useEffect(() => {
    if (!hasMessages || !firstLoadPendingRef.current) return;
    // Armed once per chat; inside the [messages] effect its cleanup cleared it and nothing re-armed it.
    const t = setTimeout(releasePin, AUTO_PIN_BACKSTOP_MS);
    return () => clearTimeout(t);
  }, [hasMessages, releasePin]);

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
    const onMediaLoad = (e: Event) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.tagName === "IMG" || t.tagName === "VIDEO") repin();
    };
    // img/video `load` does not bubble: capture phase. A ResizeObserver misses it (borderBox constant, only scrollHeight grows).
    c.addEventListener("load", onMediaLoad, true);
    const pollId = window.setInterval(() => {
      if (!firstLoadPendingRef.current) {
        window.clearInterval(pollId);
        return;
      }
      programmaticScrollRef.current = true;
      c.scrollTop = c.scrollHeight;
    }, PIN_POLL_MS);
    const release = (e: Event) => {
      if (!e.isTrusted) return;
      releasePin();
    };
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

  const fillsRef = useRef(0);
  useEffect(() => {
    const el = topSentinelRef.current;
    if (!el || !hasOlder || olderFailed) return;
    const io = new IntersectionObserver(
      (entries) => {
        const pending = firstLoadPendingRef.current;
        if (!mayLoadOlder({
          pending, headSettled, fills: fillsRef.current, intersecting: entries.some((e) => e.isIntersecting),
          hasOlder, loadingOlder, failed: olderFailed,
        })) return;
        if (pending) fillsRef.current += 1;
        onLoadOlderRef.current();
      },
      { root: containerRef.current, rootMargin: `${SENTINEL_MARGIN_PX}px 0px 0px 0px` },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasOlder, loadingOlder, olderFailed, autoPinActive, hasMessages, headSettled]);

  const jumpToLatest = () => {
    const c = containerRef.current;
    if (!c) return;
    c.scrollTo({ top: c.scrollHeight, behavior: "smooth" });
  };

  const jumpToMessage = useCallback((id: number | string) => {
    const el = containerRef.current?.querySelector(
      `[data-msg-id="${CSS.escape(String(id))}"]`,
    );
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  return { containerRef, topSentinelRef, showJumpLatest, autoPinActive, jumpToLatest, jumpToMessage };
}
