"use client";


import { useEffect, useState, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { make } from "@/lib/ofMirrorDom";
import { undoList } from "@/lib/ofMirrorUndo";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { clearChart, drawLines, type LinesSpec } from "@/lib/ofMirrorChart";
import { basePage } from "@/lib/ofMirrorRow";
import { note } from "@/lib/ofMirrorWrites";
import { parseSendFailure } from "@/lib/sendFailure";
import { useAppliedSettings } from "@/lib/appliedSettings";
import { openDatepicker, tabDate, type Day } from "@/lib/ofMirrorDatepicker";
import { mirrorQuery } from "@/lib/ofMirrorDataQueries";
import { pickerDays, startOf, statementsRange } from "@/lib/ofMirrorStatsPeriod";

export type MoneyPart = "balances" | "earningStats" | "referralBalance";

export const MONEY_ROUTES: Record<MoneyPart, string> = {
  balances: "/api/of/v2/payouts/balances",
  earningStats: "/api/of/v2/payouts/stats",
  referralBalance: "/api/of/v2/payments/referrals/balance",
};

export function moneyParts(page: string): MoneyPart[] {
  const p = basePage(page);
  const parts: MoneyPart[] = [];
  if (/^statements\/(?!support$)/.test(p) || /^statistics\/(overview|statements)\//.test(p)) parts.push("balances");
  if (p === "statements/stats/earnings") parts.push("earningStats");
  if (p === "statements/referrals" || p === "statistics/statements/referrals/earnings") parts.push("referralBalance");
  return parts;
}

export interface Balances {
  payoutAvailable?: number | null;
  payoutPending?: number | null;
  currency?: string | null;
  minPayoutSumm?: number | null;
  maxPayoutSumm?: number | null;
  availableAmount?: number | null;
  withdrawalPeriod?: string | null;
  withdrawalPeriodOptions?: { code?: string; name?: string }[] | null;
}

export interface PayoutUser {
  canReceiveManualPayout?: boolean | null;
  hasPayoutsIssue?: unknown;
}

export interface MoneyActions {
  withdraw: (amount: number) => Promise<unknown>;
  setPeriod: (code: string) => Promise<unknown>;
}

type Sums = { total_gross?: number | null; total_net?: number | null };
type EarningItem = { gross?: number | null; net?: number | null; time?: number | null };
export interface EarningStats {
  total?: Record<string, Sums | undefined> | null;
  months?: Record<string, (Sums & Record<string, unknown>) | undefined> | null;
}

export interface MoneyData {
  meId?: string | number | null;
  balances?: Balances;
  earningStats?: EarningStats;
  referralEarnings?: number | null;
  payoutUser?: PayoutUser;
  periodSaving?: boolean;
  actions?: MoneyActions;
  range?: EarningRange | null;
}

export interface EarningRange {
  tz: string | null;
  userStart: Date | null;
  picked?: { from: Day; to: Day; stats?: EarningStats } | null;
  pick: (from: Day, to: Day) => void;
  clear: () => void;
}

export function earningStatsRoute(p: { startDate: string; endDate: string }): string {
  return `${MONEY_ROUTES.earningStats}?${new URLSearchParams(p)}`;
}

export function moneyOf(part: MoneyPart, body: unknown): MoneyData {
  const o = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
  if (!o) return {};
  if (part === "balances") return { balances: o as Balances };
  if (part === "earningStats") {
    const l = o.list && typeof o.list === "object" ? o.list : o;
    return { earningStats: l as EarningStats };
  }
  return { referralEarnings: o.referralEarnings as number | null };
}

const { track, restore: restoreMoney, setText, setClass, setAttr, swapIn } = undoList({ attrMode: "all-in-order", classUndo: "snapshot", skipEqualText: true });

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
export const usd = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD" });

export const DASH = " — ";

function setMoney(doc: Document, el: Element | null | undefined, v: unknown) {
  if (!el) return;
  const n = num(v);
  setText(doc, el, n === null ? DASH : ` ${usd(n)} `);
  setClass(doc, el, "m-zero-value", n === 0);
}

const MIN_AMOUNT = /\$\d[\d,]*(?:\.\d+)?/;
const minAmount = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;


export const PAYOUT_REQUESTS = "/api/of/v2/payouts/requests";
export const CHECK_RECEIVE = "/api/of/v2/payouts/check-receive";
const START_DATE = "/api/of/v2/users/me/start-date-model";

export const TEXTS = {
  payout_min_amount_message: "Minimum withdrawal amount is {AMOUNT}",
  payout_next_date_success_message: "Next payout scheduled on: {DATE}",
  payout_next_date_warning_message: "Once your balance is over {BALANCE} next payout will be scheduled on: {DATE}",
  payout_request_manual: "Manual payouts",
  withdrawal_amount_placeholder: "Withdrawal amount",
  max_button: "Max",
  button_label_cancel: "Cancel",
  request_withdrawal_button_label: "Request withdrawal",
  min_price_label_without_currency: "Minimum {MIN}",
  max_price_label_without_currency: "Maximum {MAX}",
  payout_request_state_pending_description: "Payout request is being processed",
  payout_request_state_approved_description: "Payout has been processed",
  dialog_close_button: "Close",
  debug_alert_message: "Something went wrong. Please try again later.",
} as const;
const fill = (text: string, vars: Record<string, string>) => text.replace(/\{(\w+)\}/g, (all, k: string) => vars[k] ?? all);

// Raw JS comparison on purpose, as OF's: absent compares false, null as 0.
const lt = (a: unknown, b: unknown) => (a as number) < (b as number);
const hasBalances = (b: Balances | null | undefined): b is Balances => !!b && typeof b === "object" && Object.keys(b).length > 0;

export function payoutsDisabled(b: Balances | null | undefined, u: PayoutUser | null | undefined): boolean {
  return !(hasBalances(b) && u) || lt(b.payoutAvailable, b.minPayoutSumm) || !u.canReceiveManualPayout;
}

export function withdrawDisabled(b: Balances | null | undefined, u: PayoutUser | null | undefined): boolean {
  return !(hasBalances(b) && u) || lt(b.payoutAvailable, b.minPayoutSumm) || (!u.hasPayoutsIssue && payoutsDisabled(b, u));
}

export const isManualWithdrawal = (b: Balances | null | undefined) => b?.withdrawalPeriod === "manual";

export const maxPayout = (b: Balances) => Math.floor((lt(b.maxPayoutSumm, b.payoutAvailable) ? b.maxPayoutSumm : b.payoutAvailable) as number);

const SYMBOLS: Record<string, string> = { usd: "$", eur: "€", gbp: "£" };
const symbolOf = (currency: unknown) => SYMBOLS[typeof currency === "string" ? currency.toLowerCase() : ""] ?? "$";
const currencyFormat = (v: unknown, currency: unknown) => `${symbolOf(currency)}${v}`;
const utilsMoney = (v: number, currency: unknown, places: number) =>
  `${symbolOf(currency)}${v.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places })}`;

export function payoutDate(period: string | null | undefined, now: Date): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (period === "daily") d.setDate(d.getDate() + 2);
  else if (period === "monthly") d.setMonth(d.getMonth() + 1, 1);
  else if (period === "weekly") {
    d.setDate(d.getDate() + 7);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  } else return "";
  return longDay(d);
}

export function minSumMessage(b: Balances, now: Date): string {
  const amount = currencyFormat(b.minPayoutSumm, b.currency);
  if (isManualWithdrawal(b)) return fill(TEXTS.payout_min_amount_message, { AMOUNT: amount });
  const date = payoutDate(b.withdrawalPeriod, now);
  return (b.availableAmount as number) >= (b.minPayoutSumm as number)
    ? fill(TEXTS.payout_next_date_success_message, { DATE: date })
    : fill(TEXTS.payout_next_date_warning_message, { BALANCE: amount, DATE: date });
}

export const amountHint = (min: unknown, currency: unknown) =>
  fill(TEXTS.min_price_label_without_currency, { MIN: `${symbolOf(currency)}${min} ${String(currency || "usd").toUpperCase()}` });

export function amountError(value: string | number, min: unknown, max: unknown, currency: unknown): string {
  if (!value) return "";
  const cur = String(currency || "usd").toUpperCase();
  if (lt(value, min)) return fill(TEXTS.min_price_label_without_currency, { MIN: `${symbolOf(currency)}${min} ${cur}` });
  if (lt(max, value)) return fill(TEXTS.max_price_label_without_currency, { MAX: `${symbolOf(currency)}${max} ${cur}` });
  return "";
}

export const submitDisabled = (value: string | number, min: unknown, max: unknown) => lt(value, min) || lt(max, value);

const escapeHtml = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

export function resultDescription(body: unknown): string {
  const list = (body as { list?: unknown } | null)?.list;
  if (!Array.isArray(list) || !list.length) return "";
  return list
    .map((e: { state?: unknown; rejectReason?: unknown } | null) => {
      switch (e?.state) {
        case "new":
        case "pending":
          return TEXTS.payout_request_state_pending_description;
        case "rejected":
          return escapeHtml(e.rejectReason);
        case "approved":
          return TEXTS.payout_request_state_approved_description;
        default:
          return "";
      }
    })
    .join("<br/>");
}

export function withdrawError(err: unknown): string {
  return parseSendFailure((err as { body?: unknown } | null)?.body).reason || TEXTS.debug_alert_message;
}

const WITHDRAW = ".balance-block .g-btn__wrapper > button[data-oi-wired], .balance-block .g-btn__row > button[data-oi-wired]";

function applyBalances(doc: Document, data: MoneyData, now: Date) {
  const b = data.balances!;
  for (const el of doc.querySelectorAll(".b-statements__current-balance__value > span, .b-statements-balances__col.m-current .b-statements-balances__sum")) setMoney(doc, el, b.payoutAvailable);
  for (const el of doc.querySelectorAll(".b-statements__pending-balance__value > span, .b-statements-balances__col:not(.m-current) .b-statements-balances__sum")) setMoney(doc, el, b.payoutPending);
  const period = (b.withdrawalPeriodOptions ?? []).find((o) => o?.code === b.withdrawalPeriod)?.name;
  if (period) for (const el of doc.querySelectorAll(".balance-block .v-select__selection, .balance-block .b-holder-options__title")) setText(doc, el, el.matches(".v-select__selection") ? period : ` ${period} `);
  periodOptions(doc, b);
  const min = num(b.minPayoutSumm);
  if (min !== null) {
    const notes = ".balance-block .b-holder-options .g-sm-text, .g-box__header__subtext, .b-referrals-state .g-sm-text";
    for (const el of doc.querySelectorAll(notes)) swapIn(doc, el, MIN_AMOUNT, minAmount(min));
  }
  if (!hasBalances(b)) return;
  for (const el of doc.querySelectorAll(".b-statements__min-payout-summ")) setText(doc, el, ` ${minSumMessage(b, now)} `);
  const open = !!(b.withdrawalPeriodOptions ?? []).some((o) => o?.name) && !data.periodSaving;
  for (const slot of doc.querySelectorAll(".balance-block .v-select .v-input__slot[data-oi-wired]")) {
    setClass(doc, slot.closest(".v-input")!, "v-input--is-disabled", !open);
    setAttr(doc, slot, "role", open ? "button" : null);
    setAttr(doc, slot, "aria-haspopup", open ? "listbox" : null);
    setAttr(doc, slot, "aria-expanded", open ? "false" : null);
    setAttr(doc, slot.querySelector("input[at-attr='dropdown']"), "disabled", open ? null : "disabled");
  }
  for (const btn of doc.querySelectorAll(WITHDRAW)) {
    const wrap = btn.parentElement!;
    setAttr(doc, wrap, "style", isManualWithdrawal(b) ? wrap.getAttribute("style") : "display:none");
    setAttr(doc, btn, "disabled", withdrawDisabled(b, data.payoutUser) ? "disabled" : null);
  }
}

function periodOptions(doc: Document, b: Balances) {
  const options = (b.withdrawalPeriodOptions ?? []).filter((o) => o?.name);
  if (!options.length) return;
  for (const list of doc.querySelectorAll(".balance-block .v-select-list")) {
    const items = [...list.querySelectorAll<HTMLElement>(":scope > .v-list-item")];
    if (!items.length) continue;
    while (items.length < options.length) {
      const copy = items.at(-1)!.cloneNode(true) as HTMLElement;
      list.appendChild(copy);
      track(doc, () => copy.remove());
      items.push(copy);
    }
    items.forEach((item, i) => {
      const o = options[i];
      if (!o) {
        const was = item.getAttribute("style");
        track(doc, () => (was === null ? item.removeAttribute("style") : item.setAttribute("style", was)));
        item.style.display = "none";
        return;
      }
      const on = o.code === b.withdrawalPeriod;
      setText(doc, item.querySelector(".v-list-item__title"), ` ${o.name} `);
      setClass(doc, item, "v-list-item--active", on);
      setClass(doc, item, "primary--text", on);
      const was = item.getAttribute("aria-selected");
      if (was !== String(on)) {
        track(doc, () => (was === null ? item.removeAttribute("aria-selected") : item.setAttribute("aria-selected", was)));
        item.setAttribute("aria-selected", String(on));
      }
    });
  }
}

const CATEGORIES: [string, string][] = [
  ["m-subscriptions", "subscribes"],
  ["m-tips", "tips"],
  ["m-posts", "post"],
  ["m-messages", "chat_messages"],
  ["m-referrals", "ref"],
  ["m-calls", "stream"],
  ["m-private-calls", "call"],
];
const longDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const monthTitle = (d: Date) => ` ${d.toLocaleDateString("en-US", { month: "long" })}, ${d.getFullYear()} `;

function setSums(doc: Document, row: Element, s: Sums | undefined) {
  const vals = [...row.querySelectorAll(":scope > .b-stats-row__val")];
  if (vals.length > 1) setMoney(doc, vals[0], s?.total_gross ?? 0);
  setMoney(doc, vals.at(-1), s?.total_net ?? 0);
}

const LINES: [string, string, string][] = [
  ["subscribes", "Subscriptions", "#2196f3"],
  ["tips", "Tips", "#00bcd4"],
  ["post", "Posts", "#ec407a"],
  ["chat_messages", "Messages", "#ff7043"],
  ["ref", "Referrals", "#9575cd"],
  ["stream", "Streams", "#ffa000"],
];
type Month = NonNullable<NonNullable<EarningStats["months"]>[string]>;
const itemsOf = (m: Month | undefined, key: string): EarningItem[] => (Array.isArray(m?.[key]) ? (m[key] as EarningItem[]) : []);
const sumsOf = (m: Month | undefined, key: string): Sums =>
  itemsOf(m, key).reduce<{ total_gross: number; total_net: number }>((s, it) => ({ total_gross: s.total_gross + (num(it?.gross) ?? 0), total_net: s.total_net + (num(it?.net) ?? 0) }), { total_gross: 0, total_net: 0 });
const fade = (hex: string) => `rgba(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(",")},0.4)`;
const pad2 = (n: number) => String(n).padStart(2, "0");
const dayLabel = (ms: number) => {
  const d = new Date(ms);
  return `${pad2(d.getDate())} ${d.toLocaleDateString("en-US", { month: "short" })} ${String(d.getFullYear()).slice(2)}`;
};

export function earningsChart(months: (Month | undefined)[], start: number, end: number, current: string): LinesSpec {
  const secs = (end - start) / 1000;
  const n = secs < 15 ? Math.max(1, Math.floor(secs)) : 15;
  const unit = (end - start) / n;
  const dates = Array.from({ length: n }, (_, i) => (i === n - 1 ? end : Math.round(start + i * unit)));
  const lines = LINES.map(([key, title, color]) => {
    const values = new Array<number>(n).fill(0);
    for (const m of months)
      for (const it of itemsOf(m, key)) {
        const t = num(it?.time);
        const g = num(it?.gross);
        if (t === null || g === null) continue;
        let at = 0;
        for (let i = 1; i < n; i++) if (Math.abs(dates[i] - t * 1000) < Math.abs(dates[at] - t * 1000)) at = i;
        values[at] += g;
      }
    for (let i = 1; i < n; i++) values[i] += values[i - 1];
    return { title, values, color: key === current ? color : fade(color), kind: "money" as const };
  });
  return { labels: dates.map(dayLabel), lines };
}

interface EarningView {
  stats: EarningStats;
  now: Date;
  rows: Map<HTMLElement, "all" | number>;
  months: Map<number, Month | undefined>;
  expanded: "all" | number;
  current: string;
  custom?: { key: string; stats: EarningStats; from: Day; to: Day; start: number; end: number };
  clear?: () => void;
}
const earningViews = new WeakMap<Document, EarningView>();
const earningBound = new WeakSet<Document>();

function drawEarnings(doc: Document, canvas: HTMLCanvasElement, spec: LinesSpec) {
  const was = ["style", "width", "height"].map((a) => [a, canvas.getAttribute(a)] as const);
  track(doc, () => {
    clearChart(canvas);
    for (const [a, v] of was) if (v === null) canvas.removeAttribute(a);
    else canvas.setAttribute(a, v);
  });
  drawLines(canvas, spec);
}

function showEarning(doc: Document) {
  const v = earningViews.get(doc);
  if (!v) return;
  let all: HTMLElement | undefined;
  for (const [el, key] of v.rows) {
    if (key === "all") all = el;
    else el.querySelector(":scope > .b-stats-row__body")?.remove();
    setClass(doc, el, "m-expanded", key === v.expanded);
  }
  const allBody = all?.querySelector<HTMLElement>(":scope > .b-stats-row__body");
  if (!all || !allBody) return;
  setAttr(doc, allBody, "style", v.expanded === "all" ? null : "display:none");
  const custom = v.expanded === "all" ? v.custom : undefined;
  const total = (custom ? custom.stats.total : v.stats.total) ?? {};
  setMoney(doc, all.querySelector(".b-stats-row__total-net > span"), total.all?.total_net ?? 0);
  const month = v.expanded === "all" ? undefined : v.months.get(v.expanded);
  let body = allBody;
  let start: number;
  let end: number;
  let from: string;
  let to: string;
  if (custom) {
    [start, end] = [custom.start, custom.end];
    [from, to] = [tabDate(custom.from), tabDate(custom.to)];
  } else if (v.expanded === "all") {
    const first = Math.min(...v.months.keys());
    start = Number.isFinite(first) ? first : new Date(v.now.getFullYear(), v.now.getMonth(), v.now.getDate()).getTime();
    end = v.now.getTime();
    [from, to] = [longDay(new Date(start)), longDay(v.now)];
  } else {
    const row = [...v.rows].find(([, k]) => k === v.expanded)![0];
    body = allBody.cloneNode(true) as HTMLElement;
    body.removeAttribute("style");
    row.appendChild(body);
    const d = new Date(v.expanded);
    start = new Date(d.getFullYear(), d.getMonth(), 1).getTime();
    end = new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime() - 1;
    from = to = monthTitle(d).trim();
  }
  const dates = body.querySelectorAll(".b-date-value");
  if (dates.length === 2) {
    setText(doc, dates[0], from);
    setText(doc, dates[1], to);
  }
  for (const [cls, key] of CATEGORIES) {
    const row = body.querySelector(`.b-stats-row__content > .b-stats-row__label.${cls}`);
    if (!row) continue;
    setSums(doc, row, v.expanded === "all" ? total[key] : sumsOf(month, key));
    setClass(doc, row, "m-current", key === v.current);
  }
  const sums = v.expanded === "all" ? total.all : month;
  const items = [...body.querySelectorAll(".m-total .m-total-item")];
  setMoney(doc, items[0]?.querySelector(".b-stats-row__val"), sums?.total_gross ?? 0);
  setMoney(doc, items[1]?.querySelector(".b-stats-row__val"), sums?.total_net ?? 0);
  const canvas = body.querySelector("canvas");
  const chartMonths = custom ? Object.values(custom.stats.months ?? {}) : v.expanded === "all" ? [...v.months.values()] : [month];
  if (canvas) drawEarnings(doc, canvas, earningsChart(chartMonths, start, end, v.current));
}

function bindEarning(doc: Document) {
  if (earningBound.has(doc)) return;
  earningBound.add(doc);
  doc.addEventListener("click", (ev) => {
    const v = earningViews.get(doc);
    const t = ev.target as Element | null;
    if (!v || !t?.closest) return;
    const head = t.closest(".b-stats-wrap > .b-stats-row > .b-stats-row__head");
    const key = head && v.rows.get(head.parentElement as HTMLElement);
    if (key !== undefined && key !== null) {
      v.expanded = key;
      if (key === "all" && v.custom) {
        v.custom = undefined;
        v.clear?.();
      }
      return showEarning(doc);
    }
    const label = t.closest(".b-stats-row__body .b-stats-row__content > .b-stats-row__label");
    const cat = label && CATEGORIES.find(([cls]) => label.classList.contains(cls))?.[1];
    if (cat) {
      v.current = cat;
      showEarning(doc);
    }
  });
}

function applyEarningStats(doc: Document, stats: EarningStats, now: Date, prev: EarningView | undefined, range: EarningRange | null) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-stats-wrap > .b-stats-row")];
  const all = rows.find((r) => r.querySelector(".b-stats-row__content"));
  const monthTpl = rows.find((r) => r !== all);
  if (!all) return;
  const months = Object.entries(stats.months ?? {})
    .map(([k, m]) => ({ at: new Date(Number(k) * 1000), m }))
    .filter(({ at }) => !Number.isNaN(at.getTime()))
    .sort((a, b) => b.at.getTime() - a.at.getTime());
  const view: EarningView = { stats, now, rows: new Map([[all, "all"]]), months: new Map(months.map(({ at, m }) => [at.getTime(), m])), expanded: "all", current: prev?.current ?? "subscribes" };
  if (prev && prev.expanded !== "all" && view.months.has(prev.expanded)) view.expanded = prev.expanded;
  const picked = range?.picked;
  if (range && picked?.stats) {
    const r = statementsRange(picked.from, picked.to, now, range.tz);
    const key = `${r.params.startDate}..${r.params.endDate}`;
    view.custom = { key, stats: picked.stats, from: picked.from, to: picked.to, start: r.start.getTime(), end: r.end.getTime() };
    if (prev?.custom?.key !== key) view.expanded = "all";
  }
  view.clear = range?.clear;
  earningViews.set(doc, view);
  bindEarning(doc);
  if (monthTpl) {
    const tpl = make(monthTpl);
    tpl.style.removeProperty("display");
    if (!tpl.getAttribute("style")) tpl.removeAttribute("style");
    tpl.classList.remove("m-expanded");
    tpl.querySelector(".b-stats-row__body")?.remove();
    for (const r of rows) {
      if (r === all) continue;
      const was = r.getAttribute("style");
      track(doc, () => (was === null ? r.removeAttribute("style") : r.setAttribute("style", was)));
      r.setAttribute("style", `${was ?? ""};display:none`);
    }
    const wrap = monthTpl.parentElement!;
    for (const { at, m } of months) {
      const el = tpl.cloneNode(true) as HTMLElement;
      const title = el.querySelector(".b-stats-row__month");
      if (title) title.textContent = monthTitle(at);
      const net = el.querySelector(".b-stats-row__total-net > span");
      if (net) {
        const n = num(m?.total_net) ?? 0;
        net.textContent = ` ${usd(n)} `;
        net.classList.toggle("m-zero-value", n === 0);
      }
      wrap.appendChild(el);
      track(doc, () => el.remove());
      view.rows.set(el, at.getTime());
    }
  }
  showEarning(doc);
}

export function applyMoney(doc: Document, page: string, data: MoneyData, now: Date = new Date()): void {
  restoreMoney(doc);
  const parts = moneyParts(page);
  if (parts.includes("balances") && data.balances) applyBalances(doc, data, now);
  payouts.set(doc, { balances: parts.includes("balances") ? data.balances : undefined, user: data.payoutUser, actions: data.actions });
  const view = earningViews.get(doc);
  earningViews.delete(doc);
  if (parts.includes("earningStats")) {
    for (const b of doc.querySelectorAll(RANGE)) {
      setAttr(doc, b, "data-oi-wired", "");
      setAttr(doc, b, "disabled", null);
      setAttr(doc, b, "title", null);
    }
    bindRange(doc, data.range ?? null);
  }
  if (parts.includes("earningStats") && data.earningStats) applyEarningStats(doc, data.earningStats, now, view, data.range ?? null);
  if (parts.includes("referralBalance") && data.referralEarnings !== undefined) {
    for (const el of doc.querySelectorAll(".g-box__header__inner__value > span, .b-referrals-state__count")) setMoney(doc, el, data.referralEarnings);
  }
  if (parts.includes("referralBalance")) {
    const url = data.meId == null || data.meId === "" ? null : `https://onlyfans.com?ref=${encodeURIComponent(String(data.meId))}`;
    links.set(doc, url);
    if (url) for (const el of doc.querySelectorAll(".b-referrals__copy-description, .b-referrals-state__copy-url__link")) setText(doc, el, ` ${url} `);
  }
  bindStatements(doc);
}

const RANGE = ".b-stats-row__body button.m-time-period";
export const RANGE_NO_MODEL = "Select a model to pick a period";
const ranges = new WeakMap<Document, EarningRange | null>();
function bindRange(doc: Document, range: EarningRange | null) {
  const bound = ranges.has(doc);
  ranges.set(doc, range);
  if (bound) return;
  doc.addEventListener("click", (ev) => {
    const btn = (ev.target as Element | null)?.closest?.<HTMLElement>(RANGE);
    if (!btn) return;
    ev.preventDefault();
    const r = ranges.get(doc);
    if (!r) return note(doc, btn, RANGE_NO_MODEL);
    const now = new Date();
    const days = pickerDays(now, now, now, r.tz, r.userStart);
    const p = r.picked;
    openDatepicker(doc, { ...days, ...(p && { start: p.from, end: p.to }), opener: btn, onApply: (from, to) => r.pick(from, to) });
  });
}

const links = new WeakMap<Document, string | null>();
const payouts = new WeakMap<Document, { balances?: Balances; user?: PayoutUser; actions?: MoneyActions }>();
const bound = new WeakSet<Element>();

function bindStatements(doc: Document) {
  for (const head of doc.querySelectorAll<HTMLElement>(".balance-block > button.g-box__header.m-title[data-oi-wired]")) {
    if (bound.has(head)) continue;
    bound.add(head);
    head.addEventListener("click", () => {
      const content = head.parentElement?.querySelector<HTMLElement>(":scope > .g-box__content");
      if (!content) return;
      const collapse = content.style.display !== "none";
      content.style.display = collapse ? "none" : "";
      head.closest(".g-box")?.classList.toggle("m-roll-state", collapse);
      const icon = head.querySelector(".g-box__collapse-icon svg");
      icon?.setAttribute("data-icon-name", collapse ? "icon-arrow-down" : "icon-arrow-up");
      for (const use of icon?.querySelectorAll("use") ?? []) {
        use.setAttribute("href", collapse ? "#icon-arrow-down" : "#icon-arrow-up");
        if (use.hasAttribute("xlink:href")) use.setAttribute("xlink:href", collapse ? "#icon-arrow-down" : "#icon-arrow-up");
      }
    });
  }
  for (const slot of doc.querySelectorAll<HTMLElement>(".balance-block .v-select .v-input__slot[data-oi-wired]")) {
    if (bound.has(slot)) continue;
    bound.add(slot);
    bindPeriodSelect(doc, slot);
  }
  for (const btn of doc.querySelectorAll<HTMLButtonElement>(WITHDRAW)) {
    if (bound.has(btn)) continue;
    bound.add(btn);
    btn.addEventListener("click", () => {
      const { balances: b, user: u, actions } = payouts.get(doc) ?? {};
      if (btn.disabled || withdrawDisabled(b, u)) return;
      if (u?.hasPayoutsIssue) {
        (doc.defaultView?.top ?? doc.defaultView)?.location.assign("/of-manager/statements/support");
        return;
      }
      if (!payoutsDisabled(b, u) && actions) openPayoutsModal(doc, b!, actions);
    });
  }
  const copy = doc.querySelector<HTMLElement>("[at-attr='referrals_url'] button[data-oi-wired], .b-referrals-state__content > .g-btn__row > button[data-oi-wired]");
  if (copy && !bound.has(copy)) {
    bound.add(copy);
    copy.addEventListener("click", () => {
      const url = links.get(doc);
      if (!url) return note(doc, copy, "Select a model to copy its referral link");
      const clipboard = doc.defaultView?.navigator.clipboard;
      if (!clipboard) return note(doc, copy, "Could not copy the link", true);
      clipboard.writeText(url).then(
        () => note(doc, copy, "Link copied"),
        () => note(doc, copy, "Could not copy the link", true),
      );
    });
  }
}

function bindPeriodSelect(doc: Document, slot: HTMLElement) {
  const input = slot.closest<HTMLElement>(".v-input")!;
  const menu = () => input.parentElement?.querySelector<HTMLElement>(":scope > .v-menu__content");
  const isOpen = () => menu()?.style.display === "block";
  let was: [string | null, string | null] | null = null;
  const close = () => {
    const m = menu();
    if (!m || !isOpen()) return;
    m.style.display = "none";
    m.classList.remove("menuable__content__active");
    if (was) {
      for (const [n, v] of [["style", was[0]], ["class", was[1]]] as const) {
        if (v === null) m.removeAttribute(n);
        else m.setAttribute(n, v);
      }
    }
    input.classList.remove("v-input--is-focused", "primary--text", "v-select--is-menu-active");
    slot.setAttribute("aria-expanded", "false");
  };
  slot.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const m = menu();
    if (!m || slot.getAttribute("role") !== "button" || input.classList.contains("v-input--is-disabled")) return;
    if (isOpen()) return close();
    was = [m.getAttribute("style"), m.getAttribute("class")];
    m.style.display = "block";
    m.style.top = `${input.offsetTop + input.offsetHeight}px`;
    m.style.left = `${input.offsetLeft}px`;
    m.style.minWidth = `${input.offsetWidth}px`;
    m.style.zIndex = "8";
    m.classList.add("menuable__content__active");
    input.classList.add("v-input--is-focused", "primary--text", "v-select--is-menu-active");
    slot.setAttribute("aria-expanded", "true");
  });
  menu()?.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const item = (ev.target as Element).closest(".v-list-item");
    const items = [...(menu()?.querySelectorAll(":scope .v-select-list > .v-list-item") ?? [])];
    const i = item ? items.indexOf(item) : -1;
    if (i < 0) return;
    close();
    const { balances: b, actions } = payouts.get(doc) ?? {};
    const code = (b?.withdrawalPeriodOptions ?? []).filter((o) => o?.name)[i]?.code;
    if (code && code !== b?.withdrawalPeriod) void actions?.setPeriod(code).catch(() => {});
  });
  doc.addEventListener("click", close);
  doc.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") close();
  });
}

const modalShell = (cls: string, header: string, body: string, footer = "") =>
  `<div style="position: absolute; z-index: 1040;" data-oi-dialog="" data-oi-wired=""><div role="dialog" aria-modal="true" class="modal fade show ${cls}" style="display: block;"><div class="modal-dialog modal-sm modal-dialog-centered"><div tabindex="-1" class="modal-content">${header}${body}${footer}</div></div></div><div class="modal-backdrop show"></div></div>`;

const PAYOUTS_HTML = modalShell(
  "tip-modal payouts-modal",
  `<header class="modal-header"><h4 class="modal-title"> ${TEXTS.payout_request_manual} </h4></header>`,
  `<div class="modal-body m-reset-body-padding-bottom"><form><div class="b-inline-form d-flex align-items-start"><div class="g-input__wrapper m-reset-bottom-gap mr-2 flex-fill-1"><div class="g-input__wrapper input-text-field m-reset-bottom-gap m-empty"><div class=""><div class="v-input form-control g-input mb-0 theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder m-reset-bottom-gap m-placeholder-gap"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 0px;"><span class="notranslate">\u200b</span></legend></fieldset><div class="v-text-field__slot"><div class="v-text-field__prefix" style="display:none"></div><input id="tipInput" at-attr="input" inputmode="decimal" autocomplete="tip-input" required="required" placeholder="${TEXTS.withdrawal_amount_placeholder}" type="text"></div></div><div class="v-text-field__details"><div class="v-messages theme--light"><div class="v-messages__wrapper"></div></div></div></div><div class="v-input__append-outer"><div class="g-input__help"><div></div></div></div></div></div></div></div><button type="button" class="g-btn m-lg m-rounded" data-oi-max=""><span class="g-spacer-r">${TEXTS.max_button}</span><span class=""></span></button></div><div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.button_label_cancel} </button><button type="submit" disabled="disabled" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.request_withdrawal_button_label} </button></div></form></div>`,
);

function mountDialog(doc: Document, html: string, close: () => void): HTMLElement {
  const holder = doc.createElement("div");
  holder.innerHTML = html;
  const root = holder.firstElementChild as HTMLElement;
  doc.body.append(root);
  const modal = root.querySelector<HTMLElement>(".modal")!;
  modal.addEventListener("click", (ev) => {
    if (ev.target === modal) close();
  });
  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") close();
  };
  doc.addEventListener("keydown", onKey);
  root.addEventListener("oi-closed", () => doc.removeEventListener("keydown", onKey));
  return root;
}
const unmount = (root: HTMLElement) => {
  root.dispatchEvent(new Event("oi-closed"));
  root.remove();
};

export function showAlert(doc: Document, html: string): HTMLElement {
  doc.querySelector("[data-oi-dialog][data-oi-alert]")?.remove();
  const body = `<div class="modal-body">${html ? `<div class="dialog_message m-break-word-default">${html}</div>` : ""}</div>`;
  const footer = `<footer class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.dialog_close_button} </button></footer>`;
  const root: HTMLElement = mountDialog(doc, modalShell("modal-alert", "", body, footer), () => unmount(root));
  root.setAttribute("data-oi-alert", "");
  root.querySelector(".modal-footer button")!.addEventListener("click", () => unmount(root));
  return root;
}

export function openPayoutsModal(doc: Document, b: Balances, actions: MoneyActions): HTMLElement {
  doc.querySelector("[data-oi-dialog][data-oi-payouts]")?.remove();
  const min = b.minPayoutSumm;
  const max = maxPayout(b);
  const currency = b.currency || "usd";
  let value: string | number = "";
  let busy = false;
  const root: HTMLElement = mountDialog(doc, PAYOUTS_HTML, () => unmount(root));
  root.setAttribute("data-oi-payouts", "");
  const q = <T extends Element = HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const input = q<HTMLInputElement>("#tipInput");
  const maxBtn = q<HTMLButtonElement>("[data-oi-max]");
  const submit = q<HTMLButtonElement>(".modal-footer button[type='submit']");
  const maxText = maxBtn.querySelector("span:last-child")!;
  maxText.textContent = ` ${utilsMoney(max, currency, 0)} `;
  maxText.classList.toggle("m-zero-value", Math.round(max) === 0);
  const render = () => {
    const err = amountError(value, min, max, currency);
    const shown = value === 0 ? "" : String(value);
    if (input.value !== shown) input.value = shown;
    const field = q(".input-text-field");
    field.classList.toggle("m-empty", !shown);
    field.classList.toggle("m-error", !!err);
    const vInput = q(".v-input");
    vInput.classList.toggle("v-text-field--prefix", !!shown);
    vInput.classList.toggle("error--text", !!err);
    vInput.classList.toggle("v-input--has-state", !!err);
    const prefix = q(".v-text-field__prefix");
    prefix.textContent = shown ? symbolOf(currency) : "";
    prefix.style.display = shown ? "" : "none";
    const messages = q(".v-messages");
    messages.classList.toggle("error--text", !!err);
    q(".v-messages__wrapper").innerHTML = err ? `<div class="v-messages__message">${escapeHtml(err)}</div>` : "";
    const outOfRange = !!value && submitDisabled(value, min, max);
    q(".v-input__append-outer").style.display = outOfRange ? "none" : "";
    q(".g-input__help > div").textContent = amountHint(min, currency);
    maxBtn.disabled = value === max;
    submit.disabled = busy || submitDisabled(value, min, max);
  };
  input.addEventListener("input", () => {
    const clean = input.value.replace(/[^\d.]/g, "").replace(/(\..*)\./g, "$1");
    value = clean;
    render();
  });
  maxBtn.addEventListener("click", () => {
    value = max;
    render();
  });
  q(".modal-footer button[type='button']").addEventListener("click", () => unmount(root));
  q<HTMLFormElement>("form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (busy || submitDisabled(value, min, max)) return;
    busy = true;
    render();
    let message: string;
    try {
      message = resultDescription(await actions.withdraw(Number(value)));
    } catch (e) {
      message = escapeHtml(withdrawError(e));
    }
    unmount(root);
    showAlert(doc, message);
  });
  render();
  input.focus();
  return root;
}

export function useOfMoney(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const parts = moneyParts(page);
  const q = (part: MoneyPart) => ({
    queryKey: ["of-mirror-data", accountId, MONEY_ROUTES[part]],
    queryFn: () => relay.get<unknown>(MONEY_ROUTES[part], { accountId }),
    enabled: !!accountId && parts.includes(part),
    staleTime: 60_000,
    retry: false,
  });
  const balances = useQuery(q("balances")).data;
  const stats = useQuery(q("earningStats")).data;
  const tz = useAppliedSettings().data?.preferences?.tz ?? null;
  const startBody = useQuery(mirrorQuery(accountId, START_DATE, parts.includes("earningStats"))).data;
  const [picked, setPicked] = useState<{ accountId: string; src: string; from: Day; to: Day } | null>(null);
  const stale = !!picked && (picked.accountId !== accountId || picked.src !== src);
  if (stale) setPicked(null);
  const pick = stale ? null : picked;
  const rangeRoute = pick ? earningStatsRoute(statementsRange(pick.from, pick.to, new Date(), tz).params) : null;
  const rangeBody = useQuery(mirrorQuery(accountId, rangeRoute, parts.includes("earningStats"))).data;
  const referral = useQuery(q("referralBalance")).data;
  const me = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && (parts.includes("referralBalance") || parts.includes("balances")) }).data;
  const meId = me?.id;
  const receive = useQuery({
    queryKey: ["of-mirror-data", accountId, CHECK_RECEIVE],
    queryFn: () => relay.get<{ canReceiveManualPayout?: boolean }>(CHECK_RECEIVE, { accountId }),
    enabled: !!accountId && parts.includes("balances"),
    staleTime: 60_000,
    retry: false,
  }).data;
  const [periodSaving, setPeriodSaving] = useState(false);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !moneyParts(page).length) return;
    const balancesKey = ["of-mirror-data", accountId, MONEY_ROUTES.balances];
    const meFlags = me as (PayoutUser & object) | undefined;
    const payoutUser: PayoutUser | undefined = meFlags
      ? { canReceiveManualPayout: receive?.canReceiveManualPayout ?? meFlags.canReceiveManualPayout, hasPayoutsIssue: meFlags.hasPayoutsIssue }
      : undefined;
    const actions: MoneyActions = {
      withdraw: async (amount) => {
        const answer = await relay.post<unknown>(PAYOUT_REQUESTS, { withdrawal_amount: amount }, { accountId });
        void qc.invalidateQueries({ queryKey: balancesKey });
        void qc.invalidateQueries({ predicate: (x) => x.queryKey[0] === "of-mirror-data" && x.queryKey[1] === accountId && String(x.queryKey[2]).startsWith(PAYOUT_REQUESTS) });
        return answer;
      },
      setPeriod: async (code) => {
        const was = qc.getQueryData<Balances>(balancesKey);
        if (!was) return;
        qc.setQueryData(balancesKey, { ...was, withdrawalPeriod: code });
        setPeriodSaving(true);
        try {
          const r = await relay.patch<{ success?: boolean }>(PAYOUT_REQUESTS, { withdrawalPeriod: code }, { accountId });
          if (!r?.success) qc.setQueryData(balancesKey, was);
          return r;
        } catch (e) {
          qc.setQueryData(balancesKey, was);
          throw e;
        } finally {
          setPeriodSaving(false);
        }
      },
    };
    const data: MoneyData = accountId
      ? {
          ...moneyOf("balances", balances),
          ...moneyOf("earningStats", stats),
          ...moneyOf("referralBalance", referral),
          meId,
          payoutUser,
          periodSaving,
          actions,
          range: {
            tz,
            userStart: startOf(startBody, tz),
            picked: pick && { from: pick.from, to: pick.to, stats: moneyOf("earningStats", rangeBody).earningStats },
            pick: (from, to) => setPicked({ accountId, src, from, to }),
            clear: () => setPicked(null),
          },
        }
      : {};
    const apply = () => {
      const doc = frame.contentDocument;
      if (doc?.body) applyMoney(doc, page, data);
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, page, accountId, qc, balances, stats, referral, me, meId, receive, periodSaving, tz, startBody, pick, rangeBody]);
}
