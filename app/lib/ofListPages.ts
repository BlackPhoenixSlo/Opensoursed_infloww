/** The relay caps each list request at 50. A screen needs every page, not a larger limit. */
export const OF_LISTS_PAGE = 50;
export const OF_USER_LISTS = `/api/of/v2/lists?limit=${OF_LISTS_PAGE}`;
export const OF_CHAT_FOLDERS = `/api/of/v2/chats/folders?limit=${OF_LISTS_PAGE}`;

export type ListRow = { id: number | string };
export type ListPage<T> = { list?: T[]; hasMore?: boolean } | T[];

/**
 * Walk an OF list resource to its end, preserving order and metadata and deduplicating ids.
 * Offsets count upstream rows, including overlaps. Never cache a failed or stalled walk
 * as a successful, incomplete list. A bare array is OF's unpaged response.
 */
export async function readAllListPages<T extends ListRow>(
  get: (path: string) => Promise<ListPage<T>>,
  path: string,
): Promise<T[]> {
  const out: T[] = [];
  const seen = new Set<string>();
  let offset = 0;
  for (;;) {
    const page = await get(offset ? `${path}&offset=${offset}` : path);
    const rows = Array.isArray(page) ? page : page.list ?? [];
    const before = seen.size;
    for (const row of rows) {
      const id = String(row.id);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(row);
    }
    if (Array.isArray(page) || !page.hasMore) return out;
    if (!rows.length || seen.size === before) {
      throw new Error("Could not load every list: OnlyFans returned no new lists while reporting more. Please retry.");
    }
    offset += rows.length;
  }
}
