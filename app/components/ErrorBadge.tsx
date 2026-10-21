"use client";

/**
 * ErrorBadge — our error triage badge in the top bar, beside Infloww's static
 * "Operational" pill (TopBar's `StatusPill`): a 🐞 with how many errors have
 * landed in /admin/errors in the last 24h. Click opens a popover with the
 * recent rows so we can triage without leaving the page. At zero it stays,
 * dim and without a count, so the two header items always read as two.
 * Polls every 5 minutes (cheap — one indexed query against a small table).
 *
 * Messages Pro hides the top bar, and its Window header has no badge, as
 * Infloww's.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ssePoll } from "@/lib/events";
import { relay } from "@/lib/relay";
import { fmtRelTime, cn } from "@/lib/utils";
import { useDeferredMount } from "@/hooks/useDeferredMount";
import { HEADER_TILE } from "@/components/shell/headerTile";

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

/** The last 24h of /admin/errors and its count (0 until the first read
 *  lands; `q.data` tells the two apart). `enabled` gates the read: the Top
 *  bar badge defers it (see `ErrorBadge`); an opened menu row or panel reads
 *  at once. */
export function useRecentErrors(enabled = true) {
  const q = useQuery<ErrorListResp>({
    queryKey: ["app-errors", "recent"],
    queryFn: () => relay.get<ErrorListResp>("/admin/errors?since_hours=24&limit=50"),
    enabled,
    refetchInterval: ssePoll(15 * 60_000, 5 * 60_000), // SSE: session_dead / failed runs invalidate
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  return { q, count: q.data?.count ?? 0 };
}

/** The error popover's panel: header with the count and Clear, then the
 *  recent rows. `className` places and sizes it; `onCleared` runs after a
 *  successful Clear. */
export function ErrorPanel({ className, onCleared }: { className?: string; onCleared?: () => void }) {
  const qc = useQueryClient();
  const { q, count } = useRecentErrors();
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
          {count > 0 && (
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
  // The first read waits ~1s so it doesn't compete with the chat-list fetch
  // for relay threads on cold load; the badge only matters as a "did
  // something break in the last 24h" indicator, and a one-second delay is
  // invisible to anyone not staring at the icon.
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
          // The header's borderless filled tile (`HEADER_TILE`), tinted red with a count.
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
