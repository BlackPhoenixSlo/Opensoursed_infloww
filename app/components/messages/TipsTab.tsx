"use client";


import { useEffect, useMemo, useState } from "react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import MessagesFilters from "@/components/messages/MessagesFilters";
import TipRow from "@/components/messages/TipRow";
import InfiniteListFooter from "@/components/messages/InfiniteListFooter";
import { buildTipsListQuery, useTipsList } from "@/hooks/useTipsList";
import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/ui/Skeleton";

interface Props {
  from: string | null;
  to: string | null;
  presetFanQuery?: string | null;
}

export default function TipsTab({ from, to, presetFanQuery }: Props) {
  const [accountId, setAccountId] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [fanQuery, setFanQuery] = useState("");

  useEffect(() => {
    if (presetFanQuery == null) return;
    setFanQuery(presetFanQuery);
  }, [presetFanQuery]);

  const params = {
    from,
    to,
    account_id: accountId,
    employee_id: employeeId,
    fan_query: fanQuery,
  };
  const q = useTipsList(params);

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
          status="all"
          onStatusChange={() => {}}
          showStatus={false}
          fanQuery={fanQuery}
          onFanQueryChange={setFanQuery}
        />
        <div className="hidden md:flex items-center gap-2">
          <CsvExportButton
            path="/admin/tips-list"
            query={buildTipsListQuery(params, null, true)}
            disabled={!from || !to}
            title="Download the filtered tips as CSV (up to 50,000 rows)"
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
          No tips in this window.
        </div>
      ) : (
        <div
          className={cn(
            "space-y-2 transition-opacity",
            q.isFetching && q.isPlaceholderData && "opacity-60",
          )}
        >
          {rows.map((r) => (
            <TipRow key={r.transaction_id} row={r} />
          ))}

          <InfiniteListFooter
            hasNextPage={q.hasNextPage}
            isFetchingNextPage={q.isFetchingNextPage}
            fetchNextPage={q.fetchNextPage}
            isError={q.isError}
            endLabel="end of results"
          />
        </div>
      )}
    </div>
  );
}
