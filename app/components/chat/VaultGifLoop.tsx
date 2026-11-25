"use client";


import { useCallback, useEffect, useReducer, useRef } from "react";

import { cn } from "@/lib/utils";
import { GIF_LOOP_INIT, MAX_GIF_LOOPS, gifLoopReducer, gifMounted, gifSlots, gifVisible } from "./vaultGifLoopState";

const slots = gifSlots(MAX_GIF_LOOPS);

function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

// load() after dropping src makes the browser free the decoder and buffers.
export function releaseVideo(el: HTMLVideoElement): void {
  el.pause();
  if (!el.getAttribute("src")) return;
  el.removeAttribute("src");
  el.load();
}

export function VaultGifLoop({ src, className }: { src: string; className?: string }) {
  const [state, dispatch] = useReducer(gifLoopReducer, GIF_LOOP_INIT);
  const ref = useRef<HTMLVideoElement | null>(null);
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
    if (!el) return;
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
