"use client";

/**
 * The real rows of the OF mirror's Subscription settings pages (settings/subscription*), with a single model selected.
 * The generator leaves one hidden example of each row (data-oi-template); this fills a copy per Relay row, drawn as OF's
 * own settings components draw them (build 202610091632: settings-promotion-campaign.js, settings-tracking-links.js,
 * settings-trial-links.js):
 * - Profile promotion campaign: `/users/me`'s promotions, as OF's settings list reads them (user.promotions, sorted by
 *   type, only the first when several are related; OF's `/promotions` also lists ended ones the page does not show) (title promotionTitle, who it is for, "ended/ends <day>" from finishedAt,
 *   "left <subscribeCounts>", the message in the Creator's bubble, Started from createdAt, Claims count). A promotion on
 *   offer keeps Stop promotion (ofMirrorOffers: POST /promotions/{id}/finish) and Copy link to profile; an ended one is gray
 *   with Remove (DELETE /promotions/{id}, no confirm, as on OF).
 * - Subscription bundles: `/users/me`'s subscriptionBundles, as OF's own list reads them (authUser.subscriptionBundles;
 *   /subscriptions/bundles answers [] for a model that has two) ("$<price> USD total for <duration> months",
 *   "-<discount>%"); its Delete asks first, then DELETE /subscriptions/bundles/{id}. With no price (free) OF grays both
 *   section headers (m-disabled-block; promotions also without canCreatePromotion) and each bundle (g-disabled).
 *   A failed delete keeps the row and shows OF's own error message in OF's toast.
 * - OF's create buttons, disabled as OF disables them (the house tooltip; OF gives no reason): Start promotion campaign
 *   (no price, not a performer, !canCreatePromotion or !canEarn), Add bundle (OF's isAddBundleDisabled: no price, or
 *   every duration in users/me settings' canAddSubscriberByBundle has a bundle) and Create new free trial link
 *   (!canCreateTrial, which also disables the model's own links' Copy link).
 * - Tracking links: `/campaigns` (campaignName, created, countSubscribers, countTransitions); Delete (Remove once OF
 *   marks it isDeleted) asks first, then DELETE /campaigns/{id}; Copy link copies OF's `https://onlyfans.com/<username>/c<campaignCode>`.
 * - Free trial links: `/trials` (trialLinkName and its length, "- expired", created, offer limit, claims, clicks);
 *   Delete/Remove asks first, then DELETE /trials/{id}; Copy link copies its `url`.
 * A link page's list status is OF's own: the preloader while loading, "No results :(" when empty (and with all models),
 * "Something went wrong." with a working Retry on a Relay error. Rows act in place; the page never navigates.
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { fillSlot, make, plain, setAvatar, valid } from "@/lib/ofMirrorData";
import { onOffer, promotionTitle, type Promotion } from "@/lib/ofMirrorFeeds";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { bundleOptions, NO_BUNDLES_LEFT, trialsRoute, trialViewOf, type BundleSettings } from "@/lib/ofMirrorOffers";
import { toast } from "@/lib/ofMirrorPost";
import { message, note, NOT_YET, ofConfirm, ofErrorMessage, type Ask } from "@/lib/ofMirrorWrites";
import { SUB_ROUTES, type SubPart } from "@/lib/ofSubRoutes";

export interface SubPromotion extends Promotion {
  createdAt?: string | null;
  finishedAt?: string | null;
  /** users/me's: the promotion has a related one (OF then lists only the first). */
  hasRelatedPromo?: boolean;
}
export interface Bundle {
  id?: number | string;
  price?: number | null;
  duration?: number | null;
  discount?: number | null;
}
export interface Campaign {
  id?: number | string;
  campaignCode?: number | string | null;
  campaignName?: string | null;
  countSubscribers?: number | null;
  countTransitions?: number | null;
  createdAt?: string | null;
  isDeleted?: boolean | null;
}
export interface Trial {
  id?: number | string;
  trialLinkName?: string | null;
  url?: string | null;
  subscribeDays?: number | null;
  subscribeCounts?: number | null;
  claimCounts?: number | null;
  clicksCounts?: number | null;
  createdAt?: string | null;
  /** OF's "Link expires" / "Link expired" date. */
  expiredAt?: string | null;
  isFinished?: boolean | null;
  /** The link's owner (another creator's, on Shared with you). */
  user?: { username?: string | null } | null;
  /** Whom the owner shared the link's statistics with. */
  sharedWith?: { username?: string | null } | null;
}

/** One part's state: its rows once read, whether it is still loading, whether the read failed. */
export interface PartState<T> {
  rows?: T[];
  loading?: boolean;
  error?: boolean;
}
export interface SubData {
  promotions?: PartState<SubPromotion>;
  bundles?: PartState<Bundle>;
  campaigns?: PartState<Campaign>;
  trials?: PartState<Trial>;
}

/** The parts the Subscription page at `page` (its path under of-mirror/pages) shows. */
export function subscriptionParts(page: string): SubPart[] {
  if (!/^settings\/subscription(\/|$)/.test(page)) return [];
  if (page.startsWith("settings/subscription/tracking-links")) return ["campaigns"];
  if (page.startsWith("settings/subscription/trial-links")) return ["trials"];
  return ["promotions", "bundles"];
}

/** OF's settings promotion list (settings-promotion-campaign.js `promotions()`): users/me's promotions with an id, sorted
 * by type; only the first when more than one is related (hasRelatedPromo). */
export function mePromotions(me: OfMe | undefined): SubPromotion[] {
  const all = (me?.promotions ?? []) as SubPromotion[];
  if (!Array.isArray(all)) return [];
  const listed = all.filter((p) => p?.hasRelatedPromo).length > 1 ? all.slice(0, 1) : [...all].sort((a, b) => ((a?.type ?? "") > (b?.type ?? "") ? 1 : -1));
  return listed.filter((p) => !!p && p.id != null);
}

/** A bare array, or `{list}` / `{items}`: the rows; anything else: none. */
export function listOf<T>(r: unknown): T[] {
  if (Array.isArray(r)) return r as T[];
  const o = r as { list?: unknown; items?: unknown } | null | undefined;
  if (Array.isArray(o?.list)) return o.list as T[];
  if (Array.isArray(o?.items)) return o.items as T[];
  return [];
}

const longDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const shortDay = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;
/** OF's trial length: "N days" under 30 days, else "N months". */
export const trialLength = (days: number) => (days < 30 ? plural(days, "day") : plural(Math.round(days / 30), "month"));
const PROMO_FOR: Record<string, string> = { new: "For new subscribers", expired: "For expired subscribers", all: "For new and expired subscribers" };
const ZERO_DATE = "0000-00-00 00:00:00";

const OF = "https://onlyfans.com";
/** The tracking link OF's Copy link copies. */
export const campaignLink = (username: string, code: number | string) => `${OF}/${username}/c${code}`;

type Kind = "promotion" | "bundle" | "campaign" | "trial";
/** OF's delete confirms (SettingsBundle, the free trial link's and the tracking link's deleteInteract). */
export const ASKS = {
  bundle: { title: "Delete subscription bundle", text: "Are you sure you want to delete this subscription bundle?", ok: "Delete" },
  campaign: { title: "Delete tracking link", text: "Are you sure you want to delete this tracking link?", ok: "Delete" },
  trial: { title: "Delete free trial link", text: "Are you sure you want to delete this trial link?", ok: "Delete" },
  trialFinished: { title: "Remove free trial link", text: "Are you sure you want to remove this trial link?", ok: "Remove" },
} satisfies Record<string, Ask>;

interface RowAction {
  kind: Kind;
  id: string;
  /** Delete asks this first (null: no confirm, as OF's ended promotion's Remove). */
  ask: Ask | null;
  route: string;
  copy?: string;
}
const actions = new WeakMap<Element, RowAction>();

export interface SubHandlers {
  remove(path: string): Promise<unknown>;
  copy(text: string): Promise<void>;
  confirm(ask: Ask): Promise<boolean>;
  retry(): void;
}

function gray(el: Element | null | undefined) {
  el?.classList.add("g-gray-text");
}
function text(el: Element | null | undefined, t: string) {
  if (el) el.textContent = t;
}
/** The value cell after the list item labelled `label` (OF's b-fans__item__list__item rows). */
function cell(row: Element, label: string): Element | null {
  for (const item of row.querySelectorAll(".b-fans__item__list__item")) {
    if (item.querySelector(".b-fans__item__list__label")?.textContent?.trim() === label) return item.lastElementChild;
  }
  return null;
}
function grayValue(doc: Document, value: Element | null, t: string) {
  if (!value) return;
  const span = doc.createElement("span");
  span.className = "g-gray-text";
  span.textContent = t;
  value.replaceWith(span);
}
const button = (row: Element, label: string) =>
  [...row.querySelectorAll<HTMLButtonElement>(".b-offer-join__btn button")].find((b) => b.textContent?.trim() === label) ?? null;
/** Make a row's button one this binder runs. */
function wire(b: HTMLButtonElement | null, label?: string) {
  if (!b) return;
  if (label) b.textContent = ` ${label} `;
  b.disabled = false;
  b.removeAttribute("title");
  b.setAttribute("data-oi-wired", "");
}

function clone(tpl: HTMLElement): HTMLElement {
  const el = make(tpl);
  el.style.removeProperty("display");
  if (!el.getAttribute("style")) el.removeAttribute("style");
  el.setAttribute("data-oi-row", "");
  return el;
}

function promotionRow(doc: Document, tpl: HTMLElement, p: SubPromotion, me: OfMe | undefined, img: (u: string) => string): HTMLElement {
  const el = clone(tpl);
  const end = p.finishedAt && p.finishedAt !== ZERO_DATE ? valid(p.finishedAt) : null;
  const ended = !onOffer(p) || (!!end && end.getTime() <= Date.now());
  const details = el.querySelector(".b-offer-join__details");
  text(details, ` ${promotionTitle(p, me?.subscribePrice)} `);
  const left = el.querySelector(".b-offer-join__left-time");
  const proto = left?.querySelector(".b-offer-join__left-time__el");
  if (left && proto) {
    const bits = [PROMO_FOR[p.type ?? "all"] ?? PROMO_FOR.all];
    if (end) bits.push(`${ended ? "ended" : "ends"} ${shortDay(end)}`);
    if (p.subscribeCounts) bits.push(`left ${p.subscribeCounts}`);
    left.replaceChildren(
      ...bits.map((b) => {
        const x = proto.cloneNode(false);
        x.textContent = ` ${b} `;
        return x;
      }),
    );
  }
  const bubble = el.querySelector(".b-offer-join__bubble");
  const msg = plain(p.message);
  const holder = bubble?.querySelector(".b-offer-join__bubble__text .g-truncated-text");
  if (!msg || !holder) bubble?.remove();
  else {
    holder.textContent = msg;
    setAvatar(bubble!.querySelector(".g-avatar"), { id: me?.id ?? "", name: me?.name ?? undefined, username: me?.username ?? undefined, avatar: me?.avatar ?? undefined }, img);
  }
  const started = cell(el, "Started");
  const startedAt = valid(p.createdAt ?? undefined);
  text(started?.querySelector("span[title]") ?? started, startedAt ? ` ${longDay(startedAt)} ` : " — ");
  text(cell(el, "Claims count"), ` ${p.claimsCount ?? 0} `);
  const stop = button(el, "Stop promotion");
  const share = button(el, "Copy link to profile");
  if (ended) {
    gray(details);
    gray(bubble);
    gray(started);
    share?.remove();
    wire(stop, "Remove");
    if (stop && p.id != null) actions.set(stop, { kind: "promotion", id: String(p.id), ask: null, route: `${SUB_ROUTES.promotions}/${p.id}` });
  } else {
    // Stop promotion: ofMirrorOffers' card binder (POST /promotions/{id}/finish).
    if (stop && p.id != null) {
      wire(stop);
      stop.setAttribute("data-oi-finish", String(p.id));
    }
    if (share) {
      wire(share);
      if (me?.username) actions.set(share, { kind: "promotion", id: String(p.id ?? ""), ask: null, route: "", copy: `${OF}/${me.username}` });
    }
  }
  return el;
}

/** A bundle's wording, as OF's row draws it: "$25.47 USD", "total for 3 months", "-15%" (null without a discount). */
export function bundleLabel(b: Bundle): { price: string; time: string; discount: string | null } {
  const months = b.duration ?? 0;
  return {
    // OF's amountHumanizeShort: two decimals, ".00" dropped ("$0", "$60", "$20.35").
    price: `$${(b.price ?? 0).toFixed(2).replace(".00", "")} USD`,
    time: `total for ${months} ${months === 1 ? "month" : "months"}`,
    discount: b.discount ? `-${b.discount}%` : null,
  };
}

function bundleRow(tpl: HTMLElement, b: Bundle, free = false): HTMLElement {
  const el = clone(tpl);
  // OF's bundle row: its content g-disabled while the subscription is free (authUser.subscribePrice <= 0).
  el.querySelector(".b-offer-join__content")?.classList.toggle("g-disabled", free);
  const label = bundleLabel(b);
  const price = el.querySelector(".b-amount-price");
  text(price, ` ${label.price} `);
  const time = el.querySelector(".b-offer-join__details__time");
  if (time?.lastChild?.nodeType === 3) time.lastChild.textContent = ` ${label.time} `;
  const discount = el.querySelector(".b-offer-join__details__discount");
  if (label.discount) text(discount, ` ${label.discount} `);
  else {
    discount?.remove();
    price?.classList.remove("big-space");
  }
  const del = el.querySelector<HTMLButtonElement>("button[aria-label='Delete']");
  wire(del);
  if (del && b.id != null) actions.set(del, { kind: "bundle", id: String(b.id), ask: ASKS.bundle, route: `${SUB_ROUTES.bundles}/${b.id}` });
  return el;
}

function linkDate(row: Element, label: string, iso: string | null | undefined) {
  const value = cell(row, label);
  const d = valid(iso ?? undefined);
  text(value?.querySelector("span[title]") ?? value, d ? ` ${longDay(d)} ` : " — ");
  return value;
}

function campaignRow(doc: Document, tpl: HTMLElement, c: Campaign, username: string | null | undefined): HTMLElement {
  const el = clone(tpl);
  const off = !!c.isDeleted;
  const details = el.querySelector(".b-offer-join__details");
  if (details?.firstChild?.nodeType === 3) details.firstChild.textContent = ` ${c.campaignName ?? ""} `;
  const created = linkDate(el, "Tracking link created", c.createdAt);
  const subs = cell(el, "Subscribers count");
  if (c.countSubscribers && subs) {
    const span = doc.createElement("span");
    span.textContent = ` ${c.countSubscribers} `;
    subs.replaceWith(span);
    if (off) gray(span);
  }
  const clicks = cell(el, "Clicks count");
  text(clicks, ` ${c.countTransitions ?? 0} `);
  if (off) [created, clicks].forEach(gray);
  const del = button(el, "Delete");
  wire(del, off ? "Remove" : "Delete");
  if (del && c.id != null)
    actions.set(del, { kind: "campaign", id: String(c.id), ask: ASKS.campaign, route: `${SUB_ROUTES.campaigns}/${c.id}` });
  const copy = button(el, "Copy link");
  if (copy && !off && username && c.campaignCode != null) {
    wire(copy);
    actions.set(copy, { kind: "campaign", id: String(c.id ?? ""), ask: null, route: "", copy: campaignLink(username, c.campaignCode) });
  } else if (copy) copy.disabled = true; // OF disables a deleted link's
  return el;
}

function trialRow(doc: Document, tpl: HTMLElement, t: Trial, shared = false, canCreate = true): HTMLElement {
  const el = clone(tpl);
  // The row's "Share link's statistics with another user" (ofMirrorOffers) shares this link; a link shared with this
  // model is not its own to share or delete.
  // (the clone drops the template's data-oi-* marks: the share line is marked again here)
  if (t.id != null && !shared) el.dataset.oiTrial = String(t.id);
  const share = el.querySelector<HTMLElement>(".b-hint-offer.g-pointer-cursor");
  const off = !!t.isFinished;
  // OF's TrialItem isDisabled: the model's own link while it may not create free trials, or an ended one.
  const disabled = (!shared && !canCreate) || off;
  const withUser = shared ? t.user?.username : t.sharedWith?.username;
  if (t.sharedWith && share && withUser) sharedLine(doc, share, shared, withUser);
  else if (shared) share?.remove();
  else share?.setAttribute("data-oi-share", "");
  share?.setAttribute("data-oi-wired", "");
  const days = t.subscribeDays ?? 0;
  const details = el.querySelector(".b-offer-join__details");
  if (details) {
    const span = (s: string) => {
      const x = doc.createElement("span");
      x.className = "m-default-font-weight";
      x.textContent = s;
      return x;
    };
    const parts: (string | Node)[] = t.trialLinkName
      ? [` ${t.trialLinkName} `, span(` (${trialLength(days)} free trial) `)]
      : [` ${trialLength(days)} `, span(" free trial ")];
    if (off) parts.push(span(" - expired "));
    details.replaceChildren(...parts);
  }
  if (disabled) gray(el.querySelector(".b-offer-join__content"));
  const created = linkDate(el, "Free trial link created", t.createdAt);
  // OF's "Link expires" / "Link expired" line, after Created, when the link has an end date.
  const createdItem = created?.closest(".b-fans__item__list__item");
  const end = valid(t.expiredAt ?? undefined);
  let expires: Element | null = null;
  if (createdItem && end) {
    const item = createdItem.cloneNode(true) as Element;
    text(item.querySelector(".b-fans__item__list__label"), ` ${off ? "Link expired" : "Link expires"} `);
    expires = item.lastElementChild;
    text(expires?.querySelector("span[title]") ?? expires, ` ${longDay(end)} `);
    fillSlot(createdItem, "after", item);
  }
  const limit = cell(el, "Offer limit");
  text(limit, ` ${t.subscribeCounts || "Unlimited"} `);
  const claims = cell(el, "Claims count");
  if (t.claimCounts) text(claims, ` ${t.claimCounts} `);
  else grayValue(doc, claims, "Not claimed yet");
  const clicks = cell(el, "Clicks count");
  text(clicks, ` ${t.clicksCounts ?? 0} `);
  if (disabled) [created, expires, limit, clicks].forEach(gray);
  const del = button(el, "Delete");
  if (shared) del?.remove();
  wire(del, off ? "Remove" : "Delete");
  if (del && t.id != null && !shared)
    actions.set(del, { kind: "trial", id: String(t.id), ask: off ? ASKS.trialFinished : ASKS.trial, route: `${SUB_ROUTES.trials}/${t.id}` });
  const copy = button(el, "Copy link");
  if (copy) {
    // OF's: disabled for an ended link, and for the model's own links while it may not create free trials.
    if (off || !t.url || (!shared && !canCreate)) {
      copy.disabled = true;
      copy.removeAttribute("data-oi-wired");
    } else {
      wire(copy);
      actions.set(copy, { kind: "trial", id: String(t.id ?? ""), ask: null, route: "", copy: t.url });
    }
  }
  return el;
}

/**
 * OF's line for a link whose statistics are shared: "Shared with @user" and its remove-access button (the owner's), or
 * "Shared from @owner" on Shared with you. Removing access is never written here: the button is disabled.
 */
function sharedLine(doc: Document, line: HTMLElement, shared: boolean, username: string) {
  line.classList.remove("g-pointer-cursor");
  line.removeAttribute("data-oi-share");
  const name = doc.createElement("div");
  name.className = "b-hint-offer__name";
  name.textContent = ` ${shared ? "Shared from" : "Shared with"} `;
  const value = doc.createElement("div");
  value.className = "b-hint-offer__value";
  const who = doc.createElement("a");
  who.textContent = ` @${username} `;
  value.append(who);
  if (!shared) {
    const close = doc.createElement("button");
    close.type = "button";
    close.className = "l-sidebar__btn-close m-with-round-hover g-btn m-icon m-icon-only m-gray m-sm-size";
    close.disabled = true;
    close.title = NOT_YET;
    close.innerHTML = '<svg data-icon-name="icon-close" aria-hidden="true" class="g-icon"><use href="#icon-close" xlink:href="#icon-close"></use></svg>';
    value.append(close);
  }
  line.replaceChildren(name, value);
}

/** Why OF disables a create button (OF shows no reason; ours names the account's state, not a missing feature). */
export const PRICE_FIRST = "Set a subscription price first";
export const OF_DISALLOWS = "OnlyFans doesn't allow this on this account";

/**
 * One of OF's create buttons (an <a> to its dialog here) as OF disables it: OF's disabled look, no link, and `why` as
 * its tooltip. `why` "": enabled; null: the model is not read yet, so the button stays as it is.
 */
function gate(doc: Document, dialog: string, why: string | null) {
  if (why === null) return;
  const off = why !== "";
  for (const a of doc.querySelectorAll<HTMLAnchorElement>(`a.g-btn[href$='/${dialog}'], a.g-btn[data-oi-href$='/${dialog}']`)) {
    if (off && a.hasAttribute("href")) {
      a.setAttribute("data-oi-href", a.getAttribute("href")!);
      a.removeAttribute("href");
    } else if (!off && a.hasAttribute("data-oi-href")) {
      a.setAttribute("href", a.getAttribute("data-oi-href")!);
      a.removeAttribute("data-oi-href");
    }
    a.toggleAttribute("disabled", off);
    a.setAttribute("aria-disabled", String(off));
    // OF's [disabled] g-btn takes no pointer events; this one keeps them so its tooltip shows.
    a.classList.toggle("g-pointer-events-auto", off);
    if (off) a.title = why;
    else a.removeAttribute("title");
  }
}

/** Put the rows of `tpl`'s kind in place of the last ones drawn (before the hidden template, in the Relay's order). */
/**
 * Ours, not OF's: a long promotion list scrolls in its own box, so Subscription bundles under it stays in view without
 * scrolling the page (a short list is unchanged: the cap only bites past it). The same cap as Growth's lists.
 */
export const LIST_MAX_HEIGHT = "min(55vh, 480px)";
function boundList(el: HTMLElement | null) {
  if (!el) return;
  el.setAttribute("data-oi-scroll", "");
  el.style.maxHeight = LIST_MAX_HEIGHT;
  el.style.overflowY = "auto";
  // OF's .b-offer-wrapper is a wrapping flex column with min-height 100%: capped, it would flow the cards into new
  // columns sideways instead of scrolling. One column, no floor.
  el.style.flexWrap = "nowrap";
  el.style.minHeight = "0";
}

function put(tpl: HTMLElement, rows: HTMLElement[]) {
  for (const old of tpl.parentElement?.querySelectorAll(":scope > [data-oi-row]") ?? []) old.remove();
  tpl.before(...rows);
}

/** A link page's OF list status: [preloader, "No results :(", no more, "Something went wrong."]. */
function status(doc: Document, s: PartState<unknown> | undefined) {
  const prompts = doc.querySelectorAll<HTMLElement>(".infinite-loading-container > .infinite-status-prompt");
  if (prompts.length < 4) return;
  const shown = s?.loading ? 0 : s?.error ? 3 : s?.rows?.length ? -1 : 1;
  prompts.forEach((p, i) => {
    if (i === shown) p.style.removeProperty("display");
    else p.style.display = "none";
  });
}

/** Draw `data` on the Subscription page at `page` in `doc` (the parts it shows; a part with no rows draws none). */
export function applySubscription(
  doc: Document,
  page: string,
  data: SubData,
  me: OfMe | undefined,
  img: (u: string) => string = (u) => u,
  trialsShared = false,
  settings?: BundleSettings,
): void {
  const parts = subscriptionParts(page);
  const tpl = (name: string) => doc.querySelector<HTMLElement>(`[data-oi-template='${name}']`);
  // OF's m-disabled-block on the section headers: no price, or (promotions) no right to create one.
  const free = me ? !me.subscribePrice : null;
  const header = (title: string) =>
    [...doc.querySelectorAll("h3.b-menu-list__el")].find((h) => h.querySelector(".b-menu-list__text")?.textContent?.trim() === title);
  if (parts.includes("promotions")) {
    const t = tpl("promotion-row");
    if (t) {
      put(t, (data.promotions?.rows ?? []).map((p) => promotionRow(doc, t, p, me, img)));
      boundList(t.parentElement);
    }
    if (free !== null) header("Profile promotion campaign")?.classList.toggle("m-disabled-block", free || me?.canCreatePromotion === false);
    // OF's "Start promotion campaign": disabled with no price, or for a page that is no performer's, may not promote or earn.
    gate(doc, "promotion-campaign/modal-1", me ? (!(Number(me.subscribePrice) > 0) ? PRICE_FIRST : !me.isPerformer || !me.canCreatePromotion || !me.canEarn ? OF_DISALLOWS : "") : null);
  }
  if (parts.includes("bundles")) {
    const t = tpl("bundle-row");
    if (t) put(t, (data.bundles?.rows ?? []).map((b) => bundleRow(t, b, !!free)));
    if (free !== null) header("Subscription bundles")?.classList.toggle("m-disabled-block", free);
    // OF's isAddBundleDisabled: no price, or no duration in canAddSubscriberByBundle left without a bundle.
    const left = bundleOptions(settings, (data.bundles?.rows ?? []).map((b) => Number(b.duration))).durations;
    gate(doc, "promotion-campaign/modal-2", me ? (free ? PRICE_FIRST : !left.length ? NO_BUNDLES_LEFT : "") : null);
  }
  for (const part of ["campaigns", "trials"] as const) {
    if (!parts.includes(part)) continue;
    const t = tpl("link-row");
    const rows = (data[part]?.rows ?? []) as (Campaign & Trial)[];
    if (t) put(t, rows.map((r) => (part === "campaigns" ? campaignRow(doc, t, r, me?.username) : trialRow(doc, t, r, trialsShared, !me || !!me.canCreateTrial))));
    // OF's "Create new free trial link": disabled while the model may not create free trials (authUser.canCreateTrial).
    if (part === "trials") {
      gate(doc, "trial-links/modal-1", me ? (me.canCreateTrial ? "" : free ? PRICE_FIRST : OF_DISALLOWS) : null);
      // OF's header line: hint_trial_link(_disabled)_title, gray while disabled.
      const hint = doc.querySelector("#trial .b-menu-list__el.m-reset-bb");
      if (hint && me) {
        hint.textContent = me.canCreateTrial
          ? " Create and share separate links with free trial subscription. "
          : " Set subscription price to create and share separate links with free trial subscription. ";
        hint.classList.toggle("g-gray-text", !me.canCreateTrial);
      }
    }
    status(doc, data[part]);
    const retry = [...doc.querySelectorAll<HTMLButtonElement>(".infinite-status-prompt .empty-message__btn button")].find((b) => b.textContent?.trim() === "Retry");
    retry?.setAttribute("data-oi-wired", "");
  }
}

/** The rows' Delete, Remove and Copy buttons and the list's Retry, in `doc`. Returns an unbind. */
export function bindSubscription(doc: Document, handlers: SubHandlers): () => void {
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (t?.closest?.(".infinite-status-prompt .empty-message__btn button")) {
      ev.preventDefault();
      return handlers.retry();
    }
    const b = t?.closest?.<HTMLButtonElement>("button[data-oi-wired]");
    const a = b ? actions.get(b) : undefined;
    if (!b || !a) return;
    ev.preventDefault();
    if (a.copy !== undefined) {
      handlers.copy(a.copy).then(
        () => void toast(doc, "Link copied"),
        () => note(doc, b, "Could not copy the link", true),
      );
      return;
    }
    if (b.disabled) return;
    // OF's ModalConfirm first.
    if (!a.ask) return remove(b, a);
    void handlers.confirm(a.ask).then((yes) => yes && remove(b, a));
  };
  const remove = (b: HTMLButtonElement, a: RowAction) => {
    b.disabled = true;
    handlers.remove(a.route).then(
      () => b.closest("[data-oi-row]")?.remove(),
      (e) => {
        b.disabled = false;
        // A bundle's, as OF's deleteBundle: its own error message in a toast (the row stays).
        const of = a.kind === "bundle" ? ofErrorMessage(e) : null;
        if (of) toast(doc, of);
        else note(doc, b, `Could not delete: ${message(e)}`, true);
      },
    );
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

/** The Relay read of one part (key under "of-settings", so a write's invalidation re-reads it). */
const subQuery = (accountId: string | null, part: SubPart, enabled: boolean, route: string = SUB_ROUTES[part]) => ({
  queryKey: ["of-settings", "subscription", part, accountId, route],
  queryFn: () => relay.get<unknown>(route, { accountId }),
  enabled: !!accountId && enabled,
  staleTime: 60_000,
  retry: false,
});

/** On a Subscription settings page with a single model selected, draw its rows on every frame load and data change. */
export function useOfSubscription(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const page = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const parts = subscriptionParts(page);
  const campaigns = useQuery(subQuery(accountId, "campaigns", parts.includes("campaigns")));
  // The free trial links tab and sort (ofMirrorOffers: ?tab=shared, ?field=, ?sort=).
  const trialView = trialViewOf(useSearchParams());
  const trials = useQuery(subQuery(accountId, "trials", parts.includes("trials"), trialsRoute(trialView)));
  const meQuery = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && parts.length > 0 });
  // Add bundle's options (OF's isAddBundleDisabled reads canAddSubscriberByBundle), shared with the bundle dialog's read.
  const settings = useQuery({
    queryKey: ["of-settings", "settings", accountId],
    queryFn: () => relay.get<BundleSettings>("/api/of/v2/users/me/settings", { accountId }),
    enabled: !!accountId && parts.includes("bundles"),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const me = meQuery.data;
  const state = <T,>(q: { data?: unknown; isLoading: boolean; isError: boolean }): PartState<T> =>
    accountId ? { rows: q.isError ? [] : listOf<T>(q.data), loading: q.isLoading, error: q.isError } : {};

  const data: SubData = {
    // OF lists the promotions from /users/me too (user.promotions), not /promotions.
    promotions: state<SubPromotion>({ data: mePromotions(me), isLoading: meQuery.isLoading, isError: meQuery.isError }),
    // OF lists the bundles from /users/me (authUser.subscriptionBundles), not /subscriptions/bundles.
    bundles: state<Bundle>({ data: me?.subscriptionBundles ?? [], isLoading: meQuery.isLoading, isError: meQuery.isError }),
    campaigns: state<Campaign>(campaigns),
    trials: state<Trial>(trials),
  };
  const key = JSON.stringify([meQuery.dataUpdatedAt, settings.dataUpdatedAt, campaigns.dataUpdatedAt, trials.dataUpdatedAt, data.campaigns?.loading, data.trials?.loading, data.campaigns?.error, data.trials?.error]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !subscriptionParts(page).length) return;
    const handlers: SubHandlers = {
      remove: (path) =>
        relay.delete(path, { accountId }).then(() =>
          Promise.all([qc.invalidateQueries({ queryKey: ["of-settings", "subscription"] }), qc.invalidateQueries({ queryKey: ["of-me", accountId] })]),
        ),
      copy: (t) => frame.contentWindow?.navigator.clipboard?.writeText(t) ?? Promise.reject(new Error("no clipboard")),
      confirm: (ask) => (frame.contentDocument ? ofConfirm(frame.contentDocument, ask) : Promise.resolve(false)),
      retry: () => void qc.invalidateQueries({ queryKey: ["of-settings", "subscription"] }),
    };
    let unbind: (() => void) | undefined;
    const apply = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      applySubscription(doc, page, data, me, (u) => proxyImage(u, accountId), trialView.tab === "shared", settings.data);
      unbind = bindSubscription(doc, handlers);
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => {
      frame.removeEventListener("load", apply);
      unbind?.();
    };
    // `data` is rebuilt each render; `key` says when it changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameRef, src, page, accountId, qc, me, key, trialView.tab]);
}
