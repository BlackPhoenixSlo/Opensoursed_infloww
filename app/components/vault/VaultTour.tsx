"use client";

/**
 * Vault Pro's guided tours (growth-vault-pro#12, #118, #119, and the upload card's selection-bar tour), as the bundle
 * runs them through react-joyride (index.9f50f370.js @12944029 to @12949500 and @13101441 to @13108700), without the
 * dependency: a dimmed page, a spotlight on the target, and one tooltip beside it.
 *
 * Seen-once store: the bundle's own, `localStorage["vaultProOnboarding"]`, a JSON object of `{ <key>: "1" }`
 * (`getVaultProOnboardingCache` / `setVaultProOnboardingItemShow` @12944304). As there, a tour is marked seen the
 * moment it shows, not when it is dismissed, so a reload mid-tour never repeats it. Removing the key brings the
 * tours back.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

const STORE = "vaultProOnboarding";

/** The bundle's `VaultProOnboardingKeyMap` values (@12944029) for the tours built here. */
export type VaultTourKey = "batchUploadEntry" | "uploadPageStep" | "batchEdit" | "uploadBtn";

function readStore(): Record<string, string> {
  try {
    const v = JSON.parse(window.localStorage.getItem(STORE) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

/** `checkVaultProOnboardingItemShow`. */
export function vaultTourSeen(key: VaultTourKey): boolean {
  return readStore()[key] === "1";
}

/** `setVaultProOnboardingItemShow`. */
export function markVaultTourSeen(key: VaultTourKey): void {
  window.localStorage.setItem(STORE, JSON.stringify({ ...readStore(), [key]: "1" }));
}

/** True once, the first time `when` holds and the tour `key` has not been seen; marks it seen then (the bundle's way). */
export function useVaultTour(key: VaultTourKey, when: boolean): [boolean, () => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!when || vaultTourSeen(key)) return;
    markVaultTourSeen(key);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the store is read only after mount (no SSR access)
    setOpen(true);
  }, [key, when]);
  return [open, () => setOpen(false)];
}

export type VaultTourStep = { target: string; title?: string; content: string };

/** Joyride's default spotlight padding and the gap the bundle's tooltips keep from it. */
const PAD = 10;
const GAP = 12;

/**
 * One tour, in one of the bundle's two cards:
 *  - "coach": an icon, the text and "Got it", which moves to the next step or, on the last, closes (#12, and the
 *    selection bar's two steps, @12947586);
 *  - "guide": the upload guide's card, a title, the text, the numbered step markers, then "Next" and, on the last,
 *    "Start upload" (#118, #119). Its tours have no close button and ignore the overlay and Escape, so "Skip" is ours,
 *    labelled.
 * `spotlightClicks` lets the spotlit target take clicks, as the Add media tour's does. `overlayClose` lets a click on
 * the dimmed page close the tour, joyride's default, which the selection bar's tour keeps.
 */
export function VaultTour({
  steps,
  variant,
  placement,
  start = 0,
  overlayClose = false,
  spotlightClicks = false,
  onClose,
}: {
  steps: VaultTourStep[];
  variant: "coach" | "guide";
  placement: "left" | "right" | "top";
  start?: number;
  overlayClose?: boolean;
  spotlightClicks?: boolean;
  onClose: () => void;
}) {
  const [i, setI] = useState(start);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [tipH, setTipH] = useState(0);
  const tip = useRef<HTMLDivElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;

  useLayoutEffect(() => {
    const el = document.querySelector(step.target);
    if (el && "scrollIntoView" in el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest" });
    const place = () => {
      // The target's contents, not its box: a step title is a full-width block, and the bundle spotlights its text.
      const t = document.querySelector(step.target);
      let r: DOMRect | null = null;
      if (t) {
        const range = document.createRange();
        range.selectNodeContents(t);
        r = typeof range.getBoundingClientRect === "function" ? range.getBoundingClientRect() : t.getBoundingClientRect();
      }
      setRect(r && r.width + r.height > 0 ? r : null);
      setTipH(tip.current?.offsetHeight ?? 0);
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [step.target]);

  const vw = typeof window === "undefined" ? 0 : window.innerWidth;
  const vh = typeof window === "undefined" ? 0 : window.innerHeight;
  const width = Math.min(variant === "guide" ? 407 : 300, Math.max(0, vw - 16));
  const hole = rect && {
    left: rect.left - PAD,
    top: rect.top - PAD,
    width: rect.width + 2 * PAD,
    height: rect.height + 2 * PAD,
  };
  const clamp = (v: number, max: number) => Math.max(8, Math.min(v, max));
  // Beside the target on the placement's side, top-aligned with it; below it (above, near the bottom) when that side
  // has no room, as on a phone. "top" sits centred above it. Centred on screen when the target is not on the page.
  const side = hole && placement !== "top" && (placement === "left" ? hole.left - GAP - width : hole.left + hole.width + GAP);
  const fits = typeof side === "number" && side >= 8 && side + width <= vw - 8;
  const below = hole && (hole.top + hole.height + GAP + tipH <= vh - 8 ? hole.top + hole.height + GAP : hole.top - GAP - tipH);
  const pos = !hole
    ? { left: clamp((vw - width) / 2, vw), top: clamp((vh - tipH) / 2, vh) }
    : placement === "top"
      ? { left: clamp(hole.left + hole.width / 2 - width / 2, vw - width - 8), top: clamp(hole.top - GAP - tipH, vh - tipH - 8) }
      : fits
        ? { left: side as number, top: clamp(hole.top, vh - tipH - 8) }
        : { left: clamp(hole.left, vw - width - 8), top: clamp(below as number, vh - tipH - 8) };
  const lit = hole;
  // The blocker takes every click but the spotlight's when `spotlightClicks` (an even-odd hole in its clip path).
  const clip =
    spotlightClicks && lit
      ? `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${lit.left}px ${lit.top}px, ${lit.left + lit.width}px ${lit.top}px, ${lit.left + lit.width}px ${lit.top + lit.height}px, ${lit.left}px ${lit.top + lit.height}px, ${lit.left}px ${lit.top}px)`
      : undefined;

  if (typeof document === "undefined") return null;
  return createPortal(
    <>
      <div
        aria-hidden
        className={`fixed inset-0 z-[1001] ${lit ? "" : "bg-black/50"}`}
        style={{ clipPath: clip }}
        onClick={overlayClose ? onClose : undefined}
      />
      {lit && (
        <div
          aria-hidden
          className="pointer-events-none fixed z-[1001] rounded-lg shadow-[0_0_0_9999px_rgba(0,0,0,0.5)]"
          style={lit}
        />
      )}
      <div
        ref={tip}
        role="dialog"
        aria-label="Guided tour"
        className={`fixed z-[1002] rounded-lg bg-bg-elev-1 border border-border shadow-lg ${variant === "guide" ? "p-6" : "p-4"}`}
        style={{ width, ...pos }}
      >
        {variant === "guide" ? (
          <>
            <div className="text-lg font-bold">{step.title}</div>
            <div className="my-4 text-sm text-fg-dim">{step.content}</div>
            <div className="flex items-center justify-between">
              <div className="flex items-center">
                {steps.map((_, n) => (
                  <button
                    key={n}
                    type="button"
                    aria-current={n === i ? "step" : undefined}
                    onClick={() => setI(n)}
                    className={`mr-1 h-[14px] w-[14px] rounded-full text-center text-[10px] font-medium leading-[14px] ${n === i ? "bg-accent/15 text-accent" : "text-fg-dim hover:text-accent"}`}
                  >
                    {n + 1}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3">
                <button type="button" title={EXTRA_LABEL} onClick={onClose} className="text-sm text-fg-dim hover:text-fg">
                  Skip
                </button>
                {last ? (
                  <Button type="button" variant="primary" onClick={onClose}>
                    Start upload
                  </Button>
                ) : (
                  <Button type="button" variant="primary" onClick={() => setI(i + 1)}>
                    Next
                  </Button>
                )}
              </div>
            </div>
          </>
        ) : (
          <>
            <Sparkles size={26} className="mb-3 text-accent" aria-hidden />
            <div className="mb-5 text-sm">{step.content}</div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={last ? onClose : () => setI(i + 1)}
                className="text-sm font-medium text-fg-dim hover:text-accent"
              >
                Got it
              </button>
            </div>
          </>
        )}
      </div>
    </>,
    document.body,
  );
}
