"use client";


export interface Day {
  y: number;
  m: number;
  d: number;
}

export interface PickerOptions {
  start: Day;
  end: Day;
  today: Day;
  userStart: Day | null;
  onApply: (start: Day, end: Day) => void;
  single?: boolean;
  future?: boolean;
  opener?: Element;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad = (n: number) => String(n).padStart(2, "0");

export const dayNum = (x: Day) => Date.UTC(x.y, x.m - 1, x.d) / 86_400_000;
export const fromNum = (n: number): Day => {
  const d = new Date(n * 86_400_000);
  return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate() };
};
export const isoDay = (x: Day) => `${x.y}-${pad(x.m)}-${pad(x.d)}`;
export const parseDay = (s: string): Day | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  const day = { y: +m[1], m: +m[2], d: +m[3] };
  return isoDay(fromNum(dayNum(day))) === s ? day : null;
};
export const tabDate = (x: Day) => `${MONTHS[x.m - 1].slice(0, 3)} ${x.d}, ${x.y}`;
export const daysSelected = (a: Day, b: Day) => {
  const n = Math.abs(dayNum(b) - dayNum(a)) + 1;
  return `${n} ${n === 1 ? "day" : "days"} selected`;
};

interface State extends PickerOptions {
  fromTab: boolean;
  initial: Day;
  month: Day;
  menu: boolean;
}

const minDay = (s: State) => (s.userStart && dayNum(s.userStart) < dayNum(s.initial) ? s.userStart : s.initial);

const allowed = (s: State, at: Day) => (s.future ? dayNum(at) >= dayNum(s.today) : dayNum(at) >= dayNum(minDay(s)) && dayNum(at) <= dayNum(s.today));

export function pick(s: { start: Day; end: Day; fromTab: boolean; today: Day; min: Day | null }, at: Day): { start: Day; end: Day; fromTab: boolean } | null {
  if ((s.min && dayNum(at) < dayNum(s.min)) || dayNum(at) > dayNum(s.today)) return null;
  const a = s.fromTab ? at : s.start;
  const b = s.fromTab ? s.end : at;
  const swapped = !s.fromTab && dayNum(b) < dayNum(a);
  const [start, end] = dayNum(b) < dayNum(a) ? [b, a] : [a, b];
  return { start, end, fromTab: s.fromTab || swapped ? !s.fromTab : s.fromTab };
}

export function monthWeeks(month: Day): Day[][] {
  const first = dayNum({ ...month, d: 1 });
  const last = dayNum({ y: month.m === 12 ? month.y + 1 : month.y, m: month.m === 12 ? 1 : month.m + 1, d: 1 }) - 1;
  const from = first - new Date(first * 86_400_000).getUTCDay();
  const to = last + (6 - new Date(last * 86_400_000).getUTCDay());
  const weeks: Day[][] = [];
  for (let n = from; n <= to; n += 7) weeks.push(Array.from({ length: 7 }, (_, i) => fromNum(n + i)));
  return weeks;
}

const V = 'data-v-f708a5fa=""';

const when = (x: Day, today: Day, future = false) =>
  dayNum(x) < dayNum(today) ? "v-past" : dayNum(x) === dayNum(today) ? "v-present" : future ? "v-past" : "v-future";

function dayClasses(s: State, x: Day): string {
  const k = dayNum(x);
  if (k < dayNum(s.future ? s.today : minDay(s))) return "vc-disabled";
  if (k === dayNum(s.start) && k === dayNum(s.end)) return "active one-day-range";
  if (k === dayNum(s.start) && s.fromTab) return "active start-range";
  if (k === dayNum(s.end) && !s.fromTab) return "active end-range";
  return "";
}

function events(s: State, x: Day, week: Day[]): string {
  const out: string[] = [];
  const k = dayNum(x);
  const ev = (color: string, from: number, to: number) => {
    const segStart = Math.max(from, dayNum(week[0]));
    const segEnd = Math.min(to, dayNum(week[6]));
    if (k !== segStart || segStart > segEnd) return;
    const cls = ["v-event", k === from ? "v-event-start" : "", segEnd === to ? "v-event-end" : "", color, "white--text"].filter(Boolean).join(" ");
    out.push(
      `<div data-date="${isoDay(x)}" class="${cls}" style="height: 20px; width: ${(segEnd - segStart + 1) * 100 - 5}%; margin-bottom: 1px;"><div class="pl-1"><span class="v-event-summary"></span></div></div>`,
    );
  };
  ev("today", dayNum(s.today), dayNum(s.today));
  ev("range", dayNum(s.start), dayNum(s.end));
  return out.join("");
}

function render(s: State): string {
  const thisMonth = s.month.y === s.today.y && s.month.m === s.today.m;
  const firstMonth = !!s.userStart && s.month.y === s.userStart.y && s.month.m === s.userStart.m;
  const weeks = monthWeeks(s.month);
  const todayDow = new Date(dayNum(s.today) * 86_400_000).getUTCDay();
  const outside = (x: Day) => x.m !== s.month.m || x.y !== s.month.y;
  const head = WEEKDAYS.map((name, i) => {
    const cls = ["v-calendar-weekly__head-weekday", i < todayDow ? "v-past" : i === todayDow ? "v-present" : "v-future", outside(weeks[0][i]) ? "v-outside" : ""].filter(Boolean).join(" ");
    return `<div role="columnheader" class="${cls}">${name}</div>`;
  }).join("");
  const rows = weeks
    .map((week) => {
      const cells = week
        .map((x) => {
          const cls = ["v-calendar-weekly__day", when(x, s.today, s.future), outside(x) ? "v-outside" : ""].filter(Boolean).join(" ");
          return `<div role="cell" class="${cls}" data-oi-day="${isoDay(x)}"><div class="v-calendar-weekly__day-label"><span class="${dayClasses(s, x)}">${x.d}</span></div>${events(s, x, week)}</div>`;
        })
        .join("");
      return `<div role="row" class="v-calendar-weekly__week">${cells}</div>`;
    })
    .join("");
  const arrow = (dir: "left" | "right", disabled: boolean) =>
    `<div ${V} class="b-streaks-swither__btn d-flex justify-content-center align-items-center"><button ${V} type="button" data-oi-month="${dir === "left" ? "prev" : "next"}" class="g-btn m-with-round-hover m-size-sm-hover m-icon m-icon-only m-xs-size ${disabled ? "m-gray" : "m-default-color"}"${disabled ? ' disabled="disabled"' : ""}><svg data-icon-name="icon-arrow-${dir}" aria-hidden="true" class="g-icon"><use href="#icon-arrow-${dir}" xlink:href="#icon-arrow-${dir}"></use></svg></button></div>`;
  return (
    `<div><div class="vdatetime-overlay" data-oi-picker-close=""></div><div class="vdatetime-popup m-vdatetime-tabs">` +
    (s.single
      ? `<div class="vdatetime-popup__header"><div class="vdatetime-popup__title"> ${tabDate(s.start)} </div></div>`
      : `<div class="vdatetime-popup__header"><div class="vdatetime-popup__title m-range-icon"> ${daysSelected(s.start, s.end)} </div></div>` +
        `<div class="vdatetime-popup__tabs m-hyphen"><div class="vdatetime-popup__tab date${s.fromTab ? " active" : ""}" data-oi-tab="from"> ${tabDate(s.start)} </div><div class="vdatetime-popup__tab time${s.fromTab ? "" : " active"}" data-oi-tab="to"> ${tabDate(s.end)} </div></div>`) +
    `<div class="vdatetime-popup__body"><div ${V} class="b-datepicker-wrapper"><div ${V} class="b-streaks-swither d-flex justify-content-between align-items-center">` +
    arrow("left", s.future ? thisMonth : firstMonth) +
    `<div data-v-55f3fe86="" tabindex="-1" class="b-dropdown-wrapper m-dropdown-v2" ${V}><button data-v-55f3fe86="" type="button" role="button" aria-haspopup="true" aria-expanded="${s.menu}" data-oi-months="" class="btn dropdown-toggle m-with-hover-highlight"><span class="b-streaks-swither__time"> ${MONTHS[s.month.m - 1]} ${s.month.y} </span></button></div>` +
    arrow("right", !s.future && thisMonth) +
    `</div><div class="v-calendar-monthly v-calendar-weekly v-calendar m-streaks-calendar theme--light v-calendar-events" role="grid" ${V}><div role="row" class="v-calendar-weekly__head">${head}</div>${rows}</div></div></div>` +
    `<div class="vdatetime-popup__actions"><div class="vdatetime-popup__actions__button vdatetime-popup__actions__button--cancel"><button type="button" data-oi-picker-close="" class="g-btn m-flat m-btn-gaps custom-datepicker-button-cancel"> Cancel </button></div>` +
    `<div class="vdatetime-popup__actions__button vdatetime-popup__actions__button--confirm"><button type="button" data-oi-picker-apply="" class="g-btn m-flat m-btn-gaps"> Apply </button></div></div>` +
    `</div></div>`
  );
}

export function pickerMonths(today: Day, userStart: Day | null, future = false): Day[] {
  const back = future ? 11 : userStart ? (today.y - userStart.y) * 12 + (today.m - userStart.m) : today.m - 1;
  return Array.from({ length: Math.max(0, back) + 1 }, (_, i) => {
    const n = today.y * 12 + (today.m - 1) + (future ? i : -i);
    return { y: Math.floor(n / 12), m: (n % 12) + 1, d: 1 };
  });
}

function fitRanges(root: HTMLElement) {
  const cells = root.querySelectorAll<HTMLElement>(".v-calendar-weekly__day");
  if (cells.length < 2) return;
  const a = cells[0].getBoundingClientRect();
  const b = cells[1].getBoundingClientRect();
  if (!a.width) return;
  const step = b.left - a.left;
  for (const ev of root.querySelectorAll<HTMLElement>(".v-event.range")) {
    const days = Math.round((parseFloat(ev.style.width) + 5) / 100);
    if (days > 0) ev.style.width = `${(days - 1) * step + a.width}px`;
  }
}

const PICKER = "data-oi-picker";
const MENU = "data-oi-picker-months";

const openers = new WeakMap<Document, Element>();

export function closeDatepicker(doc: Document): void {
  doc.querySelector(`[${MENU}]`)?.remove();
  doc.querySelector(`[${PICKER}]`)?.remove();
  openers.get(doc)?.removeAttribute("aria-expanded");
  openers.delete(doc);
}

function linkPickerCss(doc: Document): HTMLLinkElement | null {
  if (doc.querySelector("link[href$='/45647.css']")) return null;
  const app = doc.querySelector<HTMLLinkElement>("link[href$='/app.css']");
  if (!app) return null;
  const link = doc.createElement("link");
  link.rel = "stylesheet";
  link.href = app.getAttribute("href")!.replace(/app\.css$/, "45647.css");
  doc.head.append(link);
  return link;
}

export function openDatepicker(doc: Document, opts: PickerOptions): HTMLElement {
  closeDatepicker(doc);
  if (opts.opener) {
    opts.opener.setAttribute("aria-expanded", "true");
    openers.set(doc, opts.opener);
  }
  const css = linkPickerCss(doc);
  const s: State = { ...opts, fromTab: true, initial: opts.start, month: { y: opts.start.y, m: opts.start.m, d: 1 }, menu: false };
  const root = doc.createElement("div");
  root.setAttribute(PICKER, "");
  root.className = "vdatetime custom-datepicker";
  root.style.cssText = "position:relative;z-index:1060";
  const draw = () => {
    root.innerHTML = render(s);
    fitRanges(root);
    doc.querySelector(`[${MENU}]`)?.remove();
    if (s.menu) openMonths();
  };
  const openMonths = () => {
    const button = root.querySelector<HTMLElement>("[data-oi-months]");
    if (!button) return;
    const r = button.getBoundingClientRect();
    const menu = doc.createElement("div");
    menu.setAttribute(MENU, "");
    menu.className = "v-menu__content theme--light menuable__content__active m-dropdown-list m-dropdown-over-modal b-datepicker-months-list";
    menu.style.cssText = `min-width:216px;max-width:216px;max-height:268px;overflow-y:auto;top:${r.bottom + 5}px;left:${r.left}px;transform-origin:left top;z-index:1070;position:fixed;`;
    const list = doc.createElement("div");
    list.className = "v-list m-dropdown-v-list v-sheet theme--light";
    for (const mo of pickerMonths(s.today, s.userStart, s.future)) {
      const item = doc.createElement("button");
      item.type = "button";
      item.className = `v-list-item v-list-item--link theme--light${mo.y === s.month.y && mo.m === s.month.m ? " m-active" : ""}`;
      item.setAttribute("data-oi-month-pick", isoDay(mo));
      item.textContent = ` ${MONTHS[mo.m - 1]} ${mo.y} `;
      list.append(item);
    }
    menu.append(list);
    doc.body.append(menu);
  };
  const close = () => {
    closeDatepicker(doc);
    win?.removeEventListener("keydown", onKey, true);
    doc.removeEventListener("click", onMenuClick);
  };
  const win = doc.defaultView;
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key !== "Escape") return;
    ev.stopPropagation();
    if (s.menu) {
      s.menu = false;
      draw();
    } else close();
  };
  const onMenuClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    const item = t?.closest?.("[data-oi-month-pick]");
    if (item) {
      const mo = parseDay(item.getAttribute("data-oi-month-pick")!);
      if (mo) s.month = mo;
      s.menu = false;
      draw();
    } else if (s.menu && !t?.closest?.(`[${MENU}], [data-oi-months]`)) {
      s.menu = false;
      draw();
    }
  };
  root.addEventListener("click", (ev) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (t.closest("[data-oi-picker-close]")) return close();
    if (t.closest("[data-oi-picker-apply]")) {
      const { start, end } = s;
      close();
      return opts.onApply(start, end);
    }
    const tab = t.closest("[data-oi-tab]");
    if (tab) {
      s.fromTab = tab.getAttribute("data-oi-tab") === "from";
      const at = s.fromTab ? s.start : s.end;
      s.month = { y: at.y, m: at.m, d: 1 };
      return draw();
    }
    const arrow = t.closest<HTMLButtonElement>("[data-oi-month]");
    if (arrow) {
      if (arrow.disabled) return;
      const n = s.month.y * 12 + (s.month.m - 1) + (arrow.getAttribute("data-oi-month") === "next" ? 1 : -1);
      s.month = { y: Math.floor(n / 12), m: (n % 12) + 1, d: 1 };
      return draw();
    }
    if (t.closest("[data-oi-months]")) {
      s.menu = !s.menu;
      return draw();
    }
    const cell = t.closest("[data-oi-day]");
    const at = cell && parseDay(cell.getAttribute("data-oi-day")!);
    if (!at) return;
    if (s.single) {
      if (!allowed(s, at)) return;
      s.start = s.end = at;
      return draw();
    }
    const next = pick({ ...s, min: minDay(s) }, at);
    if (!next) return;
    s.start = next.start;
    s.end = next.end;
    if (next.fromTab !== s.fromTab) {
      s.fromTab = next.fromTab;
      const shown = s.fromTab ? s.start : s.end;
      s.month = { y: shown.y, m: shown.m, d: 1 };
    }
    draw();
  });
  win?.addEventListener("keydown", onKey, true);
  doc.addEventListener("click", onMenuClick);
  doc.body.append(root);
  draw();
  css?.addEventListener("load", () => root.isConnected && draw());
  return root;
}
