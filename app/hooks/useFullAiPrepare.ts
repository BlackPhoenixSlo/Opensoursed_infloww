"use client";

/**
 * useFullAiPrepare — Prepare content (ticket 49; service/full_ai_prepare.py): the run's step list from
 * GET /admin/full-ai/prepare-content/status, polled every 2 s while it runs (`run_id` set, `finished_at` null), and
 * `start`, the one POST /admin/full-ai/prepare-content. Only the owner's click calls `start`: reading the status on
 * load never starts a run (the server keeps the latest run in memory; idle = `run_id: null`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

export const PREPARE_POLL_MS = 2_000;

export type PrepareStepName = "harvest" | "describe" | "folders" | "feet";
export type PrepareStepState = "pending" | "running" | "done" | "failed" | "busy" | "skipped";
export interface PrepareStep {
  name: PrepareStepName;
  state: PrepareStepState;
  detail: string;
  counts: Record<string, number>;
}
export interface PrepareRun {
  run_id: string | null;
  steps: PrepareStep[];
  started_at: string | null;
  finished_at: string | null;
}

export const prepareKey = (accountId: string) => ["full-ai-prepare", accountId] as const;
export const prepareRunning = (run: PrepareRun | undefined) => !!run?.run_id && !run.finished_at;

export function useFullAiPrepare(accountId: string) {
  const qc = useQueryClient();
  const status = useQuery<PrepareRun>({
    queryKey: prepareKey(accountId),
    queryFn: () => relay.get<PrepareRun>(
      `/admin/full-ai/prepare-content/status?account_id=${encodeURIComponent(accountId)}`, { accountId }),
    // eslint-disable-next-line local/no-fixed-polling -- no SSE event for a Prepare run; spec: poll 2 s only while it runs, idle otherwise
    refetchInterval: (q) => (prepareRunning(q.state.data) ? PREPARE_POLL_MS : false),
  });
  const start = useMutation({
    mutationFn: () => relay.post<PrepareRun>("/admin/full-ai/prepare-content", { account_id: accountId }, { accountId }),
    onSuccess: (run) => qc.setQueryData(prepareKey(accountId), run),
  });
  return { run: status.data, running: prepareRunning(status.data), readError: status.isError, start };
}
