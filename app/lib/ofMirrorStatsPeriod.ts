"use client";

/**
 * Statistics' period (OF's period menu, the button the generator marks data-oi-period): Last 24 hours, Last 7/30/90/180/
 * 365 days, this and last year, All time and the last six months, with OF's rules (build 202610091632: PeriodDatepicker,
 * statistics-fans' period table): the start is the day's first instant (24 hours: now less a day), the end now, both
 * clamped to the Creator's start (`/users/me/start-date-model`); `startDate` is sent as that wall time, `endDate` as UTC
 * when it is today. Custom opens OF's date picker (ofMirrorDatepicker): its first day's start to its last day's end,
 * titled "Custom", its dates with their times ("12:00 am, Sep 01 - 11:59 pm, Sep 15, 2026"). Dates and the "(local time
 * UTC +02:00)" note follow the owner's time zone (`preferences.tz`, the top bar's UTC label), else the browser's. The
 * period is kept while moving between the tabs, as OF keeps it.
 */

import { useSyncExternalStore } from "react";
import { isoDay, openDatepicker, parseDay, type Day } from "@/lib/ofMirrorDatepicker";
import { MONTHS, SHORT, display, pad, setText, wallOf, type Wall } from "@/lib/ofMirrorStatsDom";

// ---------------------------------------------------------------- the period

/** OF's periods: Last 24 hours, Last <n> days, a year, `m<n>`: the month n months back, All time, `c<from>_<to>`: Custom. */
export type PeriodKey = "24h" | `d${number}` | `y${number}` | `m${number}` | "all" | `c${string}`;
export const DEFAULT_PERIOD: PeriodKey = "d30";
const DAYS = [7, 30, 90, 180, 365];

export interface Period {
  key: PeriodKey;
  now: Date;
  /** The owner's time zone (IANA), else null: the browser's. */
  tz: string | null;
  start: Date;
  end: Date;
  /** OF's `startDate` / `endDate` ("YYYY-MM-DD HH:mm:ss"). */
  startApi: string;
  endApi: string;
  /** The menu button's title ("Last 30 days") and its dates ("Sep 17, 2026", "Oct 17, 2026"). */
  title: string;
  from: string;
  to: string;
}

/** The instant whose wall clock in `tz` is `w` (fields may overflow: Date.UTC normalises them). */
function instant(w: Wall, tz: string | null): Date {
  const want = Date.UTC(w.y, w.m - 1, w.d, w.h, w.mi, w.s);
  let at = want;
  for (let i = 0; i < 2; i++) {
    const got = wallOf(new Date(at), tz);
    at += want - Date.UTC(got.y, got.m - 1, got.d, got.h, got.mi, got.s);
  }
  return new Date(at);
}

const apiOf = (w: Wall) => `${w.y}-${pad(w.m)}-${pad(w.d)} ${pad(w.h)}:${pad(w.mi)}:${pad(w.s)}`;
/** OF's "MMM DD, YYYY". */
const dayLabel = (w: Wall) => `${SHORT[w.m - 1]} ${pad(w.d)}, ${w.y}`;
/** OF's "h:mm a, MMM DD" (and ", YYYY"). */
const timeLabel = (w: Wall, year: boolean) => `${w.h % 12 || 12}:${pad(w.mi)} ${w.h < 12 ? "am" : "pm"}, ${SHORT[w.m - 1]} ${pad(w.d)}${year ? `, ${w.y}` : ""}`;
const sameDay = (a: Wall, b: Wall) => a.y === b.y && a.m === b.m && a.d === b.d;

/** "2021-09-28 16:24:48" (`/users/me/start-date-model`, the owner's wall time as OF reads it) as an instant. */
export function startOf(body: unknown, tz: string | null): Date | null {
  const s = (body as { startDate?: unknown } | null)?.startDate;
  const m = typeof s === "string" ? /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(s) : null;
  return m ? instant({ y: +m[1], m: +m[2], d: +m[3], h: +m[4], mi: +m[5], s: +m[6] }, tz) : null;
}

/** A Custom key's first and last days (not a Custom key, or not two real days in order: null). */
export function customDays(key: string): [Day, Day] | null {
  const m = /^c(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/.exec(key);
  const a = m && parseDay(m[1]);
  const b = m && parseDay(m[2]);
  return a && b && isoDay(a) <= isoDay(b) ? [a, b] : null;
}
/** The Custom key for `from` to `to`. */
export const customKey = (from: Day, to: Day): PeriodKey => `c${isoDay(from)}_${isoDay(to)}`;

export function isPeriodKey(v: string): v is PeriodKey {
  return v === "24h" || v === "all" || /^(d(7|30|90|180|365)|y\d{4}|m[0-5])$/.test(v) || !!customDays(v);
}

/** The period `key` at `now` in `tz`, clamped to the Creator's start `userStart` (OF's rules: see the header). */
export function periodOf(key: PeriodKey, now: Date, tz: string | null, userStart: Date | null): Period {
  const w = wallOf(now, tz);
  const day = (y: number, m: number, d: number, end = false) => instant({ y, m, d, h: end ? 23 : 0, mi: end ? 59 : 0, s: end ? 59 : 0 }, tz);
  let start: Date;
  let end: Date = now;
  let title: string;
  if (key === "24h") {
    start = new Date(now.getTime() - 86_400_000);
    title = "Last 24 hours";
  } else if (key === "all") {
    start = userStart ?? now;
    title = "All time";
  } else if (key[0] === "d") {
    const n = Number(key.slice(1));
    start = day(w.y, w.m, w.d - n);
    title = `Last ${n} days`;
  } else if (key[0] === "c") {
    const [a, b] = customDays(key) ?? [w, w];
    start = day(a.y, a.m, a.d);
    end = day(b.y, b.m, b.d, true);
    title = "Custom";
  } else if (key[0] === "y") {
    const y = Number(key.slice(1));
    start = day(y, 1, 1);
    end = y === w.y ? now : day(y, 12, 31, true);
    title = String(y);
  } else {
    const back = Number(key.slice(1));
    const first = wallOf(day(w.y, w.m - back, 1), tz);
    start = day(first.y, first.m, 1);
    end = back === 0 ? now : instant({ y: first.y, m: first.m + 1, d: 1, h: 0, mi: 0, s: -1 }, tz);
    title = MONTHS[first.m - 1];
  }
  if (userStart && start < userStart) start = userStart;
  if (end > now) end = now;
  const sw = wallOf(start, key === "24h" ? "UTC" : tz);
  const ew = wallOf(end, tz);
  const timed = key === "24h" || key[0] === "c";
  const fw = wallOf(start, tz);
  return {
    key, now, tz, start, end,
    startApi: apiOf(sw),
    endApi: sameDay(ew, w) ? apiOf(wallOf(end, "UTC")) : apiOf(ew),
    title,
    // OF's Custom start carries its year when the end is in another year; Last 24 hours' never does.
    from: timed ? timeLabel(fw, key[0] === "c" && fw.y !== ew.y) : dayLabel(fw),
    to: timed ? timeLabel(ew, true) : dayLabel(ew),
  };
}

/** OF's menu (PeriodDatepicker's datesList): its items in order; null: a divider; key null: Custom (it opens the date picker). */
export function periodMenu(now: Date, tz: string | null, userStart: Date | null): ({ title: string; key: PeriodKey | null } | null)[] {
  const w = wallOf(now, tz);
  const age = userStart ? Math.floor((now.getTime() - userStart.getTime()) / 86_400_000) : Infinity;
  const startY = userStart ? wallOf(userStart, tz) : null;
  const years = [w.y, ...(startY && w.y > startY.y ? [w.y - 1] : [])];
  // OF's months: this one and back, at most six, none before the Creator's start.
  const since = startY ? (w.y - startY.y) * 12 + (w.m - startY.m) : 5;
  const months = Array.from({ length: Math.min(since + 1, 6) }, (_, i) => i);
  return [
    { title: "Custom", key: null },
    null,
    { title: "Last 24 hours", key: "24h" },
    ...DAYS.filter((n, i) => i === 0 || age > DAYS[i - 1]).map((n) => ({ title: `Last ${n} days`, key: `d${n}` as PeriodKey })),
    null,
    ...years.map((y) => ({ title: String(y), key: `y${y}` as PeriodKey })),
    { title: "All time", key: "all" as PeriodKey },
    null,
    ...months.map((i) => ({ title: MONTHS[(w.m - 1 - i + 12) % 12], key: `m${i}` as PeriodKey })),
  ];
}

// The period picked, kept across the Statistics tabs (each a fresh frame) until a reload, as OF keeps it.
let picked: PeriodKey = DEFAULT_PERIOD;
/** Everyone the period or a pick tells of a change (ofMirrorStatsSources' picks share it). */
export const listeners = new Set<() => void>();
export function setPeriod(key: PeriodKey): void {
  if (key === picked) return;
  picked = key;
  for (const l of listeners) l();
}
export const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export const usePeriodKey = () => useSyncExternalStore(subscribe, () => picked, () => DEFAULT_PERIOD);
/** The period picked (outside React). */
export const currentPeriodKey = () => picked;

/** The menu button's title and every date range (data-oi-range="tz": with OF's local time note). */
export function applyRange(doc: Document, p: Period) {
  for (const el of doc.querySelectorAll("[data-oi-period-title]")) setText(doc, el, ` ${p.title} `);
  const range = `${p.from} - ${p.to}`;
  for (const el of doc.querySelectorAll("[data-oi-range]")) setText(doc, el, el.getAttribute("data-oi-range") === "tz" ? ` ${range} (local time ${utcOffset(p.now, p.tz)}) ` : ` ${range} `);
  // Overview › Earnings: OF draws no period row for a month or All time (its month rows say it).
  display(doc, doc.querySelector<HTMLElement>("[data-name='period']"), !(p.key === "all" || p.key[0] === "m"));
}

/** "UTC +02:00": OF's local time note, for `tz` (the browser's when null). */
export function utcOffset(now: Date, tz: string | null) {
  const w = wallOf(now, tz);
  const m = Math.round((Date.UTC(w.y, w.m - 1, w.d, w.h, w.mi, w.s) - Math.floor(now.getTime() / 1000) * 1000) / 60_000);
  return `UTC ${m < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(m) / 60))}:${pad(Math.abs(m) % 60)}`;
}

// ---------------------------------------------------------------- the menu

const MENU = "data-oi-period-menu";
/** OF's period menu (its v-menu markup, from the captured menu) under the button. */
function openMenu(doc: Document, button: HTMLElement, p: Period, userStart: Date | null) {
  closeMenu(doc);
  const menu = doc.createElement("div");
  menu.setAttribute(MENU, "");
  menu.className = "v-menu__content theme--light menuable__content__active m-dropdown-list m-show-dividers pt-0 pb-0";
  const r = button.getBoundingClientRect();
  const win = doc.defaultView;
  menu.style.cssText = `min-width:220px;max-width:256px;top:${r.bottom + (win?.scrollY ?? 0)}px;left:${r.left + (win?.scrollX ?? 0)}px;transform-origin:left top;z-index:8;position:absolute;`;
  const list = doc.createElement("div");
  list.className = "v-list m-dropdown-v-list v-sheet theme--light shown";
  list.style.cssText = "max-height:500px;overflow-y:auto;";
  periodMenu(p.now, p.tz, userStart).forEach((item, i) => {
    if (!item) {
      const hr = doc.createElement("hr");
      hr.setAttribute("role", "separator");
      hr.setAttribute("aria-orientation", "horizontal");
      hr.className = "m-divider-item v-divider theme--light";
      list.append(hr);
      return;
    }
    const el = doc.createElement("div");
    el.setAttribute("role", "menuitem");
    el.tabIndex = 0;
    el.className = `m-with-rectangle-hover m-tb-sm v-list-item v-list-item--link theme--light${i === 0 ? " m-sticky-item m-first" : ""}`;
    el.textContent = ` ${item.title} `;
    if (!item.key) {
      el.setAttribute("data-oi-period-custom", ""); // OF's date picker
    } else {
      el.setAttribute("data-oi-period-key", item.key); // OF marks no item as the current one
    }
    list.append(el);
  });
  menu.append(list);
  doc.body.append(menu);
  button.setAttribute("aria-expanded", "true");
}
function closeMenu(doc: Document) {
  doc.querySelector(`[${MENU}]`)?.remove();
  doc.querySelector("[data-oi-period]")?.setAttribute("aria-expanded", "false");
}
/** Each page's period and Creator start, as its last apply saw them (the menu reads them when it opens). */
const shown = new WeakMap<Document, { p: Period; userStart: Date | null }>();
/**
 * The period button opens the menu; an item picks its period, Custom opens OF's date picker on the period shown (its
 * Apply picks those days); a click elsewhere or Escape closes the menu.
 */
export function bindMenu(doc: Document, p: Period, userStart: Date | null) {
  const bound = shown.has(doc);
  shown.set(doc, { p, userStart });
  if (bound) return;
  const current = () => shown.get(doc)!;
  doc.addEventListener("click", (ev) => {
    const t = ev.target as Element | null;
    const button = t?.closest?.<HTMLElement>("[data-oi-period]");
    if (button) {
      ev.preventDefault();
      if (doc.querySelector(`[${MENU}]`)) closeMenu(doc);
      else openMenu(doc, button, current().p, current().userStart);
      return;
    }
    if (t?.closest?.("[data-oi-period-custom]")) {
      closeMenu(doc);
      const { p, userStart } = current();
      const toDay = (at: Date): Day => {
        const w = wallOf(at, p.tz);
        return { y: w.y, m: w.m, d: w.d };
      };
      openDatepicker(doc, {
        start: toDay(p.start),
        end: toDay(p.end),
        today: toDay(p.now),
        userStart: userStart ? toDay(userStart) : null,
        onApply: (from, to) => setPeriod(customKey(from, to)),
      });
      return;
    }
    const item = t?.closest?.("[data-oi-period-key]");
    if (item) {
      const key = item.getAttribute("data-oi-period-key")!;
      closeMenu(doc);
      if (isPeriodKey(key)) setPeriod(key);
      return;
    }
    if (!t?.closest?.(`[${MENU}]`)) closeMenu(doc);
  });
  doc.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeMenu(doc);
  });
}

