"use client";


import type { TaggedFriendUser, VaultMedia, VaultUploadResp } from "@/lib/relay";
import type { VaultView } from "@/lib/ofMirrorVault";
import { localIso, minuteAhead, note, scheduleAt, SELECT_MODEL, TOO_SOON } from "@/lib/ofMirrorWrites";
import { fromWallClock, wallClock } from "@/lib/ofMirrorFeedsShared";
import type { PostLabel, TagView } from "@/lib/ofMirrorPostTags";
import type { VaultStoryBody } from "@/lib/ofMirrorStory";

export interface PostDraft {
  text: string;
  html?: string;
  posted_at?: string;
  save_for_later?: boolean;
  tagged_users: number[];
  media_files: Array<number | Record<string, unknown>>;
  thumbs: string[];
  voting?: Voting;
  voting_due?: number;
  period_for?: 1 | 2;
  expire_days?: number;
  fund_raising_target?: number;
  label_ids?: number[];
  price?: number;
  edit_id?: string;
  upload_failed?: Record<string, string>;
}

export interface Voting {
  type: 1 | 2;
  options: string[];
  correct?: number;
}

export interface CreatePostBody {
  text: string;
  media_files: Array<number | Record<string, unknown>>;
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
  editPost?(id: string, body: CreatePostBody): Promise<unknown>;
  confirm?(text: string): boolean;
  createLabel(name: string): Promise<{ id?: number } | null | undefined>;
  upload(file: File): Promise<VaultUploadResp>;
  addVaultStory?(body: VaultStoryBody): Promise<unknown>;
  navigate(href: string): void;
  posted?(): void;
  sortLabels?(sort: string, order: string): Promise<unknown>;
  sortFolders?(sort: string, order: string): Promise<unknown>;
  toggleTag?(body: { entity_id: number; entity_type: string }): Promise<unknown>;
  inviteGuest?(name: string): Promise<unknown>;
  searchUsers?(query: string): Promise<SearchUser[]>;
  searchPosts?(query: string): Promise<SearchPost[]>;
}

export interface SearchUser {
  id: number | string;
  name?: string | null;
  username?: string | null;
}
export interface SearchPost {
  id: number | string;
  text?: string | null;
  rawText?: string | null;
  author?: { id?: number | string; name?: string | null; username?: string | null } | null;
}

export interface PriceLimits {
  min: number;
  max: number;
}

export interface PostContext {
  handlers: PostHandlers | null;
  storage: Storage | null;
  accountId: string | null;
  tagItems?: TaggedFriendUser[];
  labelItems?: PostLabel[];
  vaultItems?: VaultMedia[];
  uploads?: UploadsInFlight;
  draftId?: string;
  composer?: string;
  vaultView?: Partial<VaultView>;
  priceLimits?: PriceLimits | null;
  postAs?: string;
  zone?: string;
  meId?: number | string;
  tagView?: TagView;
  labelSort?: { sort?: string; order?: string };
  folderSort?: { sort?: string; order?: string };
  newWrites: boolean;
}

export interface UploadsInFlight {
  count: number;
  // Uploads in flight survive a rebind (a State page round trip loads a new frame document while one runs).
  refresh?: () => void;
}

const EMPTY_TEXT = "Write something or add media to post";
const FEW_OPTIONS = "Add at least two options";
const NO_ANSWER = "Pick the correct answer";
const VOTING_DAYS = 7;
const COMPOSER = "/of-manager/new-post";
const ISO = /^\d{4}-\d{2}-\d{2}T/;
const DAY = "vdatetime-calendar__month__day";
const SHOWN = ".vdatetime-calendar__current--month";
const TIME_TAB = ".vdatetime-popup__tab.time";
const NEXT = ".vdatetime-popup__actions__button--confirm button";
const SAVE_LATER = ".custom-datepicker-button-save-later";
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

const keepOf = ({ storage, accountId, draftId }: Pick<PostContext, "storage" | "accountId" | "draftId">) => (storage && accountId ? { storage, accountId: draftId ?? accountId } : null);
const draftOf = (ctx: Pick<PostContext, "storage" | "accountId" | "draftId">) => {
  const keep = keepOf(ctx);
  return keep ? loadDraft(keep.storage, keep.accountId) : emptyDraft();
};

export const mergeSendWith = (mediaFiles: PostDraft["media_files"], sendWith: PostDraft["media_files"]): PostDraft["media_files"] => [...mediaFiles, ...sendWith];

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

export function collectPost(text: string, draft: PostDraft, now: Date = new Date()): CreatePostBody | string {
  const t = text.trim();
  if (!t && !draft.media_files.length) return EMPTY_TEXT;
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

const shownMonth = (doc: Document): Date | null => {
  const [name, year] = (doc.querySelector(SHOWN)?.textContent ?? "").trim().split(/\s+/);
  const m = MONTHS.indexOf(name);
  return m >= 0 && /^\d{4}$/.test(year ?? "") ? new Date(+year, m, 1) : null;
};

const selectedDay = (doc: Document): Date | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(doc.querySelector(POPUP)?.getAttribute(SELECTED) ?? "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
};

export function collectSchedule(doc: Document, now: Date = new Date(), zone?: string): string {
  const wallNow = wallClock(now, zone);
  const day = selectedDay(doc) ?? wallNow;
  const at = scheduleAt(day.getFullYear(), day.getMonth() + 1, day.getDate(), doc.querySelector(TIME_TAB)?.textContent ?? "", wallNow);
  return typeof at === "string" ? at : localIso(fromWallClock(at, zone));
}

const clock = (d: Date) => `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;

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

export { EMPTY_TEXT, VOTING_DAYS, MONTHS, WEEKDAYS, COMPOSER, clock, keepOf, draftOf, bindSchedule };
