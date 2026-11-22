/**
 * chatsCache — pure reads and writes over the chat-list caches
 * (`["chats", kind, accountKey, filter, listId, query, limit, order?]`,
 * InfiniteData `{ pages: [{ rows, hasMore }], pageParams }`).
 *
 * The live message handler (useInboxRealtime) and the send path
 * (useSendMessage) both move a fan's row to the top here, with ONE row match
 * (`fanRowMatcher`, `sameUserId`): the send path used to compare
 * `withUser.id === fanId`, which never matches a string fan id against a
 * number one, so a sent chat stayed where it was.
 *
 * vs the loops this replaced: the patched row is the fan's FIRST copy (the one
 * useChatList's first-seen-wins flatten shows; the live handler patched the
 * last), and a lift drops EVERY other copy (the send path kept later ones).
 *
 * Every live write to these caches goes through `patchChatCaches`, which also
 * journals it per QueryClient; each chats query's commit (`commitChatPages`)
 * re-applies the journal to the pages read before a write, so no read in
 * flight undoes one (W30-mu #12).
 */

import type { InfiniteData, QueryClient } from "@tanstack/react-query";

import { patchQueryData } from "@/lib/cacheWrite";
import { isUnreadChat } from "@/lib/chatUnread";
import type { OFChatItem } from "@/lib/relay";
import { compareFanIds, sameUserId, type FanId } from "@/lib/fanId";
import { toUtcIso } from "@/lib/threadCache";

export interface ChatPage { rows: OFChatItem[]; hasMore: boolean }
export type ChatPages = InfiniteData<ChatPage>;

/** A chats query key, read by position. */
export interface ChatsKey {
  scopeKind: unknown;
  /** The model's id (model scope) or the sorted comma-joined ids (all scope). */
  accountKey: string;
  filter: unknown;
  listId: unknown;
  query: unknown;
  /** No filter, folder or search: the only view a brand-new row may enter. */
  unfiltered: boolean;
}

export function decodeChatsKey(key: readonly unknown[]): ChatsKey {
  const filter = key[3] ?? null;
  const listId = key[4] ?? null;
  const query = key[5] ?? null;
  return {
    scopeKind: key[1],
    accountKey: String(key[2] ?? ""),
    filter, listId, query,
    unfiltered: filter === null && listId === null && query === null,
  };
}

/** Does this cache's scope include the account? A model list holds only its
 *  own model; an all-scope list every id in its key. */
export function keyHoldsAccount(k: ChatsKey, accountId: string): boolean {
  return k.scopeKind === "model"
    ? k.accountKey === accountId
    : k.accountKey.split(",").includes(accountId);
}

/** May a brand-new row for the account enter this cache? Only the unfiltered
 *  view (a new fan may not match a filter / folder / search) whose scope holds
 *  the account (another model's list would be the cross-model leak). */
export function mayAddRow(key: readonly unknown[], accountId: string): boolean {
  const k = decodeChatsKey(key);
  return k.unfiltered && keyHoldsAccount(k, accountId);
}

/** The row predicate for one fan of one model, across the number/string id split. */
export function fanRowMatcher(accountId: string, fanId: FanId): (row: OFChatItem) => boolean {
  return (row) => (row.__accountId ?? "") === accountId && sameUserId(row.withUser?.id, fanId);
}

/** Write the fan's row into one cache's pages. `patch` gets the row's first
 *  copy (the one the list shows), or null when the fan isn't there, and returns
 *  the row to write, or null to leave the pages alone. The row goes to the head
 *  of page 0 with every copy dropped, or (`inPlace`, a present row) replaces
 *  that copy where it sits. Returns the SAME `pages` when nothing changes, and
 *  keeps the reference of every page that held no copy, so React Query
 *  notifies no subscriber of an untouched list. */
export function bumpChatPages(
  pages: ChatPage[],
  isRow: (row: OFChatItem) => boolean,
  patch: (existing: OFChatItem | null) => OFChatItem | null,
  { inPlace = false }: { inPlace?: boolean } = {},
): ChatPage[] {
  if (!pages.length) return pages;
  let existing: OFChatItem | null = null;
  const hit = new Set<number>();
  for (let i = 0; i < pages.length; i++) {
    for (const c of pages[i].rows) {
      if (!isRow(c)) continue;
      if (existing === null) existing = c;
      hit.add(i);
    }
  }
  const row = patch(existing);
  if (!row) return pages;
  if (existing && inPlace) {
    return pages.map((p, i) =>
      hit.has(i) ? { ...p, rows: p.rows.map((c) => (c === existing ? row : c)) } : p);
  }
  const stripped = pages.map((p, i) =>
    hit.has(i) ? { ...p, rows: p.rows.filter((c) => !isRow(c)) } : p);
  const [first, ...rest] = stripped;
  return [{ ...first, rows: [row, ...first.rows] }, ...rest];
}

/** The fan's FRESHEST row across chats caches (newest `lastMessage` wins;
 *  ties / undated → first seen), or null. The same fan can sit in several
 *  caches at different freshness; a first match could be a stale copy. */
export function freshestFanRow(
  caches: Iterable<ChatPages | undefined>,
  accountId: string,
  fanId: FanId,
): OFChatItem | null {
  const isRow = fanRowMatcher(accountId, fanId);
  let best: OFChatItem | null = null;
  let bestAt = -Infinity;
  for (const data of caches) {
    for (const p of data?.pages ?? []) {
      for (const c of p.rows) {
        if (!isRow(c)) continue;
        const parsed = Date.parse(c.lastMessage?.createdAt ?? "");
        const ts = Number.isFinite(parsed) ? parsed : -Infinity;
        if (best === null || ts > bestAt) { best = c; bestAt = ts; }
      }
    }
  }
  return best;
}

/** What a manual send leaves on the fan's row. */
export interface SentMessage {
  fromUserId: number | string;
  fromUserName: string;
  text: string;
  mediaCount: number;
  price: number;
}

/** The fan's row once we sent `msg` (`id`, `createdAt` the message's): it is the preview, unread cleared. A
 *  fresh message, not the old one spread: the fan's previous `lockedText` / `isTip` used to ride on and mark
 *  our free text 🔒/💰. */
function repliedRow(target: OFChatItem, msg: SentMessage, id: number | string, createdAt: string): OFChatItem {
  return {
    ...target,
    hasUnread: false,
    unreadMessagesCount: 0,
    lastMessage: {
      id: id as number,
      text: msg.text,
      fromUser: { id: msg.fromUserId, name: msg.fromUserName },
      createdAt,
      mediaCount: msg.mediaCount,
      isFree: msg.price === 0,
      price: msg.price,
    },
  };
}

/** One chats cache after a manual send to `fanId`: the row (only a row
 *  already there, never a new one) gets the message as its preview with
 *  unread cleared; the unfiltered list lifts it to the top, a filtered /
 *  folder / search view patches it in place (reordering it would shuffle
 *  rows the user didn't touch). Same `data` when the fan isn't in it, or
 *  his row shows a message newer than `nowIso` (`rowNewerThan`: stamp it on the Relay's clock, `relayNow()`). */
export function bumpAfterSend(
  key: readonly unknown[],
  data: ChatPages,
  accountId: string,
  fanId: FanId,
  msg: SentMessage,
  nowIso: string,
): ChatPages {
  const pages = bumpChatPages(
    data.pages,
    fanRowMatcher(accountId, fanId),
    (target) => target && !rowNewerThan(target, Date.parse(nowIso))
      ? repliedRow(target, msg, target.lastMessage?.id ?? 0, nowIso) : null,
    { inPlace: !decodeChatsKey(key).unfiltered },
  );
  return pages === data.pages ? data : { ...data, pages };
}

/** Whether the row shows a message newer than `ms` (epoch ms on the Relay's clock: an event's `at`, OF's
 *  `createdAt`, `relayNow()`; never the tab's clock). The one rule by which a late or replayed write leaves a
 *  row alone. */
export function rowNewerThan(c: OFChatItem | null | undefined, ms: number): boolean {
  const at = c?.lastMessage?.createdAt;
  return !!at && Date.parse(toUtcIso(at)) > ms;
}

/** A person's DM through the relay (`chat_responded`, from any tab): the fan, OF's message, and when the
 *  relay announced it (epoch ms; null when unknown). */
export interface Reply {
  fanId: FanId;
  /** OF's message id. */
  id: number | string;
  createdAt: string;
  text: string;
  mediaCount: number;
  price: number;
  at: number | null;
}

/** `chat_responded`'s body (service events.publish_chat_responded: `{fan_id, by, at, message?: {id, text,
 *  createdAt, mediaCount, price}}`) as a `Reply`, or null when it carries no usable message (an older relay,
 *  a send answer that was not a message). */
export function parseReply(body: unknown): Reply | null {
  const b = (body ?? {}) as { fan_id?: unknown; at?: unknown; message?: unknown };
  const m = (b.message ?? null) as Record<string, unknown> | null;
  const fanId = b.fan_id;
  if (!(typeof fanId === "number" || (typeof fanId === "string" && fanId !== ""))) return null;
  if (!m || !(typeof m.id === "number" || (typeof m.id === "string" && m.id !== ""))) return null;
  const createdAt = typeof m.createdAt === "string" ? m.createdAt : "";
  if (!Number.isFinite(Date.parse(createdAt))) return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
  return {
    fanId, id: m.id, createdAt,
    text: typeof m.text === "string" ? m.text : "",
    mediaCount: num(m.mediaCount), price: num(m.price),
    at: typeof b.at === "number" && Number.isFinite(b.at) ? b.at : null,
  };
}

/** One chats cache after another tab's (or this tab's) reply to the fan on `accountId`: as `bumpAfterSend`
 *  (the row gets the message, read; lifted in the unfiltered list, in place elsewhere; never a new row).
 *  The SAME `data`, untouched, when the fan isn't in it, or a page holding him was read after the reply
 *  (`askedAt` > `reply.at`: it already shows it), or his row already shows this message or a newer one (a
 *  repeat, a replay, the fan wrote since). So the sender's own optimistic bump and the event, either first,
 *  leave one row. */
export function applyReply<T extends ChatPages | undefined>(
  key: readonly unknown[], data: T, accountId: string, reply: Reply,
): T {
  if (!data?.pages?.length) return data;
  const pages = data.pages as StampedPage[];
  const isRow = fanRowMatcher(accountId, reply.fanId);
  const holders = pages.filter((p) => p.rows.some(isRow));
  if (!holders.length) return data;
  if (reply.at != null && holders.some((p) => relayAskedAt(p) > reply.at!)) return data;
  const sent = Date.parse(reply.createdAt);
  const msg: SentMessage = {
    fromUserId: accountId, fromUserName: "", text: reply.text, mediaCount: reply.mediaCount, price: reply.price,
  };
  const next = bumpChatPages(
    data.pages, isRow,
    (target) => {
      const last = target?.lastMessage;
      if (!target || (last?.id != null && String(last.id) === String(reply.id))) return null;
      if (rowNewerThan(target, sent)) return null;
      return repliedRow(target, msg, reply.id, reply.createdAt);
    },
    { inPlace: !decodeChatsKey(key).unfiltered },
  );
  return next === data.pages ? data : { ...data, pages: next };
}

/** The Unread chip's view when it is the whole truth: read from OF in this
 *  page load, no search, no page left. `asOf` is when OF was asked for its
 *  oldest page (ms). */
export interface UnreadView { rows: OFChatItem[]; asOf: number }

/** A chat row's identity in the lists, (accountId, fanId): useChatList's flatten de-dupes by it, and the Fan List
 *  keys its picks by it. */
export function chatRowKey(c: OFChatItem): string {
  return `${c.__accountId ?? ""}:${c.withUser?.id}`;
}

/** The predicate "unread here, not in the complete Unread view". */
export function unreadOutsideView(view: UnreadView): (c: OFChatItem) => boolean {
  const inView = new Set(view.rows.map(chatRowKey));
  return (c) => isUnreadChat(c) && !inView.has(chatRowKey(c));
}

/** The predicate "read elsewhere": unread here, not in the complete Unread
 *  view, and its last message older than the view's read. A chat that turned
 *  unread after it (a live message: a filtered list never gains rows) or
 *  carries no date stays as it is. */
export function readElsewhere(view: UnreadView): (c: OFChatItem) => boolean {
  const outside = unreadOutsideView(view);
  return (c) => {
    if (!outside(c)) return false;
    const at = Date.parse(c.lastMessage?.createdAt ?? "");
    return Number.isFinite(at) && at < view.asOf;
  };
}

/** A chats page as useChatList stamps it. */
export interface StampedPage extends ChatPage {
  /** The page load that read it from OF. */
  session?: string;
  /** When OF was asked for it (ms, the Relay's clock as the tab estimated it: lib/ageClock `relayNow`). */
  askedAt?: number;
  /** `askedAt` was taken before any Relay time set the tab's offset: a guess, never compared with a Relay time. */
  askedAtGuess?: true;
  /** When it was asked on the tab's own order (`localSeq`): the live writes journaled after it are re-applied to it
   *  at its commit (`commitChatPages`). */
  askedSeq?: number;
  /** All Models: a Creator's call failed, its rows are missing. */
  partial?: boolean;
}

/** A page's ask time to hold against a Relay time (an event's `at`): -Infinity when unknown or a guess, so the
 *  event is applied. */
function relayAskedAt(p: StampedPage): number {
  return p.askedAt == null || p.askedAtGuess ? -Infinity : p.askedAt;
}

/** The cached Unread list (`data`) as an `UnreadView` while it is the whole
 *  truth: every page read from OF in this page load (`session`), stamped, no
 *  Creator missing, none left to load. Null otherwise. Remembered for its
 *  scope while another chip shows (the cache entry outlives its observer),
 *  kept current by every live patch of the caches (a message, a read flip),
 *  and replaced by the next read of it; the caller passes none under a search. */
export function completeUnreadView(
  data: InfiniteData<StampedPage> | undefined, session: string,
): UnreadView | null {
  const pages = data?.pages ?? [];
  if (!pages.length || pages[pages.length - 1].hasMore) return null;
  if (pages.some((p) => p.session !== session || p.askedAt == null || p.partial)) return null;
  const rows: OFChatItem[] = [];
  const seen = new Set<string>();
  for (const p of pages) for (const c of p.rows) {
    const k = chatRowKey(c);
    if (seen.has(k)) continue;
    seen.add(k);
    rows.push(c);
  }
  return { rows, asOf: Math.min(...pages.map((p) => p.askedAt as number)) };
}

/** Off the Unread chip nothing re-reads the cached Unread list (no observer;
 *  the head poll writes only the active list), so its view counts for the
 *  badge only this long after its read (`asOf`). */
export const UNREAD_VIEW_MAX_AGE_MS = 5 * 60_000;

/** The Unread view the badge may use: on the Unread chip (its own live list)
 *  as is; on any other chip only while younger than UNREAD_VIEW_MAX_AGE_MS,
 *  else null (the badge falls back to the All set's flags). */
export function badgeUnreadView(view: UnreadView | null, onUnreadChip: boolean, now: number): UnreadView | null {
  if (!view || onUnreadChip) return view;
  return now - view.asOf < UNREAD_VIEW_MAX_AGE_MS ? view : null;
}

/** The chats list order (newest last message first; ties by fan id, newest
 *  first, via compareFanIds: never `b.id - a.id`, NaN on a Fansly string snowflake). */
export function compareChats(a: OFChatItem, b: OFChatItem): number {
  const ta = a.lastMessage?.createdAt ?? "";
  const tb = b.lastMessage?.createdAt ?? "";
  if (ta && tb && ta !== tb) return tb.localeCompare(ta);
  return compareFanIds(b.withUser?.id, a.withUser?.id);
}

/** A chatter's read flip through the relay (`chat_read_changed`): one fan's
 *  chat, or every chat of the account (`fanId` null), turned read or unread,
 *  at `at` (epoch ms; null when unknown). */
export interface ReadFlip { fanId: FanId | null; unread: boolean; at: number | null }

/** `chat_read_changed`'s body (service server._publish_read_flip:
 *  `{fan_id: id | "all", unread: 0 | 1, at}`), or null when malformed. */
export function parseReadFlip(body: unknown): ReadFlip | null {
  const b = (body ?? {}) as { fan_id?: unknown; unread?: unknown; at?: unknown };
  if (b.unread !== 0 && b.unread !== 1) return null;
  const fanId = b.fan_id === "all" ? null
    : typeof b.fan_id === "number" || (typeof b.fan_id === "string" && b.fan_id !== "") ? b.fan_id : undefined;
  const at = typeof b.at === "number" && Number.isFinite(b.at) ? b.at : null;
  return fanId === undefined ? null : { fanId, unread: b.unread === 1, at };
}

/** Is this cache a plain Unread-filter list (no folder, no search, default
 *  order)? A read flip adds or drops rows there; elsewhere it flips flags. */
export function isUnreadList(key: readonly unknown[]): boolean {
  const k = decodeChatsKey(key);
  return k.filter === "unread" && k.listId === null && k.query === null && (key[7] ?? "recent") === "recent";
}

/** One chats cache after a read flip on `accountId`. A page read after the
 *  flip (`askedAt` > `flip.at`) already holds it and is left alone (a replayed
 *  event never undoes newer data).
 *  A read flip leaves a row whose last message is newer than it (`flip.at` is
 *  taken before the platform write) unread.
 *  - Any list: the fan's every row (every row of the account for a mark-all)
 *    takes the flags, in place.
 *  - An Unread list (`unreadList`), so the cached Unread view stays the truth
 *    with no stamp: turned unread, the fan's row (`source`, a copy from any
 *    cached list) enters at its place when absent; turned read, its rows
 *    leave, unless `keepRows` (the list on screen: the open chat stays put).
 *  The SAME `data` when nothing changes, so a repeated flip (the HTTP answer
 *  and the event, either first) is a no-op. */
export function applyReadFlip<T extends ChatPages | undefined>(
  data: T, accountId: string, flip: ReadFlip,
  opts: { unreadList?: boolean; keepRows?: boolean; source?: OFChatItem | null; skip?: ReadonlySet<string> } = {},
): T {
  if (!data?.pages) return data;
  const pages = data.pages as StampedPage[];
  const fresh = (p: StampedPage) => flip.at == null || flip.at >= relayAskedAt(p);
  const ofFlip = flip.fanId === null
    ? (c: OFChatItem) => (c.__accountId ?? "") === accountId
    : fanRowMatcher(accountId, flip.fanId);
  // A read flip never clears a message newer than it (a fan wrote while the write was in flight).
  const newer = (c: OFChatItem) => !flip.unread && flip.at != null && rowNewerThan(c, flip.at);
  // A fan flipped after an account-wide flip (`skip`, its fan ids as text) keeps that newer flip.
  const isRow = (c: OFChatItem) => ofFlip(c) && !newer(c) && !opts.skip?.has(String(c.withUser?.id));
  const drop = !!opts.unreadList && !flip.unread && !opts.keepRows;
  const flipped = (c: OFChatItem): OFChatItem | null => {
    if (!flip.unread) return isUnreadChat(c) ? { ...c, hasUnread: false, unreadMessagesCount: 0 } : null;
    return c.hasUnread ? null : { ...c, hasUnread: true, unreadMessagesCount: Math.max(1, c.unreadMessagesCount ?? 0) };
  };
  let changed = false;
  const next = pages.map((p) => {
    if (!fresh(p) || !p.rows.some(isRow)) return p;
    const rows = drop ? p.rows.filter((c) => !isRow(c)) : p.rows.map((c) => (isRow(c) && flipped(c)) || c);
    if (rows.length === p.rows.length && rows.every((c, i) => c === p.rows[i])) return p;
    changed = true;
    return { ...p, rows };
  });
  const src = opts.source;
  if (opts.unreadList && flip.unread && flip.fanId !== null && src && !pages.some((p) => p.rows.some(isRow))) {
    const row = { ...src, hasUnread: true, unreadMessagesCount: Math.max(1, src.unreadMessagesCount ?? 0) };
    // Before the first row it sorts ahead of; after the last only when no page is left to load.
    let at = next.findIndex((p) => p.rows.some((c) => compareChats(row, c) < 0));
    let idx = at < 0 ? -1 : next[at].rows.findIndex((c) => compareChats(row, c) < 0);
    if (at < 0 && !next[next.length - 1].hasMore) { at = next.length - 1; idx = next[at].rows.length; }
    if (at >= 0 && fresh(next[at])) {
      const p = next[at];
      next[at] = { ...p, rows: [...p.rows.slice(0, idx), row, ...p.rows.slice(idx)] };
      changed = true;
    }
  }
  return changed ? { ...data, pages: next } : data;
}

/** `data` (one chats cache) with `patch` on every copy of the fan's row (a
 *  mark-read, a mute); the SAME `data` when the fan isn't in it. */
export function patchFanRows<T extends ChatPages | undefined>(
  data: T, accountId: string, fanId: FanId, patch: Partial<OFChatItem>,
): T {
  if (!data?.pages) return data;
  const isRow = fanRowMatcher(accountId, fanId);
  if (!data.pages.some((p) => p.rows.some(isRow))) return data;
  return {
    ...data,
    pages: data.pages.map((p) => ({ ...p, rows: p.rows.map((c) => (isRow(c) ? { ...c, ...patch } : c)) })),
  };
}

/** One live write to a chats cache's rows: `data` after it, the SAME `data` when nothing changes. `key` is the
 *  cache's; `observed`: a list on screen; `replay`: re-applied at a commit to pages read before it
 *  (`commitChatPages`), where it adds no row (the live write already placed one where it belonged) and leaves a row
 *  showing a newer message alone. */
export type ChatsPatch = (data: ChatPages, ctx: { key: readonly unknown[]; observed: boolean; replay: boolean }) => ChatPages;

/** A journaled live write: its account, its place in the tab's order, the patch. */
interface ChatsFact { accountId: string; seq: number; patch: ChatsPatch }

/** How long a live write is kept for re-applying: longer than any chat-list read (a Refresh walks pages one by one). */
export const JOURNAL_MS = 10 * 60_000;
const JOURNAL_MAX = 1_000;
const journals = new WeakMap<QueryClient, ChatsFact[]>();
/** Each committed page object: the tab order (`localSeq`) every live write up to which it holds. */
const seen = new WeakMap<object, number>();
let lastSeq = 0;

/** The tab's own order for chat-list reads and live writes: strictly increasing, from the tab's clock (so a page
 *  persisted by an earlier load sorts before this load's writes). Never compared with a Relay time. */
export function localSeq(): number {
  lastSeq = Math.max(lastSeq + 1, Date.now());
  return lastSeq;
}

/** Write `patch` into every cached chat list holding `accountId` (a live write, not a read: `patchQueryData`) and
 *  journal it for this QueryClient, so a page read before it and committed after (a Refresh, a loadMore, the head
 *  poll, a first load) gets it at that commit (`commitChatPages`). Every live write to a chats cache goes through
 *  here: the journal replays in order, so it must hold them all. */
export function patchChatCaches(qc: QueryClient, accountId: string, patch: ChatsPatch): void {
  const floor = Date.now() - JOURNAL_MS;
  const journal = (journals.get(qc) ?? []).filter((f) => f.seq > floor).slice(-(JOURNAL_MAX - 1));
  journal.push({ accountId, seq: localSeq(), patch });
  journals.set(qc, journal);
  for (const q of qc.getQueryCache().findAll({ queryKey: ["chats"] })) {
    if (!keyHoldsAccount(decodeChatsKey(q.queryKey), accountId)) continue;
    const data = q.state.data as ChatPages | undefined;
    if (!data?.pages?.length) continue;
    const next = patch(data, { key: q.queryKey, observed: q.getObserversCount() > 0, replay: false });
    if (next === data) continue;
    // Its pages hold every write so far: the commit this triggers (`commitChatPages`) re-applies nothing.
    for (const p of next.pages) seen.set(p, lastSeq);
    patchQueryData<ChatPages>(qc, q.queryKey, () => next);
  }
}

/** `next` with the journaled writes re-applied: each page not known to hold them (a page fresh off the wire: since
 *  its `askedSeq`; a page object a read captured and commits again, as a loadMore does: since its last commit)
 *  gets, in their order, the writes of the Creators the key holds made after that, each applied to the pages that
 *  predate it, none older than `JOURNAL_MS` (a page with no `askedSeq`, persisted by an earlier load, gets only the
 *  writes kept). The SAME `next` when nothing applies.
 *  The pages predating a write are always a run from page 0 (a refetch reads its pages in order; a loadMore's
 *  captured pages and its new one all predate it; the head poll re-reads page 0), so a patch that lifts a row to
 *  the top of the pages it gets lifts it to the list's top, never onto a later page. */
function replayJournal(qc: QueryClient, key: readonly unknown[], next: unknown): unknown {
  const data = next as InfiniteData<StampedPage> | undefined;
  if (!data?.pages?.length) return next;
  const k = decodeChatsKey(key);
  const since = data.pages.map((p) => seen.get(p) ?? p.askedSeq ?? -Infinity);
  const floor = Math.max(Math.min(...since), Date.now() - JOURNAL_MS);
  const facts = (journals.get(qc) ?? []).filter((f) => f.seq > floor && keyHoldsAccount(k, f.accountId));
  if (!facts.length) return next;
  const pages = data.pages.slice();
  const ctx = { key, observed: (qc.getQueryCache().find({ queryKey: key, exact: true })?.getObserversCount() ?? 0) > 0, replay: true };
  for (const f of facts) {
    const at = pages.flatMap((_, i) => (since[i] < f.seq ? [i] : []));
    const sub = { pages: at.map((i) => pages[i]), pageParams: at.map((i) => data.pageParams[i]) };
    const out = f.patch(sub, ctx);
    if (out !== sub && out.pages.length === at.length) at.forEach((i, j) => { pages[i] = out.pages[j]; });
  }
  return pages.every((p, i) => p === data.pages[i]) ? next : { ...data, pages };
}

/** A chats query's commit (its `structuralSharing`; every chats query sets it, a prefetch too: a query keeps the
 *  options of its last fetch): the journaled live writes re-applied (`replayJournal`), so a read started before a
 *  read flip, a reply or a live message never undoes it, whichever page of a multi-page refetch it lands between;
 *  then `share` (useChatList's row-wise sharing); every page committed is then known to hold every write so far. */
export function commitChatPages(qc: QueryClient, key: readonly unknown[], share: (prev: unknown, next: unknown) => unknown) {
  return (prev: unknown, next: unknown): unknown => {
    const out = share(prev, replayJournal(qc, key, next)) as ChatPages | undefined;
    for (const p of out?.pages ?? []) seen.set(p, lastSeq);
    return out;
  };
}
