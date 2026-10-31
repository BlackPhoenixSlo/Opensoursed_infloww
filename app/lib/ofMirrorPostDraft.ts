"use client";

/**
 * The New post composer's contract (PostContext, PostHandlers), its draft (sessionStorage `oi:new-post:<accountId>`;
 * keepOf, draftOf) and the reads off it: the POST /posts body (collectPost) and the schedule dialog (renderCalendar,
 * collectSchedule, bindSchedule). ofMirrorPost re-exports its public names.
 */

import type { TaggedFriendUser, VaultMedia, VaultUploadResp } from "@/lib/relay";
import type { VaultView } from "@/lib/ofMirrorVault";
import { localIso, minuteAhead, note, scheduleAt, SELECT_MODEL, TOO_SOON } from "@/lib/ofMirrorWrites";
import { fromWallClock, wallClock } from "@/lib/ofMirrorFeeds";
import type { PostLabel, TagView } from "@/lib/ofMirrorPostTags";
import type { VaultStoryBody } from "@/lib/ofMirrorStory";

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

/** OF's POST PRICE limits in dollars (users/me postMinPrice, postMaxPrice). */
export interface PriceLimits {
  min: number;
  max: number;
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

const EMPTY_TEXT = "Write something or add media to post";
const FEW_OPTIONS = "Add at least two options";
const NO_ANSWER = "Pick the correct answer";
/** OF's composer default poll length in days (its panel shows "7 days"). */
const VOTING_DAYS = 7;
const COMPOSER = "/of-manager/new-post";
const ISO = /^\d{4}-\d{2}-\d{2}T/;
/** The captured vue-datetime schedule dialog (new-post/state-schedule). */
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const SAVE_LATER = ".custom-datepicker-button-save-later";
/** The dialog, and its attribute holding the selected day (YYYY-MM-DD): the one copy of the selection. */
const POPUP = ".vdatetime-popup";
const SELECTED = "data-oi-selected";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
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

/** Where this scope's draft is kept, or null (no draft is kept). */
const keepOf = ({ storage, accountId, draftId }: Pick<PostContext, "storage" | "accountId" | "draftId">) => (storage && accountId ? { storage, accountId: draftId ?? accountId } : null);
const draftOf = (ctx: Pick<PostContext, "storage" | "accountId" | "draftId">) => {
  const keep = keepOf(ctx);
  return keep ? loadDraft(keep.storage, keep.accountId) : emptyDraft();
};

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

/** "6:30 PM", as OF's time tab. */
const clock = (d: Date) => `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;

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

/** For ofMirrorPost and ofMirrorPostTags only; not re-exported. */
export { EMPTY_TEXT, VOTING_DAYS, MONTHS, WEEKDAYS, COMPOSER, clock, keepOf, draftOf, bindSchedule };
