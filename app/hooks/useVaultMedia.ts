"use client";

/**
 * useVaultMedia — paginated reader for the model's vault.
 *
 * Keys on (accountId, type, listId) so switching scope or filter swaps
 * cache cleanly. Pages are appended via loadMore so the user can scroll-
 * fetch in the picker. Returns merged list + hasMore + isLoading + error.
 *
 * No background polling — the vault is owner-managed, refresh is on demand.
 */

import { useCallback, useEffect, useRef } from "react";
import { infiniteQueryOptions, useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext, type VaultList, type VaultListsResp, type VaultMedia, type VaultTypeCounts, type VaultMediaResp } from "@/lib/relay";
import { perfDelivered, perfError, perfLog, perfOpId } from "@/lib/perfLog";
import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import { type FanId } from "@/lib/fanId";
import { mirrorThumbSrc } from "@/lib/mediaUrl";

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

/**
 * Chatter Access (folders): the authoritative folder menu for a RESTRICTED
 * chatter session (DA-3). Only runs for a chatter-only principal — owners
 * (User cookie present) are never restricted, so the query is disabled:
 * not loading, `data` undefined (read as full vault). The folder names come
 * from the backend's denormalised column, not from paginated vault/lists,
 * so the menu is complete even when a folder sits past the lists page.
 */
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
    // Short staleTime so an owner's just-saved restriction takes effect on
    // the chatter's next picker open without a full reload. The backend
    // soft-denies regardless (no leak); this only governs the cosmetic menu.
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

/** Fetch EVERY vault-folder page. OF pages `/vault/lists` (relay caps limit
 *  at 50/page) and built-in pseudo-lists count against the page too, so a
 *  creator with many script folders overflows page 1 — the old single-page
 *  fetch silently dropped everything past it. Walks offsets until hasMore
 *  is false, with a hard page cap so a stuck hasMore can't loop forever.
 *
 *  Every reader/warmer of the ["vault-lists", aid] cache MUST go through
 *  this — a single-page queryFn under the same key would repoison the
 *  cache with a truncated folder list for its whole staleTime. */
export async function fetchAllVaultLists(
  ctx: RelayContext, { refresh = false }: { refresh?: boolean } = {},
): Promise<VaultListsResp> {
  const LISTS_PAGE = 50;
  // `refresh=1`: the relay skips its shared vault cache (a day's TTL) and asks OF.
  const bypass = refresh ? "&refresh=1" : "";
  const merged: VaultList[] = [];
  let all: VaultTypeCounts | undefined;
  let offset = 0;
  for (let page = 0; page < 20; page++) {
    const r = await relay.get<VaultListsResp>(
      `/api/of/v2/vault/lists?view=main&limit=${LISTS_PAGE}&offset=${offset}${bypass}`,
      ctx,
    );
    // OF's whole-vault counts, the counts only: its `all.medias` are signed urls, and this cache is persisted.
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

/** ["vault-lists"] is persisted to the browser, so a folder's covers must not be
 *  OF-signed URLs (IP-bound, dead after ~22 h): a cover with a media id becomes the
 *  relay's stable thumb (`mirrorThumbSrc`), one without is dropped. */
export function stableCovers(l: VaultList, accountId: string | null | undefined): VaultList {
  if (!l.medias) return l;
  const medias = accountId
    ? l.medias.flatMap((m) => (m?.id != null ? [{ ...m, url: mirrorThumbSrc(accountId, m.id) }] : []))
    : [];
  return { ...l, medias };
}

/** The cache root for this model's OF folder list. Exported so nothing has to
 *  spell the literal again — an invalidation that misses by a typo is silent. */
export function vaultListsKey(accountId: string | null) {
  return ["vault-lists", accountId] as const;
}

/** The cache root for this model's LIVE OF media listing. The real keys append
 *  (type, listId, sort, query); this prefix matches every one of them, which is
 *  what an "the vault changed" invalidation wants. */
export function vaultMediaKey(accountId: string | null) {
  return ["vault-media", accountId] as const;
}

/** Vault folders / lists. The model can put items into custom folders;
 *  this drives the picker's folder filter dropdown. OF requires `view=main`.
 *  `refresh()` refetches past the relay's server cache too (a folder made on
 *  OF a minute ago shows up); a plain `refetch()` may get the cached copy. */
export function useVaultLists(accountId: string | null, enabled = true, includeEmpty = false) {
  // Set by `refresh()`, taken by the next queryFn run only.
  const bypassRef = useRef(false);
  const q = useQuery<VaultListsResp>({
    queryKey: vaultListsKey(accountId),
    enabled: enabled && !!accountId,
    queryFn: async () => {
      const opId = perfOpId("vault.lists");
      perfLog(opId, "vault.lists", "requested", { accountId });
      try {
        const refresh = bypassRef.current;
        bypassRef.current = false;
        const r = await fetchAllVaultLists({ accountId: accountId ?? undefined }, { refresh });
        perfDelivered(opId, "vault.lists", { count: (r.list ?? []).length });
        return r;
      } catch (err) {
        perfError(opId, "vault.lists", { message: (err as Error)?.message });
        throw err;
      }
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    select: (d) => ({
      // Only show custom folders — the built-in pseudo-lists like Posts/Stories
      // are useless for picking media to send. media_stickers (Uploads) is
      // built-in too but we leave it; it's where freshly-uploaded items land.
      // includeEmpty=true keeps empty custom folders too — the manage UI needs
      // them (rename/delete/add-media), the picker doesn't (can't pick nothing).
      list: (d.list ?? []).filter(
        (l: VaultList) => l.type === "custom" && (includeEmpty || l.hasMedia),
      ),
      all: d.all,
    }),
  });
  const { refetch } = q;
  const refresh = useCallback(() => {
    bypassRef.current = true;
    return refetch();
  }, [refetch]);
  return Object.assign(q, { refresh });
}

export interface UseVaultMediaOpts {
  accountId: string | null;
  type?: "all" | "photo" | "video" | "gif" | "audio";
  /** Folder id. FanId, not number: Fansly album ids are snowflakes >2^53.
   *  Only ever compared and echoed back into `list_id`, never arithmetic. */
  listId?: FanId | null;
  enabled?: boolean;
  /** OF honors server-side ordering — "oldest" maps to `sort=asc`. Kept out
   *  of client-side reversal so pagination stays correct (older pages append
   *  at the bottom, not the top). */
  sort?: "newest" | "oldest";
  /** OF-native vault search (wire param `query`). Empty = no filter. */
  query?: string;
}

/** The relay forgets every cached vault/lists and vault/media answer of one Creator, so the next read of each
 *  goes to OnlyFans (POST /admin/vault/cache/invalidate). Best effort: a failed call is swallowed (the caller's
 *  refetch still runs, from the cache). Here, in the leaf module, so hooks/vaultRefresh and this file's `refresh()`
 *  share it without an import cycle. */
export async function dropRelayVaultCache(accountId: string): Promise<void> {
  try {
    await relay.post("/admin/vault/cache/invalidate", undefined, { accountId });
  } catch {
    // best effort
  }
}

/** The one key, pager and fetcher for a live vault listing view: useVaultMedia
 *  and a background Vault warm (on the background lane)
 *  both take them from here. */
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
      const params = new URLSearchParams();
      params.set("limit", String(PAGE));
      params.set("offset", String(pageParam ?? 0));
      params.set("type", type);
      // OF orders server-side; asc = oldest-first. Sorting here (not a
      // client reverse) keeps infinite-scroll appending in the right place.
      params.set("sort", sort === "oldest" ? "asc" : "desc");
      if (listId != null) params.set("list_id", String(listId));
      if (queryTrimmed) params.set("query", queryTrimmed);
      // Per-fetch perf op. `vault.media` covers the initial fetch (the one
      // the user feels as "vault open"), filter switches (a fresh fetch
      // under a new queryKey), and infinite-scroll page loads. We tag the
      // op with offset so the log distinguishes them at a glance.
      const offset = (pageParam as number) ?? 0;
      const opId = perfOpId("vault.media");
      perfLog(opId, "vault.media", "requested", {
        accountId, type, listId, offset, phase: offset === 0 ? "initial" : "page",
      });
      // Forward the abort signal so switching folder/type cancels the
      // previous page fetch instead of letting it land into a stale key.
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
    // Keep the previous pages while a FILTER changes (type, folder, sort,
    // search) — that is what makes those switches feel instant. Never across a
    // model change: `keepPreviousData` there painted one creator's vault under
    // another creator's name, with no loading state to say otherwise, and the
    // only clue that the page had not switched yet was recognising the media.
    placeholderData: (prev, prevQuery) =>
      prevQuery?.queryKey?.[1] === accountId ? prev : undefined,
  });

  // Once page 1 lands, eagerly pull page 2 in the background so the first
  // scroll past the fold is already cached. Guarded on `pages.length === 1`
  // so we only fire the chained prefetch once per cache miss — not on
  // every render and not after the user has already scrolled further.
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
    /** Hard refresh — drops every cached page for this account's vault
     *  (any type/listId combo, the wall-media cache, and the lists cache)
     *  so the next render starts from a blank slate. The plain `q.refetch()`
     *  only refires the queries this hook owns; the picker switches the
     *  `type` chip a lot, so we want every adjacent cache nuked too. */
    refresh: async () => {
      // Await the server-side drop before refetching: the queries removed
      // here refetch with no bypass of their own, so a still-cached relay row
      // would answer them. The drop is one local POST, ~30-80ms next to the
      // OF roundtrip after it.
      qc.removeQueries({ queryKey: vaultMediaKey(accountId) });
      qc.removeQueries({ queryKey: vaultListsKey(accountId) });
      qc.removeQueries({ queryKey: ["wall-media", accountId] });
      if (accountId) await dropRelayVaultCache(accountId); // best effort: a failure still refetches
      return q.refetch();
    },
  };
}
