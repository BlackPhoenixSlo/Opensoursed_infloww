"use client";

/**
 * ScheduledTab — read + cancel queued sends across all accounts.
 *
 * Surfaces what's about to fire (or already overdue) so the operator can
 * cancel before it goes out. Direct + mass sends share the queue; we
 * label each row by recipient count so a 1-fan send vs a 200-fan blast
 * is unambiguous. A table (one row per send, Actions pinned right) with the
 * house empty state; the help line links to Auto Mass for repeating sends
 * (shown only when the role may open it).
 */

import Link from "next/link";
import { useMemo } from "react";
import { Lock, Paperclip } from "lucide-react";

import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { EmptyState, IF_TABLE, IfButton, IfCard, IfHelp } from "@/components/ui/infloww";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useIfConfirm } from "@/hooks/useIfConfirm";
import { useCancelScheduled, useScheduledMessages } from "@/hooks/useScheduledMessages";
import type { OFScheduledMessage } from "@/lib/relay";
import { deniedPage } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { fmtPrice } from "@/lib/format";
import { ofPlainText } from "@/lib/ofRichText";

import { RefreshButton } from "./RefreshButton";

const AUTO_MASS = "/growth/auto-mass";

/** The list's columns at their widths (px); Actions pinned right, as the Mass messages table pins it. */
const COLUMNS = [
  { label: "Scheduled for", width: 210 },
  { label: "Creator", width: 160 },
  { label: "Audience", width: 180 },
  { label: "Message", width: 360 },
  { label: "Attachment / Price", width: 160 },
  { label: "Actions", width: 100 },
] as const;
const TABLE_WIDTH = COLUMNS.reduce((w, c) => w + c.width, 0);

export default function ScheduledTab() {
  const accounts = useActiveAccounts();
  const accountIds = useMemo(() => accounts.map((a) => a.id), [accounts]);
  const { rows, isLoading, isFetching, error, queries } = useScheduledMessages(accountIds);
  const cancelM = useCancelScheduled();
  const { ask, modal: confirmModal } = useIfConfirm();
  // Repeating sends live on My Automations' Auto Mass; its link shows only where the role may open it.
  const autoMass = deniedPage(AUTO_MASS, useGrantedPages()) === null;

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
        <IfHelp className="mb-4">
          All queued sends across the agency. Cancel before they fire.
          {autoMass && (
            <>
              {" "}
              <Link href={AUTO_MASS} className="text-fg-dim underline underline-offset-2 hover:text-accent">
                Repeat a mass on a schedule → Auto Mass
              </Link>
            </>
          )}
        </IfHelp>

        {error && (
          <div role="alert" className="mb-3 flex flex-wrap items-center gap-x-3 text-[14px] text-err">
            <span title={error.message}>Couldn&apos;t load scheduled messages.</span>
            <IfButton variant="link" onClick={refresh}>Retry</IfButton>
          </div>
        )}

        <div className="@container overflow-x-auto">
          <table className={cn(IF_TABLE.table, "table-fixed")} style={{ width: TABLE_WIDTH, minWidth: "100%" }}>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.label} style={{ width: c.width }} className={cn(
                    IF_TABLE.th, IF_TABLE.thDivider, "border-b border-border",
                    c.label === "Actions" && cn(IF_TABLE.fixedRightHead, "z-[1] text-center"),
                  )}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading && rows.length === 0 ? (
                <SkeletonRows cols={COLUMNS.length} rows={3} cellClassName={IF_TABLE.td} />
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="p-0">
                    {/* EmptyState sticks itself; the cap keeps it centred in the scroller, not the wider table. */}
                    <EmptyState kind="data" size="md" text="Nothing queued." className="max-w-[100cqw] py-16" />
                  </td>
                </tr>
              ) : rows.map((m) => (
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
            </tbody>
          </table>
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
  const media = m.mediaCount ?? 0;
  const priced = !!m.price && m.price > 0;
  const text = ofPlainText(m.text || "");

  return (
    <tr className={cn(IF_TABLE.row, busy && "opacity-60")}>
      <td className={IF_TABLE.td}>
        <span className={cn(
          "inline-block rounded px-1.5 py-0.5 text-[12px]",
          overdue ? "bg-warn/15 text-warn" : "bg-accent/15 text-accent",
        )}>
          {when ? when.toLocaleString() : "no time"}
          {overdue && " (overdue)"}
        </span>
      </td>
      <td className={cn(IF_TABLE.td, "truncate")}>{accountLabel}</td>
      <td className={cn(IF_TABLE.td, "text-fg-dim")}>
        {isMass ? `Mass (${massLabel})` : `Direct to ${directCount} fan${directCount === 1 ? "" : "s"}`}
      </td>
      <td className={IF_TABLE.td}>
        {text
          ? <div className="line-clamp-2 whitespace-pre-wrap break-words" title={text}>{text}</div>
          : <span className="text-fg-dim">--</span>}
      </td>
      <td className={IF_TABLE.td}>
        {media === 0 && !priced ? <span className="text-fg-dim">--</span> : (
          <span className="inline-flex items-center gap-3 text-[12px]">
            {media > 0 && (
              <span className="text-fg-dim inline-flex items-center gap-1">
                <Paperclip size={12} aria-hidden /> {media}
              </span>
            )}
            {priced && (
              <span className="text-warn inline-flex items-center gap-1">
                <Lock size={12} aria-hidden /> {fmtPrice(Math.round(m.price! * 100))}
              </span>
            )}
          </span>
        )}
      </td>
      <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "z-[1] bg-bg-elev-1 text-center")}>
        <IfButton variant="link" onClick={onCancel} disabled={busy}>
          Cancel
        </IfButton>
      </td>
    </tr>
  );
}
