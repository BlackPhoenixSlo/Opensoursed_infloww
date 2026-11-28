import { useInfiniteQuery, useQueryClient, type InfiniteData, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { relay, RelayError } from "@/lib/relay";

import { leakKeys } from "./leakKeys";
import type { LeakPage } from "./leakView";

export const keyInvalid = (e: unknown) => e instanceof RelayError && e.status === 409
  && (e.body as { detail?: { error?: unknown } } | null)?.detail?.error === "key_invalid";

export async function leakRead<T>(qc: QueryClient, path: string, accountId: string | null): Promise<T> {
  try {
    return await relay.get<T>(path, { accountId });
  } catch (e) {
    if (keyInvalid(e)) void qc.invalidateQueries({ queryKey: leakKeys.setupRoot });
    throw e;
  }
}

const withCursor = (path: string, cursor: string | null) =>
  (cursor ? `${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}` : path);

export const useLeakPages = <T extends LeakPage>(key: QueryKey, path: string, accountId: string | null,
  refetchInterval?: (data: InfiniteData<T> | undefined) => number | false, enabled = true) => {
  const qc = useQueryClient();
  return useInfiniteQuery({
    queryKey: key,
    enabled,
    initialPageParam: null as string | null,
    getNextPageParam: (last: T) => last.next_cursor ?? undefined,
    queryFn: ({ pageParam }) => leakRead<T>(qc, withCursor(path, pageParam), accountId),
    // eslint-disable-next-line local/no-fixed-polling -- Tracker scans have no SSE event; callers poll only while a refresh is pending
    refetchInterval: refetchInterval && ((q) => refetchInterval(q.state.data)),
  });
};
