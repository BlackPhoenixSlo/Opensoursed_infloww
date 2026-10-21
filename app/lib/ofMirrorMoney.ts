"use client";

/**
 * Real money figures on the OF mirror's Statements and Statistics pages (reads only). With a single model selected:
 * - the balance boxes (Statements' collapsible box, Statistics' sidebar) show `/payouts/balances`: Current balance
 *   `payoutAvailable`, Pending balance `payoutPending`, the payout frequency's name (`withdrawalPeriod` among
 *   `withdrawalPeriodOptions`, which are its menu's options) and the minimum withdrawal amount `minPayoutSumm` in its
 *   captured sentence (fixture app/lib/__fixtures__/of/statements-balances.json);
 * - Statements' Earning Statistics shows `/payouts/stats` (OF reads its `list`): the all-time net, gross and net per
 *   category and in total, the date range, and one row per month (newest first) with its net;
 * - Referrals' "Current referral earnings" shows `/payments/referrals/balance`'s `referralEarnings`;
 * - Chargebacks' "Chargeback ratio N%" shows `/payouts/chargebacks/ratio`'s `chargebacksRatio` (OF's last 30 days).
 * Field names and selectors are OF's own (build 202610091632: statements.js, statistics-statements.js,
 * statements-earning-stats.js, app.js module 874727). All models (but on Statements' Earnings, which shows the first
 * model: standInModel), no data yet or a relay error: each figure a dash, as the generator draws Statements (no example
 * figure). Also on Statements: the balance box's header collapses and expands it (OF's v-show, arrow and m-roll-state),
 * and Referrals' "Copy link" copies the Creator's referral link, OF's `https://onlyfans.com?ref=<OF user id>` (from
 * `/users/me`; All models: a note asks for a model).
 *
 * Statements' balance box writes as OF's Balances, useBalances (67411.js module 327189) and ModalPayouts (808072) do,
 * for the model shown (the stand-in in All models):
 * - the payout frequency select opens its menu of `withdrawalPeriodOptions`; picking another sends OF's
 *   `PATCH /payouts/requests {withdrawalPeriod}`, the select disabled while it saves, the old one back if it fails (OF
 *   shows no message); the line under it is OF's minSumMessage for the frequency;
 * - "Request withdrawal" shows only for manual payouts and is enabled by OF's own rule (disabledManualWithdraw: a balance
 *   at least the minimum, and the account able to receive a manual payout or with a payouts issue, which opens Billing
 *   Support instead); it opens OF's "Manual payouts" dialog (amount between the minimum and OF's max, its Max button and
 *   messages), whose Request withdrawal sends `POST /payouts/requests {withdrawal_amount}`; OF's answer shows in its
 *   alert dialog (the request's state, or OF's error message), and the balances are read again.
 * Copy is OF's (texts.onlyfans.com/texts_en.json, same build: TEXTS).
 */

import { useEffect, useState, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { make } from "@/lib/ofMirrorData";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { basePage } from "@/lib/ofMirrorRow";
import { note } from "@/lib/ofMirrorWrites";
import { parseSendFailure } from "@/lib/sendFailure";

export type MoneyPart = "balances" | "earningStats" | "referralBalance" | "chargebacks";

/** Relay route per part (`X-Account-Id` from the scope). */
export const MONEY_ROUTES: Record<MoneyPart, string> = {
  balances: "/api/of/v2/payouts/balances",
  earningStats: "/api/of/v2/payouts/stats",
  referralBalance: "/api/of/v2/payments/referrals/balance",
  chargebacks: "/api/of/v2/payouts/chargebacks/ratio",
};

/** The money parts `page` (a state page: its page's) shows. Balances: every Statements page but Support, and Statistics' Overview and Statements tabs. */
export function moneyParts(page: string): MoneyPart[] {
  const p = basePage(page);
  const parts: MoneyPart[] = [];
  if (/^statements\/(?!support$)/.test(p) || /^statistics\/(overview|statements)\//.test(p)) parts.push("balances");
  if (p === "statements/stats/earnings") parts.push("earningStats");
  if (p === "statements/referrals" || p === "statistics/statements/referrals/earnings") parts.push("referralBalance");
  if (p === "statements/stats/disputes") parts.push("chargebacks"); // Statistics' ratio follows its period: ofMirrorStats
  return parts;
}

export interface Balances {
  payoutAvailable?: number | null;
  payoutPending?: number | null;
  currency?: string | null;
  minPayoutSumm?: number | null;
  maxPayoutSumm?: number | null;
  /** Read by OF's minSumMessage (absent from OF's /payouts/balances, so OF shows its "Once your balance is over" line). */
  availableAmount?: number | null;
  withdrawalPeriod?: string | null;
  withdrawalPeriodOptions?: { code?: string; name?: string }[] | null;
}

/** OF's authUser fields the withdrawal rules read (`/users/me`, `canReceiveManualPayout` updated by `/payouts/check-receive`). */
export interface PayoutUser {
  canReceiveManualPayout?: boolean | null;
  hasPayoutsIssue?: unknown;
}

/** The balance box's writes, for the model shown. */
export interface MoneyActions {
  /** OF's sendPayoutRequest: resolves with OF's answer, rejects with the relay's error. */
  withdraw: (amount: number) => Promise<unknown>;
  /** OF's changeWithdrawalPeriod. */
  setPeriod: (code: string) => Promise<unknown>;
}

type Sums = { total_gross?: number | null; total_net?: number | null };
/** `/payouts/stats`'s `list`: totals per category (`all` the sum) and per month (key: the month's start, unix seconds). */
export interface EarningStats {
  total?: Record<string, Sums | undefined> | null;
  months?: Record<string, Sums | undefined> | null;
}

export interface MoneyData {
  /** The Creator's OF user id: Referrals' link. */
  meId?: string | number | null;
  balances?: Balances;
  earningStats?: EarningStats;
  referralEarnings?: number | null;
  chargebacksRatio?: number | null;
  payoutUser?: PayoutUser;
  /** A frequency change is being saved (OF's disabledWithdrawalPeriod). */
  periodSaving?: boolean;
  actions?: MoneyActions;
}

/** The relay's body for a part as MoneyData (anything unusable: nothing). */
export function moneyOf(part: MoneyPart, body: unknown): MoneyData {
  const o = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
  if (!o) return {};
  if (part === "balances") return { balances: o as Balances };
  if (part === "earningStats") {
    const l = o.list && typeof o.list === "object" ? o.list : o; // OF reads `.list`
    return { earningStats: l as EarningStats };
  }
  if (part === "referralBalance") return { referralEarnings: o.referralEarnings as number | null };
  return { chargebacksRatio: o.chargebacksRatio as number | null };
}

// This module's own undo list per page (ofMirrorData's restore must not undo these, nor these its rows).
const undos = new WeakMap<Document, (() => void)[]>();
function track(doc: Document, undo: () => void) {
  let u = undos.get(doc);
  if (!u) undos.set(doc, (u = []));
  u.push(undo);
}
function restoreMoney(doc: Document) {
  const u = undos.get(doc) ?? [];
  while (u.length) u.pop()!();
}
function setText(doc: Document, el: Element | null | undefined, text: string) {
  if (!el) return;
  const was = el.textContent ?? "";
  if (was === text) return;
  track(doc, () => (el.textContent = was));
  el.textContent = text;
}
function setClass(doc: Document, el: Element, cls: string, on: boolean) {
  if (el.classList.contains(cls) === on) return;
  const was = el.getAttribute("class");
  track(doc, () => (was === null ? el.removeAttribute("class") : el.setAttribute("class", was)));
  el.classList.toggle(cls, on);
}
/** Set (null: remove) an attribute, undone by restoreMoney (every attribute back in its order: the markup byte for byte). */
function setAttr(doc: Document, el: Element | null | undefined, name: string, value: string | null) {
  if (!el || el.getAttribute(name) === value) return;
  const was = [...el.attributes].map((a) => [a.name, a.value] as const);
  track(doc, () => {
    for (const a of [...el.attributes]) el.removeAttribute(a.name);
    for (const [n, v] of was) el.setAttribute(n, v);
  });
  if (value === null) el.removeAttribute(name);
  else el.setAttribute(name, value);
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
/** "$1,234.00": OF's UtilsMoney. */
export const usd = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD" });

/** A figure with no value: the generator's dash. */
export const DASH = " — ";

/** A money span: ` $1,234.00 ` (not a number: a dash), with OF's `m-zero-value` mark on zero. */
function setMoney(doc: Document, el: Element | null | undefined, v: unknown) {
  if (!el) return;
  const n = num(v);
  setText(doc, el, n === null ? DASH : ` ${usd(n)} `);
  setClass(doc, el, "m-zero-value", n === 0);
}

/** Replace the first `pattern` match in `el`'s text nodes with `to`. */
function swapIn(doc: Document, el: Element | null | undefined, pattern: RegExp, to: string) {
  if (!el) return;
  const walker = doc.createTreeWalker(el, 4 /* NodeFilter.SHOW_TEXT */);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const was = n.nodeValue ?? "";
    if (!pattern.test(was)) continue;
    const node = n;
    track(doc, () => (node.nodeValue = was));
    node.nodeValue = was.replace(pattern, to);
    return;
  }
}

const MIN_AMOUNT = /\$\d[\d,]*(?:\.\d+)?/;
/** "$20": the minimum withdrawal in OF's sentences. */
const minAmount = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

// ---------------------------------------------------------------- withdrawals and the payout frequency

/** The relay's routes for OF's payout writes and the account's payout eligibility. */
export const PAYOUT_REQUESTS = "/api/of/v2/payouts/requests";
export const CHECK_RECEIVE = "/api/of/v2/payouts/check-receive";

/** OF's copy (texts_en.json, build 202610091632), by OF's key. */
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

/** OF's comparisons on raw values (JavaScript's: an absent figure compares false, null as 0). */
const lt = (a: unknown, b: unknown) => (a as number) < (b as number);
const hasBalances = (b: Balances | null | undefined): b is Balances => !!b && typeof b === "object" && Object.keys(b).length > 0;

/** OF's disabledManualPayouts: no withdrawal dialog below the minimum, or when the account cannot receive a manual payout. */
export function payoutsDisabled(b: Balances | null | undefined, u: PayoutUser | null | undefined): boolean {
  return !(hasBalances(b) && u) || lt(b.payoutAvailable, b.minPayoutSumm) || !u.canReceiveManualPayout;
}

/** OF's disabledManualWithdraw: Request withdrawal's disabled state. */
export function withdrawDisabled(b: Balances | null | undefined, u: PayoutUser | null | undefined): boolean {
  return !(hasBalances(b) && u) || lt(b.payoutAvailable, b.minPayoutSumm) || (!u.hasPayoutsIssue && payoutsDisabled(b, u));
}

/** OF's isManualWithdrawal: Request withdrawal shows for manual payouts only (the primary box is never Stripe's here). */
export const isManualWithdrawal = (b: Balances | null | undefined) => b?.withdrawalPeriod === "manual";

/** ModalPayouts' maxPayoutAvailable: the balance, at most OF's maxPayoutSumm, rounded down. */
export const maxPayout = (b: Balances) => Math.floor((lt(b.maxPayoutSumm, b.payoutAvailable) ? b.maxPayoutSumm : b.payoutAvailable) as number);

const SYMBOLS: Record<string, string> = { usd: "$", eur: "€", gbp: "£" };
/** OF's currency helper (module 277832): its symbol, `$` for any other. */
const symbolOf = (currency: unknown) => SYMBOLS[typeof currency === "string" ? currency.toLowerCase() : ""] ?? "$";
/** OF's currencyFormat: the symbol and the figure as given ("$20"). */
const currencyFormat = (v: unknown, currency: unknown) => `${symbolOf(currency)}${v}`;
/** OF's UtilsMoney text: the symbol and the figure to `places` decimals, thousands separated. */
const utilsMoney = (v: number, currency: unknown, places: number) =>
  `${symbolOf(currency)}${v.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places })}`;

/** OF's payoutDate for a frequency: the next payout's day ("Oct 19, 2026"); none for manual payouts. */
export function payoutDate(period: string | null | undefined, now: Date): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (period === "daily") d.setDate(d.getDate() + 2);
  else if (period === "monthly") d.setMonth(d.getMonth() + 1, 1);
  else if (period === "weekly") {
    d.setDate(d.getDate() + 7);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // its ISO week's Monday
  } else return "";
  return longDay(d);
}

/** OF's minSumMessage, the line under the frequency select. */
export function minSumMessage(b: Balances, now: Date): string {
  const amount = currencyFormat(b.minPayoutSumm, b.currency);
  if (isManualWithdrawal(b)) return fill(TEXTS.payout_min_amount_message, { AMOUNT: amount });
  const date = payoutDate(b.withdrawalPeriod, now);
  return (b.availableAmount as number) >= (b.minPayoutSumm as number)
    ? fill(TEXTS.payout_next_date_success_message, { DATE: date })
    : fill(TEXTS.payout_next_date_warning_message, { BALANCE: amount, DATE: date });
}

/** InputTips' line under the amount: OF's minimum (shown while the amount is in range). */
export const amountHint = (min: unknown, currency: unknown) =>
  fill(TEXTS.min_price_label_without_currency, { MIN: `${symbolOf(currency)}${min} ${String(currency || "usd").toUpperCase()}` });

/** InputTips' messagePriceError: an amount under the minimum or over the max (none while empty). */
export function amountError(value: string | number, min: unknown, max: unknown, currency: unknown): string {
  if (!value) return "";
  const cur = String(currency || "usd").toUpperCase();
  if (lt(value, min)) return fill(TEXTS.min_price_label_without_currency, { MIN: `${symbolOf(currency)}${min} ${cur}` });
  if (lt(max, value)) return fill(TEXTS.max_price_label_without_currency, { MAX: `${symbolOf(currency)}${max} ${cur}` });
  return "";
}

/** ModalPayouts' submitDisabled. */
export const submitDisabled = (value: string | number, min: unknown, max: unknown) => lt(value, min) || lt(max, value);

const escapeHtml = (v: unknown) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** OF's getResultDescription: a line per payout request in OF's answer (HTML, `<br/>` between them). */
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

/** OF's error alert (module 758987): OF's own message, else its generic one. */
export function withdrawError(err: unknown): string {
  return parseSendFailure((err as { body?: unknown } | null)?.body).reason || TEXTS.debug_alert_message;
}

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
  // Statements' select (the generator marks its slot data-oi-wired): enabled once OF's options are here, not while a change saves.
  const open = !!(b.withdrawalPeriodOptions ?? []).some((o) => o?.name) && !data.periodSaving;
  for (const slot of doc.querySelectorAll(".balance-block .v-select .v-input__slot[data-oi-wired]")) {
    setClass(doc, slot.closest(".v-input")!, "v-input--is-disabled", !open);
    setAttr(doc, slot, "role", open ? "button" : null);
    setAttr(doc, slot, "aria-haspopup", open ? "listbox" : null);
    setAttr(doc, slot, "aria-expanded", open ? "false" : null);
    setAttr(doc, slot.querySelector("input[at-attr='dropdown']"), "disabled", open ? null : "disabled");
  }
  // Request withdrawal: manual payouts only (OF's v-if), enabled by OF's rule.
  for (const btn of doc.querySelectorAll(".balance-block .g-btn__wrapper > button[data-oi-wired]")) {
    const wrap = btn.parentElement!;
    setAttr(doc, wrap, "style", isManualWithdrawal(b) ? wrap.getAttribute("style") : "display:none");
    setAttr(doc, btn, "disabled", withdrawDisabled(b, data.payoutUser) ? "disabled" : null);
  }
}

/**
 * The payout frequency menu's options (Statements' select; disabled by the generator, so shown only as its selection):
 * one captured item per `withdrawalPeriodOptions` entry, OF's `name`, the current `withdrawalPeriod` active (OF's
 * VSelect item-text "name", item-value "code"). More options than captured items: the last one copied; fewer: the rest hidden.
 */
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

/** A stats row's sums: its gross and net value spans (OF's narrow layout shows the net only). */
function setSums(doc: Document, row: Element, s: Sums | undefined) {
  const vals = [...row.querySelectorAll(":scope > .b-stats-row__val")];
  if (vals.length > 1) setMoney(doc, vals[0], s?.total_gross ?? 0);
  setMoney(doc, vals.at(-1), s?.total_net ?? 0);
}

function applyEarningStats(doc: Document, stats: EarningStats, now: Date) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-stats-wrap > .b-stats-row")];
  const all = rows.find((r) => r.querySelector(".b-stats-row__content"));
  const monthTpl = rows.find((r) => r !== all);
  if (!all) return;
  const total = stats.total ?? {};
  // OF shows 0 for an absent sum.
  setMoney(doc, all.querySelector(".b-stats-row__total-net > span"), total.all?.total_net ?? 0);
  for (const [cls, key] of CATEGORIES) {
    const row = all.querySelector(`.b-stats-row__content > .b-stats-row__label.${cls}`);
    if (row) setSums(doc, row, total[key]);
  }
  const items = [...all.querySelectorAll(".m-total .m-total-item")];
  setMoney(doc, items[0]?.querySelector(".b-stats-row__val"), total.all?.total_gross ?? 0);
  setMoney(doc, items[1]?.querySelector(".b-stats-row__val"), total.all?.total_net ?? 0);
  const months = Object.entries(stats.months ?? {})
    .map(([k, m]) => ({ at: new Date(Number(k) * 1000), m }))
    .filter(({ at }) => !Number.isNaN(at.getTime()))
    .sort((a, b) => b.at.getTime() - a.at.getTime());
  const dates = all.querySelectorAll(".b-date-value");
  if (dates.length === 2) {
    setText(doc, dates[0], longDay(months.at(-1)?.at ?? now));
    setText(doc, dates[1], longDay(now));
  }
  if (!monthTpl) return;
  const tpl = make(monthTpl); // the generator's hidden template
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
  }
}

/** Show `data` on `doc` (the capture again for what it lacks; idempotent). */
export function applyMoney(doc: Document, page: string, data: MoneyData, now: Date = new Date()): void {
  restoreMoney(doc);
  const parts = moneyParts(page);
  if (parts.includes("balances") && data.balances) applyBalances(doc, data, now);
  payouts.set(doc, { balances: parts.includes("balances") ? data.balances : undefined, user: data.payoutUser, actions: data.actions });
  if (parts.includes("earningStats") && data.earningStats) applyEarningStats(doc, data.earningStats, now);
  if (parts.includes("referralBalance") && data.referralEarnings !== undefined) {
    for (const el of doc.querySelectorAll(".g-box__header__inner__value > span, .b-referrals-state__count")) setMoney(doc, el, data.referralEarnings);
  }
  const ratio = num(data.chargebacksRatio);
  if (parts.includes("chargebacks") && ratio !== null) {
    for (const el of doc.querySelectorAll(".m-statistics-alert .alert-text-wrapper > p")) swapIn(doc, el, /\d[\d.,]*%|—/, `${Math.round(ratio * 100) / 100}%`);
  }
  if (parts.includes("referralBalance")) {
    const url = data.meId == null || data.meId === "" ? null : `https://onlyfans.com?ref=${encodeURIComponent(String(data.meId))}`;
    links.set(doc, url);
    // Statements' and Statistics' referral link, as OF prints it.
    if (url) for (const el of doc.querySelectorAll(".b-referrals__copy-description, .b-referrals-state__copy-url__link")) setText(doc, el, ` ${url} `);
  }
  bindStatements(doc);
}

// Referrals' link per page (null: no model), read by its Copy link at click time.
const links = new WeakMap<Document, string | null>();
// The balance box's figures, OF's authUser fields and the writes per page, as the last apply saw them (read at click time).
const payouts = new WeakMap<Document, { balances?: Balances; user?: PayoutUser; actions?: MoneyActions }>();
const bound = new WeakSet<Element>();

/** The balance box's collapse, frequency select and Request withdrawal, and Referrals' Copy link (the generator marks them data-oi-wired), bound once each. */
function bindStatements(doc: Document) {
  for (const head of doc.querySelectorAll<HTMLElement>(".balance-block > button.g-box__header.m-title[data-oi-wired]")) {
    if (bound.has(head)) continue;
    bound.add(head);
    head.addEventListener("click", () => {
      const content = head.parentElement?.querySelector<HTMLElement>(":scope > .g-box__content");
      if (!content) return;
      const collapse = content.style.display !== "none";
      content.style.display = collapse ? "none" : "";
      // OF's GBoxWrapper's m-roll-state and its icon-arrow-down/up.
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
  for (const btn of doc.querySelectorAll<HTMLButtonElement>(".balance-block .g-btn__wrapper > button[data-oi-wired]")) {
    if (bound.has(btn)) continue;
    bound.add(btn);
    btn.addEventListener("click", () => {
      const { balances: b, user: u, actions } = payouts.get(doc) ?? {};
      // OF's onManualWithdrawalClick: nothing while disabled; a payouts issue opens Billing Support (subject payouts).
      if (btn.disabled || withdrawDisabled(b, u)) return;
      if (u?.hasPayoutsIssue) {
        (doc.defaultView?.top ?? doc.defaultView)?.location.assign("/of-manager/statements/support");
        return;
      }
      if (!payoutsDisabled(b, u) && actions) openPayoutsModal(doc, b!, actions);
    });
  }
  // Statements › Referrals' Copy link sits in the link's box; Statistics › Referrals' beside it (OF's StatisticsReferrals).
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

/** The frequency select: its slot opens the attached menu (OF's VSelect); an item picks its code; a click elsewhere or Escape closes it. */
function bindPeriodSelect(doc: Document, slot: HTMLElement) {
  const input = slot.closest<HTMLElement>(".v-input")!;
  const menu = () => input.parentElement?.querySelector<HTMLElement>(":scope > .v-menu__content");
  const isOpen = () => menu()?.style.display === "block";
  let was: [string | null, string | null] | null = null; // the menu's own style and class while it is open
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
    // OF's VSelect emits change only for another value.
    if (code && code !== b?.withdrawalPeriod) void actions?.setPeriod(code).catch(() => {});
  });
  doc.addEventListener("click", close);
  doc.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") close();
  });
}

/** OF's b-modal markup around a dialog (the captured ModalAlert's and ModalPostPrice's). */
const modalShell = (cls: string, header: string, body: string, footer = "") =>
  `<div style="position: absolute; z-index: 1040;" data-oi-dialog="" data-oi-wired=""><div role="dialog" aria-modal="true" class="modal fade show ${cls}" style="display: block;"><div class="modal-dialog modal-sm modal-dialog-centered"><div tabindex="-1" class="modal-content">${header}${body}${footer}</div></div></div><div class="modal-backdrop show"></div></div>`;

/** OF's ModalPayouts ("Manual payouts"): InputTips for the amount (its prefix, hint and error), Max, Cancel and Request withdrawal. */
const PAYOUTS_HTML = modalShell(
  "tip-modal payouts-modal",
  `<header class="modal-header"><h4 class="modal-title"> ${TEXTS.payout_request_manual} </h4></header>`,
  `<div class="modal-body m-reset-body-padding-bottom"><form><div class="b-inline-form d-flex align-items-start"><div class="g-input__wrapper m-reset-bottom-gap mr-2 flex-fill-1"><div class="g-input__wrapper input-text-field m-reset-bottom-gap m-empty"><div class=""><div class="v-input form-control g-input mb-0 theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder m-reset-bottom-gap m-placeholder-gap"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 0px;"><span class="notranslate">\u200b</span></legend></fieldset><div class="v-text-field__slot"><div class="v-text-field__prefix" style="display:none"></div><input id="tipInput" at-attr="input" inputmode="decimal" autocomplete="tip-input" required="required" placeholder="${TEXTS.withdrawal_amount_placeholder}" type="text"></div></div><div class="v-text-field__details"><div class="v-messages theme--light"><div class="v-messages__wrapper"></div></div></div></div><div class="v-input__append-outer"><div class="g-input__help"><div></div></div></div></div></div></div></div><button type="button" class="g-btn m-lg m-rounded" data-oi-max=""><span class="g-spacer-r">${TEXTS.max_button}</span><span class=""></span></button></div><div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.button_label_cancel} </button><button type="submit" disabled="disabled" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.request_withdrawal_button_label} </button></div></form></div>`,
);

/** A dialog's root from markup, appended to the page; Escape and a click on its backdrop call `close`. */
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

/** OF's alert dialog (ModalAlert, as captured): `html` (OF's message; its own lines) and Close. */
export function showAlert(doc: Document, html: string): HTMLElement {
  doc.querySelector("[data-oi-dialog][data-oi-alert]")?.remove(); // OF hides the open alert first
  const body = `<div class="modal-body">${html ? `<div class="dialog_message m-break-word-default">${html}</div>` : ""}</div>`;
  const footer = `<footer class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width"> ${TEXTS.dialog_close_button} </button></footer>`;
  const root: HTMLElement = mountDialog(doc, modalShell("modal-alert", "", body, footer), () => unmount(root));
  root.setAttribute("data-oi-alert", "");
  root.querySelector(".modal-footer button")!.addEventListener("click", () => unmount(root));
  return root;
}

/** Open OF's withdrawal dialog for `b`; its Request withdrawal sends the amount (`actions.withdraw`) and shows OF's answer. */
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
    // InputTips' hint shows unless the amount is out of range (show-error-on-over-max).
    const outOfRange = !!value && submitDisabled(value, min, max);
    q(".v-input__append-outer").style.display = outOfRange ? "none" : "";
    q(".g-input__help > div").textContent = amountHint(min, currency);
    maxBtn.disabled = value === max;
    submit.disabled = busy || submitDisabled(value, min, max);
  };
  input.addEventListener("input", () => {
    // InputTextField's number-only: digits and one decimal point.
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

/** On a Statements or Statistics page with a single model selected, show its money figures on every frame load and data change. */
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
  const referral = useQuery(q("referralBalance")).data;
  const chargebacks = useQuery(q("chargebacks")).data;
  const me = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && (parts.includes("referralBalance") || parts.includes("balances")) }).data;
  const meId = me?.id;
  // OF's fetchPayoutsReceive: canReceiveManualPayout as /payouts/check-receive has it now.
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
      // OF's sendPayoutRequest, then fetchBalances (and the Payout requests list: OF's WITHDRAWAL_REQUESTED).
      withdraw: async (amount) => {
        const answer = await relay.post<unknown>(PAYOUT_REQUESTS, { withdrawal_amount: amount }, { accountId });
        void qc.invalidateQueries({ queryKey: balancesKey });
        void qc.invalidateQueries({ predicate: (x) => x.queryKey[0] === "of-mirror-data" && x.queryKey[1] === accountId && String(x.queryKey[2]).startsWith(PAYOUT_REQUESTS) });
        return answer;
      },
      // OF's changeWithdrawalPeriod: the new one shown while it saves (select disabled), kept on {success}, else the old one back.
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
          ...moneyOf("chargebacks", chargebacks),
          meId,
          payoutUser,
          periodSaving,
          actions,
        }
      : {};
    const apply = () => {
      const doc = frame.contentDocument;
      if (doc?.body) applyMoney(doc, page, data);
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, page, accountId, qc, balances, stats, referral, chargebacks, me, meId, receive, periodSaving]);
}
