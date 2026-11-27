"use client";


import { replaceEqualDeep, useQuery, useQueryClient } from "@tanstack/react-query";

import { cellMode } from "@/lib/cellFlag";
import { relay, type OFChatItem } from "@/lib/relay";
import { chatRowKey } from "@/lib/chatsCache";
import { cellToken, mergeCellRows, ROSTER_WAIT_MS, type CellMap } from "@/lib/cellInbox";
import { askCells, useCellMap } from "@/lib/cellMap";

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

async function cellsSeed(m: CellMap, qs: URLSearchParams, limit: number, previous: OFChatItem[]): Promise<RecentChatsResp> {
  const granted = new Set(m.accounts.map((a) => a.account_id));
  const results = await askCells(m, [...granted], undefined, async ({ cell, signal }) => {
    const value = await relay.get<RecentChatsResp>(`/admin/chats/recent?${qs}`, { cellId: cell }, signal);
    return { value: value.list ?? [], partial: [] };
  }, { source: "seed", greyAfterMs: ROSTER_WAIT_MS });
  const answered = new Set(results.flatMap((r) => r.ok ? r.accounts : []));
  const lists = results.flatMap((r) => r.ok ? [r.value] : []);
  lists.push(previous.filter((c) => !answered.has(c.__accountId ?? "")));
  const list = mergeCellRows(lists).filter((c) => granted.has(c.__accountId ?? "")).slice(0, limit);
  return { list, source: "cells" };
}

export function useRecentChatsLocal(opts: {
  enabled?: boolean;
  limit?: number;
  accountId?: string | null;
} = {}): { rows: OFChatItem[]; isLoading: boolean } {
  const { enabled = true, limit = 25, accountId = null } = opts;
  const cells = cellMode();
  const m = useCellMap();
  const qc = useQueryClient();
  const q = useQuery<RecentChatsResp>({
    queryKey: cells ? ["chats-local-seed", limit, accountId, m ? cellToken(m) : ""] : ["chats-local-seed", limit, accountId],
    enabled: enabled && (!cells || !!m),
    queryFn: ({ queryKey }) => {
      const qs = new URLSearchParams();
      qs.set("limit", String(limit));
      if (accountId) qs.set("account_id", accountId);
      if (cells && m && !accountId) return cellsSeed(m, qs, limit, qc.getQueryData<RecentChatsResp>(queryKey)?.list ?? []);
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
