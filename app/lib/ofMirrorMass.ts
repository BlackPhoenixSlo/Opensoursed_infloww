"use client";

/**
 * Write-through for New message (messages/send) of the OF mirror's Messages tab. All wiring is runtime DOM.
 *
 * New message (messages/send, single Creator): the Send to rows are the Creator's user lists (GET /api/of/v2/lists, OF's
 * own built-ins like "fans" included), each a checkbox kept on the Mass draft (`oi:mass:<accountId>`) with the text. The
 * left tabs are OF's own ?list= views of the one page: Send to ticks `user_lists`, Exclude ticks `excluded_user_lists` (a
 * list picked on one tab is disabled on the other, as OF's), Users ticks fans one by one (`user_ids`; the Creator's recent
 * chats, GET /api/of/v2/chats). A ticked row drops OF's `m-not-active` (its tick shows only then); anything picked puts
 * OF's "N Selected ⊗" chip over the search (⊗ drops every pick) and titles the right side "New message to selected
 * list". Search users and lists filters the tab's rows. Send
 * asks first (window.confirm, naming the lists and their user count), then sends one POST /api/of/v2/messages/queue
 * {text, user_lists} (OF's mass message, sent now), or with the draft's `scheduled_date` {text, user_lists,
 * scheduled_date}, OF's scheduled mass message; saved for later it goes to POST /api/of/v2/messages/queue/later
 * {…, save_for_later} (OF's Save for later: no date, never sent now).
 * Its composer's tools are ofMirrorChatShared's (bindTools), on the Mass draft: Add media, Record voice and video and drops
 * (`media_files`), Add GIF (`giphy_id`), Format text (the text as OF's markup), and the price, vault and tag dialogs over
 * New message (messages/send/state-price, state-vault, state-tag-people; the generator's sendStates), their picks the
 * draft's `price`, `media_files` and `tags` (creators only: the Relay's mass body has `tagged_users` and no guest or
 * release-form field, NO_MASS_FORMS). OF's GIF rule holds as in a chat; Clear drops every extra (not the recipients).
 * The schedule button opens a date and time dialog in the Agency's time zone (Cancel, Save for Later, Next) that puts
 * either on the draft; the Queue's Add to queue puts them there too. The line under the editor names them ("Scheduled
 * for … · Clear", "Saved for later · Clear").
 * Edit message (the Queue's row menu) fills the Mass draft from the queued message (its text, media, price, recipients,
 * lists, excluded lists and date, and `edit_id`): Send then saves that message in place, PUT
 * /api/of/v2/messages/queue/{id} with the same body (a new date is OF's reschedule; an edit always keeps a date or Save
 * for later), and goes back to the Queue or the saved-for-later page. The line names the edit, the picked recipients, the
 * media and the price it keeps; Discard drops the draft. The tools change the edit's media, price and tags (the Relay's
 * edit body has them), not a GIF (it has none: NO_EDIT_GIF).
 *
 * All models and no model: as ofMirrorChat's.
 */

import { restore, setAttr, setText, stamp } from "@/lib/ofMirrorDom";
import { applyListRows, markRow, MASS_ROW, usersLabel } from "@/lib/ofMirrorDataLists";
import { type bindComposer, GIF_ALONE } from "@/lib/ofMirrorComposer";
import { hasFormatting, ofHtml, setOfHtml } from "@/lib/ofMirrorFormat";
import { MASS_VAULT } from "@/lib/ofMirrorRow";
import { dateTimeFields, GREY, localIso, message, minuteAhead, note, NOTE_STYLE, openModal, schedulePill, SELECT_MODEL, textOf, TOO_SOON } from "@/lib/ofMirrorWrites";
import { fromWallClock, wallClock } from "@/lib/ofMirrorFeedsShared";
import { ofPrice } from "@/lib/ofMirrorPostCard";
import {
  bindChatTags,
  bindPrice,
  bindTools,
  bindVault,
  EDITOR,
  EMPTY_MESSAGE,
  flight,
  FORM_TAGS,
  load,
  NO_DATE,
  NO_EDIT_GIF,
  SEND,
  setEditor,
  SUMMARY,
  UPLOADING,
  vaultPickKey,
  type ChatContext,
  type ChatDialog,
  type ChatDraft,
  type ChatHandlers,
  type ChatTag,
  type MassView,
} from "@/lib/ofMirrorChatShared";

/** The Mass draft: its text and the picked user lists' ids (as strings: the Relay's `user_lists`). */
export interface MassDraft {
  text: string;
  user_lists: string[];
  /** Local ISO with offset (the schedule dialog, the Queue's Add to queue); none: sent now. */
  scheduled_date?: string;
  /** OF's Save for later: queued with no date (never alongside scheduled_date). */
  save_for_later?: boolean;
  /** Fans picked one by one (the Users tab, or an edited message's `userIds`). */
  user_ids?: number[];
  /** Lists left out (the Exclude tab, or an edited message's `excludedLists`). */
  excluded_user_lists?: string[];
  /** Vault ids (the vault dialog's picks, an edited message's media) and Add media's upload claims, in order. */
  media_files?: Array<number | Record<string, unknown>>;
  /** thumbs[i] is the picture of media_files[i] (none for an edited message's own media). */
  thumbs?: string[];
  /** PPV price in dollars (the price dialog, an edited message's); absent: free. */
  price?: number;
  /** The composer's tools, as the Chat draft's: the text as OF's markup, Add GIF's pick, the tags and the voice notes. */
  html?: string;
  giphy_id?: string;
  giphy_thumb?: string;
  tags?: ChatTag[];
  audio?: number;
  /** The queued message this draft edits (the Queue's Edit message): Send saves it (PUT) instead of a new one. */
  edit_id?: string;
}

/** POST /api/of/v2/messages/queue (and PUT …/queue/{id}): the Relay's _MassScheduleBody subset (neither date: sent now). */
export interface MassMessageBody {
  text: string;
  user_lists: string[];
  scheduled_date?: string;
  save_for_later?: true;
  user_ids?: number[];
  excluded_user_lists?: string[];
  media_files?: Array<number | Record<string, unknown>>;
  price?: number;
  /** Tagged creators (OF's userTags). */
  tagged_users?: number[];
  /** OF's `giphyId`. */
  giphy_id?: string;
}

export const NO_LISTS = "Pick at least one list";
/** The Relay's mass body tags creators only (`tagged_users`): no guest or release-form field. */
export const NO_MASS_FORMS = "A mass message can only tag creators";
export const MASS_TAG = "messages/send/state-tag-people";
/** New message's "N Selected ⊗" chip over the search (OF's filter counter) and its search field. */
const SELECTED = "oi-mass-selected";
const MASS_SEARCH = ".b-search-users-form input";
/** The Users tab's fans: the Creator's recent chats (the Relay's GET /chats, OF's order). */
export const MASS_FANS = "/api/of/v2/chats?limit=50";
/** The most ids OF's /users/list resolves in one read (more are dropped). */
export const USERS_LIST_MAX = 20;

export const massViewOf = (list: string | null): MassView => (list === "exclude" || list === "users" ? list : "send");
const MASS_TABS: Array<[MassView, string, string]> = [
  ["send", "Send to", "/of-manager/messages/send"],
  ["exclude", "Exclude", "/of-manager/messages/send?list=exclude"],
  ["users", "Users", "/of-manager/messages/send?list=users"],
];
/** OF's right-hand title once anything is picked (the captured page's "Select users to send them a message" before). */
export const MASS_PICKED_TITLE = "New message to selected list";

export const massDraftKey = (accountId: string) => `oi:mass:${accountId}`;

export const loadMassDraft = (storage: Storage, accountId: string): MassDraft => load<MassDraft>(storage, massDraftKey(accountId), { text: "", user_lists: [] });
/** Tick `list` on the Mass draft's Send to (and off its Exclude, as a list ticked on one tab is off the other). */
export function tickMassList(storage: Storage, accountId: string, list: string): void {
  const d = loadMassDraft(storage, accountId);
  const next = { ...d, user_lists: d.user_lists.includes(list) ? d.user_lists : [...d.user_lists, list], excluded_user_lists: d.excluded_user_lists?.filter((l) => l !== list) };
  storage.setItem(massDraftKey(accountId), JSON.stringify(next));
}

/**
 * The mass message body for `text` and the draft (its lists, kept recipients, media, price, tagged creators, GIF and date
 * or Save for later), or the validation note. An edit needs a date or Save for later (NO_DATE) and carries no GIF. A list
 * also excluded goes in `excluded_user_lists` only.
 */
export function collectMass(text: string, draft: MassDraft, now: Date = new Date()): MassMessageBody | string {
  const t = text.trim();
  const media = draft.media_files ?? [];
  const ids = draft.user_ids ?? [];
  const tags = draft.tags ?? [];
  const gif = draft.giphy_id;
  const excluded = draft.excluded_user_lists ?? [];
  const sendTo = draft.user_lists.filter((l) => !excluded.includes(l));
  if (!t && !media.length && !gif) return EMPTY_MESSAGE;
  if (!sendTo.length && !ids.length) return NO_LISTS;
  if (tags.some((x) => FORM_TAGS.includes(x.type))) return NO_MASS_FORMS;
  // OF's rule, as a chat's: a GIF goes with no media but a voice note, no price and no tags.
  if (gif && (media.length > (draft.audio ?? 0) || tags.length || draft.price)) return GIF_ALONE;
  if (gif && draft.edit_id) return NO_EDIT_GIF;
  const body: MassMessageBody = { text: t, user_lists: sendTo };
  if (ids.length) body.user_ids = [...ids];
  if (excluded.length) body.excluded_user_lists = [...excluded];
  if (media.length) body.media_files = [...media];
  if (draft.price) body.price = draft.price;
  if (tags.length) body.tagged_users = tags.map((x) => x.id);
  if (gif) body.giphy_id = gif;
  if (draft.save_for_later) body.save_for_later = true;
  else if (draft.scheduled_date) {
    if (!minuteAhead(new Date(draft.scheduled_date), now)) return TOO_SOON;
    body.scheduled_date = draft.scheduled_date;
  } else if (draft.edit_id) return NO_DATE;
  return body;
}

/**
 * The Relay request Send makes for the Mass draft: the edited queued message saved in place, a new one saved for later
 * (its own route: a Relay that predates Save for later answers 405 there instead of sending the message at once), or a
 * new mass message (now or scheduled).
 */
export const massRequest = (draft: MassDraft): { method: "POST" | "PUT"; path: string } =>
  draft.edit_id
    ? { method: "PUT", path: `/api/of/v2/messages/queue/${encodeURIComponent(draft.edit_id)}` }
    : { method: "POST", path: draft.save_for_later ? "/api/of/v2/messages/queue/later" : "/api/of/v2/messages/queue" };

/** New message's dialogs: a chat's (its schedule is bindMass' own dialog). */
const MASS_DIALOGS: Record<string, ChatDialog> = {
  [MASS_TAG]: bindChatTags,
  "messages/send/state-price": bindPrice,
  [MASS_VAULT]: bindVault,
};
const MASS_PAGE = "/of-manager/messages/send";

/**
 * New message's Send to before the user lists are here: OF's "Nothing found" reads "Loading lists…" while the Relay
 * answers, or the red "Could not load lists: <the Relay's text>" after it failed. The unbind's restore puts it back.
 */
function listsStatus(doc: Document, error: string | undefined, what: "lists" | "fans" = "lists"): void {
  const text = doc.querySelector<HTMLElement>(".b-chats__scroller [data-oi-empty] .empty-message > span");
  if (!text) return;
  setText(doc, text, error === undefined ? `Loading ${what}…` : `Could not load ${what}: ${error}`);
  if (error !== undefined) setAttr(doc, text, "style", "color:#ff4545");
}

/** New message's schedule button, its dialog's id, and where an edit or a message saved for later lands. */
const SCHEDULE_BTN = "button[at-attr='scheduled_msg']";
const MASS_SCHEDULE = "oi-mass-schedule";
const QUEUE_PAGE = "/of-manager/queue";
const SFL_MESSAGES = "/of-manager/queue/saved-for-later-messages";
/** The schedule dialog's title: the schedule button's own (captured) label. */
export const SCHEDULE_TITLE = "Scheduled messages";

/**
 * Wire New message (messages/send, or one of its dialogs' pages `page`) in `doc`: the list rows, the composer and its
 * tools (a chat's), and the open dialog. Returns an unbind.
 */
export function bindMass(doc: Document, ctx: ChatContext, page = "messages/send"): () => void {
  const { handlers, lists, zone } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const send = doc.querySelector<HTMLButtonElement>(SEND);
  if (!editor || !send) return () => {};
  const keep = handlers && ctx.storage && ctx.accountId ? { storage: ctx.storage, key: massDraftKey(ctx.accountId), accountId: ctx.accountId } : null;
  const draftOf = (): MassDraft => (keep ? loadMassDraft(keep.storage, keep.accountId) : { text: "", user_lists: [] });
  // Off its vault dialog (its Close, the backdrop, Add): the dialog's ticks are gone, as OF's.
  if (page !== MASS_VAULT && ctx.storage && ctx.accountId) ctx.storage.removeItem(vaultPickKey(ctx.accountId, MASS_VAULT));
  const update = (patch: Partial<MassDraft>) => {
    if (keep) keep.storage.setItem(keep.key, JSON.stringify({ ...draftOf(), ...patch }));
  };
  /** The draft's moment as the Agency zone's wall clock reads it ("Oct 27, 8:15 pm"). */
  const at = (iso: string) => stamp(wallClock(new Date(iso), zone));
  const link = (text: string, attr: string) => {
    const a = doc.createElement("a");
    a.href = "#";
    a.textContent = text;
    a.setAttribute("data-oi-wired", "");
    a.setAttribute(attr, "");
    return a;
  };
  /** The line under the editor: the edit, kept recipients, media and price, and the date or Save for later. */
  const summary = () => {
    const d = draftOf();
    const parts = [
      ...(d.edit_id ? [d.save_for_later ? "Editing a message saved for later" : "Editing a scheduled message"] : []),
      ...(d.user_ids?.length ? [`${usersLabel(d.user_ids.length)} picked`] : []),
      ...(d.excluded_user_lists?.length ? [`${d.excluded_user_lists.length} excluded ${d.excluded_user_lists.length === 1 ? "list" : "lists"}`] : []),
      ...(d.media_files?.length ? [`${d.media_files.length} media`] : []),
      ...(d.giphy_id ? ["GIF"] : []),
      ...(d.tags?.length ? [`Tagged: ${d.tags.map((t) => t.name || `#${t.id}`).join(", ")}`] : []),
      ...(d.price ? [`Price: ${ofPrice(d.price)}`] : []),
      ...(d.save_for_later ? ["Saved for later"] : d.scheduled_date ? [`Scheduled for ${at(d.scheduled_date)}`] : []),
    ];
    schedulePill(doc, editor, d.edit_id ? (d.save_for_later ? "Saved for later" : d.scheduled_date ? at(d.scheduled_date) : null) : null);
    const old = doc.getElementById(SUMMARY);
    if (!parts.length) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = SUMMARY;
    el.style.cssText = NOTE_STYLE;
    el.style.color = GREY;
    el.replaceChildren(`${parts.join(" · ")} · `, link("Clear", "data-oi-clear"), ...(d.edit_id ? [" · ", link("Discard", "data-oi-discard")] : []));
    if (!old) (editor.closest(".g-input__wrapper") ?? editor).after(el);
  };
  summary();
  // The left tab (OF's ?list=): Send to and Exclude tick lists (a list picked on one is disabled on the other, as OF's),
  // Users ticks fans one by one (the draft's user_ids, OF's userIds).
  const view = ctx.massView ?? "send";
  const pickedOf = (d: MassDraft): string[] => (view === "send" ? d.user_lists : view === "exclude" ? (d.excluded_user_lists ?? []) : (d.user_ids ?? []).map(String));
  const setPicked = (ids: string[]) => update(view === "send" ? { user_lists: ids } : view === "exclude" ? { excluded_user_lists: ids } : { user_ids: ids.map(Number) });
  const tabRows = view === "users" ? ctx.fans : lists;
  if (handlers && tabRows) {
    const d = draftOf();
    applyListRows(doc, tabRows, pickedOf(d), undefined, view === "send" ? (d.excluded_user_lists ?? []) : view === "exclude" ? d.user_lists : []);
  } else if (handlers) listsStatus(doc, ctx.listsError, view === "users" ? "fans" : "lists");
  const tabs = [...doc.querySelectorAll<HTMLAnchorElement>("a.b-tabs__nav__link")];
  for (const [v, label, href] of MASS_TABS) {
    const a = tabs.find((t) => t.textContent?.trim() === label);
    if (!a) continue;
    setAttr(doc, a, "href", href);
    setAttr(doc, a, "data-oi-wired", "");
    const cls = [...a.classList].filter((c) => c !== "m-current" && c !== "m-no-pointer");
    setAttr(doc, a, "class", [...cls, ...(v === view ? ["m-current", "m-no-pointer"] : [])].join(" "));
  }
  // The right-hand title and OF's "N Selected ⊗" chip over the search: what is picked to receive it (the picked lists'
  // users and the fans picked one by one; OF's own count leaves out the excluded and the ones it can't message).
  const title = doc.querySelector(".b-chat__header .g-page-title .b-inside-el");
  const titleWas = title?.textContent ?? "";
  const searchWrap = doc.querySelector(".b-search-users-form__wrapper");
  const selected = () => {
    const d = draftOf();
    const ids = d.user_ids ?? [];
    const any = d.user_lists.length + ids.length > 0;
    if (title) title.textContent = any ? MASS_PICKED_TITLE : titleWas;
    searchWrap?.classList.toggle("m-active-filter", any);
    let chip = doc.getElementById(SELECTED);
    if (!any || !searchWrap) return chip?.remove();
    if (!chip) {
      chip = doc.createElement("div");
      chip.id = SELECTED;
      chip.className = "b-filter-counter__wrapper";
      chip.innerHTML =
        '<div class="b-tabs__nav m-nv m-tab-rounded m-multiple-current mb-0"><ul class="b-tabs__nav__list m-gaps-inside m-gaps-outside"><li class="b-tabs__nav__item">' +
        // icon-profile: the captured sprite has no OF icon-friends.
        '<span class="b-tabs__nav__link m-reset-wcag-link-focus"><div class="b-tabs__nav__icon m-inside-icon m-avatar-gap"><svg class="g-icon" aria-hidden="true"><use href="#icon-profile" xlink:href="#icon-profile"></use></svg></div>' +
        '<span class="b-tabs__nav__text"></span><button type="button" at-attr="filter_delete_btn" data-oi-wired="" aria-label="Clear the selection" class="g-btn m-rounded m-reset-width m-btn-remove m-secondary m-sm-icon-size">' +
        '<svg class="g-icon" aria-hidden="true"><use href="#icon-close" xlink:href="#icon-close"></use></svg></button></span></li></ul></div>';
      searchWrap.prepend(chip);
    }
    const n = (lists ?? []).filter((l) => d.user_lists.includes(String(l.id))).reduce((s, l) => s + (l.usersCount ?? 0), 0) + ids.length;
    chip.querySelector(".b-tabs__nav__text")!.textContent = ` ${n} Selected `;
  };
  selected();
  /** Untick every row on the page and enable it (the picks were dropped). */
  const untick = () => {
    for (const box of doc.querySelectorAll<HTMLInputElement>(`${MASS_ROW}[data-oi-list] input[type='checkbox']`)) {
      box.checked = false;
      box.disabled = false;
      markRow(box.closest(MASS_ROW)!, false);
    }
  };
  const search = doc.querySelector<HTMLInputElement>(MASS_SEARCH);
  // All-Creators: the example rows are this binder's (the select-a-model note), not bindWrites' Read-only one.
  if (!handlers) for (const row of doc.querySelectorAll(MASS_ROW)) row.setAttribute("data-oi-wired", "");
  send.setAttribute("data-oi-wired", "");
  let composer: ReturnType<typeof bindComposer> | null = null;
  const sync = () => {
    const text = textOf(editor);
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const d = draftOf();
    send.disabled = (!text.trim() && !d.media_files?.length && !d.giphy_id) || flight.count > 0;
    composer?.sync();
  };
  const saved = draftOf();
  if (saved.html) setOfHtml(editor, saved.html);
  else setEditor(doc, editor, saved.text);
  sync();
  // The composer's tools and dialogs work on the Mass draft seen as a Chat draft (the same fields), as a chat's.
  const chatDraft = (): ChatDraft => {
    const d = draftOf();
    return { ...d, media_files: d.media_files ?? [], thumbs: d.thumbs ?? [] };
  };
  const edit = (patch: Partial<ChatDraft>) => {
    update(patch);
    summary();
    sync();
  };
  const ready = (anchor: Element): ChatHandlers | null => handlers ?? (note(doc, anchor, SELECT_MODEL), null);
  const refresh = () => {
    summary();
    sync();
  };
  const tools = bindTools(doc, editor, send, { draftOf: chatDraft, update: edit, refresh, ready, writer: handlers, none: SELECT_MODEL, accountId: ctx.accountId, key: keep?.key ?? `${ctx.accountId ?? ""}:mass`, mobile: ctx.mobile });
  composer = tools.composer;
  sync();
  const unbindDialog = Object.hasOwn(MASS_DIALOGS, page)
    ? MASS_DIALOGS[page](doc, ctx, { page, draftOf: chatDraft, update: edit, back: MASS_PAGE, ready, toggleMute: () => {}, writer: handlers, stay: (href) => href })
    : () => {};

  /** The schedule dialog: the draft's date (else ten minutes from now) in the Agency's zone; Next or Save for Later. */
  const schedule = (opener: Element) => {
    const d = draftOf();
    const soon = new Date(Date.now() + 600_000);
    const fields = dateTimeFields(doc, wallClock(d.scheduled_date ? new Date(d.scheduled_date) : soon, zone), wallClock(new Date(), zone));
    const flat = "g-btn m-flat m-btn-gaps m-reset-width";
    const { close } = openModal(doc, MASS_SCHEDULE, SCHEDULE_TITLE, (body) => body.append(fields.row), [
      { text: "Cancel", className: flat, onClick: () => close() },
      {
        text: "Save for Later",
        className: `${flat} custom-datepicker-button-save-later`,
        onClick: () => {
          update({ save_for_later: true, scheduled_date: undefined });
          close();
          summary();
        },
      },
      {
        text: "Next",
        className: flat,
        onClick: () => {
          const wall = fields.read();
          const when = wall && fromWallClock(wall, zone);
          if (!when || !minuteAhead(when, new Date())) return note(doc, fields.row, TOO_SOON, true);
          update({ scheduled_date: localIso(when), save_for_later: undefined });
          close();
          summary();
        },
      },
    ], opener);
  };

  const onInput = (ev: Event) => {
    // Search users and lists: the tab's rows whose name (or @handle) holds the text, OF's filter.
    if (search && ev.target === search) {
      const q = search.value.trim().toLowerCase();
      for (const row of doc.querySelectorAll<HTMLElement>(`${MASS_ROW}[data-oi-list]`)) row.style.display = !q || (row.textContent ?? "").toLowerCase().includes(q) ? "" : "none";
      return;
    }
    if (!(ev.target as Element | null)?.closest?.(EDITOR)) return;
    sync();
    update({ text: textOf(editor), html: hasFormatting(editor) ? ofHtml(editor) : undefined });
  };
  // Enter in the search field would submit OF's form (a navigation of the frame).
  const onSubmit = (ev: Event) => {
    if ((ev.target as Element | null)?.closest?.(".b-search-users-form")) ev.preventDefault();
  };
  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement;
    const row = box.closest?.<HTMLElement>(MASS_ROW);
    if (!row) return;
    if (!handlers) {
      box.checked = !box.checked; // nothing was picked: show the real state again
      return note(doc, row, SELECT_MODEL);
    }
    const id = row.getAttribute("data-oi-list");
    if (!id) return; // an example row: bindWrites' change path
    const others = pickedOf(draftOf()).filter((l) => l !== id);
    setPicked(box.checked ? [...others, id] : others);
    selected();
    summary();
  };
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (target?.closest?.(`#${SELECTED} [at-attr='filter_delete_btn']`)) {
      ev.preventDefault();
      update({ user_lists: [], excluded_user_lists: undefined, user_ids: undefined });
      untick();
      selected();
      return summary();
    }
    if (target?.closest?.("[data-oi-clear]")) {
      ev.preventDefault();
      update({ scheduled_date: undefined, save_for_later: undefined, price: undefined, media_files: undefined, thumbs: undefined, giphy_id: undefined, giphy_thumb: undefined, tags: undefined, audio: undefined });
      return refresh();
    }
    if (target?.closest?.("[data-oi-discard]")) {
      ev.preventDefault();
      if (keep) keep.storage.removeItem(keep.key);
      setEditor(doc, editor, "");
      untick();
      sync();
      selected();
      return summary();
    }
    const plan = target?.closest?.<HTMLButtonElement>(SCHEDULE_BTN);
    if (plan) {
      ev.preventDefault();
      return handlers ? schedule(plan) : note(doc, plan, SELECT_MODEL);
    }
    if (target?.closest?.(SEND) !== send) return;
    ev.preventDefault();
    if (!handlers) return note(doc, send, SELECT_MODEL);
    if (flight.count > 0) return note(doc, send, UPLOADING);
    if (send.disabled) return;
    const draft = draftOf();
    const body = collectMass(hasFormatting(editor) ? ofHtml(editor) : textOf(editor), draft);
    if (typeof body === "string") return note(doc, send, body, true);
    const picked = (lists ?? []).filter((l) => body.user_lists.includes(String(l.id)));
    const count = picked.reduce((n, l) => n + (l.usersCount ?? 0), 0);
    const names = picked.map((l) => l.name ?? String(l.id)).join(", ");
    const audience = [
      ...(body.user_lists.length ? [`${usersLabel(count)} on ${names || `${body.user_lists.length} lists`}`] : []),
      ...(body.user_ids?.length ? [`${usersLabel(body.user_ids.length)} picked`] : []),
    ].join(" and ") + (body.price ? ` for ${ofPrice(body.price)}` : "");
    const when = body.save_for_later ? "for later" : body.scheduled_date ? `for ${at(body.scheduled_date)}` : "";
    const ask = draft.edit_id
      ? `Save this message ${when} to ${audience}?`
      : body.save_for_later
        ? `Save this message for later to ${audience}?`
        : body.scheduled_date
          ? `Schedule this message for ${at(body.scheduled_date)} to ${audience}?`
          : `Send this message to ${audience}?`;
    if (!handlers.confirm(ask)) return;
    const req = massRequest(draft);
    const go = req.method === "PUT" ? handlers.put : handlers.send;
    if (!go) return;
    send.disabled = true;
    doc.getElementById("oi-note")?.remove();
    go(req.path, body).then(
      () => {
        if (keep) keep.storage.removeItem(keep.key);
        // An edit, or a message saved for later, goes to where it is listed, as OF's (MessagesSavedForLater, the queue).
        // (OF opens the queue on the message's day: /my/queue/<yyyy-mm-dd>.)
        if (draft.edit_id || body.save_for_later) return handlers.navigate(body.save_for_later ? SFL_MESSAGES : `${QUEUE_PAGE}?date=${localIso(wallClock(new Date(body.scheduled_date!), zone)).slice(0, 10)}`);
        setEditor(doc, editor, "");
        untick();
        sync();
        selected();
        summary();
        note(doc, send, body.scheduled_date ? "Scheduled" : "Sent", false, 2000);
      },
      (e) => {
        sync();
        note(doc, send, `Could not ${draft.edit_id ? "save" : "send"}: ${message(e)}`, true);
      },
    );
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("submit", onSubmit);
  return () => {
    tools.unbind();
    unbindDialog();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("submit", onSubmit);
    doc.getElementById(SUMMARY)?.remove();
    doc.getElementById(SELECTED)?.remove();
    searchWrap?.classList.remove("m-active-filter");
    if (title) title.textContent = titleWas;
    if (search) search.value = "";
    doc.getElementById(MASS_SCHEDULE)?.remove();
    restore(doc);
  };
}
