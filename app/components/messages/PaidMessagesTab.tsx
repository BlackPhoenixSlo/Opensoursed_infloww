"use client";

/**
 * PaidMessagesTab — owns the filter state and the infinite-scroll list.
 *
 * The date range comes in from the page; everything else (model,
 * employee, status, fan search) is local to this tab so switching to
 * the Tips tab in the future doesn't pollute its filter state.
 *
 * Pagination is keyset (message_id DESC) via usePaidMessages, paged by
 * InfiniteListFooter.
 */

import { useMemo, useState } from "react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import GroupMassButton from "@/components/messages/GroupMassButton";
import MessagesFilters from "@/components/messages/MessagesFilters";
import MessageRow from "@/components/messages/MessageRow";
import InfiniteListFooter from "@/components/messages/InfiniteListFooter";
import { buildPaidMessagesQuery, usePaidMessages, type PaidStatus } from "@/hooks/usePaidMessages";
import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/ui/Skeleton";

interface Props {
  from: string | null;
  to: string | null;
}

export default function PaidMessagesTab({ from, to }: Props) {
  const [accountId, setAccountId] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [status, setStatus] = useState<PaidStatus>("all");
  const [fanQuery, setFanQuery] = useState("");

  const params = useMemo(
    () => ({
      from,
      to,
      account_id: accountId,
      employee_id: employeeId,
      status,
      // PPV-tab semantics: outbound priced messages only. type=paid +
      // direction=out are backend defaults, but we set them explicitly
      // here so the CSV export reflects what the tab actually shows
      // (Status: All|Paid|Unpaid still applies — that's what the user
      // ticks to widen between paid-only and paid+unpaid).
      type: "paid" as const,
      direction: "out" as const,
      fan_query: fanQuery,
    }),
    [from, to, accountId, employeeId, status, fanQuery],
  );

  const q = usePaidMessages(params);

  const rows = useMemo(
    () => (q.data?.pages ?? []).flatMap((p) => p.rows),
    [q.data],
  );

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <MessagesFilters
          accountId={accountId}
          onAccountChange={setAccountId}
          employeeId={employeeId}
          onEmployeeChange={setEmployeeId}
          status={status}
          onStatusChange={setStatus}
          fanQuery={fanQuery}
          onFanQueryChange={setFanQuery}
        />
        <div className="hidden md:flex items-center gap-2">
          <GroupMassButton accountId={accountId} />
          <CsvExportButton
            path="/admin/paid-messages"
            query={buildPaidMessagesQuery(params, null, { format: "csv" })}
            disabled={!from || !to}
          />
        </div>
      </div>

      {q.isError && (
        <div className="p-4 text-sm text-err border border-err/30 bg-err/10 rounded-xl">
          Failed to load: {(q.error as Error)?.message || "unknown error"}
        </div>
      )}

      {q.isPending ? (
        <TableSkeleton rows={6} className="m-4" />
      ) : rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          No paid messages in this window.
        </div>
      ) : (
        <div
          className={cn(
            "space-y-2 transition-opacity",
            q.isFetching && q.isPlaceholderData && "opacity-60",
          )}
        >
          {rows.map((r) => (
            <MessageRow key={`${r.account_id}:${r.fan_id}:${r.message_id}`} row={r} />
          ))}

          <InfiniteListFooter
            hasNextPage={q.hasNextPage}
            isFetchingNextPage={q.isFetchingNextPage}
            fetchNextPage={q.fetchNextPage}
            endLabel="end of results"
          />
        </div>
      )}
    </div>
  );
}
