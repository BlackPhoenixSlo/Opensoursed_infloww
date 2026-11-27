import { useInfiniteQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { relay, RelayError } from "@/lib/relay";

import type { LeakPage } from "./leakView";

const keyInvalid = (e: unknown) => e instanceof RelayError && e.status === 409
  && (e.body as { detail?: { error?: unknown } } | null)?.detail?.error === "key_invalid";

export async function leakRead<T>(qc: QueryClient, path: string, accountId: string | null): Promise<T> {
  try {
    return await relay.get<T>(path, { accountId });
  } catch (e) {
    if (keyInvalid(e)) void qc.invalidateQueries({ queryKey: ["leak-tracker", "setup"] });
    throw e;
  }
}

const withCursor = (path: string, cursor: string | null) => (cursor ? `${path}?cursor=${encodeURIComponent(cursor)}` : path);

export const useLeakPages = <T extends LeakPage>(key: QueryKey, path: string, accountId: string | null) => {
  const qc = useQueryClient();
  return useInfiniteQuery({
    queryKey: key,
    initialPageParam: null as string | null,
    getNextPageParam: (last: T) => last.next_cursor ?? undefined,
    queryFn: ({ pageParam }) => leakRead<T>(qc, withCursor(path, pageParam), accountId),
  });
};
