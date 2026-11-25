export function rowsOf<T>(r: unknown): T[] | undefined {
  if (Array.isArray(r)) return r as T[];
  const o = r as { list?: unknown; chats?: unknown } | null | undefined;
  if (Array.isArray(o?.list)) return o.list as T[];
  if (Array.isArray(o?.chats)) return o.chats as T[];
  return undefined;
}

export function nextOffset(last: unknown, pages: unknown[]): number | undefined {
  if (!(last as { hasMore?: unknown } | null)?.hasMore || !rowsOf(last)?.length) return undefined;
  const next = (last as { nextOffset?: unknown }).nextOffset;
  return typeof next === "number" ? next : pages.reduce<number>((n, p) => n + (rowsOf(p)?.length ?? 0), 0);
}

export const POSTS_PAGE = 20;

export function nextFeedOffset(last: unknown, pages: unknown[]): number | undefined {
  if (!Array.isArray(last)) return nextOffset(last, pages);
  return last.length >= POSTS_PAGE ? pages.reduce<number>((n, p) => n + (rowsOf(p)?.length ?? 0), 0) : undefined;
}

export function nextMarker(last: unknown, _pages: unknown[], lastParam: string | null): string | undefined {
  const o = last as { hasMore?: unknown; tailMarker?: unknown } | null | undefined;
  const tail = typeof o?.tailMarker === "number" ? String(o.tailMarker) : o?.tailMarker;
  // A marker that did not move would loop.
  if (!o?.hasMore || !rowsOf(last)?.length || typeof tail !== "string" || !tail || tail === lastParam) return undefined;
  return tail;
}

export function uniqueRows<T extends { id?: unknown }>(rows: T[]): T[];
export function uniqueRows<T extends { id?: unknown }>(rows: T[] | undefined): T[] | undefined;
export function uniqueRows<T extends { id?: unknown }>(rows: T[] | undefined): T[] | undefined {
  // OF's offset pages overlap.
  const seen = new Set<string>();
  return rows?.filter((r) => r.id == null || (!seen.has(String(r.id)) && !!seen.add(String(r.id))));
}

export function pageRows<T>(pages: unknown[] | undefined): T[] | undefined {
  if (!pages?.length || !rowsOf(pages[0])) return undefined;
  return pages.flatMap((p) => rowsOf<T>(p) ?? []);
}
