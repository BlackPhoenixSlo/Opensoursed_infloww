"use client";

/**
 * OF's hover text on the OF mirror's Statistics and Statements pages. OF marks an element with a tooltip `has-tooltip`
 * and keeps its text in `aria-label` (v-tooltip): the "i" icons (Pending balance, Chargeback ratio, Unsend), an
 * earnings row's status tip ("Complete", "Earning will become available in N days"), the header's Support. Hovering or
 * focusing one shows that text in OF's own tooltip markup (app.css `.tooltip`, `.tooltip-arrow`, `.tooltip-inner`)
 * above it, below when there is no room above, as live OF does; leaving or blurring it hides it. A disabled control
 * (its own `title` says "Not available in Inflowwww yet") or one with no text shows none.
 */

import { useEffect, type RefObject } from "react";

/**
 * A disabled control's tooltip, in place of "Not available in Inflowwww yet", where another Inflowwww page does its job
 * (read-only → redirect): where to go instead. Plain text: the mirror's tooltips are `title`s, which carry no link.
 */
export const ELSEWHERE = {
  /** OF's welcome message (Settings › Chats): its Edit and Delete. */
  welcome: "Use Smart Messages → Automated Messages → Delayed welcome",
  /** A mass message's Unsend (Statistics' Top Message). */
  unsendMass: "Use Smart Messages → Mass Messages → OF mass messages to unsend it",
  /** A chat's Purchases (the chat header's menu). */
  fanPurchases: "Use Messages Pro → the fan's Sales tab",
} as const;

/** The pages whose `has-tooltip` elements show their text. */
export const tooltipPage = (page: string) => /^(statistics|statements)\//.test(page);

const TIP = "data-oi-tooltip";

/** The element whose text a hover on `target` shows (none: no tooltip). */
export function tipTarget(target: EventTarget | null): HTMLElement | null {
  const el = (target as Element | null)?.closest?.<HTMLElement>(".has-tooltip[aria-label]");
  if (!el || el.hasAttribute("title") || el.hasAttribute("disabled") || el.closest("[disabled]")) return null;
  return el.getAttribute("aria-label")?.trim() ? el : null;
}

/** OF's tooltip for `el` (its aria-label) in `doc`, above it (no room: below), centred on it. */
export function showTip(doc: Document, el: HTMLElement): HTMLElement {
  hideTip(doc);
  const tip = doc.createElement("div");
  tip.setAttribute(TIP, "");
  tip.setAttribute("role", "tooltip");
  tip.className = "tooltip vue-tooltip-theme";
  const arrow = doc.createElement("div");
  arrow.className = "tooltip-arrow";
  const inner = doc.createElement("div");
  inner.className = "tooltip-inner";
  inner.textContent = el.getAttribute("aria-label")!.trim();
  tip.append(arrow, inner);
  tip.style.position = "absolute";
  tip.style.top = "0";
  tip.style.left = "0";
  doc.body.append(tip);
  const win = doc.defaultView;
  const r = el.getBoundingClientRect();
  const t = tip.getBoundingClientRect();
  const sx = win?.scrollX ?? 0;
  const sy = win?.scrollY ?? 0;
  const below = r.top - t.height - 8 < 0;
  tip.setAttribute("x-placement", below ? "bottom" : "top");
  const width = win?.innerWidth ?? Infinity;
  const left = Math.max(4, Math.min(r.left + r.width / 2 - t.width / 2, width - t.width - 4));
  tip.style.left = `${left + sx}px`;
  tip.style.top = `${(below ? r.bottom + 8 : r.top - t.height - 8) + sy}px`;
  // The arrow under (over) the element's centre.
  arrow.style.left = `${Math.max(4, r.left + r.width / 2 - left - 5)}px`;
  if (below) arrow.style.top = "-5px";
  else arrow.style.bottom = "-5px";
  return tip;
}

export function hideTip(doc: Document): void {
  for (const t of doc.querySelectorAll(`[${TIP}]`)) t.remove();
}

const bound = new WeakSet<Document>();
/** Hover and focus show an element's tooltip; leaving it, blurring it, scrolling or Escape hide it. Bound once per page. */
export function bindTooltips(doc: Document): void {
  if (bound.has(doc)) return;
  bound.add(doc);
  let current: HTMLElement | null = null;
  const show = (ev: Event) => {
    const el = tipTarget(ev.target);
    if (!el || el === current) return;
    current = el;
    showTip(doc, el);
  };
  const hide = (ev: Event) => {
    if (!current) return;
    const to = (ev as MouseEvent | FocusEvent).relatedTarget as Node | null;
    if (to && current.contains(to)) return;
    current = null;
    hideTip(doc);
  };
  doc.addEventListener("mouseover", show);
  doc.addEventListener("focusin", show);
  doc.addEventListener("mouseout", hide);
  doc.addEventListener("focusout", hide);
  const reset = () => {
    current = null;
    hideTip(doc);
  };
  doc.addEventListener("scroll", reset, true);
  doc.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") reset();
  });
}

/** On a Statistics or Statements page, OF's hover text for its `has-tooltip` elements on every frame load. */
export function useOfTooltips(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const on = tooltipPage(page);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !on) return;
    const bind = () => {
      const doc = frame.contentDocument;
      if (doc?.body) bindTooltips(doc);
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => frame.removeEventListener("load", bind);
  }, [frameRef, src, on]);
}
