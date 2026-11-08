"use client";

/**
 * A vault gif's .mp4 looping over its picker tile's still (state: vaultGifLoopState.ts).
 *
 *   • No src until the tile is on screen (IntersectionObserver) and holds one of the MAX_GIF_LOOPS slots shared by
 *     every tile, so an off-screen gif fetches nothing; plays while visible. Off screen it is detached: the src
 *     comes off and `load()` releases its decoder buffers, and its slot goes to the next tile waiting.
 *   • A hidden tab (visibilitychange) pauses it; back, it plays again.
 *   • prefers-reduced-motion: never autoplays; attached and played while the
 *     pointer is over the tile (its parent), detached on leave.
 *   • Muted, looped, no controls, no pointer events (the tile keeps its clicks).
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import { cn } from "@/lib/utils";
import { GIF_LOOP_INIT, MAX_GIF_LOOPS, gifLoopReducer, gifMounted, gifSlots, gifVisible } from "./vaultGifLoopState";

// Module-level: one cap for every loop on the page.
const slots = gifSlots(MAX_GIF_LOOPS);

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** Let go of a <video>'s clip: pause, drop the src, and `load()` so the browser frees its decoder and buffers. */
export function releaseVideo(el: HTMLVideoElement): void {
  el.pause();
  if (!el.getAttribute("src")) return;
  el.removeAttribute("src");
  el.load();
}

/** `src`: the proxied mp4. `className`: the tile's blur, if any. */
export function VaultGifLoop({ src, className }: { src: string; className?: string }) {
  const [state, dispatch] = useReducer(gifLoopReducer, GIF_LOOP_INIT);
  const ref = useRef<HTMLVideoElement | null>(null);
  // Should it be playing now: on screen with a slot, or (reduced motion) hovered.
  const want = useRef(false);
  const mounted = gifMounted(state);

  const sync = useCallback(() => {
    const el = ref.current;
    if (!el || !el.getAttribute("src")) return;
    if (want.current && !document.hidden) el.play().catch(() => {});
    else el.pause();
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;   // failed: the <video> is gone, and so is its slot (the cleanup below)
    const me = {};
    const grant = () => {
      want.current = true;
      dispatch({ type: "attach" });
      sync();
    };
    const leave = () => {
      slots.release(me);
      if (!want.current) return;
      want.current = false;
      releaseVideo(el);
      dispatch({ type: "detach" });
    };
    const set = (on: boolean) => {
      if (!on) leave();
      else if (slots.acquire(me, grant)) grant();
    };
    document.addEventListener("visibilitychange", sync);
    let stop = () => {};
    if (reducedMotion()) {
      const tile = el.parentElement;
      if (tile) {
        const enter = (e: PointerEvent) => { if (e.pointerType !== "touch") set(true); };
        const out = () => set(false);
        tile.addEventListener("pointerenter", enter);
        tile.addEventListener("pointerleave", out);
        stop = () => {
          tile.removeEventListener("pointerenter", enter);
          tile.removeEventListener("pointerleave", out);
        };
      }
    } else if (typeof IntersectionObserver !== "undefined") {
      const io = new IntersectionObserver(([e]) => set(e.isIntersecting));
      io.observe(el);
      stop = () => io.disconnect();
    }
    return () => {
      stop();
      document.removeEventListener("visibilitychange", sync);
      leave();
    };
  }, [sync, mounted]);

  // The render after `attach` put the src on: start it if still wanted.
  useEffect(() => {
    if (state.attached) sync();
  }, [state.attached, sync]);

  if (!mounted) return null;
  return (
    <video
      ref={ref}
      data-gif-loop
      src={state.attached ? src : undefined}
      muted
      loop
      playsInline
      preload={state.attached ? "auto" : "none"}
      onPlaying={() => dispatch({ type: "playing" })}
      onPause={() => dispatch({ type: "paused" })}
      onError={() => dispatch({ type: "error" })}
      className={cn("absolute inset-0 w-full h-full object-cover pointer-events-none", className,
        !gifVisible(state) && "opacity-0")}
    />
  );
}
