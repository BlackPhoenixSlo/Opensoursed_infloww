"use client";

/**
 * Write-through for the Messages tab of the OF mirror: a chat's composer, its price, schedule and vault dialogs and its
 * header menu (messages/chat and its state-* pages), and New message (messages/send). All wiring is runtime DOM.
 *
 * Chat (single Creator, a real chat opened from the list: ?chat=<fanId>): typing in OF's editor enables Send. The text,
 * price, schedule and picked vault media are the Chat draft, kept per Creator and chat in sessionStorage
 * (`oi:chat:<accountId>:<fanId>`), so a State page round trip keeps it. A line under the editor names the extras
 * ("Price: $5 · Scheduled for … · 2 media · Clear"). Send sends one POST /api/of/v2/chats/<fanId>/messages
 * {text, price, media_files}, or with a schedule POST …/messages/scheduled {text, scheduled_date, price, media_files}
 * (the Relay's SendMessageBody and _ScheduleMessageBody), the path Messages Pro sends on. A priced message asks first
 * (window.confirm). Success clears the draft and refetches the thread, so the message shows in place; a failure keeps it
 * and shows the Relay's text in a red note (its re-sale guard's 409 included). With no chat open (no ?chat=) nothing is
 * sent: "Open a chat from the list to send".
 * - Add media: New post's upload (ofMirrorPost's bindAddMedia, POST /api/of/v2/upload); an accepted upload's `send_with`
 *   joins the draft's media_files. Send waits while an upload runs.
 * - Message price (state-price): the typed price ("" is free, else at least $3, OF's own minimum); Save keeps it on the draft.
 * - Scheduled messages (state-schedule): the same vue-datetime calendar as New post's; Next keeps the moment. Save for Later
 *   (no Relay body for one chat) is disabled by the generator.
 * - Add media from vault (state-vault): ofMirrorData shows the Creator's folders and vault media (none: OF's empty
 *   dialog), the draft's picks marked; a tile click picks or unpicks it, a folder row or type tab opens the dialog on that
 *   view (the chat kept), and Search media filters the tiles (New post's bindVaultSearch).
 * - The composer's own tools (ofMirrorComposer): Format text (the text then goes as OF's markup, the draft's `html`),
 *   Add GIF (`giphy_id`), Record voice and Record video (Add media's upload), dropped files (the same), and Send tip shown
 *   only where OF shows it (disabled: OF's tip is a card payment).
 * - Tag other creators (state-tag-people): New post's tag dialog (bindTags) over the chat; a row toggles a tag on the
 *   draft, sent as OF's chat fields: a creator (`rfTag`, the Relay's `tagged_users`), a guest (`rfGuest`, `rf_guest`), a
 *   release-form link or document (`rfPartner`, `rf_partner`).
 * - Scripts (OfManagerChrome's Fan insights column, over the chat's right edge): a picked script or saved reply replaces the draft's text, media, free
 *   previews, price, locked text, tags and GIF (applyScript), as Messages Pro's composer applies one.
 * - Header menu (state-header-menu) and the header's bell: Hide chat (POST …/hide, then the chat list) and Mute / Unmute
 *   notifications (POST / DELETE …/mute, labelled from the chat's real state). The menu's other items stay inert links.
 *
 * New message (messages/send): ofMirrorMass. What both share (the composer's tools, the price, vault and tag dialogs):
 * ofMirrorChatShared.
 *
 * All models: the Messages pages show the first model and act as it (standInModel). With no model at all: Send, Save, Next,
 * a tile, a list row and the menu items send nothing and show "Select a model to save changes" (a checkbox flips back); no
 * draft is kept.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { gifSearch, gifTrending, relay, type OFChatItem, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultUploadResp } from "@/lib/relay";
import { chatPath, handleOf, mirrorQuery, nameOf, usersListPath, withChatUsers, rowsOf, stamp, USER_LISTS, type UserList } from "@/lib/ofMirrorData";
import { afterChatWrite } from "@/lib/ofMirrorKeys";
import { collectSchedule, renderCalendar, tagsRoute, tagViewOf, type TagView } from "@/lib/ofMirrorPost";
import { type bindComposer, GIF_ALONE } from "@/lib/ofMirrorComposer";
import { hasFormatting, ofHtml, setOfHtml } from "@/lib/ofMirrorFormat";
import { CHAT_VAULT } from "@/lib/ofMirrorRow";
import { viewOf } from "@/lib/ofMirrorVault";
import { GREY, message, minuteAhead, note, NOTE_STYLE, SELECT_MODEL, textOf, TOO_SOON } from "@/lib/ofMirrorWrites";
import { useAgencyZone } from "@/lib/ofMirrorFeeds";
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
  SEND,
  setEditor,
  SUMMARY,
  UPLOADING,
  vaultPickKey,
  type ChatContext,
  type ChatDialog,
  type ChatDraft,
  type ChatHandlers,
} from "@/lib/ofMirrorChatShared";
import { bindMass, MASS_FANS, MASS_SEND, MASS_TAG, massViewOf, tickMassList, USERS_LIST_MAX } from "@/lib/ofMirrorMass";

export {
  EMPTY_MESSAGE,
  loadVaultPick,
  NO_DATE,
  NO_EDIT_GIF,
  readPrice,
  UPLOADING,
  VAULT_PICK_MAX,
  vaultPickKey,
  type ChatContext,
  type ChatDraft,
  type ChatHandlers,
  type ChatTag,
  type MassView,
  type VaultPick,
} from "@/lib/ofMirrorChatShared";
export {
  applyListRows,
  bindMass,
  collectMass,
  loadMassDraft,
  MASS_PICKED_TITLE,
  MASS_SEND,
  massDraftKey,
  massRequest,
  massViewOf,
  NO_LISTS,
  NO_MASS_FORMS,
  SCHEDULE_TITLE,
  tickMassList,
  type MassDraft,
  type MassMessageBody,
} from "@/lib/ofMirrorMass";

/** The chat draft changed outside the composer (a message's Reply): its line and Send are redrawn. */
export const DRAFT_EVENT = "oi-chat-draft";

/** The Relay's SendMessageBody subset; with `scheduled_date`, its _ScheduleMessageBody. */
export interface ChatMessageBody {
  text: string;
  price: number;
  media_files: Array<number | Record<string, unknown>>;
  scheduled_date?: string;
  /** OF's quote-reply (sent now only; the Relay's reply_to_message_id). */
  reply_to_message_id?: number;
  /** OF's `giphyId` (sent now only). */
  giphy_id?: string;
  /** Tagged creators (OF's `rfTag`), guests (`rfGuest`) and release-form links and documents (`rfPartner`). */
  tagged_users?: number[];
  rf_guest?: number[];
  rf_partner?: number[];
  /** The Relay's free previews (a subset of media_files) and locked text, with a price. */
  previews?: number[];
  locked_text?: boolean;
}

export const NO_CHAT = "Open a chat from the list to send";
export const NOT_LOADED = "This chat has not loaded yet";
/** The Relay's scheduled-message body has no GIF and no guest or release-form tags. */
export const NO_SCHEDULED_GIF = "A scheduled message can't carry a GIF";
export const NO_SCHEDULED_FORMS = "A scheduled message can only tag creators";
const TAG_PAGE = "messages/chat/state-tag-people";
const CHAT_PAGE = "/of-manager/messages/chat";
const MESSAGES = "/of-manager/messages";

const MUTE_BTN = "button[at-attr='mute_chat']";
const MENU_ITEM = ".of-state-menu .v-list-item";
/** The schedule dialog (vue-datetime), as on New post. */
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ISO = /^\d{4}-\d{2}-\d{2}T/;

export const chatDraftKey = (accountId: string, chat: string) => `oi:chat:${accountId}:${chat}`;
export const loadChatDraft = (storage: Storage, accountId: string, chat: string): ChatDraft =>
  load<ChatDraft>(storage, chatDraftKey(accountId, chat), { text: "", media_files: [], thumbs: [] });

/** A Messages Pro script or saved reply (TemplatePicker's PickedTemplate, the fields the Chat draft takes). */
export interface PickedScript {
  text: string;
  price: number;
  lockedText: boolean;
  media: { id: number }[];
  previews: number[];
  taggedUsers: number[];
  gifId?: string | null;
  gifUrl?: string | null;
}

/**
 * Put `t` on the Chat draft of `chat` as Messages Pro's composer applies a script (a snapshot: its text, media, free
 * previews, price, locked text, tagged creators and GIF replace the draft's; a reply and a schedule stay), then tell the
 * frame's composer (`doc`) to show it.
 */
export function applyScript(storage: Storage, accountId: string, chat: string, t: PickedScript, doc: Document | null): void {
  const d = loadChatDraft(storage, accountId, chat);
  const priced = t.price > 0;
  const next: ChatDraft = {
    ...d,
    text: t.text,
    html: undefined,
    price: priced ? t.price : undefined,
    media_files: t.media.map((m) => m.id),
    // Blank on purpose: nothing draws a Chat draft's thumbs (its summary counts media), and a template's VaultMedia only
    // carries raw OF CDN urls that would need the account's image proxy. Kept parallel to media_files, as an edit's are.
    thumbs: t.media.map(() => ""),
    audio: undefined,
    previews: priced && t.previews.length ? t.previews : undefined,
    locked_text: priced && t.lockedText ? true : undefined,
    tags: t.taggedUsers.length ? t.taggedUsers.map((id) => ({ id, type: "user", name: "" })) : undefined,
    giphy_id: t.gifId ?? undefined,
    giphy_thumb: t.gifId ? (t.gifUrl ?? undefined) : undefined,
  };
  storage.setItem(chatDraftKey(accountId, chat), JSON.stringify(next));
  doc?.dispatchEvent(new CustomEvent(DRAFT_EVENT, { detail: { text: true } }));
}

/** The send body for `text` and `draft` (and whether it is scheduled), or the validation note. */
export function collectMessage(text: string, draft: ChatDraft, now: Date = new Date()): ChatMessageBody | string {
  const t = text.trim();
  if (!t && !draft.media_files.length && !draft.giphy_id) return EMPTY_MESSAGE;
  const body: ChatMessageBody = { text: t, price: draft.price ?? 0, media_files: [...draft.media_files] };
  if (body.price > 0) {
    const free = (draft.previews ?? []).filter((id) => draft.media_files.includes(id));
    if (free.length) body.previews = free;
    if (draft.locked_text) body.locked_text = true;
  }
  // OF's chat mapper: a creator is rfTag, a guest rfGuest, a release form's link or document rfPartner.
  const tags = draft.tags ?? [];
  const of = (...types: string[]) => tags.filter((x) => types.includes(x.type)).map((x) => x.id);
  const users = tags.filter((x) => !FORM_TAGS.includes(x.type)).map((x) => x.id);
  const [guests, partners] = [of("guest"), of("link", "document")];
  if (users.length) body.tagged_users = users;
  if (draft.scheduled_date) {
    if (draft.giphy_id) return NO_SCHEDULED_GIF;
    if (guests.length || partners.length) return NO_SCHEDULED_FORMS;
    if (!minuteAhead(new Date(draft.scheduled_date), now)) return TOO_SOON;
    body.scheduled_date = draft.scheduled_date;
    return body;
  }
  if (draft.reply_to && /^\d+$/.test(draft.reply_to)) body.reply_to_message_id = Number(draft.reply_to);
  // OF's rule: a GIF goes with no media but a voice note, no price and no tags; a draft that has both is refused.
  if (draft.giphy_id && (draft.media_files.length > (draft.audio ?? 0) || tags.length || body.price)) return GIF_ALONE;
  if (draft.giphy_id) body.giphy_id = draft.giphy_id;
  if (guests.length) body.rf_guest = guests;
  if (partners.length) body.rf_partner = partners;
  return body;
}

/** The Relay path a chat message goes to: now, or OF's queue when scheduled. */
export const sendPath = (chat: string, body: ChatMessageBody) =>
  `/api/of/v2/chats/${encodeURIComponent(chat)}/messages${body.scheduled_date ? "/scheduled" : ""}`;

const shownMonth = (doc: Document): Date | null => {
  const [name, year] = (doc.querySelector(SHOWN)?.textContent ?? "").trim().split(/\s+/);
  const m = MONTHS.indexOf(name);
  return m >= 0 && /^\d{4}$/.test(year ?? "") ? new Date(+year, m, 1) : null;
};
const clock12 = (d: Date) => `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;

/**
 * Wire a chat page (`page`: messages/chat or one of its state-* pages) in `doc`: the composer, the open dialog and
 * the header's mute bell. Returns an unbind.
 */
export function bindChat(doc: Document, page: string, ctx: ChatContext): () => void {
  const { handlers, chat } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const send = doc.querySelector<HTMLButtonElement>(SEND);
  if (!editor || !send) return () => {};
  const keep = handlers && ctx.storage && ctx.accountId && chat ? { storage: ctx.storage, key: chatDraftKey(ctx.accountId, chat), accountId: ctx.accountId, chat } : null;
  const draftOf = (): ChatDraft => (keep ? loadChatDraft(keep.storage, keep.accountId, keep.chat) : { text: "", media_files: [], thumbs: [] });
  // Off its vault dialog (its Close, the backdrop, Add): the dialog's ticks are gone, as OF's.
  if (page !== CHAT_VAULT && ctx.storage && ctx.accountId) ctx.storage.removeItem(vaultPickKey(ctx.accountId, CHAT_VAULT, chat));
  const back = chat ? `${CHAT_PAGE}?chat=${encodeURIComponent(chat)}` : CHAT_PAGE;
  send.setAttribute("data-oi-wired", "");

  const summary = () => {
    const { price, scheduled_date: at, media_files: media, reply_to: reply, reply_text: quoted, giphy_id: gif, tags = [] } = draftOf();
    const parts = [
      ...(reply ? [`Replying to “${(quoted ?? "").slice(0, 60)}${(quoted ?? "").length > 60 ? "…" : ""}”`] : []),
      ...(price ? [`Price: ${ofPrice(price)}`] : []),
      ...(at ? [`Scheduled for ${stamp(new Date(at))}`] : []),
      ...(media.length ? [`${media.length} media`] : []),
      ...(gif ? ["GIF"] : []),
      ...(tags.length ? [`Tagged: ${tags.map((t) => t.name || `#${t.id}`).join(", ")}`] : []),
    ];
    const old = doc.getElementById(SUMMARY);
    if (!parts.length) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = SUMMARY;
    el.style.cssText = NOTE_STYLE;
    el.style.color = GREY;
    const clear = doc.createElement("a");
    clear.href = "#";
    clear.textContent = "Clear";
    clear.setAttribute("data-oi-wired", "");
    clear.setAttribute("data-oi-clear", "");
    el.replaceChildren(`${parts.join(" · ")} · `, clear);
    if (!old) (editor.closest(".g-input__wrapper") ?? editor).after(el);
  };
  const sync = () => {
    const text = textOf(editor);
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const d = draftOf();
    send.disabled = (!text.trim() && !d.media_files.length && !d.giphy_id) || flight.count > 0;
    composer?.sync();
  };
  let composer: ReturnType<typeof bindComposer> | null = null;
  const update = (patch: Partial<ChatDraft>) => {
    if (keep) keep.storage.setItem(keep.key, JSON.stringify({ ...draftOf(), ...patch }));
    summary();
    sync();
  };

  const saved = draftOf();
  if (saved.html) setOfHtml(editor, saved.html);
  else setEditor(doc, editor, saved.text);
  sync();
  summary();

  // The header's bell: its label follows the chat's real state.
  const bell = doc.querySelector<HTMLButtonElement>(MUTE_BTN);
  const muted = ctx.fan?.muted;
  if (bell && muted !== undefined) bell.setAttribute("aria-label", muted ? "Unmute notifications" : "Mute notifications");
  bell?.setAttribute("data-oi-wired", "");

  /** Check the scope and chat before a write; the note goes after `anchor`. */
  const ready = (anchor: Element): ChatHandlers | null => {
    if (!handlers) return note(doc, anchor, SELECT_MODEL), null;
    if (!chat) return note(doc, anchor, NO_CHAT), null;
    return handlers;
  };
  const toggleMute = (anchor: Element, then?: string) => {
    const h = ready(anchor);
    if (!h) return;
    if (muted === undefined) return note(doc, anchor, NOT_LOADED);
    h.mute(!muted).then(
      () => (then ? h.navigate(then) : note(doc, anchor, muted ? "Unmuted" : "Muted", false, 2000)),
      (e) => note(doc, anchor, `Could not save: ${message(e)}`, true),
    );
  };

  const onInput = (ev: Event) => {
    if (!(ev.target as Element | null)?.closest?.(EDITOR)) return;
    sync();
    update({ text: textOf(editor), html: hasFormatting(editor) ? ofHtml(editor) : undefined });
  };

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest("[data-oi-clear]")) {
      ev.preventDefault();
      return update({ price: undefined, scheduled_date: undefined, media_files: [], thumbs: [], reply_to: undefined, reply_text: undefined, giphy_id: undefined, giphy_thumb: undefined, tags: undefined, audio: undefined, previews: undefined, locked_text: undefined });
    }
    if (bell && target.closest(MUTE_BTN) === bell) {
      ev.preventDefault();
      return toggleMute(bell);
    }
    if (target.closest(SEND) !== send) return;
    ev.preventDefault();
    const h = ready(send);
    if (!h) return;
    if (flight.count > 0) return note(doc, send, UPLOADING);
    if (send.disabled) return;
    const body = collectMessage(hasFormatting(editor) ? ofHtml(editor) : textOf(editor), draftOf());
    if (typeof body === "string") return note(doc, send, body, true);
    if (body.price > 0 && !h.confirm(`Send this message to ${ctx.fan?.name || "this fan"} for ${ofPrice(body.price)}?`)) return;
    send.disabled = true;
    doc.getElementById("oi-note")?.remove();
    h.send(sendPath(chat!, body), body).then(
      () => {
        if (keep) keep.storage.removeItem(keep.key);
        setEditor(doc, editor, "");
        sync();
        summary();
        note(doc, send, body.scheduled_date ? "Scheduled" : "Sent", false, 2000);
      },
      (e) => {
        sync();
        note(doc, send, `Could not send: ${message(e)}`, true);
      },
    );
  };

  const writer = chat ? handlers : null;
  const stay = (href: string) => `${href}${href.includes("?") ? "&" : "?"}chat=${encodeURIComponent(chat!)}`;
  const unbindDialog = Object.hasOwn(CHAT_DIALOGS, page) ? CHAT_DIALOGS[page](doc, ctx, { page, draftOf, update, back, ready, toggleMute, writer, stay }) : () => {};
  const refresh = () => {
    summary();
    sync();
  };
  // Add media and the composer's tools (any chat page: the State pages' composer sits under their dialog). No chat open: nothing to attach to.
  const tools = bindTools(doc, editor, send, {
    draftOf,
    update,
    refresh,
    ready,
    writer,
    none: handlers ? NO_CHAT : SELECT_MODEL,
    accountId: ctx.accountId,
    key: keep?.key ?? `${ctx.accountId ?? ""}:${chat ?? ""}`,
    tipsEnabled: ctx.fan?.tipsEnabled,
    mobile: ctx.mobile,
  });
  composer = tools.composer;
  sync();
  const onDraft = (ev: Event) => {
    // A picked script (applyScript) brings its own text.
    if ((ev as CustomEvent<{ text?: boolean } | null>).detail?.text) {
      const d = draftOf();
      if (d.html) setOfHtml(editor, d.html);
      else setEditor(doc, editor, d.text);
    }
    refresh();
    editor.focus();
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  doc.addEventListener(DRAFT_EVENT, onDraft);
  return () => {
    doc.removeEventListener(DRAFT_EVENT, onDraft);
    tools.unbind();
    unbindDialog();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
}

/** Scheduled messages: opens on the draft's moment (else today, an hour from now); day cells, arrows and Next keep the moment. */
const bindSchedule: ChatDialog = (doc, _ctx, { draftOf, update, back, ready }) => {
  const timeTab = doc.querySelector<HTMLElement>(TIME_TAB);
  const next = doc.querySelector<HTMLButtonElement>(NEXT);
  if (!timeTab || !next) return () => {};
  const now = new Date();
  const saved = draftOf().scheduled_date;
  const at = saved ? new Date(saved) : null;
  const start = at && at.getTime() > now.getTime() ? at : null;
  renderCalendar(doc, start ?? now, start ?? now, now);
  timeTab.setAttribute("contenteditable", "true");
  timeTab.textContent = clock12(start ?? new Date(now.getTime() + 3_600_000));
  next.setAttribute("data-oi-wired", "");

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    const shown = shownMonth(doc);
    const cell = target.closest<HTMLElement>(`.${DAY}`);
    const day = Number(cell?.textContent?.trim());
    if (cell && shown && day && !cell.classList.contains(`${DAY}--disabled`)) {
      renderCalendar(doc, shown, new Date(shown.getFullYear(), shown.getMonth(), day), new Date());
    }
    const arrow = target.closest(".vdatetime-calendar__navigation--previous, .vdatetime-calendar__navigation--next");
    if (arrow && shown) {
      const today = new Date();
      const step = arrow.matches(".vdatetime-calendar__navigation--next") ? 1 : -1;
      const month = new Date(shown.getFullYear(), shown.getMonth() + step, 1);
      const sel = doc.querySelector(".vdatetime-popup")?.getAttribute("data-oi-selected");
      const picked = sel ? new Date(`${sel}T00:00:00`) : null;
      if (month >= new Date(today.getFullYear(), today.getMonth(), 1)) renderCalendar(doc, month, picked, today);
    }
    if (target.closest(NEXT) !== next) return;
    ev.preventDefault();
    const h = ready(next);
    if (!h) return;
    const moment = collectSchedule(doc);
    if (!ISO.test(moment)) return note(doc, next, moment, true);
    update({ scheduled_date: moment });
    h.navigate(back);
  };
  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
};

/** The header menu: Hide chat and Mute / Unmute notifications (its other items stay links back to the chat). */
const bindHeaderMenu: ChatDialog = (doc, ctx, { ready, toggleMute }) => {
  const items = [...doc.querySelectorAll<HTMLElement>(MENU_ITEM)];
  const hide = items.find((i) => i.textContent?.trim() === "Hide chat");
  const mute = items.find((i) => /^(?:un)?mute notifications$/i.test(i.textContent?.trim() ?? ""));
  const label = (el: HTMLElement, text: string) => {
    const t = [...el.childNodes].find((n) => n.nodeType === 3 && n.textContent?.trim());
    if (t) t.textContent = ` ${text} `;
  };
  if (mute && ctx.fan?.muted !== undefined) label(mute, ctx.fan.muted ? "Unmute notifications" : "Mute notifications");
  for (const el of [hide, mute]) el?.setAttribute("data-oi-wired", "");
  // Capture: before the frame's own link handler, which would go back to the chat.
  const onClick = (ev: MouseEvent) => {
    const item = (ev.target as Element | null)?.closest?.(MENU_ITEM);
    if (!item || (item !== hide && item !== mute)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (item === mute) return toggleMute(item, ctx.chat ? `${CHAT_PAGE}?chat=${encodeURIComponent(ctx.chat)}` : CHAT_PAGE);
    const h = ready(item);
    if (!h) return;
    h.hide().then(
      () => h.navigate(MESSAGES),
      (e) => note(doc, item, `Could not hide: ${message(e)}`, true),
    );
  };
  doc.addEventListener("click", onClick, true);
  return () => doc.removeEventListener("click", onClick, true);
};

const CHAT_DIALOGS: Record<string, ChatDialog> = {
  [TAG_PAGE]: bindChatTags,
  "messages/chat/state-price": bindPrice,
  "messages/chat/state-schedule": bindSchedule,
  [CHAT_VAULT]: bindVault,
  "messages/chat/state-header-menu": bindHeaderMenu,
};
/** A chat page (messages/chat and its state-* pages) or New message (and its state-* pages): its mirror path, else "". */
const pageOf = (src: string) => /^\/of-mirror\/pages\/(messages\/(?:chat|send)(?:\/state-[^/]+)?)\.html$/.exec(src)?.[1] ?? "";

/** The Messages tab's composers: bind on every frame load (writes only with a single Creator). */
export function useOfChat(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const qc = useQueryClient();
  const params = useSearchParams();
  const chat = params.get("chat");
  const vaultType = params.get("type");
  const vaultList = params.get("list");
  // The vault dialog's folder search and media sort (OF's ?slist=, ?field=, ?sort=), as New post's.
  const vaultSlist = params.get("slist");
  const vaultField = params.get("field");
  const vaultSort = params.get("sort");
  const page = pageOf(src);
  const isChat = page.startsWith("messages/chat");
  // The same queries (keys and paths) as ofMirrorData's, so the cache is shared.
  const detail = useQuery(mirrorQuery<OFChatItem>(accountId, chat && chatPath(chat), isChat));
  const mass = page.startsWith("messages/send");
  const massView = mass ? massViewOf(params.get("list")) : undefined;
  const massTo = mass ? params.get("to") : null;
  const lists = useQuery(mirrorQuery(accountId, USER_LISTS, mass));
  const listRows = rowsOf<UserList>(lists.data);
  // The Users tab: the Creator's recent chats' fans (OF's Users tab lists its recent chats' users too).
  const chats = useQuery(mirrorQuery(accountId, MASS_FANS, massView === "users"));
  // /chats sends each partner bare (its id): named from /users/list, as the chat list's rows are (OF resolves 20 ids a read).
  const fanIds = useMemo(() => [...new Set((rowsOf<OFChatItem>(chats.data) ?? []).flatMap((c) => (c?.withUser ? [String(c.withUser.id)] : [])))].sort(), [chats.data]);
  const partners = useQueries({
    queries: Array.from({ length: Math.ceil(fanIds.length / USERS_LIST_MAX) }, (_, i) => mirrorQuery(accountId, usersListPath(fanIds.slice(i * USERS_LIST_MAX, (i + 1) * USERS_LIST_MAX)), massView === "users")),
  });
  const partnersPending = partners.some((p) => p.isPending);
  const partnersKey = partners.map((p) => p.dataUpdatedAt).join();
  const fans = useMemo(() => {
    const items = rowsOf<OFChatItem>(chats.data);
    if (!items || partnersPending) return undefined; // "Loading fans…", never bare ids
    const byId = Object.assign({}, ...partners.map((p) => (p.data && typeof p.data === "object" && !Array.isArray(p.data) ? p.data : {})));
    return withChatUsers(items.filter((c) => c?.withUser), byId).map((c) => ({ id: c.withUser.id, name: nameOf(c.withUser), sub: `@${handleOf(c.withUser)}` }));
    // partnersKey stands for `partners` (a new array every render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chats.data, partnersPending, partnersKey]);
  const rowsError = massView === "users" ? chats.error : lists.error;
  const with_ = (detail.data as OFChatItem | undefined)?.withUser;
  const fanName = with_ ? nameOf(with_) : undefined;
  const muted = (detail.data as OFChatItem | undefined)?.isMutedNotifications;
  const tipsEnabled = (with_ as { tipsEnabled?: boolean } | undefined)?.tipsEnabled;
  const zone = useAgencyZone();
  // The tag dialog's rows, for its view (fetched there only), as New post's.
  const tagPage = page === TAG_PAGE || page === MASS_TAG;
  const tagView = tagViewOf(tagPage ? params : new URLSearchParams());
  const tagKey = JSON.stringify(tagView);
  const tags = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagView), tagPage));
  const tagItems = accountId && tagPage ? (tags.data?.items ?? rowsOf<TaggedFriendUser>(tags.data)) : undefined;

  // A list page's Send message (`?to=<list>`): New message opens with that list ticked; the URL then drops it, so
  // unticking it sticks. Before the bind below, which reads the draft.
  useEffect(() => {
    if (!massTo || !accountId) return;
    tickMassList(window.sessionStorage, accountId, massTo);
    router.replace(MASS_SEND);
  }, [massTo, accountId, router]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    // A chat write's refresh, and the thread (Messages Pro's useChatMessages cache).
    const refresh = () => Promise.all([afterChatWrite(qc, accountId), qc.invalidateQueries({ queryKey: ["messages", accountId] })]);
    const enc = chat ? encodeURIComponent(chat) : "";
    const handlers: ChatHandlers | null = accountId
      ? {
          send: (path, body) => relay.post(path, body, { accountId }).then((r) => (refresh(), r)),
          put: (path, body) => relay.put(path, body, { accountId }).then((r) => (refresh(), r)),
          upload: (file) => relay.uploadFile<VaultUploadResp>("/api/of/v2/upload", file, "file", { accountId }),
          gifs: (query) => (query ? gifSearch(query, 24, 0, { accountId }) : gifTrending(24, 0, { accountId })).then((r) => r.data ?? []),
          toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
          inviteGuest: (name) => relay.post("/api/of/v2/guests", { name }, { accountId }),
          // The chat's own state is set from the answer (a refetch right after can still read OF's old state); the lists are refetched.
          mute: (on) =>
            (on ? relay.post(`/api/of/v2/chats/${enc}/mute`, undefined, { accountId }) : relay.delete(`/api/of/v2/chats/${enc}/mute`, { accountId })).then((r) => {
              qc.setQueryData<OFChatItem>(mirrorQuery(accountId, chatPath(chat!), true).queryKey, (d) => (d ? { ...d, isMutedNotifications: on } : d));
              void qc.invalidateQueries({ queryKey: ["chats"] });
              return r;
            }),
          hide: () => relay.post(`/api/of/v2/chats/${enc}/hide`, undefined, { accountId }).then((r) => (refresh(), r)),
          confirm: (text) => window.confirm(text),
          navigate: (href) => router.push(href),
        }
      : null;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      if (!doc?.body) return void (unbind = undefined);
      const ctx: ChatContext = {
        handlers,
        storage: window.sessionStorage,
        accountId,
        chat,
        fan: fanName !== undefined || muted !== undefined ? { name: fanName ?? "", muted, tipsEnabled } : undefined,
        tagItems,
        tagView: JSON.parse(tagKey) as TagView,
        lists: accountId ? listRows : undefined,
        listsError: rowsError ? message(rowsError) : undefined,
        massView,
        fans: accountId ? fans : undefined,
        vaultView: viewOf({ get: (k) => ({ type: vaultType, list: vaultList, slist: vaultSlist, field: vaultField, sort: vaultSort })[k] ?? null }),
        zone,
      };
      unbind = mass ? bindMass(doc, ctx, page) : bindChat(doc, page, ctx);
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, page, mass, accountId, chat, fanName, muted, tipsEnabled, listRows, rowsError, massView, fans, vaultType, vaultList, vaultSlist, vaultField, vaultSort, qc, router, zone, tagItems, tagKey]);
}
