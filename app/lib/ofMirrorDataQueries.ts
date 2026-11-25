"use client";


import { useEffect, useRef } from "react";
import { infiniteQueryOptions, useQueries, useQueryClient } from "@tanstack/react-query";
import { cacheMark, cacheMovedSince } from "@/lib/queryCacheMark";
import { relay, type OFChatItem, type OFUserMini, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { vaultMediaPath, viewOf } from "@/lib/ofMirrorVault";
import { message } from "@/lib/ofMirrorWrites";
import { nextMarker, nextOffset, uniqueRows } from "@/lib/ofMirrorPaging";
import type { ThreadMessage } from "@/lib/ofMirrorThread";
import { sameId, type MorePages } from "@/lib/ofMirrorDom";
import type { MirrorNotification } from "@/lib/ofMirrorFeedsNotifications";

export const USER_LISTS = "/api/of/v2/lists?limit=50";
export const STORIES_FEED = "/api/of/v2/stories";
export const STREAMS_FEED = "/api/of/v2/streams/feed";
export const VAULT_LISTS = "/api/of/v2/vault/lists?view=main&limit=50";
export const chatPath = (chat: string) => `/api/of/v2/chats/${encodeURIComponent(chat)}`;
export const vaultMediaOf = (params: { get(key: string): string | null }) => vaultMediaPath(viewOf(params));

export function mirrorQuery<T = unknown>(accountId: string | null, path: string | null, enabled: boolean) {
  return {
    queryKey: ["of-mirror-data", accountId, path],
    queryFn: () => relay.get<T>(path!, { accountId }),
    enabled: !!accountId && !!path && enabled,
    staleTime: 60_000,
    retry: false,
  };
}

export function useRevalidate(accountId: string | null, path: string | null, cached: { isPending: boolean }) {
  const qc = useQueryClient();
  const done = useRef<string | null>(null);
  const ready = !!accountId && !!path && !cached.isPending;
  useEffect(() => {
    const at = `${accountId}|${path}`;
    if (!ready || done.current === at) return;
    done.current = at;
    const key = mirrorQuery(accountId, path, true).queryKey;
    // A write meanwhile (a vault folder write's refetch) is newer than this read.
    const before = cacheMark(qc, key);
    relay.get(path!, { accountId }, undefined, { refresh: true }).then(
      (fresh) => { if (!cacheMovedSince(before, cacheMark(qc, key))) qc.setQueryData(key, fresh); },
      () => {},
    );
  }, [ready, accountId, path, qc]);
}

export const TRANSACTIONS = "/api/of/v2/payouts/transactions";
// OF's page size (app.js limit: 10).
export const TRANSACTIONS_PAGE = 10;

export const usersListPath = (ids: readonly string[]) => `/api/of/v2/users/list?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`;

export function chatUser<U extends OFUserMini>(u: U): U {
  const custom = u.displayName?.trim();
  return custom ? { ...u, name: custom } : u;
}

// /chats sends each withUser bare (skip_users=all); /users/list answers [] when it resolves none.
export function withChatUsers(chats: OFChatItem[], users: unknown): OFChatItem[] {
  const byId = users && typeof users === "object" && !Array.isArray(users) ? (users as Record<string, OFUserMini>) : {};
  return chats.map((c) => {
    const u = byId[String(c.withUser.id)];
    return u ? { ...c, withUser: chatUser({ ...c.withUser, ...u, id: c.withUser.id }) } : c;
  });
}

export type PartnersRead = { isPending: boolean; data?: unknown };

export function usePageUsers<T>(accountId: string | null, pages: readonly (readonly T[])[], idOf: (row: T) => unknown, enabled: boolean) {
  const ids = pages.map((rows) => [...new Set(rows.flatMap((r) => (idOf(r) != null ? [String(idOf(r))] : [])))].sort());
  const reads = useQueries({ queries: ids.map((page) => mirrorQuery(accountId, page.length ? usersListPath(page) : null, enabled)) });
  return { ids, reads, key: reads.map((r) => `${r.status}:${r.dataUpdatedAt}`).join(",") };
}

// A page with no partner ids is a disabled query, which TanStack reports as pending forever.
export const pendingPartners = (pageIds: readonly string[][], partners: readonly PartnersRead[]) =>
  partners.some((p, i) => !!pageIds[i]?.length && p.isPending);

export function chatRowsOf(pages: readonly OFChatItem[][], pageIds: readonly string[][], partners: readonly PartnersRead[], known: Record<string, OFUserMini>): OFChatItem[] | undefined {
  const seen = new Set<string>();
  const rows: OFChatItem[] = [];
  for (let i = 0; i < pages.length; i++) {
    const waiting = !!pageIds[i]?.length && !!partners[i]?.isPending;
    if (waiting && !pageIds[i].some((id) => Object.hasOwn(known, id))) return i === 0 ? undefined : rows;
    for (const c of withChatUsers(pages[i].filter((c) => c?.withUser), waiting ? known : partners[i]?.data)) {
      const id = String(c.withUser.id);
      if ((waiting && !Object.hasOwn(known, id)) || seen.has(id)) continue;
      seen.add(id);
      rows.push(c);
    }
  }
  return rows;
}

export const isVaultPage = (page: string) => page.startsWith("vault/");

// hasMore is the only marker OF sends.
export function nextVaultOffset(pages: readonly Partial<VaultMediaResp>[]): number | undefined {
  const last = pages.at(-1);
  return last?.hasMore && last.list?.length ? pages.reduce((n, p) => n + (p.list?.length ?? 0), 0) : undefined;
}

// OF's offset pages overlap (read live: page 2 repeated two of page 1's).
export const vaultPageMedia = (pages: readonly Partial<VaultMediaResp>[]): VaultMedia[] => uniqueRows(pages.flatMap((p) => p.list ?? []));

// Every page uses the relay's refresh=1 (past its day-long vault cache), so no tab, folder or page is a day older than the next.
export function vaultPagesQuery(accountId: string | null, path: string | null) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, path, "pages"],
    queryFn: ({ pageParam }) => relay.get<VaultMediaResp>(`${path}&offset=${pageParam}`, { accountId }, undefined, { refresh: true }),
    initialPageParam: 0,
    getNextPageParam: (_last: VaultMediaResp, pages: VaultMediaResp[]) => nextVaultOffset(pages),
    enabled: !!accountId && !!path,
    staleTime: 60_000,
    retry: false,
  });
}

export function offsetPagesQuery(accountId: string | null, route: string | null, enabled: boolean, next: (last: unknown, pages: unknown[]) => number | undefined = nextOffset) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, route, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(`${route}&offset=${pageParam}`, { accountId }),
    initialPageParam: 0,
    getNextPageParam: next,
    enabled: !!accountId && !!route && enabled,
    staleTime: 60_000,
    retry: false,
  });
}

export function markerPagesQuery(accountId: string | null, route: string | null, enabled: boolean) {
  return infiniteQueryOptions({
    queryKey: ["of-mirror-data", accountId, route, "pages"],
    queryFn: ({ pageParam }) => relay.get<unknown>(pageParam ? `${route}&before_publish_time=${encodeURIComponent(pageParam)}` : route!, { accountId }),
    initialPageParam: null as string | null,
    getNextPageParam: nextMarker,
    enabled: !!accountId && !!route && enabled,
    staleTime: 60_000,
    retry: false,
  });
}

export type PagesState = { isFetchingNextPage: boolean; isFetchNextPageError: boolean; error: unknown; hasNextPage: boolean; fetchNextPage: () => unknown };
export const morePages = (q: PagesState): MorePages => ({
  loading: q.isFetchingNextPage,
  error: q.isFetchNextPageError ? message(q.error) : null,
  next: q.hasNextPage ? () => void q.fetchNextPage() : null,
});

export type ReadState = { isError: boolean; error: unknown; isPending: boolean; isFetchNextPageError?: boolean };
export const feedStatus = (q: ReadState, tpl: ReadState | null): string | null | undefined =>
  q.isError && !q.isFetchNextPageError ? message(q.error) : tpl?.isError ? message(tpl.error) : q.isPending || tpl?.isPending ? null : undefined;

export const MORE_PX = 400;
export const CHATS_PAGE = 20;
// vue-infinite-loading's default distance, as OF's loader.
export const CHATS_MORE_PX = 100;

export function relatedOnly(rows: MirrorNotification[] | undefined, user: string | null): MirrorNotification[] | undefined {
  if (!rows || !user) return rows;
  return rows.filter((n) => sameId((n.user ?? n.fromUser)?.id, user));
}

export const GALLERY_EMPTY_CAP = 5;
// OF's pages always carry media; without this stop the Gallery would page forever.
export function galleryStalled(pages: readonly { list?: unknown[] }[]): boolean {
  const seen = new Set<string>();
  let empty = 0;
  for (const p of pages) {
    let added = 0;
    for (const m of (p.list ?? []) as ThreadMessage[]) {
      if (m?.id == null || seen.has(String(m.id))) continue;
      seen.add(String(m.id));
      added++;
    }
    empty = added ? 0 : empty + 1;
  }
  return empty >= GALLERY_EMPTY_CAP;
}

export function galleryItems(pages: readonly { list?: unknown[] }[]): ThreadMessage[] {
  const seen = new Set<string>();
  const out: ThreadMessage[] = [];
  for (const p of pages) for (const m of (p.list ?? []) as ThreadMessage[]) {
    if (m?.id == null || seen.has(String(m.id))) continue;
    seen.add(String(m.id));
    out.push(m);
  }
  return out;
}
