"use client";


import { useEffect, type RefObject } from "react";
import { BRAND_NAME } from "@/lib/brand";

export const NOT_YET = `Not available in ${BRAND_NAME} yet`;

export function markWired(el: Element, live: boolean): void {
  if ("disabled" in el) el.disabled = false;
  if (live) el.removeAttribute("title");
  el.setAttribute("data-oi-wired", "");
}

export function markNotYet(el: Element): void {
  if ("disabled" in el) el.disabled = true;
  el.setAttribute("title", NOT_YET);
  el.removeAttribute("data-oi-wired");
}

export const ELSEWHERE = {
  welcome: "Use Smart Messages → Automated Messages → Delayed welcome",
  unsendMass: "Use Smart Messages → Mass Messages → OF mass messages to unsend it",
  fanPurchases: "Use Messages Pro → the fan's Sales tab",
} as const;

export const tooltipPage = (page: string) => /^(statistics|statements)\//.test(page);

const TIP = "data-oi-tooltip";

export function tipTarget(target: EventTarget | null): HTMLElement | null {
  const el = (target as Element | null)?.closest?.<HTMLElement>(".has-tooltip[aria-label]");
  if (!el || el.hasAttribute("title") || el.hasAttribute("disabled") || el.closest("[disabled]")) return null;
  return el.getAttribute("aria-label")?.trim() ? el : null;
}

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
  arrow.style.left = `${Math.max(4, r.left + r.width / 2 - left - 5)}px`;
  if (below) arrow.style.top = "-5px";
  else arrow.style.bottom = "-5px";
  return tip;
}

export function hideTip(doc: Document): void {
  for (const t of doc.querySelectorAll(`[${TIP}]`)) t.remove();
}

const bound = new WeakSet<Document>();
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
