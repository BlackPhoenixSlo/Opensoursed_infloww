"use client";

/**
 * A bubble's meta: the time row (time, receipt, "Sent by <name>"; spec gap
 * rows L3, L5), under a run's last bubble since Phase 4 Part C (look-and-feel
 * T12), and our status row under it (sending…, failed — retry, scheduled,
 * cancel). Split out of `MessageList` (ticket 97).
 */
import { useEffect, useState } from "react";

import type { OFMessage } from "@/lib/relay";
import { clockTime } from "@/lib/format";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return clockTime(d);
}

type TimeRowProps = {
  side: "left" | "right";
  createdAt?: string;
  scheduled: boolean;
  receipt: "delivered" | "seen" | null;
  employeeLabel?: string | null;
};

/** Whether `BubbleTimeRow` renders anything: a scheduled bubble has no time
 *  yet (its fire time is in the status row). */
export function timeRowShows({ createdAt, scheduled, receipt, employeeLabel }: TimeRowProps): boolean {
  return !!(scheduled ? "" : fmtTime(createdAt)) || !!receipt || !!employeeLabel;
}

/** The time row under a run's last bubble (Phase 4 spec T12): the bubble
 *  box's next sibling in its column, in the dim text grey, left under the
 *  Fan's and right under ours. It never widens the bubble: a row longer than
 *  the bubble runs past it on the list's side, on one line. Renders nothing
 *  when it would be empty. */
export function BubbleTimeRow(props: TimeRowProps) {
  const { side, createdAt, scheduled, receipt, employeeLabel } = props;
  const time = scheduled ? "" : fmtTime(createdAt);
  if (!timeRowShows(props)) return null;
  return (
    <div
      data-time-row=""
      className={cn(
        MP.messageList.time, "flex items-baseline whitespace-nowrap [contain:inline-size] text-fg-dim",
        side === "right" ? "justify-end" : "justify-start",
      )}
    >
      {time && <time dateTime={createdAt}>{time}</time>}
      {/* ✓ / ✓✓ on outgoing real-server messages (spec L4). Seen comes from
       *  the Fan's read pointer, surfaced by the parent. */}
      {receipt && (
        <span
          role="img"
          className={cn(MP.messageList.seen, receipt === "seen" && "text-info")}
          title={receipt === "seen" ? "Seen" : "Delivered"}
          aria-label={receipt === "seen" ? "Seen" : "Delivered"}
        >
          {receipt === "seen" ? "✓✓" : "✓"}
        </span>
      )}
      {employeeLabel && (
        <span className={cn(MP.messageList.sentBy, "whitespace-nowrap")} title={`Sent by ${employeeLabel}`}>
          {`Sent by ${employeeLabel}`}
        </span>
      )}
    </div>
  );
}

/** Our status controls under the bubble. Renders nothing for a settled
 *  message. */
function DiscardButton({ msg, onDiscard }: { msg: OFMessage; onDiscard: (tempId: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => msg._tempId != null && onDiscard(msg._tempId)}
      className="text-fg-dim hover:underline"
      aria-label="Discard message"
      title="Remove this unsent message"
    >
      · discard
    </button>
  );
}

export function BubbleStatusRow({ msg, side, scheduled, pending, failed, onRetry, onDiscard, onCancelScheduled }: {
  msg: OFMessage;
  side: "left" | "right";
  scheduled: boolean;
  pending: boolean;
  failed: boolean;
  onRetry: (tempId: number) => void;
  /** Drop a failed send; the "discard" control shows only with it. */
  onDiscard?: (tempId: number) => void;
  onCancelScheduled?: (tempId: number) => void;
}) {
  if (!scheduled && !pending && !failed) return null;
  return (
    <div
      className={cn(
        MP.ours.BubbleMeta.status, "text-fg-dim flex items-center flex-wrap",
        side === "right" ? "justify-end" : "justify-start",
      )}
    >
      {scheduled && (
        <ScheduledStatus fireAt={msg._fireAt ?? msg.createdAt} mediaCount={msg.mediaCount ?? 0} />
      )}
      {pending && !scheduled && <span className="text-warn">{msg._uploading ? "uploading…" : "sending…"}</span>}
      {/* A message waiting on its files can be dropped before it sends. */}
      {pending && !scheduled && msg._uploading && onDiscard && <DiscardButton msg={msg} onDiscard={onDiscard} />}
      {scheduled && onCancelScheduled && msg._scheduleJobId != null && (
        <button
          type="button"
          onClick={() => msg._scheduleJobId != null && onCancelScheduled(msg._scheduleJobId)}
          className="text-err hover:underline"
          title="Cancel this scheduled send (for everyone on the account)."
        >
          cancel
        </button>
      )}
      {failed && (
        <>
          <button
            type="button"
            onClick={() => msg._tempId != null && onRetry(msg._tempId)}
            className="text-err hover:underline"
          >
            failed — retry
          </button>
          {msg._failedReason && (
            <span className="text-err/80" title={msg._failedReason}>
              · {truncate(msg._failedReason, 80)}
            </span>
          )}
          {onDiscard && <DiscardButton msg={msg} onDiscard={onDiscard} />}
          {/* The "remove N of M" count is NOT here: it belongs to the tile
           *  row, which is the only place that knows which ids it actually
           *  rendered and marked. See MediaStrip's `refusedHere`. */}
        </>
      )}
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

/** Live countdown that re-renders every 20s. Short enough to feel
 *  responsive ("Sending in 1 min" → fires shortly after); long enough
 *  to not be wasteful across many pending bubbles in one chat. */
function ScheduledStatus({ fireAt, mediaCount = 0 }:
                         { fireAt: string; mediaCount?: number }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 20_000);
    return () => clearInterval(id);
  }, []);
  const clip = mediaCount > 0 ? ` · 📎 ${mediaCount}` : "";
  const ms = new Date(fireAt).getTime() - Date.now();
  const mins = Math.max(1, Math.round(ms / 60_000));
  const label = ms <= 0
    ? `⏱ sending now…${clip}`
    : `⏱ scheduled · ${fmtTime(fireAt)} (in ${mins} min)${clip}`;
  return <span className="text-[var(--inf-accent-text,var(--color-accent))]">{label}</span>;
}
