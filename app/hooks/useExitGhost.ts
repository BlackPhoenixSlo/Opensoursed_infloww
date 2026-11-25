"use client";

import { useLayoutEffect, type RefObject } from "react";

import { EXIT_GHOST, SWIPED_ATTR } from "@/hooks/layerMarks";
import { prefersReducedMotion } from "@/hooks/prefersReducedMotion";

// Longer than the longest exit in globals.css (.exit-ghost.sheet-*, 200ms).
const GHOST_MS = 260;
const MAX_NODES = 1500;
const LIVE_MEDIA = "video, audio, iframe, canvas, object, embed";

export function useExitGhost(active: boolean, ...refs: RefObject<HTMLElement | null>[]) {
  useLayoutEffect(() => {
    if (!active) return;
    const seen: ({ node: HTMLElement; parent: ParentNode | null } | null)[] = refs.map(() => null);
    const look = () => refs.forEach((r, i) => {
      if (r.current?.parentNode) seen[i] = { node: r.current, parent: r.current.parentNode };
    });
    look();
    const frame = requestAnimationFrame(look);
    // A detached element reads scrollTop 0, so keep the offsets as they change.
    const scrolled = new Map<Element, [number, number]>();
    const onScroll = (e: Event) => {
      if (e.target instanceof Element) scrolled.set(e.target, [e.target.scrollTop, e.target.scrollLeft]);
    };
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("scroll", onScroll, { capture: true });
      look();
      if (prefersReducedMotion()) return;
      for (const s of seen) if (s) leaveGhost(s.node, s.parent, scrolled);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
}

function leaveGhost(node: HTMLElement, parent: ParentNode | null, scrolled: Map<Element, [number, number]>) {
  if (!parent?.isConnected) return;
  const skip = `[${SWIPED_ATTR}], ${LIVE_MEDIA}`;
  if (node.matches(skip) || node.querySelector(skip)) return;
  const originals = [node, ...node.getElementsByTagName("*")];
  if (originals.length > MAX_NODES + 1) return;
  const ghost = node.cloneNode(true) as HTMLElement;
  const copies = [ghost, ...ghost.getElementsByTagName("*")];
  // React throws on a non-React radio sharing a name with the original, and ids would duplicate.
  for (const el of copies) { el.removeAttribute("id"); el.removeAttribute("name"); }
  ghost.setAttribute("aria-hidden", "true");
  ghost.inert = true;
  ghost.classList.add(EXIT_GHOST);
  parent.insertBefore(ghost, node.parentNode === parent ? node.nextSibling : null);
  originals.forEach((el, i) => {
    const [top, left] = el.isConnected ? [el.scrollTop, el.scrollLeft] : scrolled.get(el) ?? [0, 0];
    if (top || left) { copies[i].scrollTop = top; copies[i].scrollLeft = left; }
  });
  const drop = window.setTimeout(() => ghost.remove(), GHOST_MS);
  queueMicrotask(() => {
    if (node.isConnected) { window.clearTimeout(drop); ghost.remove(); }
  });
}
