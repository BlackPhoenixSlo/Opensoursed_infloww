"use client";


import { useEffect, useRef } from "react";
import {
  infiniteQueryOptions, useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData, type QueryClient, type QueryKey,
} from "@tanstack/react-query";

import { relay, type RelayContext, type VaultList, type VaultListsResp, type VaultMedia, type VaultTypeCounts, type VaultMediaResp } from "@/lib/relay";
import { perfDelivered, perfError, perfLog, perfOpId } from "@/lib/perfLog";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { type FanId } from "@/lib/fanId";
import { mirrorThumbSrc } from "@/lib/mediaUrl";
import { invalidateVaultQueries, vaultReadOwners } from "@/lib/vaultInvalidation";

const PAGE = 24;

export interface ChatterFolderGrant {
  folder_id: FanId;
  folder_name: string | null;
}

export interface ChatterFolderAccessResp {
  account_id: string;
  restricted: boolean;
  folders: ChatterFolderGrant[];
}

export function useChatterFolderAccess(accountId: string | null, enabled = true) {
  const { user } = useUser();
  const { chatter } = useChatter();
  const isChatterOnly = !user && !!chatter;
  return useQuery<ChatterFolderAccessResp>({
    queryKey: ["chatter", "folder-access", accountId],
    enabled: enabled && isChatterOnly && !!accountId,
    queryFn: () =>
      relay.get<ChatterFolderAccessResp>(
        `/chatter/me/folder-access?account_id=${encodeURIComponent(accountId!)}`,
      ),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

export async function fetchAllVaultLists(
  ctx: RelayContext, { refresh = false, revalidate = false }: { refresh?: boolean; revalidate?: boolean } = {},
): Promise<VaultListsResp> {
  const LISTS_PAGE = 50;
  const bypass = refresh ? "&refresh=1" : revalidate ? "&revalidate=1" : "";
  const merged: VaultList[] = [];
  let all: VaultTypeCounts | undefined;
  let offset = 0;
  for (let page = 0; page < 20; page++) {
    const r = await relay.get<VaultListsResp>(
      `/api/of/v2/vault/lists?view=main&limit=${LISTS_PAGE}&offset=${offset}${bypass}`,
      ctx,
    );
    if (page === 0 && r.all) {
      const { photosCount, videosCount, gifsCount, audiosCount } = r.all;
      all = { photosCount, videosCount, gifsCount, audiosCount };
    }
    const rows = r.list ?? [];
    merged.push(...rows);
    if (!r.hasMore || rows.length === 0) break;
    offset += LISTS_PAGE;
  }
  return { list: merged.map((l) => stableCovers(l, ctx.accountId)), hasMore: false, ...(all && { all }) };
}

// vault-lists is persisted: OF-signed cover urls are IP-bound and expire, so covers use the relay's stable thumb.
export function stableCovers(l: VaultList, accountId: string | null | undefined): VaultList {
  if (!l.medias) return l;
  const medias = accountId
    ? l.medias.flatMap((m) => (m?.id != null ? [{ ...m, url: mirrorThumbSrc(accountId, m.id) }] : []))
    : [];
  return { ...l, medias };
}

export function vaultListsKey(accountId: string | null) {
  return ["vault-lists", accountId] as const;
}

export function vaultMediaKey(accountId: string | null) {
  return ["vault-media", accountId] as const;
}

async function readVaultLists(accountId: string | null, refresh = false): Promise<VaultListsResp> {
  const opId = perfOpId("vault.lists");
  perfLog(opId, "vault.lists", "requested", { accountId });
  try {
    const result = await fetchAllVaultLists({ accountId: accountId ?? undefined }, { refresh });
    perfDelivered(opId, "vault.lists", { count: (result.list ?? []).length });
    return result;
  } catch (err) {
    perfError(opId, "vault.lists", { message: (err as Error)?.message });
    throw err;
  }
}

export function useVaultLists(accountId: string | null, enabled = true, includeEmpty = false) {
  const qc = useQueryClient();
  const q = useQuery<VaultListsResp>({
    queryKey: vaultListsKey(accountId),
    enabled: enabled && !!accountId,
    queryFn: () => readVaultLists(accountId),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    select: (d) => ({
      list: (d.list ?? []).filter(
        (l: VaultList) => l.type === "custom" && (includeEmpty || l.hasMedia),
      ),
      all: d.all,
    }),
  });
  const manual = useMutation({
    mutationFn: (id: string) => readVaultLists(id, true),
    retry: 1,
    onSuccess: async (data, id) => {
      const queryKey = vaultListsKey(id);
      await qc.cancelQueries({ queryKey, exact: true });
      qc.setQueryData(queryKey, data);
    },
  });
  const currentRefresh = manual.variables === accountId;
  return {
    ...q,
    refresh: () => { if (accountId) manual.mutate(accountId); },
    isRefreshing: currentRefresh && manual.isPending,
    refreshFailed: currentRefresh && manual.isError,
  };
}

export interface UseVaultMediaOpts {
  accountId: string | null;
  type?: "all" | "photo" | "video" | "gif" | "audio";
  listId?: FanId | null;
  enabled?: boolean;
  sort?: "newest" | "oldest";
  query?: string;
}

export async function dropRelayVaultCache(accountId: string): Promise<void> {
  try {
    await relay.post("/admin/vault/cache/invalidate", undefined, { accountId });
  } catch {
  }
}

function vaultMediaParams(opts: Omit<UseVaultMediaOpts, "enabled">, offset: number): URLSearchParams {
  const { type = "all", listId = null, sort = "newest", query = "" } = opts;
  const params = new URLSearchParams();
  params.set("limit", String(PAGE));
  params.set("offset", String(offset));
  params.set("type", type);
  params.set("sort", sort === "oldest" ? "asc" : "desc");
  if (listId != null) params.set("list_id", String(listId));
  if (query.trim()) params.set("query", query.trim());
  return params;
}

function ownVaultRead(qc: QueryClient, queryKey: QueryKey) {
  const cache = qc.getQueryCache();
  const query = cache.build(qc, { queryKey });
  const token = Symbol();
  vaultReadOwners.set(query, token);
  let valid = true;
  let cancelling = false;
  const stop = cache.subscribe((event) => {
    if (event.query !== query) return;
    if (event.type === "removed") valid = false;
    if (event.type !== "updated") return;
    const action = event.action;
    if ((action.type === "fetch" && !action.meta?.fetchMore)
        || (action.type === "success" && (action.manual || !query.state.fetchMeta?.fetchMore))
        || action.type === "invalidate"
        || (action.type === "setState" && !cancelling)) valid = false;
  });
  return {
    query,
    current: () => valid && vaultReadOwners.get(query) === token
      && cache.find({ queryKey, exact: true }) === query,
    cancel: () => {
      cancelling = true;
      try { return qc.cancelQueries({ queryKey, exact: true }); }
      finally { cancelling = false; }
    },
    release: () => {
      stop();
      if (vaultReadOwners.get(query) === token) vaultReadOwners.delete(query);
    },
  };
}

async function writeAfterVaultPaging(
  read: ReturnType<typeof ownVaultRead>, unchanged: boolean, write: () => void,
): Promise<void> {
  const q = read.query;
  while (read.current() && q.state.fetchStatus !== "idle") {
    if (!q.state.fetchMeta?.fetchMore) return;
    if (unchanged) await q.promise?.catch(() => {});
    else await read.cancel();
  }
  if (read.current()) write();
}

export async function revalidateVaultLists(qc: QueryClient, accountId: string): Promise<void> {
  const key = vaultListsKey(accountId);
  const read = ownVaultRead(qc, key);
  try {
    const r = await fetchAllVaultLists({ accountId }, { revalidate: true });
    if (read.current() && read.query.state.fetchStatus === "idle") qc.setQueryData(key, r);
  } finally { read.release(); }
}

export function useVaultListsRevalidated(accountId: string | null) {
  const qc = useQueryClient();
  const q = useVaultLists(accountId);
  const doneFor = useRef<string | null>(null);
  const settled = q.isSuccess && q.fetchStatus === "idle";
  useEffect(() => {
    if (!accountId || !settled || doneFor.current === accountId) return;
    doneFor.current = accountId;
    revalidateVaultLists(qc, accountId).catch(() => {});
  }, [qc, accountId, settled]);
  return q;
}

const sameIds = (a: VaultMediaResp, b: VaultMediaResp): boolean => {
  const x = a.list ?? [], y = b.list ?? [];
  return x.length === y.length && x.every((m, i) => m.id === y[i].id) && !!a.hasMore === !!b.hasMore;
};

export async function revalidateVaultMediaFirstPage(
  qc: QueryClient, opts: Omit<UseVaultMediaOpts, "enabled">,
): Promise<void> {
  const { queryKey } = vaultMediaQuery(opts);
  const read = ownVaultRead(qc, queryKey);
  const old = qc.getQueryData(queryKey);
  try {
    const params = vaultMediaParams(opts, 0);
    params.set("revalidate", "1");
    const fresh = await relay.get<VaultMediaResp>(
      `/api/of/v2/vault/media?${params.toString()}`, { accountId: opts.accountId ?? undefined },
    );
    if (!old?.pages.length) return;
    const unchanged = sameIds(old.pages[0], fresh);
    await writeAfterVaultPaging(read, unchanged, () => qc.setQueryData(queryKey, (current) => {
      if (!read.current() || !current) return undefined;
      return unchanged
        ? { ...current, pages: [fresh, ...current.pages.slice(1)] }
        : { pages: [fresh], pageParams: [0] };
    }));
  } finally { read.release(); }
}

export async function revalidateLoadedVaultPages(qc: QueryClient, accountId: string): Promise<void> {
  const root = vaultMediaKey(accountId);
  const active = qc.getQueryCache().findAll({ queryKey: root, type: "active" });
  void invalidateVaultQueries(qc, { queryKey: root, refetchType: "none" });
  await Promise.allSettled(active.map(async (q) => {
    const read = ownVaultRead(qc, q.queryKey);
    try {
      const [, , type, listId, sort, query] = q.queryKey as [
        string, string, UseVaultMediaOpts["type"], FanId | null, UseVaultMediaOpts["sort"], string,
      ];
      const opts: Omit<UseVaultMediaOpts, "enabled"> = { accountId, type, listId, sort, query };
      const data = qc.getQueryData<InfiniteData<VaultMediaResp, number>>(q.queryKey);
      if (!data?.pages.length) return;
      const pages: VaultMediaResp[] = [];
      for (const offset of data.pageParams) {
        if (!read.current()) return;
        const params = vaultMediaParams(opts, offset);
        params.set("revalidate", "1");
        pages.push(await relay.get<VaultMediaResp>(`/api/of/v2/vault/media?${params.toString()}`, { accountId }));
        if (!pages[pages.length - 1].hasMore) break;
      }
      const unchanged = pages.length === data.pages.length && pages.every((page, i) => sameIds(data.pages[i], page));
      await writeAfterVaultPaging(read, unchanged, () => qc.setQueryData<InfiniteData<VaultMediaResp, number>>(q.queryKey, (current) => {
        if (!read.current() || !current) return undefined;
        return unchanged
          ? { ...current, pages: [...pages, ...current.pages.slice(pages.length)] }
          : { pages, pageParams: data.pageParams.slice(0, pages.length) };
      }));
    } finally { read.release(); }
  }));
}

export function vaultMediaQuery(
  opts: Omit<UseVaultMediaOpts, "enabled">,
  { priority }: { priority?: "background" } = {},
) {
  const { accountId, type = "all", listId = null, sort = "newest", query = "" } = opts;
  const queryTrimmed = query.trim();
  return infiniteQueryOptions({
    queryKey: [...vaultMediaKey(accountId), type, listId, sort, queryTrimmed],
    initialPageParam: 0,
    getNextPageParam: (last: VaultMediaResp, all: VaultMediaResp[]) =>
      last.hasMore ? all.length * PAGE : undefined,
    queryFn: async ({ pageParam, signal }) => {
      const params = vaultMediaParams(opts, (pageParam as number) ?? 0);
      const offset = (pageParam as number) ?? 0;
      const opId = perfOpId("vault.media");
      perfLog(opId, "vault.media", "requested", {
        accountId, type, listId, offset, phase: offset === 0 ? "initial" : "page",
      });
      try {
        const r = await relay.get<VaultMediaResp>(
          `/api/of/v2/vault/media?${params.toString()}`,
          { accountId: accountId ?? undefined, priority },
          signal,
        );
        perfDelivered(opId, "vault.media", {
          count: (r.list ?? []).length, hasMore: !!r.hasMore, offset,
        });
        return r;
      } catch (err) {
        perfError(opId, "vault.media", {
          message: (err as Error)?.message, offset, aborted: signal?.aborted,
        });
        throw err;
      }
    },
    staleTime: 3 * 24 * 60 * 60_000,
  });
}

export function useVaultMedia(opts: UseVaultMediaOpts) {
  const { accountId, enabled = true } = opts;
  const qc = useQueryClient();

  const q = useInfiniteQuery({
    ...vaultMediaQuery(opts),
    enabled: enabled && !!accountId,
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey?.[1] === accountId ? prev : undefined,
  });

  useEffect(() => {
    if (q.data?.pages.length === 1 && q.hasNextPage && !q.isFetchingNextPage) {
      q.fetchNextPage();
    }
  }, [q.data?.pages.length, q.hasNextPage, q.isFetchingNextPage, q]);

  const items: VaultMedia[] = (q.data?.pages ?? []).flatMap((p) => p.list ?? []);
  return {
    items,
    hasMore: !!q.hasNextPage,
    isLoading: q.isLoading,
    isFetching: q.isFetching,
    isFetchingNextPage: q.isFetchingNextPage,
    isPlaceholderData: q.isPlaceholderData,
    error: q.error,
    loadMore: () => {
      if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage();
    },
    refresh: async () => {
      qc.removeQueries({ queryKey: vaultMediaKey(accountId) });
      qc.removeQueries({ queryKey: vaultListsKey(accountId) });
      qc.removeQueries({ queryKey: ["wall-media", accountId] });
      if (accountId) await dropRelayVaultCache(accountId);
      return q.refetch();
    },
  };
}
