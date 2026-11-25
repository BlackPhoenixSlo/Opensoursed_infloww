"use client";


import { useMemo, useState, type ReactNode } from "react";
import { RotateCw } from "lucide-react";

import CsvExportButton from "@/components/messages/CsvExportButton";
import GroupMassButton from "@/components/messages/GroupMassButton";
import MessageDashboardFilters, { EMPTY_DASHBOARD_FILTERS } from "@/components/messages/MessageDashboardFilters";
import MessageDashboardForm, { initialParams, type DashboardParams } from "@/components/messages/MessageDashboardForm";
import MessageDashboardTable from "@/components/messages/MessageDashboardTable";
import MessageRowGeneric from "@/components/messages/MessageRowGeneric";
import MessagesFilters from "@/components/messages/MessagesFilters";
import UnsendMessageButton, { canOfferUnsend } from "@/components/messages/UnsendMessageButton";
import InfiniteListFooter from "@/components/messages/InfiniteListFooter";
import { IfButton } from "@/components/ui/infloww";
import {
  buildPaidMessagesQuery,
  usePaidMessages,
  type MessageDirection,
  type MessageKind,
  type MessageType,
  type PaidStatus,
} from "@/hooks/usePaidMessages";
import { cn } from "@/lib/utils";
import type { FanId } from "@/lib/fanId";
import { TableSkeleton } from "@/components/ui/Skeleton";

interface Props {
  from: string | null;
  to: string | null;
  fanId?: FanId | null;
  onClearFanId?: () => void;
  kind?: Exclude<MessageKind, "all">;
  reportTz?: string | null;
  range?: ReactNode;
}

export default function AllMessagesTab(props: Props) {
  return props.kind ? <DashboardTab {...props} kind={props.kind} /> : <AllTab {...props} />;
}

function DashboardTab({ from, to, fanId, kind, reportTz = null, range }: Props & { kind: Exclude<MessageKind, "all"> }) {
  const [applied, setApplied] = useState<DashboardParams>(() => initialParams(kind, fanId));
  const params = useMemo(() => ({ from, to, direction: "out" as const, ...applied }), [from, to, applied]);
  const q = usePaidMessages(params);
  const rows = useMemo(() => (q.data?.pages ?? []).flatMap((p) => p.rows), [q.data]);
  const updated = useMemo(() => {
    if (!q.dataUpdatedAt) return "--";
    const at = new Date(q.dataUpdatedAt);
    const tz = reportTz ?? undefined;
    const time = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: tz }).format(at);
    const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: tz }).format(at);
    return `${time} on ${day}`;
  }, [q.dataUpdatedAt, reportTz]);

  return (
    <div className="space-y-2">
      <MessageDashboardForm kind={kind} fanId={fanId} onSearch={setApplied} range={range} />
      <div className="flex items-center justify-end gap-3 text-[12px] text-fg-dim">
        <span>Last updated: {updated}</span>
        <IfButton aria-label="Refresh" title="Re-read these messages now" onClick={() => q.refetch()}
          disabled={q.isFetching} className="w-8 px-0">
          <RotateCw className={cn("h-4 w-4", q.isFetching && "animate-spin")} aria-hidden />
        </IfButton>
        <CsvExportButton
          path="/admin/paid-messages"
          query={buildPaidMessagesQuery(params, null, { format: "csv" })}
          disabled={!from || !to}
        />
      </div>
      <MessageDashboardTable
        rows={rows}
        reportTz={reportTz}
        loading={q.isPending}
        error={q.isError}
        onRetry={() => q.refetch()}
        dim={q.isFetching && q.isPlaceholderData}
        hasNextPage={q.hasNextPage}
        isFetchingNextPage={q.isFetchingNextPage}
        fetchNextPage={q.fetchNextPage}
      />
    </div>
  );
}

function AllTab({ from, to, fanId, onClearFanId }: Props) {
  const [accountId, setAccountId] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [status, setStatus] = useState<PaidStatus>("all");
  const [type, setType] = useState<MessageType>("all");
  const [direction, setDirection] = useState<MessageDirection>("out");
  const [fanQuery, setFanQuery] = useState("");
  const [dash, setDash] = useState(EMPTY_DASHBOARD_FILTERS);

  const handleDirectionChange = (d: MessageDirection) => {
    setDirection(d);
    // Inbound has no sending employee; a leftover filter would silently zero the result.
    if (d === "in" && employeeId != null) setEmployeeId(null);
  };
  const handleTypeChange = (t: MessageType) => {
    setType(t);
    if (t === "free" && status !== "all") setStatus("all");
  };

  const params = useMemo(
    () => ({
      from,
      to,
      account_id: accountId,
      employee_id: employeeId,
      status,
      type,
      direction,
      fan_id: fanId ?? null,
      fan_query: fanQuery,
      q: dash.q,
      min_price_cents: dash.minPriceCents,
      max_price_cents: dash.maxPriceCents,
      unsent_only: dash.unsentOnly,
      sender_type: dash.senderType,
    }),
    [from, to, accountId, employeeId, status, type, direction, fanId, fanQuery, dash],
  );

  const q = usePaidMessages(params);

  const rows = useMemo(
    () => (q.data?.pages ?? []).flatMap((p) => p.rows),
    [q.data],
  );

  return (
    <div className="space-y-3">
      <MessageDashboardFilters value={dash} onChange={setDash} />
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
          type={type}
          onTypeChange={handleTypeChange}
          direction={direction}
          onDirectionChange={handleDirectionChange}
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

      {fanId != null && (
        <div className="flex items-center gap-2 text-sm md:text-xs text-fg-dim">
          <span>Filtered to fan #{fanId}</span>
          {onClearFanId && (
            <button
              type="button"
              onClick={onClearFanId}
              className="text-accent underline underline-offset-2 md:no-underline md:underline-offset-auto md:hover:underline inline-flex items-center px-3 py-2 -my-2 min-h-11 md:inline-block md:px-0 md:py-0 md:my-0 md:min-h-0"
            >
              clear
            </button>
          )}
        </div>
      )}

      {q.isError && (
        <div className="p-4 text-sm text-err border border-err/30 bg-err/10 rounded-xl">
          Failed to load: {(q.error as Error)?.message || "unknown error"}
        </div>
      )}

      {q.isPending ? (
        <TableSkeleton rows={6} className="m-4" />
      ) : rows.length === 0 ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          No messages match these filters.
        </div>
      ) : (
        <div
          className={cn(
            "space-y-2 transition-opacity",
            q.isFetching && q.isPlaceholderData && "opacity-60",
          )}
        >
          {rows.map((r) => (
            <div key={`${r.account_id}:${r.fan_id}:${r.message_id}`} className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <MessageRowGeneric row={r} />
              </div>
              {canOfferUnsend(r) && <UnsendMessageButton row={r} />}
            </div>
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
