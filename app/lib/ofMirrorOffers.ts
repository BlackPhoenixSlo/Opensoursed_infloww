"use client";


import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { plain } from "@/lib/ofMirrorData";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { mirrorKey } from "@/lib/ofMirrorKeys";
import { showMenu, ORDER_GROUP, type MenuOption } from "@/lib/ofMirrorMenu";
import { toast } from "@/lib/ofMirrorPost";
import { message, note, SELECT_MODEL } from "@/lib/ofMirrorWrites";


export type Audience = "new" | "expired" | "both";
export type PromoKind = "trial" | "discount";
export interface PromotionForm {
  audience: Audience;
  kind: PromoKind;
  limit: number;
  expiration: number;
  duration: number;
  percent: number;
  message: string;
}
export interface PromotionBody {
  discount: number;
  subscribe_counts: number;
  subscribe_days: number;
  finish_days: number;
  message: string;
  type: ("all" | "expired")[];
}

export const PROMOTION_DEFAULTS: PromotionForm = { audience: "new", kind: "trial", limit: 10, expiration: 7, duration: 7, percent: 5, message: "" };
const MIN_DISCOUNT = 5;
const MIN_SUBSCRIPTION_PRICE = 3;

export function promotionBody(f: PromotionForm): PromotionBody {
  const trial = f.kind === "trial";
  return {
    discount: trial ? 100 : f.percent,
    subscribe_counts: f.limit,
    subscribe_days: trial ? f.duration : f.expiration,
    finish_days: f.expiration,
    message: f.message,
    type: [...(f.audience !== "expired" ? (["all"] as const) : []), ...(f.audience !== "new" ? (["expired"] as const) : [])],
  };
}

export interface TrialForm {
  name: string;
  limit: number;
  expiration: number;
  duration: number;
}
export interface TrialBody {
  name: string;
  subscribe_counts: number;
  expire_days: number;
  subscribe_days: number;
}
export const TRIAL_DEFAULTS: TrialForm = { name: "", limit: 10, expiration: 7, duration: 7 };
export const trialBody = (f: TrialForm): TrialBody => ({ name: f.name.replace(/^ +/, ""), subscribe_counts: f.limit, expire_days: f.expiration, subscribe_days: f.duration });

export interface BundleForm {
  discount: number;
  duration: number;
}
export const bundleBody = (f: BundleForm) => ({ discount: f.discount, duration: f.duration });

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;
const range = (from: number, to: number, step = 1) => Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step);
const opts = (values: number[], label: (n: number) => string): MenuOption[] => values.map((v) => ({ value: String(v), label: label(v) }));
const limitLabel = (n: number) => (n ? plural(n, "subscriber") : "No limits");
const expireLabel = (n: number) => (n ? plural(n, "day") : "No expiration");
export const daysHuman = (n: number) => (n < 30 ? plural(n, "day") : plural(Math.round(n / 30), "month"));

export const PROMO_LIMITS = opts([...range(0, 10), ...range(20, 100, 10)], limitLabel);
export const EXPIRATIONS = opts(range(0, 30), expireLabel);
export const PROMO_DURATIONS = opts(range(1, 30), (n) => plural(n, "day"));
export const TRIAL_LIMITS = opts([...range(0, 10), 50, 100], limitLabel);
export const TRIAL_DURATIONS = opts([1, 3, 7, 14, 30, 90, 180, 360], daysHuman);

export function discountOptions(price: number): MenuOption[] {
  const max = price > 0 ? Math.min(Math.floor((100 * (price - MIN_SUBSCRIPTION_PRICE)) / price), 100) : 0;
  return opts(range(MIN_DISCOUNT, Math.min(max, 95), 5), (n) => `${n}% discount`);
}
export const discountDisabled = (price: number) => (price * (100 - MIN_DISCOUNT)) / 100 < MIN_SUBSCRIPTION_PRICE;

const money = (n: number) => (n ? n.toFixed(2).replace(".00", "") : n.toFixed(2));

export function promotionDesc(f: PromotionForm, price: number): string {
  const discount = f.kind === "trial" ? 100 : f.percent;
  const amount = money((price * (100 - discount)) / 100);
  if (f.kind === "discount") return `Promotional subscription $${amount} for 1 month.`;
  const days = plural(f.duration, "day");
  return `Promotional subscription $${amount} for ${days}.\n User will not be subscribed for $${money(price)} automatically, only by choice`;
}

interface MePromotion {
  type?: string;
  canClaim?: boolean;
}
// Only the "new subscribers" wording was captured; the other two are assumed.
export function replaceText(audience: Audience, promotions: MePromotion[]): string {
  const all = promotions.find((p) => p.type === "all");
  const expired = promotions.find((p) => p.type === "expired");
  const toNew = audience !== "expired";
  const toExpired = audience !== "new";
  if (expired?.canClaim && all?.canClaim) return "This campaign will replace your current promotions for new and expired subscribers.";
  if (!expired?.canClaim || (toNew && !toExpired)) {
    return !all?.canClaim || (toExpired && !toNew) ? "" : "This campaign will replace you current promotion for new subscribers.";
  }
  return "This campaign will replace your current promotion for expired subscribers.";
}

export interface BundleSettings {
  canAddSubscriberByBundle?: false | { discounts?: Record<string, string>; durations?: Record<string, string> } | null;
  bundleMaxPrice?: number | null;
}
export function bundleOptions(settings: BundleSettings | undefined, existing: number[]): { discounts: MenuOption[]; durations: MenuOption[] } {
  const c = settings?.canAddSubscriberByBundle || {};
  const list = (o: Record<string, string> | undefined) => Object.entries(o ?? {}).map(([value, label]) => ({ value: String(Number(value)), label }));
  return { discounts: list(c.discounts), durations: list(c.durations).filter((d) => !existing.includes(Number(d.value))) };
}
export const NO_BUNDLES_LEFT = "OnlyFans offers no more subscription bundles for this page";
export const bundleAmount = (f: BundleForm, price: number) => Math.round(f.duration * price * (100 - f.discount)) / 100;
export function bundleBlock(o: { noModel?: boolean; settings: BundleSettings | undefined; discounts: MenuOption[]; durations: MenuOption[]; amount: number }): string {
  const max = Number(o.settings?.bundleMaxPrice ?? 0);
  if (o.noModel) return SELECT_MODEL;
  if (!o.settings) return "Loading OnlyFans' bundle options";
  if (!o.discounts.length || !o.durations.length) return NO_BUNDLES_LEFT;
  if (max && o.amount > max) return `Maximum bundle price is $${max}`;
  return "";
}
export const bundleHelp = (amount: number, durationLabel: string) => `Promotional subscription $${amount.toFixed(2)} for ${durationLabel}.`;


const FORM_STATE = "data-oi-offer";
export const PROMOTION_MODAL = "settings/subscription/promotion-campaign/modal-1";
export const BUNDLE_MODAL = "settings/subscription/promotion-campaign/modal-2";
export const TRIAL_MODAL = "settings/subscription/trial-links/modal-1";
export const NEW_POST_PROMOTION = "new-post/state-promotion";
export const NEW_POST_TRIAL = "new-post/state-trial-link";
export const HOME_PROMOTION = "home/state-promotion";
const TRIAL_PAGE = "settings/subscription/trial-links";
export const AFTER_NEW_POST_PROMOTION = "/of-manager/settings/subscription#promotion";
export const AFTER_NEW_POST_TRIAL = "/of-manager/settings/subscription/trial-links";

export function scrollToHash(doc: Document, hash: string): boolean {
  if (!/^#[a-zA-Z_][a-zA-Z0-9_-]*$/.test(hash)) return false;
  const el = doc.getElementById(hash.slice(1));
  el?.scrollIntoView({ behavior: "smooth", block: "start" });
  return !!el;
}

const formOf = (doc: Document) => doc.querySelector<HTMLFormElement>(".modal.show form") ?? doc.querySelector<HTMLElement>(".modal.show .modal-body");
function readState<T>(doc: Document): T | null {
  const raw = formOf(doc)?.getAttribute(FORM_STATE);
  try {
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
const writeState = (doc: Document, state: object) => formOf(doc)?.setAttribute(FORM_STATE, JSON.stringify(state));

export function collectPromotion(doc: Document): PromotionBody | string {
  const f = readState<PromotionForm>(doc);
  return f ? promotionBody(f) : "The campaign form is not ready";
}
export function collectTrial(doc: Document): TrialBody | string {
  const f = readState<TrialForm>(doc);
  if (!f) return "The link form is not ready";
  const name = doc.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']")?.value ?? f.name;
  return trialBody({ ...f, name });
}
export function collectBundle(doc: Document): BundleForm | string {
  const f = readState<BundleForm & { why?: string }>(doc);
  if (!f) return "The bundle form is not ready";
  if (f.why) return f.why;
  return bundleBody(f);
}

const selects = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".modal.show .v-input.v-select")];

function setSelect(sel: HTMLElement, label: string | null, text: string, value: string) {
  const l = sel.querySelector(".v-label");
  if (l && label !== null) l.textContent = label;
  const shown = sel.querySelector(".v-select__selection");
  if (shown) shown.textContent = text;
  const hidden = sel.querySelector<HTMLInputElement>("input[type='hidden']");
  if (hidden) hidden.value = value;
  sel.classList.remove("v-input--is-disabled");
  sel.removeAttribute("title");
  for (const el of sel.querySelectorAll("input, .v-input__slot")) el.setAttribute("data-oi-wired", "");
  sel.querySelector(".v-input__slot")?.setAttribute("role", "button");
}

interface SelectSpec {
  label: string | null;
  options: MenuOption[];
  value: number;
  pick(value: number): void;
}

function bindDialog<T extends object>(
  doc: Document,
  initial: T,
  render: (state: T, set: (patch: Partial<T>) => void) => SelectSpec[],
  extra?: (ev: MouseEvent, state: T, set: (patch: Partial<T>) => void) => boolean,
): () => void {
  let state = initial;
  let specs: SelectSpec[] = [];
  const set = (patch: Partial<T>) => {
    state = { ...state, ...patch };
    draw();
  };
  const draw = () => {
    writeState(doc, state);
    specs = render(state, set);
    selects(doc).forEach((sel, i) => {
      const s = specs[i];
      if (!s) return;
      const o = s.options.find((x) => Number(x.value) === s.value);
      setSelect(sel, s.label, o?.label ?? "", String(s.value));
    });
  };
  draw();
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (extra?.(ev, state, set)) return;
    const sel = t.closest<HTMLElement>(".modal.show .v-input.v-select");
    if (!sel) return;
    const s = specs[selects(doc).indexOf(sel)];
    if (!s) return;
    ev.preventDefault();
    showMenu(doc, sel, [{ name: "v", options: s.options, value: String(s.value), radio: false }], (_, v) => s.pick(Number(v)));
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

export function current(tab: Element | null, on: boolean) {
  tab?.classList.toggle("m-current", on);
  tab?.classList.toggle("m-no-pointer", on);
  tab?.setAttribute("data-oi-wired", "");
}

function countText(area: HTMLTextAreaElement) {
  const c = area.closest(".v-input")?.querySelector(".v-counter");
  if (c) c.textContent = `${[...area.value].length} / ${area.maxLength > 0 ? area.maxLength : 500}`;
  area.closest(".g-input__wrapper")?.classList.toggle("m-empty", !area.value);
}

const AUDIENCE_TABS: Record<Audience, string> = { new: "New subscribers", expired: "Expired subscribers", both: "Both new and expired" };
const KIND_TABS: Record<PromoKind, string> = { trial: "Free trial", discount: "First month discount" };
const tabText = (tab: Element) => tab.textContent?.trim() ?? "";
const tabOf = (doc: Document, text: string) =>
  [...doc.querySelectorAll<HTMLButtonElement>(".modal.show .b-tabs__nav__link")].find((t) => tabText(t) === text) ?? null;

export function bindPromotionDialog(doc: Document, me: OfMe | undefined): () => void {
  const price = Number(me?.subscribePrice ?? 0);
  const promotions = ((me as { promotions?: MePromotion[] } | undefined)?.promotions ?? []).filter(Boolean);
  const noDiscount = discountDisabled(price);
  const discountTab = tabOf(doc, KIND_TABS.discount);
  if (discountTab && noDiscount) {
    discountTab.disabled = true;
    discountTab.title = `The discount must leave at least $${MIN_SUBSCRIPTION_PRICE} per month`;
  }
  const replace = doc.querySelector<HTMLElement>(".modal.show p.g-input__help.m-mt-12");
  const desc = [...doc.querySelectorAll<HTMLElement>(".modal.show p.g-input__help")].find((p) => p !== replace) ?? null;
  const area = doc.querySelector<HTMLTextAreaElement>(".modal.show textarea");
  area?.setAttribute("data-oi-wired", "");
  const percents = discountOptions(price);
  const initial: PromotionForm = { ...PROMOTION_DEFAULTS, percent: Number(percents[0]?.value ?? MIN_DISCOUNT) };
  const unbind = bindDialog<PromotionForm>(
    doc,
    initial,
    (f, set) => {
      for (const [a, text] of Object.entries(AUDIENCE_TABS)) current(tabOf(doc, text), a === f.audience);
      for (const [k, text] of Object.entries(KIND_TABS)) current(tabOf(doc, text), k === f.kind);
      if (replace) {
        const text = replaceText(f.audience, promotions);
        replace.textContent = ` ${text} `;
        replace.style.display = text ? "" : "none";
      }
      if (desc) {
        const [first, second] = promotionDesc(f, price).split("\n");
        desc.replaceChildren(first, ...(second ? [doc.createElement("br"), second] : []));
      }
      return [
        { label: "Offer limit", options: PROMO_LIMITS, value: f.limit, pick: (limit) => set({ limit }) },
        { label: "Offer expiration", options: EXPIRATIONS, value: f.expiration, pick: (expiration) => set({ expiration }) },
        f.kind === "trial"
          ? { label: "Free trial duration", options: PROMO_DURATIONS, value: f.duration, pick: (duration) => set({ duration }) }
          : { label: "Discount percent", options: percents, value: f.percent, pick: (percent) => set({ percent }) },
      ];
    },
    (ev, _f, set) => {
      const tab = (ev.target as Element).closest<HTMLButtonElement>(".modal.show .b-tabs__nav__link");
      if (!tab) return false;
      ev.preventDefault();
      const audience = (Object.entries(AUDIENCE_TABS).find(([, t]) => tabText(tab) === t)?.[0] ?? null) as Audience | null;
      const kind = (Object.entries(KIND_TABS).find(([, t]) => tabText(tab) === t)?.[0] ?? null) as PromoKind | null;
      if (audience) set({ audience });
      else if (kind && !(kind === "discount" && noDiscount)) set({ kind });
      return true;
    },
  );
  const onInput = (ev: Event) => {
    if (!area || ev.target !== area) return;
    countText(area);
    const f = readState<PromotionForm>(doc);
    if (f) writeState(doc, { ...f, message: area.value });
  };
  doc.addEventListener("input", onInput);
  return () => {
    unbind();
    doc.removeEventListener("input", onInput);
  };
}

export function bindTrialDialog(doc: Document, me: OfMe | undefined): () => void {
  const price = Number(me?.subscribePrice ?? 0);
  const desc = doc.querySelector<HTMLElement>(".modal.show p.g-input__help");
  const name = doc.querySelector<HTMLInputElement>(".modal.show input[at-attr='input']");
  const unbind = bindDialog<TrialForm>(doc, TRIAL_DEFAULTS, (f, set) => {
    if (desc) desc.replaceChildren(`Promotional subscription $0.00 for ${daysHuman(f.duration)}.`, doc.createElement("br"), ` User will not be subscribed for $${money(price)} automatically, only by choice`);
    return [
      { label: null, options: TRIAL_LIMITS, value: f.limit, pick: (limit) => set({ limit }) },
      { label: null, options: EXPIRATIONS, value: f.expiration, pick: (expiration) => set({ expiration }) },
      { label: null, options: TRIAL_DURATIONS, value: f.duration, pick: (duration) => set({ duration }) },
    ];
  });
  const onInput = (ev: Event) => {
    if (!name || ev.target !== name) return;
    const f = readState<TrialForm>(doc);
    if (f) writeState(doc, { ...f, name: name.value });
  };
  doc.addEventListener("input", onInput);
  return () => {
    unbind();
    doc.removeEventListener("input", onInput);
  };
}

export function bindBundleDialog(doc: Document, me: OfMe | undefined, settings: BundleSettings | undefined, noModel = false): () => void {
  const price = Number(me?.subscribePrice ?? 0);
  const existing = ((me as { subscriptionBundles?: { duration?: number }[] } | undefined)?.subscriptionBundles ?? []).map((b) => Number(b.duration));
  const { discounts, durations } = bundleOptions(settings, existing);
  const help = doc.querySelector<HTMLElement>(".modal.show p.g-input__help");
  const save = doc.querySelector<HTMLButtonElement>(".modal.show .modal-footer button");
  const initial = { discount: Number(discounts[0]?.value ?? 0), duration: Number(durations[0]?.value ?? 0) };
  return bindDialog<BundleForm & { why?: string }>(doc, initial, (f, set) => {
    const amount = bundleAmount(f, price);
    const why = bundleBlock({ noModel, settings, discounts, durations, amount });
    if (why !== (f.why ?? "")) writeState(doc, { ...f, why: why || undefined });
    if (help) {
      const duration = durations.find((d) => Number(d.value) === f.duration)?.label ?? "";
      help.textContent = why || ` ${bundleHelp(amount, duration)} `;
      help.classList.toggle("m-danger", !!why);
    }
    if (save) save.disabled = !!why;
    return [
      { label: null, options: discounts, value: f.discount, pick: (discount) => set({ discount }) },
      { label: null, options: durations, value: f.duration, pick: (duration) => set({ duration }) },
    ];
  });
}


export const TRIAL_SORT: MenuOption[] = [
  { value: "create_date", label: "Created" },
  { value: "expire_date", label: "Expires" },
  { value: "subscribe_counts", label: "Limit" },
  { value: "subscribe_days", label: "Duration" },
  { value: "claims_count", label: "Claims count" },
  { value: "clicks_count", label: "Clicks count" },
  { value: "shared", label: "Shared" },
];
export interface TrialView {
  field: string | null;
  sort: string | null;
  tab: "shared" | null;
}
export const trialViewOf = (params: { get(k: string): string | null }): TrialView => {
  const field = params.get("field");
  return {
    field: field && TRIAL_SORT.some((o) => o.value === field) && field !== "create_date" ? field : null,
    sort: params.get("sort") === "asc" ? "asc" : null,
    tab: params.get("tab") === "shared" ? "shared" : null,
  };
};
export function trialsRoute(view: TrialView): string {
  if (view.tab === "shared") return "/api/of/v2/trials/share-access";
  if (!view.field && !view.sort) return "/api/of/v2/trials";
  return `/api/of/v2/trials?field=${view.field ?? "create_date"}&sort=${view.sort ?? "desc"}`;
}
export const trialHref = (view: TrialView) => {
  const q = new URLSearchParams();
  if (view.field) q.set("field", view.field);
  if (view.sort) q.set("sort", view.sort);
  if (view.tab) q.set("tab", view.tab);
  const s = q.toString();
  return `/of-manager/${TRIAL_PAGE}${s ? `?${s}` : ""}`;
};
export const trialPick = (view: TrialView, group: string, value: string): TrialView =>
  group === "field" ? { ...view, field: value === "create_date" ? null : value } : { ...view, sort: value === "asc" ? "asc" : null };

export interface Performer {
  id: number;
  name?: string | null;
  username?: string | null;
}

export interface OfferHandlers {
  navigate(href: string): void;
  finish(id: string): Promise<unknown>;
  copy(text: string): Promise<void>;
  confirm(text: string): boolean;
  searchPerformers(query: string): Promise<Performer[]>;
  share(body: { trial_id: number; user_id: number }): Promise<unknown>;
}

function bindTrialPage(doc: Document, view: TrialView, handlers: OfferHandlers | null): () => void {
  const sortBtn = doc.querySelector<HTMLButtonElement>(".trial-sorting-dropdown button[aria-label='Sort'], button[aria-label='Sort']");
  sortBtn?.setAttribute("data-oi-wired", "");
  const title = doc.querySelector(".b-content-filter__title");
  if (title) title.textContent = view.field ? (TRIAL_SORT.find((o) => o.value === view.field)?.label ?? "Recent") : "Recent";
  for (const r of doc.querySelectorAll<HTMLInputElement>("input[name='trial-filter-field'], input[name='trial-order-dir']")) {
    const group = r.name === "trial-filter-field" ? "field" : "order";
    const on = r.value === (group === "field" ? (view.field ?? "create_date") : (view.sort ?? "desc"));
    r.checked = on;
    r.toggleAttribute("checked", on);
    r.disabled = false;
    r.setAttribute("data-oi-wired", "");
    r.closest("[role='menuitem']")?.querySelector("a.of-state-link")?.setAttribute("href", trialHref(trialPick(view, group, r.value)));
  }
  doc.querySelector(".trial-sorting-dropdown > a.of-state-link[aria-label='Toggle']")?.setAttribute("href", trialHref(view));
  const yours = doc.querySelector<HTMLElement>("#Your-links");
  const shared = doc.querySelector<HTMLElement>("#Shared-with-you");
  current(yours, view.tab !== "shared");
  current(shared, view.tab === "shared");
  if (yours) yours.setAttribute("role", "button");
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (sortBtn && t.closest("button[aria-label='Sort']") === sortBtn) {
      ev.preventDefault();
      if (!handlers) return note(doc, sortBtn, SELECT_MODEL);
      showMenu(doc, sortBtn, [{ name: "field", options: TRIAL_SORT, value: view.field ?? "create_date" }, ORDER_GROUP(view.sort)], (group, value) => handlers?.navigate(trialHref(trialPick(view, group, value))));
      return;
    }
    const tab = t.closest("#Your-links, #Shared-with-you");
    if (tab) {
      ev.preventDefault();
      const want = tab.id === "Shared-with-you" ? "shared" : null;
      if (!handlers) return note(doc, tab, SELECT_MODEL);
      if (want !== view.tab) handlers.navigate(trialHref({ ...view, tab: want }));
      return;
    }
    const share = t.closest<HTMLElement>("[data-oi-share]");
    if (share) {
      ev.preventDefault();
      const id = Number(share.closest<HTMLElement>("[data-oi-trial]")?.dataset.oiTrial);
      if (!handlers) return note(doc, share, SELECT_MODEL);
      if (id) shareDialog(doc, id, handlers);
    }
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

export function shareDialog(doc: Document, trialId: number, handlers: Pick<OfferHandlers, "searchPerformers" | "share">): HTMLElement {
  return shareStatsDialog(doc, { searchPerformers: handlers.searchPerformers, send: (userId) => handlers.share({ trial_id: trialId, user_id: userId }) });
}

export function shareStatsDialog(
  doc: Document,
  handlers: { searchPerformers(query: string): Promise<Performer[]>; send(userId: number): Promise<unknown> },
): HTMLElement {
  doc.getElementById("oi-share")?.remove();
  const root = doc.createElement("div");
  root.id = "oi-share";
  root.setAttribute("data-oi-wired", "");
  root.innerHTML =
    '<div class="modal fade show" role="dialog" aria-modal="true" style="display:block;z-index:1050">' +
    '<div class="modal-dialog modal-sm modal-dialog-centered"><div class="modal-content">' +
    '<header class="modal-header"><h4 class="modal-title"> SHARE LINK\'S STATISTICS </h4></header>' +
    '<div class="modal-body"><div class="v-input form-control g-input mb-0 v-input--hide-details theme--light v-text-field v-text-field--outlined">' +
    '<div class="v-input__control"><div class="v-input__slot"><div class="v-text-field__slot">' +
    '<input type="text" maxlength="100" autocomplete="off" placeholder="Enter username..." aria-label="Username" data-oi-wired="" style="width:100%;padding:8px 0">' +
    '</div></div></div></div><div class="oi-share-results b-rows-lists" style="max-height:240px;overflow:auto"></div></div>' +
    '<div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired="" data-oi-cancel=""> Cancel </button>' +
    '<button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired="" data-oi-send="" disabled> Share </button></div>' +
    "</div></div></div><div class=\"modal-backdrop fade show\" data-oi-cancel=\"\" style=\"z-index:1040\"></div>";
  doc.body.append(root);
  const input = root.querySelector<HTMLInputElement>("input")!;
  const results = root.querySelector<HTMLElement>(".oi-share-results")!;
  const send = root.querySelector<HTMLButtonElement>("[data-oi-send]")!;
  let picked: Performer | null = null;
  let timer = 0;
  let asked = "";
  const win = doc.defaultView;
  const close = () => root.remove();
  const draw = (rows: Performer[]) => {
    results.replaceChildren(
      ...rows.map((p) => {
        const row = doc.createElement("div");
        row.className = "b-rows-lists__item m-with-rectangle-hover";
        row.style.cssText = "padding:8px 16px;cursor:pointer";
        row.setAttribute("role", "button");
        row.setAttribute("data-oi-wired", "");
        row.dataset.oiPerformer = String(p.id);
        // OF's names come HTML-escaped.
        row.textContent = `${plain(p.name)}${p.username ? ` @${p.username}` : ""}`.trim();
        return row;
      }),
    );
    (results as HTMLElement & { _rows?: Performer[] })._rows = rows;
  };
  input.addEventListener("input", () => {
    picked = null;
    send.disabled = true;
    win?.clearTimeout(timer);
    const q = input.value.trim().replace(/^@/, "");
    if (!q) return draw([]);
    timer = win?.setTimeout(() => {
      asked = q;
      handlers.searchPerformers(q).then(
        (rows) => {
          if (asked === q) draw(rows);
        },
        (e) => note(doc, results, `Could not search: ${message(e)}`, true),
      );
    }, 300) ?? 0;
  });
  root.addEventListener("click", (ev) => {
    const t = ev.target as Element;
    if (t.closest("[data-oi-cancel]")) return close();
    const row = t.closest<HTMLElement>("[data-oi-performer]");
    if (row) {
      const rows = (results as HTMLElement & { _rows?: Performer[] })._rows ?? [];
      picked = rows.find((p) => String(p.id) === row.dataset.oiPerformer) ?? null;
      if (picked) {
        input.value = picked.username ? `@${picked.username}` : plain(picked.name);
        send.disabled = false;
        draw([]);
      }
      return;
    }
    if (t.closest("[data-oi-send]") && picked && !send.disabled) {
      send.disabled = true;
      const who = picked;
      handlers.send(who.id).then(
        () => {
          close();
          toast(doc, `Link's statistics shared with ${who.username ? `@${who.username}` : (who.name ?? "")}`);
        },
        (e) => {
          send.disabled = false;
          note(doc, send, `Could not share: ${message(e)}`, true);
        },
      );
    }
  });
  input.focus();
  return root;
}


function bindPromotionCards(doc: Document, handlers: OfferHandlers | null): () => void {
  const onClick = (ev: MouseEvent) => {
    const b = (ev.target as Element | null)?.closest?.<HTMLButtonElement>("button[data-oi-finish], button[data-oi-copy]");
    if (!b) return;
    ev.preventDefault();
    if (!handlers) return note(doc, b, SELECT_MODEL);
    const copy = b.getAttribute("data-oi-copy");
    if (copy !== null) {
      handlers.copy(copy).then(
        () => void toast(doc, "Link copied"),
        () => note(doc, b, "Could not copy the link", true),
      );
      return;
    }
    const id = b.getAttribute("data-oi-finish") ?? "";
    if (b.disabled || !id || !handlers.confirm("Stop this promotion?")) return;
    b.disabled = true;
    handlers.finish(id).then(
      () => void toast(doc, "Promotion stopped"),
      (e) => {
        b.disabled = false;
        note(doc, b, `Could not stop: ${message(e)}`, true);
      },
    );
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

const PROMOTION_TILE = "Start profile promotion";
const TRIAL_TILE = "Create new trial link";

export function applyOfferTiles(doc: Document, me: OfMe | undefined, page: string): void {
  const dialog = page.startsWith("home/") ? HOME_PROMOTION : NEW_POST_PROMOTION;
  const flags = (me ?? {}) as { canCreatePromotion?: boolean; canCreateTrial?: boolean; promotions?: MePromotion[] | null };
  const claimable = (flags.promotions ?? []).some((p) => p?.type === "all" && p.canClaim);
  for (const tile of doc.querySelectorAll<HTMLElement>(".b-story-item.m-create")) {
    const text = tile.querySelector(".b-story-item__text")?.textContent?.trim();
    const off = text === PROMOTION_TILE ? flags.canCreatePromotion === false : text === TRIAL_TILE ? flags.canCreateTrial === false : null;
    if (off === null) continue;
    tile.style.display = off ? "none" : "";
    if (text === PROMOTION_TILE && tile instanceof HTMLAnchorElement) tile.href = claimable ? AFTER_NEW_POST_PROMOTION : `/of-manager/${dialog}`;
  }
}

export function bindOffers(
  doc: Document,
  page: string,
  ctx: { me?: OfMe; settings?: BundleSettings; trialView: TrialView; handlers: OfferHandlers | null },
): () => void {
  const unbinds = [bindPromotionCards(doc, ctx.handlers)];
  if (page.startsWith("new-post/") || page.startsWith("home/")) applyOfferTiles(doc, ctx.me, page);
  if (page === PROMOTION_MODAL || page === NEW_POST_PROMOTION || page === HOME_PROMOTION) unbinds.push(bindPromotionDialog(doc, ctx.me));
  if (page === BUNDLE_MODAL) unbinds.push(bindBundleDialog(doc, ctx.me, ctx.settings, !ctx.handlers));
  if (page === TRIAL_MODAL || page === NEW_POST_TRIAL) unbinds.push(bindTrialDialog(doc, ctx.me));
  if (page === TRIAL_PAGE || page.startsWith(`${TRIAL_PAGE}/`)) unbinds.push(bindTrialPage(doc, ctx.trialView, ctx.handlers));
  return () => unbinds.forEach((u) => u());
}

export function useOfOffers(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const dialog = [PROMOTION_MODAL, BUNDLE_MODAL, TRIAL_MODAL].includes(page) || page.startsWith("new-post/") || page.startsWith("home/");
  const me = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && dialog }).data;
  const settings = useQuery({
    queryKey: ["of-settings", "settings", accountId],
    queryFn: () => relay.get<BundleSettings>("/api/of/v2/users/me/settings", { accountId }),
    enabled: !!accountId && page === BUNDLE_MODAL,
    staleTime: 5 * 60 * 1000,
    retry: false,
  }).data;
  const trialView = trialViewOf(params);
  const viewKey = JSON.stringify(trialView);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    const handlers: OfferHandlers | null = accountId
      ? {
          navigate: (href) => router.push(href),
          finish: (id) =>
            relay.post(`/api/of/v2/promotions/${id}/finish`, {}, { accountId }).then((r) => {
              qc.invalidateQueries({ queryKey: ["of-settings", "subscription"] });
              qc.invalidateQueries({ queryKey: mirrorKey(accountId) });
              qc.invalidateQueries({ queryKey: ["of-me", accountId] });
              return r;
            }),
          copy: (t) => frame.contentWindow?.navigator.clipboard?.writeText(t) ?? Promise.reject(new Error("no clipboard")),
          confirm: (t) => frame.contentWindow?.confirm(t) ?? false,
          searchPerformers: (q) =>
            relay.get<Performer[] | { list?: Performer[] }>(`/api/of/v2/users/performers-search?query=${encodeURIComponent(q)}&limit=10`, { accountId }).then((r) => (Array.isArray(r) ? r : (r?.list ?? []))),
          share: (body) => relay.post("/api/of/v2/trials/share-access", body, { accountId }).then((r) => {
            qc.invalidateQueries({ queryKey: ["of-settings", "subscription"] });
            return r;
          }),
        }
      : null;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindOffers(doc, page, { me, settings, trialView: JSON.parse(viewKey) as TrialView, handlers }) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, accountId, router, qc, me, settings, viewKey]);
}

export const CLAIMS_TO_LIST = {
  source: "inferred",
  write(listId: number, kind: "promo" | "trial", claimId: number): { method: "POST"; path: string } {
    return { method: "POST", path: `/api/of/v2/lists/${positive(listId)}/users/${kind}/${positive(claimId)}/claims` };
  },
  // One DELETE per added user: OF's bulk DELETE /lists/{id}/users clears the whole list.
  undo(listId: number, addedUsers: readonly number[]): { method: "DELETE"; path: string }[] {
    const list = positive(listId);
    return [...new Set(addedUsers)].map((u) => ({ method: "DELETE", path: `/api/of/v2/lists/${list}/users/${positive(u)}` }));
  },
} as const;

function positive(n: number): number {
  if (!Number.isSafeInteger(n) || n < 1) throw new RangeError(`not an OnlyFans id: ${n}`);
  return n;
}
