"use client";

import { useEffect, useId, useReducer } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IfButton } from "@/components/ui/infloww";
import { parseUtc } from "@/lib/format";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";

import { afterWatchWrite } from "./leakKeys";
import { cooldown, nextRefreshTime, refreshView, unchanged } from "./leakRefresh";
import { viewerZone } from "./leakView";

export function RefreshButton({ creatorId, scopeAccountId, nextRefreshAt, pending, expired, onQueued, onReadRetry }: {
  creatorId: string;
  scopeAccountId: string | null;
  nextRefreshAt: string | null;
  pending: boolean;
  onQueued: (nextRefreshAt: string, queuedAt: string) => void;
  expired: boolean;
  onReadRetry: () => void;
}) {
  const qc = useQueryClient();
  const noteId = useId();
  const [, tick] = useReducer((n: number) => n + 1, 0);
  const send = useMutation({
    mutationFn: () => relay.post<{ queued_at: string; next_refresh_at: string }>(
      `/admin/leaks/watches/${creatorId}/refresh`, undefined, { accountId: scopeAccountId }),
    onSuccess: (r) => {
      onQueued(r.next_refresh_at, r.queued_at);
      void afterWatchWrite(qc, creatorId);
    },
    onError: (e) => {
      if (!unchanged(e)) void afterWatchWrite(qc, creatorId);
    },
  });
  const localNextRefreshAt = send.data?.next_refresh_at ?? cooldown(send.error)?.until ?? null;
  const expires = parseUtc(nextRefreshTime(localNextRefreshAt, nextRefreshAt))?.getTime();
  useEffect(() => {
    if (expires === undefined) return;
    let timer: ReturnType<typeof setTimeout>;
    const update = () => {
      const remaining = expires - Date.now();
      if (remaining > 0) timer = setTimeout(update, Math.min(remaining, 2_147_483_647));
      else tick();
    };
    update();
    return () => clearTimeout(timer);
  }, [expires]);
  const view = refreshView({ sending: send.isPending, localNextRefreshAt, error: send.error },
    { nextRefreshAt, pending, expired }, new Date(), viewerZone());
  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <IfButton
        aria-disabled={view.disabled}
        aria-describedby={noteId}
        className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        onClick={() => {
          if (view.disabled) return;
          if (expired) onReadRetry();
          else send.mutate();
        }}
      >
        {view.label}
      </IfButton>
      <span role={view.error ? "alert" : "status"} className={cn("min-w-0 break-words", view.error ? "text-[14px] text-err" : "text-[13px] text-muted")}>
        <span className="sr-only">{view.error ? "" : `${view.label}. `}</span>
        <span id={noteId}>{view.note}</span>
      </span>
    </div>
  );
}
