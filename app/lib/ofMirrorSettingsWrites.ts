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
 * - The switches the mirror draws itself (DRAWN_TOGGLES: Messaging's Tip switch, Security's Fully private) are
 *   saveUserSetting keys too; email's "Update frequency" sends New Likes Summary's digest with the picked hours.
 * - Login sessions' Close all sessions sends OF's DELETE /sessions, no body (settings-sessions.js), after OF's
 *   ModalConfirm says it cannot be undone; Cancel sends nothing. Only with a model picked: a stand-in page in All models
 *   says "Select a model to save changes" (a Lockout control acts for the real scope). A session-lost answer (OF's
 *   "Wrong user.") says to re-link the Creator. The Relay refuses it until the owner's go (ticket 81).
 * - ticket 66: Block by country's and Block by IP's Save PUT their own Relay routes (BLOCKED_COUNTRIES, BLOCKED_IPS:
 *   OF's security PUT with the whole list, ofMirrorBlockLists) after a confirm naming what they block; Block by IP's
 *   Cancel puts the saved list back and sends nothing. Lockout controls: only with a model picked (else the
 *   Select-model note, nothing sent).
 * - Social media's Add button and a button's remove (ticket 69) are ofMirrorProfileLinks': PUT /users/social/buttons
 *   from its form, DELETE /users/social/buttons/{id}; the stand-in page sends as the stand-in.
 * - Things I Like's Create link and a link's delete (ticket 70) are ofMirrorProfileLinks' too: PUT /users/links `{link}`,
 *   DELETE /users/links/{id}.
 * - Streaming's Reset (ticket 76) sends its capture record's request (aborted at the sitting): DELETE
 *   /streams/obs/key?type=<the OBS server the page shows>, no body, after OF's confirm (its captured text); Cancel sends
 *   nothing. A Lockout control like Close all sessions (the real scope only). The settings re-read then carries the new
 *   key: the field keeps the mask (the key never enters the page) and Copy key copies the new one.
 * The new writes (frequency, Close all, Block by country/IP, Reset, the profile links) bind per page through NEW_WRITERS,
 * only with OFM_NEW_WRITES_ENABLED on; each unbind puts the controls it drew Wired back to Not yet.
 * Each of these controls is marked data-oi-wired, so ofMirrorWrites leaves it alone. A toggle saves on change; an
 * error (or no single model selected: "Select a model to save changes") puts it back. A save shows OF's settings toast
 * (SAVED_TOAST), in place. Cancel reloads the page.
 */

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

// ticket 60
/** Switches the mirror draws itself (ofMirrorSettingsPages), per settings page: control id -> saveUserSetting key. */
export const DRAWN_TOGGLES: Record<string, Record<string, string>> = {
  messaging: { messageOnlyFromFriends: "canAcceptMessageOnlyFromFriends" },
  security: { setting_isPrivate: "isPrivate" },
};

/** OF's "Update frequency" menu, in order (live 2026-11-21, docs/of-manager/captures/settings--email-frequency-menu-page.json). */
const OF_FREQUENCIES: { value: number; label: string }[] = [
  { value: 1, label: "Every Hour" },
  { value: 3, label: "3 Hours" },
  { value: 6, label: "6 Hours" },
  { value: 12, label: "12 Hours" },
  { value: 24, label: "24 Hours" },
];
/** The "Update frequency" choices: OF's menu, plus the stored hours (`frequencyLabel`) when OF's list lacks them. */
export const frequencyChoices = (stored: number): { value: number; label: string }[] =>
  OF_FREQUENCIES.some((c) => c.value === stored)
    ? OF_FREQUENCIES
    : [...OF_FREQUENCIES, { value: stored, label: frequencyLabel(stored) }].sort((a, b) => a.value - b.value);

/** New Likes Summary's frequency save: the notifications PATCH the email digest toggle sends, with the picked hours. */
export const frequencyWrite = (hours: number): SettingsWrite => ({
  method: "PATCH",
  path: NOTIFICATIONS,
  body: { notifications: { email: [{ code: "new_likes_digest", value: hours }] } },
});

// ticket 63
/** Close all sessions: OF's DELETE /sessions with no body (settings-sessions.js module 205489, API catalogue). */
export const CLOSE_ALL_WRITE: SettingsWrite = { method: "DELETE", path: "/api/of/v2/sessions" };
/**
 * Its confirm. ASSUMPTION: OF's own texts for it are not in this tree (no capture of the confirm), so the house words say
 * what the story asks: it ends the other sign-ins and cannot be undone (rung 5); a Page capture replaces them.
 */
export const CLOSE_ALL_ASK: Ask = {
  title: "Close all sessions?",
  text: "This signs this account out of OnlyFans everywhere else. This cannot be undone.",
  ok: "Close all sessions",
};
/**
 * The note for a failed Close all sessions: a session-lost answer (OF's "Wrong user.") says to re-link the Creator; the
 * Relay's own backstop (`refused_by_relay`, `_denied` until ticket 81) says it is not available yet.
 */
export const closeAllNote = (e: unknown): string => {
  const m = message(e);
  if (/Wrong user/.test(m)) return describeDeadSession("wrong_user");
  return `Could not close sessions: ${/refused_by_relay/.test(m) ? NOT_YET : m}`;
};

// ticket 76
/** Reset stream key: its capture record's request (DELETE /streams/obs/key?type=<server>, no body). */
export const resetKeyWrite = (server: ObsServer): SettingsWrite => ({ method: "DELETE", path: `/api/of/v2/streams/obs/key?type=${server}` });
/**
 * Its confirm: OF's text (the capture record's confirm_text). ASSUMPTION: the title and the confirm button's words are
 * the house's (the capture kept the text only); a Page capture replaces them.
 */
export const RESET_KEY_ASK: Ask = {
  title: "Reset stream key?",
  text: "Please confirm you want to generate a new key (previous key will no longer be valid)",
  ok: "Reset",
};
/** A failed reset's note; a Relay refusal (`refused_by_relay`: the Live guard, no owner go) says it is not available yet. */
export const resetKeyNote = (e: unknown): string => {
  const m = message(e);
  return `Could not reset the stream key: ${/refused_by_relay/.test(m) ? NOT_YET : m}`;
};

/** The write for changed control `el` on settings `page`, or null when it is not one of the page's saved toggles. */
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
  /** ticket 63: the model is All models' stand-in, not picked: a Lockout control sends nothing. */
  standIn: boolean;
}

/**
 * Wire the settings writes of the mirrored page at `path` (its full path under of-mirror/pages) in `doc`. `data()`:
 * the page's fetched sources (a digest's frequency; a radio put back), `me`: /users/me once loaded (the price).
 * `handlers` null (no single model): a change or Save sends nothing and says "Select a model to save changes".
 * `newWrites` false (OFM_NEW_WRITES_ENABLED off, ofMirrorNewWrites): the new writes' controls (Close all sessions, Block
 * by country / IP, Reset stream key, Social media's and Things I Like's add and remove, email's Update frequency, the
 * drawn Tip and Fully private switches) are not bound: they stay disabled with their Not-yet title, as applyPageExtras
 * draws them with the same flag.
 */
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

  // The page's new write (NEW_WRITERS), bound only with OFM_NEW_WRITES_ENABLED on.
  const sub = path.slice("settings/".length); // a State page binds none
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
    bound.unbind();
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
  };
}

// ── The new writes (OFM_NEW_WRITES_ENABLED) ──────────────────────────────────────────────────────────────────────

/** What a new write's binder (NEW_WRITERS) gets from bindSettingsWrites. */
export interface NewWriteEnv {
  doc: Document;
  /** The settings page (no State page suffix). */
  page: string;
  data: () => SettingsData;
  handlers: SettingsWriteHandlers | null;
  /** A Lockout control may not send: no single model, or All models' stand-in. */
  locked: boolean;
  /** A Lockout control's handlers, or (locked) null with the Select-model note at `anchor`. */
  unlocked(anchor: Element): SettingsWriteHandlers | null;
}
/** A bound new write: its unbind (a control it drew Wired goes back to Not yet); `toggled`: a saved toggle on its page
 *  changed or was put back. */
export interface NewWriteBinding {
  unbind(): void;
  toggled?(el: HTMLInputElement): void;
}

/** Email's "Update frequency" (New Likes Summary's digest hours), re-drawn as the digest switches; a pick shows it at
 *  once and saves, a failure puts the old one back. Drawn by applyPageExtras (drawFrequency). */
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

/** A Lockout button `b` (the real scope only): OF's confirm `ask`, then `write()`; `ok` on success, else `failNote`. */
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

/** tickets 69, 70: Social media's buttons and Things I Like's links (ofMirrorProfileLinks): add and remove, each sent as is.
 *  Switch off: the add buttons stay as captured; drawLinks draws each row's remove Not yet (applyPageExtras). */
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

/** Settings sub path (exact: a State page binds none) -> its new write's binder. */
const NEW_WRITERS: Record<string, (env: NewWriteEnv) => NewWriteBinding> = {
  // ticket 60
  "notifications/email": bindFrequency,
  // ticket 63: Login sessions' Close all sessions
  "account/sessions": (env) => bindLockoutButton(env, closeAllSessions(env.doc, true), CLOSE_ALL_ASK, () => CLOSE_ALL_WRITE, () => undefined, closeAllNote),
  // ticket 66
  "security/block_by_country": bindBlockByCountry,
  "security/block_by_ip": bindBlockByIp,
  // ticket 76: Streaming's Reset stream key, for the OBS server the page shows
  streaming: (env) =>
    bindLockoutButton(env, streamKeyReset(env.doc, true), RESET_KEY_ASK, () => resetKeyWrite(shownObsServer(env.doc)), () => void toast(env.doc, SAVED_TOAST), resetKeyNote),
  // tickets 69, 70
  "social-media": bindLinks,
  links: bindLinks,
};

/** Every settings Mirror page: bind its writes on every frame load (writes only with a single model selected). */
export function useOfSettingsWrites(frameRef: RefObject<HTMLIFrameElement | null>, src: string, standIn: string | null): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const path = /^\/of-mirror\/pages\/(.+)\.html$/.exec(src)?.[1] ?? "";
  // The price needs /users/me (useOfIdentity's cache entry); rebinding when it lands fills the field.
  const { data: me } = useQuery({ ...ofMeQuery(accountId), enabled: !!accountId && isPricePage(path) });
  const newWrites = useOfmNewWrites(path.startsWith("settings/"), accountId); // OFM_NEW_WRITES_ENABLED (ofMirrorNewWrites)

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
