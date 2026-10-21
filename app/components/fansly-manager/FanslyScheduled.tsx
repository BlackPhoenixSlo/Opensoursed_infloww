"use client";

/**
 * Fansly Manager > Scheduled Posts: the creator's queued Fansly posts, soonest first, and Cancel. The list is the
 * Relay's `GET /api/of/v2/schedules`, which the Fansly shim answers from Fansly's `GET /post/scheduled` as OF queue
 * items (fansly_shim.schedules). Cancel is the Relay's `DELETE /api/of/v2/messages/queue/{id}`, the route to the
 * shim's `cancel_scheduled` (Fansly's `POST /post/scheduled/{id}/cancel`); a queue item's id is the post id.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState, IF_TABLE, IfBody, IfButton, IfModal } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

interface QueueItem {
  id: string;
  type: string;
  publishDateTime: string | null;
  entity: { id: string; text?: string } | null;
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");

export function FanslyScheduled({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const queryKey = ["fansly-manager", "scheduled", accountId];
  const listQ = useQuery<{ list: QueueItem[] }>({
    queryKey,
    queryFn: () => relay.get("/api/of/v2/schedules?limit=50", { accountId }),
    staleTime: 30_000,
  });
  const [confirm, setConfirm] = useState<QueueItem | null>(null);
  const cancel = useMutation({
    mutationFn: (id: string) => relay.delete(`/api/of/v2/messages/queue/${encodeURIComponent(id)}`, { accountId }),
    onSuccess: () => {
      setConfirm(null);
      void qc.invalidateQueries({ queryKey });
    },
  });
  const close = () => { setConfirm(null); cancel.reset(); };
  const rows = listQ.data?.list ?? [];

  return (
    <IfBody>
      {listQ.isError ? (
        <EmptyState kind="error" text="Could not load scheduled posts." onRetry={() => void listQ.refetch()} className="mt-16" />
      ) : listQ.isPending ? (
        <p className="mt-16 text-center text-[14px] text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState text="No scheduled posts" className="mt-16" />
      ) : (
        <table className={IF_TABLE.table}>
          <thead>
            <tr>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider, "w-[220px]")}>Scheduled for</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.thDivider)}>Post</th>
              <th className={cn(IF_TABLE.th, IF_TABLE.fixedRightHead)}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={IF_TABLE.row}>
                <td className={cn(IF_TABLE.td, "whitespace-nowrap")}>{when(r.publishDateTime)}</td>
                <td className={cn(IF_TABLE.td, "max-w-0 truncate")} title={r.entity?.text || undefined}>
                  {r.entity?.text || <span className="text-muted">No text</span>}
                </td>
                <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight)}>
                  <IfButton variant="link" onClick={() => setConfirm(r)}>Cancel</IfButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirm && (
        <IfModal
          title="Cancel this scheduled post?"
          onClose={close}
          footer={
            <>
              <IfButton onClick={close}>Keep</IfButton>
              <IfButton variant="primary" disabled={cancel.isPending} onClick={() => cancel.mutate(confirm.id)}>
                {cancel.isPending ? "Cancelling…" : "Cancel post"}
              </IfButton>
            </>
          }
        >
          <p>It was due {when(confirm.publishDateTime)}. Fansly will not publish it.</p>
          {cancel.isError && <p role="alert" className="mt-2 text-[12px] text-err">Could not cancel the post.</p>}
        </IfModal>
      )}
    </IfBody>
  );
}
