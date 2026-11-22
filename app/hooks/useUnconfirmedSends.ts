"use client";

/**
 * useUnconfirmedSends — one Creator's funnel / follow-up steps that may not
 * have sent (GET /admin/unconfirmed-sends, service/unconfirmed_sends_api.py)
 * plus a per-row Retry (POST /admin/unconfirmed-sends/retry) and It went through
 * (POST /admin/unconfirmed-sends/dismiss, asked first). The rows are the
 * query's; each row's op overlay is the pure reducer in
 * components/automations/unconfirmedSendsReducer.ts; this fetches and
 * dispatches. Mount it keyed by `accountId` (a Creator switch starts fresh).
 */

import { useCallback, useMemo, useReducer } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  buildDismissPayload, buildRetryPayload, canAct, dismissQuestion, initialOverlay, retryOutcome, settleRows,
  unconfirmedSendsReducer, viewRows, type Op, type UnconfirmedRow, type UnconfirmedView,
} from "@/components/automations/unconfirmedSendsReducer";
import { ifConfirm } from "@/components/ui/ifConfirm";
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

  const run = useCallback(async (row: UnconfirmedView, op: Op) => {
    if (!canAct(row)) return;
    if (op === "dismiss" && !(await ifConfirm(dismissQuestion(row), { confirmLabel: "It went through" }))) return;
    dispatch({ type: "start", key: row.key, op });
    let result;
    try {
      await relay.post(
        `/admin/unconfirmed-sends/${op}?account_id=${encodeURIComponent(accountId)}`,
        op === "retry" ? buildRetryPayload(row) : buildDismissPayload(row),
        { accountId },
      );
      result = { status: 200 };
    } catch (e) {
      result = e instanceof RelayError
        ? { status: e.status, message: e.message }
        : { status: 0, message: e instanceof Error ? e.message : String(e) };
    }
    dispatch({ type: "done", key: row.key, op, result });
    const out = retryOutcome(result.status);
    if (out === "error" && result.status !== 409) return;   // a 409: the row changed, show it as it is now
    qc.setQueryData<UnconfirmedRow[]>([KEY, accountId], (d) => settleRows(d, row.key, out));
    void qc.invalidateQueries({ queryKey: [KEY, accountId] });
  }, [accountId, qc]);

  const retry = useCallback((row: UnconfirmedView) => run(row, "retry"), [run]);
  const dismiss = useCallback((row: UnconfirmedView) => run(row, "dismiss"), [run]);
  return { rows, retry, dismiss };
}
