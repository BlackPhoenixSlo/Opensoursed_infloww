"use client";

/**
 * The Mass messages tab's bulk unsend run, held in the app's react-query
 * client (not the tab), so it outlives the tab: a tab switch or route change
 * unmounts MassMessagesTab but the run goes on, and a remount reads its live
 * "N of M". State moves only through `bulkRunReducer` (bulkUnsendRun.ts); the
 * close-tab warning belongs to the run, set at its start and dropped at its end.
 * One run at a time: `startBulkUnsend` sends nothing while one is going (the
 * tab disables its bulk buttons then, so it never asks). The lock is held
 * outside the cache: an identity wipe clears the cache, never the lock of a
 * loop still going. An identity switch (`stopBulkUnsends`) skips the run's
 * queued deletes and drops its progress / finish.
 */

import { skipToken, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { cancelMassMessage } from "@/hooks/useMassMessages";

import { bulkRunReducer, INITIAL_BULK_RUN, type BulkRun, type BulkRunAction } from "./bulkUnsendRun";
import { unsendByCreator, type ActionableRow, type BulkAction } from "./massUnsendRules";

const KEY = ["bulk-unsend-run"] as const;

// A run started with no tab mounted creates its entry via setQueryData: these
// defaults keep it from being collected mid-run. Once per client.
const defaulted = new WeakSet<QueryClient>();

function step(qc: QueryClient, a: BulkRunAction): void {
  if (!defaulted.has(qc)) {
    qc.setQueryDefaults(KEY, { gcTime: Infinity, staleTime: Infinity });
    defaulted.add(qc);
  }
  qc.setQueryData<BulkRun>(KEY, (s) => bulkRunReducer(s ?? INITIAL_BULK_RUN, a));
}

// Clients with a run going (the lock), and the identity epoch a run started in.
const locked = new WeakSet<QueryClient>();
let epoch = 0;

/** An identity switch: every run going now stops at its next delete and no
 *  longer writes the (new identity's) cache. */
export function stopBulkUnsends(): void {
  epoch += 1;
}

const warnOnClose = (e: BeforeUnloadEvent) => {
  e.preventDefault();
  e.returnValue = "";
};

/** Unsend `targets` (`unsendByCreator`: one delete in flight, Creator by
 *  Creator) as the client's one bulk run. Sends nothing when a run is already
 *  going. */
export async function startBulkUnsend(
  qc: QueryClient,
  action: BulkAction,
  targets: readonly ActionableRow[],
): Promise<void> {
  if (locked.has(qc)) return;
  const startEpoch = epoch;
  const live = () => epoch === startEpoch;
  locked.add(qc);
  step(qc, { type: "start", action, total: targets.length });
  window.addEventListener("beforeunload", warnOnClose);
  let failed = 0;
  try {
    failed = await unsendByCreator(
      targets,
      async (r) => {
        if (live()) await cancelMassMessage(qc, { id: r.id, accountId: r.__accountId });
      },
      (done) => {
        if (live()) step(qc, { type: "progress", done });
      },
    );
  } finally {
    window.removeEventListener("beforeunload", warnOnClose);
    locked.delete(qc);
    if (live()) step(qc, { type: "finish", failed });
  }
}

/** The run as the tab sees it, and the only moves the tab makes on it
 *  (start / progress / finish belong to `startBulkUnsend`). */
export function useBulkUnsend() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: skipToken,   // never fetched: only `step` writes it
    initialData: INITIAL_BULK_RUN,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return {
    run: data ?? INITIAL_BULK_RUN,
    clear: () => step(qc, { type: "clear" }),
    nothing: () => step(qc, { type: "nothing" }),
    start: (action: BulkAction, targets: readonly ActionableRow[]) => startBulkUnsend(qc, action, targets),
  };
}
