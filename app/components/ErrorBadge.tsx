"use client";


import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";
import { fmtRelTime, cn } from "@/lib/utils";
import { useDeferredMount } from "@/hooks/useDeferredMount";
import { HEADER_TILE } from "@/components/shell/headerTile";
import { useOptionalUser } from "@/contexts/UserContext";
import { useOptionalChatter } from "@/contexts/ChatterContext";
import { isChatterOnly } from "@/lib/session";

interface ErrorRow {
  id: number;
  occurred_at: string;
  source: string;
  kind: string;
  message: string;
  stack: string | null;
  url: string | null;
}

interface ErrorListResp {
  count: number;
  since_hours: number;
  list: ErrorRow[];
}

export function useRecentErrors(enabled = true) {
  // The Top bar defers the first read ~1s so it doesn't compete with the chat-list fetch for relay threads on cold load.
  const q = useQuery<ErrorListResp>({
    queryKey: ["app-errors", "recent"],
    queryFn: () => relay.get<ErrorListResp>("/admin/errors?since_hours=24&limit=50"),
    enabled,
    refetchInterval: ssePoll(15 * 60_000, 5 * 60_000),
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  return { q, count: q.data?.count ?? 0 };
}

export function ErrorPanel({ className, onCleared }: { className?: string; onCleared?: () => void }) {
  const qc = useQueryClient();
  const { q, count } = useRecentErrors();
  const chatterOnly = isChatterOnly(useOptionalUser()?.user, useOptionalChatter()?.chatter);
  const clear = useMutation({
    mutationFn: () => relay.delete<{ ok: boolean; deleted: number }>("/admin/errors?since_hours=24"),
    onSuccess: () => {
      qc.setQueryData<ErrorListResp>(["app-errors", "recent"], (prev) =>
        prev ? { ...prev, count: 0, list: [] } : prev,
      );
      qc.invalidateQueries({ queryKey: ["app-errors", "recent"] });
    },
  });
  return (
    <div className={cn("bg-panel border border-border rounded-lg shadow-xl flex flex-col", className)}>
      <header className="px-3 py-2 border-b border-border flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">Recent errors</div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-fg-dim">
            {count} in {q.data?.since_hours ?? 24}h
          </span>
          {count > 0 && !chatterOnly && (
            <button
              type="button"
              onClick={() => clear.mutate(undefined, { onSuccess: () => onCleared?.() })}
              disabled={clear.isPending}
              className="text-[11px] px-2 py-0.5 rounded border border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-fg-dim hover:text-fg disabled:opacity-50"
              title="Dismiss all errors from the last 24h"
            >
              {clear.isPending ? "Clearing…" : "Clear"}
            </button>
          )}
        </div>
      </header>
      <div className="flex-1 overflow-y-auto">
        {q.isLoading && (
          <div className="p-3 text-xs text-fg-dim">Loading…</div>
        )}
        {!q.isLoading && count === 0 && (
          <div className="p-3 text-xs text-fg-dim">No errors. 🎉</div>
        )}
        {q.data?.list.map((row) => (
          <ErrorEntry key={row.id} row={row} />
        ))}
      </div>
    </div>
  );
}

export function ErrorBadge() {
  const [open, setOpen] = useState(false);
  const popRef = useRef<HTMLDivElement | null>(null);
  const ready = useDeferredMount(1000);
  const { count } = useRecentErrors(ready);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!popRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative hidden lg:block shrink-0" ref={popRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          HEADER_TILE,
          "px-2 gap-1 text-sm",
          count > 0 ? "bg-err/15 text-err hover:bg-err/25 hover:text-err" : "text-fg-dim hover:text-fg",
        )}
        title={`${count} error${count === 1 ? "" : "s"} in last 24h`}
        aria-label="Recent errors"
        aria-expanded={open}
      >
        <span aria-hidden>🐞</span>
        {count > 0 && <span className="text-[11px] font-semibold tabular-nums">{count}</span>}
      </button>
      {open && (
        <ErrorPanel className="absolute right-0 mt-1 w-[420px] max-h-[60vh] z-40" onCleared={() => setOpen(false)} />
      )}
    </div>
  );
}

function ErrorEntry({ row }: { row: ErrorRow }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border-b border-border/60 px-3 py-2 text-xs">
      <div className="flex items-baseline gap-2">
        <span
          className={cn(
            "text-[10px] uppercase font-semibold tracking-wide px-1.5 py-0.5 rounded",
            row.source === "server" ? "bg-warn/15 text-warn" : "bg-err/15 text-err",
          )}
        >
          {row.source}
        </span>
        <span className="text-fg-dim text-[10px]">{row.kind}</span>
        <span className="text-fg-dim text-[10px] ml-auto">
          {fmtRelTime(row.occurred_at)}
        </span>
      </div>
      <div className="mt-1 break-words text-fg">{row.message}</div>
      {row.url && (
        <div className="mt-0.5 text-[10px] text-fg-dim break-all">{row.url}</div>
      )}
      {row.stack && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[10px] text-fg-dim hover:text-fg underline underline-offset-2"
        >
          {expanded ? "Hide stack" : "Show stack"}
        </button>
      )}
      {expanded && row.stack && (
        <pre className="mt-1 text-[10px] text-fg-dim bg-bg-elev-1 border border-border rounded p-1.5 overflow-auto max-h-40">
          {row.stack}
        </pre>
      )}
    </div>
  );
}
