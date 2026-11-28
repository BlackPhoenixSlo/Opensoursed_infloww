"use client";

import { useEffect, useId, useReducer } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IfButton } from "@/components/ui/infloww";
import { relay, RelayError } from "@/lib/relay";
import { cn } from "@/lib/utils";

import { afterWatchWrite } from "./leakKeys";
import { cooldownUntil, loaded, refreshReducer, refreshView } from "./leakRefresh";
import { viewerZone } from "./leakView";

const unchanged = (e: Error) => e instanceof RelayError && (e.status === 429 || e.status === 503);

export function RefreshButton({ creatorId, scopeAccountId, nextRefreshAt, pending }: {
  creatorId: string;
  scopeAccountId: string | null;
  nextRefreshAt: string | null;
  pending: boolean;
}) {
  const qc = useQueryClient();
  const noteId = useId();
  const [state, dispatch] = useReducer(refreshReducer, loaded(nextRefreshAt, pending));
  useEffect(() => dispatch({ type: "load", nextRefreshAt, pending }), [nextRefreshAt, pending]);
  const send = useMutation({
    mutationFn: () => relay.post<{ queued_at: string; next_refresh_at: string }>(
      `/admin/leaks/watches/${creatorId}/refresh`, undefined, { accountId: scopeAccountId }),
    onSuccess: (r) => {
      dispatch({ type: "queued", nextRefreshAt: r.next_refresh_at });
      void afterWatchWrite(qc, creatorId);
    },
    onError: (e) => {
      const until = cooldownUntil(e);
      if (until) return dispatch({ type: "cooldown", nextRefreshAt: until });
      dispatch({ type: "fail", message: e.message });
      if (!unchanged(e)) void afterWatchWrite(qc, creatorId);
    },
  });
  const view = refreshView(state, new Date(), viewerZone());
  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <IfButton
        aria-disabled={view.disabled}
        aria-describedby={noteId}
        className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        onClick={() => {
          if (view.disabled) return;
          dispatch({ type: "send" });
          send.mutate();
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
