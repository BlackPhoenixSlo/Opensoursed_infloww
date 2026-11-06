"use client";

/**
 * A vault gif's .mp4 looping over its picker tile's still (state: vaultGifLoopState.ts).
 *
 *   • No src until the tile is first on screen (IntersectionObserver), so an
 *     off-screen gif fetches nothing; plays while visible, pauses when it leaves.
 *   • prefers-reduced-motion: never autoplays; attached and played while the
 *     pointer is over the tile (its parent), paused on leave.
 *   • Muted, looped, no controls, no pointer events (the tile keeps its clicks).
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import { cn } from "@/lib/utils";
import { GIF_LOOP_INIT, gifLoopReducer, gifMounted, gifVisible } from "./vaultGifLoopState";

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/** `src`: the proxied mp4. `className`: the tile's blur, if any. */
export function VaultGifLoop({ src, className }: { src: string; className?: string }) {
  const [state, dispatch] = useReducer(gifLoopReducer, GIF_LOOP_INIT);
  const ref = useRef<HTMLVideoElement | null>(null);
  // Should it be playing now: on screen, or (reduced motion) hovered.
  const want = useRef(false);

  const sync = useCallback(() => {
    const el = ref.current;
    if (!el || !el.getAttribute("src")) return;
    if (want.current) el.play().catch(() => {});
    else el.pause();
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const set = (on: boolean) => {
      want.current = on;
      if (on) dispatch({ type: "attach" });
      sync();
    };
    if (reducedMotion()) {
      const tile = el.parentElement;
      if (!tile) return;
      const enter = (e: PointerEvent) => { if (e.pointerType !== "touch") set(true); };
      const leave = () => set(false);
      tile.addEventListener("pointerenter", enter);
      tile.addEventListener("pointerleave", leave);
      return () => {
        tile.removeEventListener("pointerenter", enter);
        tile.removeEventListener("pointerleave", leave);
      };
    }
    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => set(e.isIntersecting));
    io.observe(el);
    return () => io.disconnect();
  }, [sync]);

  // The render after `attach` put the src on: start it if still wanted.
  useEffect(() => {
    if (state.attached) sync();
  }, [state.attached, sync]);

  if (!gifMounted(state)) return null;
  return (
    <video
      ref={ref}
      data-gif-loop
      src={state.attached ? src : undefined}
      muted
      loop
      playsInline
      preload="auto"
      onPlaying={() => dispatch({ type: "playing" })}
      onPause={() => dispatch({ type: "paused" })}
      onError={() => dispatch({ type: "error" })}
      className={cn("absolute inset-0 w-full h-full object-cover pointer-events-none", className,
        !gifVisible(state) && "opacity-0")}
    />
  );
}
