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
 */

import type { InfiniteData } from "@tanstack/react-query";

import type { OFChatItem } from "@/lib/relay";
import { sameUserId, type FanId } from "@/lib/fanId";

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

/** One chats cache after a manual send to `fanId`: the row (only a row
 *  already there, never a new one) gets the message as its preview with
 *  unread cleared; the unfiltered list lifts it to the top, a filtered /
 *  folder / search view patches it in place (reordering it would shuffle
 *  rows the user didn't touch). Same `data` when the fan isn't in it. */
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
    (target) => target && {
      ...target,
      hasUnread: false,
      unreadMessagesCount: 0,
      lastMessage: {
        ...(target.lastMessage ?? { id: 0 }),
        id: target.lastMessage?.id ?? 0,
        text: msg.text,
        fromUser: { id: msg.fromUserId, name: msg.fromUserName },
        createdAt: nowIso,
        mediaCount: msg.mediaCount,
        isFree: msg.price === 0,
      },
    },
    { inPlace: !decodeChatsKey(key).unfiltered },
  );
  return pages === data.pages ? data : { ...data, pages };
}
