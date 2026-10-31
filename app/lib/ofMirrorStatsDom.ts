"use client";

/**
 * The Statistics pages' DOM helpers (ofMirrorStats and its per-tab modules): every change is tracked per page, so one
 * apply undoes the last before it draws again (idempotent); the wall clock in the owner's time zone; OF's number formats.
 */

import { valid } from "@/lib/ofMirrorData";
import { undoList } from "@/lib/ofMirrorUndo";
import { usd } from "@/lib/ofMirrorMoney";
import { elOf, iconOf } from "@/lib/ofMirrorAvatar";

export { elOf, iconOf };

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const SHORT = MONTHS.map((m) => m.slice(0, 3));
export const pad = (n: number) => String(n).padStart(2, "0");

export interface Wall {
  y: number;
  m: number; // 1-12
  d: number;
  h: number;
  mi: number;
  s: number;
}

/** The wall clock of `at` in `tz` (the browser's when null). */
export function wallOf(at: Date, tz: string | null): Wall {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz ?? undefined, hourCycle: "h23",
    year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric",
  }).formatToParts(at);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { y: part("year"), m: part("month"), d: part("day"), h: part("hour"), mi: part("minute"), s: part("second") };
}

/** OF's "MMM DD, YYYY" (`dayPad` false: "MMM D, YYYY"). */
export const dayText = (d: Date, tz: string | null, dayPad = true) => {
  const w = wallOf(d, tz);
  return `${SHORT[w.m - 1]} ${dayPad ? pad(w.d) : w.d}, ${w.y}`;
};
/** OF's agenda date "MMM D, YYYY, hh:mm a" in `tz` (a Top card's, a message's). */
export const agendaText = (d: Date, tz: string | null) => `${dayText(d, tz, false)}, ${timeText(d, tz)}`;
/** OF's "hh:mm a". */
export const timeText = (d: Date, tz: string | null) => {
  const w = wallOf(d, tz);
  return `${pad(w.h % 12 || 12)}:${pad(w.mi)} ${w.h < 12 ? "am" : "pm"}`;
};

// ---------------------------------------------------------------- the page's changes, undone before each apply

// Its own undo list per page; a class change is undone by toggling the class back (it may come back last in the attribute).
export const { track, restore: restoreStats, setText, setClass, setAttr, swapIn } = undoList({ attrMode: "single", classUndo: "toggle", skipEqualText: true });
export function add(doc: Document, el: Element, where: Element, how: "after" | "append" | "before" = "append") {
  if (how === "after") where.after(el);
  else if (how === "before") where.before(el);
  else where.append(el);
  track(doc, () => el.remove());
}
export function display(doc: Document, el: HTMLElement | null | undefined, show: boolean) {
  if (!el || (el.style.display !== "none") === show) return;
  const was = el.getAttribute("style");
  track(doc, () => (was === null ? el.removeAttribute("style") : el.setAttribute("style", was)));
  if (show) el.style.removeProperty("display");
  else el.style.display = "none";
}
/**
 * A control the generator disabled with the tooltip (data-oi-enable), enabled once its source answers: OF's own control
 * again (no disabled, no tooltip), marked as wired.
 */
export function enable(doc: Document, el: Element) {
  setAttr(doc, el, "disabled", null);
  setAttr(doc, el, "title", null);
  setAttr(doc, el, "data-oi-wired", "");
}
/** A tab row's current tab (OF's m-current, no pointer, out of the tab order) by `key` in `attr`. */
export function currentTab(doc: Document, root: ParentNode, attr: string, key: string) {
  for (const b of root.querySelectorAll<HTMLElement>(`[${attr}]`)) {
    const on = b.getAttribute(attr) === key;
    setClass(doc, b, "m-current", on);
    setClass(doc, b, "m-no-pointer", on);
    setAttr(doc, b, "tabindex", on ? "-1" : "0");
  }
}

/** A pick's tabs (every `data-oi-pick="<name>:…"` of `doc`): the one for `value` is the current one. */
export function pickTabs(doc: Document, name: string, value: string) {
  // A shortcut to another page's pick (data-oi-href: a Statements sidebar row) is no tab.
  for (const b of doc.querySelectorAll<HTMLElement>(`[data-oi-pick^='${name}:']:not([data-oi-href])`)) {
    const on = b.getAttribute("data-oi-pick") === `${name}:${value}`;
    setClass(doc, b, "m-current", on);
    setClass(doc, b, "m-no-pointer", on);
    setAttr(doc, b, "tabindex", on ? "-1" : "0");
    if (b.classList.contains("router-link-active") && !on) setClass(doc, b, "router-link-active", false);
  }
}

/** OF's level mark: the change in % with its arrow (a Summary block prints its sign, the others do not). */
export function level(doc: Document, delta: number, signed: boolean) {
  const icon = delta > 0 ? "icon-increase" : "icon-decrease";
  const span = doc.createElement("span");
  span.className = `b-statistics-level ${delta >= 0 ? "m-level-up" : "m-level-down"}`;
  const v = (signed ? delta : Math.abs(delta)).toLocaleString("en-US", { maximumFractionDigits: 2 });
  span.innerHTML = `<svg data-icon-name="${icon}" aria-hidden="true" class="g-icon"><use href="#${icon}" xlink:href="#${icon}"></use></svg> ${v}% `;
  return span;
}
// ---------------------------------------------------------------- values

/** A number, or a numeric string (OF sends some counts as strings: "43"). */
export const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return null;
};
/** The value at a dotted `path` in `body`. */
export const at = (body: unknown, path: string): unknown => path.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), body);
export const zero = (v: number | null) => v !== null && Math.abs(v) < 0.005;
/** A plain object (not an array, not null). */
export const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
/** OF's count (utils' `c6`): an integer grouped, anything else as sent. */
export const ofCount = (v: unknown) => (typeof v === "number" && Number.isInteger(v) ? v.toLocaleString("en-US") : v == null ? "—" : String(v));
/** OF's money (utils-money): "$1,234.50"; none: "". */
export const money = (v: unknown) => {
  const n = num(v);
  return n === null ? "" : usd(n);
};
export const cell = (el: Element, i: number) => el.querySelectorAll(":scope > td")[i];
export const count = (v: unknown) => {
  const n = num(v);
  return n === null ? " — " : ` ${n.toLocaleString("en-US")} `;
};
/** A date OF sent (ISO), else null. */
export const dateOf = (v: unknown) => (typeof v === "string" ? valid(v) ?? null : null);

// ---------------------------------------------------------------- OF's infinite loading

/** When `el` scrolls into view, read the next page (OF's infinite loading); nothing to read: nothing. */
export function moreAt(doc: Document, el: Element | null | undefined, more: (() => void) | null | undefined) {
  const IO = doc.defaultView?.IntersectionObserver;
  if (!el || !more || !IO) return;
  const io = new IO((entries) => {
    if (!entries.some((e) => e.isIntersecting)) return;
    io.disconnect();
    more();
  }, { rootMargin: "0px 0px 300px 0px" });
  io.observe(el);
  track(doc, () => io.disconnect());
}

/** OF's empty row while the first rows (or the period's) are still being read: "Loading…" instead of a claim. */
export function loadingRow(doc: Document, body: Element | null | undefined) {
  const span = body?.querySelector(":scope > tr .empty-message > span");
  if (span) setText(doc, span, "Loading…");
}
