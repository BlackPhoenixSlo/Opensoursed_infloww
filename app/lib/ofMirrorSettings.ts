"use client";

/**
 * Per-model settings values for the OF settings mirror (public/of-mirror/pages/settings).
 * The pages show placeholder toggle/field states; we fetch the model's settings (a selected model, or in All models
 * the first one: OfMirrorFrame's standInModel) and set the mapped controls after each frame load.
 * Only the fields named in SETTINGS_MAP are read (never stream keys or tokens); the account email is shown to the
 * owner as OF shows it, read-only (applyPageExtras). Unmapped controls and failed fetches keep the placeholders.
 * applyPageExtras draws what OF computes rather than reads (build 202610091632): the price lines of Profile and Fans,
 * Fans' referral switch off while free, and every Account page's controls disabled. PAGE_EXTRAS names each page's
 * sources and drawer; the Account, Messaging and Security drawers are in ofMirrorSettingsPages.
 */

import { useEffect, type RefObject } from "react";
import { usePathname } from "next/navigation";
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { objectOf } from "@/lib/ofMirrorData";
import { applyAccount, applyMessaging, applySecurity } from "@/lib/ofMirrorSettingsPages";

type Transport = "email" | "message" | "toast" | "webpush";
export type SettingsSource = "settings" | "me" | "story" | "templates" | "sessions" | `notifications:${Transport}`;
/** A settings page's sources' bodies (source -> response body; undefined while loading or after a failure). */
export type SettingsData = Partial<Record<SettingsSource, unknown>>;
type Value = boolean | string | null | undefined;
type Data = Record<string, unknown>;

export interface SettingsEntry {
  source: SettingsSource;
  /** A top-level field of the source, or a reader over the whole source body. */
  field: string | ((data: unknown) => Value);
  /** "help": write `Current: <value>` into the control's help line instead of its value. */
  target?: "help";
}

/** Relay route per source (`X-Account-Id` comes from the scope). */
export const SOURCE_PATHS: Record<SettingsSource, string> = {
  settings: "/api/of/v2/users/me/settings",
  me: "/api/of/v2/users/me",
  story: "/api/of/v2/users/settings/story",
  // OF's message templates: Messaging shows the welcome one (reply_on_subscribe).
  templates: "/api/of/v2/messages/templates",
  // Account > Login sessions, read-only (OF's settings-sessions.js; nothing here ends a session).
  sessions: "/api/of/v2/sessions",
  "notifications:email": "/api/of/v2/users/settings/notifications/email?group=1",
  "notifications:message": "/api/of/v2/users/settings/notifications/message?group=1",
  "notifications:toast": "/api/of/v2/users/settings/notifications/toast?group=1",
  "notifications:webpush": "/api/of/v2/users/settings/notifications/webpush?group=1",
};

const of = (source: SettingsSource, fields: string[], id = (f: string) => `setting_${f}`) =>
  Object.fromEntries(fields.map((f) => [id(f), { source, field: f } as SettingsEntry]));

/** `group=1` body: `[{code, items: [{code, isEnabled}]}]`; the toggle for item `code` is `toggle_<code>`. */
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

/** Page (sub path under settings/) -> control `id` (or `name`) -> value source. */
export const SETTINGS_MAP: Record<string, Record<string, SettingsEntry>> = {
  profile: of("me", ["location", "website", "wishlist"], (f) => `input-${f}`),
  fans: of("settings", ["isAutoFollowBack", "unfollowAutoFollowBack", "recommenderReward", "sendAwardsTop1", "sendAwardsTop5"]),
  // The welcome message's master flag.
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
  // OF's 2FA switches (module 739988's page, chunk 9779): the authenticator app, SMS and Face ID. Shown, never saved.
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
  // Radios: the one whose value equals the field is checked.
  streaming: { allowSubscribers: coStreaming, allowFriends: coStreaming, allowNobody: coStreaming },
};

/** The sources a settings page reads: its mapped controls' and its PAGE_EXTRAS entry's. */
export function sourcesFor(page: string): SettingsSource[] {
  const base = page.replace(/\/state-[^/]+$/, "");
  return [...new Set([...Object.values(settingsEntriesFor(page) ?? {}).map((e) => e.source), ...(extraFor(base)?.sources ?? [])])];
}

/** The map for a settings page; a `<page>/state-<name>` page shares its page's controls. */
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

/** "bottom_right" -> "Bottom right" (OF's labels for its option values). */
const label = (v: string) => (v ? v[0].toUpperCase() + v.slice(1).replace(/_/g, " ") : v);

/** What Vuetify does for a filled field: its label floats up into a gap in the outline, clear of the value. */
export function floatLabel(input: HTMLInputElement, filled: boolean) {
  const field = input.closest(".v-input");
  if (!field) return;
  for (const c of ["v-input--is-label-active", "v-input--is-dirty"]) field.classList.toggle(c, filled);
  const label = field.querySelector<HTMLElement>(".v-label");
  label?.classList.toggle("v-label--active", filled);
  // Vuetify's gap: the label at its floated scale (0.75) plus 6px.
  const legend = field.querySelector<HTMLElement>("legend");
  if (legend && label) legend.style.width = filled ? `${label.scrollWidth * 0.75 + 6}px` : "0px";
}

/**
 * A select's open list (a state page's, found by its activator's aria-owns, wherever the menu was moved) marks the
 * option titled `text` as Vuetify marks the selected one, and only that one.
 */
function selectOption(doc: Document, input: HTMLInputElement, text: string) {
  const id = input.closest(".v-select")?.querySelector("[aria-owns]")?.getAttribute("aria-owns");
  const list = id ? doc.getElementById(id) : null;
  for (const item of list?.querySelectorAll(".v-list-item") ?? []) {
    const on = item.querySelector(".v-list-item__title")?.textContent?.trim() === text;
    for (const c of ["primary--text", "v-list-item--active", "v-list-item--highlighted"]) item.classList.toggle(c, on);
    item.setAttribute("aria-selected", String(on));
  }
}

/**
 * Set the mapped controls of `page` in `doc` from `data` (source -> response
 * body). Idempotent; controls whose source or field is missing stay as they are.
 */
export function applySettings(doc: Document, page: string, data: SettingsData): void {
  const entries = settingsEntriesFor(page);
  if (!entries) return;
  for (const [key, e] of Object.entries(entries)) {
    if (data[e.source] === undefined) continue;
    const v = read(e, data[e.source]);
    if (v === undefined) continue;
    // Tag checks, not instanceof: the frame's elements belong to its own window.
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
        // A select's hidden value input: show the matching option label too.
        const shown = input.type === "hidden" ? input.closest(".v-select")?.querySelector(".v-select__selection") : null;
        if (shown) shown.textContent = label(v);
        if (input.type === "hidden") selectOption(doc, input, label(v));
        const counter = input.closest(".g-input__wrapper")?.querySelector(".v-counter");
        if (counter) counter.textContent = (counter.textContent ?? "").replace(/^\s*\d+/, String([...v].length));
      }
    }
  }
}

/** OF's price for a menu line: "$9.69" (two decimals). */
const dollars = (p: number) => `$${p.toFixed(2)}`;

/** OF's `<span class="b-amount-price m-num">{PRICE}</span> per month` (message_type_price_per_month) into `el`. */
function perMonth(el: Element, price: number) {
  const doc = el.ownerDocument;
  const amount = doc.createElement("span");
  amount.className = "b-amount-price m-num";
  amount.textContent = dollars(price);
  el.replaceChildren(amount, doc.createTextNode(" per month"));
}

/** The "Following price" / "Subscription price and bundles" line: the menu row linking to Subscription with that title. */
function priceLine(doc: Document, title: string): HTMLElement | null {
  // The settings menu has a same-titled link without a line; the page's own row carries it.
  for (const a of doc.querySelectorAll("a[href='/of-manager/settings/subscription']")) {
    const sub = a.querySelector<HTMLElement>(".b-menu-list__subtext");
    if (sub && a.querySelector(".b-menu-list__text")?.textContent?.trim() === title) return sub;
  }
  return null;
}

/** The OBS Stream Key as the mirror shows it: never the key, only that there is one. */
export const STREAM_KEY_MASK = "•".repeat(16);

/**
 * Profile and Fans' price lines: profile's "Subscription price and bundles" says "$P per month, N subscription bundles"
 * (no line while free; module 41290's Ae); fans' "Following price" says "$P per month", or "Free" (free_placeholder), and
 * "1 Free month for referrer" is disabled while free (settings-fans.js). The lines lose data-oi-price, so useOfIdentity
 * (which shows "$5.00 per month" as "Free per month") leaves them be.
 */
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
    if (reward) reward.disabled = !price; // OF's own rule (disabled: !authUser.subscribePrice), not a missing route
  }
}

/**
 * Streaming: OF's OBS CloudBeta server (obs_agora): its Server is settings' streamingRtmpServer. The Stream Key stays
 * masked: its value never enters the page (OF shows it); Reset and both Copy buttons stay disabled.
 */
function obsServer(doc: Document, _base: string, data: SettingsData): void {
  const { streamingRtmpServer: server, streamingRtmpKey: key } = objectOf<{ streamingRtmpServer?: unknown; streamingRtmpKey?: unknown }>(data.settings) ?? {};
  const byLabel = (text: string) => {
    const label = [...doc.querySelectorAll<HTMLLabelElement>("#content label.v-label")].find((l) => l.textContent?.trim() === text);
    return label?.htmlFor ? (doc.getElementById(label.htmlFor) as HTMLInputElement | null) : null;
  };
  const serverField = byLabel("Server");
  if (serverField && typeof server === "string") serverField.value = server;
  const keyField = byLabel("Stream Key");
  if (keyField) keyField.value = typeof key === "string" && key ? STREAM_KEY_MASK : "";
}

/** Watermarks (OF's setDataFromStore): the custom text field holds the model's text, blank when it is the default "OnlyFans.com/<username>". */
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

/** A settings page's extras: the sources it reads beyond its mapped controls', and what OF computes from them on it. */
interface PageExtra {
  sources: SettingsSource[];
  apply(doc: Document, base: string, data: SettingsData, img: (url: string) => string): void;
}
/** Every Account page: its controls disabled, OF's masked phone and the model's email (ofMirrorSettingsPages). */
const ACCOUNT: PageExtra = { sources: [], apply: applyAccount };
/** Page (sub path under settings/, no State page suffix) -> its extras. Each `apply` reads only its own `sources`. */
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
};
/** A page's extras; any other Account page's is ACCOUNT. */
const extraFor = (base: string): PageExtra | null => (Object.hasOwn(PAGE_EXTRAS, base) ? PAGE_EXTRAS[base] : base.startsWith("account/") ? ACCOUNT : null);

/** Draw what OF computes on settings `page` rather than reads into a control (its PAGE_EXTRAS entry). Idempotent. */
export function applyPageExtras(doc: Document, page: string, data: SettingsData, img: (url: string) => string = (u) => u): void {
  const base = page.replace(/\/state-[^/]+$/, "");
  extraFor(base)?.apply(doc, base, data, img);
}

/**
 * OF's settings layout below its LG media query (1004px, module 480343): the menu column renders only on the settings
 * root (`isLgMQ || route Settings`), and a sub-page's header shows its own title, not "Settings" (isSidebarTitle). The
 * capture is the desktop one, so this sheet hides what OF would not render. The root (/of-manager/settings, which on a
 * wide screen shows Edit profile, as OF redirects there) shows only the menu under "Settings".
 */
export const NARROW_CSS = `@media (max-width: 1003.98px) {
html:not(.oi-settings-root) .b-settings__nav { display: none !important; }
html:not(.oi-settings-root) .b-settings__header__left-col .g-page-title { display: none !important; }
html:not(.oi-settings-root) .g-page__header > a.g-page__header__btn { display: none !important; }
html.oi-settings-root .b-settings__content, html.oi-settings-root .g-page__header > :not(.b-settings__header__left-col) { display: none !important; }
}`;

/** OF's narrow layout (below LG): the width a settings page is laid out as a single column under. */
const NARROW = "(max-width: 1003.98px)";

/**
 * Put the narrow-layout sheet in a settings page and mark the root. Narrow, as OF there: the root's menu marks no
 * page current (its route is Settings), and a sub-page's back arrow leads to the settings menu. Idempotent.
 */
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

/**
 * Single-model scope on a settings page: fetch the sources its mapped controls
 * need and apply them to the frame on every load. Otherwise does nothing.
 */
export function useOfSettings(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const root = usePathname() === "/of-manager/settings";
  const page = /^\/of-mirror\/pages\/settings\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const sources = page ? sourcesFor(page) : [];
  const values = useQueries({
    queries: sources.map((s) => ({
      // "me" shares useOfIdentity's cache entry.
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
      applyPageExtras(doc, page, data, (u) => proxyImage(u, accountId));
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => frame.removeEventListener("load", apply);
  }, [frameRef, src, page, key, values, accountId, root]);
}
