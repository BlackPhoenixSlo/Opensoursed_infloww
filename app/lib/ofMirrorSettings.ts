"use client";


import { useEffect, type RefObject } from "react";
import { usePathname } from "next/navigation";
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { floatLabel, objectOf } from "@/lib/ofMirrorDom";
import { applyAccount, applyEmailFrequency, applyMessaging, applySecurity } from "@/lib/ofMirrorSettingsPages";
import { drawLinks, LISTS } from "@/lib/ofMirrorProfileLinks";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";
import { drawObsServer, STREAM_KEY_MASK } from "@/lib/ofMirrorObsServer";

type Transport = "email" | "message" | "toast" | "webpush";
export type SettingsSource = "settings" | "me" | "story" | "templates" | "sessions" | "socialButtons" | "init" | "thingsLinks" | `notifications:${Transport}` | "countries";
export type SettingsData = Partial<Record<SettingsSource, unknown>>;
type Value = boolean | string | null | undefined;
type Data = Record<string, unknown>;

export interface SettingsEntry {
  source: SettingsSource;
  field: string | ((data: unknown) => Value);
  target?: "help";
}

export const SOURCE_PATHS: Record<SettingsSource, string> = {
  settings: "/api/of/v2/users/me/settings",
  me: "/api/of/v2/users/me",
  story: "/api/of/v2/users/settings/story",
  templates: "/api/of/v2/messages/templates",
  sessions: "/api/of/v2/sessions",
  socialButtons: "/api/of/v2/users/social/buttons",
  init: "/api/of/v2/init",
  thingsLinks: "/api/of/v2/users/links",
  "notifications:email": "/api/of/v2/users/settings/notifications/email?group=1",
  "notifications:message": "/api/of/v2/users/settings/notifications/message?group=1",
  "notifications:toast": "/api/of/v2/users/settings/notifications/toast?group=1",
  "notifications:webpush": "/api/of/v2/users/settings/notifications/webpush?group=1",
  countries: "/api/of/v2/countries?all=1",
};

const of = (source: SettingsSource, fields: string[], id = (f: string) => `setting_${f}`) =>
  Object.fromEntries(fields.map((f) => [id(f), { source, field: f } as SettingsEntry]));

const notifications = (t: Transport, codes: string[]) =>
  Object.fromEntries(
    codes.map((code) => [
      `toggle_${code}`,
      {
        source: `notifications:${t}`,
        field: (groups: unknown) => {
          if (!Array.isArray(groups)) return undefined;
          for (const g of groups as { items?: { code?: string; isEnabled?: boolean }[] }[])
            for (const it of g?.items ?? []) if (it?.code === code && typeof it.isEnabled === "boolean") return it.isEnabled;
          return undefined;
        },
      } as SettingsEntry,
    ]),
  );

const coStreaming: SettingsEntry = { source: "settings", field: "coStreamingRequestFrom" };

// Only these fields are read (never stream keys or tokens).
export const SETTINGS_MAP: Record<string, Record<string, SettingsEntry>> = {
  profile: of("me", ["location", "website", "wishlist"], (f) => `input-${f}`),
  fans: of("settings", ["isAutoFollowBack", "unfollowAutoFollowBack", "recommenderReward", "sendAwardsTop1", "sendAwardsTop5"]),
  messaging: { autoMessage: { source: "settings", field: "replyOnSubscribe" } },
  security: {
    ...of("me", ["isVisibleOnline", "showSubscribersCount", "showMediaCount", "isWantComments"]),
    ...of("settings", [
      "showFriendsToSubscribers",
      "isOldLoginRedirect",
      "isSuggestionsOptOut",
      "commentsOnlyForPayers",
      "creatorsCommentsOnlyForFriends",
      "showPostsTips",
      "isDrmEnabled",
    ]),
  },
  "security/watermarks": {
    ...of("me", ["hasWatermarkPhoto", "hasWatermarkVideo"], (f) => f),
    "input-watermark-text": { source: "me", field: "watermarkText", target: "help" },
    watermark_position: { source: "me", field: "watermarkPosition" },
  },
  "notifications/email": {
    "toggle_email-notifications": { source: "settings", field: "isEmailNotificationsEnabled" },
    toggle_isMonthlyNewsletters: { source: "settings", field: "isMonthlyNewsletters" },
    "toggle_important-email-notifications": { source: "settings", field: "importantSubscriptionNotifications" },
    ...notifications("email", [
      "new_likes_digest",
      "fund_raising_goal_reached",
      "new_tips_fund_raising",
      "new_referal",
      "new_subscriber",
      "new_subscriber_trial",
      "new_tips",
      "autoprolong",
      "returning_subscriber",
      "reminder_stream",
    ]),
  },
  "notifications/mentions": of("settings", ["notifyOnAllMentions", "muteTagsInChats", "muteTagsInPosts", "muteTagsInStories"]),
  "notifications/message": notifications("message", [
    "fund_raising_goal_reached",
    "new_tips_fund_raising",
    "new_comment",
    "new_favorite",
    "new_subscriber",
    "new_subscriber_trial",
    "new_tips",
    "returning_subscriber",
    "promoreg_for_expired",
    "new_stream",
    "reminder_stream",
  ]),
  "notifications/toast": notifications("toast", [
    "new_tips_fund_raising",
    "new_comment",
    "new_favorite",
    "new_subscriber",
    "new_subscriber_trial",
    "new_tips",
    "new_stream",
  ]),
  "notifications/webpush": notifications("webpush", [
    "new_tips_fund_raising",
    "new_comment",
    "new_favorite",
    "new_subscriber",
    "new_subscriber_trial",
    "new_tips",
    "new_stream",
    "new_chat_message",
  ]),
  "account/2fa": {
    show_otp_settings: { source: "settings", field: "appOtp" },
    otp_phone_settings: { source: "settings", field: "phoneOtp" },
    otp_face_info: { source: "settings", field: "faceOtp" },
  },
  story: {
    show_subscribes_offers: {
      source: "story",
      field: (s) => {
        const v = (s as Data | null)?.allowReplyFrom;
        return typeof v === "string" ? v === "subscribers" : undefined;
      },
    },
  },
  streaming: { allowSubscribers: coStreaming, allowFriends: coStreaming, allowNobody: coStreaming },
};

export function sourcesFor(page: string): SettingsSource[] {
  const base = page.replace(/\/state-[^/]+$/, "");
  return [...new Set([...Object.values(settingsEntriesFor(page) ?? {}).map((e) => e.source), ...(extraFor(base)?.sources ?? [])])];
}

export function settingsEntriesFor(page: string): Record<string, SettingsEntry> | null {
  const base = page.replace(/\/state-[^/]+$/, "");
  return Object.hasOwn(SETTINGS_MAP, base) ? SETTINGS_MAP[base] : null;
}

const read = (e: SettingsEntry, data: unknown): Value => {
  if (typeof e.field === "function") return e.field(data);
  if (!data || typeof data !== "object") return undefined;
  const v = (data as Data)[e.field];
  return typeof v === "boolean" || typeof v === "string" || v === null ? v : undefined;
};

const label = (v: string) => (v ? v[0].toUpperCase() + v.slice(1).replace(/_/g, " ") : v);

function selectOption(doc: Document, input: HTMLInputElement, text: string) {
  const id = input.closest(".v-select")?.querySelector("[aria-owns]")?.getAttribute("aria-owns");
  const list = id ? doc.getElementById(id) : null;
  for (const item of list?.querySelectorAll(".v-list-item") ?? []) {
    const on = item.querySelector(".v-list-item__title")?.textContent?.trim() === text;
    for (const c of ["primary--text", "v-list-item--active", "v-list-item--highlighted"]) item.classList.toggle(c, on);
    item.setAttribute("aria-selected", String(on));
  }
}

export function applySettings(doc: Document, page: string, data: SettingsData): void {
  const entries = settingsEntriesFor(page);
  if (!entries) return;
  for (const [key, e] of Object.entries(entries)) {
    if (data[e.source] === undefined) continue;
    const v = read(e, data[e.source]);
    if (v === undefined) continue;
    const el = doc.getElementById(key) ?? doc.querySelector(`input[name="${key}"]`);
    if (el?.tagName === "INPUT") {
      const input = el as HTMLInputElement;
      if (input.type === "checkbox") input.checked = !!v;
      else if (typeof v !== "string") continue;
      else if (input.type === "radio") input.checked = input.value === v;
      else if (e.target === "help") {
        const help = input.closest(".v-input")?.querySelector(".g-input__help");
        if (help && v) help.textContent = ` Current: ${v} `;
      } else {
        input.value = v;
        if (input.type !== "hidden") floatLabel(input, !!v);
        const shown = input.type === "hidden" ? input.closest(".v-select")?.querySelector(".v-select__selection") : null;
        if (shown) shown.textContent = label(v);
        if (input.type === "hidden") selectOption(doc, input, label(v));
        const counter = input.closest(".g-input__wrapper")?.querySelector(".v-counter");
        if (counter) counter.textContent = (counter.textContent ?? "").replace(/^\s*\d+/, String([...v].length));
      }
    }
  }
}

const dollars = (p: number) => `$${p.toFixed(2)}`;

function perMonth(el: Element, price: number) {
  const doc = el.ownerDocument;
  const amount = doc.createElement("span");
  amount.className = "b-amount-price m-num";
  amount.textContent = dollars(price);
  el.replaceChildren(amount, doc.createTextNode(" per month"));
}

function priceLine(doc: Document, title: string): HTMLElement | null {
  for (const a of doc.querySelectorAll("a[href='/of-manager/settings/subscription']")) {
    const sub = a.querySelector<HTMLElement>(".b-menu-list__subtext");
    if (sub && a.querySelector(".b-menu-list__text")?.textContent?.trim() === title) return sub;
  }
  return null;
}

export { STREAM_KEY_MASK };

function priceLines(doc: Document, base: string, data: SettingsData): void {
  const me = objectOf<{ subscribePrice?: unknown; subscriptionBundles?: unknown }>(data.me);
  if (!me) return;
  const price = typeof me.subscribePrice === "number" && me.subscribePrice > 0 ? me.subscribePrice : 0;
  const line = priceLine(doc, base === "profile" ? "Subscription price and bundles" : "Following price");
  if (line) {
    line.removeAttribute("data-oi-price");
    if (base === "fans") {
      if (price) perMonth(line, price);
      else line.textContent = "Free";
      line.style.removeProperty("display");
    } else if (!price) line.style.display = "none";
    else {
      perMonth(line, price);
      const n = Array.isArray(me.subscriptionBundles) ? me.subscriptionBundles.length : 0;
      if (n) line.append(`, ${n} subscription ${n === 1 ? "bundle" : "bundles"}`);
      line.style.removeProperty("display");
    }
  }
  if (base === "fans") {
    const reward = doc.getElementById("setting_recommenderReward") as HTMLInputElement | null;
    if (reward) reward.disabled = !price;
  }
}

function obsServer(doc: Document, _base: string, data: SettingsData): void {
  drawObsServer(doc, data.settings);
}

function watermarkText(doc: Document, _base: string, data: SettingsData): void {
  const me = objectOf<{ watermarkText?: unknown; username?: unknown }>(data.me);
  const field = doc.getElementById("input-watermark-text") as HTMLInputElement | null;
  if (!me || !field) return;
  const text = typeof me.watermarkText === "string" ? me.watermarkText : "";
  field.value = text === `OnlyFans.com/${String(me.username ?? "")}` ? "" : text;
  floatLabel(field, !!field.value);
  const counter = field.closest(".g-input__wrapper, .v-input")?.querySelector(".v-counter");
  if (counter) counter.textContent = (counter.textContent ?? "").replace(/^\s*\d+/, String([...field.value].length));
}

interface PageExtra {
  sources: SettingsSource[];
  apply(doc: Document, base: string, data: SettingsData, img: (url: string) => string, writable: boolean): void;
}
const ACCOUNT: PageExtra = { sources: [], apply: applyAccount };
const PAGE_EXTRAS: Record<string, PageExtra> = {
  profile: { sources: ["me"], apply: priceLines },
  fans: { sources: ["me"], apply: priceLines },
  messaging: { sources: ["me", "settings", "templates"], apply: applyMessaging },
  security: { sources: ["me", "settings"], apply: applySecurity },
  "security/watermarks": { sources: ["me"], apply: watermarkText },
  streaming: { sources: ["settings"], apply: obsServer },
  account: { sources: ["settings", "me"], apply: applyAccount },
  "account/email": { sources: ["me"], apply: applyAccount },
  "account/phone": { sources: ["settings"], apply: applyAccount },
  "account/2fa": { sources: ["settings", "me"], apply: applyAccount },
  "account/sessions": { sources: ["sessions"], apply: applyAccount },
  "notifications/email": { sources: ["notifications:email"], apply: applyEmailFrequency },
  "security/block_by_country": { sources: ["settings", "countries"], apply: settingsRead },
  "security/block_by_ip": { sources: ["settings"], apply: settingsRead },
  "social-media": { sources: ["socialButtons", "init"], apply: (doc, base, data, _img, writable) => drawLinks(doc, LISTS[base], data.socialButtons, writable) },
  links: { sources: ["thingsLinks"], apply: (doc, base, data, _img, writable) => drawLinks(doc, LISTS[base], data.thingsLinks, writable) },
};
export const SETTINGS_READ = "oi-settings-read";
function settingsRead(doc: Document): void {
  doc.dispatchEvent(new (doc.defaultView?.Event ?? Event)(SETTINGS_READ));
}
const extraFor = (base: string): PageExtra | null => (Object.hasOwn(PAGE_EXTRAS, base) ? PAGE_EXTRAS[base] : base.startsWith("account/") ? ACCOUNT : null);

export function applyPageExtras(doc: Document, page: string, data: SettingsData, writable: boolean, img: (url: string) => string = (u) => u): void {
  const base = page.replace(/\/state-[^/]+$/, "");
  extraFor(base)?.apply(doc, base, data, img, writable);
}

export const NARROW_CSS = `@media (max-width: 1003.98px) {
html:not(.oi-settings-root) .b-settings__nav { display: none !important; }
html:not(.oi-settings-root) .b-settings__header__left-col .g-page-title { display: none !important; }
html:not(.oi-settings-root) .g-page__header > a.g-page__header__btn { display: none !important; }
html.oi-settings-root .b-settings__content, html.oi-settings-root .g-page__header > :not(.b-settings__header__left-col) { display: none !important; }
}`;

const NARROW = "(max-width: 1003.98px)";

export function applyLayout(doc: Document, root: boolean): void {
  doc.documentElement.classList.toggle("oi-settings-root", root);
  const narrow = !!doc.defaultView?.matchMedia?.(NARROW).matches;
  if (root && narrow) for (const a of doc.querySelectorAll(".b-settings__nav .m-current")) a.classList.remove("m-current");
  const back = doc.querySelector<HTMLAnchorElement>(".b-settings__header__left-col > a.g-page__header__btn");
  if (back && !root && narrow && back.getAttribute("href") === "/of-manager/home") back.setAttribute("href", "/of-manager/settings");
  if (doc.head && !doc.getElementById("oi-settings-mq")) {
    const style = doc.createElement("style");
    style.id = "oi-settings-mq";
    style.textContent = NARROW_CSS;
    doc.head.append(style);
  }
}

const combine = (results: UseQueryResult<unknown>[]) => results.map((r) => r.data);

export function useOfSettings(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const root = usePathname() === "/of-manager/settings";
  const page = /^\/of-mirror\/pages\/settings\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const sources = page ? sourcesFor(page) : [];
  const newWrites = useOfmNewWrites(!!page, accountId);
  const values = useQueries({
    queries: sources.map((s) => ({
      queryKey: s === "me" ? ["of-me", accountId] : ["of-settings", s, accountId],
      queryFn: () => relay.get(SOURCE_PATHS[s], { accountId }),
      enabled: !!accountId,
      staleTime: 5 * 60 * 1000,
      retry: false,
    })),
    combine,
  });

  const key = sources.join();
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    const data = Object.fromEntries(key.split(",").map((s, i) => [s, values[i]]));
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      applyLayout(doc, root);
      applySettings(doc, page, data);
      applyPageExtras(doc, page, data, newWrites, (u) => proxyImage(u, accountId));
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, page, key, values, accountId, root, newWrites]);
}
