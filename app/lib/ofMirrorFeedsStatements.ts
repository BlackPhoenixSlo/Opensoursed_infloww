"use client";

/** Statements' Earnings, Payouts and Referrals tables and Streaming's past streams. */

import { NOT_YET } from "@/lib/ofMirrorWrites";
import { applyMore, clock, dayOf, dropClass, fill, make, plain, stamp, track, valid, type MorePages } from "@/lib/ofMirrorDom";
import { fullDay, wallClock } from "@/lib/ofMirrorFeedsShared";

/**
 * Statements' Earnings, Payouts and Referrals tables while their rows load (`null`) or after they failed: OF's empty row
 * says so (as Home's feed, applyFeedStatus).
 */
export function applyStatementsStatus(doc: Document, error: string | null) {
  const text = [...doc.querySelectorAll<HTMLElement>(".b-table tbody > tr .empty-message > span")].find((s) => !s.closest("[style*='none']"));
  if (!text) return;
  const [was, style] = [text.textContent, text.getAttribute("style")];
  track(doc, () => {
    text.textContent = was;
    if (style === null) text.removeAttribute("style");
    else text.setAttribute("style", style);
  });
  text.textContent = error === null ? "Loading…" : `Could not load: ${error}`;
  if (error !== null) text.style.color = "#ff4545";
}

/**
 * A `/payouts/transactions` item: OF's own fields (fixtures app/lib/__fixtures__/of/statements-transactions*.json; build
 * 202610091632: statements-earnings.js's StatementsEarningsList, Description and StatusTip).
 */
export interface Transaction {
  createdAt?: string;
  amount?: number | null;
  fee?: number | null;
  net?: number | null;
  /** "USD": UtilsMoney's symbol ($, € or £; another code follows the figure). */
  currency?: string | null;
  /** HTML: its fan link becomes text. */
  description?: string | null;
  /** `done`: Complete; `loading`: pending, `payoutPendingDays` until it is available. */
  status?: string;
  payoutPendingDays?: number | null;
  /** The fan: a deleted or inactive one is OF's greyed name (m-disabled-username). */
  user?: { isDeleted?: boolean | null; isActive?: boolean | null } | null;
}

/** OF's UtilsMoney: the currency's symbol and the figure with two decimals and thousands commas ("$1,234.50"). */
export function ofMoney(v: number, currency?: string | null): string {
  const figure = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const code = (currency || "usd").toLowerCase();
  const symbol = ({ usd: "$", eur: "€", gbp: "£" } as Record<string, string>)[code];
  return symbol ? `${symbol}${figure}` : `${figure} ${code.toUpperCase()}`;
}

/** A transaction's money cell: ` $5.00 ` (none: empty), with OF's m-zero-value when it rounds to 0. */
function moneyCell(span: Element | null, v: number | null | undefined, currency?: string | null) {
  if (!span) return;
  const n = typeof v === "number" && Number.isFinite(v) ? v : null;
  span.textContent = n === null ? "" : ` ${ofMoney(n, currency)} `;
  span.classList.toggle("m-zero-value", n !== null && Math.round(n) === 0);
  if (!span.getAttribute("class")) span.setAttribute("class", "");
}

/** "UTC +02:00": `zone`'s offset at `now` (none or unknown: the browser's), as OF's dayjs().format("Z"). */
export function zoneNote(zone?: string | null, now: Date = new Date()): string {
  const at = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
  const mins = -at.getTimezoneOffset() + Math.round((wallClock(at, zone ?? undefined).getTime() - at.getTime()) / 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `UTC ${mins < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(mins) / 60))}:${pad(Math.abs(mins) % 60)}`;
}

/** "$5.00": OF's statements money (none: empty). */
const dollars = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? ` $${v.toFixed(2)} ` : "");

/**
 * A statements table's rows: hide `examples` (and, while `clones` show, OF's empty row), put `clones` (shown: their
 * template is the generator's hidden row) before the table's loading row (none: at the table's end).
 */
function intoTable(doc: Document, body: Element, examples: HTMLElement[], clones: HTMLElement[]) {
  const empty = clones.length ? [...body.querySelectorAll<HTMLElement>(":scope > tr")].filter((r) => r.querySelector(".empty-message")) : [];
  const hide = [...examples, ...empty].filter((r) => !/display:\s*none/.test(r.getAttribute("style") ?? ""));
  if (hide.length) fill(doc, hide, [], [body]);
  const end = body.querySelector(".infinite-loading-container")?.closest("tr");
  for (const c of clones) {
    c.style.removeProperty("display");
    if (!c.getAttribute("style")) c.removeAttribute("style");
    if (end) end.before(c);
    else body.append(c);
    track(doc, () => c.remove());
  }
}

/** Set a cloned statements row's date and time from `createdAt` as `zone`'s wall clock reads it (none: empty; no zone: the browser's), then each [selector, text] cell. */
function setCells(el: Element, createdAt: string | undefined, cells: [string, string][], zone?: string) {
  const v = valid(createdAt);
  const at = v && wallClock(v, zone);
  const all: [string, string][] = [
    [".b-table__date__date > span", at ? ` ${fullDay(at)} ` : ""],
    [".b-table__date__time > span", at ? ` ${clock(at)} ` : ""],
    ...cells,
  ];
  for (const [sel, text] of all) {
    const cell = el.querySelector(sel);
    if (cell) cell.textContent = text;
  }
}

/**
 * Statements' Earnings: one copy of a captured row per transaction, in order, before the table's loading row. Its date
 * and time in `zone` (the Agency's time zone; none: the browser's, as the "Date/Time shown in local time (UTC ±hh:mm)"
 * note above the table then says), amount, fee and net in OF's money format (none: empty) and its description as plain
 * text, greyed for a deleted or inactive fan; a done item is the "Complete" row, a pending one ("loading") the pending
 * row, its tip "Earning will become available in N days" (no N: no tip text), any other status no status tips. `more`:
 * OF's infinite loading row shows its spinner while the next page is read, its "Opps, something went wrong" with Retry
 * after that failed, and otherwise asks for the next page once it scrolls into view. The balance boxes and the other
 * tabs stay as captured.
 */
export function applyTransactions(doc: Document, items: Transaction[], zone?: string, more?: MorePages) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-table tbody > tr")].filter((r) => r.querySelector(".b-table__date"));
  const row = (icon: string) => rows.find((r) => r.querySelector(`.b-table__status svg[data-icon-name='${icon}']`));
  const done = row("icon-done");
  const pending = row("icon-loading"); // Statements' index captures none: a pending item there shows no status tips
  const body = doc.querySelector(".b-table tbody");
  if (!done || !body) return;
  const note = doc.querySelector(".b-statements__head-timezone");
  if (note) {
    const was = note.textContent;
    const text = ` Date/Time shown in local time (${zoneNote(zone)}) `;
    if (was !== text) {
      track(doc, () => (note.textContent = was));
      note.textContent = text;
    }
  }
  const clones = items.map((t) => {
    const asPending = t.status === "loading" && pending;
    const el = make(asPending || done);
    setCells(el, t.createdAt, [], zone);
    moneyCell(el.querySelector(".b-table__amount > span"), t.amount, t.currency);
    moneyCell(el.querySelector(".b-table__fee > span"), t.fee, t.currency);
    moneyCell(el.querySelector(".b-table__net strong > span"), t.net, t.currency);
    const desc = el.querySelector(".b-table__desc .b-field-subscription");
    if (desc) {
      desc.classList.toggle("m-disabled-username", !!t.user && (!!t.user.isDeleted || t.user.isActive === false));
      desc.textContent = plain(t.description);
    }
    // Both copies: the status column's tip and the one inside the description (OF's narrow layout).
    if (t.status !== "done") {
      for (const tip of el.querySelectorAll(".b-table__status-tip")) {
        if (!asPending) tip.remove();
        else if (t.payoutPendingDays == null) tip.removeAttribute("aria-label");
        else tip.setAttribute("aria-label", `Earning will become available in ${t.payoutPendingDays} days`);
      }
    }
    return el;
  });
  intoTable(doc, body, rows, clones);
  if (more) applyMore(doc, body, more);
}

/**
 * A `/payouts/requests` or `/payouts/requests/referral` item. Field names and states are OF's own (build 202610091632:
 * statements-payout.js's StatementsPayoutRequestsList and the referrals table's StatePayout read `invoiceId`, `state`,
 * `rejectReason`).
 */
export interface Payout {
  createdAt?: string;
  invoiceId?: string | number | null;
  amount?: number | null;
  /** `approved`: processed; `new` or `pending`: pending; `rejected`: returned, with its `rejectReason`. */
  state?: string;
  rejectReason?: string | null;
}

/**
 * Statements' Payouts (its own rows, `tpl` absent) or Referrals (`tpl`: the Payouts tab's approved row, borrowed, with
 * the rejected row beside it in its capture): one copy per payout, in order, before the table's loading row (Referrals:
 * at its end, its "This list is empty" row hidden while rows show). Its date, time, invoice and amount (none: empty);
 * an approved payout is the row "Payout has been processed", a rejected one the rejected row with its "Reason:" line
 * the payout's reason (none: no line), a new or pending one OF's pending mark (its loading icon: OF's wording for it
 * was never captured), any other state an empty status cell, as OF's getDescription.
 */
export function applyPayouts(doc: Document, items: Payout[], tpl?: Element) {
  const body = doc.querySelector(".b-table tbody");
  if (!body) return;
  const trs = [...body.querySelectorAll<HTMLElement>(":scope > tr")];
  const own = trs.filter((r) => r.querySelector(".b-table__date"));
  const pool = tpl ? [...(tpl.parentElement?.children ?? [tpl])] : own;
  const row = (state: string) => {
    const r = pool.find((p) => p.querySelector(".b-table__date") && p.querySelector(`.b-table__desc > span.${state}`));
    return r && tpl ? doc.importNode(r, true) : r;
  };
  const approved = row("approved");
  const rejected = row("rejected");
  if (!approved || !rejected) return;
  const clones = items.map((p) => {
    const el = make(p.state === "rejected" ? rejected : approved);
    setCells(el, p.createdAt, [
      [".b-table__invoice", p.invoiceId == null || p.invoiceId === "" ? "" : ` ${p.invoiceId} `],
      [".b-table__amount strong > span", dollars(p.amount)],
    ]);
    const desc = el.querySelector(".b-table__desc");
    if (p.state === "rejected") {
      const br = desc?.querySelector(":scope > span.rejected > br");
      const line = br?.nextSibling?.nodeType === 3 ? br.nextSibling : null; // "Reason: …"
      const reason = plain(p.rejectReason);
      if (line && reason) line.textContent = `Reason: ${reason}`;
      else {
        line?.remove();
        br?.remove();
      }
    } else if (p.state === "new" || p.state === "pending") {
      const mark = desc?.querySelector(":scope > span.approved");
      if (mark) {
        mark.className = "pending";
        for (const n of [...mark.childNodes]) if (n.nodeType === 3) n.remove();
        mark.querySelector("use")?.setAttribute("href", "#icon-loading");
      }
    } else if (p.state !== "approved") desc?.replaceChildren();
    return el;
  });
  intoTable(doc, body, own, clones);
}

/** A `/users/{id}/streams` item: a past live stream. */
export interface PastStream {
  id?: number | string;
  media?: { files?: { thumb?: { url?: string | null } } } | null;
  viewsCount?: number | null;
  startedAt?: string;
}

/**
 * Streaming's dashboard, "Past live streams": one thumb per stream with media (as OF lists them), in OF's markup: its
 * thumb picture (none: no picture), "View stats" (disabled with the tooltip), "Viewers: n" and the start date with its hover
 * stamp. With a thumb, the page and the list lose OF's empty-list centring; an empty list keeps the capture.
 */
export function applyPastStreams(doc: Document, streams: PastStream[], img: (u: string) => string) {
  const thumbs = doc.querySelector(".b-s-dashboard__thumbs");
  const shown = streams.filter((s) => s.media);
  if (!thumbs || !shown.length) return;
  const scope = [...thumbs.attributes].filter((a) => a.name.startsWith("data-v-"));
  const built = (tag: string, cls: string, parent?: Element, text?: string) => {
    const el = doc.createElement(tag);
    for (const a of scope) el.setAttribute(a.name, a.value);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    parent?.appendChild(el);
    return el;
  };
  const clones = shown.map((s) => {
    const holder = built("div", "b-s-dashboard__thumb-holder g-position-relative");
    holder.dataset.oiData = "";
    const preview = built("div", "b-s-dashboard__thumb-holder_preview m-default-bg", holder);
    const thumb = s.media?.files?.thumb?.url;
    if (thumb) built("img", "", preview).setAttribute("src", img(thumb));
    // OF's stats modal was never captured: View stats is disabled with the tooltip.
    const stats = built("button", "g-btn m-rounded", built("div", "b-s-dashboard__btn w-100 text-center", preview), " View stats ");
    stats.setAttribute("type", "button");
    stats.setAttribute("disabled", "disabled");
    stats.setAttribute("title", NOT_YET);
    const content = built("div", "b-s-dashboard__thumb-content g-md-text", holder);
    built("span", "b-viewers-counter", built("div", "b-s-dashboard__thumb-content__viewers", content, " Viewers: "), String(s.viewsCount ?? 0));
    const time = built("div", "b-s-dashboard__thumb-content__time", content);
    const at = valid(s.startedAt);
    if (at) built("span", "", time, ` ${dayOf(at)} `).setAttribute("title", stamp(at));
    return holder;
  });
  fill(doc, [], clones, [thumbs]);
  const page = thumbs.closest(".g-sides-gaps");
  if (page) dropClass(doc, page, "d-flex", "flex-column");
  const loader = thumbs.parentElement?.querySelector(":scope > .infinite-loading-container");
  if (loader) dropClass(doc, loader, "mt-auto", "mb-auto");
}
