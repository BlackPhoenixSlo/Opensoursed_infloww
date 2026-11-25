"use client";


import { useEffect, type RefObject } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, RelayError } from "@/lib/relay";
import { parseSendFailure } from "@/lib/sendFailure";
import { floatLabel } from "@/lib/ofMirrorDom";
import { afterProfileWrite, MIRROR } from "@/lib/ofMirrorKeys";
import { flushPersistedCache } from "@/lib/rqPersister";
import { frameNavigate, LIST_ROW, STORY, takeCarried, toast } from "@/lib/ofMirrorPost";
import { mirrorPageOfPath } from "@/lib/of-mirror-route";
import { openDatepicker, tabDate, type Day } from "@/lib/ofMirrorDatepicker";
import { AFTER_NEW_POST_PROMOTION, AFTER_NEW_POST_TRIAL, collectBundle, collectPromotion, collectTrial } from "@/lib/ofMirrorOffers";
import { BRAND_NAME } from "@/lib/brand";
import { bindHandoffs } from "@/lib/ofMirrorHandoffs";
import { NOT_YET } from "@/lib/ofMirrorTooltip";
import { bindAboutFormat, profileAbout } from "@/lib/ofMirrorProfileFormat";
import { bindProfileImages, profileImagePatch, type ProfileImage, type ProfileImageKind, type ProfileImagePatch } from "@/lib/ofMirrorProfileImages";
import { bindBrowserOnly } from "@/lib/ofMirrorBrowserOnly";
import { useOfmNewWrites } from "@/lib/ofMirrorNewWrites";

export type ProfilePatch = Partial<Record<"name" | "about" | "location" | "website" | "wishlist", string>>;

export const WRITABLE: Record<string, Record<string, string>> = {
  profile: {
    "#input-name": "name",
    "[data-placeholder='Bio']": "about",
    "#input-location": "location",
    "#input-website": "website",
    "#input-wishlist": "wishlist",
  },
  messaging: { "#autoMessage": "replyOnSubscribe" },
};

export interface Submit {
  button: string;
  fields: string;
  collect(doc: Document, now: Date): object | string;
  send: string;
  then(doc: Document): string;
  invalidate?: readonly (readonly unknown[])[];
  fail: string;
  ofToast?: boolean;
  closeOnError?: boolean;
}

const STREAM_DATE = "input[name='date']";
const STREAM_TIME = "input[name='time']";
const STREAM_DESCRIPTION = ".create-scheduled__description [contenteditable], textarea[name='description']";
const LINK_NAME = "input[name='name']";

const OFFER_READS = [["of-settings"], [MIRROR], ["of-me"]] as const;

const PROMOTION_SUBMIT: Submit = {
  button: ".modal-footer button[type='submit']",
  fields: ".modal.show textarea, .modal.show .v-select input, .modal.show .b-tabs__nav__link",
  collect: collectPromotion,
  send: "/api/of/v2/promotions",
  then: modalCancel,
  invalidate: OFFER_READS,
  fail: "Could not start the campaign",
};
const TRIAL_SUBMIT: Submit = {
  button: ".modal-footer button[type='submit']",
  fields: ".modal.show input[at-attr='input'], .modal.show .v-select input",
  collect: collectTrial,
  send: "/api/of/v2/trials",
  then: modalCancel,
  invalidate: OFFER_READS,
  fail: "Could not create",
};

export const SUBMITS: Record<string, Submit> = {
  "streaming/dashboard/create": {
    button: ".g-page__header > button.g-btn",
    fields: [STREAM_DATE, STREAM_TIME, STREAM_DESCRIPTION].join(", "),
    collect: collectStream,
    send: "/api/of/v2/streams",
    then: () => QUEUE,
    fail: "Could not schedule",
  },
  "settings/subscription/tracking-links/modal-1": {
    button: ".modal-footer button[type='submit']",
    fields: LINK_NAME,
    collect: collectTrackingLink,
    send: "/api/of/v2/campaigns",
    then: modalCancel,
    invalidate: [["of-settings"]],
    fail: "Could not create",
  },
  "settings/subscription/promotion-campaign/modal-1": PROMOTION_SUBMIT,
  "new-post/state-promotion": { ...PROMOTION_SUBMIT, then: () => AFTER_NEW_POST_PROMOTION },
  "home/state-promotion": PROMOTION_SUBMIT,
  "settings/subscription/promotion-campaign/modal-2": {
    button: ".modal-footer button",
    fields: ".modal.show .v-select input",
    collect: collectBundle,
    send: "/api/of/v2/subscriptions/bundles",
    then: modalCancel,
    invalidate: OFFER_READS,
    fail: "Could not add the bundle",
    ofToast: true,
    closeOnError: true,
  },
  "settings/subscription/trial-links/modal-1": TRIAL_SUBMIT,
  "new-post/state-trial-link": { ...TRIAL_SUBMIT, then: () => AFTER_NEW_POST_TRIAL },
};

export interface StreamBody {
  description: string;
  scheduledDate: string;
  isShowTips: true;
}

export const QUEUE = "/of-manager/queue";

const SAVE = ".g-btn__wrapper button[type='submit']";
export const READ_ONLY = `Read-only in ${BRAND_NAME} for now`;
export const BANK_NOTE = `Bank details stay on onlyfans.com (${BRAND_NAME} does not read them).`;
export const BANK_URL = "https://onlyfans.com/my/banking";
export { NOT_YET };
export const SELECT_MODEL = "Select a model to save changes";
export const SAVED_TOAST = "Changes were saved";
export const TOO_SOON = "Pick a time at least a minute from now";
export const minuteAhead = (at: Date, now: Date) => at.getTime() >= now.getTime() + 60_000;
export const NOTE_STYLE = "padding:6px 16px;font-size:13px;line-height:18px";
export const GREY = "#8a96a3";
const DARK_MODE = "dark_mode_switcher";
const NOT_FALLBACK = "a[href], .video-js, [data-oi-dialog]";
const OWNED = "[data-oi-wired], input:not([readonly]), label, textarea, select, [contenteditable]";

export interface WriteHandlers {
  saveProfile(body: ProfilePatch & ProfileImagePatch): Promise<unknown>;
  uploadProfileImage(kind: ProfileImageKind, file: File): Promise<ProfileImage>;
  setReplyOnSubscribe(enabled: boolean): Promise<unknown>;
  submit(path: string, body: object): Promise<unknown>;
  navigate(href: string, toast?: string): void;
}

const settingsPage = (path: string) => (path.startsWith("settings/") ? path.slice("settings/".length).replace(/\/state-[^/]+$/, "") : null);

export const textOf = (el: Element) => {
  const ps = [...el.querySelectorAll("p")];
  return ps.length ? ps.map((p) => p.textContent ?? "").join("\n") : (el.textContent ?? "");
};

export function collectProfilePatch(doc: Document, formatted: boolean, fields?: Iterable<string>): ProfilePatch {
  const only = fields ? new Set(fields) : null;
  const body: Record<string, string> = {};
  for (const [sel, field] of Object.entries(WRITABLE.profile)) {
    if (only && !only.has(field)) continue;
    const el = doc.querySelector(sel);
    if (!el) continue;
    body[field] = el.tagName === "INPUT" ? (el as HTMLInputElement).value : formatted ? profileAbout(el) : textOf(el);
  }
  return body;
}

export function note(doc: Document, anchor: Element, text: string, error = false, ms = 3000) {
  const el = doc.getElementById("oi-note") ?? doc.createElement("div");
  el.id = "oi-note";
  el.setAttribute("role", "status");
  el.style.cssText = NOTE_STYLE;
  el.textContent = text;
  el.style.color = error ? "#ff4545" : GREY;
  const row = anchor.tagName === "BUTTON" ? anchor.closest(".modal-footer, #oi-new-label") : null;
  if (row) row.before(el);
  else if (anchor.tagName === "BUTTON") {
    el.style.display = "inline-block";
    el.style.alignSelf = "center";
    anchor.before(el);
  } else (anchor.closest(".g-input__wrapper, .b-menu-list__el") ?? anchor).after(el);
  const win = doc.defaultView;
  const timer = Number(el.dataset.timer);
  if (timer) win?.clearTimeout(timer);
  el.dataset.timer = error ? "" : String(win?.setTimeout(() => el.remove(), ms) ?? "");
}

export interface Ask {
  title: string;
  text: string;
  ok: string;
}
export function ofConfirm(doc: Document, ask: Ask): Promise<boolean> {
  doc.getElementById("ModalConfirm")?.remove();
  doc.getElementById("ModalConfirm___BV_modal_backdrop_")?.remove();
  const wrap = doc.createElement("div");
  wrap.innerHTML =
    '<div id="ModalConfirm" role="dialog" aria-describedby="ModalConfirm___BV_modal_body_" class="modal fade show m-confirm" aria-modal="true" style="display: block;">' +
    '<div class="modal-dialog modal-sm modal-dialog-centered"><div id="ModalConfirm___BV_modal_content_" tabindex="-1" class="modal-content m-modal-view">' +
    '<header id="ModalConfirm___BV_modal_header_" class="modal-header"><h4 class="modal-title"></h4></header>' +
    '<div id="ModalConfirm___BV_modal_body_" class="modal-body m-reset-body-padding-top"><div class="dialog_message m-break-word-default"></div></div>' +
    '<footer id="ModalConfirm___BV_modal_footer_" class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired=""> Cancel </button>' +
    '<button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired=""></button></footer></div></div></div>' +
    '<div id="ModalConfirm___BV_modal_backdrop_" class="modal-backdrop"></div>';
  wrap.querySelector(".modal-title")!.textContent = ask.title;
  wrap.querySelector(".dialog_message")!.textContent = ask.text;
  const [cancel, ok] = [...wrap.querySelectorAll<HTMLButtonElement>(".modal-footer button")];
  ok.textContent = ` ${ask.ok} `;
  const [modal, backdrop] = [...wrap.children] as HTMLElement[];
  doc.body.append(modal, backdrop);
  doc.body.classList.add("modal-open");
  return new Promise((resolve) => {
    const done = (yes: boolean) => {
      modal.remove();
      backdrop.remove();
      doc.body.classList.remove("modal-open");
      doc.removeEventListener("keydown", onKey);
      resolve(yes);
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") done(false);
    };
    cancel.addEventListener("click", (ev) => (ev.stopPropagation(), done(false)));
    ok.addEventListener("click", (ev) => (ev.stopPropagation(), done(true)));
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) done(false);
    });
    doc.addEventListener("keydown", onKey);
  });
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const ymd = (y: number, m: number, d: number): [number, number, number] | null => {
  const t = new Date(y, m - 1, d);
  return t.getFullYear() === y && t.getMonth() === m - 1 && t.getDate() === d ? [y, m, d] : null;
};

export function parseDate(value: string): [number, number, number] | null {
  const s = value.trim().replace(/\s+/g, " ");
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (m) return ymd(+m[1], +m[2], +m[3]);
  m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(s);
  if (m) return ymd(+m[3], +m[1], +m[2]);
  const month = (name: string) => MONTHS.indexOf(name.slice(0, 3).toLowerCase()) + 1;
  m = /^(?:[a-z]+,? )?([a-z]{3,})\.? (\d{1,2}),? (\d{4})$/i.exec(s);
  if (m && month(m[1])) return ymd(+m[3], month(m[1]), +m[2]);
  m = /^(?:[a-z]+,? )?(\d{1,2}) ([a-z]{3,})\.?,? (\d{4})$/i.exec(s);
  if (m && month(m[2])) return ymd(+m[3], month(m[2]), +m[1]);
  return null;
}

export function parseTime(value: string): [number, number] | null {
  const m = /^(\d{1,2}):(\d{2})(?:\s*([ap])\.?\s*m\.?)?$/i.exec(value.trim());
  if (!m) return null;
  let h = +m[1];
  const min = +m[2];
  if (min > 59) return null;
  if (m[3]) {
    if (h < 1 || h > 12) return null;
    h = (h % 12) + (m[3].toLowerCase() === "p" ? 12 : 0);
  } else if (h > 23) return null;
  return [h, min];
}

const pad = (n: number) => String(n).padStart(2, "0");

export function localIso(d: Date): string {
  const off = -d.getTimezoneOffset();
  const abs = Math.abs(off);
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `${date}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${off < 0 ? "-" : "+"}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

export interface ModalButton {
  text: string;
  className: string;
  icon?: string;
  attrs?: Record<string, string>;
  onClick(): void;
}

export function openModal(
  doc: Document,
  id: string,
  title: string,
  build: (body: HTMLElement) => void,
  footer: ModalButton[],
  opener?: Element,
): { modal: HTMLElement; close(): void } {
  doc.getElementById(id)?.remove();
  opener?.setAttribute("aria-expanded", "true");
  const modal = doc.createElement("div");
  modal.id = id;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.className = "modal fade show";
  modal.style.cssText = "display:block";
  modal.dataset.oiData = "";
  modal.innerHTML =
    '<div class="modal-backdrop show" style="z-index:0"></div><div class="modal-dialog modal-sm modal-dialog-centered" style="position:relative;z-index:1"><div tabindex="-1" class="modal-content"><header class="modal-header"><h4 class="modal-title"></h4></header><div class="modal-body m-reset-body-padding-top"></div><footer class="modal-footer g-border-top"></footer></div></div>';
  modal.querySelector(".modal-title")!.textContent = ` ${title} `;
  build(modal.querySelector<HTMLElement>(".modal-body")!);
  const foot = modal.querySelector("footer")!;
  for (const b of footer) foot.append(modalButton(doc, b));
  const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && close();
  const close = () => {
    modal.remove();
    opener?.setAttribute("aria-expanded", "false");
    doc.removeEventListener("keydown", onKey);
  };
  modal.addEventListener("click", (ev) => {
    const t = ev.target as Element;
    if (t === modal || t.matches(".modal-backdrop, .modal-dialog")) close();
  });
  doc.addEventListener("keydown", onKey);
  doc.body.append(modal);
  return { modal, close };
}

export function modalButton(doc: Document, b: ModalButton): HTMLButtonElement {
  const el = doc.createElement("button");
  el.type = "button";
  el.className = b.className;
  el.setAttribute("data-oi-wired", "");
  for (const [k, v] of Object.entries(b.attrs ?? {})) el.setAttribute(k, v);
  if (b.icon) {
    const svg = el.appendChild(doc.createElementNS("http://www.w3.org/2000/svg", "svg"));
    svg.setAttribute("class", "g-icon");
    svg.setAttribute("data-icon-name", `icon-${b.icon}`);
    svg.setAttribute("aria-hidden", "true");
    svg.appendChild(doc.createElementNS("http://www.w3.org/2000/svg", "use")).setAttribute("href", `#icon-${b.icon}`);
  }
  el.append(` ${b.text} `);
  el.addEventListener("click", (ev) => {
    ev.preventDefault();
    b.onClick();
  });
  return el;
}

export function dateTimeFields(doc: Document, wall: Date, today: Date = new Date()): { row: HTMLElement; read(): Date | null } {
  const row = doc.createElement("div");
  row.className = "row m-quarter-gap b-period-fields m-mb-25";
  row.style.cssText = "display:flex;margin:0 -4px";
  const field = (label: string, type: "date" | "time", value: string, icon: string) => {
    const col = row.appendChild(doc.createElement("div"));
    col.className = "col-xs-6";
    col.style.cssText = "flex:1 1 0;padding:0 4px";
    col.innerHTML =
      '<div class="v-datetime chat-data-filter w-100 m-mt-12 m-reset-bottom-gap m-field-label-over"><div class="vdatetime custom-datepicker v-datetime__fill-field" style="position:relative"><input class="vdatetime-input form-control g-input"><span class="v-datetime__icon"><svg class="m-aligned-top g-icon" aria-hidden="true"><use></use></svg></span><label class="v-datetime__label"></label></div></div>';
    col.querySelector("label")!.textContent = ` ${label} `;
    const svg = col.querySelector("svg")!;
    svg.setAttribute("data-icon-name", icon);
    svg.querySelector("use")!.setAttribute("href", `#${icon}`);
    const input = col.querySelector("input")!;
    input.type = type === "date" ? "text" : type;
    input.readOnly = type === "date";
    input.value = value;
    input.setAttribute("at-attr", `${type}_input`);
    input.setAttribute("data-oi-wired", "");
    return input;
  };
  const style = row.appendChild(doc.createElement("style"));
  style.textContent = ".b-period-fields input::-webkit-calendar-picker-indicator{opacity:0;position:absolute;right:0;top:0;width:44px;height:100%;cursor:pointer}";
  const dayOf = (d: Date): Day => ({ y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() });
  const date = field("Date", "date", tabDate(dayOf(wall)), "icon-calendar-datepicker");
  date.closest(".vdatetime")!.addEventListener("click", () => {
    const at = parseDate(date.value);
    const day = at ? { y: at[0], m: at[1], d: at[2] } : dayOf(wall);
    openDatepicker(doc, { start: day, end: day, today: dayOf(today), userStart: null, single: true, future: true, onApply: (d) => void (date.value = tabDate(d)) });
  });
  const time = field("Time", "time", `${pad(wall.getHours())}:${pad(wall.getMinutes())}`, "icon-recent");
  return {
    row,
    read: () => {
      const d = parseDate(date.value);
      const t = parseTime(time.value);
      return d && t ? new Date(d[0], d[1] - 1, d[2], t[0], t[1]) : null;
    },
  };
}

const PILL = "oi-schedule-pill";

export function schedulePill(doc: Document, editor: Element, text: string | null): void {
  const old = doc.getElementById(PILL);
  if (text === null) return old?.remove();
  const wrap = old ?? doc.createElement("div");
  wrap.id = PILL;
  wrap.className = "b-dropzone__previews";
  const V = 'data-v-346a4cb3=""';
  const icon = (name: string) => `<svg ${V} data-icon-name="${name}" aria-hidden="true" class="g-icon"><use href="#${name}" xlink:href="#${name}"></use></svg>`;
  wrap.innerHTML =
    `<div ${V} class="b-post-piece b-dropzone__preview m-schedule m-loaded g-pointer-cursor m-row" data-oi-wired="">${icon("icon-schedule")} Scheduled for <span ${V} class="b-post-piece__value g-text-ellipsis"></span>` +
    `<button ${V} type="button" class="b-dropzone__preview__delete g-btn m-rounded m-reset-width m-thumb-r-corner-pos m-btn-remove m-sm-icon-size" disabled="disabled" data-oi-wired="">${icon("icon-close")}</button></div>`;
  wrap.querySelector("span")!.textContent = ` ${text} `;
  wrap.querySelector("button")!.title = NOT_YET;
  wrap.firstElementChild!.addEventListener("click", () => doc.querySelector<HTMLElement>("[at-attr='scheduled_msg']")?.click());
  if (!old) (editor.closest(".g-input__wrapper") ?? editor).before(wrap);
}

export function scheduleAt(y: number, m: number, d: number, timeText: string, now: Date): Date | string {
  const time = parseTime(timeText);
  if (!time) return "Enter a valid time";
  const at = new Date(y, m - 1, d, time[0], time[1]);
  return minuteAhead(at, now) ? at : TOO_SOON;
}

export function collectStream(doc: Document, now: Date = new Date()): StreamBody | string {
  const value = (sel: string) => doc.querySelector<HTMLInputElement>(sel)?.value.trim() ?? "";
  const dateText = value(STREAM_DATE);
  const timeText = value(STREAM_TIME);
  if (!dateText || !timeText) return "Enter a date and a time";
  const date = parseDate(dateText);
  if (!date) return "Enter a valid date";
  const at = scheduleAt(date[0], date[1], date[2], timeText, now);
  if (typeof at === "string") return at;
  const editor = doc.querySelector(STREAM_DESCRIPTION);
  const description = !editor ? "" : editor.tagName === "TEXTAREA" ? (editor as HTMLTextAreaElement).value : textOf(editor);
  return { description: description.trim(), scheduledDate: localIso(at), isShowTips: true };
}

export function prefillStream(doc: Document, date: string | null, time: string | null): void {
  const d = date ? parseDate(date) : null;
  const fill = (sel: string, value: string | null) => {
    const input = doc.querySelector<HTMLInputElement>(sel);
    if (input && value && !input.value) input.value = value;
  };
  fill(STREAM_DATE, d && new Date(d[0], d[1] - 1, d[2]).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }));
  const t = time ? parseTime(time) : null;
  fill(STREAM_TIME, t && `${pad(t[0])}:${pad(t[1])}`);
}

export function collectTrackingLink(doc: Document): { name: string } | string {
  const name = doc.querySelector<HTMLInputElement>(LINK_NAME)?.value.trim() ?? "";
  return name ? { name } : "Enter a tracking link name";
}

function modalCancel(doc: Document): string {
  return doc.querySelector(".modal-footer a[href]")?.getAttribute("href") ?? "";
}

const NO_ROUTE: Record<number, string> = { 404: "Not Found", 405: "Method Not Allowed" };
// The Relay runs older code than the app, so the action never reached OF.
export const OLD_RELAY = "the Relay runs older code that cannot do this yet (restart it on the app's branch)";

export const message = (e: unknown) =>
  e instanceof RelayError && NO_ROUTE[e.status] !== undefined && (e.body as { detail?: unknown } | null)?.detail === NO_ROUTE[e.status]
    ? OLD_RELAY
    : e instanceof Error
      ? e.message
      : String(e);
export const ofErrorMessage = (e: unknown): string | null => (e instanceof RelayError ? (parseSendFailure(e.body).reason ?? null) : null);
export function unresolvedId(body: unknown): number | null {
  const d = (body as { detail?: { reason?: unknown; id?: unknown } } | null)?.detail;
  return d?.reason === "create_unresolved" && typeof d.id === "number" ? d.id : null;
}

export function bindWrites(doc: Document, path: string, handlers: WriteHandlers | null, newWrites: boolean): () => void {
  takeCarried(doc);
  const unbindBank = path.startsWith("bank/") ? bankNote(doc) : () => {};
  const unbindPickers = path === "streaming/dashboard/create" ? streamPickers(doc) : () => {};
  const unbindHandoffs = bindHandoffs(doc, path);
  const page = settingsPage(path);
  const map = page !== null && Object.hasOwn(WRITABLE, page) ? WRITABLE[page] : {};
  const entry = Object.hasOwn(SUBMITS, path) ? SUBMITS[path] : null;
  const entryButton = entry ? doc.querySelector<HTMLButtonElement>(entry.button) : null;
  const form = entry && entryButton ? { submit: entry, button: entryButton } : null;
  const gated = form?.button.disabled ? form : null;
  let sending = false;
  const writable = (t: Element | null) => {
    for (const [sel, field] of Object.entries(map)) if (t?.closest(sel)) return field;
    return null;
  };
  const dirty = new Set<string>();
  const save = page === "profile" ? doc.querySelector<HTMLButtonElement>(SAVE) : null;
  const wired = [
    ...Object.keys(map).flatMap((sel) => [...doc.querySelectorAll(sel)]),
    ...(save ? [save] : []),
    ...(form ? [form.button, ...doc.querySelectorAll(form.submit.fields)] : []),
  ];
  for (const el of wired) el.setAttribute("data-oi-wired", "");
  const images = save && newWrites
    ? bindProfileImages(doc, {
        canWrite: !!handlers,
        onStage: () => void (save.disabled = false),
        onRefuse: (anchor, text) => note(doc, anchor, text, true),
        onSelectModel: (anchor) => note(doc, anchor, SELECT_MODEL),
      })
    : null;
  const unbindFormat = save && newWrites ? bindAboutFormat(doc, () => (handlers ? null : SELECT_MODEL)) : null;

  const onInput = (ev: Event) => {
    if (form) doc.getElementById("oi-note")?.remove();
    const editor = (ev.target as Element | null)?.closest?.("[contenteditable][data-placeholder]");
    if (editor && (form || writable(editor))) {
      const len = textOf(editor).length;
      editor.setAttribute("data-is-empty", String(!len));
      const count = editor.closest(".g-input__wrapper")?.querySelector(".count-block");
      if (count) count.textContent = count.textContent!.replace(/\d+(?=\/)/, String(len));
    }
    const input = (ev.target as Element | null)?.closest?.<HTMLInputElement>(".v-input input[type='text']");
    if (input && (form || writable(input))) {
      floatLabel(input, !!input.value);
      const counter = input.closest(".v-input")?.querySelector(".v-counter");
      if (counter) counter.textContent = counter.textContent!.replace(/^\s*\d+/, String([...input.value].length));
    }
    if (gated && !sending) gated.button.disabled = typeof gated.submit.collect(doc, new Date()) === "string";
    const field = writable(ev.target as Element);
    if (!field || !save) return;
    dirty.add(field);
    save.disabled = false;
  };

  const onChange = (ev: Event) => {
    const t = ev.target as HTMLInputElement;
    const field = writable(t);
    if (field && !handlers) {
      note(doc, t, SELECT_MODEL);
      if (t.type === "checkbox") t.checked = !t.checked;
    } else if (field === "replyOnSubscribe" && handlers) {
      const enabled = t.checked;
      handlers.setReplyOnSubscribe(enabled).then(
        () => void toast(doc, SAVED_TOAST),
        (e) => {
          t.checked = !enabled;
          note(doc, t, `Could not save: ${message(e)}`, true);
        },
      );
    } else if (!field && !form && t.id !== DARK_MODE && !t.closest("[data-oi-wired]")) {
      note(doc, t.closest(LIST_ROW) ?? t, READ_ONLY);
      if (t.type === "checkbox") t.checked = !t.checked;
    }
  };

  const send = () => {
    if (!form) return;
    const { submit, button } = form;
    if (!handlers) return note(doc, button, SELECT_MODEL);
    if (button.disabled) return;
    const body = submit.collect(doc, new Date());
    if (typeof body === "string") return note(doc, button, body, true);
    button.disabled = sending = true;
    doc.getElementById("oi-note")?.remove();
    const post = (b: object): Promise<void> => handlers.submit(submit.send, b).then(
      () => handlers.navigate(submit.then(doc)),
      async (e) => {
        // 409 create_unresolved: an earlier create OF never answered; the operator says whether it went through.
        const open = e instanceof RelayError ? unresolvedId(e.body) : null;
        if (open !== null) {
          const text = String(((e as RelayError).body as { detail?: { message?: unknown } }).detail?.message ?? "");
          if (await ofConfirm(doc, { title: "Create anyway?", text, ok: "Create anyway" })) return post({ ...b, resolve_open: open });
          button.disabled = sending = false;
          return;
        }
        button.disabled = sending = false;
        const of = submit.ofToast ? ofErrorMessage(e) : null;
        if (submit.closeOnError) handlers.navigate(submit.then(doc), of ?? `${submit.fail}: ${message(e)}`);
        else if (of) toast(doc, of);
        else note(doc, button, `${submit.fail}: ${message(e)}`, true);
      },
    );
    void post(body);
  };

  const onSubmit = (ev: Event) => {
    ev.preventDefault();
    const t = ev.target as Element;
    if (form && (t.contains(form.button) || t.querySelector(form.submit.fields))) send();
  };

  const fallback = (t: Element | null) => {
    if (!t?.closest || t.closest(NOT_FALLBACK) || t.closest(`${STORY.strip} ${STORY.tile}`)) return;
    const control = t.closest("button, [role=button]");
    const owned = t.closest(OWNED);
    if (control && !(owned && control.contains(owned))) note(doc, control, READ_ONLY);
  };

  const onClick = (ev: MouseEvent) => {
    if (form?.button.contains(ev.target as Node)) {
      ev.preventDefault();
      return send();
    }
    const btn = (ev.target as Element | null)?.closest?.(SAVE);
    if (!btn || btn !== save) return fallback(ev.target as Element | null);
    ev.preventDefault();
    const pictures = images?.staged() ?? {};
    if (!dirty.size && !Object.keys(pictures).length) return;
    if (!handlers) return note(doc, save, SELECT_MODEL);
    const fields = [...dirty];
    save.disabled = true;
    const upload = (kind: ProfileImageKind, file: File) => handlers.uploadProfileImage(kind, file);
    const text = collectProfilePatch(doc, newWrites, fields);
    const sent = Object.keys(pictures).length
      ? profileImagePatch(pictures, upload).then((imgs) => handlers.saveProfile({ ...text, ...imgs }))
      : handlers.saveProfile(text);
    sent.then(
      () => {
        for (const f of fields) dirty.delete(f);
        images?.commit();
        save.disabled = dirty.size === 0;
        toast(doc, SAVED_TOAST);
      },
      (e) => {
        images?.revert();
        save.disabled = false;
        note(doc, save, `Could not save: ${message(e)}`, true);
      },
    );
  };

  doc.addEventListener("input", onInput);
  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
    unbindBank();
    unbindPickers();
    unbindHandoffs();
    images?.unbind();
    unbindFormat?.();
  };
}

function streamPickers(doc: Document, today: Date = new Date()): () => void {
  const date = doc.querySelector<HTMLInputElement>(STREAM_DATE);
  const time = doc.querySelector<HTMLInputElement>(STREAM_TIME);
  const box = date?.closest(".vdatetime");
  if (!date || !time || !box) return () => {};
  const dayOf = (d: Date): Day => ({ y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate() });
  date.readOnly = true;
  time.type = "time";
  const style = doc.head.appendChild(doc.createElement("style"));
  style.textContent = ".create-scheduled__time .vdatetime{position:relative}.create-scheduled__time input::-webkit-calendar-picker-indicator{opacity:0;position:absolute;right:0;top:0;width:44px;height:100%;cursor:pointer}";
  const open = () => {
    const at = parseDate(date.value);
    const day = at ? { y: at[0], m: at[1], d: at[2] } : dayOf(today);
    openDatepicker(doc, { start: day, end: day, today: dayOf(today), userStart: null, single: true, future: true, onApply: (d) => {
      date.value = tabDate(d);
      date.dispatchEvent(new Event("input", { bubbles: true }));
    } });
  };
  box.addEventListener("click", open);
  return () => {
    box.removeEventListener("click", open);
    style.remove();
  };
}

function bankNote(doc: Document): () => void {
  const header = doc.querySelector(".g-page__header");
  if (!header) return () => {};
  const el = doc.createElement("div");
  el.id = "oi-bank-note";
  el.style.cssText = NOTE_STYLE;
  el.style.color = GREY;
  const link = doc.createElement("a");
  link.href = BANK_URL;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Open banking on onlyfans.com";
  link.setAttribute("data-oi-wired", "");
  el.append(`${BANK_NOTE} `, link);
  header.after(el);
  return () => el.remove();
}

export function useOfWrites(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const path = mirrorPageOfPath(src) ?? "";
  const entry = Object.hasOwn(SUBMITS, path) ? SUBMITS[path] : null;
  const stream = path === "streaming/dashboard/create";
  const streamDate = stream ? params.get("date") : null;
  const streamTime = stream ? params.get("time") : null;
  const newWrites = useOfmNewWrites(settingsPage(path) === "profile", accountId);
  const refresh = () => {
    void afterProfileWrite(qc, accountId).then(flushPersistedCache);
    void qc.invalidateQueries({ queryKey: ["reply-on-subscribe", accountId] });
  };
  const { mutateAsync: saveProfile } = useMutation({
    mutationFn: (body: ProfilePatch & ProfileImagePatch) => relay.patch("/api/of/v2/users/me", body, { accountId }),
    onSuccess: refresh,
  });
  const { mutateAsync: uploadProfileImage } = useMutation({
    mutationFn: ({ kind, file }: { kind: ProfileImageKind; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      return relay.uploadForm<ProfileImage>("/api/of/v2/users/me/profile-image", form, { accountId });
    },
  });
  const { mutateAsync: setReplyOnSubscribe } = useMutation({
    mutationFn: (enabled: boolean) => relay.patch("/api/of/v2/users/me/reply-on-subscribe", { enabled }, { accountId }),
    onSuccess: refresh,
  });

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const navigate = frameNavigate(frameRef, (href) => router.push(href));
      const submit = (send: string, body: object) =>
        relay.post(send, body, { accountId }).then((r) => {
          for (const queryKey of entry?.invalidate ?? []) qc.invalidateQueries({ queryKey });
          return r;
        });
      if (doc?.body && stream) prefillStream(doc, streamDate, streamTime);
      if (!doc?.body) return void (unbind = undefined);
      const unbindWrites = bindWrites(doc, path, accountId ? { saveProfile, uploadProfileImage: (kind, file) => uploadProfileImage({ kind, file }), setReplyOnSubscribe, submit, navigate } : null, newWrites);
      const unbindBrowserOnly = bindBrowserOnly(doc, path, navigate);
      unbind = () => {
        unbindWrites();
        unbindBrowserOnly();
      };
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, entry, accountId, qc, saveProfile, uploadProfileImage, setReplyOnSubscribe, router, stream, streamDate, streamTime, newWrites]);
}
