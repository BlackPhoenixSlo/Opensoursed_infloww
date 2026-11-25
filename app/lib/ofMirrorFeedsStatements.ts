"use client";


import { NOT_YET } from "@/lib/ofMirrorWrites";
import { applyMore, clock, dayOf, dropClass, fill, make, plain, stamp, track, valid, type MorePages } from "@/lib/ofMirrorDom";
import { fullDay, wallClock } from "@/lib/ofMirrorFeedsShared";

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

export interface Transaction {
  createdAt?: string;
  amount?: number | null;
  fee?: number | null;
  net?: number | null;
  currency?: string | null;
  description?: string | null;
  status?: string;
  payoutPendingDays?: number | null;
  user?: { isDeleted?: boolean | null; isActive?: boolean | null } | null;
}

export function ofMoney(v: number, currency?: string | null): string {
  const figure = v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const code = (currency || "usd").toLowerCase();
  const symbol = ({ usd: "$", eur: "€", gbp: "£" } as Record<string, string>)[code];
  return symbol ? `${symbol}${figure}` : `${figure} ${code.toUpperCase()}`;
}

function moneyCell(span: Element | null, v: number | null | undefined, currency?: string | null) {
  if (!span) return;
  const n = typeof v === "number" && Number.isFinite(v) ? v : null;
  span.textContent = n === null ? "" : ` ${ofMoney(n, currency)} `;
  span.classList.toggle("m-zero-value", n !== null && Math.round(n) === 0);
  if (!span.getAttribute("class")) span.setAttribute("class", "");
}

export function zoneNote(zone?: string | null, now: Date = new Date()): string {
  const at = new Date(Math.floor(now.getTime() / 60_000) * 60_000);
  const mins = -at.getTimezoneOffset() + Math.round((wallClock(at, zone ?? undefined).getTime() - at.getTime()) / 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `UTC ${mins < 0 ? "-" : "+"}${pad(Math.floor(Math.abs(mins) / 60))}:${pad(Math.abs(mins) % 60)}`;
}

const dollars = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? ` $${v.toFixed(2)} ` : "");

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

export function applyTransactions(doc: Document, items: Transaction[], zone?: string, more?: MorePages) {
  const rows = [...doc.querySelectorAll<HTMLElement>(".b-table tbody > tr")].filter((r) => r.querySelector(".b-table__date"));
  const row = (icon: string) => rows.find((r) => r.querySelector(`.b-table__status svg[data-icon-name='${icon}']`));
  const done = row("icon-done");
  const pending = row("icon-loading");
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

export interface Payout {
  createdAt?: string;
  invoiceId?: string | number | null;
  amount?: number | null;
  state?: string;
  rejectReason?: string | null;
}

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
      const line = br?.nextSibling?.nodeType === 3 ? br.nextSibling : null;
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

export interface PastStream {
  id?: number | string;
  media?: { files?: { thumb?: { url?: string | null } } } | null;
  viewsCount?: number | null;
  startedAt?: string;
}

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
