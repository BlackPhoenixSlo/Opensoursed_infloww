"use client";

/**
 * useUnconfirmedSends — one Creator's funnel / follow-up steps that may not
 * have sent (GET /admin/unconfirmed-sends, service/unconfirmed_sends_api.py)
 * plus a per-row Retry (POST /admin/unconfirmed-sends/retry). The rows are the
 * query's; each row's Retry overlay is the pure reducer in
 * components/automations/unconfirmedSendsReducer.ts; this fetches and
 * dispatches. Mount it keyed by `accountId` (a Creator switch starts fresh).
 */

import { useCallback, useMemo, useReducer } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  buildRetryPayload, canRetry, initialOverlay, retryOutcome, settleRows, unconfirmedSendsReducer, viewRows,
  type UnconfirmedRow, type UnconfirmedView,
} from "@/components/automations/unconfirmedSendsReducer";
import { relay, RelayError } from "@/lib/relay";

const KEY = "unconfirmed-sends";

export function useUnconfirmedSends(accountId: string) {
  const qc = useQueryClient();
  const q = useQuery<UnconfirmedRow[]>({
    queryKey: [KEY, accountId],
    queryFn: async () => {
      const r = await relay.get<{ rows: UnconfirmedRow[] }>(
        `/admin/unconfirmed-sends?account_id=${encodeURIComponent(accountId)}`,
        { accountId, priority: "background" },
      );
      return r.rows ?? [];
    },
    staleTime: 30_000,
    // An IN_FLIGHT ("Sending") row turns UNCONFIRMED or clears on its own.
    // eslint-disable-next-line local/no-fixed-polling -- state flips on timeout, no row written
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

  const [overlay, dispatch] = useReducer(unconfirmedSendsReducer, initialOverlay);
  const rows = useMemo(() => viewRows(q.data, overlay), [q.data, overlay]);

  const retry = useCallback(async (row: UnconfirmedView) => {
    if (!canRetry(row)) return;
    dispatch({ type: "retryStart", key: row.key });
    let result;
    try {
      await relay.post(
        `/admin/unconfirmed-sends/retry?account_id=${encodeURIComponent(accountId)}`,
        buildRetryPayload(row),
        { accountId },
      );
      result = { status: 200 };
    } catch (e) {
      result = e instanceof RelayError
        ? { status: e.status, message: e.message }
        : { status: 0, message: e instanceof Error ? e.message : String(e) };
    }
    dispatch({ type: "retryDone", key: row.key, result });
    const out = retryOutcome(result.status);
    if (out === "error") return;
    qc.setQueryData<UnconfirmedRow[]>([KEY, accountId], (d) => settleRows(d, row.key, out));
    void qc.invalidateQueries({ queryKey: [KEY, accountId] });
  }, [accountId, qc]);

  return { rows, retry };
}
