"use client";

/**
 * DeepLinkTarget — walks a `#go=` hash (lib/deepLink.ts) on whatever page is
 * open: each step waits for its tab, toggle or heading to render, opens it,
 * and the last is scrolled to the middle and outlined for a moment.
 *
 * Runs on a page load or route change, on hashchange, and after a click on a
 * `#go=` link (a client navigation to the same route changes the hash with
 * pushState, which fires no hashchange). Renders nothing.
 */

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { pick, stepsOf, type Candidate, type CandidateKind } from "@/lib/deepLink";

/** How long one step waits for its element to render (data loads first). */
const STEP_WAIT_MS = 8_000;
const POLL_MS = 150;
const OUTLINE_MS = 2_500;

const SELECTOR = '[role="tab"], button[aria-expanded], summary, h1, h2, h3, h4, h5, legend';
/** The chrome around a page: its labels are not the page's parts. */
const OUTSIDE = '#app-sidebar, #app-sidebar-drawer, [aria-label="Help assistant"], header';

function kindOf(el: Element): CandidateKind {
  if (el.getAttribute("role") === "tab") return "tab";
  if (el.tagName === "SUMMARY" || el.hasAttribute("aria-expanded")) return "toggle";
  return "heading";
}

function find(step: string): HTMLElement | null {
  const els = [...document.querySelectorAll<HTMLElement>(SELECTOR)].filter(
    (el) => !el.closest(OUTSIDE) && (el.getClientRects().length > 0 || el.closest("details:not([open])")),
  );
  const cands: Candidate[] = els.map((el) => ({ text: el.textContent ?? "", kind: kindOf(el) }));
  const i = pick(cands, step);
  return i < 0 ? null : els[i];
}

function open(el: HTMLElement): void {
  const closed = el.closest("details:not([open])");
  if (closed) (closed as HTMLDetailsElement).open = true;
  const kind = kindOf(el);
  if (kind === "tab" && el.getAttribute("aria-selected") !== "true") el.click();
  else if (kind === "toggle" && el.tagName !== "SUMMARY" && el.getAttribute("aria-expanded") === "false") el.click();
}

function outline(el: HTMLElement): void {
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  const prev = { outline: el.style.outline, offset: el.style.outlineOffset };
  el.style.outline = "2px solid var(--color-accent, #3b82f6)";
  el.style.outlineOffset = "4px";
  el.setAttribute("data-deeplink-target", "");
  window.setTimeout(() => {
    el.style.outline = prev.outline;
    el.style.outlineOffset = prev.offset;
    el.removeAttribute("data-deeplink-target");
  }, OUTLINE_MS);
}

/** Walk `steps`; resolves when done or a step never shows. `alive()` false = a newer walk took over. */
async function walk(steps: string[], alive: () => boolean): Promise<void> {
  let last: HTMLElement | null = null;
  for (const step of steps) {
    let el: HTMLElement | null = null;
    for (let waited = 0; alive() && waited <= STEP_WAIT_MS; waited += POLL_MS) {
      el = find(step);
      if (el) break;
      await new Promise((r) => window.setTimeout(r, POLL_MS));
    }
    if (!el || !alive()) break;
    open(el);
    last = el;
    await new Promise((r) => window.setTimeout(r, POLL_MS)); // let the opened part render
  }
  if (last && alive()) outline(last);
}

export function DeepLinkTarget() {
  const pathname = usePathname();

  useEffect(() => {
    let run = 0;
    const start = () => {
      const steps = stepsOf(window.location.hash);
      if (!steps.length) return;
      const mine = ++run;
      void walk(steps, () => mine === run);
    };
    const onClick = (e: MouseEvent) => {
      // Only a link to this same route: one to another route is walked by the
      // route change, once the new page is the one in the DOM.
      const a = (e.target as Element | null)?.closest?.("a[href*='#go=']") as HTMLAnchorElement | null;
      if (a && new URL(a.href).pathname === window.location.pathname) window.setTimeout(start, 0);
    };
    start();
    window.addEventListener("hashchange", start);
    document.addEventListener("click", onClick);
    return () => {
      run++;
      window.removeEventListener("hashchange", start);
      document.removeEventListener("click", onClick);
    };
  }, [pathname]);

  return null;
}
