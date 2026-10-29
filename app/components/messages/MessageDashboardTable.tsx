"use client";

/**
 * MessageDashboardTable — the Message dashboard's Direct messages and OnlyFans mass messages table (page-parity
 * ticket 30; bundle `AllMessageTable`): `IF_TABLE`, eleven columns, Infloww's order and cell rules.
 *
 * - Sender: the Employee, else the mass sender tag, else the automation's name; "--" when none.
 * - Creator: avatar and nickname.
 * - Message: ours, two lines at most. Infloww draws the fan's message above it; no row we read carries that text,
 *   so only ours shows.
 * - Sent time: "h:mm A" over "MMM D, YYYY" in the report time zone.
 * - Reply time: `reply_seconds` as "2m 10s"; "--" when the message before was not the fan's.
 * - Price: "--" on a free message. Purchased: a check or a cross on a priced message ("N of M" bought on a mass
 *   summary), "--" on a free one. A purchase counts as recorded, so a sale not yet cleared reads as bought.
 * - Source: AI chatbot (an automation sent it) or Employee. Infloww's AI Copilot is not told apart (a Copilot send
 *   is the Employee's).
 * - Status: Sent / Unsent (its reason in the tooltip). Sent to: the fan, or "N fans" on a mass summary.
 * - Actions: Open chat (Messages Pro's window), and Unsend where `canOfferUnsend`.
 *
 * Keyset paging: the sentinel row loads the next page as it scrolls into view; the end line closes the list.
 */

import { useMemo, type ReactNode } from "react";
import Link from "next/link";
import { Check, Info, MessageSquare, X } from "lucide-react";

import { automationLabel } from "@/components/messages/MessageRowGeneric";
import UnsendMessageButton, { canOfferUnsend } from "@/components/messages/UnsendMessageButton";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { EmptyState, IF_TABLE } from "@/components/ui/infloww";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAccounts } from "@/hooks/useAccounts";
import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";
import type { PaidMessageRow } from "@/hooks/usePaidMessages";
import { parseUtc } from "@/lib/format";
import { fmtPrice, stripHtml } from "@/lib/messageFormat";
import { onPopoutClick } from "@/lib/nav";
import { cn } from "@/lib/utils";

const DASH = "--";

/** The header row, in Infloww's order; `tip` draws the (i) with Infloww's text. */
export const COLUMNS: Array<{ title: string; tip?: string; width: number }> = [
  { title: "Sender", width: 120 },
  { title: "Creator", width: 180 },
  { title: "Message", tip: "The top message is sent by the fan and the bottom message is sent by the sender.", width: 500 },
  { title: "Sent time", width: 130 },
  { title: "Reply time", tip: "Tracks how long it takes for an employee to reply to a fan. If the previous message isn’t from a fan, there’s no reply time.", width: 110 },
  { title: "Price", tip: "How much the content costs to unlock. Will be left empty if content is free.", width: 100 },
  { title: "Purchased", width: 100 },
  { title: "Source", width: 97 },
  { title: "Status", width: 100 },
  { title: "Sent to", width: 150 },
  { title: "Actions", width: 120 },
];

/** Infloww's reply time: whole minutes and seconds, "--" for none. */
export function replyTime(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return DASH;
  return `${Math.floor(sec / 60)}m ${Math.floor(sec % 60)}s`;
}

function senderOf(r: PaidMessageRow): string {
  return r.employee_name || r.sender_name || automationLabel(r.automation_kind) || DASH;
}

export default function MessageDashboardTable({
  rows, reportTz, loading, error, onRetry, dim, hasNextPage, isFetchingNextPage, fetchNextPage,
}: {
  rows: PaidMessageRow[];
  reportTz: string | null;
  loading: boolean;
  error?: boolean;
  onRetry?: () => void;
  /** A refetch under the old rows (placeholder data). */
  dim?: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
}) {
  const accounts = useAccounts().data?.accounts;
  const byId = useMemo(() => new Map((accounts ?? []).map((a) => [a.id, a])), [accounts]);
  const time = useMemo(() => new Intl.DateTimeFormat("en-US", {
    hour: "numeric", minute: "2-digit", timeZone: reportTz ?? undefined,
  }), [reportTz]);
  const day = useMemo(() => new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: reportTz ?? undefined,
  }), [reportTz]);

  // A callback ref: the sentinel unmounts under an error and mounts again on Retry, and is observed again.
  const sentinelRef = useLoadMoreSentinel(hasNextPage, isFetchingNextPage, fetchNextPage);

  const span = COLUMNS.length;
  let body: ReactNode;
  if (error) {
    body = <FullRow span={span}><EmptyState kind="error" text="Unable to load page. Try again later" onRetry={onRetry} /></FullRow>;
  } else if (loading) {
    body = Array.from({ length: 6 }, (_, i) => (
      <tr key={i} className={IF_TABLE.row} aria-busy="true">
        {COLUMNS.map((c, j) => <td key={j} className={IF_TABLE.td}><Skeleton className="h-3 w-16" /></td>)}
      </tr>
    ));
  } else if (!rows.length) {
    body = <FullRow span={span}><EmptyState /></FullRow>;
  } else {
    body = rows.map((r) => {
      const sent = parseUtc(r.sent_at);
      const acct = byId.get(r.account_id);
      const priced = r.price_cents > 0;
      const href = `/messages-pro/${r.account_id}/${r.fan_id}`;
      return (
        <tr key={`${r.account_id}:${r.fan_id}:${r.message_id}`} className={IF_TABLE.row}>
          <td className={IF_TABLE.td}><span className="line-clamp-1 break-all">{senderOf(r)}</span></td>
          <td className={IF_TABLE.td}>
            <span className="flex min-w-0 items-center gap-2">
              {acct && (
                <span className="h-6 w-6 shrink-0 overflow-hidden rounded-full">
                  <AccountAvatarPicture account={acct} letters={1} initialClassName="text-[11px]" />
                </span>
              )}
              <span className="truncate">{acct?.nickname || r.account_id}</span>
            </span>
          </td>
          <td className={IF_TABLE.td}>
            <span className="line-clamp-2 break-words">
              {stripHtml(r.body) || (r.media_count > 0 ? `${r.media_count} media` : DASH)}
            </span>
          </td>
          <td className={IF_TABLE.td}>
            {sent ? (
              <span className="flex flex-col whitespace-nowrap">
                <span>{time.format(sent)}</span>
                <span className="text-[12px] text-muted">{day.format(sent)}</span>
              </span>
            ) : DASH}
          </td>
          <td className={IF_TABLE.td}>{replyTime(r.reply_seconds)}</td>
          <td className={IF_TABLE.td}>{priced ? fmtPrice(r.price_cents) : DASH}</td>
          <td className={IF_TABLE.td}><Purchased row={r} /></td>
          <td className={IF_TABLE.td}>{r.automation_kind ? "AI chatbot" : "Employee"}</td>
          <td className={IF_TABLE.td}>
            {r.is_unsent ? (
              <span className="inline-flex items-center gap-1.5 text-err" title={r.unsent_reason ? `Unsent: ${r.unsent_reason}` : undefined}>
                Unsent{r.unsent_reason && <Info className="h-3 w-3" aria-hidden />}
              </span>
            ) : "Sent"}
          </td>
          <td className={IF_TABLE.td}>
            <span className="line-clamp-1 break-all">
              {r.is_mass_summary
                ? `${r.recipient_count ?? 0} fans`
                : r.fan.display_name || (r.fan.username ? `@${r.fan.username}` : `#${r.fan_id}`)}
            </span>
          </td>
          <td className={cn(IF_TABLE.td, IF_TABLE.fixedRight, "w-[120px]")}>
            <span className="flex items-center justify-center gap-2">
              {!r.is_mass_summary && (
                <Link href={href} onClick={(e) => onPopoutClick(e, href)} aria-label="Open chat" title="Open chat"
                  className="text-accent hover:text-accent-hover">
                  <MessageSquare className="h-5 w-5" aria-hidden />
                </Link>
              )}
              {canOfferUnsend(r) && <UnsendMessageButton row={r} />}
            </span>
          </td>
        </tr>
      );
    });
  }

  return (
    <div className={cn("transition-opacity", dim && "opacity-60")}>
      <div className="overflow-x-auto">
        {/* antd's `scroll: {x: 1100}` with these column widths: a fixed layout as wide as the columns, scrolling
            sideways under the pinned Actions column. */}
        <table className={cn(IF_TABLE.table, "table-fixed min-w-[1100px]")}>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.title} scope="col" style={{ width: c.width }}
                  className={cn(IF_TABLE.th, IF_TABLE.thDivider, c.title === "Actions" && cn(IF_TABLE.fixedRightHead, "w-[120px] text-center"))}>
                  <span className="inline-flex items-center gap-1">
                    {c.title}
                    {c.tip && (
                      <span role="img" aria-label={c.tip} title={c.tip} className="cursor-help">
                        <Info className="h-3.5 w-3.5" aria-hidden />
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </div>
      {!loading && !error && rows.length > 0 && (
        <>
          <div ref={sentinelRef} className="h-4" />
          <p className="py-2 text-center text-[12px] text-muted">
            {hasNextPage ? (isFetchingNextPage ? "Loading…" : "") : "You have reached the end of the page"}
          </p>
        </>
      )}
    </div>
  );
}

function FullRow({ span, children }: { span: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={span} className="py-[110px] text-center">{children}</td>
    </tr>
  );
}

function Purchased({ row: r }: { row: PaidMessageRow }) {
  if (r.is_mass_summary) {
    return r.price_cents > 0 ? <>{`${r.purchased_count ?? 0} of ${r.recipient_count ?? 0}`}</> : <>{DASH}</>;
  }
  if (r.price_cents <= 0) return <>{DASH}</>;
  return r.is_paid
    ? <Check role="img" aria-label="Paid" className="h-6 w-6 text-ok" />
    : <X role="img" aria-label="Unpaid" className="h-6 w-6 text-err" />;
}
