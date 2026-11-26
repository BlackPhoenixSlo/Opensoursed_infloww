"use client";


import { useCallback, useMemo, useReducer } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  buildRequest, canAct, initialOverlay, retryOutcome, settleRows, unconfirmedSendsReducer, viewRows,
  type ListedRow, type Op, type Outcome, type UnconfirmedView,
} from "@/components/automations/unconfirmedSendsReducer";
import { ifConfirm } from "@/components/ui/ifConfirm";
import { relay, RelayError } from "@/lib/relay";

const KEY = "unconfirmed-sends";

export function useUnconfirmedSends(accountId: string) {
  const qc = useQueryClient();
  const q = useQuery<ListedRow[]>({
    queryKey: [KEY, accountId],
    queryFn: async () => {
      const r = await relay.get<{ rows: ListedRow[] }>(
        `/admin/unconfirmed-sends?account_id=${encodeURIComponent(accountId)}`,
        { accountId, priority: "background" },
      );
      return r.rows ?? [];
    },
    staleTime: 30_000,
    // eslint-disable-next-line local/no-fixed-polling -- state flips on timeout, no row written
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

  const [overlay, dispatch] = useReducer(unconfirmedSendsReducer, initialOverlay);
  const rows = useMemo(() => viewRows(q.data, overlay), [q.data, overlay]);

  const run = useCallback(async (row: UnconfirmedView, op: Op) => {
    const req = buildRequest(row, op);
    if (!canAct(row) || !req) return;
    if (req.confirm && !(await ifConfirm(req.confirm.question, { confirmLabel: req.confirm.label }))) return;
    dispatch({ type: "start", key: row.key, op });
    let result;
    try {
      await relay.post(`/admin/unconfirmed-sends/${req.path}?account_id=${encodeURIComponent(accountId)}`, req.body, { accountId });
      result = { status: 200 };
    } catch (e) {
      result = e instanceof RelayError
        ? { status: e.status, message: e.message }
        : { status: 0, message: e instanceof Error ? e.message : String(e) };
    }
    dispatch({ type: "done", key: row.key, op, result });
    const out = retryOutcome(result.status);
    // A 409: the row changed, show it as it is now.
    if (out === "error" && result.status !== 409) return;
    qc.setQueryData<ListedRow[]>([KEY, accountId], (d) => settleRows(d, row.key, out));
    void qc.invalidateQueries({ queryKey: [KEY, accountId] });
  }, [accountId, qc]);

  const retry = useCallback((row: UnconfirmedView) => run(row, "retry"), [run]);
  const dismiss = useCallback((row: UnconfirmedView) => run(row, "dismiss"), [run]);
  const resolve = useCallback((row: UnconfirmedView, outcome: Outcome) => run(row, outcome), [run]);
  return { rows, retry, dismiss, resolve };
}
