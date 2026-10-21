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
 * - Scripts (OfChatSidePanel, beside the chat): a picked script or saved reply replaces the draft's text, media, free
 *   previews, price, locked text, tags and GIF (applyScript), as Messages Pro's composer applies one.
 * - Header menu (state-header-menu) and the header's bell: Hide chat (POST …/hide, then the chat list) and Mute / Unmute
 *   notifications (POST / DELETE …/mute, labelled from the chat's real state). The menu's other items stay inert links.
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
 * Its composer's tools are a chat's (bindTools), on the Mass draft: Add media, Record voice and video and drops
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
 * All models: the Messages pages show the first model and act as it (standInModel). With no model at all: Send, Save, Next,
 * a tile, a list row and the menu items send nothing and show "Select a model to save changes" (a checkbox flips back); no
 * draft is kept.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { gifSearch, gifTrending, relay, type GiphyItem, type OFChatItem, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultUploadResp } from "@/lib/relay";
import { chatPath, fill, handleOf, make, mirrorQuery, nameOf, usersListPath, withChatUsers, restore, rowsOf, setAttr, setText, stamp, toggleTile, USER_LISTS, type UserList } from "@/lib/ofMirrorData";
import { bindAddMedia, bindTags, bindVaultSearch, bindVaultTools, collectSchedule, mediaTaker, renderCalendar, tagHref, tagsRoute, tagViewOf, type TagView } from "@/lib/ofMirrorPost";
import { bindComposer, GIF_ALONE, isMobile } from "@/lib/ofMirrorComposer";
import { hasFormatting, ofHtml, setOfHtml } from "@/lib/ofMirrorFormat";
import { CHAT_VAULT, MASS_VAULT } from "@/lib/ofMirrorRow";
import { TYPES, vaultHref, viewOf, type VaultView } from "@/lib/ofMirrorVault";
import { dateTimeFields, GREY, localIso, message, minuteAhead, note, NOTE_STYLE, openModal, schedulePill, SELECT_MODEL, textOf, TOO_SOON } from "@/lib/ofMirrorWrites";
import { fromWallClock, useAgencyZone, wallClock } from "@/lib/ofMirrorFeeds";
import { MIN_PRICE, PRICE_NOTE } from "@/lib/sendGuards";

/** The Chat draft (sessionStorage JSON): thumbs[i] is the picture of media_files[i] (vault ids, in click order). */
export interface ChatDraft {
  text: string;
  /** PPV price in dollars; absent: free. */
  price?: number;
  /** Local ISO with offset (localIso), at least a minute ahead when sent. */
  scheduled_date?: string;
  /** Vault ids (picked in the vault dialog) and Add media's upload claims (the Relay's `send_with`), in order. */
  media_files: Array<number | Record<string, unknown>>;
  thumbs: string[];
  /** A message's ⋮ Reply (ofMirrorMessageMenu): the message answered (OF's replyToMessageId) and its text for the line. */
  reply_to?: string;
  reply_text?: string;
  /** The editor's text as OF's markup (ofMirrorFormat), while it holds any formatting; Send sends it as the text. */
  html?: string;
  /** Add GIF's pick: Giphy's id (OF's `giphyId`) and the picture shown under the editor. */
  giphy_id?: string;
  giphy_thumb?: string;
  /** Tag other creators' picks, in click order: a creator ("user"), a guest, or a release form ("link", "document"). */
  tags?: ChatTag[];
  /** How many of media_files are voice notes (OF: one per message; GIF stays possible beside them). */
  audio?: number;
  /** A picked script's (applyScript) vault ids sent unlocked and its locked text, both only with a price. */
  previews?: number[];
  locked_text?: boolean;
}

/** A tag dialog pick: its row's id and type (OF's release-form entity type) and the name the line shows. */
export interface ChatTag {
  id: number;
  type: string;
  name: string;
}

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

export const EMPTY_MESSAGE = "Write a message or add media";
export const NO_CHAT = "Open a chat from the list to send";
export const NO_LISTS = "Pick at least one list";
/** An edited queued message keeps a date or Save for later (without one it would go out at once: that is Message now). */
export const NO_DATE = "Pick a date or Save for Later";
export const UPLOADING = "Wait for the upload to finish";
export const NOT_LOADED = "This chat has not loaded yet";
/** The Relay's scheduled-message body has no GIF and no guest or release-form tags. */
export const NO_SCHEDULED_GIF = "A scheduled message can't carry a GIF";
export const NO_SCHEDULED_FORMS = "A scheduled message can only tag creators";
/** The Relay's mass body tags creators only (`tagged_users`): no guest or release-form field. */
export const NO_MASS_FORMS = "A mass message can only tag creators";
/** The Relay's edit body (PUT …/queue/{id}) has no GIF. */
export const NO_EDIT_GIF = "An edited message can't carry a GIF";
const TAG_PAGE = "messages/chat/state-tag-people";
const MASS_TAG = "messages/send/state-tag-people";
/** A guest's and a release form's tag types (OF's rfGuest, rfPartner); any other is a creator (rfTag). */
const FORM_TAGS = ["guest", "link", "document"];
const CHAT_PAGE = "/of-manager/messages/chat";
const MESSAGES = "/of-manager/messages";

const EDITOR = "[contenteditable][aria-label='Textbox field']";
const SEND = "button[at-attr='send_btn']";
const MUTE_BTN = "button[at-attr='mute_chat']";
const PRICE_INPUT = ".modal.show input[at-attr='input']";
const PRICE_SAVE = ".modal.show .modal-footer button";
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
const VAULT_TABS = ".modal.show .b-tabs__nav__link";
const MENU_ITEM = ".of-state-menu .v-list-item";
const MASS_ROW = ".b-chats__scroller label.b-rows-lists__item";
/** The schedule dialog (vue-datetime), as on New post. */
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ISO = /^\d{4}-\d{2}-\d{2}T/;
const SUMMARY = "oi-chat-summary";
/** New message's "N Selected ⊗" chip over the search (OF's filter counter) and its search field. */
const SELECTED = "oi-mass-selected";
const MASS_SEARCH = ".b-search-users-form input";
/** The Users tab's fans: the Creator's recent chats (the Relay's GET /chats, OF's order). */
const MASS_FANS = "/api/of/v2/chats?limit=50";
/** The most ids OF's /users/list resolves in one read (more are dropped). */
const USERS_LIST_MAX = 20;

/** New message's left tabs (OF's /my/chats/send, ?list=exclude, ?list=users). */
export type MassView = "send" | "exclude" | "users";
export const massViewOf = (list: string | null): MassView => (list === "exclude" || list === "users" ? list : "send");
const MASS_TABS: Array<[MassView, string, string]> = [
  ["send", "Send to", "/of-manager/messages/send"],
  ["exclude", "Exclude", "/of-manager/messages/send?list=exclude"],
  ["users", "Users", "/of-manager/messages/send?list=users"],
];
/** OF's right-hand title once anything is picked (the captured page's "Select users to send them a message" before). */
export const MASS_PICKED_TITLE = "New message to selected list";

export const chatDraftKey = (accountId: string, chat: string) => `oi:chat:${accountId}:${chat}`;
export const massDraftKey = (accountId: string) => `oi:mass:${accountId}`;

function load<T>(storage: Storage, key: string, fresh: T): T {
  try {
    const raw = storage.getItem(key);
    return raw ? { ...fresh, ...(JSON.parse(raw) as Partial<T>) } : fresh;
  } catch {
    return fresh;
  }
}
export const loadChatDraft = (storage: Storage, accountId: string, chat: string): ChatDraft =>
  load<ChatDraft>(storage, chatDraftKey(accountId, chat), { text: "", media_files: [], thumbs: [] });
export const loadMassDraft = (storage: Storage, accountId: string): MassDraft => load<MassDraft>(storage, massDraftKey(accountId), { text: "", user_lists: [] });

/**
 * A composer's vault dialog's ticked tiles (OF's "N / 40 Selected"), kept over its tabs and folders (each its own page)
 * and attached only by its Add; Close, the backdrop or any other way back to the composer drops them (bindChat, bindMass).
 */
export interface VaultPick {
  ids: number[];
  thumbs: string[];
}
/** OF's most media one message takes: its vault dialog's "N / 40 Selected". */
export const VAULT_PICK_MAX = 40;
export const vaultPickKey = (accountId: string, page: string, chat?: string | null) => `oi:vault-pick:${accountId}:${page}:${chat ?? ""}`;
export const loadVaultPick = (storage: Storage, key: string): VaultPick => load<VaultPick>(storage, key, { ids: [], thumbs: [] });

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

/** The price field's value in dollars: "" is free (0), else a number of at least MIN_PRICE (a leading "$" allowed); null otherwise. */
export function readPrice(value: string): number | null {
  const s = value.trim().replace(/^\$\s*/, "");
  if (!s) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(s)) return null;
  const n = Number(s);
  return n === 0 || n >= MIN_PRICE ? n : null;
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

/**
 * The mass message body for `text` and the draft (its lists, kept recipients, media, price, tagged creators, GIF and date
 * or Save for later), or the validation note. An edit needs a date or Save for later (NO_DATE) and carries no GIF.
 */
export function collectMass(text: string, draft: MassDraft, now: Date = new Date()): MassMessageBody | string {
  const t = text.trim();
  const media = draft.media_files ?? [];
  const ids = draft.user_ids ?? [];
  const tags = draft.tags ?? [];
  const gif = draft.giphy_id;
  if (!t && !media.length && !gif) return EMPTY_MESSAGE;
  if (!draft.user_lists.length && !ids.length) return NO_LISTS;
  if (tags.some((x) => FORM_TAGS.includes(x.type))) return NO_MASS_FORMS;
  // OF's rule, as a chat's: a GIF goes with no media but a voice note, no price and no tags.
  if (gif && (media.length > (draft.audio ?? 0) || tags.length || draft.price)) return GIF_ALONE;
  if (gif && draft.edit_id) return NO_EDIT_GIF;
  const body: MassMessageBody = { text: t, user_lists: [...draft.user_lists] };
  if (ids.length) body.user_ids = [...ids];
  if (draft.excluded_user_lists?.length) body.excluded_user_lists = [...draft.excluded_user_lists];
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

export interface ChatHandlers {
  /** POST `path` with `body` for the selected Creator. */
  send(path: string, body: object): Promise<unknown>;
  /** PUT `path` with `body` for the selected Creator (an edited queued message). */
  put?(path: string, body: object): Promise<unknown>;
  /** POST /api/of/v2/upload (multipart, part `file`) for the selected Creator. */
  upload(file: File): Promise<VaultUploadResp>;
  /** Giphy's trending GIFs ("") or a search, through the Relay's OF Giphy proxy. */
  gifs?(query: string): Promise<GiphyItem[]>;
  /** The tag dialog's row More (PATCH /release-forms/toggle-show) and Invite new user (POST /guests). */
  toggleTag?(body: { entity_id: number; entity_type: string }): Promise<unknown>;
  inviteGuest?(name: string): Promise<unknown>;
  mute(on: boolean): Promise<unknown>;
  hide(): Promise<unknown>;
  confirm(text: string): boolean;
  navigate(href: string): void;
}

/** `handlers` null: All-Creators scope. `storage` or `accountId` null: no draft is kept. */
export interface ChatContext {
  handlers: ChatHandlers | null;
  storage: Storage | null;
  accountId: string | null;
  /** ?chat=: the open chat's fan id (null: the example chat). */
  chat: string | null;
  /** The open chat's partner name, mute state and whether they take tips, when the Relay has sent them. */
  fan?: { name: string; muted?: boolean; tipsEnabled?: boolean };
  /** The tag dialog's rows (the Relay's list; undefined while loading, after a failure, or All-Creators) and view. */
  tagItems?: TaggedFriendUser[];
  tagView?: TagView;
  /** A phone or tablet (OF hides Record video there); default: the browser's user agent. */
  mobile?: boolean;
  /** New message: the Creator's user lists (undefined while loading, after a failure, or All-Creators). */
  lists?: UserList[];
  /** New message: why the user lists could not be read (the Relay's text), else undefined. */
  listsError?: string;
  /** New message's left tab, OF's own ?list= (`exclude`, `users`); absent: Send to. */
  massView?: MassView;
  /** New message's Users tab: the Creator's recent chats' fans (undefined while loading or All-Creators). */
  fans?: UserList[];
  /** The vault dialog's view (its ?list= folder and ?type= tab); absent: all media. */
  vaultView?: Partial<VaultView>;
  /** The Agency's time zone (the top bar's): New message's schedule dialog and line show its wall clock. */
  zone?: string;
}

/** Add media's uploads in flight: they outlive a bind (a State page round trip loads a new frame document). */
const flight: { count: number; refresh?: () => void } = { count: 0 };

/** OF's editor text into `editor`, one <p> per line (an empty line keeps OF's <br>). */
function setEditor(doc: Document, editor: HTMLElement, text: string) {
  editor.replaceChildren(
    ...text.split("\n").map((line) => {
      const p = doc.createElement("p");
      p.append(line || doc.createElement("br"));
      return p;
    }),
  );
}

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
      ...(price ? [`Price: $${price}`] : []),
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
    if (body.price > 0 && !h.confirm(`Send this message to ${ctx.fan?.name || "this fan"} for $${body.price}?`)) return;
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

/** What a composer's tools work on: its draft (a chat's, or New message's seen as one) and who may write. */
interface ToolsOf {
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  /** Redraw the line under the editor and Send (an upload started or ended). */
  refresh(): void;
  ready(anchor: Element): ChatHandlers | null;
  /** The handlers a tool writes with (an upload), else null and `none` is the note. */
  writer: ChatHandlers | null;
  none: string;
  accountId: string | null;
  /** The draft a recording belongs to (ofMirrorComposer's key). */
  key: string;
  tipsEnabled?: boolean;
  mobile?: boolean;
}

/**
 * A composer's Add media (New post's upload), its recordings and drops (the same upload) and ofMirrorComposer's tools:
 * a chat's and New message's alike. Returns the composer (its `sync` re-applies OF's rules) and an unbind.
 */
function bindTools(doc: Document, editor: HTMLElement, send: HTMLButtonElement, t: ToolsOf): { composer: ReturnType<typeof bindComposer>; unbind(): void } {
  const { draftOf, update, refresh } = t;
  flight.refresh = refresh;
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };
  const media = { handlers: t.writer, accountId: t.accountId };
  // Every attached audio file (a recording, a drop, an Add media pick) is a voice note: OF allows one, and a GIF beside it.
  const audioDone = (file: File) => {
    if (/^audio\//i.test(file.type)) update({ audio: (draftOf().audio ?? 0) + 1 });
  };
  const unbindAddMedia = bindAddMedia(doc, media, draftOf, update, uploading, t.none, undefined, audioDone);
  // A recording or dropped files: Add media's upload. With a GIF set only a voice note may join it (OF's rule).
  const taker = mediaTaker(doc, send, media, draftOf, update, uploading, audioDone);
  const take = (files: File[]) => {
    const gif = !!draftOf().giphy_id;
    const ok = gif ? files.filter((f) => /^audio\//i.test(f.type)) : files;
    if (ok.length < files.length) note(doc, send, GIF_ALONE, true);
    if (ok.length) taker(ok);
  };
  const composer = bindComposer(doc, {
    editor,
    draftOf,
    update,
    ready: t.ready,
    blocked: () => (t.writer ? null : t.none),
    take,
    key: t.key,
    tipsEnabled: t.tipsEnabled,
    mobile: t.mobile ?? isMobile(doc.defaultView?.navigator.userAgent ?? ""),
  });
  return {
    composer,
    unbind: () => {
      if (flight.refresh === refresh) flight.refresh = undefined;
      unbindAddMedia();
      composer.unbind();
    },
  };
}

interface DialogTools {
  /** The dialog's page (messages/chat/state-* or messages/send/state-*). */
  page: string;
  draftOf(): ChatDraft;
  update(patch: Partial<ChatDraft>): void;
  /** The composer's page (its dialogs return there). */
  back: string;
  ready(anchor: Element): ChatHandlers | null;
  toggleMute(anchor: Element, then?: string): void;
  /** The handlers when a pick may be kept (a chat open, or New message with a model), else null. */
  writer: ChatHandlers | null;
  /** `href` (another view of the dialog) with the composer's own query (a chat's ?chat=). */
  stay(href: string): string;
}
type ChatDialog = (doc: Document, ctx: ChatContext, tools: DialogTools) => () => void;

/** Message price: the field starts at the draft's price; Save is enabled while the value is valid and keeps it. */
const bindPrice: ChatDialog = (doc, _ctx, { draftOf, update, back, ready }) => {
  const input = doc.querySelector<HTMLInputElement>(PRICE_INPUT);
  const save = doc.querySelector<HTMLButtonElement>(PRICE_SAVE);
  if (!input || !save) return () => {};
  for (const el of [input, save]) el.setAttribute("data-oi-wired", "");
  const price = draftOf().price;
  if (price) input.value = String(price);
  const sync = () => (save.disabled = readPrice(input.value) === null);
  sync();
  const onInput = (ev: Event) => {
    if (ev.target === input) sync();
  };
  const onClick = (ev: MouseEvent) => {
    if (!(ev.target as Element | null)?.closest?.(PRICE_SAVE)) return;
    ev.preventDefault();
    const h = ready(save);
    if (!h) return;
    const p = readPrice(input.value);
    if (p === null) return note(doc, save, PRICE_NOTE, true);
    update({ price: p || undefined });
    h.navigate(back);
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
};

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

/** OF's bar over a vault dialog's grid while tiles are ticked (its scoped CSS is the page's): Clear, the count and Add. */
const VAULT_BAR = "[data-oi-vault-bar]";
const VAULT_ADD = "[data-oi-vault-add]";
const VAULT_CLEAR = "[data-oi-vault-clear]";
function vaultBar(doc: Document, count: number) {
  const grid = doc.querySelector(".modal.show .b-photos")?.closest(".g-sides-gaps") ?? null;
  let bar = doc.querySelector<HTMLElement>(VAULT_BAR);
  if (!count || !grid) return bar?.remove();
  if (!bar) {
    const v = 'data-v-1b24e6ba=""';
    bar = doc.createElement("div");
    bar.setAttribute("data-v-1b24e6ba", "");
    bar.setAttribute("data-oi-vault-bar", "");
    bar.className = "b-placeholder-item-selected m-absolute-position ml-0 mr-0";
    bar.innerHTML =
      `<div ${v} class="b-wrapper-selected"><div ${v} class="b-row-selected"><div ${v} class="b-row-selected__body">` +
      `<button ${v} type="button" at-attr="unselect" aria-label="Clear" data-oi-vault-clear="" data-oi-wired="" class="g-btn m-with-round-hover m-light m-icon m-icon-only m-white m-sm-size">` +
      `<span ${v} class="g-btn m-rounded m-reset-width m-btn-remove m-sm-icon-size m-light m-colored-btn m-mall-auto"><svg class="g-icon" aria-hidden="true"><use href="#icon-close" xlink:href="#icon-close"></use></svg></span></button>` +
      `<div ${v} class="b-row-selected__text g-text-ellipsis"></div></div>` +
      `<div ${v} class="b-row-selected__controls"><button ${v} type="button" data-oi-vault-add="" data-oi-wired="" class="g-btn m-reset-width m-rounded m-sm"> Add </button></div></div></div>`;
    grid.append(bar);
  }
  bar.querySelector(".b-row-selected__text")!.textContent = ` ${count} / ${VAULT_PICK_MAX} Selected `;
}

/**
 * Add media from vault, as OF's: a real tile (ofMirrorData's `data-oi-media`) only ticks or unticks it (OF's bar shows the
 * count), Add attaches the ticked vault ids and pictures and goes back, and Close, the backdrop or the bar's Clear attach
 * nothing; a media type tab shows the view's type and a click opens the dialog on that type (the folder, chat and ticks
 * kept); Search media and the folder Search and Sort and media Sort are New post's.
 */
const bindVault: ChatDialog = (doc, ctx, { page, draftOf, update, back, ready, writer, stay }) => {
  const view = ctx.vaultView ?? {};
  const tabs = [...doc.querySelectorAll<HTMLElement>(VAULT_TABS)];
  tabs.forEach((t, i) => {
    const on = (TYPES[i] ?? null) === (view.type ?? null);
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    t.setAttribute("data-oi-wired", "");
  });
  const store = ctx.storage && ctx.accountId ? { storage: ctx.storage, key: vaultPickKey(ctx.accountId, page, ctx.chat) } : null;
  const pickOf = (): VaultPick => (store ? loadVaultPick(store.storage, store.key) : { ids: [], thumbs: [] });
  const keep = (pick: VaultPick) => {
    if (store) store.storage.setItem(store.key, JSON.stringify(pick));
    vaultBar(doc, pick.ids.length);
  };
  vaultBar(doc, pickOf().ids.length);
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    const tab = target?.closest?.(VAULT_TABS);
    if (tab) {
      ev.preventDefault();
      const type = TYPES[tabs.indexOf(tab as HTMLElement)] ?? null;
      const h = type === (view.type ?? null) ? null : ready(tab);
      if (!h) return;
      return h.navigate(stay(vaultHref({ list: view.list, type }, `/of-manager/${page}`)));
    }
    const add = target?.closest?.(VAULT_ADD);
    if (add) {
      ev.preventDefault();
      const h = ready(add);
      if (!h) return;
      const { ids, thumbs } = pickOf();
      const d = draftOf();
      const fresh = ids.map((id, i) => [id, thumbs[i] ?? ""] as const).filter(([id]) => !d.media_files.includes(id));
      update({ media_files: [...d.media_files, ...fresh.map(([id]) => id)], thumbs: [...d.thumbs, ...fresh.map(([, t]) => t)] });
      keep({ ids: [], thumbs: [] });
      return h.navigate(back);
    }
    if (target?.closest?.(VAULT_CLEAR)) {
      ev.preventDefault();
      doc.querySelectorAll(`${VAULT_TILE}.selected`).forEach((t) => toggleTile(t, false));
      return keep({ ids: [], thumbs: [] });
    }
    const tile = target?.closest?.(VAULT_TILE);
    if (!tile) return;
    const footer = doc.querySelector(".modal-footer a") ?? tile; // a note in the grid would take a tile's place
    if (!ready(footer)) return;
    const id = Number(tile.getAttribute("data-oi-media"));
    if (!id) return;
    const { ids, thumbs } = pickOf();
    const at = ids.indexOf(id);
    if (at < 0 && draftOf().giphy_id) return note(doc, footer, GIF_ALONE, true); // a GIF goes without vault media
    if (at < 0 && ids.length >= VAULT_PICK_MAX) return;
    if (at < 0) keep({ ids: [...ids, id], thumbs: [...thumbs, tile.querySelector(".b-photos__item__img")?.getAttribute("src") ?? ""] });
    else keep({ ids: ids.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
    toggleTile(tile, at < 0);
  };
  doc.addEventListener("click", onClick);
  const unbindSearch = bindVaultSearch(doc);
  const unbindTools = bindVaultTools(doc, { vaultView: view, handlers: writer }, page, stay);
  return () => {
    doc.removeEventListener("click", onClick);
    unbindSearch();
    unbindTools();
  };
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

/**
 * Tag other creators (state-tag-people): New post's tag dialog (its rows, search, sort, tabs, row More and Invite new
 * user), its picks the draft's `tags`; its views keep the chat.
 */
const bindChatTags: ChatDialog = (doc, ctx, { page, draftOf, update, writer: h, stay }) => {
  const picks = () => draftOf().tags ?? [];
  return bindTags(
    doc,
    { handlers: h && { navigate: h.navigate, toggleTag: h.toggleTag, inviteGuest: h.inviteGuest }, tagItems: ctx.tagItems, tagView: ctx.tagView, storage: null, accountId: null },
    () => {},
    page,
    {
      ids: () => picks().map((t) => t.id),
      toggle: (pick, on) => {
        const others = picks().filter((t) => t.id !== pick.id || t.type !== pick.type);
        update({ tags: on ? [...others, pick] : others });
      },
      href: (view) => stay(tagHref(view, page)),
    },
  );
};

const CHAT_DIALOGS: Record<string, ChatDialog> = {
  [TAG_PAGE]: bindChatTags,
  "messages/chat/state-price": bindPrice,
  "messages/chat/state-schedule": bindSchedule,
  [CHAT_VAULT]: bindVault,
  "messages/chat/state-header-menu": bindHeaderMenu,
};
/** New message's dialogs: a chat's (its schedule is bindMass' own dialog). */
const MASS_DIALOGS: Record<string, ChatDialog> = {
  [MASS_TAG]: bindChatTags,
  "messages/send/state-price": bindPrice,
  [MASS_VAULT]: bindVault,
};
const MASS_PAGE = "/of-manager/messages/send";

const users = (n: number) => `${n} ${n === 1 ? "user" : "users"}`;
/** OF's checkbox row: ticked, it drops `m-not-active` (its CSS shows the tick only then; `:checked` alone shows nothing). */
const markRow = (row: Element, on: boolean) => row.classList.toggle("m-not-active", !on);

/**
 * New message's Send to rows for `lists`: the example (the generator's hidden one) cloned per list (`data-oi-list="<id>"`, its
 * name and user count, or its `sub` line, no avatars, no link, checked when picked). As OF's, a ticked row drops
 * `m-not-active` (OF's tick shows only then) and a `disabled` one (picked on the other tab) can't be ticked.
 * ofMirrorData's restore (the unbind) undoes it. `where`: another checkbox list's rows and "Nothing found" (the chat
 * list's folders dialog), default New message's.
 */
export function applyListRows(doc: Document, lists: Array<UserList & { sub?: string }>, picked: string[], where: { rows: string; empty: string } = { rows: MASS_ROW, empty: ".b-chats__scroller [data-oi-empty]" }, disabled: string[] = []): void {
  const examples = [...doc.querySelectorAll<HTMLElement>(`${where.rows}:not([data-oi-list])`)];
  if (!examples.length) return;
  const rows = lists.map((l) => {
    const row = make(examples[0]);
    row.style.removeProperty("display"); // the generator's hidden template
    row.setAttribute("data-oi-list", String(l.id));
    row.setAttribute("data-oi-wired", "");
    const box = row.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (box) {
      box.checked = picked.includes(String(l.id));
      box.disabled = disabled.includes(String(l.id));
      markRow(row, box.checked);
      box.addEventListener("change", () => markRow(row, box.checked));
    }
    // A link inside the label would open the list instead of ticking the row.
    const a = row.querySelector("a.b-rows-lists__item__text");
    if (a) {
      const div = doc.createElement("div");
      div.className = a.className;
      div.append(...a.childNodes);
      a.replaceWith(div);
    }
    const name = row.querySelector(".b-rows-lists__item__name");
    if (name) name.textContent = ` ${l.name ?? ""} `;
    row.querySelector(".b-media-set")?.remove();
    const count = row.querySelector(".b-content-inside-thumbs__item");
    if (count) count.textContent = ` ${l.sub ?? users(l.usersCount ?? 0)} `;
    return row;
  });
  // OF's "Nothing found" (the generator's) only for no list.
  const empty = lists.length ? [...doc.querySelectorAll<HTMLElement>(where.empty)] : [];
  fill(doc, [...examples, ...empty], rows);
}

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
      ...(d.user_ids?.length ? [`${users(d.user_ids.length)} picked`] : []),
      ...(d.excluded_user_lists?.length ? [`${d.excluded_user_lists.length} excluded ${d.excluded_user_lists.length === 1 ? "list" : "lists"}`] : []),
      ...(d.media_files?.length ? [`${d.media_files.length} media`] : []),
      ...(d.giphy_id ? ["GIF"] : []),
      ...(d.tags?.length ? [`Tagged: ${d.tags.map((t) => t.name || `#${t.id}`).join(", ")}`] : []),
      ...(d.price ? [`Price: $${d.price}`] : []),
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
      ...(body.user_lists.length ? [`${users(count)} on ${names || `${body.user_lists.length} lists`}`] : []),
      ...(body.user_ids?.length ? [`${users(body.user_ids.length)} picked`] : []),
    ].join(" and ") + (body.price ? ` for $${body.price}` : "");
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

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !page) return;
    let unbind: (() => void) | undefined;
    // The mirror's reads, and the chat list and thread (Messages Pro's useChatList / useChatMessages caches).
    const refresh = () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] }),
        qc.invalidateQueries({ queryKey: ["chats"] }),
        qc.invalidateQueries({ queryKey: ["messages", accountId] }),
      ]);
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
