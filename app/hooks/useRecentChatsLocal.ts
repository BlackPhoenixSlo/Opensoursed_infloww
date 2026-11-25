"use client";


import { replaceEqualDeep, useQuery } from "@tanstack/react-query";

import { relay, type OFChatItem } from "@/lib/relay";
import { chatRowKey } from "@/lib/chatsCache";

interface RecentChatsResp {
  list: OFChatItem[];
  source: string;
}

// Share per (accountId, fanId), not by index: a live message shifts rows and index sharing re-rendered the whole list (76% of row renders under a DM flood).
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
