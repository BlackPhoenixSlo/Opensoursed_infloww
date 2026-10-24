"use client";

/**
 * useRecentChatsLocal — instant-load seed for the inbox.
 *
 * Reads the LOCAL `chats` table via /admin/chats/recent. The table is
 * populated by the WS transcoder, so it carries every chat we've ever
 * seen an event for — including names + avatars cached on the fans
 * row. Sub-50ms because SQLite is indexed on last_message_at.
 *
 * Used by ChatList as a fallback display while the cold `/chats` OF
 * fetch is still in flight: 10–25 rows render instantly, the user can
 * click into one, and the live OF data replaces it once it arrives.
 */

import { replaceEqualDeep, useQuery } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { chatRowKey } from "./useChatList";

interface RecentChatsResp {
  list: OFChatItem[];
  source: string;
}

/** The seed's structural sharing, by row as `shareChatPages` does for the
 *  chats query: each row is shared with the previous row of the same
 *  (accountId, fanId), not the one at the same index. A live message moves its
 *  row to the top (useInboxRealtime), shifting every row above its old place
 *  down one; React Query's index-wise sharing would hand each of those a new
 *  object and the memoized FanRow would re-render the whole list on every
 *  message (measured: 76% of row renders under a DM flood). Exported for
 *  tests. */
export function shareSeedList(prev: unknown, next: unknown): unknown {
  const p = prev as RecentChatsResp | undefined;
  const n = next as RecentChatsResp | undefined;
  if (!Array.isArray(p?.list) || !Array.isArray(n?.list)) return replaceEqualDeep(prev, next);
  if (p === n) return p;
  const old = new Map<string, OFChatItem>();
  for (const c of p.list) old.set(chatRowKey(c), c);
  let same = p.list.length === n.list.length && p.source === n.source;
  const list = n.list.map((c, i) => {
    const was = old.get(chatRowKey(c));
    const row = was ? replaceEqualDeep(was, c) : c;
    if (same && p.list[i] !== row) same = false;
    return row;
  });
  return same ? p : { ...n, list };
}

export function useRecentChatsLocal(opts: {
  enabled?: boolean;
  limit?: number;
  /** When set, the backend filters to this account_id so seed rows in a
   *  single-model view don't bleed in other accounts' chats. */
  accountId?: string | null;
} = {}): { rows: OFChatItem[]; isLoading: boolean } {
  const { enabled = true, limit = 25, accountId = null } = opts;
  const q = useQuery<RecentChatsResp>({
    queryKey: ["chats-local-seed", limit, accountId],
    enabled,
    queryFn: () => {
      const qs = new URLSearchParams();
      qs.set("limit", String(limit));
      if (accountId) qs.set("account_id", accountId);
      return relay.get<RecentChatsResp>(`/admin/chats/recent?${qs.toString()}`);
    },
    // Fresh enough for a session. The OF data replaces it in <2s anyway.
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    structuralSharing: shareSeedList,
  });
  return {
    rows: q.data?.list ?? [],
    isLoading: q.isLoading,
  };
}
