import type { OFMedia } from "@/lib/relay";
import { stillUrl } from "@/lib/ofMedia";
import { bubbleClass, chatMedia, chatMediaTemplate } from "@/lib/ofMirrorDataChats";
import { clock, fillSlot, floatLabel, htmlLines, make, objectOf } from "@/lib/ofMirrorDom";
import type { SettingsData } from "@/lib/ofMirrorSettings";
import { ELSEWHERE, markNotYet, markWired, NOT_YET } from "@/lib/ofMirrorTooltip";

const maskPhone = (last4: string) => `******${last4}`;

export function applyAccount(doc: Document, base: string, data: SettingsData, _img: unknown, writable: boolean): void {
  const last4 = objectOf<{ phoneLast4?: unknown }>(data.settings)?.phoneLast4;
  const phone = typeof last4 === "string" && last4 ? maskPhone(last4) : null;
  if (phone && base === "account/phone") connectedPhone(doc, phone);
  const sms = doc.getElementById("otp_phone_settings")?.closest(".g-input__wrapper");
  if (phone && base === "account/2fa" && sms) {
    const help = sms.querySelector(".g-input__help") ?? doc.createElement("p");
    help.className = "g-input__help";
    help.textContent = `Phone ${phone}`;
    if (!help.isConnected) fillSlot(sms, "append", help);
  }
  if (base === "account/sessions") closeAllSessions(doc, writable);
  for (const el of doc.querySelectorAll<HTMLInputElement | HTMLButtonElement>("#content input, #content button, #content textarea, #content select")) {
    el.disabled = !el.hasAttribute("data-oi-wired");
    if (!el.title) el.title = NOT_YET;
  }
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

export function applyMessaging(doc: Document, _base: string, data: SettingsData, img: (url: string) => string, writable: boolean): void {
  const me = objectOf<{ subscribePrice?: unknown; canChat?: unknown }>(data.me);
  if (!me) return;
  const settings = objectOf<{ canAcceptMessageOnlyFromFriends?: unknown; replyOnSubscribe?: unknown }>(data.settings);
  if (settings) tipRow(doc, !(Number(me.subscribePrice) > 0), settings.canAcceptMessageOnlyFromFriends, writable);
  const list = Array.isArray(data.templates) ? (data.templates as Welcome[]) : null;
  if (list) welcomeTemplate(doc, me.canChat === false ? null : (list.find((t) => t?.template === "reply_on_subscribe") ?? null), settings ? settings.replyOnSubscribe === true : null, img);
}

export function applySecurity(doc: Document, _base: string, data: SettingsData, _img: unknown, writable: boolean): void {
  const me = objectOf<{ isPerformer?: unknown; isAdultContent?: unknown }>(data.me);
  const settings = objectOf<{ isPrivate?: unknown }>(data.settings);
  if (!me || !settings) return;
  privateRow(doc, me.isPerformer === true && me.isAdultContent === false, settings.isPrivate, writable);
}

export function closeAllSessions(doc: Document, wired: boolean): HTMLButtonElement | null {
  const b = [...doc.querySelectorAll<HTMLButtonElement>("#content .b-sessions-list button")].find((x) => x.textContent?.trim() === "Close all sessions") ?? null;
  if (b && wired) markWired(b, false);
  else if (b) markNotYet(b);
  return b;
}

export function streamKeyReset(doc: Document, wired: boolean): HTMLButtonElement | null {
  const row = [...doc.querySelectorAll<HTMLElement>("#content .b-settings__spacer")].find((r) => r.querySelector("label.v-label")?.textContent?.trim() === "Stream Key");
  const b = [...(row?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find((x) => x.textContent?.trim() === "Reset") ?? null;
  if (b && wired) markWired(b, false);
  else if (b) markNotYet(b);
  return b;
}

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

function sessionTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}/${d.getDate()}/${String(d.getFullYear() % 100).padStart(2, "0")} ${clock(d)}`;
}

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

const CONNECTED_PHONE = `<div><div class="g-input__wrapper b-settings__spacer"><div data-v-5684fe78="" class="g-input__wrapper input-text-field m-reset-bottom-gap"><div data-v-5684fe78="" class="m-filled"><div data-v-5684fe78="" class="v-input form-control g-input mb-0 v-input--is-label-active v-input--is-dirty v-input--is-readonly theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined v-text-field--placeholder"><div class="v-input__control"><div class="v-input__slot"><fieldset aria-hidden="true"><legend style="width: 143.25px;"><span class="notranslate">\u200b</span></legend></fieldset><div class="v-text-field__slot"><label for="connected_phone_number" class="v-label v-label--active theme--light" style="left: 0px; right: auto; position: absolute;">Connected phone number</label><input at-attr="input" autocomplete="on" name="" tabindex="0" id="connected_phone_number" readonly="readonly" type="text"></div></div><div class="v-text-field__details"><div class="v-messages theme--light"><div class="v-messages__wrapper"></div></div></div></div><div class="v-input__append-outer"><div data-v-5684fe78="" class="g-input__help"><!----><div data-oi-hint=""></div><!----></div><!----></div></div></div><!----></div></div><div class="b-settings__row g-btn__wrapper"><button type="button" class="g-btn m-rounded m-border m-danger m-sm"> Delete </button><button type="button" class="g-btn m-rounded m-border m-sm"> Update phone </button></div></div>`;

function connectedPhone(doc: Document, masked: string) {
  const block = doc.querySelector("#content .phone-setting-block");
  if (!block) return;
  const t = doc.createElement("template");
  t.innerHTML = CONNECTED_PHONE;
  block.replaceChildren(t.content);
  (block.querySelector("#connected_phone_number") as HTMLInputElement).value = masked;
  block.querySelector("[data-oi-hint]")!.textContent = `Phone number ${masked} is verified`;
}

function toggleLike(like: Element, id: string, labelText: string, value: unknown, wired: boolean): Element {
  const row = make(like);
  row.querySelector(".g-input__label")!.firstChild!.textContent = labelText;
  const input = row.querySelector("input")!;
  input.id = id;
  input.name = id;
  const sw = row.querySelector("label.b-checkbox-switcher")!;
  sw.setAttribute("for", id);
  sw.setAttribute("at-attr", id);
  input.checked = value === true;
  if (wired) markWired(input, false);
  else markNotYet(input);
  input.title = NOT_YET;
  sw.setAttribute("title", NOT_YET);
  return row;
}

function tipRow(doc: Document, shown: boolean, value: unknown, wired: boolean) {
  const id = "messageOnlyFromFriends";
  const old = doc.getElementById(id)?.closest(".b-menu-list");
  const like = doc.getElementById("autoMessage")?.closest(".g-input__wrapper");
  if (!shown || !like) {
    old?.replaceWith(doc.createComment(""));
    return;
  }
  const list = doc.createElement("div");
  list.className = "b-menu-list";
  list.append(toggleLike(like, id, "Don't accept messages without a Tip from free followers whom you don't follow back", value, wired));
  if (old) return void old.replaceWith(list);
  const form = like.closest("form");
  if (form) fillSlot(form, "before", list);
}

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

function privateRow(doc: Document, shown: boolean, value: unknown, wired: boolean) {
  const old = doc.getElementById("setting_isPrivate")?.closest(".g-input__wrapper");
  const after = doc.getElementById("setting_isVisibleOnline")?.closest(".g-input__wrapper");
  if (!shown || !after) {
    old?.replaceWith(doc.createComment(""));
    return;
  }
  const row = toggleLike(after, "setting_isPrivate", "Fully private profile", value, wired);
  row.querySelector("input")!.name = "isPrivate";
  row.querySelector("label.b-checkbox-switcher")!.setAttribute("at-attr", "isPrivate");
  const help = doc.createElement("p");
  help.className = "g-input__help";
  help.textContent = "Text will be hidden";
  fillSlot(row, "append", help);
  if (old) return void old.replaceWith(row);
  fillSlot(after, "after", row);
}

export const DIGEST_TOGGLE = "toggle_new_likes_digest";

export function digestHours(groups: unknown, code: string): number {
  if (Array.isArray(groups))
    for (const g of groups as { items?: { code?: string; value?: unknown }[] }[])
      for (const it of g?.items ?? []) if (it?.code === code && typeof it.value === "number" && it.value > 0) return it.value;
  return 24;
}

export const frequencyLabel = (hours: number) => `Every ${hours} Hours`;

export function frequencySelect(doc: Document): HTMLElement | null {
  return doc.getElementById(DIGEST_TOGGLE)?.closest("span")?.parentElement?.querySelector<HTMLElement>(".v-select") ?? null;
}

export const DIGEST_OFF = "Turn on New Likes Summary to change its frequency";

export function drawFrequency(doc: Document, hours: number, writable: boolean): void {
  const sel = frequencySelect(doc);
  if (!sel) return;
  const on = writable && !!(doc.getElementById(DIGEST_TOGGLE) as HTMLInputElement | null)?.checked;
  sel.closest(".b-menu-list__el")?.classList.toggle("m-disabled", !on);
  sel.classList.toggle("v-input--is-disabled", !on);
  sel.querySelector("[aria-owns]")?.setAttribute("aria-disabled", String(!on));
  const field = sel.querySelector<HTMLInputElement>("input:not([type='hidden'])");
  for (const el of field ? [sel, field] : [sel]) {
    if (writable) markWired(el, true);
    else markNotYet(el);
  }
  if (writable && !on) sel.title = DIGEST_OFF;
  if (field) field.disabled = !on;
  const shown = sel.querySelector(".v-select__selection");
  if (shown) shown.textContent = frequencyLabel(hours);
  const value = sel.querySelector<HTMLInputElement>("input[type='hidden']");
  if (value) value.value = String(hours);
}

export function applyEmailFrequency(doc: Document, _base: string, data: SettingsData, _img: unknown, writable: boolean): void {
  drawFrequency(doc, digestHours(data["notifications:email"], "new_likes_digest"), writable);
}

export interface CountryPicker {
  box: HTMLElement;
  input: HTMLInputElement;
  save: HTMLButtonElement;
}
export function countryPicker(doc: Document, usable: boolean): CountryPicker | null {
  const box = doc.querySelector<HTMLElement>("#content .g-select__wrapper .v-input");
  const input = box?.querySelector<HTMLInputElement>("input#input-298");
  const save = doc.querySelector<HTMLButtonElement>("#content .g-page__header .g-btn__wrapper button[type='submit']");
  if (!box || !input || !save) return null;
  box.querySelector("a.of-state-link")?.remove();
  box.classList.remove("v-input--is-disabled");
  for (const el of [box, input]) markWired(el, true);
  markWired(save, false);
  input.readOnly = !usable;
  input.autocomplete = "off";
  return { box, input, save };
}

export function countryPickerNotYet(p: CountryPicker): void {
  for (const el of [p.box, p.input, p.save]) markNotYet(el);
  p.box.classList.add("v-input--is-disabled");
  p.input.readOnly = false;
  p.box.querySelector("#oi-countries")?.remove();
  const label = p.box.querySelector<HTMLElement>(".v-label");
  if (label) label.style.display = "";
}

export function drawCountries(doc: Document, codes: string[], name: (code: string) => string): void {
  const box = doc.querySelector<HTMLElement>("#content .g-select__wrapper .v-input");
  const input = box?.querySelector<HTMLInputElement>("input#input-298");
  if (!box || !input) return;
  let chips = box.querySelector<HTMLElement>("#oi-countries");
  if (!chips) {
    chips = doc.createElement("div");
    chips.id = "oi-countries";
    chips.className = "v-select__selections";
    input.before(chips);
  }
  chips.replaceChildren(
    ...codes.map((code) => {
      const chip = doc.createElement("span");
      chip.className = "v-chip v-chip--removable v-size--small theme--light";
      chip.setAttribute("data-oi-country", code);
      chip.setAttribute("data-oi-wired", "");
      chip.title = `Remove ${name(code)}`;
      chip.textContent = `${name(code)} ✕`;
      return chip;
    }),
  );
  const label = box.querySelector<HTMLElement>(".v-label");
  if (label) label.style.display = codes.length ? "none" : "";
}

export function showIps(field: HTMLTextAreaElement): void {
  floatLabel(field, !!field.value);
  field.closest(".g-input__wrapper")?.classList.toggle("m-empty", !field.value);
}

export interface IpForm {
  field: HTMLTextAreaElement;
  cancel: HTMLButtonElement;
  save: HTMLButtonElement;
}
export function ipForm(doc: Document, usable: boolean): IpForm | null {
  const field = doc.querySelector<HTMLTextAreaElement>("#content textarea#input-blocked-ips");
  const buttons = [...doc.querySelectorAll<HTMLButtonElement>("#content .b-settings__row.g-btn__wrapper button")];
  const cancel = buttons.find((b) => b.textContent?.trim() === "Cancel");
  const save = buttons.find((b) => b.textContent?.trim() === "Save");
  if (!field || !cancel || !save) return null;
  markWired(field, true);
  for (const el of [cancel, save]) markWired(el, false);
  field.readOnly = !usable;
  return { field, cancel, save };
}

export function ipFormNotYet(f: IpForm): void {
  for (const el of [f.field, f.cancel, f.save]) markNotYet(el);
  f.field.readOnly = false;
}
