"use client";


import { useState } from "react";

import { useCancelScheduled, useScheduledMessages } from "@/hooks/useScheduledMessages";
import { stripOFHtml } from "@/lib/ofHtml";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

import { CHAT_EXTRA_ROW, ExtraMenuRow } from "./ExtraMenuRow";
import { fmtPrice } from "@/lib/format";
import { ifConfirm } from "@/components/ui/ifConfirm";

export function ScheduledForChat({
  accountId, fanId,
}: { accountId: string; fanId: FanId }) {
  const { rows, queries, isLoading, error } = useScheduledMessages([accountId]);
  const cancelM = useCancelScheduled();
  const [open, setOpen] = useState(false);

  const mine = rows.filter(
    (m) => (m.userIds?.length ?? 0) === 1 && m.userIds?.[0] === fanId,
  );

  // A failed load disables the row instead of reading 0, which would invite a second send.
  const empty = isLoading || !!error || mine.length === 0;
  const detail = error?.message ?? (empty ? undefined : `${mine.length} scheduled for this fan — click to view/cancel`);

  return (
    <div>
      <ExtraMenuRow
        name="Scheduled chip"
        onClick={() => setOpen((v) => !v)}
        disabled={empty}
        expanded={empty ? undefined : open}
        className={CHAT_EXTRA_ROW}
        detail={detail}
      >
        Scheduled <span className="ml-auto text-[var(--inf-accent-text,var(--color-accent))] tabular-nums">{isLoading ? "…" : error ? "—" : mine.length}</span>
      </ExtraMenuRow>
      {open && !empty && (
        <div className="border border-border rounded-lg max-h-96 overflow-y-auto">
          <div className="px-3 py-2 border-b border-border text-xs font-medium">
            Scheduled for this fan
          </div>
          <div className="p-2 space-y-2">
            {mine.map((m) => {
              const busy = cancelM.isPending && cancelM.variables?.id === m.id;
              const when = m.scheduledDate ? new Date(m.scheduledDate) : null;
              const firstThumb =
                m.media?.[0]?.files?.thumb?.url ||
                m.media?.[0]?.files?.preview?.url ||
                null;
              return (
                <div
                  key={m.id}
                  className={`border border-border rounded-md p-2 text-xs space-y-1 ${busy ? "opacity-60" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={cn(MP.ours.ScheduledForChat.time, "text-fg-dim")}>
                      {when ? when.toLocaleString() : "no time"}
                    </span>
                    <div className={cn(MP.ours.ScheduledForChat.meta, "flex items-center")}>
                      {(m.mediaCount ?? 0) > 0 && (
                        <span className="text-fg-dim">📎 {m.mediaCount}</span>
                      )}
                      {m.price && m.price > 0 && (
                        <span className="text-warn">🔒 {fmtPrice(Math.round(m.price * 100))}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    {firstThumb && (
                      <img
                        src={proxyImage(firstThumb, accountId)}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        className="w-10 h-10 rounded object-cover border border-border shrink-0"
                      />
                    )}
                    <div className="flex-1 min-w-0 line-clamp-3 break-words">
                      {stripOFHtml(m.text || "")}
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={async () => {
                        if (!(await ifConfirm("Cancel this scheduled send?", { danger: true }))) return;
                        cancelM.mutate(
                          { id: m.id, accountId },
                          { onSuccess: () => queries.forEach((q) => q.refetch()) },
                        );
                      }}
                      disabled={busy}
                      className={cn(MP.ours.ScheduledForChat.cancel, "border-err/40 text-err hover:bg-err/10 disabled:opacity-40")}
                    >
                      {busy ? "Cancelling…" : "Cancel"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
