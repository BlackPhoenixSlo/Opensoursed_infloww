import { replaceEqualDeep, type InfiniteData, type QueryClient, type QueryState } from "@tanstack/react-query";

import { CHAT_AUTO_PAGES_MAX } from "@/hooks/chatListLoadMore";
import type { ChatListFilter } from "@/lib/chatFilters";
import { patchQueryData } from "@/lib/cacheWrite";
import { isUnreadChat } from "@/lib/chatUnread";
import type { OFChatItem } from "@/lib/relay";
import { compareFanIds, sameUserId, type FanId } from "@/lib/fanId";
import { toUtcIso } from "@/lib/threadCache";
import { compareCellChats, tokenOf } from "@/lib/cellInbox";

export interface ChatPage {
  rows: OFChatItem[];
  hasMore: boolean;
  splitVersions?: Record<string, string>;
}
export type ChatPages = InfiniteData<ChatPage>;

export function replayCachedPage<T>(state: QueryState<InfiniteData<T>> | undefined, offset: number, limit: number): T | undefined {
  const data = state?.data;
  if (state?.fetchMeta?.fetchMore || !data?.pages || offset < CHAT_AUTO_PAGES_MAX * limit) return undefined;
  const i = data.pageParams.indexOf(offset);
  return i < 0 ? undefined : data.pages[i];
}

export interface ChatsKey {
  scopeKind: unknown;
  accountKey: string;
  filter: ChatListFilter | null;
  listId: string | null;
  query: string | null;
  limit: number;
  order: "old" | "recent";
  gated: boolean;
  unfiltered: boolean;
}

export function decodeChatsKey(key: readonly unknown[]): ChatsKey {
  const filter = (key[3] ?? null) as ChatsKey["filter"];
  const listId = key[4] == null ? null : String(key[4]);
  const query = typeof key[5] === "string" ? key[5] : null;
  return {
    scopeKind: key[1],
    accountKey: String(key[2] ?? ""),
    filter, listId, query,
    limit: key[6] as number,
    order: key[7] === "old" ? "old" : "recent",
    gated: key[8] === true,
    unfiltered: filter === null && listId === null && query === null,
  };
}

export function keyHoldsAccount(k: ChatsKey, accountId: string): boolean {
  return k.accountKey.split(",").includes(accountId);
}

export function isLiveView(key: ChatsKey): boolean {
  return (key.unfiltered && key.order === "recent") || isPlainUnread(key);
}

export function viewAdmits(key: ChatsKey, row: OFChatItem): boolean {
  return isLiveView(key) && keyHoldsAccount(key, row.__accountId ?? "")
    && (key.unfiltered || isUnreadChat(row));
}

export function fanRowMatcher(accountId: string, fanId: FanId): (row: OFChatItem) => boolean {
  // Fan ids are numbers on OF, string snowflakes on Fansly: never compare with ===.
  return (row) => (row.__accountId ?? "") === accountId && sameUserId(row.withUser?.id, fanId);
}

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

export interface SentMessage {
  fromUserId: number | string;
  fromUserName: string;
  text: string;
  mediaCount: number;
  price: number;
}

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

export function rowNewerThan(c: OFChatItem | null | undefined, ms: number): boolean {
  const at = c?.lastMessage?.createdAt;
  return !!at && Date.parse(toUtcIso(at)) > ms;
}

export interface Reply {
  fanId: FanId;
  id: number | string;
  createdAt: string;
  text: string;
  mediaCount: number;
  price: number;
  at: number | null;
}

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

export interface UnreadView { rows: OFChatItem[]; asOf: number }

export function chatAccountOf(chat: OFChatItem, singleAccountId: string | null): string | null {
  return chat.__accountId ?? singleAccountId;
}

export function chatRowKey(c: OFChatItem): string {
  return `${c.__accountId ?? ""}:${c.withUser?.id}`;
}

export function unreadOutsideView(view: UnreadView): (c: OFChatItem) => boolean {
  const inView = new Set(view.rows.map(chatRowKey));
  return (c) => isUnreadChat(c) && !inView.has(chatRowKey(c));
}

export function readElsewhere(view: UnreadView): (c: OFChatItem) => boolean {
  const outside = unreadOutsideView(view);
  return (c) => {
    if (!outside(c)) return false;
    const at = Date.parse(c.lastMessage?.createdAt ?? "");
    return Number.isFinite(at) && at < view.asOf;
  };
}

export interface StampedPage extends ChatPage {
  session?: string;
  askedAt?: number;
  askedAtGuess?: true;
  askedSeq?: number;
  partial?: boolean;
  missing?: string[];
  moreAccounts: string[];
  scanned: number;
}

function relayAskedAt(p: StampedPage): number {
  return p.askedAt == null || p.askedAtGuess ? -Infinity : p.askedAt;
}

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

// Off the Unread chip nothing re-reads the cached Unread list, so its view only counts this long.
export const UNREAD_VIEW_MAX_AGE_MS = 5 * 60_000;

export function badgeUnreadView(view: UnreadView | null, onUnreadChip: boolean, now: number): UnreadView | null {
  if (!view || onUnreadChip) return view;
  return now - view.asOf < UNREAD_VIEW_MAX_AGE_MS ? view : null;
}

export function compareChats(a: OFChatItem, b: OFChatItem): number {
  const ta = a.lastMessage?.createdAt ?? "";
  const tb = b.lastMessage?.createdAt ?? "";
  if (ta && tb && ta !== tb) return tb.localeCompare(ta);
  // Never b.id - a.id: NaN on a Fansly string snowflake.
  return compareFanIds(b.withUser?.id, a.withUser?.id);
}

export interface ReadFlip { fanId: FanId | null; unread: boolean; at: number | null }

export function parseReadFlip(body: unknown): ReadFlip | null {
  const b = (body ?? {}) as { fan_id?: unknown; unread?: unknown; at?: unknown };
  if (b.unread !== 0 && b.unread !== 1) return null;
  const fanId = b.fan_id === "all" ? null
    : typeof b.fan_id === "number" || (typeof b.fan_id === "string" && b.fan_id !== "") ? b.fan_id : undefined;
  const at = typeof b.at === "number" && Number.isFinite(b.at) ? b.at : null;
  return fanId === undefined ? null : { fanId, unread: b.unread === 1, at };
}

export function isUnreadList(key: readonly unknown[]): boolean {
  return isPlainUnread(decodeChatsKey(key));
}

function isPlainUnread(k: ChatsKey): boolean {
  return k.filter === "unread" && k.listId === null && k.query === null && k.order === "recent";
}

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
  // flip.at is taken before the platform write: a message newer than it stays unread.
  const newer = (c: OFChatItem) => !flip.unread && flip.at != null && rowNewerThan(c, flip.at);
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

export interface RestrictFlip { fanId: FanId; restricted: boolean }

export function parseRestrictFlip(body: unknown): RestrictFlip | null {
  const b = (body ?? {}) as { fan_id?: unknown; restricted?: unknown };
  if (typeof b.restricted !== "boolean") return null;
  if (!(typeof b.fan_id === "number" || (typeof b.fan_id === "string" && b.fan_id !== ""))) return null;
  return { fanId: b.fan_id, restricted: b.restricted };
}

export function restrictedRow(c: OFChatItem, restricted: boolean): OFChatItem {
  // OF answers a restricted chat canSendMessage:false, canNotSendReason:"muted".
  let { canSendMessage, canNotSendReason } = c;
  if (restricted && canSendMessage !== false) [canSendMessage, canNotSendReason] = [false, "muted"];
  if (!restricted && canNotSendReason === "muted") [canSendMessage, canNotSendReason] = [true, null];
  const isRestricted = restricted || undefined;
  const badgeExcluded = (restricted || canSendMessage === false) || undefined;
  const wu = c.withUser;
  if (canSendMessage === c.canSendMessage && canNotSendReason === c.canNotSendReason
    && isRestricted === (wu.isRestricted || undefined) && badgeExcluded === (wu.badgeExcluded || undefined)) return c;
  const withUser = { ...wu, isRestricted, badgeExcluded };
  if (!isRestricted) delete withUser.isRestricted;
  if (!badgeExcluded) delete withUser.badgeExcluded;
  return { ...c, canSendMessage, canNotSendReason, withUser };
}

export function applyRestrictFlip<T extends ChatPages | undefined>(data: T, accountId: string, flip: RestrictFlip): T {
  if (!data?.pages) return data;
  const isRow = fanRowMatcher(accountId, flip.fanId);
  let changed = false;
  const pages = data.pages.map((p) => {
    if (!p.rows.some(isRow)) return p;
    const rows = p.rows.map((c) => (isRow(c) ? restrictedRow(c, flip.restricted) : c));
    if (rows.every((c, i) => c === p.rows[i])) return p;
    changed = true;
    return { ...p, rows };
  });
  return changed ? { ...data, pages } : data;
}

export type ChatsPatch = (data: ChatPages, ctx: { key: readonly unknown[]; observed: boolean; replay: boolean }) => ChatPages;

interface ChatsFact { accountId: string; seq: number; patch: ChatsPatch }

// Longer than any chat-list read (a Refresh walks pages one by one).
export const JOURNAL_MS = 10 * 60_000;
const JOURNAL_MAX = 1_000;
const journals = new WeakMap<QueryClient, ChatsFact[]>();
const seen = new WeakMap<object, number>();
let lastSeq = 0;

export function localSeq(): number {
  lastSeq = Math.max(lastSeq + 1, Date.now());
  return lastSeq;
}

// Every live chats write goes here: the journal replays in order, so it must hold them all.
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
    for (const p of next.pages) seen.set(p, lastSeq);
    patchQueryData<ChatPages>(qc, q.queryKey, () => next);
  }
}

function replayJournal(qc: QueryClient, key: readonly unknown[], next: unknown): unknown {
  const data = next as ChatPages | undefined;
  if (!data?.pages?.length) return next;
  const k = decodeChatsKey(key);
  const since = data.pages.map((p) => seen.get(p) ?? (p as StampedPage).askedSeq ?? -Infinity);
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

export const LIVE_ROW_MS = 20 * 60_000;

function lastMessageMs(c: OFChatItem): number {
  const at = c.lastMessage?.createdAt;
  return at ? Date.parse(toUtcIso(at)) : NaN;
}

function keepMissingCreatorRows(prev: ChatPages, next: ChatPages) {
  return (next.pages as StampedPage[]).map((page, i) => {
    if (!page.missing?.length) return undefined;
    const missing = new Set(page.missing);
    const fromMissingCreator = (row: OFChatItem) => missing.has(row.__accountId ?? "");
    const overflow = i === next.pages.length - 1
      ? prev.pages.slice(i + 1).flatMap((p) => p.rows.filter(fromMissingCreator))
      : [];
    return { fromMissingCreator, overflow };
  });
}

function keepLiveRows(
  page: StampedPage, shown: ReadonlyMap<string, OFChatItem>, view: ChatsKey, head: boolean, headAuthoritative: boolean,
) {
  const floor = (page.askedAt ?? Date.now()) - LIVE_ROW_MS;
  const live = (c: OFChatItem) => lastMessageMs(c) >= floor;
  const rows = page.rows.map((c) => {
    const was = shown.get(chatRowKey(c));
    if (!was || was === c || !live(was) || !rowNewerThan(was, lastMessageMs(c))) return c;
    if (String(was.lastMessage?.id) === String(c.lastMessage?.id)) return c;
    return was;
  });
  if (!head || headAuthoritative) return { rows };

  const tails = new Map(page.rows.map((row) => [row.__accountId ?? "", lastMessageMs(row)]));
  const moreAccounts = new Set(page.moreAccounts ?? (page.hasMore ? view.accountKey.split(",") : []));
  const keepOnHead = (c: OFChatItem) => {
    const accountId = c.__accountId ?? "";
    return live(c) && viewAdmits(view, c)
      && (!moreAccounts.has(accountId) || !(lastMessageMs(c) <= (tails.get(accountId) ?? NaN)));
  };
  return { rows, keepOnHead };
}

function reconcileReplayTail<T extends ChatPages>(prev: ChatPages, next: T, view: ChatsKey): T {
  const cap = CHAT_AUTO_PAGES_MAX;

  const sort = chatSort(view);
  const tails = new Map(next.pages[cap - 1].rows.map((row) => [row.__accountId, row]));
  const inNext = new Set(next.pages.flatMap((page) => page.rows.map(chatRowKey)));
  const displaced = prev.pages.flatMap((page) => page.rows).filter((row) => {
    const tail = tails.get(row.__accountId);
    const key = chatRowKey(row);
    if (inNext.has(key)) return false;
    inNext.add(key);
    return !!tail && sort(row, tail) > 0;
  });
  if (!displaced.length) return next;
  const pages = next.pages.slice();
  pages[cap] = { ...pages[cap], rows: [...pages[cap].rows, ...displaced].sort(sort) };
  return { ...next, pages };
}

function chatSort(view: ChatsKey) {
  const cmp = tokenOf(view.accountKey) ? compareCellChats : compareChats;
  return view.order === "old" ? (a: OFChatItem, b: OFChatItem) => cmp(b, a) : cmp;
}

export function preserveChatRows<T extends ChatPages | undefined>(
  key: readonly unknown[], prev: ChatPages | undefined, incoming: T, fresh: (i: number) => boolean,
): T {
  if (!prev?.pages?.length || !incoming?.pages?.length) return incoming;
  const view = decodeChatsKey(key);
  const cap = CHAT_AUTO_PAGES_MAX;
  const replay = incoming.pages.length > cap && !fresh(cap) && incoming.pages.slice(0, cap).every((_, i) => fresh(i));
  const freshVersions = incoming.pages[0].splitVersions;
  const splitChanged = replay && [...prev.pages, ...incoming.pages].some((page) =>
    replaceEqualDeep(freshVersions, page.splitVersions) !== freshVersions);
  const trim = replay && (!view.unfiltered || splitChanged);
  const next = trim
    ? { ...incoming, pages: incoming.pages.slice(0, cap), pageParams: incoming.pageParams.slice(0, cap) }
    : replay ? reconcileReplayTail(prev, incoming, view) : incoming;
  if (splitChanged) return next;
  const shown = new Map<string, OFChatItem>();
  for (const p of prev.pages) for (const c of p.rows) if (!shown.has(chatRowKey(c))) shown.set(chatRowKey(c), c);
  const inNext = new Set(next.pages.flatMap((p) => p.rows.map(chatRowKey)));
  const sort = chatSort(view);
  const missing = keepMissingCreatorRows(prev, next);
  const headAuthoritative = trim;
  const pages = (next.pages as StampedPage[]).map((page, i) => {
    if (!fresh(i)) return page;
    const { rows, keepOnHead } = keepLiveRows(page, shown, view, i === 0, headAuthoritative);
    const failed = missing[i];
    const kept = (prev.pages[i]?.rows ?? []).filter((c) =>
      !inNext.has(chatRowKey(c)) && (failed?.fromMissingCreator(c) || keepOnHead?.(c)));
    for (const c of kept) inNext.add(chatRowKey(c));
    for (const c of failed?.overflow ?? []) {
      const key = chatRowKey(c);
      if (inNext.has(key)) continue;
      kept.push(c);
      inNext.add(key);
    }
    if (!kept.length && rows.every((row, j) => row === page.rows[j])) return page;
    return { ...page, rows: [...rows, ...kept].sort(sort) };
  });
  return pages.every((page, i) => page === next.pages[i]) ? next : { ...next, pages };
}

// Every chats query, prefetch too, must set this as structuralSharing (a query keeps its last fetch's options), or an in-flight read undoes a live write.
export function commitChatPages(qc: QueryClient, key: readonly unknown[], share: (prev: unknown, next: unknown) => unknown) {
  return (prev: unknown, next: unknown): unknown => {
    const before = prev as ChatPages | undefined;
    const incoming = next as ChatPages | undefined;
    const replayed = replayJournal(qc, key, next) as ChatPages | undefined;
    const kept = preserveChatRows(key, before, replayed, (i) => {
      const page = incoming?.pages[i];
      return !!page && page !== before?.pages[i] && !seen.has(page);
    });
    const out = share(prev, kept) as ChatPages | undefined;
    for (const p of out?.pages ?? []) seen.set(p, lastSeq);
    return out;
  };
}
