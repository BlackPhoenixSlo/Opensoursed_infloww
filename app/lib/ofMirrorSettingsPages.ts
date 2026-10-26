/**
 * What OF computes on its Account, Messaging and Security settings pages rather than reads into a control (build
 * 202610091632), drawn by ofMirrorSettings' applyPageExtras (its PAGE_EXTRAS table names each page's sources):
 * - account/*: email, password, phone, 2FA, sessions, linked accounts and deletion are never written here, so every
 *   control there stays disabled with the house tooltip. Account's Phone number line is OF's "******<last 4>"; its
 *   Email line, Email's "Current email" field and Two Step Authentication's passwordless note are users/me's email, and
 *   the field's hint OF's "E-mail <email> is verified" when it is (OF's not-verified error has no English text in the
 *   capture, so none is shown). Login sessions lists GET /sessions' rows as OF's (loginSessions), read-only.
 * - messaging: the Tip switch while free, and the welcome message under its switch (both read-only).
 * - security: the "Fully private profile" switch for a performer whose page is not adult content (read-only).
 */

import type { OFMedia } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { bubbleClass, chatMedia, chatMediaTemplate, clock, fillSlot, htmlLines, objectOf } from "@/lib/ofMirrorData";
import type { SettingsData } from "@/lib/ofMirrorSettings";
import { ELSEWHERE } from "@/lib/ofMirrorTooltip";
import { BRAND_NAME } from "@/lib/brand";

/** The house tooltip of a control Inflowwww never writes (ofMirrorWrites' NOT_YET; repeated: that module imports ofMirrorSettings, which imports this one). */
const NOT_YET = `Not available in ${BRAND_NAME} yet`;

/** OF's masked phone (settings-advanced.js): the last four digits behind six stars. */
const maskPhone = (last4: string) => `******${last4}`;

/** Every Account page (account and account/*): see the header. */
export function applyAccount(doc: Document, base: string, data: SettingsData): void {
  const last4 = objectOf<{ phoneLast4?: unknown }>(data.settings)?.phoneLast4;
  const phone = typeof last4 === "string" && last4 ? maskPhone(last4) : null;
  if (phone && base === "account/phone") connectedPhone(doc, phone);
  // Two Step Authentication's Verification via SMS help: OF's "Phone ******<last 4>".
  const sms = doc.getElementById("otp_phone_settings")?.closest(".g-input__wrapper");
  if (phone && base === "account/2fa" && sms) {
    const help = sms.querySelector(".g-input__help") ?? doc.createElement("p");
    help.className = "g-input__help";
    help.textContent = `Phone ${phone}`;
    if (!help.isConnected) fillSlot(sms, "append", help);
  }
  for (const el of doc.querySelectorAll<HTMLInputElement | HTMLButtonElement>("#content input, #content button, #content textarea, #content select")) {
    el.disabled = true;
    if (!el.title) el.title = NOT_YET;
  }
  // OF's Phone number line, none without a phone.
  const row = doc.querySelector("#content a[href='/of-manager/settings/account/phone']");
  if (row && phone) {
    const sub = row.querySelector(".b-menu-list__subtext") ?? doc.createElement("div");
    sub.className = "b-menu-list__subtext";
    sub.textContent = phone;
    if (!sub.isConnected) row.querySelector(".b-menu-list__text")?.after(sub);
  }
  const { email, isEmailChecked } = objectOf<{ email?: unknown; isEmailChecked?: unknown }>(data.me) ?? {};
  if (typeof email === "string" && email) {
    const line = doc.querySelector("#content a[href='/of-manager/settings/account/email'] .b-menu-list__subtext");
    if (line) line.textContent = email;
    // Two Step Authentication's passwordless note: "Email: <b>email</b>".
    for (const b of doc.querySelectorAll("#content .alert-text-wrapper b"))
      if (/Email:\s*$/.test(b.previousSibling?.textContent ?? "")) b.textContent = email;
    const field = doc.getElementById("authUser_email") as HTMLInputElement | null;
    if (field) {
      field.value = email;
      const help = field.closest(".v-input")?.querySelector(".g-input__help");
      help?.querySelector("[data-oi-hint]")?.remove();
      if (help && isEmailChecked === true) {
        const hint = doc.createElement("div");
        hint.setAttribute("data-oi-hint", "");
        hint.textContent = `E-mail ${email} is verified`;
        if (help.firstChild) help.firstChild.after(hint);
        else help.append(hint);
      }
    }
  }
  if (base === "account/sessions" && Array.isArray(data.sessions)) loginSessions(doc, data.sessions as LoginSession[]);
}

/**
 * Messaging (settings-messaging.js): the Tip switch while the subscription is free, and the welcome message
 * (reply_on_subscribe template; none when the model cannot chat). Until users/me/settings is read (or when it failed)
 * the tip row and the welcome's on/off look are not drawn.
 */
export function applyMessaging(doc: Document, _base: string, data: SettingsData, img: (url: string) => string): void {
  const me = objectOf<{ subscribePrice?: unknown; canChat?: unknown }>(data.me);
  if (!me) return;
  const settings = objectOf<{ canAcceptMessageOnlyFromFriends?: unknown; replyOnSubscribe?: unknown }>(data.settings);
  if (settings) tipRow(doc, !(Number(me.subscribePrice) > 0), settings.canAcceptMessageOnlyFromFriends);
  const list = Array.isArray(data.templates) ? (data.templates as Welcome[]) : null;
  if (list) welcomeTemplate(doc, me.canChat === false ? null : (list.find((t) => t?.template === "reply_on_subscribe") ?? null), settings ? settings.replyOnSubscribe === true : null, img);
}

/**
 * Security (settings-security.js): "Fully private profile" for a performer whose page is not adult content. Until
 * users/me/settings is read (or when it failed) the row is not drawn.
 */
export function applySecurity(doc: Document, _base: string, data: SettingsData): void {
  const me = objectOf<{ isPerformer?: unknown; isAdultContent?: unknown }>(data.me);
  const settings = objectOf<{ isPrivate?: unknown }>(data.settings);
  if (!me || !settings) return;
  privateRow(doc, me.isPerformer === true && me.isAdultContent === false, settings.isPrivate);
}

/** A login session as OF's GET /sessions lists it (settings-sessions.js). */
export interface LoginSession {
  sessionId?: unknown;
  client?: unknown;
  os?: unknown;
  brand?: unknown;
  ipAddress?: unknown;
  countryName?: unknown;
  loginMessage?: unknown;
  lastActivity?: unknown;
  isCurrent?: unknown;
}

const str = (v: unknown) => (typeof v === "string" || typeof v === "number" ? String(v) : "");

/** OF's utils-time "setting-sessions" in English: dayjs `M/D/YY h:mm a` in local time ("10/9/26 3:04 pm"). */
function sessionTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()}/${String(d.getFullYear() % 100).padStart(2, "0")} ${clock(d)}`;
}

/**
 * Account > Login sessions as OF draws them (settings-sessions.js): the current session first ("Active now", "<ip> •
 * <country>"), above OF's Close all sessions row, then the others in their own list (last activity, "<ip> - <country>"),
 * no other list when there are none. Read-only: Close all sessions stays disabled with the house tooltip (the generator's)
 * and nothing here ends a session. Idempotent.
 */
function loginSessions(doc: Document, sessions: LoginSession[]) {
  for (const old of doc.querySelectorAll("[data-oi-session]")) old.remove();
  const [first, second] = doc.querySelectorAll<HTMLElement>("#content .b-sessions-list");
  if (!first) return;
  const row = (s: LoginSession, current: boolean) => {
    const r = doc.createElement("div");
    r.className = "b-settings__row m-session-row g-border-bottom";
    r.setAttribute("data-oi-session", "");
    const client = doc.createElement("strong");
    client.textContent = str(s.client);
    const time = doc.createElement("div");
    if (current) {
      time.className = "session-time m-online g-blue";
      time.textContent = " Active now ";
    } else {
      time.className = "session-time";
      const span = doc.createElement("span");
      span.title = "";
      span.textContent = ` ${typeof s.lastActivity === "number" ? sessionTime(s.lastActivity) : ""} `;
      time.append(span);
    }
    const where = doc.createElement("div");
    where.className = "b-session-location";
    where.textContent = ` ${str(s.ipAddress)} ${current ? "•" : "-"} ${str(s.countryName)} `;
    r.append(client, `, ${str(s.os)}${s.brand ? `, ${str(s.brand)}` : ""} `, time, where);
    if (s.loginMessage) {
      const note = doc.createElement("div");
      note.textContent = ` ${str(s.loginMessage)} `;
      r.append(note);
    }
    return r;
  };
  const current = sessions.find((s) => s?.isCurrent === true);
  if (current) first.prepend(row(current, true));
  const others = sessions.filter((s) => s && s.isCurrent !== true);
  if (second) {
    second.style.display = others.length ? "" : "none";
    const block = second.querySelector(".b-settings__block") ?? second;
    block.append(...others.map((s) => row(s, false)));
  }
}

/** OF's phone-setting-block with a phone (its showConnectedNumber view): the masked number read-only, Delete, Update phone. */
const CONNECTED_PHONE = `<div><div class="g-input__wrapper b-settings__spacer"><div data-v-5684fe78="" class="g-input__wrapper input-text-field m-reset-bottom-gap"><div data-v-5684fe78="" class="m-filled"><div data-v-5684fe78="" class="v-input form-control g-input mb-0 v-input--is-label-active v-input--is-dirty v-input--is-readonly theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 143.25px;"><span class="notranslate">\u200b</span></legend></fieldset><div class="v-text-field__slot"><label for="connected_phone_number" class="v-label v-label--active theme--light" style="left: 0px; right: auto; position: absolute;">Connected phone number</label><input at-attr="input" autocomplete="on" name="" tabindex="0" id="connected_phone_number" readonly="readonly" type="text"></div></div><div class="v-text-field__details"><div class="v-messages theme--light"><div class="v-messages__wrapper"></div></div></div></div><div class="v-input__append-outer"><div data-v-5684fe78="" class="g-input__help"><!----><div data-oi-hint=""></div><!----></div><!----></div></div></div><!----></div></div><div class="b-settings__row g-btn__wrapper"><button type="button" class="g-btn m-rounded m-border m-danger m-sm"> Delete </button><button type="button" class="g-btn m-rounded m-border m-sm"> Update phone </button></div></div>`;

/** Account > Phone number for a model with a phone, as OF draws it (`masked`: maskPhone). Idempotent. */
function connectedPhone(doc: Document, masked: string) {
  const block = doc.querySelector("#content .phone-setting-block");
  if (!block) return;
  const t = doc.createElement("template");
  t.innerHTML = CONNECTED_PHONE;
  block.replaceChildren(t.content);
  (block.querySelector("#connected_phone_number") as HTMLInputElement).value = masked;
  block.querySelector("[data-oi-hint]")!.textContent = `Phone number ${masked} is verified`;
}

/** A switch row like `like` (an OF checkbox-o-f toggle) with its own id/name and label, disabled with the house tooltip. */
function toggleLike(like: Element, id: string, labelText: string, value: unknown): Element {
  const row = like.cloneNode(true) as Element;
  row.querySelector(".g-input__label")!.firstChild!.textContent = labelText;
  const input = row.querySelector("input")!;
  input.id = id;
  input.name = id;
  const sw = row.querySelector("label.b-checkbox-switcher")!;
  sw.setAttribute("for", id);
  sw.setAttribute("at-attr", id);
  input.checked = value === true;
  input.disabled = true;
  input.title = NOT_YET;
  sw.setAttribute("title", NOT_YET);
  return row;
}

/**
 * OF's Messaging "Don't accept messages without a Tip from free followers whom you don't follow back" (settings-messaging.js:
 * only while the subscription is free; its value settings' canAcceptMessageOnlyFromFriends), in its own list before
 * Welcome message. Never written here: disabled. Idempotent.
 */
function tipRow(doc: Document, shown: boolean, value: unknown) {
  const id = "messageOnlyFromFriends";
  const old = doc.getElementById(id)?.closest(".b-menu-list");
  const like = doc.getElementById("autoMessage")?.closest(".g-input__wrapper");
  if (!shown || !like) {
    old?.replaceWith(doc.createComment(""));
    return;
  }
  const list = doc.createElement("div");
  list.className = "b-menu-list";
  list.append(toggleLike(like, id, "Don't accept messages without a Tip from free followers whom you don't follow back", value));
  if (old) return void old.replaceWith(list);
  const form = like.closest("form");
  if (form) fillSlot(form, "before", list);
}

/**
 * OF's welcome message under its switch (auto-message-item): the reply_on_subscribe template's text in a chat bubble,
 * grayed while the switch is off (`on` null: settings not read, neither look), then its Delete and Edit, which are never run here (disabled, house tooltip).
 * Its media (OF's TemplatesItem: a media wrapper above the text, the message m-has-media m-photo) are drawn read-only,
 * each as its still (ofMedia's stillUrl: the preview, a video's poster) through `img`; one with no still (a voice
 * note) is not drawn. The price is not drawn. `tpl` null: none (OF's, when there is no template or the model cannot
 * chat). Idempotent.
 */
interface Welcome {
  template?: unknown;
  text?: unknown;
  media?: unknown;
}
function welcomeTemplate(doc: Document, tpl: Welcome | null, on: boolean | null, img: (url: string) => string) {
  for (const old of doc.querySelectorAll("[data-oi-welcome]")) old.remove();
  const like = doc.getElementById("autoMessage")?.closest(".g-input__wrapper");
  if (!tpl || !like) return;
  const V = "data-v-20366c0c";
  const div = (cls: string) => {
    const x = doc.createElement("div");
    x.className = cls;
    x.setAttribute(V, "");
    return x;
  };
  const box = div("b-settings__message");
  box.setAttribute("data-oi-welcome", "");
  if (on !== null) box.classList.toggle("g-disabled", !on);
  const stills = (Array.isArray(tpl.media) ? (tpl.media as OFMedia[]) : []).map((x) => ({ x, url: stillUrl(x) })).filter((s) => s.url);
  const lines = htmlLines(typeof tpl.text === "string" ? tpl.text : "");
  const hasText = lines.some((l) => l.trim());
  const msg = div(bubbleClass({ media: !!stills.length, photo: !!stills.length, text: hasText || !stills.length, fromMe: true }));
  const content = div("b-chat__message__content");
  const body = div("b-chat__message__body");
  const mediaTpl = chatMediaTemplate(doc, null);
  for (const { x, url } of stills) {
    const media = chatMedia(mediaTpl, x, img(url!));
    for (const el of [media, ...media.querySelectorAll("div")]) el.setAttribute(V, "");
    // Its own aspect, full width (OF's media area sizes itself from the media's; this has no size area).
    media.querySelector("img")!.style.cssText = "display:block;width:100%;height:auto";
    body.append(media);
  }
  const wrap = div("b-chat__message__text-wrapper");
  wrap.setAttribute("at-attr", "message_text");
  const textBox = div("b-chat__message__text m-message-content-bg m-possible-markdown m-break-word-default");
  for (const t of lines.length ? lines : [""]) {
    const p = doc.createElement("p");
    p.textContent = t;
    textBox.append(p);
  }
  wrap.append(textBox);
  if (hasText || !stills.length) body.append(wrap);
  content.append(body);
  msg.append(content);
  box.append(msg);
  const row = doc.createElement("div");
  row.className = "b-settings__row b-settings__text-block g-btn__wrapper g-border-bottom";
  row.setAttribute("data-oi-welcome", "");
  for (const [label, danger] of [["Delete", true], ["Edit", false]] as const) {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = `g-btn m-border m-rounded m-sm m-reset-width${danger ? " m-danger" : ""}`;
    b.textContent = ` ${label} `;
    b.disabled = true;
    b.title = ELSEWHERE.welcome;
    row.append(b);
  }
  fillSlot(like, "after", box);
  box.after(row);
}

/**
 * OF's Security "Fully private profile" switch (settings-security.js: a performer's, unless isAdultContent), with its
 * "Text will be hidden" help, in its place after Show activity status. Its value is settings' isPrivate; it is never
 * written here, so it is disabled with the house tooltip. Idempotent; `shown` false takes it out again.
 */
function privateRow(doc: Document, shown: boolean, value: unknown) {
  const old = doc.getElementById("setting_isPrivate")?.closest(".g-input__wrapper");
  const after = doc.getElementById("setting_isVisibleOnline")?.closest(".g-input__wrapper");
  if (!shown || !after) {
    old?.replaceWith(doc.createComment(""));
    return;
  }
  const row = toggleLike(after, "setting_isPrivate", "Fully private profile", value);
  row.querySelector("input")!.name = "isPrivate";
  row.querySelector("label.b-checkbox-switcher")!.setAttribute("at-attr", "isPrivate");
  const help = doc.createElement("p");
  help.className = "g-input__help";
  help.textContent = "Text will be hidden";
  fillSlot(row, "append", help);
  if (old) return void old.replaceWith(row);
  // OF's v-if slot (an empty comment) right after Show activity status.
  fillSlot(after, "after", row);
}
