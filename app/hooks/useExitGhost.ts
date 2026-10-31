"use client";

import { useLayoutEffect, type RefObject } from "react";

import { EXIT_GHOST, SWIPED_ATTR } from "@/hooks/layerMarks";
import { prefersReducedMotion } from "@/hooks/prefersReducedMotion";

/** Longer than the longest exit in globals.css (`.exit-ghost.sheet-*`, 200ms):
 *  lengthen that and this goes with it. */
const GHOST_MS = 260;
/** A bigger layer goes without a ghost: copying it would cost more than the fade is worth. */
const MAX_NODES = 1500;
/** A copy of these would restart (a video, a frame) or come out blank (a canvas). */
const LIVE_MEDIA = "video, audio, iframe, canvas, object, embed";

/**
 * An exit animation that never blocks: when the layer ends, each ref's element
 * is copied into its place as an `EXIT_GHOST`, which globals.css animates out
 * (a `.pop-modal` shrinks and fades, a `.pop-menu` fades, a `.sheet-*` slides
 * off) and which is dropped after `GHOST_MS`. The real element unmounts at once,
 * so focus, scroll and clicks return to the page immediately and the next open
 * does not wait.
 *
 * `active` is the layer's lifetime: pass the open flag when the component stays
 * mounted while closed (the copy is made when it turns false), or `true` when
 * the component mounts with the layer and unmounts with it (the copy is made on
 * unmount).
 *
 * The copy is inert and aria-hidden, takes no click, keeps the scroll offsets
 * the original showed, and has no `id` or `name` anywhere in it (no duplicate
 * ids, no radio input joining the original's group). It
 * keeps its role and data-* attributes, so it looks as it did on screen; what
 * looks for an open layer skips the copy (`notInGhost`).
 *
 * No copy under prefers-reduced-motion, for a layer a swipe already slid away
 * (`SWIPED_ATTR` on it or inside it, `useSwipe`), one holding live media, or one
 * too big to copy cheaply. An element still in the document right after its
 * cleanup (React's strict-mode remount, a fast refresh) had not left, so its
 * copy is dropped at once.
 */
export function useExitGhost(active: boolean, ...refs: RefObject<HTMLElement | null>[]) {
  useLayoutEffect(() => {
    if (!active) return;
    // Remember each element and its parent while mounted: by the cleanup React may have detached it (a child of
    // this component) or nulled its ref (Radix re-composes refs on close). A portal's content (Radix) mounts a
    // commit after `active` turns on, so look again on the next frame.
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
    // The refs are stable objects; only `active` starts and ends a layer.
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
  // No duplicate ids, and no field in the copy joins a radio group (React throws on a non-React radio sharing a name).
  for (const el of copies) { el.removeAttribute("id"); el.removeAttribute("name"); }
  ghost.setAttribute("aria-hidden", "true");
  ghost.inert = true;
  ghost.classList.add(EXIT_GHOST);
  parent.insertBefore(ghost, node.parentNode === parent ? node.nextSibling : null);
  // Scroll offsets are not copied by cloneNode: set them once the copy is in the document.
  originals.forEach((el, i) => {
    const [top, left] = el.isConnected ? [el.scrollTop, el.scrollLeft] : scrolled.get(el) ?? [0, 0];
    if (top || left) { copies[i].scrollTop = top; copies[i].scrollLeft = left; }
  });
  const drop = window.setTimeout(() => ghost.remove(), GHOST_MS);
  // Still in the document after the cleanup: it did not leave (strict mode, fast refresh).
  queueMicrotask(() => {
    if (node.isConnected) { window.clearTimeout(drop); ghost.remove(); }
  });
}
