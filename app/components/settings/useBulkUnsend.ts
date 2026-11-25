"use client";


import { skipToken, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { cancelMassMessage } from "@/hooks/useMassMessages";

import { bulkRunReducer, INITIAL_BULK_RUN, type BulkRun, type BulkRunAction } from "./bulkUnsendRun";
import { unsendByCreator, type ActionableRow, type BulkAction } from "./massUnsendRules";

const KEY = ["bulk-unsend-run"] as const;

const defaulted = new WeakSet<QueryClient>();

function step(qc: QueryClient, a: BulkRunAction): void {
  if (!defaulted.has(qc)) {
    qc.setQueryDefaults(KEY, { gcTime: Infinity, staleTime: Infinity });
    defaulted.add(qc);
  }
  qc.setQueryData<BulkRun>(KEY, (s) => bulkRunReducer(s ?? INITIAL_BULK_RUN, a));
}

// Lock held outside the cache: an identity wipe clears the cache, never the lock of a loop still going.
const locked = new WeakSet<QueryClient>();
let epoch = 0;

export function stopBulkUnsends(): void {
  epoch += 1;
}

const warnOnClose = (e: BeforeUnloadEvent) => {
  e.preventDefault();
  e.returnValue = "";
};

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

export function useBulkUnsend() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: KEY,
    queryFn: skipToken,
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
