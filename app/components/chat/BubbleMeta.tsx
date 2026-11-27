"use client";

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

export function timeRowShows({ createdAt, scheduled, receipt, employeeLabel }: TimeRowProps): boolean {
  return !!(scheduled ? "" : fmtTime(createdAt)) || !!receipt || !!employeeLabel;
}

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
          {msg._failedUncertain ? (
            <span className="text-err">not confirmed</span>
          ) : (
            <button
              type="button"
              onClick={() => msg._tempId != null && onRetry(msg._tempId)}
              className="text-err hover:underline"
            >
              {msg._failedPaused ? "Sending paused — retry" : "failed — retry"}
            </button>
          )}
          {msg._failedReason && (
            <span className="text-err/80" title={msg._failedReason}>
              · {truncate(msg._failedReason, 80)}
            </span>
          )}
          {onDiscard && <DiscardButton msg={msg} onDiscard={onDiscard} />}
          {/* The "remove N of M" count lives in the tile row, the only place that knows which ids it rendered (MediaStrip `refusedHere`). */}
        </>
      )}
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

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
