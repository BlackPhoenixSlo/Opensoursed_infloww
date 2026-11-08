"use client";

/**
 * Growth > Scripts' "All models" view (CreatorRail's All-models pick): a read-only COVERAGE MATRIX over every owned
 * Creator — one row per distinct sequence (or tag) name, one column per Creator, each cell the Creator's step/script
 * count for that name or "—" when it is missing. The Tag / Sequence toggle mirrors the per-account page's.
 *
 * It reads the lean `GET /admin/saved-replies/overview` (counts only, no bodies). Each row offers "Share to all
 * creators" — feature 1 from the first Creator that already holds it: it reads that Creator's scripts for the row
 * (its list query, fetched fresh), then copies them to the rest of the owned roster (`all_creators`,
 * idempotent, so a re-share adds nothing) and shows what the copy did. One share at a time: the share's mutation
 * holds the row, its failure and its result. Rows render in steps of 200 (`useRenderCap`).
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, Share2 } from "lucide-react";

import { CopySummary } from "@/components/growth/ScriptsImportDialogs";
import { ShowMore, creatorName } from "@/components/growth/ScriptsParts";
import { entryIds } from "@/components/growth/scriptsPageState";
import { EmptyState } from "@/components/ui/infloww";
import { useRenderCap } from "@/hooks/useRenderCap";
import {
  savedRepliesQuery, useCopySavedReplies, useScriptsOverview, type SavedReplyCopyResult, type ScriptsOverview,
} from "@/hooks/useSavedReplies";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";

type Kind = "sequences" | "tags";

/** One row's share: the entry and the Creator it is copied from. */
interface Share {
  kind: Kind;
  name: string;
  src: string;
}

/** The first Creator (overview column order) that already holds `name`'s scripts — the share source. */
function sourceOf(row: { per_account: Record<string, number> }, accounts: ScriptsOverview["accounts"]): string | null {
  for (const a of accounts) if ((row.per_account[a.id] ?? 0) > 0) return a.id;
  return null;
}

export function AllModelsView({ accounts }: { accounts: AccountMeta[] }) {
  const [kind, setKind] = useState<Kind>("sequences");
  const overview = useScriptsOverview();
  const copy = useCopySavedReplies();
  const qc = useQueryClient();
  const share = useMutation<SavedReplyCopyResult, Error, Share>({
    mutationFn: async ({ kind: k, name, src }) => {
      // Fresh, never the cache's up-to-5-min-old list: a stale one would share yesterday's ids.
      const list = await qc.fetchQuery({ ...savedRepliesQuery(src), staleTime: 0 });
      const ids = entryIds(k === "sequences" ? "sequence" : "tag", name, list);
      return copy.mutateAsync({ fromAccountIds: [src], toAccountIds: [], allCreators: true, ids });
    },
  });

  const data = overview.data;
  // The matrix columns: the overview's own accounts, named off the roster meta when it has one.
  const cols = data?.accounts ?? [];
  const nameOf = (id: string) => creatorName(accounts.find((x) => x.id === id) ?? cols.find((c) => c.id === id) ?? { id });
  const rows = (kind === "sequences" ? data?.sequences : data?.tags) ?? [];
  const { cap, hasMore, more, sentinel } = useRenderCap(rows.length, `all-models|${kind}`);

  return (
    <div className="flex flex-1 flex-col min-w-0">
      {/* The Tag / Sequence toggle, mirroring the per-account page's tabs. */}
      <div className="min-h-14 px-3 sm:px-6 flex items-center gap-4 sm:gap-6 border-b border-border">
        {([["sequences", "Sequence"], ["tags", "Tag"]] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={kind === key}
            onClick={() => setKind(key)}
            className={cn("h-14 flex items-center text-sm font-bold border-b-2",
              kind === key ? "text-fg border-accent" : "text-fg-dim border-transparent")}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-fg-dim">{cols.length} creators · {rows.length} {kind}</span>
      </div>

      {share.error && <div role="alert" className="px-4 py-2 text-sm text-err">{share.error.message || "Share failed"}</div>}
      {share.data && share.variables && (
        <div aria-label="Share result" className="px-4 py-3 border-b border-border">
          <p className="mb-1 text-center text-sm font-medium">Shared “{share.variables.name}” to all creators</p>
          <CopySummary result={share.data} />
        </div>
      )}
      {overview.isLoading && <div className="px-4 py-2 text-sm text-fg-dim">Loading…</div>}
      {overview.error && <div className="px-4 py-2 text-sm text-err">Failed to load: {overview.error.message || "unknown"}</div>}

      {!overview.isLoading && !overview.error && rows.length === 0 ? (
        <EmptyState size="sm" text="No data" />
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="min-w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr className="text-left text-xs text-fg-dim">
                <th className="sticky left-0 z-[1] bg-bg px-4 py-2">{kind === "sequences" ? "Sequence" : "Tag"}</th>
                {cols.map((c) => (
                  <th key={c.id} className="px-3 py-2 whitespace-nowrap max-w-[140px] truncate" title={nameOf(c.id)}>
                    {nameOf(c.id)}
                  </th>
                ))}
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, cap).map((row) => {
                const src = sourceOf(row, cols);
                const busy = share.isPending && share.variables?.name === row.name;
                return (
                  <tr key={row.name} className="border-t border-border">
                    <td className="sticky left-0 z-[1] bg-bg px-4 py-2 font-medium max-w-[220px] truncate" title={row.name}>
                      {row.name}
                    </td>
                    {cols.map((c) => {
                      const n = row.per_account[c.id] ?? 0;
                      return (
                        <td key={c.id} className="px-3 py-2 text-center">
                          {n > 0 ? (
                            <span className="inline-flex items-center gap-1 text-ok">
                              <Check size={12} aria-hidden /> {n}
                            </span>
                          ) : (
                            <span aria-label="missing" className="text-fg-dim"><Minus size={12} aria-hidden /></span>
                          )}
                        </td>
                      );
                    })}
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button
                        type="button"
                        disabled={!src || share.isPending}
                        title="Share to all creators"
                        onClick={() => src && share.mutate({ kind, name: row.name, src })}
                        className="inline-flex items-center gap-1 text-accent hover:opacity-90 disabled:opacity-50"
                      >
                        <Share2 size={14} aria-hidden /> {busy ? "Sharing…" : "Share to all"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {hasMore && (
            <div ref={sentinel}>
              <ShowMore left={rows.length - cap} onClick={more} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
