"use client";

/**
 * Write-through for the OF settings mirror's toggles and forms beyond the profile page and the welcome switch
 * (those are ofMirrorWrites'). Every body is the one OF's own settings pages send (build 202610091632):
 * - A settings toggle (fans, security, mentions, story, the co-streaming radios) is OF's `saveUserSetting`
 *   (settings-story.js module 289051): a security-section key PATCHes /users/me/settings/security, `allowReplyFrom`
 *   PATCHes /users/settings/story, any other key PATCHes /users/me; each with `{key: value}`.
 * - A notification toggle PATCHes /users/settings/notifications with `{notifications: {<transport>: [{code, value}]}}`
 *   (email's value is 1 or false, a digest's its frequency in hours); email's master switches send `{field: value}`
 *   there too, and switching email off also turns the newsletter off, as OF does.
 * - Watermarks' Save PUTs /users/me/settings/security `{hasWatermarkPhoto, hasWatermarkVideo, watermarkText?,
 *   watermarkPosition}`: watermarkText is the field (prefilled with the custom text) whenever a watermark is on, as OF's
 *   save() (settings-watermarks.js); OF resets a missing or blank one to "OnlyFans.com/<username>".
 * - Subscription's price Save PATCHes /users/me `{subscribePrice}` after a confirm (it moves money).
 * Each of these controls is marked data-oi-wired, so ofMirrorWrites leaves it alone. A toggle saves on change; an
 * error (or no single model selected: "Select a model to save changes") puts it back. A save shows OF's settings toast
 * (SAVED_TOAST), in place. Cancel reloads the page.
 */

import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { applySettings, floatLabel, settingsEntriesFor, SOURCE_PATHS, type SettingsData, type SettingsSource } from "@/lib/ofMirrorSettings";
import { toast } from "@/lib/ofMirrorPost";
import { message, note, SAVED_TOAST, SELECT_MODEL } from "@/lib/ofMirrorWrites";

export interface SettingsWrite {
  method: "PATCH" | "PUT";
  path: string;
  body: Record<string, unknown>;
}

const ME = "/api/of/v2/users/me";
const SECURITY = "/api/of/v2/users/me/settings/security";
const NOTIFICATIONS = "/api/of/v2/users/settings/notifications";
const STORY = "/api/of/v2/users/settings/story";

/** OF's security-section keys (module 289051's list): they PATCH /users/me/settings/security. */
export const SECURITY_KEYS = new Set([
  "isSuggestionsOptOut",
  "phoneOtp",
  "isPrivate",
  "showPostsTips",
  "showFriendsToSubscribers",
  "showSubscribesOffers",
  "showSubscribersCount",
  "isWantComments",
  "isAutoFollowBack",
  "unfollowAutoFollowBack",
  "coStreamingRequestFrom",
  "showMediaCount",
  "isDrmEnabled",
  "requireFaceIdForPayoutUpdate",
]);

/** Email notifications with a frequency (hours) as their value; OF's default is 24. */
const DIGESTS = new Set(["new_likes_digest", "new_posts_digest", "new_unread_chats_messages_digest"]);

/** Settings pages (under settings/) whose mapped toggles save on change. */
export const TOGGLE_PAGES = new Set([
  "fans",
  "security",
  "story",
  "streaming",
  "notifications/mentions",
  "notifications/email",
  "notifications/message",
  "notifications/toast",
  "notifications/webpush",
]);
const WATERMARKS = "security/watermarks";
const WATERMARK_FIELDS = "#hasWatermarkPhoto, #hasWatermarkVideo, #input-watermark-text";
const PRICE_FORM = "form[data-vv-scope='action-info-form']";
const PRICE = `${PRICE_FORM} input[inputmode='decimal']`;

/** OF's saveUserSetting routing for one key. */
export function settingWrite(field: string, value: boolean | string | null): SettingsWrite {
  if (SECURITY_KEYS.has(field)) return { method: "PATCH", path: SECURITY, body: { [field]: value } };
  if (field === "allowReplyFrom") return { method: "PATCH", path: STORY, body: { allowReplyFrom: value } };
  return { method: "PATCH", path: ME, body: { [field]: value } };
}

/** A digest's frequency from the transport's `group=1` body, or OF's default 24. */
function digestHours(groups: unknown, code: string): number {
  if (Array.isArray(groups))
    for (const g of groups as { items?: { code?: string; value?: unknown }[] }[])
      for (const it of g?.items ?? []) if (it?.code === code && typeof it.value === "number" && it.value > 0) return it.value;
  return 24;
}

/** The write for changed control `el` on settings `page`, or null when it is not one of the page's saved toggles. */
export function toggleWrite(page: string, el: HTMLInputElement, data: SettingsData): SettingsWrite | null {
  if (!TOGGLE_PAGES.has(page)) return null;
  const entries = settingsEntriesFor(page);
  const entry = entries && el.id && Object.hasOwn(entries, el.id) ? entries[el.id] : null;
  if (!entry) return null;
  const on = el.checked;
  if (entry.source.startsWith("notifications:")) {
    const transport = entry.source.slice("notifications:".length);
    const code = el.id.slice("toggle_".length);
    const value = transport !== "email" ? on : on && (DIGESTS.has(code) ? digestHours(data[entry.source], code) : 1);
    return { method: "PATCH", path: NOTIFICATIONS, body: { notifications: { [transport]: [{ code, value }] } } };
  }
  if (typeof entry.field !== "string") return page === "story" ? settingWrite("allowReplyFrom", on ? "subscribers" : "nobody") : null;
  if (page === "notifications/email") {
    const body: Record<string, unknown> = { [entry.field]: on };
    if (entry.field === "isEmailNotificationsEnabled" && !on) body.isMonthlyNewsletters = false;
    return { method: "PATCH", path: NOTIFICATIONS, body };
  }
  if (el.type === "radio") return on ? settingWrite(entry.field, el.value) : null;
  // OF's referral switch saves its transform-value: "1 month" or null (settings-fans.js).
  if (entry.field === "recommenderReward") return settingWrite(entry.field, on ? "1 month" : null);
  return settingWrite(entry.field, on);
}

/** Watermarks' Save body: both checkboxes, the typed custom text (when any watermark is on) and the position. */
export function collectWatermarks(doc: Document): Record<string, unknown> {
  const checked = (id: string) => !!doc.querySelector<HTMLInputElement>(`#${id}`)?.checked;
  const body: Record<string, unknown> = { hasWatermarkPhoto: checked("hasWatermarkPhoto"), hasWatermarkVideo: checked("hasWatermarkVideo") };
  // OF sends the field whenever a watermark is on, blank too (OF then uses its default "OnlyFans.com/<username>"):
  // the field shows the current custom text (applyPageExtras), so an untouched Save keeps it. Seen live: a PUT
  // without watermarkText reset "founder" to "OnlyFans.com/<username>".
  const field = doc.querySelector<HTMLInputElement>("#input-watermark-text");
  if (field && (body.hasWatermarkPhoto || body.hasWatermarkVideo)) body.watermarkText = field.value;
  const position = doc.querySelector<HTMLInputElement>("input[name='watermark_position']")?.value;
  if (position) body.watermarkPosition = position;
  return body;
}

/** The price field's text as OF's price (blank: free), or the validation note. */
export function parsePrice(text: string): number | string {
  const s = text.trim().replace(/^\$/, "");
  if (!s) return 0;
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return "Enter a valid price";
  return Number(s);
}

/** The price shown in OF's field: two decimals, blank when free. */
export const priceText = (price: number) => (price > 0 ? price.toFixed(2) : "");

/** A subscription page (not a modal: its Enter belongs to the modal's form) that shows the price form. */
export const isPricePage = (path: string) => /^settings\/subscription(\/[a-z-]+)*$/.test(path) && !/\/modal-\d+$/.test(path);

export interface SettingsWriteHandlers {
  send(w: SettingsWrite): Promise<unknown>;
  confirm(text: string): boolean;
}

/**
 * Wire the settings writes of the mirrored page at `path` (its full path under of-mirror/pages) in `doc`. `data()`:
 * the page's fetched sources (a digest's frequency; a radio put back), `me`: /users/me once loaded (the price).
 * `handlers` null (no single model): a change or Save sends nothing and says "Select a model to save changes".
 */
export function bindSettingsWrites(
  doc: Document,
  path: string,
  data: () => SettingsData,
  me: { subscribePrice?: unknown } | undefined,
  handlers: SettingsWriteHandlers | null,
): () => void {
  if (!path.startsWith("settings/")) return () => {};
  const page = path.slice("settings/".length).replace(/\/state-[^/]+$/, "");
  const entries = TOGGLE_PAGES.has(page) ? (settingsEntriesFor(page) ?? {}) : {};
  for (const id of Object.keys(entries)) doc.getElementById(id)?.setAttribute("data-oi-wired", "");

  // A Save form: watermarks' or the subscription price's.
  const form =
    page === WATERMARKS
      ? { fields: [...doc.querySelectorAll<HTMLInputElement>(WATERMARK_FIELDS)], buttons: doc.querySelectorAll<HTMLButtonElement>("form .g-btn__wrapper button") }
      : isPricePage(path) && doc.querySelector(PRICE)
        ? { fields: [doc.querySelector<HTMLInputElement>(PRICE)!], buttons: doc.querySelectorAll<HTMLButtonElement>(`${PRICE_FORM} .g-btn__wrapper button`) }
        : null;
  const buttons = [...(form?.buttons ?? [])];
  const save = buttons.find((b) => b.textContent?.trim() === "Save") ?? null;
  const cancel = buttons.find((b) => b.textContent?.trim() === "Cancel") ?? null;
  for (const el of [...(form?.fields ?? []), ...buttons]) el.setAttribute("data-oi-wired", "");
  const price = form && page !== WATERMARKS ? form.fields[0] : null;
  if (price && typeof me?.subscribePrice === "number") price.value = priceText(me.subscribePrice);
  const setDirty = (dirty: boolean) => {
    for (const b of [save, cancel]) if (b) b.disabled = !dirty;
  };

  /** Put a toggle back: a checkbox flips; radios show the loaded value again (none checked, as captured, before it loads). */
  const putBack = (el: HTMLInputElement) => {
    if (el.type === "checkbox") return void (el.checked = !el.checked);
    for (const r of doc.querySelectorAll<HTMLInputElement>(`input[type='radio'][name='${el.name}']`)) r.checked = false;
    applySettings(doc, page, data());
  };

  const onChange = (ev: Event) => {
    const el = ev.target as HTMLInputElement;
    if (form?.fields.includes(el)) return setDirty(true);
    const w = el?.tagName === "INPUT" ? toggleWrite(page, el, data()) : null;
    if (!w) return;
    if (!handlers) {
      putBack(el);
      return note(doc, el, SELECT_MODEL);
    }
    handlers.send(w).then(
      () => void toast(doc, SAVED_TOAST),
      (e) => {
        putBack(el);
        note(doc, el, `Could not save: ${message(e)}`, true);
      },
    );
  };

  const onInput = (ev: Event) => {
    const el = ev.target as HTMLInputElement;
    if (!form?.fields.includes(el)) return;
    if (el.id === "input-watermark-text") floatLabel(el, !!el.value); // its label floats clear of the text, as on OF
    setDirty(true);
  };

  const submit = () => {
    if (!save || save.disabled) return;
    if (!handlers) return note(doc, save, SELECT_MODEL);
    let w: SettingsWrite;
    if (price) {
      const p = parsePrice(price.value);
      if (typeof p === "string") return note(doc, save, p, true);
      const ask = p ? `Change the subscription price to $${p.toFixed(2)} per month?` : "Make the subscription free?";
      if (!handlers.confirm(ask)) return;
      w = { method: "PATCH", path: ME, body: { subscribePrice: p } };
    } else w = { method: "PUT", path: SECURITY, body: collectWatermarks(doc) };
    setDirty(false);
    handlers.send(w).then(
      () => void toast(doc, SAVED_TOAST),
      (e) => {
        setDirty(true);
        note(doc, save, `Could not save: ${message(e)}`, true);
      },
    );
  };

  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Node;
    if (save?.contains(t)) {
      ev.preventDefault();
      submit();
    } else if (cancel?.contains(t)) {
      ev.preventDefault();
      doc.defaultView?.location.reload(); // back to the loaded values
    }
  };

  /** Enter in the price field: OF's form submit (ofMirrorWrites already cancels the native one). */
  const onSubmit = (ev: Event) => {
    if (price && (ev.target as Element | null)?.contains?.(price)) submit();
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
  };
}

/** Every settings Mirror page: bind its writes on every frame load (writes only with a single model selected). */
export function useOfSettingsWrites(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const path = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  // The price needs /users/me (useOfIdentity's cache entry); rebinding when it lands fills the field.
  const { data: me } = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && isPricePage(path) });

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !path.startsWith("settings/")) return;
    const data = (): SettingsData => {
      const read = (s: SettingsSource) => qc.getQueryData(s === "me" ? ["of-me", accountId] : ["of-settings", s, accountId]);
      return Object.fromEntries((Object.keys(SOURCE_PATHS) as SettingsSource[]).map((s) => [s, read(s)]));
    };
    const send = (w: SettingsWrite) =>
      (w.method === "PUT" ? relay.put(w.path, w.body, { accountId }) : relay.patch(w.path, w.body, { accountId })).then((r) => {
        qc.invalidateQueries({ queryKey: ["of-me", accountId] });
        qc.invalidateQueries({ queryKey: ["of-settings"] });
        return r;
      });
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const confirm = (text: string) => frame.contentWindow?.confirm(text) ?? false;
      unbind = doc?.body ? bindSettingsWrites(doc, path, data, me, accountId ? { send, confirm } : null) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, accountId, qc, me]);
}
