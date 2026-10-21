"use client";

/**
 * Write-through for the New post composer (new-post and every new-post/state-* Mirror page).
 * Text or media enables Post, as OF's (a disabled Post's tooltip says why); the text is the Post draft, kept per Creator in
 * sessionStorage (`oi:new-post:<accountId>`) and restored on every new-post page, so a move to a
 * State page and back keeps it. Post sends exactly one POST /api/of/v2/posts with the Known body
 * {text, media_files, price} (the Relay's _CreatePostBody subset, as PostComposer sends it),
 * then clears the draft and stays: the composer empties and OF's toast says "Your post has been published" ("…is
 * scheduled for …", "…has been saved for later"). A failure re-enables Post, shows the Relay's own
 * text in a red note and keeps the draft. "as <model>" by Post names the model it goes to. In All models New post shows
 * the first model (OfMirrorFrame's standInModel), so the composer, its dialogs and Post are that model's; with no model at
 * all, Post sends nothing and shows "Select a model to save changes" and no draft is stored. All wiring is runtime DOM
 * (ADR-0006).
 *
 * Post price (new-post/state-price, OF's ModalPostPrice): the price button shows where OF's does (postPriceLimits: a
 * free page whose users/me allows prices); Save keeps a price within users/me's postMinPrice..postMaxPrice (empty: free)
 * on the draft and Post sends it. A price disables Expiration period and Fundraising target, and either of those the
 * price button, as OF's composer.
 *
 * Home's composer (home/index and its state-schedule, state-tag-people, state-vault, state-poll, state-quiz,
 * state-expiration, state-target and state-format-text pages: New post's dialogs and panels over Home) is the same
 * composer with its own draft (`oi:new-post:home:<accountId>`) and upload flight. It never leaves Home: its dialogs
 * return to Home (a poll's duration to Home's poll panel), and a sent Post clears the composer, refetches the Creator's Mirror data (the new post shows at
 * the top of the feed) and shows the same toast.
 *
 * Schedule (new-post/state-schedule): the captured vue-datetime calendar is re-rendered for the
 * draft's month (or the current month), past days disabled; the time tab takes a typed time. Next
 * stores `posted_at` (local ISO with offset) and returns to the composer, which then shows a
 * "Scheduled for … · Clear" line; Post sends `posted_at`.
 *
 * Tag other creators (new-post/state-tag-people): with a single Creator, the dialog lists the Creator's taggable
 * creators from GET /api/of/v2/posts/tagged-friend-users in OF's own row markup (the examples hidden); a checked row
 * is a Co-tag (`tagged_users`, OF user ids), named in the summary ("Tagged: …") and sent with Post. While the list
 * is loading, after it failed and in All-Creators scope the dialog has no rows (the captured examples never show).
 *
 * Add media from vault (new-post/state-vault): ofMirrorData shows the Creator's vault media, its picked tiles marked from
 * the draft; a tile click picks or unpicks it (its vault id in the draft's `media_files`, its picture in `thumbs`, in click
 * order). An example tile, or any tile in All-Creators scope, sends nothing and gives "Select a model". Its search box hides
 * the real tiles whose date label and AI text (description, tags) lack the query; it never touches the draft. Every new-post
 * page shows the picks as a row of 64px thumbs above the toolbar, and Post sends their ids as `media_files`. The dialog's
 * "Add to story" publishes the one picked vault item as the Creator's Story (POST /api/of/v2/stories: a photo by its full
 * picture, which the Relay re-uploads, anything else by its vault id, as OF's web client does).
 *
 * Add media (every composer page, Single-Creator scope): OF's button opens a hidden picker taking several photos, videos and
 * audio files at once (POST_PICK); each picked file uploads through POST /api/of/v2/upload, one after another in the picked
 * order, and an accepted upload's `send_with` entries are appended to the draft's `media_files` as the Relay returned them,
 * with a thumb from the browser's own copy of the file (a `blob:` URL; an audio file's is OF's grey square). Post stays
 * disabled while any upload is in flight.
 *
 * Add to story (every Mirror page with a story strip; OF's own tile is on home, new-post and their State pages): a click
 * on the tile opens a hidden image or video picker; the picked file is published as the Creator's Story through one multipart
 * POST /api/of/v2/stories/upload (part `file`); the tile is disabled until the upload settles, then "Added to story" shows under the strip (and the Creator's own stories are
 * read again, so Home's strip shows the new one), or a red
 * "Could not add: <message>" note stays; either way the picker is reset so the same file can be picked again. A picked file
 * that is neither image/* nor video/* (an empty type included) sends nothing and shows a red "Could not add: choose an image
 * or a video"; a cancelled picker sends nothing and shows nothing. All-Creators scope: no picker, the select-a-model note.
 *
 * Post extras (each saved on the draft, named in the composer summary, sent with Post; the summary's Clear drops them all):
 * Save for Later (state-schedule) sends `save_for_later` instead of a date; the poll
 * and quiz panels (state-poll, state-quiz) send their typed options (`voting_*`, a quiz's correct row from its radio; "+ Add
 * another option" adds a row, a row's delete removes it while more than two are left); the panel's "Poll · 7 days" piece
 * opens EXPIRATION PERIOD for the poll's length (`voting_due`, OF's 7-day default, No limit none), as OF's composer does;
 * EXPIRATION PERIOD's Save sends `expire_days` (a tab or a typed
 * number up to OF's 30, No limit none); Fundraising target's Save sends `fund_raising_target` (minimum $10); ADD LABELS lists the
 * Creator's own post labels from GET /api/of/v2/labels (not OF's Archive and Private Archive), a checked row is a `label_ids` pick, and NEW LABEL opens a name field
 * whose Save sends POST /api/of/v2/labels {name} and picks the new label. The Relay maps these names to OF's own keys.
 *
 * OF's own tools: the Format text panel (bindFormat: Bold, Italic, Text Color, Clear Formatting, Text Size; the post text is
 * then OF's composer markup, ofMirrorFormat), Record video and Record voice (a "not supported here" popup), the poll and
 * quiz drag handles, the tag dialog's search, Sort, Release form tab, row More and Invite new user, the vault dialog's folder
 * Search and Sort and media Sort, ADD LABELS' Sort and the right column's search (bindFeedSearch: OF's users and posts
 * search, each result a link to its OF Manager page). Sort menus are ofMirrorMenu's.
 */

import { useEffect, useMemo, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { relay, toChoice, type TaggedFriendUser, type TaggedFriendUsersResp, type VaultMedia, type VaultUploadResp } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { avatarOf } from "@/lib/ofMirrorAvatar";
import { fill, linkUser, make, mirrorQuery, own, plain, rowsOf, toggleTile, userHref, VAULT_LISTS, vaultMediaOf } from "@/lib/ofMirrorData";
import { sortOfFolders } from "@/hooks/useVaultCache";
import { HOME_VAULT, homeDraft, VAULT_DIALOG } from "@/lib/ofMirrorRow";
import { ofMeQuery, type OfMe } from "@/lib/ofMirrorIdentity";
import { floatLabel } from "@/lib/ofMirrorSettings";
import { FIELDS, openViewer, TYPES, vaultHref, viewerItem, viewOf, type StoryAuthor, type VaultView, type ViewerItem } from "@/lib/ofMirrorVault";
import { applyFormat, COLORS, hasFormatting, ofHtml, setOfHtml, SIZES, type FormatCommand } from "@/lib/ofMirrorFormat";
import { closeMenu, ORDER_GROUP, showMenu, type MenuGroup } from "@/lib/ofMirrorMenu";
import { GREY, localIso, message, minuteAhead, note, NOTE_STYLE, QUEUE, READ_ONLY, scheduleAt, schedulePill, SELECT_MODEL, textOf, TOO_SOON } from "@/lib/ofMirrorWrites";
import { fromWallClock, storyItems, useAgencyZone, wallClock, type StoryEntry } from "@/lib/ofMirrorFeeds";
import { ofPrice } from "@/lib/ofMirrorPostCard";
import { mirrorPageOfHref, mirrorPageOfPath } from "@/lib/of-mirror-route";

/**
 * The Post draft (sessionStorage JSON). thumbs[i] is the picture of media_files[i] (vault ids are picked in the vault
 * dialog; Add media's uploads add the Relay's `send_with` entries, vault ids or claim dicts).
 */
export interface PostDraft {
  text: string;
  /** The text as OF's composer markup (ofMirrorFormat's ofHtml) while it has formatting; absent: plain `text`. */
  html?: string;
  posted_at?: string;
  /** Save for Later: queued with no date (never alongside posted_at). */
  save_for_later?: boolean;
  tagged_users: number[];
  media_files: Array<number | Record<string, unknown>>;
  thumbs: string[];
  voting?: Voting;
  /** The poll's or quiz's length in days (0: No limit); absent: OF's 7. */
  voting_due?: number;
  /** Set by a poll (1) or quiz (2) panel's duration: the EXPIRATION PERIOD dialog opened next edits `voting_due`. */
  period_for?: 1 | 2;
  expire_days?: number;
  fund_raising_target?: number;
  label_ids?: number[];
  /** The post's price in dollars (POST PRICE dialog); absent: free. */
  price?: number;
  /** The queued post this draft edits (the Queue's Edit post): Post saves it (PUT /api/of/v2/queue/posts/{id}) instead of a new one. */
  edit_id?: string;
}

/** A poll (type 1) or quiz (type 2): its options as typed, blanks kept so each keeps its row, and the quiz's correct row. */
export interface Voting {
  type: 1 | 2;
  options: string[];
  correct?: number;
}

/** POST /api/of/v2/posts: the Relay's _CreatePostBody subset. Absent keys are omitted, never null. */
export interface CreatePostBody {
  text: string;
  media_files: Array<number | Record<string, unknown>>;
  /** 0: free. */
  price: number;
  posted_at?: string;
  save_for_later?: true;
  tagged_users?: number[];
  label_ids?: number[];
  expire_days?: number;
  fund_raising_target?: number;
  voting_type?: 1 | 2;
  voting_options?: string[];
  voting_due?: number;
  voting_correct_index?: number;
}

/** A post label as GET /api/of/v2/labels gives it (OF's `{list, hasMore}`, or a bare array). */
export interface PostLabel {
  id: number;
  name: string;
  postsCount?: number;
}
export type PostLabelsResp = { list?: PostLabel[]; hasMore?: boolean } | PostLabel[];
export const labelsOf = (r: PostLabelsResp): PostLabel[] => (Array.isArray(r) ? r : (r.list ?? []));
/** The labels a post can be given: the Creator's own (numeric ids); OF's Archive and Private Archive are not offered. */
export const postLabelsOf = (r: PostLabelsResp): PostLabel[] => labelsOf(r).filter((l) => Number.isInteger(Number(l.id)));

/** OF's POST PRICE limits in dollars (users/me postMinPrice, postMaxPrice). */
export interface PriceLimits {
  min: number;
  max: number;
}

/**
 * OF's price button on a post (MakeFeedPost isShowPriceBtn: canChangeContentPrice, canEarn and a free page) and its
 * limits; null: no price button (a paid page, say); undefined: users/me not loaded yet (no button either).
 */
export function postPriceLimits(me: OfMe | undefined): PriceLimits | null | undefined {
  if (!me) return undefined;
  if (!me.canChangeContentPrice || !me.canEarn || Number(me.subscribePrice) !== 0) return null;
  const min = Number(me.postMinPrice);
  const max = Number(me.postMaxPrice);
  return min > 0 && max >= min ? { min, max } : null;
}

/**
 * POST /api/of/v2/stories for one vault item, as OF's web client publishes a vault item as a Story: a photo by its full
 * picture (`media_url`; the Relay fetches and re-uploads it, as OF's `addStoryFromVault` does), anything else (or a
 * photo the list does not hold with a full url) by its vault id (`media_files`, OF's `createStoryByFileId`).
 */
export type VaultStoryBody = { media_url: string } | { media_files: number[] };
export function vaultStoryBody(id: number, items: VaultMedia[] | undefined): VaultStoryBody {
  const m = items?.find((v) => Number(v.id) === id);
  const url = m?.type === "photo" ? m.files?.full?.url : undefined;
  return url ? { media_url: url } : { media_files: [id] };
}

const EMPTY_TEXT = "Write something or add media to post";
const UPLOADING = "Wait for the upload to finish";
const FEW_OPTIONS = "Add at least two options";
const ONE_FOR_STORY = "Pick one vault item for the story";
const NO_ANSWER = "Pick the correct answer";
/** Where an immediate post lands, a saved-for-later one, and a dialog's Save or Next. */
/** OF's toast after a post goes through (the scheduled one ends with its moment). */
export const POSTED_TOAST = "Your post has been published";
export const SCHEDULED_TOAST = "Your post is scheduled for";
export const SAVED_TOAST = "Your post has been saved for later";
/** How long OF's toast stays. */
const TOAST_MS = 5_000;
const COMPOSER = "/of-manager/new-post";
/** Where a saved edit goes: the Queue, or its Posts saved for later page. */
const SFL_POSTS = "/of-manager/queue/saved-for-later-posts";
/** The summary's first part while the draft edits a queued post, and the confirm before an edit publishes it. */
export const EDITING = "Editing a scheduled post";
export const EDITING_LATER = "Editing a post saved for later";
export const PUBLISH_EDITED = "This post has no date: publish it now?";
const HOME = "/of-manager/home";
/** OF's composer default poll length in days (its panel shows "7 days"). */
const VOTING_DAYS = 7;
/** OF's longest expiration period and poll length, in days (its period dialog's validator). */
const MAX_DAYS = 30;
/** OF's most poll options. */
const MAX_OPTIONS = 20;
/** The fundraising target's minimum, as the captured dialog states ("Minimum $10 USD"). */
const MIN_TARGET = 10;
/** Every post extra off the draft (the summary's Clear). */
const NO_EXTRAS: Partial<PostDraft> = {
  posted_at: undefined,
  save_for_later: undefined,
  tagged_users: [],
  voting: undefined,
  voting_due: undefined,
  expire_days: undefined,
  fund_raising_target: undefined,
  label_ids: undefined,
  price: undefined,
};
/** OF's composer editor and its Post button (every new-post page has both). */
const EDITOR = "[contenteditable][aria-label='Textbox field']";
const POST = "button[at-attr='submit_post']";
/** The format-text panel (read-only), a dialog's Save (expiration, target) and its fields. */
const FORMAT = ".js-text-editor-toolbar";
const DIALOG_SAVE = ".modal.show .modal-footer button";
const PERIOD = ".modal.show input[name='periodValue']";
const PERIOD_TAB = ".modal.show .b-tabs__nav__link";
const TARGET = ".modal.show input[at-attr='input']";
/** The poll and quiz panels: an option row, its text, its correct-answer switch (quiz), "+ Add another option" and the × that drops the poll. */
const VOTE_ROW = ".b-make-post__voting .vote-input";
const OPTION = "input[at-attr='input']";
const QUIZ_PICK = ".m-quiz-swithcer";
const ADD_OPTION = ".b-make-post__voting .new_vote_add_option";
const DROP_VOTING = ".b-make-post__voting .b-post-piece .b-dropzone__preview__delete";
/** An option row's delete button, and the panel's "Poll · 7 days" piece (a click opens its duration in the period dialog). */
const DELETE_OPTION = ".delete-vote-option";
/** An option row's drag handle (OF's m-drag-btn). */
const DRAG = ".m-drag-btn";
const VOTING_PIECE = ".b-make-post__voting .b-post-piece";
/**
 * The poll and quiz pages, and the EXPIRATION PERIOD dialog's page (also the poll's duration, as OF's composer): State
 * pages of New post and of Home (`/of-manager/<composer>/<state>`, the composer's own).
 */
const VOTING_PAGES = { 1: "state-poll", 2: "state-quiz" } as const;
const PERIOD_PAGE = "state-expiration";
/** `state`'s page under the composer `ctx` posts from (New post's, or Home's). */
const composerPage = (ctx: PostContext, state: string) => `${ctx.composer ?? COMPOSER}/${state}`;
/** The period dialog's title for a poll's or quiz's duration (OF's own strings for these are not in the capture). */
const DURATION_TITLES = { 1: " POLL DURATION ", 2: " QUIZ DURATION " } as const;
/** The captured vue-datetime schedule dialog (new-post/state-schedule). */
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const SAVE_LATER = ".custom-datepicker-button-save-later";
/** The dialog, and its attribute holding the selected day (YYYY-MM-DD): the one copy of the selection. */
const POPUP = ".vdatetime-popup";
const SELECTED = "data-oi-selected";
/** OF's checkbox list row (the tag and labels dialogs). */
export const LIST_ROW = "label.b-rows-lists__item";
/** The tag dialog (new-post/state-tag-people), and the Relay list it shows. */
const TAG_PAGE = "new-post/state-tag-people";
/** Home's own copies of New post's schedule and tag dialogs (its vault dialog is ofMirrorRow's HOME_VAULT). */
const HOME_SCHEDULE = "home/state-schedule";
const HOME_TAGS = "home/state-tag-people";
const TAGS = "/api/of/v2/posts/tagged-friend-users?limit=50&offset=0";
/** The labels dialog (new-post/state-labels), the Relay's post labels, and its NEW LABEL button. */
const LABEL_PAGE = "new-post/state-labels";
const LABELS = "/api/of/v2/labels";
const NEW_LABEL = ".b-rows-lists__modal__add-list-btn";
/** The Relay's Story route. */
const STORIES = "/api/of/v2/stories";
/** The price button (OF's `price_btn`) and its POST PRICE dialog's page; the two tools OF disables while a price is set. */
const PRICE_BTN = "[at-attr='price_btn']";
const PRICE_PAGE = "new-post/state-price";
const NOT_WITH_PRICE = "[aria-label='Expiration period'], [aria-label='Your target']";
/** The Post button's "as <model>" line. */
const POST_AS = "oi-post-as";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const ISO = /^\d{4}-\d{2}-\d{2}T/;

/** "1 day", "7 days" or "No limit" (0), as OF's poll piece and period tabs. */
const daysText = (n: number) => (n ? `${n} ${n === 1 ? "day" : "days"}` : "No limit");
/** "6:30 PM", as OF's time tab. */
const clock = (d: Date) => `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;
/** "Tue, Oct 13, 6:30 PM": the composer summary's moment. */
const when = (d: Date) => `${WEEKDAYS[d.getDay()].slice(0, 3)}, ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}, ${clock(d)}`;
const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export const draftKey = (accountId: string) => `oi:new-post:${accountId}`;

const emptyDraft = (): PostDraft => ({ text: "", tagged_users: [], media_files: [], thumbs: [] });

export function loadDraft(storage: Storage, accountId: string): PostDraft {
  const fresh = emptyDraft();
  try {
    const raw = storage.getItem(draftKey(accountId));
    return raw ? { ...fresh, ...(JSON.parse(raw) as Partial<PostDraft>) } : fresh;
  } catch {
    return fresh;
  }
}

export function saveDraft(storage: Storage, accountId: string, draft: PostDraft): void {
  storage.setItem(draftKey(accountId), JSON.stringify(draft));
}

export function clearDraft(storage: Storage, accountId: string): void {
  storage.removeItem(draftKey(accountId));
}

/** The draft's media after an accepted upload: a new array of `mediaFiles` then the Relay's `sendWith`, in order, nothing skipped or altered. */
export const mergeSendWith = (mediaFiles: PostDraft["media_files"], sendWith: PostDraft["media_files"]): PostDraft["media_files"] => [...mediaFiles, ...sendWith];

/**
 * A poll's or quiz's part of the POST /posts body (blank options dropped, as OF does), or the validation note. `due` is its
 * length in days; 0 (No limit) sends no `voting_due`, as OF's composer.
 */
function collectVoting({ type, options, correct }: Voting, due: number): Partial<CreatePostBody> | string {
  const typed = options.map((o) => o.trim());
  const kept = typed.filter(Boolean);
  if (kept.length < 2) return FEW_OPTIONS;
  const body = { voting_type: type, voting_options: kept, ...(due > 0 ? { voting_due: due } : {}) };
  if (type === 1) return body;
  if (correct === undefined || !typed[correct]) return NO_ANSWER;
  // OF counts the correct answer among the options it keeps
  return { ...body, voting_correct_index: typed.slice(0, correct).filter(Boolean).length };
}

/**
 * The POST /posts body for `text` and `draft`, or the validation note: it needs text or media, as OF's Post, and a schedule
 * must still be at least a minute ahead.
 */
export function collectPost(text: string, draft: PostDraft, now: Date = new Date()): CreatePostBody | string {
  const t = text.trim();
  if (!t && !draft.media_files.length) return EMPTY_TEXT;
  // Formatted text goes as OF's own markup (its composer's getHTML), plain text as it is.
  const body: CreatePostBody = { text: t && draft.html ? draft.html : t, media_files: [...draft.media_files], price: draft.price ?? 0 };
  if (draft.save_for_later) body.save_for_later = true;
  else if (draft.posted_at) {
    if (!minuteAhead(new Date(draft.posted_at), now)) return TOO_SOON;
    body.posted_at = draft.posted_at;
  }
  if (draft.tagged_users.length) body.tagged_users = [...draft.tagged_users];
  if (draft.label_ids?.length) body.label_ids = [...draft.label_ids];
  if (draft.expire_days) body.expire_days = draft.expire_days;
  if (draft.fund_raising_target) body.fund_raising_target = draft.fund_raising_target;
  if (draft.voting) {
    const voting = collectVoting(draft.voting, draft.voting_due ?? VOTING_DAYS);
    if (typeof voting === "string") return voting;
    Object.assign(body, voting);
  }
  return body;
}

/**
 * Rebuild the schedule dialog's day grid for `month` (any day in it) from a captured day cell:
 * Sunday-first leading blanks, days before `now`'s day `--disabled`, `selected` `--selected`.
 * With `selected`, the dialog keeps it (data-oi-selected) and the header date and year and the date tab show it.
 */
export function renderCalendar(doc: Document, month: Date, selected: Date | null, now: Date): void {
  const grid = doc.querySelector(".vdatetime-calendar__month");
  const cell = grid?.querySelector(`.${DAY}`);
  if (!grid || !cell) return;
  const y = month.getFullYear();
  const m = month.getMonth();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const make = (day: number | null) => {
    const c = cell.cloneNode(true) as HTMLElement;
    c.className = DAY;
    const label = c.querySelector("span > span") ?? c;
    label.textContent = day === null ? "" : String(day);
    const date = day === null ? null : new Date(y, m, day);
    c.classList.toggle(`${DAY}--disabled`, !date || date < today);
    c.classList.toggle(`${DAY}--selected`, !!date && !!selected && sameDay(date, selected));
    return c;
  };
  const blanks = new Date(y, m, 1).getDay();
  const count = new Date(y, m + 1, 0).getDate();
  grid.querySelectorAll(`.${DAY}`).forEach((c) => c.remove());
  grid.append(...Array.from({ length: blanks }, () => make(null)), ...Array.from({ length: count }, (_, i) => make(i + 1)));
  const set = (sel: string, text: string) => {
    const el = doc.querySelector(sel);
    if (el) el.textContent = text;
  };
  set(SHOWN, `${MONTHS[m]} ${y}`);
  if (!selected) return;
  doc.querySelector(POPUP)?.setAttribute(SELECTED, localIso(selected).slice(0, 10));
  const name = MONTHS[selected.getMonth()];
  set(".vdatetime-popup__date", `${selected.getDate()} ${name}`);
  set(".vdatetime-popup__year", String(selected.getFullYear()));
  set(".vdatetime-popup__tab.date", `${name.slice(0, 3)} ${selected.getDate()}, ${WEEKDAYS[selected.getDay()].slice(0, 2)}`);
}

/** The shown month ("October 2026") as its first day, or null. */
const shownMonth = (doc: Document): Date | null => {
  const [name, year] = (doc.querySelector(SHOWN)?.textContent ?? "").trim().split(/\s+/);
  const m = MONTHS.indexOf(name);
  return m >= 0 && /^\d{4}$/.test(year ?? "") ? new Date(+year, m, 1) : null;
};

/** The day renderCalendar last selected (the dialog's data-oi-selected), or null. */
const selectedDay = (doc: Document): Date | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(doc.querySelector(POPUP)?.getAttribute(SELECTED) ?? "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
};

/** The schedule dialog's moment (its selected day, else `now`'s day, at the time tab) as local ISO, or the validation note. */
export function collectSchedule(doc: Document, now: Date = new Date(), zone?: string): string {
  // The dialog shows `zone`'s wall clock: the picked day and time are read as that zone's.
  const wallNow = wallClock(now, zone);
  const day = selectedDay(doc) ?? wallNow;
  const at = scheduleAt(day.getFullYear(), day.getMonth() + 1, day.getDate(), doc.querySelector(TIME_TAB)?.textContent ?? "", wallNow);
  return typeof at === "string" ? at : localIso(fromWallClock(at, zone));
}

/**
 * The tag dialog's rows for `items`: the examples hidden and the first one cloned per item (`data-oi-user="<id>"`,
 * its name and @username, checked when the id is `picked`). An empty list hides all rows. ofMirrorData's restore undoes it.
 * Only the open dialog's rows: the page behind may hold its own (New message's Send to lists).
 */
export function applyTagRows(doc: Document, items: TaggedFriendUser[], picked: number[], img?: (u: string) => string): void {
  const examples = [...(doc.querySelector(".modal.show") ?? doc).querySelectorAll<HTMLElement>(`${LIST_ROW}:not([data-oi-user])`)];
  if (!examples.length) return;
  const rows = items.map((item) => {
    const { id, name: label, username } = toChoice(item);
    const row = make(examples[0]);
    row.setAttribute("data-oi-user", String(id));
    // Its More menu's hide (OF's toggle-show takes the list entry's own id and type).
    row.setAttribute("data-oi-entity", String(item.id));
    row.setAttribute("data-oi-type", item.type ?? "user");
    if ((item.user as { hiddenForRf?: boolean } | undefined)?.hiddenForRf) row.setAttribute("data-oi-hidden", "");
    row.setAttribute("data-oi-wired", "");
    const box = row.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (box) box.checked = picked.includes(id);
    // OF sends names HTML-escaped ("&amp;"); its row shows the text.
    const name = row.querySelector(".b-rows-lists__item__name");
    if (name) name.textContent = ` ${plain(label)} `;
    // OF's avatar: the picture, else the initials (the example's is a grey placeholder picture).
    const user = item.user ?? { id, name: label, username };
    row.querySelector(".b-rows-lists__item__icon .g-avatar")?.replaceWith(avatarOf(doc, { ...user, name: plain(user.name ?? label) }, 36, img, "m-border-line m-absolute m-valign-center"));
    // the subline keeps one of OF's items, the @username ("Verified" and the rest dropped)
    const thumbs = row.querySelector(".b-content-inside-thumbs");
    const handle = thumbs?.lastElementChild;
    if (handle) handle.textContent = username ? ` @${username} ` : "";
    thumbs?.replaceChildren(...(handle ? [handle] : []));
    return row;
  });
  fill(doc, examples, rows);
}

/** OF's icon-release-form (its sprite's symbol; the captured tag dialog's cut-down sprite lacks it). */
const ICON_RELEASE_FORM =
  "M17,21H7c-2.21,0-4-1.79-4-4V7c0-2.21,1.79-4,4-4h6.88c.66,0,1.3,.27,1.77,.73l4.62,4.62c.47,.47,.73,1.11,.73,1.77v6.88c0,2.21-1.79,4-4,4Zm-2-15.09v3.09h3.09l-3.09-3.09Zm4,5.09h-5c-.55,0-1-.45-1-1V5H7c-1.1,0-2,.9-2,2v10c0,1.1,.9,2,2,2h10c1.1,0,2-.9,2-2v-6Zm-4,4h-6c-.55,0-1-.45-1-1s.45-1,1-1h6c.55,0,1,.45,1,1s-.45,1-1,1Zm-4.5-4h-1.5c-.55,0-1-.45-1-1s.45-1,1-1h1.5c.55,0,1,.45,1,1s-.45,1-1,1Z";
/** OF's English texts (texts_en.json) for the Release form tab's empty placeholder: message.no_rf_yet, and the
 * EmptyPlaceholder's default message.nothing_found_message while searching. */
export const NO_RELEASE_FORMS = "No release forms yet";
export const NOTHING_FOUND = "Nothing found";

/**
 * The tag dialog's Release form tab with no forms, as OF's DocsAndLinks (chunk 44328) in a modal (or the Release forms
 * page's, with no dialog open): the list's column becomes `d-flex flex-column flex-fill` (no scrollbar) and shows OF's
 * EmptyPlaceholder, the release-form icon (`m-md-size mb-1`) over "No release forms yet"; while searching the search icon
 * over "Nothing found". Returns its undo.
 */
export function applyFormsEmpty(doc: Document, searching: boolean): () => void {
  const docs = (doc.querySelector(".modal.show") ?? doc).querySelector<HTMLElement>(".b-release-form__docs");
  if (!docs) return () => {};
  const was = docs.className;
  docs.classList.remove("m-native-custom-scrollbar", "m-scrollbar-y", "m-invisible-scrollbar");
  docs.classList.add("d-flex", "flex-column", "flex-fill");
  const empty = doc.createElement("div");
  empty.className = "empty-message";
  empty.setAttribute("data-oi-empty", "");
  const icon = searching ? "icon-search" : "icon-release-form";
  const shape = searching ? `<use href="#icon-search" xlink:href="#icon-search"></use>` : `<path d="${ICON_RELEASE_FORM}"></path>`;
  empty.innerHTML = `<svg class="m-md-size mb-1 g-icon" data-icon-name="${icon}" aria-hidden="true" viewBox="0 0 24 24">${shape}</svg><span></span>`;
  empty.querySelector("span")!.textContent = searching ? NOTHING_FOUND : NO_RELEASE_FORMS;
  docs.append(empty);
  return () => {
    empty.remove();
    docs.className = was;
  };
}

/**
 * The labels dialog's rows for `items`: the examples hidden and the first one cloned per label (`data-oi-label="<id>"`,
 * its name and post count, no pictures, checked when the id is `picked`). An empty list hides all rows. ofMirrorData's
 * restore undoes it.
 */
export function applyLabelRows(doc: Document, items: PostLabel[], picked: number[]): void {
  const examples = [...doc.querySelectorAll<HTMLElement>(`${LIST_ROW}:not([data-oi-label])`)];
  if (!examples.length) return;
  const rows = items.map(({ id, name: label, postsCount }) => {
    const row = make(examples[0]);
    row.setAttribute("data-oi-label", String(id));
    row.setAttribute("data-oi-wired", "");
    const box = row.querySelector<HTMLInputElement>("input[type='checkbox']");
    if (box) box.checked = picked.includes(id);
    const name = row.querySelector(".b-rows-lists__item__name");
    if (name) name.textContent = ` ${label} `;
    row.querySelector(".b-media-set")?.remove();
    const count = row.querySelector(".b-content-inside-thumbs__item");
    if (count) count.textContent = ` ${postsCount ?? 0} posts `;
    return row;
  });
  fill(doc, examples, rows);
}

export interface PostHandlers {
  createPost(body: CreatePostBody): Promise<unknown>;
  /** PUT /api/of/v2/queue/posts/{id} with the same body: the Queue's Edit post saving the post in place. */
  editPost?(id: string, body: CreatePostBody): Promise<unknown>;
  /** Ask before a step that cannot be taken back (an edited post with no schedule is published at once). */
  confirm?(text: string): boolean;
  /** POST /api/of/v2/labels {name} for the selected Creator: the new label (its `id`). */
  createLabel(name: string): Promise<{ id?: number } | null | undefined>;
  /** POST /api/of/v2/upload (multipart, part `file`) for the selected Creator. */
  upload(file: File): Promise<VaultUploadResp>;
  /** POST /api/of/v2/stories (JSON) for the selected Creator: a vault item as a Story (absent: the Read-only note). */
  addVaultStory?(body: VaultStoryBody): Promise<unknown>;
  navigate(href: string): void;
  /** A post went through (the composer stays where it is): refresh what shows it (Home's feed, the queue). */
  posted?(): void;
  /** ADD LABELS' Sort: POST /api/of/v2/labels/sort {sort, order}. */
  sortLabels?(sort: string, order: string): Promise<unknown>;
  /** The vault dialog's folder Sort: OF's POST /vault/lists/sort {sort, order} (the Vault page's route). */
  sortFolders?(sort: string, order: string): Promise<unknown>;
  /** A tag row's More > hide from / back to the list: PATCH /api/of/v2/release-forms/toggle-show. */
  toggleTag?(body: { entity_id: number; entity_type: string }): Promise<unknown>;
  /** Invite new user: POST /api/of/v2/guests {name}. */
  inviteGuest?(name: string): Promise<unknown>;
  /** The right column's search: OF's users search and posts search. */
  searchUsers?(query: string): Promise<SearchUser[]>;
  searchPosts?(query: string): Promise<SearchPost[]>;
}

/** A user as OF's search box lists one. */
export interface SearchUser {
  id: number | string;
  name?: string | null;
  username?: string | null;
}
/** A post as OF's posts search lists one. */
export interface SearchPost {
  id: number | string;
  text?: string | null;
  rawText?: string | null;
  author?: { id?: number | string; name?: string | null; username?: string | null } | null;
}

/** The tag dialog's view (the app URL's ?tab= ?q= ?sort= ?order= ?filter=; OF's releaseForms fetch params). */
export interface TagView {
  tab: "users" | "forms";
  q: string | null;
  sort: "date" | "name";
  order: "asc" | "desc";
  filter: "all" | "pending";
}
export function tagViewOf(params: { get(k: string): string | null }): TagView {
  return {
    tab: params.get("tab") === "forms" ? "forms" : "users",
    q: params.get("q")?.trim() || null,
    sort: params.get("sort") === "name" ? "name" : "date",
    order: params.get("order") === "asc" ? "asc" : "desc",
    filter: params.get("filter") === "pending" ? "pending" : "all",
  };
}
/** The tag dialog's page with `view` (OF's defaults left out). */
export function tagHref(view: TagView, page: string): string {
  const q = new URLSearchParams();
  if (view.tab === "forms") q.set("tab", "forms");
  if (view.q) q.set("q", view.q);
  if (view.sort !== "date") q.set("sort", view.sort);
  if (view.order !== "desc") q.set("order", view.order);
  if (view.filter !== "all") q.set("filter", view.filter);
  const qs = q.toString();
  return `/of-manager/${page}${qs ? `?${qs}` : ""}`;
}
/**
 * The relay read for the tag dialog's rows: the Tag user tab is OF's tagged-friend-users (its `name` search: the relay's
 * `search`), the Release form tab OF's release-forms, both with OF's `sort` "<date|name>:<asc|desc>" and `filter`.
 */
export function tagsRoute(view: TagView): string {
  const q = new URLSearchParams({ limit: "50", offset: "0" });
  const plain = view.tab === "users" && !view.q && view.sort === "date" && view.order === "desc" && view.filter === "all";
  if (plain) return TAGS;
  q.set("sort", `${view.sort}:${view.order}`);
  q.set("filter", view.filter);
  if (view.q) q.set(view.tab === "users" ? "search" : "name", view.q);
  return `${view.tab === "users" ? "/api/of/v2/posts/tagged-friend-users" : "/api/of/v2/release-forms"}?${q}`;
}

/** `handlers` null: All-Creators scope (nothing is sent). `storage` or `accountId` null: no draft is kept. */
export interface PostContext {
  handlers: PostHandlers | null;
  storage: Storage | null;
  accountId: string | null;
  /** The Creator's taggable creators (the Relay's list); undefined while loading, after a failure, or All-Creators. */
  tagItems?: TaggedFriendUser[];
  /** The Creator's post labels (the Relay's list); undefined while loading, after a failure, or All-Creators. */
  labelItems?: PostLabel[];
  /** The vault dialog's media (the Relay's list ofMirrorData shows); undefined while loading, after a failure, or All-Creators. */
  vaultItems?: VaultMedia[];
  /** Add media's uploads in flight, shared by every bind of this Creator's composer; undefined: this bind's own count. */
  uploads?: UploadsInFlight;
  /** The draft's id in its key (default: `accountId`): Home's composer keeps its own draft (homeDraft). */
  draftId?: string;
  /** Where a dialog's Next, Save or Save for Later returns: its composer's page (bindPost sets it; default New post). */
  composer?: string;
  /** The vault dialog's view (its ?list= folder and ?type= tab); absent: all media. */
  vaultView?: Partial<VaultView>;
  /** The price button's limits (postPriceLimits); null or undefined: no price button. */
  priceLimits?: PriceLimits | null;
  /** The model Post goes to (its OF name), named by the Post button. */
  postAs?: string;
  /** The Agency's time zone (the top bar's): the schedule dialog and the summary show its wall clock. */
  zone?: string;
  /** The model's OF user id (a search result that is its own post opens My profile). */
  meId?: number | string;
  /** The tag dialog's view (its search, sort, filter and tab). */
  tagView?: TagView;
  /** The labels' and the vault folders' current sort (GET /labels' and /vault/lists' `sort` and `order`). */
  labelSort?: { sort?: string; order?: string };
  folderSort?: { sort?: string; order?: string };
}

/**
 * Uploads in flight survive a rebind (a State page round trip loads a new frame document while an upload runs):
 * `count` is shared, and `refresh` redraws the current bind from the saved draft (Post state and media row), set on bind
 * and cleared on its unbind.
 */
export interface UploadsInFlight {
  count: number;
  refresh?: () => void;
}

/** New post's Add media takes several files at once, audio too (OF's composer: photos, videos and audio). */
export const POST_PICK = { accept: "image/*,video/*,audio/*", multiple: true };

/** OF's "Add media" button on the composer (new-post index; its State page copies sit under the open dialog). */
const ADD_MEDIA = "button.attach_file[aria-label='Add media']";
/** The composer's row of picked media thumbs (rebuilt from the draft on every load). */
const THUMBS_ROW = "oi-post-thumbs";
/** A picker tile in the vault dialog (the folder rows' thumbnails are not). */
const VAULT_TILE = ".b-photos__item.m-checkbox-control";
/** The vault dialog's search box, the header button that opens OF's search form and the form's Back. */
const VAULT_SEARCH = "input[name='media_vault_search']";
const OPEN_SEARCH = "button[aria-label='Search media']";
const CLOSE_SEARCH = "[at-attr='close_search']";
/** OF's mark on a page header whose search form is open (app.css, 70780.css). */
const SEARCH_OPEN = "m-search-form-visible";
/** The vault dialog's media type tabs (All, Photo, GIF, Video, Audio: ofMirrorVault's TYPES). */
const VAULT_TABS = ".modal.show .b-tabs__nav__link";

/** A dialog page's own binding: `update` saves a patch onto the draft. Returns an unbind. */
type DialogBinder = (doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string) => () => void;

/** Where this scope's draft is kept, or null (no draft is kept). */
const keepOf = ({ storage, accountId, draftId }: Pick<PostContext, "storage" | "accountId" | "draftId">) => (storage && accountId ? { storage, accountId: draftId ?? accountId } : null);
const draftOf = (ctx: Pick<PostContext, "storage" | "accountId" | "draftId">) => {
  const keep = keepOf(ctx);
  return keep ? loadDraft(keep.storage, keep.accountId) : emptyDraft();
};

/**
 * Wire the schedule dialog (new-post/state-schedule): it opens on the draft's moment, or else today with the
 * time tab at now plus one hour; day cells, arrows, Next (the moment) and Save for Later (no date). Its days and time
 * are the Agency zone's (ctx.zone) wall clock. Returns an unbind.
 */
function bindSchedule(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void): () => void {
  const timeTab = doc.querySelector<HTMLElement>(TIME_TAB);
  const next = doc.querySelector<HTMLButtonElement>(NEXT);
  const later = doc.querySelector<HTMLButtonElement>(SAVE_LATER);
  if (!timeTab || !next) return () => {};
  const wallNow = () => wallClock(new Date(), ctx.zone);
  const now = wallNow();
  const postedAt = draftOf(ctx).posted_at;
  const at = postedAt ? wallClock(new Date(postedAt), ctx.zone) : null;
  const start = at && at.getTime() > now.getTime() ? at : null;
  renderCalendar(doc, start ?? now, start ?? now, now);
  timeTab.setAttribute("contenteditable", "true");
  timeTab.textContent = clock(start ?? new Date(now.getTime() + 3_600_000));
  next.setAttribute("data-oi-wired", "");
  later?.setAttribute("data-oi-wired", "");

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    const shown = shownMonth(doc);
    const cell = target.closest<HTMLElement>(`.${DAY}`);
    const day = Number(cell?.textContent?.trim());
    if (cell && shown && day && !cell.classList.contains(`${DAY}--disabled`)) {
      renderCalendar(doc, shown, new Date(shown.getFullYear(), shown.getMonth(), day), wallNow());
    }
    const arrow = target.closest(".vdatetime-calendar__navigation--previous, .vdatetime-calendar__navigation--next");
    if (arrow && shown) {
      const today = wallNow();
      const step = arrow.matches(".vdatetime-calendar__navigation--next") ? 1 : -1;
      const month = new Date(shown.getFullYear(), shown.getMonth() + step, 1);
      if (month >= new Date(today.getFullYear(), today.getMonth(), 1)) renderCalendar(doc, month, selectedDay(doc), today);
    }
    if (later && target.closest(SAVE_LATER) === later) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, later, SELECT_MODEL);
      update({ save_for_later: true, posted_at: undefined });
      return ctx.handlers.navigate(ctx.composer ?? COMPOSER);
    }
    if (target.closest(NEXT) !== next) return;
    ev.preventDefault();
    if (!ctx.handlers) return note(doc, next, SELECT_MODEL);
    const at = collectSchedule(doc, new Date(), ctx.zone);
    if (!ISO.test(at)) return note(doc, next, at, true);
    update({ posted_at: at, save_for_later: undefined });
    ctx.handlers.navigate(ctx.composer ?? COMPOSER);
  };

  doc.addEventListener("click", onClick);
  return () => doc.removeEventListener("click", onClick);
}

/** What the tag dialog reads: the Relay's rows, its view, the draft's place, and the handlers its tools use. */
export type TagContext = Pick<PostContext, "tagItems" | "tagView" | "storage" | "accountId" | "draftId"> & {
  handlers: Pick<PostHandlers, "navigate" | "toggleTag" | "inviteGuest"> | null;
};
/** A tag dialog's picks kept elsewhere than New post's draft (a chat's): the picked ids, a row's toggle, the dialog's href for a view. */
export interface TagPicks {
  ids(): number[];
  toggle(pick: { id: number; type: string; name: string }, on: boolean): void;
  href(view: TagView): string;
}

/**
 * Wire the tag dialog (new-post/state-tag-people): its rows are the Relay's list with a single Creator, else none (the
 * captured examples never show: All-Creators, loading, a failure); a row's change toggles its id in the draft's Co-tags
 * (operator order, no duplicates). OF's own tools, for the view in the app URL (TagView, tagsRoute):
 * - the header's search icon opens a search field (OF's `name` search; typing stops for 400 ms: the dialog with ?q=);
 * - Sort: OF's menu (All / Pending, Recent / Name, Ascending / Descending), a pick opens the dialog sorted so;
 * - the Tag user / Release form tabs: the Release form tab lists OF's release forms (GET /release-forms), as rows to tag;
 *   none: OF's empty placeholder (applyFormsEmpty);
 * - a row's More: "Hide from list" (or "Show in list" for a hidden one) sends OF's toggle-show, then OF's toast;
 * - Invite new user: a name field and Save (POST /guests {name}); OF answers with the guest.
 * All-Creators: each says "Select a model". Returns an unbind, which puts the examples back.
 */
export function bindTags(doc: Document, ctx: TagContext, update: (patch: Partial<PostDraft>) => void, page: string, picks?: TagPicks): () => void {
  const { handlers, tagItems } = ctx;
  const view = ctx.tagView ?? tagViewOf(new URLSearchParams());
  const picked = () => (picks ? picks.ids() : draftOf(ctx).tagged_users);
  // Kept apart from ofMirrorData's restore: over Home, the feed's data re-applies (and this unbind leaves it alone).
  const undo = own(() => applyTagRows(doc, (handlers && tagItems) || [], picked(), (u) => proxyImage(u, ctx.accountId)));
  // The Release form tab's list came back empty: OF's placeholder (nothing while loading, after a failure, All-Creators).
  const undoEmpty = view.tab === "forms" && handlers && tagItems && !tagItems.length ? applyFormsEmpty(doc, !!view.q) : () => {};
  const modal = doc.querySelector<HTMLElement>(".modal.show");
  const header = modal?.querySelector<HTMLElement>(".modal-header");
  const sortBtn = modal?.querySelector<HTMLButtonElement>("button[aria-label='Sort']");
  // OF's search icon: the header's first round button (no label).
  const searchBtn = header?.querySelector<HTMLButtonElement>("button.g-btn.m-icon.m-icon-only:not([aria-label])");
  const tabs = [...(modal?.querySelectorAll<HTMLElement>(".b-tabs__nav__link") ?? [])];
  markTagTabs(tabs, view);
  const invite = [...(modal?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find((b) => b.textContent?.trim() === "Invite new user") ?? null;
  for (const el of [sortBtn, searchBtn, invite, ...doc.querySelectorAll(`${LIST_ROW} .m-btn-vertical-dots`)]) el?.setAttribute("data-oi-wired", "");
  const go = (next: TagView) => handlers?.navigate(picks ? picks.href(next) : tagHref(next, page));

  // The search field (OF's header search): open while the view has a query, or once the icon is clicked.
  let field: HTMLInputElement | null = null;
  let timer = 0;
  const title = header?.querySelector<HTMLElement>(".modal-title, h4");
  const openSearch = () => {
    if (field || !header) return field?.focus();
    field = doc.createElement("input");
    field.type = "search";
    field.maxLength = 100;
    field.placeholder = "Search...";
    field.setAttribute("aria-label", "Search creators");
    field.className = "b-search-form__input form-control";
    field.style.cssText = "flex:1;min-width:0;margin:0 8px;height:32px";
    field.value = view.q ?? "";
    field.setAttribute("data-oi-wired", "");
    field.id = "oi-tag-search";
    // OF's open search form takes the title's place.
    if (title) title.style.display = "none";
    (searchBtn ?? header.lastElementChild)?.before(field);
    field.addEventListener("input", () => {
      doc.defaultView?.clearTimeout(timer);
      timer = doc.defaultView?.setTimeout(() => go({ ...view, q: field?.value.trim() || null }), 400) ?? 0;
    });
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  };
  if (view.q && handlers) openSearch();

  const form = invite ? newLabelForm(doc, invite, "Name") : null;
  const openInvite = (on: boolean) => {
    if (!invite || !form) return;
    invite.style.display = on ? "none" : "";
    form.root.style.display = on ? "flex" : "none";
    form.input.value = "";
    form.save.disabled = true;
    if (on) form.input.focus();
  };
  const sendInvite = () => {
    const name = form?.input.value.trim();
    if (!handlers?.inviteGuest || !form || !name || form.save.disabled) return;
    form.save.disabled = true;
    handlers.inviteGuest(name).then(
      () => {
        openInvite(false);
        toast(doc, `${name} is invited`);
      },
      (e) => {
        form.save.disabled = false;
        note(doc, form.save, `Could not invite: ${message(e)}`, true);
      },
    );
  };

  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement;
    const row = box.closest?.<HTMLElement>(LIST_ROW);
    const id = Number(row?.getAttribute("data-oi-user"));
    if (!handlers || !id) return;
    if (picks) return picks.toggle({ id, type: row!.getAttribute("data-oi-type") ?? "user", name: row!.querySelector(".b-rows-lists__item__name")?.textContent?.trim() ?? "" }, box.checked);
    const others = draftOf(ctx).tagged_users.filter((t) => t !== id);
    update({ tagged_users: box.checked ? [...others, id] : others });
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (!t?.closest) return;
    if (tagViewClick(doc, ev, { tabs, sortBtn, view, on: !!handlers, go })) return;
    if (searchBtn && t.closest("button") === searchBtn) {
      ev.preventDefault();
      return handlers ? openSearch() : note(doc, searchBtn, SELECT_MODEL);
    }
    const dots = t.closest<HTMLButtonElement>(`${LIST_ROW} .m-btn-vertical-dots`);
    if (dots) {
      ev.preventDefault();
      ev.stopPropagation();
      return tagRowMenu(doc, dots, handlers);
    }
    if (invite && form) {
      if (t.closest("button") === invite) {
        ev.preventDefault();
        return handlers ? openInvite(true) : note(doc, invite, SELECT_MODEL);
      }
      if (t.closest("[data-oi-cancel]") === form.cancel) {
        ev.preventDefault();
        return openInvite(false);
      }
      if (t.closest("[data-oi-save]") === form.save) {
        ev.preventDefault();
        sendInvite();
      }
    }
  };
  const onInput = (ev: Event) => {
    if (form && ev.target === form.input) form.save.disabled = !form.input.value.trim();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (form && ev.target === form.input && ev.key === "Enter") {
      ev.preventDefault();
      sendInvite();
    }
    if (field && ev.target === field && ev.key === "Enter") ev.preventDefault();
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("keydown", onKey);
  return () => {
    doc.defaultView?.clearTimeout(timer);
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("keydown", onKey);
    field?.remove();
    if (title) title.style.display = "";
    form?.root.remove();
    if (invite) invite.style.display = "";
    closeMenu(doc);
    undoEmpty();
    undo();
  };
}

/** The tag lists' sorts (OF's `sort`), as their Sort menu and filter title word them. */
export const TAG_SORT_LABELS: Record<TagView["sort"], string> = { date: "Recent", name: "Name" };
/** A tag list's tab (the tag dialog's, Release forms'): Release form lists OF's release forms, any other OF's users. */
const tagTabOf = (t: Element): TagView["tab"] => (t.textContent?.trim() === "Release form" ? "forms" : "users");

/** The tag list's tabs `tabs` for `view`: its tab current (OF's m-current, not clickable), each Wired. */
export function markTagTabs(tabs: Element[], view: TagView): void {
  for (const t of tabs) {
    const on = tagTabOf(t) === view.tab;
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    t.setAttribute("data-oi-wired", "");
  }
}

/**
 * A click on a tag list's view tools: one of `tabs` opens the list on that tab; `sortBtn` opens OF's Sort menu (All /
 * Pending, Recent / Name, Ascending / Descending), a pick opens the list so. `on` false (no model): the select-a-model
 * note. Returns whether the click was on one of them.
 */
export function tagViewClick(
  doc: Document,
  ev: MouseEvent,
  { tabs, sortBtn, view, on, go }: { tabs: Element[]; sortBtn?: HTMLButtonElement | null; view: TagView; on: boolean; go(view: TagView): void },
): boolean {
  const t = ev.target as Element;
  const tab = tabs.find((x) => x.contains(t));
  if (tab) {
    ev.preventDefault();
    if (!on) note(doc, tab, SELECT_MODEL);
    else if (tagTabOf(tab) !== view.tab) go({ ...view, tab: tagTabOf(tab) });
    return true;
  }
  if (!sortBtn || t.closest("button") !== sortBtn) return false;
  ev.preventDefault();
  if (!on) {
    note(doc, sortBtn, SELECT_MODEL);
    return true;
  }
  const groups: MenuGroup[] = [
    { name: "filter", value: view.filter, options: [{ value: "all", label: "All" }, { value: "pending", label: "Pending" }] },
    { name: "sort", value: view.sort, options: [{ value: "date", label: TAG_SORT_LABELS.date }, { value: "name", label: TAG_SORT_LABELS.name }] },
    ORDER_GROUP(view.order),
  ];
  showMenu(doc, sortBtn, groups, (g, v) => go({ ...view, [g]: v } as TagView));
  return true;
}

/**
 * A tag row's More (`dots`, an applyTagRows row's): OF's menu with "Hide from list" (or "Show in list" for a hidden row),
 * which sends OF's toggle-show for the row's list entry, then OF's toast. No handlers (All-Creators): the select-a-model note.
 */
export function tagRowMenu(doc: Document, dots: HTMLElement, handlers: Pick<PostHandlers, "toggleTag"> | null): void {
  const row = dots.closest<HTMLElement>(LIST_ROW);
  const entity = Number(row?.getAttribute("data-oi-entity"));
  if (!handlers || !row || !entity) return note(doc, row ?? dots, SELECT_MODEL);
  const hidden = row.hasAttribute("data-oi-hidden");
  showMenu(doc, dots, [{ name: "row", radio: false, options: [{ value: "toggle", label: hidden ? "Show in list" : "Hide from list" }] }], () => {
    if (!handlers.toggleTag) return note(doc, row, READ_ONLY);
    handlers.toggleTag({ entity_id: entity, entity_type: row.getAttribute("data-oi-type") ?? "user" }).then(
      () => {
        row.toggleAttribute("data-oi-hidden", !hidden);
        toast(doc, hidden ? "Successfully returned to the list" : "Successfully removed from the list");
      },
      (e) => note(doc, row, `Could not ${hidden ? "show" : "hide"}: ${message(e)}`, true),
    );
  });
}

/**
 * Wire the labels dialog (new-post/state-labels) as the tag dialog: its rows are the Relay's list with a single Creator,
 * else none; a row's change toggles the label's id in the draft's `label_ids`. NEW LABEL opens OF's name field in place of
 * the button (Cancel puts the button back; Save is enabled while the name has text): Save creates the label and picks it
 * (the Relay's list is then fetched again, and the rebind shows it checked); a failure shows a red "Could not create: …".
 * All-Creators: NEW LABEL gives the select-a-model note. Returns an unbind, which removes the field and puts the
 * examples back.
 */
function bindLabels(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void): () => void {
  const { handlers, labelItems } = ctx;
  // Kept apart from ofMirrorData's restore: the page's right column (promotions, events) re-applies over it.
  const undo = own(() => applyLabelRows(doc, (handlers && labelItems && postLabelsOf(labelItems)) || [], draftOf(ctx).label_ids ?? []));
  const add = doc.querySelector<HTMLButtonElement>(NEW_LABEL);
  add?.setAttribute("data-oi-wired", "");
  const form = add && newLabelForm(doc, add);
  // OF's Sort (labels/savePostLabelsOrder): the rows are put in that order at once, and OF keeps it.
  const sortBtn = doc.querySelector<HTMLButtonElement>(".modal.show button[aria-label='Sort']");
  sortBtn?.setAttribute("data-oi-wired", "");
  const sorted = { sort: ctx.labelSort?.sort ?? "recent", order: ctx.labelSort?.order ?? "desc" };

  const onChange = (ev: Event) => {
    const box = ev.target as HTMLInputElement;
    const id = Number(box.closest?.<HTMLElement>(LIST_ROW)?.getAttribute("data-oi-label"));
    if (!handlers || !id) return;
    const others = (draftOf(ctx).label_ids ?? []).filter((l) => l !== id);
    update({ label_ids: box.checked ? [...others, id] : others });
  };
  /** NEW LABEL's field shown (`on`) or the button back, the field emptied. */
  const open = (on: boolean) => {
    if (!add || !form) return;
    add.style.display = on ? "none" : "";
    form.root.style.display = on ? "flex" : "none";
    form.input.value = "";
    form.save.disabled = true;
    if (on) form.input.focus();
  };
  const create = () => {
    const name = form?.input.value.trim();
    if (!handlers || !form || !name || form.save.disabled) return;
    form.save.disabled = true;
    handlers.createLabel(name).then(
      (label) => {
        const id = Number(label?.id);
        if (id) update({ label_ids: [...(draftOf(ctx).label_ids ?? []).filter((l) => l !== id), id] });
        open(false);
      },
      (e) => {
        form.save.disabled = false;
        note(doc, form.save, `Could not create: ${message(e)}`, true);
      },
    );
  };
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (sortBtn && target?.closest?.("button") === sortBtn) {
      ev.preventDefault();
      if (!handlers) return note(doc, sortBtn, SELECT_MODEL);
      const groups: MenuGroup[] = [{ name: "sort", value: sorted.sort, options: LABEL_SORTS }, ORDER_GROUP(sorted.order)];
      showMenu(doc, sortBtn, groups, (g, v) => {
        Object.assign(sorted, { [g]: v });
        sortLabelRows(doc, labelItems ?? [], sorted.sort, sorted.order);
        if (!handlers.sortLabels) return note(doc, sortBtn, READ_ONLY);
        // (under the dialog's header: a note beside the button would squeeze its title)
        handlers.sortLabels(sorted.sort, sorted.order).catch((e) => note(doc, sortBtn.closest(".modal-header") ?? sortBtn, `Could not save the order: ${message(e)}`, true));
      });
      return;
    }
    if (!add || !form || !target?.closest) return;
    if (target.closest(NEW_LABEL) === add) {
      ev.preventDefault();
      return handlers ? open(true) : note(doc, add, SELECT_MODEL);
    }
    if (target.closest("[data-oi-cancel]") === form.cancel) {
      ev.preventDefault();
      return open(false);
    }
    if (target.closest("[data-oi-save]") === form.save) {
      ev.preventDefault();
      create();
    }
  };
  const onInput = (ev: Event) => {
    if (form && ev.target === form.input) form.save.disabled = !form.input.value.trim();
  };
  const onKey = (ev: KeyboardEvent) => {
    if (form && ev.target === form.input && ev.key === "Enter") {
      ev.preventDefault();
      create();
    }
  };

  doc.addEventListener("change", onChange);
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("keydown", onKey);
  return () => {
    doc.removeEventListener("change", onChange);
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("keydown", onKey);
    form?.root.remove();
    if (add) add.style.display = "";
    undo();
  };
}

/** OF's labels Sort fields (labels/savePostLabelsOrder: recent | name | posts | custom). */
const LABEL_SORTS = [
  { value: "recent", label: "Recent" },
  { value: "name", label: "Name" },
  { value: "posts", label: "Posts" },
  { value: "custom", label: "Custom" },
];

/**
 * The labels dialog's rows in `sort` / `order` (Recent: newest id first, Name, Posts: post count; Custom: OF's own order,
 * the Relay's as read), moved in place.
 */
export function sortLabelRows(doc: Document, items: PostLabel[], sort: string, order: string): void {
  const rows = [...doc.querySelectorAll<HTMLElement>(`${LIST_ROW}[data-oi-label]`)];
  if (rows.length < 2) return;
  const byId = new Map(items.map((l, i) => [String(l.id), { ...l, at: i }]));
  const key = (r: HTMLElement) => byId.get(r.getAttribute("data-oi-label") ?? "");
  const dir = order === "asc" ? 1 : -1;
  const cmp = (a: HTMLElement, b: HTMLElement) => {
    const x = key(a);
    const y = key(b);
    if (!x || !y) return 0;
    if (sort === "name") return dir * x.name.localeCompare(y.name);
    if (sort === "posts") return dir * ((x.postsCount ?? 0) - (y.postsCount ?? 0));
    if (sort === "recent") return dir * (Number(x.id) - Number(y.id));
    return x.at - y.at;
  };
  const anchor = rows[0].previousSibling;
  const parent = rows[0].parentElement!;
  const ordered = [...rows].sort(cmp);
  if (anchor) anchor.after(...ordered);
  else parent.prepend(...ordered);
}

/**
 * NEW LABEL's name field (hidden until opened), in its own row above the labels dialog's footer: OF's outlined text
 * field (the Fundraising target's markup) with a Cancel and a Save in the footer's own button style.
 */
function newLabelForm(doc: Document, add: HTMLButtonElement, placeholder = "Label name") {
  const root = doc.createElement("div");
  root.id = "oi-new-label";
  root.style.cssText = "display:none;align-items:center;gap:8px;padding:8px 16px;min-width:0";
  const field = doc.createElement("div");
  field.className = "v-input form-control g-input mb-0 v-input--hide-details theme--light v-text-field v-text-field--is-booted v-text-field--enclosed v-text-field--outlined";
  field.style.cssText = "flex:1;min-width:0;border-bottom:1px solid rgba(138,150,163,.5)";
  const slot = doc.createElement("div");
  slot.className = "v-text-field__slot";
  const input = doc.createElement("input");
  input.type = "text";
  input.maxLength = 64;
  input.style.cssText = "width:100%;padding:6px 0";
  input.placeholder = placeholder;
  input.setAttribute("aria-label", placeholder);
  input.setAttribute("data-oi-wired", "");
  slot.append(input);
  const control = doc.createElement("div");
  control.className = "v-input__control";
  const inner = doc.createElement("div");
  inner.className = "v-input__slot";
  inner.append(slot);
  control.append(inner);
  field.append(control);
  const button = (text: string, mark: string) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "g-btn m-flat m-btn-gaps m-uppercase m-reset-width";
    b.textContent = ` ${text} `;
    b.setAttribute(mark, "");
    b.setAttribute("data-oi-wired", "");
    return b;
  };
  const cancel = button("Cancel", "data-oi-cancel");
  const save = button("Save", "data-oi-save");
  save.disabled = true;
  root.append(field, cancel, save);
  (add.closest("footer") ?? add).before(root);
  return { root, input, cancel, save };
}

/**
 * Wire the poll (`type` 1, new-post/state-poll) or quiz (2, new-post/state-quiz) panel: its rows show the draft's
 * options of that type ("+ Add another option" rows added as needed); typing saves the rows' text, and a quiz row's
 * correct-answer switch marks that row alone, as the draft's `voting` (none while every option is blank). "+ Add
 * another option" adds an empty row (OF's markup, cloned; at most 20). A row's delete removes it while more than two
 * are left (OF's minimum; a removed correct answer moves to the first row). The panel's "Poll · 7 days" piece shows the
 * draft's `voting_due` and a click on it opens the period dialog for it (`period_for`). The panel's × drops the poll and
 * its duration from the draft (its link then returns to the composer). All-Creators: a typed option or a switch is reset
 * and gives the select-a-model note, as do a delete, the piece and "+ Add another option". Returns an unbind.
 */
const bindVoting =
  (type: 1 | 2): DialogBinder =>
  (doc, ctx, update) => {
    const add = doc.querySelector<HTMLButtonElement>(ADD_OPTION);
    const first = doc.querySelector(VOTE_ROW);
    if (!add || !first) return () => {};
    const template = first.cloneNode(true) as HTMLElement;
    const rows = () => [...doc.querySelectorAll<HTMLElement>(VOTE_ROW)];
    const radio = (row: Element) => row.querySelector<HTMLInputElement>("input[type='radio']");
    /** A quiz row's correct-answer switch on or off: its radio, and OF's grey dropped from the chosen switch. */
    const pick = (row: Element, on: boolean) => {
      const r = radio(row);
      if (r) {
        r.checked = on;
        r.toggleAttribute("checked", on);
      }
      row.querySelector(QUIZ_PICK)?.classList.toggle("m-gray", !on);
    };
    /** Mark the rows' controls, and enable their deletes while more than two rows are left. */
    const wire = () => {
      for (const el of doc.querySelectorAll(`${VOTE_ROW} ${OPTION}, ${VOTE_ROW} ${QUIZ_PICK}, ${VOTE_ROW} input[type='radio'], ${VOTE_ROW} ${DELETE_OPTION}, ${VOTE_ROW} ${DRAG}`)) el.setAttribute("data-oi-wired", "");
      const many = rows().length > 2;
      for (const del of doc.querySelectorAll<HTMLButtonElement>(`${VOTE_ROW} ${DELETE_OPTION}`)) del.disabled = !many;
    };
    let added = 0;
    const addRow = () => {
      const row = template.cloneNode(true) as HTMLElement;
      const input = row.querySelector<HTMLInputElement>(OPTION);
      if (input) input.placeholder = "Enter another option...";
      const r = radio(row);
      if (r) r.name = `quiz-option-oi-${++added}`; // a row's own group, as each captured row has
      rows().at(-1)!.after(row);
      wire();
      return input;
    };
    const saved = draftOf(ctx).voting;
    if (saved?.type === type) {
      while (rows().length < saved.options.length) addRow();
      rows().forEach((row, i) => {
        const input = row.querySelector<HTMLInputElement>(OPTION);
        if (input) input.value = saved.options[i] ?? "";
        pick(row, i === saved.correct);
      });
    }
    add.setAttribute("data-oi-wired", "");
    wire();
    const piece = doc.querySelector(VOTING_PIECE);
    piece?.setAttribute("data-oi-wired", "");
    const shown = piece?.querySelector(".b-post-piece__value");
    if (shown) shown.textContent = daysText(draftOf(ctx).voting_due ?? VOTING_DAYS);

    /** The panel's rows as the draft's `voting` (none while every option is blank). */
    const save = () => {
      const all = rows();
      const options = all.map((row) => row.querySelector<HTMLInputElement>(OPTION)?.value ?? "");
      const correct = all.findIndex((row) => radio(row)?.checked);
      update({ voting: options.some((o) => o.trim()) ? { type, options, ...(type === 2 && correct >= 0 ? { correct } : {}) } : undefined });
    };
    const onInput = (ev: Event) => {
      if (ctx.handlers && (ev.target as Element | null)?.closest?.(VOTE_ROW)) save();
    };
    const onChange = (ev: Event) => {
      const field = ev.target as HTMLInputElement;
      if (ctx.handlers || !field.closest?.(VOTE_ROW) || field.type === "radio") return;
      field.value = ""; // nothing was saved: show the real state again
      note(doc, field, SELECT_MODEL);
    };
    const onClick = (ev: MouseEvent) => {
      const target = ev.target as Element | null;
      if (!target?.closest) return;
      if (target.closest(DROP_VOTING)) return update({ voting: undefined, voting_due: undefined });
      // A handle only drags; a plain click says so.
      const handle = target.closest(`${VOTE_ROW} ${DRAG}`);
      if (handle) {
        ev.preventDefault();
        if (ctx.handlers) note(doc, handle.closest(VOTE_ROW) ?? handle, "Drag to reorder the options");
        return;
      }
      if (target.closest(ADD_OPTION) === add) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, add, SELECT_MODEL);
        if (rows().length < MAX_OPTIONS) addRow()?.focus();
        return;
      }
      if (piece && target.closest(VOTING_PIECE) === piece) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, piece, SELECT_MODEL);
        update({ period_for: type });
        return ctx.handlers.navigate(composerPage(ctx, PERIOD_PAGE));
      }
      const del = target.closest(DELETE_OPTION)?.closest(VOTE_ROW);
      if (del) {
        ev.preventDefault();
        if (!ctx.handlers) return note(doc, del, SELECT_MODEL);
        if (rows().length <= 2) return;
        const wasCorrect = !!radio(del)?.checked;
        del.remove();
        if (wasCorrect) pick(rows()[0], true);
        wire();
        return save();
      }
      const row = target.closest(QUIZ_PICK)?.closest(VOTE_ROW);
      if (!row) return;
      for (const r of rows()) pick(r, !!ctx.handlers && r === row);
      if (ctx.handlers) save();
      else note(doc, row, SELECT_MODEL);
    };
    // OF's drag handle (its m-draggable list): a press on a row's handle carries the row; it is put before the first row
    // whose middle lies below the pointer (else last), and the release saves the new order.
    let dragging: HTMLElement | null = null;
    const onDown = (ev: PointerEvent | MouseEvent) => {
      const handle = (ev.target as Element | null)?.closest?.(`${VOTE_ROW} ${DRAG}`);
      if (!handle) return;
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, handle.closest(VOTE_ROW) ?? handle, SELECT_MODEL);
      dragging = handle.closest<HTMLElement>(VOTE_ROW);
      if (dragging) dragging.style.opacity = "0.5";
    };
    const onMove = (ev: PointerEvent | MouseEvent) => {
      if (!dragging) return;
      ev.preventDefault();
      const others = rows().filter((r) => r !== dragging);
      const before = others.find((r) => {
        const box = r.getBoundingClientRect();
        return ev.clientY < box.top + box.height / 2;
      });
      if (before) {
        if (dragging.nextElementSibling !== before) before.before(dragging);
      } else if (others.length && others.at(-1)!.nextElementSibling !== dragging) others.at(-1)!.after(dragging);
    };
    const onUp = () => {
      if (!dragging) return;
      dragging.style.opacity = "";
      dragging = null;
      wire();
      save();
    };
    doc.addEventListener("input", onInput);
    doc.addEventListener("change", onChange);
    doc.addEventListener("click", onClick);
    doc.addEventListener("pointerdown", onDown);
    doc.addEventListener("pointermove", onMove);
    doc.addEventListener("pointerup", onUp);
    return () => {
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("change", onChange);
      doc.removeEventListener("click", onClick);
      doc.removeEventListener("pointerdown", onDown);
      doc.removeEventListener("pointermove", onMove);
      doc.removeEventListener("pointerup", onUp);
    };
  };

/**
 * A dialog with one field and a Save (`field`; EXPIRATION PERIOD, Fundraising target, a poll's duration): it opens on the
 * draft's value; `read` gives the field's value for the draft, or null while it is not valid (Save is disabled then). Save
 * stores it (0 or "" as none; `voting_due` keeps 0, its No limit, and opens on OF's 7 days when unset) and returns to
 * `back` (default: the composer); All-Creators: the select-a-model note. `extra` wires anything else and returns its unbind.
 */
const bindValueDialog =
  <K extends "expire_days" | "fund_raising_target" | "voting_due" | "price">(
    key: K,
    field: string,
    read: (value: string) => PostDraft[K] | null,
    extra: (doc: Document, input: HTMLInputElement, sync: () => void) => () => void = () => () => {},
    back?: string,
  ): DialogBinder =>
  (doc, ctx, update) => {
    const input = doc.querySelector<HTMLInputElement>(field);
    const save = doc.querySelector<HTMLButtonElement>(DIALOG_SAVE);
    if (!input || !save) return () => {};
    for (const el of [input, save]) el.setAttribute("data-oi-wired", "");
    const sync = () => {
      floatLabel(input, !!input.value);
      save.disabled = read(input.value) === null;
    };
    const saved = key === "voting_due" ? (draftOf(ctx).voting_due ?? VOTING_DAYS) : draftOf(ctx)[key];
    if (saved) {
      input.value = String(saved);
      sync();
    }
    const onInput = (ev: Event) => {
      if (ev.target === input) sync();
    };
    const onClick = (ev: MouseEvent) => {
      if ((ev.target as Element | null)?.closest?.(DIALOG_SAVE) !== save) return;
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, save, SELECT_MODEL);
      const value = read(input.value);
      if (value === null) return;
      update({ [key]: key === "voting_due" ? value : value || undefined });
      ctx.handlers.navigate(back ?? ctx.composer ?? COMPOSER);
    };
    const unbindExtra = extra(doc, input, sync);
    doc.addEventListener("input", onInput);
    doc.addEventListener("click", onClick);
    return () => {
      unbindExtra();
      doc.removeEventListener("input", onInput);
      doc.removeEventListener("click", onClick);
    };
  };

/** EXPIRATION PERIOD's days: "" (No limit) is 0; a whole 1-30 (OF's maximum) is itself; anything else is null. */
const readDays = (value: string): number | null => {
  const v = value.trim();
  const n = Number(v);
  return !v ? 0 : Number.isInteger(n) && n >= 1 && n <= MAX_DAYS ? n : null;
};
/** Its tabs (No limit, 1 day, …): a click puts its days in the field; the tab of the field's days is current. */
const periodTabs = (doc: Document, input: HTMLInputElement, sync: () => void) => {
  const tabs = [...doc.querySelectorAll<HTMLButtonElement>(PERIOD_TAB)];
  const daysOf = (tab: Element) => /\d+/.exec(tab.textContent ?? "")?.[0] ?? "";
  const mark = () => {
    for (const tab of tabs) tab.classList.toggle("m-current", readDays(daysOf(tab)) === readDays(input.value));
  };
  for (const tab of tabs) tab.setAttribute("data-oi-wired", "");
  mark();
  const onInput = (ev: Event) => {
    if (ev.target === input) mark();
  };
  const onClick = (ev: MouseEvent) => {
    const tab = (ev.target as Element | null)?.closest?.<HTMLButtonElement>(PERIOD_TAB);
    if (!tab || !tabs.includes(tab)) return;
    ev.preventDefault();
    input.value = daysOf(tab);
    mark();
    sync();
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
};
/**
 * The EXPIRATION PERIOD dialog (new-post/state-expiration): the post's `expire_days`, or, when a poll or quiz panel's
 * duration opened it (the draft's `period_for`), that poll's `voting_due`: then its title names the duration, and Save,
 * Cancel and the backdrop return to the poll or quiz panel. Returns an unbind, which puts the title and links back.
 */
const bindPeriod: DialogBinder = (doc, ctx, update, page) => {
  const type = draftOf(ctx).period_for;
  if (!type) return bindValueDialog("expire_days", PERIOD, readDays, periodTabs)(doc, ctx, update, page);
  const back = composerPage(ctx, VOTING_PAGES[type]);
  const title = doc.querySelector(".modal.show .modal-title");
  const links = [...doc.querySelectorAll<HTMLAnchorElement>(".modal.show .modal-footer a, .modal.show .of-state-backdrop")];
  const was = { title: title?.textContent, hrefs: links.map((a) => a.getAttribute("href")) };
  if (title) title.textContent = DURATION_TITLES[type];
  for (const a of links) a.setAttribute("href", back);
  const unbind = bindValueDialog("voting_due", PERIOD, readDays, periodTabs, back)(doc, ctx, update, page);
  return () => {
    unbind();
    if (title) title.textContent = was.title ?? "";
    links.forEach((a, i) => a.setAttribute("href", was.hrefs[i] ?? ctx.composer ?? COMPOSER));
  };
};

/** POST PRICE's dollars: "" is free (0); a number within `limits` is itself; anything else (or no limits) is null. */
export const readPrice =
  (limits: PriceLimits | null | undefined) =>
  (value: string): number | null => {
    const v = value.trim().replace(/^\$/, "");
    if (!v) return 0;
    const n = Number(v);
    return limits && Number.isFinite(n) && n >= limits.min && n <= limits.max ? Math.round(n * 100) / 100 : null;
  };

/**
 * The POST PRICE dialog (new-post/state-price, OF's ModalPostPrice over the composer): it opens on the draft's price, its
 * line under the field states the Creator's minimum ("Minimum $3 USD or free", OF's), and Save keeps a price within the
 * limits on the draft and returns to the composer. As OF's isPriceInvalid, Save is disabled while the field is empty
 * (unless it clears a saved price: the post is free again) or holds the saved price. No limits (a paid page): Save
 * stays disabled.
 */
const bindPrice: DialogBinder = (doc, ctx, update, page) => {
  const help = doc.querySelector(".modal.show .g-input__help");
  const was = help?.textContent ?? "";
  if (help && ctx.priceLimits) help.textContent = `Minimum $${ctx.priceLimits.min} USD or free`;
  const saved = draftOf(ctx).price ?? 0;
  const read = (value: string) => {
    const n = readPrice(ctx.priceLimits)(value);
    return n === null || n === saved || (n === 0 && !saved) ? null : n;
  };
  const unbind = bindValueDialog("price", TARGET, read)(doc, ctx, update, page);
  return () => {
    unbind();
    if (help) help.textContent = was;
  };
};

/** The fundraising target in dollars ("$" allowed), or null below the minimum. */
const readTarget = (value: string): number | null => {
  const n = Number(value.trim().replace(/^\$/, ""));
  return value.trim() && Number.isFinite(n) && n >= MIN_TARGET ? n : null;
};

/**
 * Wire the vault dialog's search (new-post/state-vault): Search media opens OF's search form (Back closes and clears
 * it); typing there hides (display:none) every real tile whose `data-oi-text` (ofMirrorData's date label and AI text)
 * lacks the trimmed, case-folded query, an empty query shows all, and a submit stays on the page. Search never touches
 * the draft. Returns an unbind.
 */
export function bindVaultSearch(doc: Document): () => void {
  const search = doc.querySelector<HTMLInputElement>(VAULT_SEARCH);
  const header = search?.closest(".g-page__header");
  const opener = header?.querySelector(OPEN_SEARCH);
  const closer = header?.querySelector(CLOSE_SEARCH);
  if (!search || !header || !opener || !closer) return () => {};
  for (const el of [search, opener, closer]) el.setAttribute("data-oi-wired", "");
  const filter = () => {
    const query = search.value.trim().toLowerCase();
    for (const tile of doc.querySelectorAll<HTMLElement>("[data-oi-media]")) {
      tile.style.display = (tile.getAttribute("data-oi-text") ?? "").toLowerCase().includes(query) ? "" : "none";
    }
  };
  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest(OPEN_SEARCH) === opener) {
      header.classList.add(SEARCH_OPEN);
      search.focus();
    } else if (target.closest(CLOSE_SEARCH) === closer) {
      header.classList.remove(SEARCH_OPEN);
      search.value = "";
      filter();
    }
  };
  const onInput = (ev: Event) => {
    if (ev.target === search) filter();
  };
  const onSubmit = (ev: Event) => {
    if (ev.target === search.form) ev.preventDefault();
  };
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    doc.removeEventListener("click", onClick);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
  };
}

/**
 * Wire the vault dialog (new-post/state-vault): a click on a real tile (`data-oi-media`, stamped by ofMirrorData) adds or
 * removes its vault id and picture in the draft, and its mark follows the draft; an example tile or All-Creators scope
 * gives the select-a-model note. Its search is `bindVaultSearch`. An "Add to story" button (OF's footer button markup)
 * before Close publishes the one picked vault item as the Creator's Story (`vaultStoryBody`): disabled while it sends,
 * then "Added to story", or a red "Could not add: …"; none or several picked: a red "Pick one vault item for the story"
 * and nothing is sent; All-Creators: the select-a-model note. The pick stays in the Post draft. Its media type tabs show
 * the view's type and a click opens the dialog on that type (`page`'s own route, the folder kept), as the Vault page's
 * tabs do. Returns an unbind, which removes the button.
 */
function bindVault(doc: Document, ctx: PostContext, update: (patch: Partial<PostDraft>) => void, page: string): () => void {
  const view = ctx.vaultView ?? {};
  const tabs = [...doc.querySelectorAll<HTMLElement>(VAULT_TABS)];
  tabs.forEach((t, i) => {
    const on = (TYPES[i] ?? null) === (view.type ?? null);
    t.classList.toggle("m-current", on);
    t.classList.toggle("m-no-pointer", on);
    t.setAttribute("data-oi-wired", "");
  });
  const close = doc.querySelector(".modal.show .modal-footer a");
  const story = doc.createElement("button");
  story.type = "button";
  story.className = close?.className ?? "g-btn m-flat m-btn-gaps m-uppercase m-reset-width";
  story.textContent = " Add to story ";
  story.setAttribute("data-oi-wired", "");
  close?.before(story);
  const onStory = (ev: Event) => {
    ev.preventDefault();
    const { handlers } = ctx;
    if (!handlers) return note(doc, story, SELECT_MODEL);
    if (!handlers.addVaultStory) return note(doc, story, READ_ONLY);
    if (story.disabled) return;
    const ids = draftOf(ctx).media_files.filter((m): m is number => typeof m === "number");
    if (ids.length !== 1) return note(doc, story, ONE_FOR_STORY, true);
    story.disabled = true;
    doc.getElementById("oi-note")?.remove();
    handlers
      .addVaultStory(vaultStoryBody(ids[0], ctx.vaultItems))
      .then(
        () => note(doc, story, "Added to story"),
        (e) => note(doc, story, `Could not add: ${message(e)}`, true),
      )
      .finally(() => (story.disabled = false));
  };
  story.addEventListener("click", onStory);
  const onClick = (ev: MouseEvent) => {
    const tab = (ev.target as Element | null)?.closest?.(VAULT_TABS);
    if (tab) {
      ev.preventDefault();
      const type = TYPES[tabs.indexOf(tab as HTMLElement)] ?? null;
      if (type === (view.type ?? null)) return;
      return ctx.handlers ? ctx.handlers.navigate(vaultHref({ list: view.list, type }, `/of-manager/${page}`)) : note(doc, tab, SELECT_MODEL);
    }
    const tile = (ev.target as Element | null)?.closest?.(VAULT_TILE);
    if (!tile) return;
    const id = Number(tile.getAttribute("data-oi-media"));
    // In the dialog's footer: a note in the grid would take a tile's place.
    if (!ctx.handlers || !id) return note(doc, doc.querySelector(".modal-footer a") ?? tile, SELECT_MODEL);
    const { media_files, thumbs } = draftOf(ctx);
    const at = media_files.indexOf(id);
    if (at < 0) {
      update({ media_files: [...media_files, id], thumbs: [...thumbs, tile.querySelector(".b-photos__item__img")?.getAttribute("src") ?? ""] });
    } else {
      update({ media_files: media_files.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
    }
    toggleTile(tile, at < 0);
  };
  doc.addEventListener("click", onClick);
  const unbindSearch = bindVaultSearch(doc);
  const unbindTools = bindVaultTools(doc, ctx, page);
  return () => {
    doc.removeEventListener("click", onClick);
    story.removeEventListener("click", onStory);
    story.remove();
    unbindSearch();
    unbindTools();
  };
}

/** OF's vault folder Sort (the Vault page's captured menu: sort default | name | recent | media | custom, and order). */
const FOLDER_SORTS = [
  { value: "default", label: "Default" },
  { value: "name", label: "Name" },
  { value: "recent", label: "Recent" },
  { value: "media", label: "Media" },
  { value: "custom", label: "Custom" },
];

/** The folder rows ofMirrorData drew (not "All media"), in the dialog's folder column. */
const folderRows = (doc: Document) => [...doc.querySelectorAll<HTMLElement>(".modal.show .l-sidebar-column .b-rows-lists__item[data-oi-data]")];
const folderName = (r: Element) => r.querySelector(".b-rows-lists__item__name")?.textContent?.trim() ?? "";

/** The folder rows by name in `order`, moved in place (OF's other sorts come back from the Relay, already in its order). */
export function sortFoldersByName(doc: Document, order: string): void {
  const rows = folderRows(doc);
  if (rows.length < 2) return;
  const dir = order === "asc" ? 1 : -1;
  const anchor = rows[0].previousSibling;
  const parent = rows[0].parentElement!;
  const sorted = [...rows].sort((a, b) => dir * folderName(a).localeCompare(folderName(b)));
  if (anchor) anchor.after(...sorted);
  else parent.prepend(...sorted);
}

/**
 * The vault dialog's own tools: the folder column's Search (a field in its header; typing, 400 ms after it stops, opens the
 * dialog with ?slist=, which ofMirrorData sends to GET /vault/lists as OF's `query`, as the Vault page's), the folder Sort (OF's menu; a pick sends OF's POST
 * /vault/lists/sort, and Name re-orders the rows at once) and the media Sort (OF's fields Recent, Most liked, Highest
 * tips, Buyers and the order: the dialog with ?field= and ?sort=, as the Vault page's). A chat's vault dialog has them
 * too (`stay` keeps its ?chat=). Returns an unbind.
 */
export function bindVaultTools(
  doc: Document,
  ctx: Pick<PostContext, "vaultView" | "folderSort"> & { handlers: Pick<PostHandlers, "navigate" | "sortFolders"> | null },
  page: string,
  stay: (href: string) => string = (href) => href,
): () => void {
  const view = ctx.vaultView ?? {};
  const side = doc.querySelector<HTMLElement>(".modal.show .l-sidebar-column");
  const folderSearch = side?.querySelector<HTMLButtonElement>(".g-page__header button[aria-label='Search']");
  const folderSort = side?.querySelector<HTMLButtonElement>("button[aria-label='Sort']");
  const mediaSort = [...doc.querySelectorAll<HTMLButtonElement>(".modal.show button[aria-label='Sort']")].find((b) => !side?.contains(b)) ?? null;
  const submit = doc.querySelector<HTMLButtonElement>(".modal.show .b-search-form button[type='submit']");
  for (const el of [folderSearch, folderSort, mediaSort, submit]) el?.setAttribute("data-oi-wired", "");
  // A chat's dialog comes greyed by the generator ("Not available in Inflowwww yet"): these tools run there too.
  const greyed = [folderSearch, folderSort, mediaSort, submit].filter((b): b is HTMLButtonElement => !!b?.disabled);
  const tips = greyed.map((b) => b.getAttribute("title"));
  for (const b of greyed) {
    b.disabled = false;
    b.removeAttribute("title");
  }
  // The media column's title names its sort (OF's "Recent", "Most liked", …), as the Vault page's.
  const mediaTitle = mediaSort?.closest(".b-content-filter")?.querySelector(".b-content-filter__title");
  const wasTitle = mediaTitle?.textContent ?? null;
  if (mediaTitle) mediaTitle.textContent = FIELDS[view.field ?? "recent"] ?? "Recent";
  const sorted = { sort: ctx.folderSort?.sort ?? "default", order: ctx.folderSort?.order ?? "desc" };
  let field: HTMLInputElement | null = null;
  let timer = 0;
  const win = doc.defaultView;
  const search = (q: string | null) => ctx.handlers?.navigate(stay(vaultHref({ ...view, slist: q }, `/of-manager/${page}`)));
  const openSearch = () => {
    if (field || !folderSearch) return;
    field = doc.createElement("input");
    field.type = "search";
    field.maxLength = 100;
    field.placeholder = "Search...";
    field.setAttribute("aria-label", "Search folders");
    field.className = "b-search-form__input form-control";
    field.style.cssText = "flex:1;min-width:0;margin:0 8px;height:32px";
    field.setAttribute("data-oi-wired", "");
    field.value = view.slist ?? "";
    field.addEventListener("input", () => {
      win?.clearTimeout(timer);
      timer = win?.setTimeout(() => search(field?.value.trim() || null), 400) ?? 0;
    });
    folderSearch.closest(".b-btns-group")?.before(field);
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  };
  if (view.slist) openSearch();
  const onClick = (ev: MouseEvent) => {
    const b = (ev.target as Element | null)?.closest?.("button");
    if (!b) return;
    if (b === folderSearch) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      if (!field) return openSearch();
      field.remove();
      field = null;
      if (view.slist) search(null);
      return;
    }
    if (b === folderSort) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      const { handlers } = ctx;
      showMenu(doc, b, [{ name: "sort", value: sorted.sort, options: FOLDER_SORTS }, ORDER_GROUP(sorted.order)], (g, v) => {
        Object.assign(sorted, { [g]: v });
        if (sorted.sort === "name") sortFoldersByName(doc, sorted.order);
        if (!handlers.sortFolders) return note(doc, b, READ_ONLY);
        handlers.sortFolders(sorted.sort, sorted.order).catch((e) => note(doc, b.closest(".b-content-filter") ?? b, `Could not sort: ${message(e)}`, true));
      });
      return;
    }
    if (b === mediaSort) {
      ev.preventDefault();
      if (!ctx.handlers) return note(doc, b, SELECT_MODEL);
      const { handlers } = ctx;
      const fields = Object.entries(FIELDS).map(([value, label]) => ({ value, label }));
      showMenu(doc, b, [{ name: "field", value: view.field ?? "recent", options: fields }, ORDER_GROUP(view.sort ?? "desc")], (g, v) => {
        const next = g === "field" ? { ...view, field: v === "recent" ? null : v } : { ...view, sort: v === "asc" ? "asc" : null };
        handlers.navigate(stay(vaultHref(next, `/of-manager/${page}`)));
      });
    }
  };
  doc.addEventListener("click", onClick);
  return () => {
    win?.clearTimeout(timer);
    doc.removeEventListener("click", onClick);
    field?.remove();
    if (mediaTitle && wasTitle !== null) mediaTitle.textContent = wasTitle;
    greyed.forEach((b, i) => {
      b.disabled = true;
      if (tips[i] !== null) b.setAttribute("title", tips[i]!);
    });
    closeMenu(doc);
  };
}

/**
 * Wire OF's "Add media" (any composer page, a chat's too: `media` reads its draft's picks): a click opens a hidden one-file image/video picker (All-Creators scope: the
 * select-a-model note). The picked file uploads at once; an accepted upload's `send_with` is appended to the draft's
 * `media_files` (`mergeSendWith`), each entry with a thumb from the file's object URL, made in the app's window (the
 * frame's document is replaced on every State page). The picker is cleared so the same file can be picked again, and
 * further picks are allowed while one uploads; `uploading` is told when each upload starts (+1) and settles (-1).
 * A refused upload (`ready` not true) or a thrown one shows a red "Could not upload: …" note and attaches nothing.
 * Returns an unbind, which removes the picker.
 */
export function bindAddMedia(
  doc: Document,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => Pick<PostDraft, "media_files" | "thumbs">,
  update: (patch: Pick<PostDraft, "media_files" | "thumbs">) => void,
  uploading: (n: 1 | -1) => void,
  /** The note when nothing can be sent (`ctx.handlers` null): All-Creators scope's by default. */
  none: string = SELECT_MODEL,
  /** What the picker takes (a chat's: one image or video; New post's: POST_PICK). */
  pick: { accept: string; multiple: boolean } = { accept: "image/*,video/*", multiple: false },
  /** Told of each attached file (a chat counts its voice notes by MIME). */
  done?: (file: File) => void,
): () => void {
  const button = doc.querySelector(ADD_MEDIA);
  if (!button) return () => {};
  const { handlers } = ctx;
  const input = doc.createElement("input");
  input.type = "file";
  input.accept = pick.accept;
  input.multiple = pick.multiple;
  input.hidden = true;
  input.setAttribute("data-oi-wired", ""); // the field whose file Add media sends: not bindWrites' change path
  doc.body.append(input);
  button.setAttribute("data-oi-wired", "");

  const onClick = (ev: Event) => {
    ev.preventDefault();
    if (handlers) input.click();
    else note(doc, button, none);
  };
  const take = mediaTaker(doc, button, ctx, media, update, uploading, done);
  const onChange = () => {
    // The File comes from the frame's realm: no `instanceof File` on it.
    const files = [...(input.files ?? [])];
    input.value = "";
    take(files);
  };
  button.addEventListener("click", onClick);
  input.addEventListener("change", onChange);
  return () => {
    button.removeEventListener("click", onClick);
    input.removeEventListener("change", onChange);
    input.remove();
  };
}

/**
 * Add media's upload of `files` (a pick, a drop, a recording): each file goes to POST /api/of/v2/upload, one after
 * another (the draft keeps their order), and an accepted upload's `send_with` is appended to the draft's `media_files`
 * with a thumb from the file's object URL; `done` is told of each attached file. Every file counts as in flight
 * (`uploading`) from the start. A refused or failed upload shows a red "Could not upload: …" note after `anchor` and
 * attaches nothing. No `ctx.handlers` (or no files): nothing is sent.
 */
export function mediaTaker(
  doc: Document,
  anchor: Element,
  ctx: { handlers: Pick<PostHandlers, "upload"> | null; accountId: string | null },
  media: () => Pick<PostDraft, "media_files" | "thumbs">,
  update: (patch: Pick<PostDraft, "media_files" | "thumbs">) => void,
  uploading: (n: 1 | -1) => void,
  done?: (file: File) => void,
): (files: File[]) => void {
  const send = (file: File) =>
    ctx
      .handlers!.upload(file)
      .then(
        ({ ready, send_with, note: why }) => {
          if (ready !== true) return note(doc, anchor, `Could not upload: ${why || "upload not ready"}`, true);
          if (!send_with.length) return;
          const { media_files, thumbs } = media();
          const thumb = proxyImage(URL.createObjectURL(file), ctx.accountId);
          update({ media_files: mergeSendWith(media_files, send_with), thumbs: [...thumbs, ...send_with.map(() => thumb)] });
          done?.(file);
        },
        (e) => note(doc, anchor, `Could not upload: ${message(e)}`, true),
      )
      .finally(() => uploading(-1));
  return (files) => {
    if (!files.length || !ctx.handlers) return;
    // Every file counts as in flight at once (Post waits for all); they upload one after another.
    files.forEach(() => uploading(1));
    let chain: Promise<unknown> | null = null;
    for (const file of files) chain = chain ? chain.then(() => send(file)) : send(file);
  };
}

/**
 * The Format text panel (new-post/state-format-text, OF's TextEditorToolbar): Bold, Italic and Clear Formatting format
 * the editor's selection; Text Color and Text Size open OF's lists (ofMirrorMenu) and format it with the picked one.
 * The editor then holds OF's own markup (ofMirrorFormat), which is the post's text (bindPost saves it as the draft's
 * `html`). A press on the panel keeps the editor's selection; with nothing selected a tool says "Select some text to
 * format". All-Creators: the select-a-model note. Returns an unbind.
 */
const bindFormat: DialogBinder = (doc, ctx) => {
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const panel = doc.querySelector<HTMLElement>(FORMAT);
  if (!editor || !panel) return () => {};
  return bindFormatPanel(doc, editor, panel, () => (ctx.handlers ? null : SELECT_MODEL));
};

/** OF's Format text `panel` over `editor` (New post's dialog, a chat's composer); `blocked`: the note when no write may be made. */
export function bindFormatPanel(doc: Document, editor: HTMLElement, panel: HTMLElement, blocked: () => string | null): () => void {
  const tool = (label: string) => panel.querySelector<HTMLElement>(`[aria-label='${label}']`);
  const size = tool("Text Size");
  const color = tool("Text Color");
  for (const el of panel.querySelectorAll("button, .v-input, .v-input__slot, input")) el.setAttribute("data-oi-wired", "");
  let saved: Range | null = null;
  const onSelection = () => {
    const sel = doc.getSelection();
    if (sel?.rangeCount && editor.contains(sel.getRangeAt(0).commonAncestorContainer)) saved = sel.getRangeAt(0).cloneRange();
  };
  const apply = (cmd: FormatCommand) => {
    const why = blocked();
    if (why) return note(doc, panel, why);
    if (saved) {
      editor.focus();
      const sel = doc.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(saved);
    }
    if (!applyFormat(editor, cmd)) return note(doc, panel, "Select some text to format");
    onSelection();
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const onDown = (ev: MouseEvent) => {
    const t = ev.target as Element | null;
    if (t?.closest && panel.contains(t) && !t.closest("a[href]")) ev.preventDefault();
  };
  const onClick = (ev: MouseEvent) => {
    const t = (ev.target as Element | null)?.closest?.<HTMLElement>("[aria-label]");
    if (!t || !panel.contains(t)) return;
    const label = t.getAttribute("aria-label");
    if (label === "Bold" || label === "Italic" || label === "Clear Formatting") {
      ev.preventDefault();
      return apply({ kind: label === "Bold" ? "bold" : label === "Italic" ? "italic" : "clear" });
    }
    if (label === "Text Color" && color) {
      ev.preventDefault();
      const options = COLORS.map((c) => ({ value: c.cls, label: c.label, className: c.cls }));
      showMenu(doc, color, [{ name: "color", radio: false, options }], (_, cls) => {
        apply({ kind: "color", cls });
        const swatch = color.querySelector(".b-text-colour");
        if (swatch) swatch.className = `b-text-colour ${cls}`;
      });
      return;
    }
    if (label === "Text Size" && size) {
      ev.preventDefault();
      const shown = size.querySelector(".v-select__selection");
      const current = SIZES.find((x) => x.label === shown?.textContent?.trim())?.cls ?? "m-editor-fs__default";
      const options = SIZES.map((x) => ({ value: x.cls, label: x.label, className: x.cls }));
      showMenu(doc, size, [{ name: "size", radio: false, value: current, options }], (_, cls) => {
        apply({ kind: "size", cls });
        if (shown) shown.textContent = SIZES.find((x) => x.cls === cls)?.label ?? "Default";
      });
    }
  };
  doc.addEventListener("selectionchange", onSelection);
  doc.addEventListener("mousedown", onDown);
  doc.addEventListener("click", onClick);
  return () => {
    doc.removeEventListener("selectionchange", onSelection);
    doc.removeEventListener("mousedown", onDown);
    doc.removeEventListener("click", onClick);
    closeMenu(doc);
  };
}

/** The composer tools Home's composer shares with New post: each a State page of both (home/<state>, new-post/<state>). */
const SHARED_DIALOGS: Record<string, DialogBinder> = {
  [VOTING_PAGES[1]]: bindVoting(1),
  [VOTING_PAGES[2]]: bindVoting(2),
  [PERIOD_PAGE]: bindPeriod,
  "state-target": bindValueDialog("fund_raising_target", TARGET, readTarget),
  "state-format-text": bindFormat,
};

/** new-post/state-* (and Home's copies of most of them) page -> its dialog's binding. */
const DIALOGS: Record<string, DialogBinder> = {
  "new-post/state-schedule": bindSchedule,
  [HOME_SCHEDULE]: bindSchedule,
  [TAG_PAGE]: bindTags,
  [HOME_TAGS]: bindTags,
  [VAULT_DIALOG]: bindVault,
  [HOME_VAULT]: bindVault,
  [LABEL_PAGE]: bindLabels,
  [PRICE_PAGE]: bindPrice,
  ...Object.fromEntries(Object.entries(SHARED_DIALOGS).flatMap(([state, bind]) => [[`new-post/${state}`, bind], [`home/${state}`, bind]])),
};

/** A tool OF disables (`on`) or enables again: a mirror link takes no click while disabled. */
export function lock(el: HTMLElement, on: boolean): void {
  el.toggleAttribute("disabled", on);
  el.setAttribute("aria-disabled", String(on));
  el.style.pointerEvents = on ? "none" : "";
  el.style.opacity = on ? "0.4" : "";
}

/**
 * OF's toast (its `.toasts-host`, made when the page has none, and a `v-snack m-alert` without a timer bar) saying `text`;
 * it goes after TOAST_MS. Returns the toast.
 */
export function toast(doc: Document, text: string): HTMLElement {
  let host = doc.querySelector<HTMLElement>(".toasts-host");
  if (!host) {
    host = doc.createElement("div");
    host.className = "toasts-host w-100 h-100 d-flex flex-column-reverse justify-content-start";
    host.style.cssText = "top:0;left:0";
    doc.body.append(host);
  }
  const snack = doc.createElement("div");
  snack.className = "v-snack v-snack--active v-snack--bottom v-snack--has-background m-alert";
  snack.id = "oi-toast";
  snack.innerHTML = '<div class="v-snack__wrapper v-sheet theme--dark"><div role="status" aria-live="polite" class="v-snack__content m-without-timer"><div class="toast__body"><div class="toast__content"><div class="toast__text"></div></div></div></div></div>';
  snack.querySelector(".toast__text")!.textContent = text;
  doc.getElementById("oi-toast")?.remove();
  host.append(snack);
  doc.defaultView?.setTimeout(() => snack.remove(), TOAST_MS);
  return snack;
}

/** How long a carried toast waits for its page's document (it never shows late, on a page opened again). */
export const CARRY_MS = 15_000;
/** A toast carried over a navigation: the mirror page it shows on, the one it was carried from, its text and expiry. */
let carried: { page: string; from: string | null; text: string; until: number } | null = null;
/** A document's mirror page, its path under of-mirror/pages; null for about:blank (a new frame's placeholder). */
const docPage = (doc: Document) => mirrorPageOfPath(doc.location?.pathname ?? "");

/**
 * OF's toast `text`, carried to the page an /of-manager `href` opens (its mirror page, as the route maps it: the section
 * root is its index page). `current` (the frame's document now) already that page: the toast shows at once and this
 * returns true (nothing to navigate); so does an empty `href` (no destination: it shows where the user is). Else it waits
 * CARRY_MS for that page's bind (takeCarried).
 */
function carryToast(current: Document | null | undefined, href: string, text: string): boolean {
  const page = mirrorPageOfHref(href);
  const here = current ? docPage(current) : null;
  if (current?.body && (!href || (page !== null && here === page))) return toast(current, text), true;
  carried = page ? { page, from: here, text, until: Date.now() + CARRY_MS } : null;
  return false;
}

/**
 * A binder's first step on `doc`: the carried toast shows if `doc` is its page. about:blank and the page it was carried
 * from (a rebind there while the frame loads) keep it; any other page, or its expiry, drops it.
 */
export function takeCarried(doc: Document): void {
  const here = docPage(doc);
  if (!carried || !here) return;
  const live = Date.now() < carried.until;
  if (live && here === carried.from) return;
  if (live && here === carried.page) toast(doc, carried.text);
  carried = null;
}

/** A binder's navigate(href, toast?) for the frame: `toast` carried to href's page (carryToast), and router.push unless it is there already. */
export const frameNavigate =
  (frameRef: RefObject<HTMLIFrameElement | null>, push: (href: string) => void) =>
  (href: string, text?: string): void => {
    if (!text || !carryToast(frameRef.current?.contentDocument, href, text)) push(href);
  };

/** The composer's Record video and Record voice buttons, and their popup. */
const RECORD = "button.b-chat__video-record-btn, button[aria-label='Record voice']";
const RECORD_POPUP = "oi-record-popup";
export const RECORD_TEXT = "Recording isn't supported here. Use OnlyFans in your real browser. (I am a lazy dev.)";

/** A small OF dialog saying recording is not supported here, with an OK that closes it (as does its backdrop). */
export function recordPopup(doc: Document, closed?: () => void): HTMLElement {
  doc.getElementById(RECORD_POPUP)?.remove();
  const root = doc.createElement("div");
  root.id = RECORD_POPUP;
  root.setAttribute("data-oi-wired", "");
  root.innerHTML =
    '<div class="modal fade show" role="dialog" aria-modal="true" style="display:block;z-index:1050">' +
    '<div class="modal-dialog modal-sm modal-dialog-centered"><div class="modal-content">' +
    '<div class="modal-body"><p class="m-break-word" style="margin:16px 0 0"></p></div>' +
    '<div class="modal-footer"><button type="button" class="g-btn m-flat m-btn-gaps m-reset-width" data-oi-wired="" data-oi-ok=""> OK </button></div>' +
    '</div></div></div><div class="modal-backdrop fade show" data-oi-ok="" style="z-index:1040"></div>';
  root.querySelector("p")!.textContent = RECORD_TEXT;
  root.addEventListener("click", (ev) => {
    if (!(ev.target as Element).closest("[data-oi-ok]")) return;
    root.remove();
    closed?.();
  });
  doc.body.append(root);
  root.querySelector<HTMLButtonElement>("[data-oi-ok]")?.focus();
  return root;
}

/** The right column's search box (OF's "Search users or posts"), its submit, and the results list under it. */
const FEED_SEARCH = "input[name='feed-search-input']";
const SEARCH_RESULTS = "oi-search-results";

/** Where a search result opens (userHref): a user's OF profile; a post, My profile when it is the model's own, else its
 *  author's OF profile. */
export function searchHref(kind: "user" | "post", item: SearchUser | SearchPost, meId?: number | string): string | null {
  const me = meId == null ? null : String(meId);
  return kind === "user" ? userHref(item as SearchUser, me) : userHref((item as SearchPost).author, me);
}

/** A search response's rows: a bare array, or OF's `{list}` / `{items}`. */
const rowsIn = <T,>(r: unknown): T[] => (Array.isArray(r) ? (r as T[]) : ((r as { list?: T[]; items?: T[] } | null)?.list ?? (r as { items?: T[] } | null)?.items ?? []));

/**
 * Wire the right column's search (New post's and Home's): typing (400 ms after it stops) runs OF's users search and posts
 * search, and a list under the box shows "Users" and "Posts" rows, each a link to its OF profile or My profile (searchHref); the
 * submit (Enter or the search button) runs it at once and never reloads the frame; an empty box clears the list.
 * All-Creators: the select-a-model note. Returns an unbind.
 */
function bindFeedSearch(doc: Document, ctx: PostContext): () => void {
  const input = doc.querySelector<HTMLInputElement>(FEED_SEARCH);
  if (!input) return () => {};
  const form = input.closest("form");
  const submit = form?.querySelector<HTMLButtonElement>("button[type='submit']") ?? null;
  for (const el of [input, submit, form]) el?.setAttribute("data-oi-wired", "");
  let timer = 0;
  let asked = "";
  const win = doc.defaultView;
  const results = () => doc.getElementById(SEARCH_RESULTS);
  const draw = (users: SearchUser[], posts: SearchPost[]) => {
    results()?.remove();
    const box = doc.createElement("div");
    box.id = SEARCH_RESULTS;
    box.setAttribute("data-oi-wired", "");
    box.className = "b-rows-lists";
    box.style.cssText = "padding:4px 0;font-size:14px;line-height:20px";
    const head = (text: string) => {
      const h = doc.createElement("div");
      h.className = "g-gray-text g-text-uppercase";
      h.style.cssText = "padding:8px 16px 4px;font-size:12px";
      h.textContent = text;
      return h;
    };
    const link = (href: string | null, text: string) => {
      const a = doc.createElement("a");
      a.className = "b-rows-lists__item__text m-with-rectangle-hover g-text-ellipsis";
      a.style.cssText = "display:block;padding:6px 16px";
      a.textContent = text;
      if (href) linkUser([a], href);
      else a.setAttribute("aria-disabled", "true");
      return a;
    };
    if (!users.length && !posts.length) box.append(head("Nothing found"));
    // OF's names and texts come HTML-escaped (and a post's text as markup): shown as text.
    if (users.length) box.append(head("Users"), ...users.map((u) => link(searchHref("user", u, ctx.meId), `${plain(u.name)}${u.username ? ` @${u.username}` : ""}`.trim())));
    if (posts.length) {
      box.append(
        head("Posts"),
        ...posts.map((p) => {
          const text = plain((p.rawText ?? p.text ?? "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").slice(0, 80) || "Post";
          const by = p.author?.username ? ` · @${p.author.username}` : "";
          return link(searchHref("post", p, ctx.meId), `${text}${by}`);
        }),
      );
    }
    (form ?? input).after(box);
  };
  const run = (q: string) => {
    const { handlers } = ctx;
    if (!q) return results()?.remove();
    if (!handlers) return note(doc, input, SELECT_MODEL);
    if (!handlers.searchUsers || !handlers.searchPosts) return note(doc, input, READ_ONLY);
    asked = q;
    Promise.allSettled([handlers.searchUsers(q), handlers.searchPosts(q)]).then(([u, p]) => {
      if (asked !== q) return;
      draw(u.status === "fulfilled" ? rowsIn<SearchUser>(u.value) : [], p.status === "fulfilled" ? rowsIn<SearchPost>(p.value) : []);
      if (u.status === "rejected" && p.status === "rejected") note(doc, input, `Could not search: ${message(u.reason)}`, true);
    });
  };
  const onInput = (ev: Event) => {
    if (ev.target !== input) return;
    if (submit) submit.disabled = !input.value.trim();
    win?.clearTimeout(timer);
    const q = input.value.trim();
    timer = win?.setTimeout(() => run(q), 400) ?? 0;
  };
  const onSubmit = (ev: Event) => {
    if (ev.target !== form) return;
    ev.preventDefault();
    win?.clearTimeout(timer);
    run(input.value.trim());
  };
  doc.addEventListener("input", onInput);
  doc.addEventListener("submit", onSubmit);
  return () => {
    win?.clearTimeout(timer);
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("submit", onSubmit);
    results()?.remove();
  };
}

/**
 * Wire the composer of a new-post Mirror page (`page`: its path under of-mirror/pages, e.g.
 * "new-post/index" or "new-post/state-schedule") in `doc`. Returns an unbind.
 */
export function bindPost(doc: Document, page: string, given: PostContext): () => void {
  // Home's composer posts in place, and its dialogs (Home's own State pages) return to Home.
  const home = page.startsWith("home/");
  const ctx: PostContext = { ...given, composer: home ? HOME : COMPOSER };
  const { handlers } = ctx;
  const editor = doc.querySelector<HTMLElement>(EDITOR);
  const post = doc.querySelector<HTMLButtonElement>(POST);
  if (!editor || !post) return () => {};
  const keep = keepOf(ctx);
  post.setAttribute("data-oi-wired", "");

  /** A Co-tag's name from the Relay's list, else its id. */
  const tagName = (id: number) => {
    const u = ctx.tagItems?.map(toChoice).find((t) => t.id === id);
    return u ? u.name : String(id);
  };
  /** The picked labels' names from the Relay's list ("Summer, Beach"); null while any is unknown (the summary counts them). */
  const labelNames = (ids: number[]) => {
    const names = ids.map((id) => ctx.labelItems?.find((l) => Number(l.id) === id)?.name);
    return names.every(Boolean) ? names.join(", ") : null;
  };
  /** "Scheduled for … · Tagged: … · Poll: … · Clear" under the editor while the draft has extras (note's grey, persistent). */
  const summary = () => {
    const { posted_at: at, save_for_later: later, tagged_users: tags, voting, voting_due: due, expire_days: days, fund_raising_target: target, label_ids: labels, price, edit_id: editing } = draftOf(ctx);
    // OF's tools a price rules out (and the price button while they are set).
    for (const el of doc.querySelectorAll<HTMLElement>(NOT_WITH_PRICE)) lock(el, !!price);
    const priceBtn = doc.querySelector<HTMLElement>(PRICE_BTN);
    if (priceBtn) lock(priceBtn, !!(days || target));
    const parts = [
      ...(editing ? [later ? EDITING_LATER : EDITING] : []),
      ...(price ? [`Price: ${ofPrice(price)}`] : []),
      ...(later ? ["Saved for later"] : at ? [`Scheduled for ${when(wallClock(new Date(at), ctx.zone))}`] : []),
      ...(tags.length ? [`Tagged: ${tags.map(tagName).join(", ")}`] : []),
      ...(voting ? [`${voting.type === 2 ? "Quiz" : "Poll"}: ${voting.options.filter((o) => o.trim()).length} options${due === undefined ? "" : `, ${daysText(due)}`}`] : []),
      ...(days ? [`Expires after ${days} ${days === 1 ? "day" : "days"}`] : []),
      ...(target ? [`Target: ${ofPrice(target)}`] : []),
      ...(labels?.length ? [`Labels: ${labelNames(labels) ?? labels.length}`] : []),
    ];
    schedulePill(doc, editor, editing ? (later ? "Saved for later" : at ? when(wallClock(new Date(at), ctx.zone)) : null) : null);
    const old = doc.getElementById("oi-post-summary");
    if (!parts.length) return old?.remove();
    const el = old ?? doc.createElement("div");
    el.id = "oi-post-summary";
    el.style.cssText = NOTE_STYLE;
    el.style.color = GREY;
    const clear = doc.createElement("a");
    clear.href = "#";
    clear.textContent = "Clear";
    clear.setAttribute("data-oi-wired", "");
    clear.setAttribute("data-oi-clear", "");
    el.replaceChildren(`${parts.join(" · ")} · `, clear);
    // Editing a queued post: Discard drops the whole draft (the queued post stays as it is).
    if (editing) {
      const discard = doc.createElement("a");
      discard.href = "#";
      discard.textContent = "Discard";
      discard.setAttribute("data-oi-wired", "");
      discard.setAttribute("data-oi-discard", "");
      el.append(" · ", discard);
    }
    if (!old) (editor.closest(".g-input__wrapper") ?? editor).after(el);
  };
  /**
   * The draft's picked media as one row of 64px squares directly before the actions bar, in click order: each OF's vault
   * tile picture markup with the draft's thumb as its src. A picture that fails to load (a video, or a `blob:` URL dead
   * after a full reload) leaves a plain square in OF's grey; its media stays in the draft. Each square's X drops that
   * file. Rebuilt from the draft; no row while nothing is picked.
   */
  const media = () => {
    doc.getElementById(THUMBS_ROW)?.remove();
    const { thumbs } = draftOf(ctx);
    const actions = doc.querySelector(".b-make-post__actions");
    if (!thumbs.length || !actions) return;
    const row = doc.createElement("div");
    row.id = THUMBS_ROW;
    row.dataset.oiData = "";
    row.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px";
    row.append(
      ...thumbs.map((src, at) => {
        const item = doc.createElement("div");
        item.className = "b-photos__item";
        item.style.cssText = "position:relative;width:64px;height:64px;flex:none;border-radius:6px;overflow:hidden";
        const img = doc.createElement("img");
        img.alt = "";
        img.className = "b-photos__item__img";
        img.addEventListener("error", () => {
          img.remove();
          item.style.background = GREY;
        });
        img.src = src;
        // OF's X on an attached file's preview: it drops that file from the post.
        const remove = doc.createElement("button");
        remove.type = "button";
        remove.className = "b-dropzone__preview__delete g-btn m-rounded m-reset-width m-thumb-r-corner-pos m-btn-remove m-sm-icon-size";
        remove.style.cssText = "position:absolute;top:4px;right:4px;z-index:1";
        remove.setAttribute("aria-label", "Delete");
        remove.setAttribute("data-oi-wired", "");
        remove.dataset.oiRemoveMedia = String(at);
        remove.innerHTML = `<svg data-icon-name="icon-close" aria-hidden="true" class="g-icon"><use href="#icon-close" xlink:href="#icon-close"></use></svg>`;
        item.append(img, remove);
        return item;
      }),
    );
    actions.before(row);
  };
  /** Save `patch` onto this scope's draft (none is kept in All-Creators scope) and show it in the summary and the media row. */
  const update = (patch: Partial<PostDraft>) => {
    if (keep) saveDraft(keep.storage, keep.accountId, { ...draftOf(ctx), ...patch });
    summary();
    if (patch.thumbs) media();
    if (patch.media_files) sync(textOf(editor));
  };

  /** Add media's uploads in flight (an earlier bind's may still be running). */
  const flight = ctx.uploads ?? { count: 0 };
  /**
   * OF's placeholder marks follow the editor's text; Post is enabled while there is text or media and no upload is in
   * flight, and a disabled Post says why (its tooltip).
   */
  const sync = (text: string) => {
    editor.setAttribute("data-is-empty", String(!text));
    editor.closest(".g-input__wrapper")?.classList.toggle("m-empty", !text);
    const why = flight.count > 0 ? UPLOADING : !text.trim() && !draftOf(ctx).media_files.length ? EMPTY_TEXT : "";
    post.disabled = !!why;
    if (why) post.title = why;
    else post.removeAttribute("title");
  };
  /** Redraw this bind from the saved draft: Post state and the media row (an earlier bind's upload may have saved to it). */
  const refresh = () => {
    sync(textOf(editor));
    media();
  };
  flight.refresh = refresh;
  /** An upload started (+1) or settled (-1): the current bind is refreshed from the saved draft. */
  const uploading = (n: 1 | -1) => {
    flight.count += n;
    flight.refresh?.();
  };

  /** The editor shows `text`, one <p> per line, or the draft's formatted `html` (OF's markup). */
  const show = (text: string, html?: string) => {
    if (html) setOfHtml(editor, html);
    else
      editor.replaceChildren(
        ...text.split("\n").map((line) => {
          const p = doc.createElement("p");
          p.append(line || doc.createElement("br"));
          return p;
        }),
      );
    sync(text);
  };
  /** The editor's formatted text as OF's markup, or undefined while it has no formatting. */
  const html = () => (hasFormatting(editor) ? ofHtml(editor) : undefined);
  // OF shows the price button only where a post can have a price (postPriceLimits).
  const priceBtn = doc.querySelector<HTMLElement>(PRICE_BTN);
  if (priceBtn) priceBtn.style.display = ctx.priceLimits ? "" : "none";
  // Which model New post's Post goes to, by the button (All models posts as the model the page shows).
  doc.getElementById(POST_AS)?.remove();
  if (ctx.postAs && !home) {
    const as = doc.createElement("span");
    as.id = POST_AS;
    as.textContent = `as ${ctx.postAs}`;
    as.style.cssText = `color:${GREY};font-size:13px;margin-right:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px`;
    post.before(as);
  }
  // This scope's draft (a rebind after a scope change replaces the other scope's text).
  show(draftOf(ctx).text, draftOf(ctx).html);
  summary();
  media();

  const onInput = (ev: Event) => {
    if (!(ev.target as Element | null)?.closest?.(EDITOR)) return;
    const text = textOf(editor);
    sync(text);
    update({ text, html: html() });
  };

  const onClick = (ev: MouseEvent) => {
    const target = ev.target as Element | null;
    if (!target?.closest) return;
    if (target.closest("[data-oi-clear]")) {
      ev.preventDefault();
      return update(NO_EXTRAS);
    }
    const remove = target.closest<HTMLElement>("[data-oi-remove-media]");
    if (remove) {
      ev.preventDefault();
      const at = Number(remove.dataset.oiRemoveMedia);
      const { media_files, thumbs } = draftOf(ctx);
      return update({ media_files: media_files.filter((_, i) => i !== at), thumbs: thumbs.filter((_, i) => i !== at) });
    }
    if (target.closest("[data-oi-discard]")) {
      ev.preventDefault();
      if (keep) clearDraft(keep.storage, keep.accountId);
      show("");
      summary();
      return media();
    }
    if (target.closest(POST) !== post) return;
    ev.preventDefault();
    if (!handlers) return note(doc, post, SELECT_MODEL);
    if (post.disabled) return;
    const body = collectPost(textOf(editor), { ...draftOf(ctx), html: html() });
    if (typeof body === "string") return note(doc, post, body, true);
    const editing = draftOf(ctx).edit_id;
    // An edited post with no date and not saved for later goes out at once: OF asks too (confirm_post_right_now).
    if (editing && !body.posted_at && !body.save_for_later && !(handlers.confirm?.(PUBLISH_EDITED) ?? false)) return;
    post.disabled = true;
    doc.getElementById("oi-note")?.remove();
    (editing && handlers.editPost ? handlers.editPost(editing, body) : handlers.createPost(body)).then(
      () => {
        if (keep) clearDraft(keep.storage, keep.accountId);
        // Saving an edited queued post goes back to where it is listed, as OF's (the queue, or saved for later).
        // (OF opens the queue on the post's day: /my/queue/<yyyy-mm-dd>.)
        if (editing) return handlers.navigate(body.save_for_later ? SFL_POSTS : `${QUEUE}?date=${localIso(wallClock(new Date(body.posted_at!), ctx.zone)).slice(0, 10)}`);
        // The composer empties in place, OF's toast says what happened, and the Creator's reads (Home's feed, the
        // Scheduled events, the queue) are fetched again.
        show("");
        summary();
        media();
        // An open poll or quiz panel empties too: its options went with the post, and the draft no longer has them.
        for (const input of doc.querySelectorAll<HTMLInputElement>(`${VOTE_ROW} ${OPTION}`)) input.value = "";
        for (const r of doc.querySelectorAll<HTMLInputElement>(`${VOTE_ROW} input[type='radio']`)) r.checked = false;
        const due = doc.querySelector(`${VOTING_PIECE} .b-post-piece__value`);
        if (due) due.textContent = daysText(VOTING_DAYS);
        handlers.posted?.();
        toast(doc, body.save_for_later ? SAVED_TOAST : body.posted_at ? `${SCHEDULED_TOAST} ${when(wallClock(new Date(body.posted_at), ctx.zone))}` : POSTED_TOAST);
      },
      (e) => {
        sync(textOf(editor));
        note(doc, post, `Could not ${editing ? "save" : "post"}: ${message(e)}`, true);
      },
    );
  };

  // A poll's duration opens the period dialog only straight from its panel.
  if (!page.endsWith(`/${PERIOD_PAGE}`) && draftOf(ctx).period_for) update({ period_for: undefined });
  const unbindDialog = Object.hasOwn(DIALOGS, page) ? DIALOGS[page](doc, ctx, update, page) : () => {};
  // New post's Record video and Record voice: OF records in the browser, which the mirror does not (the popup says so).
  const records = home ? [] : [...doc.querySelectorAll<HTMLButtonElement>(RECORD)];
  for (const b of records) b.setAttribute("data-oi-wired", "");
  const onRecord = (ev: Event) => {
    ev.preventDefault();
    const b = ev.currentTarget as HTMLButtonElement;
    b.setAttribute("aria-expanded", "true");
    recordPopup(doc, () => b.removeAttribute("aria-expanded"));
  };
  for (const b of records) b.addEventListener("click", onRecord);
  const unbindSearch = bindFeedSearch(doc, ctx);
  // Every composer page: the State pages' toolbar sits under their panel, and OF's Add media works there too.
  const unbindAddMedia = bindAddMedia(doc, ctx, () => draftOf(ctx), update, uploading, SELECT_MODEL, POST_PICK);
  const unbindOverflow = bindActionsOverflow(doc);
  doc.addEventListener("input", onInput);
  doc.addEventListener("click", onClick);
  return () => {
    if (flight.refresh === refresh) flight.refresh = undefined;
    doc.getElementById(POST_AS)?.remove();
    for (const b of records) b.removeEventListener("click", onRecord);
    doc.getElementById(RECORD_POPUP)?.remove();
    unbindSearch();
    unbindDialog();
    unbindAddMedia();
    unbindOverflow();
    doc.removeEventListener("input", onInput);
    doc.removeEventListener("click", onClick);
  };
}

const MORE_ACTIONS = "oi-actions-more";

/**
 * The composer toolbar on a narrow screen, as OF's MakeFeedPost resize(): while the row of action buttons is wider than
 * the composer, its last button moves into a More menu (OF's icon-more dropdown), one at a time, and comes back once
 * there is room. A More row clicks the button it stands for. Re-run on every resize (a ResizeObserver on the composer).
 * Returns an unbind, which puts every button back.
 */
export function bindActionsOverflow(doc: Document): () => void {
  const actions = doc.querySelector<HTMLElement>(".b-make-post__actions");
  const btns = actions?.querySelector<HTMLElement>(".b-make-post__actions__btns");
  const box = actions?.parentElement;
  if (!actions || !btns || !box) return () => {};
  const more = doc.createElement("button");
  more.type = "button";
  more.id = MORE_ACTIONS;
  more.className = "g-btn m-with-round-hover m-icon m-icon-only m-gray m-sm-size has-tooltip";
  more.setAttribute("aria-label", "More");
  more.setAttribute("aria-haspopup", "true");
  more.setAttribute("data-oi-wired", "");
  more.innerHTML = '<svg class="g-icon" aria-hidden="true"><use href="#icon-more" xlink:href="#icon-more"></use></svg>';
  const moved = () => [...btns.querySelectorAll<HTMLElement>(":scope > [data-oi-overflow]")];
  const restore = () => {
    for (const b of moved()) {
      b.style.display = "";
      b.removeAttribute("data-oi-overflow");
    }
    more.remove();
  };
  const layout = () => {
    closeMenu(doc);
    restore();
    if (actions.offsetWidth <= box.clientWidth) return;
    btns.append(more);
    const shown = () => [...btns.children].filter((c): c is HTMLElement => c !== more && (c as HTMLElement).style.display !== "none");
    for (let left = shown(); left.length && actions.offsetWidth > box.clientWidth; left = shown()) {
      const last = left[left.length - 1];
      last.style.display = "none";
      last.setAttribute("data-oi-overflow", "");
    }
  };
  const onMore = (ev: Event) => {
    ev.preventDefault();
    ev.stopPropagation();
    const items = moved();
    showMenu(doc, more, [{ name: "actions", radio: false, options: items.map((b, i) => ({ value: String(i), label: b.getAttribute("aria-label") ?? "", icon: b.querySelector("use")?.getAttribute("href")?.replace(/^#/, "") })) }], (_g, v) => items[Number(v)]?.click());
  };
  more.addEventListener("click", onMore);
  layout();
  const win = doc.defaultView as (Window & typeof globalThis) | null;
  const observer = win?.ResizeObserver ? new win.ResizeObserver(() => layout()) : null;
  observer?.observe(box);
  return () => {
    observer?.disconnect();
    more.removeEventListener("click", onMore);
    closeMenu(doc);
    restore();
  };
}

/** Each Creator's uploads in flight, kept for the page's lifetime so they outlive the frame and its component. */
const flights = new Map<string, UploadsInFlight>();
const flightOf = (accountId: string) => {
  if (!flights.has(accountId)) flights.set(accountId, { count: 0 });
  return flights.get(accountId)!;
};

/** A Creator's active stories read (ofMirrorData's Home strip: GET /users/{id}/stories). */
const OWN_STORIES = /^\/api\/of\/v2\/users\/[^/]+\/stories$/;
/** A story was added: the Creator's own stories are read again, so it shows in Home's strip. */
const refetchOwnStories = (qc: QueryClient, accountId: string | null) =>
  void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "of-mirror-data" && q.queryKey[1] === accountId && OWN_STORIES.test(String(q.queryKey[2])) });

/**
 * new-post, home and their state-* pages: bind the composer on every frame load (posts only with a single Creator). Home's
 * composer keeps its own draft and uploads, and a post from it refreshes the feed's queries.
 */
export function useOfPost(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const router = useRouter();
  const path = /^\/of-mirror\/pages\/((?:new-post|home)\/(?:index|state-[^/]+))\.html$/.exec(src)?.[1] ?? "";
  const draftId = accountId && path.startsWith("home/") ? homeDraft(accountId) : undefined;
  const qc = useQueryClient();
  const { mutateAsync: createPost } = useMutation({
    mutationFn: (body: CreatePostBody) => relay.post("/api/of/v2/posts", body, { accountId }),
  });
  const { mutateAsync: savePost } = useMutation({
    mutationFn: ({ id, body }: { id: string; body: CreatePostBody }) => relay.put(`/api/of/v2/queue/posts/${encodeURIComponent(id)}`, body, { accountId }),
  });
  const zone = useAgencyZone();
  // Not awaited: the new label is picked before the refetched list rebinds the dialog.
  const { mutateAsync: createLabel } = useMutation({
    mutationFn: (name: string) => relay.post<{ id?: number }>(LABELS, { name }, { accountId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, LABELS] }),
  });
  const params = useSearchParams();
  // Fetched only on the tag dialog (its view: search, sort, filter, tab); its cached rows also name the Co-tags in the
  // composer summary.
  const tagPage = path === TAG_PAGE || path === HOME_TAGS;
  const tagView = tagViewOf(tagPage ? params : new URLSearchParams());
  const tags = useQuery(mirrorQuery<TaggedFriendUsersResp>(accountId, tagsRoute(tagView), tagPage));
  const tagItems = accountId ? (tags.data?.items ?? rowsOf<TaggedFriendUser>(tags.data)) : undefined;
  // Fetched on the labels dialog, and on the composer while the draft has labels: the summary names them.
  const keep = typeof window === "undefined" ? null : keepOf({ storage: window.sessionStorage, accountId, draftId });
  const draftLabels = !!path && !!keep && !!loadDraft(keep.storage, keep.accountId).label_ids?.length;
  const labels = useQuery(mirrorQuery<PostLabelsResp>(accountId, LABELS, path === LABEL_PAGE || draftLabels));
  const labelItems = accountId && labels.data ? labelsOf(labels.data) : undefined;
  const labelSort = labels.data && !Array.isArray(labels.data) ? { sort: (labels.data as { sort?: string }).sort, order: (labels.data as { order?: string }).order } : undefined;
  const { mutateAsync: addVaultStory } = useMutation({
    mutationFn: (body: VaultStoryBody) => relay.post(STORIES, body, { accountId }),
    onSuccess: () => refetchOwnStories(qc, accountId),
  });
  // The vault dialog's tiles' own query (ofMirrorData's), so Add to story reads the media the tiles show; its folders'
  // (their sort).
  const vaultPage = path === VAULT_DIALOG || path === HOME_VAULT;
  const vault = useQuery(mirrorQuery(accountId, vaultMediaOf(params), vaultPage));
  const vaultItems = accountId ? rowsOf<VaultMedia>(vault.data) : undefined;
  const lists = useQuery(mirrorQuery<{ sort?: string; order?: string }>(accountId, VAULT_LISTS, vaultPage)).data;
  const folderSort = lists ? { sort: lists.sort, order: lists.order } : undefined;
  // The price button and its limits, and the name by Post (the Creator's OF name; the model in All models).
  const me = useQuery(ofMeQuery(accountId)).data;
  const priceLimits = useMemo(() => postPriceLimits(me), [me]);
  const postAs = me?.name || me?.username || undefined;
  const meId = me?.id ?? undefined;
  const tagKey = JSON.stringify(tagView);
  const sortKey = JSON.stringify([labelSort, folderSort]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || !path) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      const navigate = (href: string) => router.push(href);
      const upload = (file: File) => relay.uploadFile<VaultUploadResp>("/api/of/v2/upload", file, "file", { accountId });
      // Home's feed, its Scheduled events and the rest of this Creator's mirror reads.
      const posted = () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId] });
      const sorts = JSON.parse(sortKey) as [PostContext["labelSort"] | null, PostContext["folderSort"] | null];
      const refetch = (path: string) => () => void qc.invalidateQueries({ queryKey: ["of-mirror-data", accountId, path] });
      const tools: Partial<PostHandlers> = {
        sortLabels: (sort, order) => relay.post(`${LABELS}/sort`, { sort, order }, { accountId }).then(refetch(LABELS)),
        sortFolders: (sort, order) => sortOfFolders(accountId!, { sort, order }).then(refetch(VAULT_LISTS)),
        toggleTag: (body) => relay.patch("/api/of/v2/release-forms/toggle-show", body, { accountId }),
        inviteGuest: (name) => relay.post("/api/of/v2/guests", { name }, { accountId }),
        searchUsers: (q) => relay.get<SearchUser[]>(`/api/of/v2/users/search?q=${encodeURIComponent(q)}&limit=5`, { accountId }),
        searchPosts: (q) => relay.get<SearchPost[]>(`/api/of/v2/posts/search?query=${encodeURIComponent(q)}&limit=5`, { accountId }),
      };
      unbind = doc?.body
        ? bindPost(doc, path, {
            handlers: accountId
              ? { createPost, editPost: (id, body) => savePost({ id, body }).then((r) => (posted(), r)), confirm: (text) => window.confirm(text), createLabel, upload, addVaultStory, navigate, posted, ...tools }
              : null,
            storage: window.sessionStorage,
            accountId,
            tagItems,
            labelItems,
            vaultItems,
            vaultView: viewOf(params),
            uploads: accountId ? flightOf(draftId ?? accountId) : undefined,
            draftId,
            priceLimits,
            postAs,
            zone,
            meId,
            tagView: JSON.parse(tagKey) as TagView,
            labelSort: sorts[0] ?? undefined,
            folderSort: sorts[1] ?? undefined,
          })
        : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, path, accountId, draftId, qc, createPost, savePost, createLabel, addVaultStory, router, tagItems, labelItems, vaultItems, params, priceLimits, postAs, zone, meId, tagKey, sortKey]);
}

/** What Add to story takes: an image or a video (OF's stories take both), and its note for anything else. */
export const STORY_PICK = "image/*,video/*";
export const NOT_STORY_MEDIA = "Could not add: choose an image or a video";

/** OF's story strip: its own "Add to story" tile, any tile, a tile with media to view (a creator's stories on Home, a
 *  highlight on My profile) and the strip (the note's anchor, outside the scroller's views). */
export const STORY = {
  own: ".b-story-item.m-story-item-own",
  tile: ".b-story-item",
  viewable: "[data-oi-story-user], [data-oi-story], [data-oi-highlight], [data-oi-full]",
  strip: ".stories-list",
};

export interface StoryHandlers {
  addStory(file: File): Promise<unknown>;
  /** A creator's current stories, as viewer items (GET /users/{id}/stories). */
  userStories?(userId: string): Promise<ViewerItem[]>;
  /** A highlight's stories in order, as viewer items (GET /stories/highlights/{id}). */
  highlightStories?(highlightId: string): Promise<ViewerItem[]>;
}

/** A story tile's header in the story player: its name (a creator's, a highlight's title) and its avatar, else its picture. */
function tileAuthor(tile: HTMLElement): StoryAuthor {
  const name = tile.querySelector(".b-story-item__text")?.textContent?.trim() || tile.title.trim();
  const pic = tile.querySelector(".b-story-item__icon img") ?? tile.querySelector(".b-story-item__inside > img");
  return { name, avatar: pic?.getAttribute("src") ?? null };
}

/** A highlight's viewer items from OF's GET /stories/highlights/{id} answer (`{..., stories: [...]}`, read from OF's app.js:
 *  unconfirmed against a real account); anything else: none. */
export function highlightItems(r: unknown, img: (u: string) => string): ViewerItem[] {
  const stories = (r as { stories?: unknown } | null)?.stories;
  return Array.isArray(stories) ? storyItems(stories as StoryEntry[], img) : [];
}

/** What a viewable tile shows without a read: its stories (`data-oi-story`), else its own file (`data-oi-full`). */
function tileItems(tile: HTMLElement): ViewerItem[] {
  if (tile.dataset.oiStory) {
    try {
      const items = JSON.parse(tile.dataset.oiStory) as ViewerItem[];
      if (Array.isArray(items) && items.length) return items;
    } catch { /* fall through */ }
  }
  const one = viewerItem(tile);
  return one ? [one] : [];
}

/**
 * Wire OF's story strip in `doc` (any Mirror page; a page without the strip is left alone). A viewable tile (STORY.viewable)
 * plays its media in the Vault's viewer as OF's story player (openViewer's story mode, the tile's name and avatar in its
 * header; previous / next through a creator's stories): the stories the feed carried,
 * else the creator's current stories read through `handlers.userStories` (a failure or none: a note under the strip).
 * A highlight tile (`data-oi-highlight`) plays the highlight's stories in order, read through `handlers.highlightStories`
 * (a failure or none: a note); with no such handler, its cover. Every other tile but "Add to story" ("Go live", "Create highlight", ...) sends nothing and shows the Read-only note under the strip,
 * in either scope (bindWrites' click fallback leaves them to this, as its note would sit inside the scroller). These tiles are not marked
 * `data-oi-wired`. A strip without "Add to story" (My profile's) gets nothing more. "Add to story": a click opens a
 * hidden image picker appended to the body; a picked file goes to `handlers.addStory`, then "Added to story" shows
 * under the strip. While it uploads the tile is disabled (no second picker, no second Story) and a stale note is gone;
 * a failure shows a red "Could not add: …" that stays. Either way the tile is enabled again and the picker cleared, so
 * the same file can be picked again. A non-image pick (or one with no type) sends nothing and shows a red
 * "Could not add: choose an image"; a cancelled picker does nothing. `handlers` null (no single Creator): no picker, the select-a-model note. Returns
 * an unbind, which removes the picker.
 */
export function bindStory(doc: Document, handlers: StoryHandlers | null): () => void {
  const strip = doc.querySelector(STORY.strip);
  if (!strip) return () => {};
  // Not readOnly(panel): it anchors the note on the button (inside the scroller's views) and catches the own tile too.
  const viewStory = (tile: HTMLElement) => {
    // A highlight (My profile) plays its stories, read on each click as OF's fetchHighlightsById; no single Creator: its cover.
    const play = (items: ViewerItem[]) => openViewer(doc, items, 0, tileAuthor(tile));
    const highlight = tile.dataset.oiHighlight;
    if (highlight && handlers?.highlightStories) {
      handlers.highlightStories(highlight).then(
        (got) => (got.length ? play(got) : note(doc, strip, "No story to show", true)),
        (e) => note(doc, strip, `Could not load the highlight: ${message(e)}`, true),
      );
      return;
    }
    const items = tileItems(tile);
    if (items.length) return play(items);
    const user = tile.dataset.oiStoryUser;
    if (!user || !handlers?.userStories) return note(doc, strip, handlers ? "No story to show" : SELECT_MODEL, !!handlers);
    handlers.userStories(user).then(
      (got) => (got.length ? play(got) : note(doc, strip, "No story to show", true)),
      (e) => note(doc, strip, `Could not load the story: ${message(e)}`, true),
    );
  };
  const onOther = (ev: Event) => {
    const tile = (ev.target as Element | null)?.closest?.(STORY.tile);
    if (tile?.matches(STORY.viewable) && !tile.matches(":disabled")) {
      ev.preventDefault();
      return viewStory(tile as HTMLElement);
    }
    // A tile that is a link (New post's Go live), disabled or wired (My profile's Story archive) goes its own way.
    if (!tile || tile.matches(STORY.own) || tile.closest("a[href]") || tile.matches(":disabled, [data-oi-wired]")) return;
    ev.preventDefault();
    note(doc, strip, READ_ONLY);
  };
  strip.addEventListener("click", onOther);
  const own = strip.querySelector<HTMLButtonElement>(STORY.own);
  if (!own) return () => strip.removeEventListener("click", onOther);
  const input = doc.createElement("input");
  input.type = "file";
  input.accept = STORY_PICK;
  input.style.display = "none";
  input.setAttribute("data-oi-wired", "");
  doc.body.append(input);
  own.setAttribute("data-oi-wired", "");

  const onClick = (ev: Event) => {
    ev.preventDefault();
    if (!handlers) note(doc, strip, SELECT_MODEL);
    else if (!own.disabled) input.click();
  };
  const onChange = () => {
    // The File comes from the frame's realm: no `instanceof File` on it.
    const file = input.files?.[0];
    if (!file || !handlers) return;
    if (!/^(image|video)\//.test(file.type)) return note(doc, strip, NOT_STORY_MEDIA, true);
    own.disabled = true;
    doc.getElementById("oi-note")?.remove();
    handlers
      .addStory(file)
      .then(
        () => note(doc, strip, "Added to story"),
        (e) => note(doc, strip, `Could not add: ${message(e)}`, true),
      )
      .finally(() => {
        own.disabled = false;
        input.value = "";
      });
  };
  own.addEventListener("click", onClick);
  input.addEventListener("change", onChange);
  return () => {
    strip.removeEventListener("click", onOther);
    own.removeEventListener("click", onClick);
    input.removeEventListener("change", onChange);
    input.remove();
  };
}

/** Every Mirror page: bind the story strip (bindStory) on every frame load (a Story only with a single Creator). */
export function useOfStory(frameRef: RefObject<HTMLIFrameElement | null>, src: string): void {
  const { accountId } = useScope();
  const qc = useQueryClient();
  const { mutateAsync: addStory } = useMutation({
    mutationFn: (file: File) => relay.uploadFile("/api/of/v2/stories/upload", file, "file", { accountId }),
    onSuccess: () => refetchOwnStories(qc, accountId),
  });

  const userStories = useMemo(
    () => async (userId: string) => {
      const r = await relay.get<unknown>(`/api/of/v2/users/${encodeURIComponent(userId)}/stories`, { accountId });
      return storyItems(rowsOf<StoryEntry>(r) ?? [], (u) => proxyImage(u, accountId));
    },
    [accountId],
  );
  const highlightStories = useMemo(
    () => async (id: string) =>
      highlightItems(await relay.get<unknown>(`/api/of/v2/stories/highlights/${encodeURIComponent(id)}`, { accountId }), (u) => proxyImage(u, accountId)),
    [accountId],
  );

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let unbind: (() => void) | undefined;
    const bind = () => {
      unbind?.();
      const doc = frame.contentDocument;
      unbind = doc?.body ? bindStory(doc, accountId ? { addStory, userStories, highlightStories } : null) : undefined;
    };
    if (frame.contentDocument?.readyState === "complete") bind();
    frame.addEventListener("load", bind);
    return () => {
      frame.removeEventListener("load", bind);
      unbind?.();
    };
  }, [frameRef, src, accountId, addStory, userStories, highlightStories]);
}
