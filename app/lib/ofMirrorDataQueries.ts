"use client";

/** The mirror's Relay reads, cut from ofMirrorData (useOfData runs them): its paths, query options, page and status helpers. */

import { useEffect, useRef } from "react";
import { infiniteQueryOptions, useQueries, useQueryClient } from "@tanstack/react-query";
import { relay, type OFChatItem, type OFUserMini, type VaultMedia, type VaultMediaResp } from "@/lib/relay";
import { vaultMediaPath, viewOf } from "@/lib/ofMirrorVault";
import { message } from "@/lib/ofMirrorWrites";
import { nextMarker, nextOffset, uniqueRows } from "@/lib/ofMirrorPaging";
import type { ThreadMessage } from "@/lib/ofMirrorThread";
import { sameId, type MorePages } from "@/lib/ofMirrorDom";
import type { MirrorNotification } from "@/lib/ofMirrorFeedsNotifications";

/** The Relay paths more than one mirror module reads: one spelling each, so their queries share one cache entry. */
export const USER_LISTS = "/api/of/v2/lists?limit=50";
/** Home's story strip: the creators the Creator follows with stories. */
export const STORIES_FEED = "/api/of/v2/stories";
/** Home's story strip: the live and scheduled streams (OF's streams/feed). */
export const STREAMS_FEED = "/api/of/v2/streams/feed";
export const VAULT_LISTS = "/api/of/v2/vault/lists?view=main&limit=50";
export const chatPath = (chat: string) => `/api/of/v2/chats/${encodeURIComponent(chat)}`;
/** The vault media the page's view (`?list ?type ?field ?sort ?q`) asks for: the Vault page's and the vault dialogs' tiles. */
export const vaultMediaOf = (params: { get(key: string): string | null }) => vaultMediaPath(viewOf(params));

/** The one mirror query for `path` (key `["of-mirror-data", accountId, path]`), fetched with the model's X-Account-Id. */
export function mirrorQuery<T = unknown>(accountId: string | null, path: string | null, enabled: boolean) {
  return {
    queryKey: ["of-mirror-data", accountId, path],
    queryFn: () => relay.get<T>(path!, { accountId }),
    enabled: !!accountId && !!path && enabled,
    staleTime: 60_000,
    retry: false,
  };
}

/**
 * Stale-while-revalidate for a mirrorQuery read the Relay serves from its day-long vault cache (the folder list, a vault
 * dialog's first 24): its cached answer (`cached`) shows at once; once it is in, the same path is read once more past
 * the cache (the Relay's `refresh=1`, which refills it) and that answer takes its place under the same key. Once per
 * model and path while mounted (a page open), never per render; a failed recheck leaves the cached answer.
 */
export function useRevalidate(accountId: string | null, path: string | null, cached: { isPending: boolean }) {
  const qc = useQueryClient();
  const done = useRef<string | null>(null);
  const ready = !!accountId && !!path && !cached.isPending;
  useEffect(() => {
    const at = `${accountId}|${path}`;
    if (!ready || done.current === at) return;
    done.current = at;
    relay.get(path!, { accountId }, undefined, { refresh: true }).then(
      (fresh) => qc.setQueryData(mirrorQuery(accountId, path, true).queryKey, fresh),
      () => {},
    );
  }, [ready, accountId, path, qc]);
}

/** Statements' Earnings' source and OF's page size (app.js `limit: Jg`, 10). */
export const TRANSACTIONS = "/api/of/v2/payouts/transactions";
export const TRANSACTIONS_PAGE = 10;

/** GET /users/list for `ids` (OF's batch user read, a dict by id). */
export const usersListPath = (ids: readonly string[]) => `/api/of/v2/users/list?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`;

/** A chat partner as OF's Messages page names it: its custom name (`displayName`, the Creator's rename of that user) over its name. */
export function chatUser<U extends OFUserMini>(u: U): U {
  const custom = u.displayName?.trim();
  return custom ? { ...u, name: custom } : u;
}

/**
 * The chat list's rows with their partners filled in: /chats sends each `withUser` bare (its id; OF's skip_users=all),
 * so, as on OF's page, the name, @handle and avatar come from /users/list by id (`users`; OF answers `[]` when it
 * resolves none). A partner it did not return keeps the bare id.
 */
export function withChatUsers(chats: OFChatItem[], users: unknown): OFChatItem[] {
  const byId = users && typeof users === "object" && !Array.isArray(users) ? (users as Record<string, OFUserMini>) : {};
  return chats.map((c) => {
    const u = byId[String(c.withUser.id)];
    return u ? { ...c, withUser: chatUser({ ...c.withUser, ...u, id: c.withUser.id }) } : c;
  });
}

/** A chat list page's /users/list read, as useQueries gives it. */
export type PartnersRead = { isPending: boolean; data?: unknown };

/**
 * Each page's users, for rows that carry only their user's id (OF's skip_users=all: the chat list's partners, a feed's
 * authors): one /users/list call a page, its ids sorted for one key, so a next page asks only for its own. `ids` per
 * page, `reads` per page (a dict by id each), `key` standing for `reads` (a new array each render) in a memo's deps.
 */
export function usePageUsers<T>(accountId: string | null, pages: readonly (readonly T[])[], idOf: (row: T) => unknown, enabled: boolean) {
  const ids = pages.map((rows) => [...new Set(rows.flatMap((r) => (idOf(r) != null ? [String(idOf(r))] : [])))].sort());
  const reads = useQueries({ queries: ids.map((page) => mirrorQuery(accountId, page.length ? usersListPath(page) : null, enabled)) });
  return { ids, reads, key: reads.map((r) => `${r.status}:${r.dataUpdatedAt}`).join(",") };
}

/** Whether a page's partners are still being asked for; a page with no partner ids asks nothing (its query is disabled, which TanStack reports as pending for ever). */
export const pendingPartners = (pageIds: readonly string[][], partners: readonly PartnersRead[]) =>
  partners.some((p, i) => !!pageIds[i]?.length && p.isPending);

/**
 * The chat list's rows from its pages, each partner named from its page's /users/list (withChatUsers), a chat on two
 * pages once. A page whose partners are still being asked for: when none of them is `known` (the partners this view
 * resolved so far; a first read) it and the pages after it wait (undefined when it is the first: "Loading chats…", no
 * bare ids); else its known partners' rows show and a new one (a chat that just came in) waits until it is named.
 */
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

/** The Vault page's own pages (vault/index, vault/list, vault/state-*), whose grid loads more as it is scrolled. */
export const isVaultPage = (page: string) => page.startsWith("vault/");

/** OF's next offset after `pages`: the media so far while OF says it has more (its `hasMore`, the only marker it sends). */
export function nextVaultOffset(pages: readonly Partial<VaultMediaResp>[]): number | undefined {
  const last = pages.at(-1);
  return last?.hasMore && last.list?.length ? pages.reduce((n, p) => n + (p.list?.length ?? 0), 0) : undefined;
}

/** The pages' media in order, each media once: OF's offset pages overlap (read live: page 2 repeated two of page 1's). */
export const vaultPageMedia = (pages: readonly Partial<VaultMediaResp>[]): VaultMedia[] => uniqueRows(pages.flatMap((p) => p.list ?? []));

/**
 * The Vault page's media for `path` (vaultMediaOf: 24 a page), page by page with OF's `offset`. Its own key (a composer's
 * vault dialog reads `path` once, with mirrorQuery), still under `["of-mirror-data", accountId]`, so a write's refresh
 * reaches it. Each page is OF's own as it is now (the Relay's `refresh=1`: past its day-long vault cache, which it
 * refills), as OF's Vault reads every page it shows: no tab, folder or page a day older than the next.
 */
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

/** An offset-paged read: `route` (with its query: limit, filters) a page at a time from offset 0 (`next`: nextOffset). */
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

/** A marker-paged read (OF's format=infinite): `route` first, then each page before the last one's tailMarker (nextMarker). */
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
/** An offset-paged read's next page as OF's infinite loading row shows it (MorePages). */
export const morePages = (q: PagesState): MorePages => ({
  loading: q.isFetchingNextPage,
  error: q.isFetchNextPageError ? message(q.error) : null,
  next: q.hasNextPage ? () => void q.fetchNextPage() : null,
});

export type ReadState = { isError: boolean; error: unknown; isPending: boolean; isFetchNextPageError?: boolean };
/**
 * A feed's or table's status: loading until its first page and its borrowed row (`tpl`, when it needs one) are both
 * here, either failing the error; a next page's failure is its own prompt (MorePages), not this.
 */
export const feedStatus = (q: ReadState, tpl: ReadState | null): string | null | undefined =>
  q.isError && !q.isFetchNextPageError ? message(q.error) : tpl?.isError ? message(tpl.error) : q.isPending || tpl?.isPending ? null : undefined;

/** How near the end of the Vault page's (and the chat list's) scroll (px) its next page is asked for. */
export const MORE_PX = 400;
/** The chat list's page size (the Relay assembles OF's pages of 10 up to it). */
export const CHATS_PAGE = 20;
/** How near the visible end (px) the chat list's last row brings its next page: vue-infinite-loading's default distance, OF's loader. */
export const CHATS_MORE_PX = 100;

/** A notifications page for one user (`related_user`): only that user's items (OF filters them; a Relay that does not yet is followed here). */
export function relatedOnly(rows: MirrorNotification[] | undefined, user: string | null): MirrorNotification[] | undefined {
  if (!rows || !user) return rows;
  return rows.filter((n) => sameId((n.user ?? n.fromUser)?.id, user));
}

/** Consecutive pages with no new item after which the Gallery stops asking for more (OF's pages always carry media). */
export const GALLERY_EMPTY_CAP = 5;
/** The Gallery's last GALLERY_EMPTY_CAP pages all brought no new item: stop paging (it would page forever). */
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

/** The Gallery's tiles from its pages, newest first, a message once. */
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
