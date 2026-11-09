"use client";

/**
 * ScheduledTab — read + cancel queued sends across all accounts.
 *
 * Surfaces what's about to fire (or already overdue) so the operator can
 * cancel before it goes out. Direct + mass sends share the queue; we
 * label each row by recipient count so a 1-fan send vs a 200-fan blast
 * is unambiguous.
 */

import { useMemo } from "react";
import { Lock, Paperclip } from "lucide-react";

import { IfButton, IfCard, IfHelp } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useIfConfirm } from "@/hooks/useIfConfirm";
import { useCancelScheduled, useScheduledMessages } from "@/hooks/useScheduledMessages";
import type { OFScheduledMessage } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { fmtPrice } from "@/lib/format";
import { ofPlainText } from "@/lib/ofRichText";

import { RefreshButton } from "./RefreshButton";

export default function ScheduledTab() {
  const accounts = useActiveAccounts();
  const accountIds = useMemo(() => accounts.map((a) => a.id), [accounts]);
  const { rows, isLoading, isFetching, error, queries } = useScheduledMessages(accountIds);
  const cancelM = useCancelScheduled();
  const { ask, modal: confirmModal } = useIfConfirm();

  const refresh = () => queries.forEach((q) => q.refetch());

  // Account id → nickname for the row label. Tiny lookup so the body
  // doesn't need to thread `accounts` through every row.
  const accountName = (id?: string) =>
    accounts.find((a) => a.id === id)?.nickname || id || "?";

  return (
    <div className="space-y-4">
      <IfCard title="Scheduled messages" extra={(
        <RefreshButton onClick={refresh} refreshing={isFetching} />
      )}>
        <IfHelp className="mb-4">All queued sends across the agency. Cancel before they fire.</IfHelp>

        {error && (
          <div className="text-[14px] text-err mb-3">
            Failed to load: {error.message}
          </div>
        )}

        {isLoading && rows.length === 0 && (
          <div className="text-[14px] text-fg-dim">Loading…</div>
        )}

        {!isLoading && rows.length === 0 && (
          <div className="text-[14px] text-fg-dim">Nothing queued.</div>
        )}

        <div className="space-y-2">
          {rows.map((m) => (
            <ScheduledRow
              key={`${m.__accountId}:${m.id}`}
              m={m}
              accountLabel={accountName(m.__accountId)}
              busy={cancelM.isPending && cancelM.variables?.id === m.id}
              onCancel={async () => {
                const accountId = m.__accountId;
                if (!accountId) return;
                if (!(await ask("Cancel this scheduled send?", undefined, "Cancel send"))) return;
                cancelM.mutate({ id: m.id, accountId });
              }}
            />
          ))}
        </div>
      </IfCard>
      {confirmModal}
    </div>
  );
}

function ScheduledRow({
  m, accountLabel, busy, onCancel,
}: {
  m: OFScheduledMessage;
  accountLabel: string;
  busy: boolean;
  onCancel: () => void;
}) {
  const when = m.scheduledDate ? new Date(m.scheduledDate) : null;
  const overdue = !!when && when.getTime() < Date.now();
  const listCount = m.userLists?.length ?? 0;
  const groupCount = m.groups?.length ?? 0;
  const directCount = m.userIds?.length ?? 0;
  const isMass = listCount > 0 || groupCount > 0;
  // Mass audiences fan out to whole lists/groups, so a flat "N targets" is
  // misleading — name what the blast actually points at instead.
  const massLabel = [
    listCount > 0 && `${listCount} list${listCount === 1 ? "" : "s"}`,
    groupCount > 0 && `${groupCount} group${groupCount === 1 ? "" : "s"}`,
    directCount > 0 && `${directCount} fan${directCount === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(" + ") || "?";

  return (
    <div className={cn(
      "border border-border rounded-md px-3 py-2.5 flex items-start gap-3",
      busy && "opacity-60",
    )}>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 text-[12px] flex-wrap">
          <span className={cn(
            "px-1.5 py-0.5 rounded",
            overdue ? "bg-warn/15 text-warn" : "bg-accent/15 text-accent",
          )}>
            {when ? when.toLocaleString() : "no time"}
            {overdue && " (overdue)"}
          </span>
          <span className="text-fg-dim">{accountLabel}</span>
          {isMass ? (
            <span className="text-fg-dim">Mass ({massLabel})</span>
          ) : (
            <span className="text-fg-dim">Direct to {directCount} fan{directCount === 1 ? "" : "s"}</span>
          )}
          {(m.mediaCount ?? 0) > 0 && (
            <span className="text-fg-dim inline-flex items-center gap-1">
              <Paperclip size={12} aria-hidden /> {m.mediaCount}
            </span>
          )}
          {m.price && m.price > 0 && (
            <span className="text-warn inline-flex items-center gap-1">
              <Lock size={12} aria-hidden /> {fmtPrice(Math.round(m.price * 100))}
            </span>
          )}
        </div>
        <div className="text-[14px] whitespace-pre-wrap break-words line-clamp-3">
          {ofPlainText(m.text || "")}
        </div>
      </div>
      <IfButton variant="link" onClick={onCancel} disabled={busy}>
        Cancel
      </IfButton>
    </div>
  );
}
