"use client";

/**
 * Write-through for the few OF mirror controls whose relay route is
 * implemented: the profile page's text fields (Save -> PATCH /users/me),
 * the messaging page's welcome message switch (PATCH /users/me/reply-on-subscribe),
 * the stream schedule form's SCHEDULE (SUBMITS: POST /streams, then the queue) and the
 * "Create new tracking link" modal's Create Link (SUBMITS: POST /campaigns {name}, then its Cancel link).
 * All of them are confirmed against live OF: its own Save, captured with the
 * request intercepted and rejected before sending, sends PATCH /api2/v2/users/me
 * with exactly {name, location, website, wishlist}; `about` (the bio) and the
 * welcome message switch were confirmed before; the schedule form's body
 * {description, scheduledDate, isShowTips: true} is read from OF's own JS; the tracking link's
 * {name} is verified live by the relay's create_campaign (OF picks the code). The promotion modal's "Start campaign",
 * the bundle modal's "Save" and the free trial modal's "Create link" send OF's own bodies, read from its bundle (not
 * observed live; ofMirrorOffers keeps their dialogs' state and builds them).
 * A profile Save or welcome switch that saved shows OF's settings toast (SAVED_TOAST).
 * Any other control a user changes on any Mirror page, in either scope, sends nothing, shows a small "Read-only"
 * note and (a toggle) flips back, unless it is marked data-oi-wired (its binder owns it). The "Dark mode" switch is left
 * to useOfTheme. Writes need a single model: in the all-models scope a writable control's Save, switch, SCHEDULE or
 * Create Link sends nothing either and shows "Select a model to save changes" (a switch flips back).
 * On every Mirror page, in either scope, a click on any other button or [role=button] shows the "Read-only" note
 * (the click fallback), unless it is a link or State page opener, the video player, a Wired control or a form field
 * (a dropdown's readonly input is none; a button nested in a Wired row or a label still gets the note).
 * No native form submit on a Mirror page goes through (it would reload the frame and drop the note).
 */

import { useEffect, type RefObject } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, RelayError } from "@/lib/relay";
import { parseSendFailure } from "@/lib/sendFailure";
import { floatLabel } from "@/lib/ofMirrorSettings";
import { frameNavigate, LIST_ROW, STORY, takeCarried, toast } from "@/lib/ofMirrorPost";
import { mirrorPageOfPath } from "@/lib/of-mirror-route";
import { openDatepicker, tabDate, type Day } from "@/lib/ofMirrorDatepicker";
// Only functions and lazily read constants from ofMirrorOffers (it imports this module): SUBMITS' keys are literals, as
// a constant of a module still evaluating would be undefined here.
import { AFTER_NEW_POST_PROMOTION, AFTER_NEW_POST_TRIAL, collectBundle, collectPromotion, collectTrial } from "@/lib/ofMirrorOffers";
import { BRAND_NAME } from "@/lib/brand";

export type ProfilePatch = Partial<Record<"name" | "about" | "location" | "website" | "wishlist", string>>;

/** Page (sub path under settings/) -> writable control selector -> field. */
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

/**
 * A form whose submit writes through: its `button`, the `fields` whose values it sends, `collect` (the body, or a validation note),
 * the relay path it POSTs to (`send`), where to go after success (`then`) and the query keys
 * a success refreshes (`invalidate`); a relay error reads `<fail>: <message>`.
 */
export interface Submit {
  button: string;
  fields: string;
  collect(doc: Document, now: Date): object | string;
  send: string;
  then(doc: Document): string;
  invalidate?: readonly (readonly unknown[])[];
  fail: string;
  /** OF's own error message, when the relay error carries one, shows as OF shows it: a toast (the form stays as it was). */
  ofToast?: boolean;
  /** OF's dialog closes whatever the answer (the bundle modal: its save's `finally` hides it); an error's toast (OF's message, else `fail`'s) shows on the page under it. */
  closeOnError?: boolean;
}

/** The fields each SUBMITS form sends: its `collect` reads them and its binder marks them. */
const STREAM_DATE = "input[name='date']";
const STREAM_TIME = "input[name='time']";
const STREAM_DESCRIPTION = ".create-scheduled__description [contenteditable], textarea[name='description']";
const LINK_NAME = "input[name='name']";

/** What an offer dialog's write refreshes: the settings rows, the right column's promotions and users/me's. */
const OFFER_READS = [["of-settings"], ["of-mirror-data"], ["of-me"]] as const;

const PROMOTION_SUBMIT: Submit = {
  button: ".modal-footer button[type='submit']", // Start campaign
  fields: ".modal.show textarea, .modal.show .v-select input, .modal.show .b-tabs__nav__link",
  collect: collectPromotion,
  send: "/api/of/v2/promotions",
  then: modalCancel,
  invalidate: OFFER_READS,
  fail: "Could not start the campaign",
};
const TRIAL_SUBMIT: Submit = {
  button: ".modal-footer button[type='submit']", // Create link
  fields: ".modal.show input[at-attr='input'], .modal.show .v-select input",
  collect: collectTrial,
  send: "/api/of/v2/trials",
  then: modalCancel,
  invalidate: OFFER_READS,
  fail: "Could not create",
};

/** Mirrored page (its full path under of-mirror/pages) -> its form's Submit. */
export const SUBMITS: Record<string, Submit> = {
  "streaming/dashboard/create": {
    button: ".g-page__header > button.g-btn", // SCHEDULE (a new stream)
    fields: [STREAM_DATE, STREAM_TIME, STREAM_DESCRIPTION].join(", "),
    collect: collectStream,
    send: "/api/of/v2/streams",
    then: () => QUEUE,
    fail: "Could not schedule",
  },
  "settings/subscription/tracking-links/modal-1": {
    button: ".modal-footer button[type='submit']", // Create Link
    fields: LINK_NAME,
    collect: collectTrackingLink,
    send: "/api/of/v2/campaigns",
    then: modalCancel,
    invalidate: [["of-settings"]],
    fail: "Could not create",
  },
  // The offer dialogs, on Settings and over New post (ofMirrorOffers binds their fields and keeps their state).
  "settings/subscription/promotion-campaign/modal-1": PROMOTION_SUBMIT, // ofMirrorOffers' PROMOTION_MODAL
  // Over New post OF goes on to Settings > Subscription (#promotion) once the campaign starts.
  "new-post/state-promotion": { ...PROMOTION_SUBMIT, then: () => AFTER_NEW_POST_PROMOTION }, // NEW_POST_PROMOTION
  // Over Home OF stays on Home (its Cancel's way back).
  "home/state-promotion": PROMOTION_SUBMIT, // HOME_PROMOTION
  "settings/subscription/promotion-campaign/modal-2": { // BUNDLE_MODAL
    button: ".modal-footer button", // Save
    fields: ".modal.show .v-select input",
    collect: collectBundle,
    send: "/api/of/v2/subscriptions/bundles",
    then: modalCancel,
    invalidate: OFFER_READS,
    fail: "Could not add the bundle",
    ofToast: true,
    closeOnError: true,
  },
  "settings/subscription/trial-links/modal-1": TRIAL_SUBMIT, // TRIAL_MODAL
  // Over New post OF goes on to the free trial links once the link is made.
  "new-post/state-trial-link": { ...TRIAL_SUBMIT, then: () => AFTER_NEW_POST_TRIAL }, // NEW_POST_TRIAL
};

/** POST /streams: OF's own create form's body (no cover). */
export interface StreamBody {
  description: string;
  scheduledDate: string;
  isShowTips: true;
}

/** Where OF goes after scheduling a stream (it opens the queue at that date). */
export const QUEUE = "/of-manager/queue";

/** OF's header "Save" on the profile page (disabled until a field changes). */
const SAVE = ".g-btn__wrapper button[type='submit']";
export const READ_ONLY = `Read-only in ${BRAND_NAME} for now`;
/** The Bank pages' line under the title (the mirror shows OF's banking placeholders and reads none of it). */
export const BANK_NOTE = `Bank details stay on onlyfans.com (${BRAND_NAME} does not read them).`;
export const BANK_URL = "https://onlyfans.com/my/banking";
/** The tooltip of a control quietly disabled because Inflowwww has no source for it (the generator's NOT_YET_TITLE). */
export const NOT_YET = `Not available in ${BRAND_NAME} yet`;
export const SELECT_MODEL = "Select a model to save changes";
/** OF's settings success toast (`message.changes_saved_toast`, OF's texts_en.json). */
export const SAVED_TOAST = "Changes were saved";
/** A schedule (a stream's or a post's) must be at least a minute ahead, as OF's min. */
export const TOO_SOON = "Pick a time at least a minute from now";
export const minuteAhead = (at: Date, now: Date) => at.getTime() >= now.getTime() + 60_000;
/** The status note's base style and its (non-error) grey. */
export const NOTE_STYLE = "padding:6px 16px;font-size:13px;line-height:18px";
export const GREY = "#8a96a3";
/** OF's "Dark mode" switch (settings/display): it switches our theme (useOfTheme), not a read-only OF setting. */
const DARK_MODE = "dark_mode_switcher";
/**
 * Where a click is not the click fallback's: links and State page openers (of-state-link, of-state-backdrop, inert `#`),
 * the video player, and a dialog a binder built (`[data-oi-dialog]`: Collections' list dialogs, Statements' payout and
 * alert dialogs), whose every control is its binder's; a failed Save there once also said "Read-only".
 */
const NOT_FALLBACK = "a[href], .video-js, [data-oi-dialog]";
/**
 * Nor at or inside the clicked control: a Wired control (its binder's) and a form field (the change path's). A dropdown's
 * readonly input is no field, and a control nested in a Wired row or a label is still the fallback's.
 */
const OWNED = "[data-oi-wired], input:not([readonly]), label, textarea, select, [contenteditable]";

export interface WriteHandlers {
  saveProfile(body: ProfilePatch): Promise<unknown>;
  setReplyOnSubscribe(enabled: boolean): Promise<unknown>;
  submit(path: string, body: object): Promise<unknown>;
  /** `toast`: OF's toast, carried to the page href opens (carryToast). */
  navigate(href: string, toast?: string): void;
}

/** A mirror path's WRITABLE key: a settings page's path under settings/ without a State page suffix; null outside settings/. */
const settingsPage = (path: string) => (path.startsWith("settings/") ? path.slice("settings/".length).replace(/\/state-[^/]+$/, "") : null);

/** The bio editor's text, one line per paragraph. */
export const textOf = (el: Element) => {
  const ps = [...el.querySelectorAll("p")];
  return ps.length ? ps.map((p) => p.textContent ?? "").join("\n") : (el.textContent ?? "");
};

/** The profile page's writable values (only `fields`, when given) as a PATCH /users/me body. */
export function collectProfilePatch(doc: Document, fields?: Iterable<string>): ProfilePatch {
  const only = fields ? new Set(fields) : null;
  const body: Record<string, string> = {};
  for (const [sel, field] of Object.entries(WRITABLE.profile)) {
    if (only && !only.has(field)) continue;
    const el = doc.querySelector(sel);
    if (!el) continue;
    body[field] = el.tagName === "INPUT" ? (el as HTMLInputElement).value : textOf(el);
  }
  return body;
}

/**
 * One shared status line, placed after `anchor`'s field row (or just before
 * the button, when a button is the anchor; a dialog footer's button or a name
 * field row's Save: above that row, so it never splits its buttons); non-error notes fade after `ms`.
 */
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

/** OF's ModalConfirm: its title, text and confirm button (OF's texts_en.json). */
export interface Ask {
  title: string;
  text: string;
  ok: string;
}
/**
 * OF's ModalConfirm in `doc` (its captured markup: #ModalConfirm, .modal.m-confirm, modal-sm, Cancel and the confirm
 * button), resolved true by the confirm button, false by Cancel, the backdrop or Escape.
 */
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
    // The dialog's own backdrop is the .modal box around .modal-dialog (bootstrap-vue).
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

/** The date field: OF's formatted date ("Oct 20, 2026", "20 Oct 2026", "10/20/2026") or yyyy-mm-dd; null if none of them. */
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

/** The time field: 24h "18:30" or 12h "6:30 pm"; [hours, minutes] or null. */
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

/** `d` as local ISO with its UTC offset, as moment's .format(): 2026-10-20T18:30:00+02:00. */
export function localIso(d: Date): string {
  const off = -d.getTimezoneOffset();
  const abs = Math.abs(off);
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `${date}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${off < 0 ? "-" : "+"}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** A button in a modal built by openModal: its text and classes (OF's), and what a click does. */
export interface ModalButton {
  text: string;
  className: string;
  /** Before the text: an OF sprite icon (`icon-<name>`; nothing shows when the page's sprite lacks it). */
  icon?: string;
  attrs?: Record<string, string>;
  onClick(): void;
}

/**
 * A bootstrap-vue modal as OF's ModalWrapper draws it (`.modal.show` > `.modal-dialog.modal-sm.modal-dialog-centered` >
 * `.modal-content` with header, body and footer, then the backdrop), built in `doc` with `id`, its header `title`, the
 * body `build` fills and the `footer` buttons. The backdrop, Escape and close() remove it. Every button carries
 * data-oi-wired (its own handler, not the read-only click fallback); `opener` is aria-expanded while it is open.
 * Returns the modal and close.
 */
export function openModal(
  doc: Document,
  id: string,
  title: string,
  build: (body: HTMLElement) => void,
  footer: ModalButton[],
  opener?: Element,
): { modal: HTMLElement; close(): void } {
  doc.getElementById(id)?.remove();
  // The control that opened it says so while it is open (aria-expanded), as OF's dropdown activators do.
  opener?.setAttribute("aria-expanded", "true");
  const modal = doc.createElement("div");
  modal.id = id;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.className = "modal fade show";
  modal.style.cssText = "display:block";
  modal.dataset.oiData = "";
  // The backdrop under the dialog (OF's sits outside the modal; here both are inside it, so their order is set).
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
  // The dialog sits over the backdrop; a click on the dialog's empty margin or the backdrop closes it.
  modal.addEventListener("click", (ev) => {
    const t = ev.target as Element;
    if (t === modal || t.matches(".modal-backdrop, .modal-dialog")) close();
  });
  doc.addEventListener("keydown", onKey);
  doc.body.append(modal);
  return { modal, close };
}

/** One of openModal's buttons (also for a modal body's own buttons). */
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

/**
 * OF's date and time pair (the Add to queue modal's two DatetimeInputs, captured live: a `b-period-fields` row of two
 * `v-datetime` fields labelled "Date" and "Time", with OF's calendar and clock icons), opened on `wall` (a wall clock: its
 * local fields are shown). The date ("Oct 19, 2026") opens OF's day popup (ofMirrorDatepicker, from `today`, a wall
 * clock, on); the time is a native time input (its picker opens from the icon). read() gives the picked wall clock, or
 * null while either is empty.
 */
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
    // The date: OF's own day popup (ofMirrorDatepicker, from today on); the time: the browser's.
    input.type = type === "date" ? "text" : type;
    input.readOnly = type === "date";
    input.value = value;
    input.setAttribute("at-attr", `${type}_input`);
    // Its own field (read by read()), not one bindWrites' change path answers with the Read-only note.
    input.setAttribute("data-oi-wired", "");
    return input;
  };
  // The native picker's own indicator sits invisibly over OF's icon, so the icon opens it.
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

/**
 * OF's "Scheduled for" piece (PostScheduleForItem, chunk 45507: a post piece in the dropzone previews, above the editor)
 * on an Edit post / Edit message page: `text` is the date (or "Saved for later", OF's same piece); a click opens the
 * composer's schedule (its `scheduled_msg` button); its × stays disabled with the tooltip (an edit keeps its date or
 * Save for later). Null removes it.
 */
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

/** Day `y`-`m`-`d` (m 1-based) at the typed time, or the validation note (a valid time, at least a minute after `now`). */
export function scheduleAt(y: number, m: number, d: number, timeText: string, now: Date): Date | string {
  const time = parseTime(timeText);
  if (!time) return "Enter a valid time";
  const at = new Date(y, m - 1, d, time[0], time[1]);
  return minuteAhead(at, now) ? at : TOO_SOON;
}

/** The schedule form's POST /streams body, or the validation note (date and time required, at least a minute ahead, as OF's min). */
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

/**
 * The stream schedule form's date and time filled in from its page's ?date= (yyyy-mm-dd) and ?time= ("5:30 pm"), as the
 * Queue's "+" > Stream opens it; a field already typed in, or a value that does not parse, is left alone.
 */
export function prefillStream(doc: Document, date: string | null, time: string | null): void {
  const d = date ? parseDate(date) : null;
  const fill = (sel: string, value: string | null) => {
    const input = doc.querySelector<HTMLInputElement>(sel);
    if (input && value && !input.value) input.value = value;
  };
  fill(STREAM_DATE, d && new Date(d[0], d[1] - 1, d[2]).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }));
  // The time field is the browser's time input (streamPickers): its value is 24h "13:15".
  const t = time ? parseTime(time) : null;
  fill(STREAM_TIME, t && `${pad(t[0])}:${pad(t[1])}`);
}

/** The tracking link modal's POST /campaigns body (its name, trimmed; never a code), or the validation note. */
export function collectTrackingLink(doc: Document): { name: string } | string {
  const name = doc.querySelector<HTMLInputElement>(LINK_NAME)?.value.trim() ?? "";
  return name ? { name } : "Enter a tracking link name";
}

/** Where a modal goes when closed: its own Cancel link's href (back to its tab). */
function modalCancel(doc: Document): string {
  return doc.querySelector(".modal-footer a[href]")?.getAttribute("href") ?? "";
}

/** FastAPI's own answers when the Relay has no such route (an OF error comes as 502 with an object detail instead). */
const NO_ROUTE: Record<number, string> = { 404: "Not Found", 405: "Method Not Allowed" };
/** What a note says for those: the Relay runs older code than the app, so the action never reached OF. */
export const OLD_RELAY = "the Relay runs older code that cannot do this yet (restart it on the app's branch)";

export const message = (e: unknown) =>
  e instanceof RelayError && NO_ROUTE[e.status] !== undefined && (e.body as { detail?: unknown } | null)?.detail === NO_ROUTE[e.status]
    ? OLD_RELAY
    : e instanceof Error
      ? e.message
      : String(e);
/** OF's own error text (its `error.message`) in a relay error, as OF's toasts show it; null without one. */
export const ofErrorMessage = (e: unknown): string | null => (e instanceof RelayError ? (parseSendFailure(e.body).reason ?? null) : null);

/**
 * Wire the writable controls of the mirrored page at `path` (its full path under of-mirror/pages:
 * a settings page's WRITABLE controls, a SUBMITS page's form) in `doc`; every other changed control outside
 * [data-oi-wired] gets the read-only note (a checkbox flips back), in either scope, on any page. Each of those Wired controls (and a form's fields) is marked `data-oi-wired`, in either scope.
 * Any other clicked button or [role=button] (outside NOT_FALLBACK) gets the read-only note, in either scope, on any page;
 * the story strip's tiles keep bindStory's note, which sits under the strip.
 * A SUBMITS button posts its form (an invalid form: nothing, the validation
 * note) and then navigates.
 * Every native submit is cancelled (a SUBMITS page's is sent), so none reloads the frame.
 * `handlers` null (no single model selected): a writable control's Save, switch or submit sends nothing
 * and gets the select-a-model note instead. Returns an unbind.
 */
export function bindWrites(doc: Document, path: string, handlers: WriteHandlers | null): () => void {
  takeCarried(doc);
  const unbindBank = path.startsWith("bank/") ? bankNote(doc) : () => {};
  const unbindPickers = path === "streaming/dashboard/create" ? streamPickers(doc) : () => {};
  const page = settingsPage(path);
  const map = page !== null && Object.hasOwn(WRITABLE, page) ? WRITABLE[page] : {};
  const entry = Object.hasOwn(SUBMITS, path) ? SUBMITS[path] : null;
  const entryButton = entry ? doc.querySelector<HTMLButtonElement>(entry.button) : null;
  // A SUBMITS page's form, once its button is found.
  const form = entry && entryButton ? { submit: entry, button: entryButton } : null;
  // A submit button captured disabled (Create Link) turns on while its form is valid, as on OF.
  const gated = form?.button.disabled ? form : null;
  let sending = false;
  const writable = (t: Element | null) => {
    for (const [sel, field] of Object.entries(map)) if (t?.closest(sel)) return field;
    return null;
  };
  const dirty = new Set<string>();
  // Profile's Save (any other page's Save has no Known body: the click fallback's).
  const save = page === "profile" ? doc.querySelector<HTMLButtonElement>(SAVE) : null;
  // The Wired controls, in either scope: the page's WRITABLE fields, profile Save, a SUBMITS button and the fields it sends.
  const wired = [
    ...Object.keys(map).flatMap((sel) => [...doc.querySelectorAll(sel)]),
    ...(save ? [save] : []),
    ...(form ? [form.button, ...doc.querySelectorAll(form.submit.fields)] : []),
  ];
  for (const el of wired) el.setAttribute("data-oi-wired", "");

  const onInput = (ev: Event) => {
    if (form) doc.getElementById("oi-note")?.remove(); // a validation note is stale once the form changes
    // A form's text editor, or a WRITABLE one (Edit profile's Bio): OF's own script raises its label and counts its text.
    const editor = (ev.target as Element | null)?.closest?.("[contenteditable][data-placeholder]");
    if (editor && (form || writable(editor))) {
      const len = textOf(editor).length;
      editor.setAttribute("data-is-empty", String(!len));
      const count = editor.closest(".g-input__wrapper")?.querySelector(".count-block");
      if (count) count.textContent = count.textContent!.replace(/\d+(?=\/)/, String(len));
    }
    // A text field (a modal's name, Edit profile's Display name): its label floats clear of the value and its counter
    // counts.
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
      // (any Mirror page, either scope; a SUBMITS page's fields are its form's, sent by its submit)
      note(doc, t.closest(LIST_ROW) ?? t, READ_ONLY); // after an OF list row (a label, a tag), not inside it
      if (t.type === "checkbox") t.checked = !t.checked; // nothing was saved: show the real state again
    }
  };

  /** The form's submit (its button's click or a native form submit): post the body, then navigate. */
  const send = () => {
    if (!form) return;
    const { submit, button } = form;
    if (!handlers) return note(doc, button, SELECT_MODEL);
    if (button.disabled) return;
    const body = submit.collect(doc, new Date());
    if (typeof body === "string") return note(doc, button, body, true);
    button.disabled = sending = true;
    doc.getElementById("oi-note")?.remove();
    handlers.submit(submit.send, body).then(
      () => handlers.navigate(submit.then(doc)),
      (e) => {
        button.disabled = sending = false;
        const of = submit.ofToast ? ofErrorMessage(e) : null;
        if (submit.closeOnError) handlers.navigate(submit.then(doc), of ?? `${submit.fail}: ${message(e)}`);
        else if (of) toast(doc, of);
        else note(doc, button, `${submit.fail}: ${message(e)}`, true);
      },
    );
  };

  /** Every native submit (Enter in a field, a submit button's click), on any page: cancelled, so it never reloads the frame; a SUBMITS page's is sent. */
  const onSubmit = (ev: Event) => {
    ev.preventDefault();
    send();
  };

  /** The click fallback: any other button or [role=button] says it is read-only (no preventDefault: skips are markup). */
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
    if (!dirty.size) return;
    if (!handlers) return note(doc, save, SELECT_MODEL);
    const fields = [...dirty];
    save.disabled = true;
    handlers.saveProfile(collectProfilePatch(doc, fields)).then(
      () => {
        for (const f of fields) dirty.delete(f);
        save.disabled = dirty.size === 0;
        toast(doc, SAVED_TOAST);
      },
      (e) => {
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
  };
}

/**
 * The stream form's Date and Time (OF's two vdatetime fields), as the Add to queue modal's (dateTimeFields): a click on
 * the date opens OF's day popup (ofMirrorDatepicker, from `today` on); the time is the browser's time input, its picker
 * opened from OF's clock icon. Returns the remover of the popup's trigger.
 */
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
      date.dispatchEvent(new Event("input", { bubbles: true })); // SCHEDULE's gate and the stale note follow it
    } });
  };
  box.addEventListener("click", open);
  return () => {
    box.removeEventListener("click", open);
    style.remove();
  };
}

/** BANK_NOTE under a Bank page's title (its sticky header), with a link to OF's own banking page. Returns its remover. */
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

/** Every Mirror page: bind the controls on every frame load (writes only with a single model selected). */
export function useOfWrites(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const path = mirrorPageOfPath(src) ?? "";
  const entry = Object.hasOwn(SUBMITS, path) ? SUBMITS[path] : null;
  // The stream form opened from the Queue's "+": its day and time.
  const stream = path === "streaming/dashboard/create";
  const streamDate = stream ? params.get("date") : null;
  const streamTime = stream ? params.get("time") : null;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["of-me", accountId] });
    qc.invalidateQueries({ queryKey: ["of-settings"] });
    qc.invalidateQueries({ queryKey: ["reply-on-subscribe", accountId] });
  };
  const { mutateAsync: saveProfile } = useMutation({
    mutationFn: (body: ProfilePatch) => relay.patch("/api/of/v2/users/me", body, { accountId }),
    onSuccess: refresh,
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
      unbind = doc?.body ? bindWrites(doc, path, accountId ? { saveProfile, setReplyOnSubscribe, submit, navigate } : null) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, entry, accountId, qc, saveProfile, setReplyOnSubscribe, router, stream, streamDate, streamTime]);
}
