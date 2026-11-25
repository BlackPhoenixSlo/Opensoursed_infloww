"use client";


import { useEffect, type RefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useScope } from "@/contexts/ScopeContext";
import { relay } from "@/lib/relay";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { floatLabel } from "@/lib/ofMirrorDom";
import { applySettings, settingsEntriesFor, SOURCE_PATHS, type SettingsData, type SettingsSource } from "@/lib/ofMirrorSettings";
import { toast } from "@/lib/ofMirrorPost";
import { message, note, NOT_YET, ofConfirm, SAVED_TOAST, SELECT_MODEL, type Ask } from "@/lib/ofMirrorWrites";
import { describeDeadSession } from "@/lib/utils";
import { closeMenu, showMenu } from "@/lib/ofMirrorMenu";
import { bindProfileLinks } from "@/lib/ofMirrorProfileLinks";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";
import { shownObsServer, type ObsServer } from "@/lib/ofMirrorObsServer";
import { closeAllSessions, streamKeyReset, DIGEST_TOGGLE, digestHours, drawFrequency, frequencyLabel, frequencySelect } from "@/lib/ofMirrorSettingsPages";
import { bindBlockByCountry, bindBlockByIp, NONE } from "@/lib/ofMirrorBlockLists";
import { markNotYet } from "@/lib/ofMirrorTooltip";

export interface SettingsWrite {
  method: "PATCH" | "PUT" | "DELETE";
  path: string;
  body?: Record<string, unknown>;
}

const ME = "/api/of/v2/users/me";
const SECURITY = "/api/of/v2/users/me/settings/security";
const NOTIFICATIONS = "/api/of/v2/users/settings/notifications";
const STORY = "/api/of/v2/users/settings/story";

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

const DIGESTS = new Set(["new_likes_digest", "new_posts_digest", "new_unread_chats_messages_digest"]);

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

export function settingWrite(field: string, value: boolean | string | null): SettingsWrite {
  if (SECURITY_KEYS.has(field)) return { method: "PATCH", path: SECURITY, body: { [field]: value } };
  if (field === "allowReplyFrom") return { method: "PATCH", path: STORY, body: { allowReplyFrom: value } };
  return { method: "PATCH", path: ME, body: { [field]: value } };
}

export const DRAWN_TOGGLES: Record<string, Record<string, string>> = {
  messaging: { messageOnlyFromFriends: "canAcceptMessageOnlyFromFriends" },
  security: { setting_isPrivate: "isPrivate" },
};

const OF_FREQUENCIES: { value: number; label: string }[] = [
  { value: 1, label: "Every Hour" },
  { value: 3, label: "3 Hours" },
  { value: 6, label: "6 Hours" },
  { value: 12, label: "12 Hours" },
  { value: 24, label: "24 Hours" },
];
export const frequencyChoices = (stored: number): { value: number; label: string }[] =>
  OF_FREQUENCIES.some((c) => c.value === stored)
    ? OF_FREQUENCIES
    : [...OF_FREQUENCIES, { value: stored, label: frequencyLabel(stored) }].sort((a, b) => a.value - b.value);

export const frequencyWrite = (hours: number): SettingsWrite => ({
  method: "PATCH",
  path: NOTIFICATIONS,
  body: { notifications: { email: [{ code: "new_likes_digest", value: hours }] } },
});

export const CLOSE_ALL_WRITE: SettingsWrite = { method: "DELETE", path: "/api/of/v2/sessions" };
export const CLOSE_ALL_ASK: Ask = {
  title: "Close all sessions?",
  text: "This signs this account out of OnlyFans everywhere else. This cannot be undone.",
  ok: "Close all sessions",
};
export const closeAllNote = (e: unknown): string => {
  const m = message(e);
  if (/Wrong user/.test(m)) return describeDeadSession("wrong_user");
  return `Could not close sessions: ${/refused_by_relay/.test(m) ? NOT_YET : m}`;
};

export const resetKeyWrite = (server: ObsServer): SettingsWrite => ({ method: "DELETE", path: `/api/of/v2/streams/obs/key?type=${server}` });
export const RESET_KEY_ASK: Ask = {
  title: "Reset stream key?",
  text: "Please confirm you want to generate a new key (previous key will no longer be valid)",
  ok: "Reset",
};
export const resetKeyNote = (e: unknown): string => {
  const m = message(e);
  return `Could not reset the stream key: ${/refused_by_relay/.test(m) ? NOT_YET : m}`;
};

export function toggleWrite(page: string, el: HTMLInputElement, data: SettingsData): SettingsWrite | null {
  const drawn = Object.hasOwn(DRAWN_TOGGLES, page) && el.id && Object.hasOwn(DRAWN_TOGGLES[page], el.id) ? DRAWN_TOGGLES[page][el.id] : null;
  if (drawn) return settingWrite(drawn, el.checked);
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
  // OF's referral switch saves its transform-value: "1 month" or null.
  if (entry.field === "recommenderReward") return settingWrite(entry.field, on ? "1 month" : null);
  return settingWrite(entry.field, on);
}

export function collectWatermarks(doc: Document): Record<string, unknown> {
  const checked = (id: string) => !!doc.querySelector<HTMLInputElement>(`#${id}`)?.checked;
  // Seen live: a PUT without watermarkText reset the custom text to "OnlyFans.com/<username>"; send the field whenever a watermark is on.
  const body: Record<string, unknown> = { hasWatermarkPhoto: checked("hasWatermarkPhoto"), hasWatermarkVideo: checked("hasWatermarkVideo") };
  const field = doc.querySelector<HTMLInputElement>("#input-watermark-text");
  if (field && (body.hasWatermarkPhoto || body.hasWatermarkVideo)) body.watermarkText = field.value;
  const position = doc.querySelector<HTMLInputElement>("input[name='watermark_position']")?.value;
  if (position) body.watermarkPosition = position;
  return body;
}

export function parsePrice(text: string): number | string {
  const s = text.trim().replace(/^\$/, "");
  if (!s) return 0;
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return "Enter a valid price";
  return Number(s);
}

export const priceText = (price: number) => (price > 0 ? price.toFixed(2) : "");

export const isPricePage = (path: string) => /^settings\/subscription(\/[a-z-]+)*$/.test(path) && !/\/modal-\d+$/.test(path);

export interface SettingsWriteHandlers {
  send(w: SettingsWrite): Promise<unknown>;
  confirm(text: string): boolean;
  standIn: boolean;
}

export function bindSettingsWrites(
  doc: Document,
  path: string,
  data: () => SettingsData,
  me: { subscribePrice?: unknown } | undefined,
  handlers: SettingsWriteHandlers | null,
  newWrites: boolean,
): () => void {
  if (!path.startsWith("settings/")) return () => {};
  const page = path.slice("settings/".length).replace(/\/state-[^/]+$/, "");
  const entries = TOGGLE_PAGES.has(page) ? (settingsEntriesFor(page) ?? {}) : {};
  for (const id of Object.keys(entries)) doc.getElementById(id)?.setAttribute("data-oi-wired", "");

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

  const putBack = (el: HTMLInputElement) => {
    if (el.type === "checkbox") return void (el.checked = !el.checked);
    for (const r of doc.querySelectorAll<HTMLInputElement>(`input[type='radio'][name='${el.name}']`)) r.checked = false;
    applySettings(doc, page, data());
  };

  const sub = path.slice("settings/".length);
  const locked = !handlers || handlers.standIn;
  const env: NewWriteEnv = {
    doc,
    page,
    data,
    handlers,
    locked,
    unlocked: (anchor) => (locked ? (note(doc, anchor, SELECT_MODEL), null) : handlers),
  };
  const bound = newWrites && Object.hasOwn(NEW_WRITERS, sub) ? NEW_WRITERS[sub](env) : NONE;

  const onChange = (ev: Event) => {
    const el = ev.target as HTMLInputElement;
    if (form?.fields.includes(el)) return setDirty(true);
    const drawn = Object.hasOwn(DRAWN_TOGGLES, page) && Object.hasOwn(DRAWN_TOGGLES[page], el?.id ?? "");
    const w = el?.tagName === "INPUT" && (newWrites || !drawn) ? toggleWrite(page, el, data()) : null;
    if (!w) return;
    if (!handlers) {
      putBack(el);
      return note(doc, el, SELECT_MODEL);
    }
    bound.toggled?.(el);
    handlers.send(w).then(
      () => void toast(doc, SAVED_TOAST),
      (e) => {
        putBack(el);
        bound.toggled?.(el);
        note(doc, el, `Could not save: ${message(e)}`, true);
      },
    );
  };

  const onInput = (ev: Event) => {
    const el = ev.target as HTMLInputElement;
    if (!form?.fields.includes(el)) return;
    if (el.id === "input-watermark-text") floatLabel(el, !!el.value);
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
      doc.defaultView?.location.reload();
    }
  };

  const onSubmit = (ev: Event) => {
    if (price && (ev.target as Element | null)?.contains?.(price)) submit();
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    bound.unbind();
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
  };
}


export interface NewWriteEnv {
  doc: Document;
  page: string;
  data: () => SettingsData;
  handlers: SettingsWriteHandlers | null;
  locked: boolean;
  unlocked(anchor: Element): SettingsWriteHandlers | null;
}
export interface NewWriteBinding {
  unbind(): void;
  toggled?(el: HTMLInputElement): void;
}

function bindFrequency({ doc, data, handlers }: NewWriteEnv): NewWriteBinding {
  const freq = frequencySelect(doc);
  if (!freq) return NONE;
  const shownHours = () => Number(freq.querySelector<HTMLInputElement>("input[type='hidden']")?.value) || 24;
  const open = () => {
    if (freq.classList.contains("v-input--is-disabled")) return;
    const was = shownHours();
    const stored = digestHours(data()["notifications:email"], "new_likes_digest");
    const options = frequencyChoices(stored).map((c) => ({ value: String(c.value), label: c.label }));
    showMenu(doc, freq, [{ name: "frequency", radio: false, value: String(was), options }], (_g, v) => {
      const hours = Number(v);
      if (hours === was) return;
      if (!handlers) return note(doc, freq, SELECT_MODEL);
      drawFrequency(doc, hours, true);
      handlers.send(frequencyWrite(hours)).then(
        () => void toast(doc, SAVED_TOAST),
        (e) => {
          drawFrequency(doc, was, true);
          note(doc, freq, `Could not save: ${message(e)}`, true);
        },
      );
    });
  };
  const onClick = (ev: MouseEvent) => {
    if (!freq.contains(ev.target as Node)) return;
    ev.preventDefault();
    open();
  };
  doc.addEventListener("click", onClick);
  return {
    toggled: (el) => {
      if (el.id === DIGEST_TOGGLE) drawFrequency(doc, shownHours(), true);
    },
    unbind: () => {
      doc.removeEventListener("click", onClick);
      closeMenu(doc);
    },
  };
}

function bindLockoutButton(
  { doc, unlocked }: NewWriteEnv,
  b: HTMLButtonElement | null,
  ask: Ask,
  write: () => SettingsWrite,
  ok: () => void,
  failNote: (e: unknown) => string,
): NewWriteBinding {
  if (!b) return NONE;
  const run = async () => {
    const h = unlocked(b);
    if (!h || !(await ofConfirm(doc, ask))) return;
    h.send(write()).then(ok, (e) => note(doc, b, failNote(e), true));
  };
  const onClick = (ev: MouseEvent) => {
    if (!b.contains(ev.target as Node)) return;
    ev.preventDefault();
    void run();
  };
  doc.addEventListener("click", onClick);
  return {
    unbind: () => {
      doc.removeEventListener("click", onClick);
      markNotYet(b);
    },
  };
}

function bindLinks({ doc, page, data, handlers }: NewWriteEnv): NewWriteBinding {
  return {
    unbind: bindProfileLinks(doc, page, handlers, {
      saved: () => void toast(doc, SAVED_TOAST),
      fail: (anchor, text) => note(doc, anchor, text, true),
      selectModel: (anchor) => note(doc, anchor, SELECT_MODEL),
      message,
    }, () => data().init),
  };
}

const NEW_WRITERS: Record<string, (env: NewWriteEnv) => NewWriteBinding> = {
  "notifications/email": bindFrequency,
  "account/sessions": (env) => bindLockoutButton(env, closeAllSessions(env.doc, true), CLOSE_ALL_ASK, () => CLOSE_ALL_WRITE, () => undefined, closeAllNote),
  "security/block_by_country": bindBlockByCountry,
  "security/block_by_ip": bindBlockByIp,
  streaming: (env) =>
    bindLockoutButton(env, streamKeyReset(env.doc, true), RESET_KEY_ASK, () => resetKeyWrite(shownObsServer(env.doc)), () => void toast(env.doc, SAVED_TOAST), resetKeyNote),
  "social-media": bindLinks,
  links: bindLinks,
};

export function useOfSettingsWrites(frameRef: RefObject<HTMLIFrameElement | null>, src: string, standIn: string | null): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const path = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  const { data: me } = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && isPricePage(path) });
  const newWrites = useOfmNewWrites(path.startsWith("settings/"), accountId);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !path.startsWith("settings/")) return;
    const data = (): SettingsData => {
      const read = (s: SettingsSource) => qc.getQueryData(s === "me" ? ["of-me", accountId] : ["of-settings", s, accountId]);
      return Object.fromEntries((Object.keys(SOURCE_PATHS) as SettingsSource[]).map((s) => [s, read(s)]));
    };
    const send = (w: SettingsWrite) =>
      (w.method === "DELETE"
        ? relay.delete(w.path, { accountId })
        : w.method === "PUT"
          ? relay.put(w.path, w.body, { accountId })
          : relay.patch(w.path, w.body, { accountId })
      ).then((r) => {
        qc.invalidateQueries({ queryKey: ["of-me", accountId] });
        qc.invalidateQueries({ queryKey: ["of-settings"] });
        return r;
      });
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const confirm = (text: string) => frame.contentWindow?.confirm(text) ?? false;
      unbind = doc?.body ? bindSettingsWrites(doc, path, data, me, accountId ? { send, confirm, standIn: !!standIn } : null, newWrites) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, accountId, qc, me, standIn, newWrites]);
}
