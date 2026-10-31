"use client";

/**
 * GifPicker — inline strip rendered above the composer toolbar (mirrors OF
 * desktop). The Composer owns the open/close state and the 🎬 toggle
 * button; this file exports the strip + a `toPicked` adapter.
 *
 * Wire-format: send via top-level `giphyId` on /chats/{id}/messages.
 * Verified live 2026-05-23.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { TOOLBAR_ICON } from "./ComposerToolbar";
import {
  gifSearch, gifTrending,
  type GiphyItem, type GiphyResponse,
} from "@/lib/relay";
import { INITIAL_GIFS, PAGE_SIZE, gifReducer } from "./gifPickerState";

export interface PickedGif {
  id: string;
  /** Animated preview URL the chip + grid render. */
  thumbUrl: string;
  /** Full-size URL — useful for the optimistic message bubble later. */
  fullUrl: string;
  width?: number;
  height?: number;
  title?: string;
}

function toPicked(g: GiphyItem): PickedGif {
  const fh = g.images.fixed_height ?? g.images.original;
  const orig = g.images.original;
  return {
    id: g.id,
    thumbUrl: fh?.url ?? orig?.url ?? "",
    fullUrl: orig?.url ?? fh?.url ?? "",
    width: orig?.width ? Number(orig.width) : undefined,
    height: orig?.height ? Number(orig.height) : undefined,
    title: g.title,
  };
}

/**
 * Inline strip — rendered above the composer textarea when the user
 * clicks 🎬. Search input runs the row across the top; below is a
 * horizontally-scrolling row of trending / search results.
 */
export function GifPickerStrip({
  accountId, onPick, onClose,
}: {
  accountId: string | null;
  onPick: (gif: PickedGif) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [{ items, loading, error, hasMore }, dispatch] = useReducer(gifReducer, INITIAL_GIFS);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Debounce the search box so we don't fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    setTimeout(() => searchInputRef.current?.focus(), 50);
    return () => abortRef.current?.abort();
  }, []);

  // One page fetch, through one abortRef: a new fetch (a query change, or "more") aborts the one in flight, so a
  // fast typer never sees stale results paint over fresh ones, and a stale "more" never appends the OLD query's
  // page onto the NEW query's first page. Aborted fetches never dispatch.
  const fetchPage = useCallback((offset: number) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    dispatch({ type: "start" });
    const ctx = { accountId };
    const p: Promise<GiphyResponse> = debouncedSearch
      ? gifSearch(debouncedSearch, PAGE_SIZE, offset, ctx, ctrl.signal)
      : gifTrending(PAGE_SIZE, offset, ctx, ctrl.signal);
    p.then((resp) => {
      if (!ctrl.signal.aborted) dispatch({ type: "loaded", resp, offset });
    }).catch((e: unknown) => {
      if (!ctrl.signal.aborted) dispatch({ type: "failed", message: e instanceof Error ? e.message : String(e), offset });
    });
    return ctrl;
  }, [debouncedSearch, accountId]);

  // Fetch the first page on mount + whenever the (debounced) query changes.
  useEffect(() => {
    const ctrl = fetchPage(0);
    return () => ctrl.abort();
  }, [fetchPage]);

  const loadMore = () => fetchPage(items.length);

  const grid = useMemo(() => items.map(toPicked), [items]);

  return (
    <div className="bg-bg/60 border border-border rounded-lg">
      <div className="p-2 border-b border-border flex items-center gap-2">
        <button
          type="button"
          onClick={onClose}
          className="w-10 h-10 md:w-6 md:h-6 grid place-items-center rounded-md text-fg-dim hover:text-fg hover:bg-bg-elev-1 shrink-0"
          aria-label="Close GIF picker"
          title="Close"
        >
          ✕
        </button>
        <input
          ref={searchInputRef}
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search GIFs…"
          className="flex-1 bg-transparent border border-border rounded-md px-2 py-1 text-base md:text-xs placeholder:text-muted focus:outline-none focus:border-accent"
        />
        <span className="text-[10px] text-fg-dim shrink-0">
          {debouncedSearch ? "search" : "trending"}
        </span>
      </div>

      <div className="p-2">
        {error && (
          <div className="text-[11px] text-err py-2 text-center">
            {error.slice(0, 200)}
          </div>
        )}
        {grid.length === 0 && !loading && !error && (
          <div className="text-xs text-fg-dim text-center py-4">
            {debouncedSearch ? `No GIFs match "${debouncedSearch}".` : "No GIFs."}
          </div>
        )}
        {grid.length > 0 && (
          <div className="grid grid-cols-3 gap-1.5 max-h-56 overflow-y-auto overscroll-contain md:flex md:max-h-none md:overflow-y-visible md:overflow-x-auto pb-1 scrollbar-thin">
            {grid.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => onPick(g)}
                className={cn(
                  "w-full aspect-square md:aspect-auto md:shrink-0 md:w-32 md:h-32 rounded-md overflow-hidden border border-border bg-bg-elev-1",
                  "hover:border-accent focus:border-accent focus:outline-none",
                )}
                title={g.title}
              >
                {g.thumbUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={g.thumbUrl}
                    alt={g.title || "GIF"}
                    loading="lazy"
                    className="w-full h-full object-cover"
                  />
                ) : null}
              </button>
            ))}
            {hasMore && (
              <button
                type="button"
                onClick={loadMore}
                disabled={loading}
                className="w-full aspect-square md:aspect-auto md:shrink-0 md:w-24 md:h-32 rounded-md border border-dashed border-border text-[11px] text-fg-dim hover:text-fg hover:bg-bg-elev-1 disabled:opacity-40"
              >
                {loading ? "…" : "more →"}
              </button>
            )}
          </div>
        )}
        {loading && grid.length === 0 && (
          <div className="text-[11px] text-fg-dim text-center py-3">Loading…</div>
        )}
      </div>
    </div>
  );
}

/**
 * Toolbar toggle. Stateless — parent passes `open` + `onToggle`; the
 * actual GIF strip mounts elsewhere in the composer's layout.
 * `messagesPro` (only the Composer passes it) makes it the 34px borderless
 * "GIF" toolbar icon (Clone `#cbGif`, messages.html:756).
 */
export function GifPickerButton({
  open, onToggle, disabled, messagesPro,
}: {
  open: boolean;
  onToggle: () => void;
  disabled?: boolean;
  messagesPro?: boolean;
}) {
  if (messagesPro) {
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={onToggle}
        aria-label="GIF"
        title="Send a GIF"
        className={cn(TOOLBAR_ICON, open ? "text-[var(--inf-accent-text,var(--color-accent))]" : "text-fg-dim hover:text-fg")}
      >
        <svg width={20} height={20} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.4} aria-hidden>
          <rect x="3" y="6" width="18" height="12" rx="2" />
          <text x="12" y="15" fontSize="7" fontWeight="700" textAnchor="middle" fill="currentColor" stroke="none">GIF</text>
        </svg>
      </button>
    );
  }
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "w-8 h-8 grid place-items-center rounded-md border text-sm",
        open
          ? "bg-accent/15 text-[var(--inf-accent-text,var(--color-accent))] border-accent/40"
          : "bg-transparent text-fg-dim border-border hover:bg-bg-elev-1",
        disabled && "opacity-40 cursor-not-allowed",
      )}
      aria-label="GIF picker"
      title="Send a GIF"
    >
      🎬
    </button>
  );
}
