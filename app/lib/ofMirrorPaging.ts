/** OF's paged reads (offset- and marker-paged, as useInfiniteQuery's getNextPageParam) and their rows: pure. */

/** `{list: [...]}` (or `{chats: [...]}`), or a bare array: the rows; anything else: none. */
export function rowsOf<T>(r: unknown): T[] | undefined {
  if (Array.isArray(r)) return r as T[];
  const o = r as { list?: unknown; chats?: unknown } | null | undefined;
  if (Array.isArray(o?.list)) return o.list as T[];
  if (Array.isArray(o?.chats)) return o.chats as T[];
  return undefined;
}

/**
 * An offset-paged read's next offset after `pages` (OF's `{list, hasMore, nextOffset?}`): OF's `nextOffset` (a list's
 * posts send it), else the rows read so far (Statements' Earnings: OF pages those by `marker` and sends no nextOffset,
 * the Relay by offset); none when OF has no more.
 */
export function nextOffset(last: unknown, pages: unknown[]): number | undefined {
  if (!(last as { hasMore?: unknown } | null)?.hasMore || !rowsOf(last)?.length) return undefined;
  const next = (last as { nextOffset?: unknown }).nextOffset;
  return typeof next === "number" ? next : pages.reduce<number>((n, p) => n + (rowsOf(p)?.length ?? 0), 0);
}

/** Home's feed's and My profile's wall's page size (OF's GET /posts and GET /users/{id}/posts, 20 a page). */
export const POSTS_PAGE = 20;

/**
 * Home's feed's next offset (GET /posts, offset-paged): OF's `{list, hasMore, nextOffset?}` as nextOffset; a bare
 * array (the Relay passes OF's answer as it comes) has more when it is a full page.
 */
export function nextFeedOffset(last: unknown, pages: unknown[]): number | undefined {
  if (!Array.isArray(last)) return nextOffset(last, pages);
  return last.length >= POSTS_PAGE ? pages.reduce<number>((n, p) => n + (rowsOf(p)?.length ?? 0), 0) : undefined;
}

/**
 * My profile's wall's next page (GET /users/{id}/posts?format=infinite): OF's `tailMarker`, sent back as
 * `before_publish_time`, while OF says `hasMore` with rows and a marker that moved (the same one again would loop).
 */
export function nextMarker(last: unknown, _pages: unknown[], lastParam: string | null): string | undefined {
  const o = last as { hasMore?: unknown; tailMarker?: unknown } | null | undefined;
  const tail = typeof o?.tailMarker === "number" ? String(o.tailMarker) : o?.tailMarker;
  if (!o?.hasMore || !rowsOf(last)?.length || typeof tail !== "string" || !tail || tail === lastParam) return undefined;
  return tail;
}

/** Rows once each by id, where each first came (OF's offset pages overlap, as the Vault's: vaultPageMedia); id-less rows all stay. */
export function uniqueRows<T extends { id?: unknown }>(rows: T[]): T[];
export function uniqueRows<T extends { id?: unknown }>(rows: T[] | undefined): T[] | undefined;
export function uniqueRows<T extends { id?: unknown }>(rows: T[] | undefined): T[] | undefined {
  const seen = new Set<string>();
  return rows?.filter((r) => r.id == null || (!seen.has(String(r.id)) && !!seen.add(String(r.id))));
}

/** An offset-paged read's rows in order (none: no first page yet, or it is not OF's list). */
export function pageRows<T>(pages: unknown[] | undefined): T[] | undefined {
  if (!pages?.length || !rowsOf(pages[0])) return undefined;
  return pages.flatMap((p) => rowsOf<T>(p) ?? []);
}
