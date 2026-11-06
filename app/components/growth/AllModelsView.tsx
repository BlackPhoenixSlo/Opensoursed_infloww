"use client";

/**
 * Growth > Scripts' "All models" view (CreatorRail's All-models pick): a read-only COVERAGE MATRIX over every owned
 * Creator — one row per distinct sequence (or tag) name, one column per Creator, each cell the Creator's step/script
 * count for that name or "—" when it is missing. The Tag / Sequence toggle mirrors the per-account page's.
 *
 * It reads the lean `GET /admin/saved-replies/overview` (counts only, no bodies). Each row offers "Share to all
 * creators" — feature 1 from the first Creator that already holds it: it fetches that Creator's scripts for the row,
 * then copies them to the whole owned roster (`all_creators`, idempotent, so a re-share adds nothing). Rows render in
 * steps of 200 (`useRenderCap`).
 */

import { useState } from "react";
import { Check, Minus, Share2 } from "lucide-react";

import { ShowMore } from "@/components/growth/ScriptsParts";
import { EmptyState } from "@/components/ui/infloww";
import { useRenderCap } from "@/hooks/useRenderCap";
import { useCopySavedReplies, useScriptsOverview, type ScriptsOverview } from "@/hooks/useSavedReplies";
import { relay, type AccountMeta, type SavedReply } from "@/lib/relay";
import { cn } from "@/lib/utils";

type Kind = "sequences" | "tags";

const creatorName = (a: AccountMeta) => a.nickname || a.name || a.id;

/** The first Creator (overview column order) that already holds `name`'s scripts — the share source. */
function sourceOf(row: { per_account: Record<string, number> }, accounts: ScriptsOverview["accounts"]): string | null {
  for (const a of accounts) if ((row.per_account[a.id] ?? 0) > 0) return a.id;
  return null;
}

export function AllModelsView({ accounts }: { accounts: AccountMeta[] }) {
  const [kind, setKind] = useState<Kind>("sequences");
  const overview = useScriptsOverview();
  const copy = useCopySavedReplies();
  const [sharing, setSharing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const data = overview.data;
  // The matrix columns: the overview's own accounts (nickname off the roster meta when it has one).
  const cols = data?.accounts ?? [];
  const nameOf = (id: string) => {
    const a = accounts.find((x) => x.id === id);
    return a ? creatorName(a) : (cols.find((c) => c.id === id)?.nickname || id);
  };
  const rows = (kind === "sequences" ? data?.sequences : data?.tags) ?? [];
  const { cap, hasMore, more, sentinel } = useRenderCap(rows.length, `all-models|${kind}`);

  async function shareRow(name: string) {
    const row = rows.find((r) => r.name === name);
    const src = row && sourceOf(row, cols);
    if (!src) return;
    setSharing(name);
    setError(null);
    try {
      const list = (await relay.get<{ list: SavedReply[] }>(
        `/admin/saved-replies?account_id=${encodeURIComponent(src)}`,
      )).list ?? [];
      const ids = kind === "sequences"
        ? list.filter((r) => r.script_id === name).map((r) => r.id)
        : list.filter((r) => (r.tags ?? []).includes(name)).map((r) => r.id);
      await copy.mutateAsync({ fromAccountIds: [src], toAccountIds: [], allCreators: true, ids });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Share failed");
    } finally {
      setSharing(null);
    }
  }

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
        <span className="ml-auto text-xs text-fg-dim">{cols.length} creators · {rows.length} {kind === "sequences" ? "sequences" : "tags"}</span>
      </div>

      {error && <div className="px-4 py-2 text-sm text-err">{error}</div>}
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
                const busy = sharing === row.name || (copy.isPending && sharing === row.name);
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
                        disabled={!src || busy || copy.isPending}
                        title="Share to all creators"
                        onClick={() => shareRow(row.name)}
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
