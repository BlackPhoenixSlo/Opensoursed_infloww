"use client";

/**
 * TopPostsTab — best-performing posts in the selected window.
 *
 * This is the only place purchases/earnings ranking is available: OF's
 * feed payload carries no per-post buy counts, but /posts/top returns the
 * posts already sorted by the chosen metric. Order = rank, which we surface
 * as a "#N" chip on each card. Uses the page-level date range.
 */

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { PostCard } from "@/components/messages/PostCard";
import ModelSelect, { usePickedModel } from "@/components/messages/ModelSelect";
import { useTopPosts, type TopBy } from "@/hooks/usePosts";
import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/ui/Skeleton";

interface Props {
  from: string | null;
  to: string | null;
}

const METRICS: { key: TopBy; label: string }[] = [
  { key: "purchases", label: "Purchases" },
  { key: "likes", label: "Likes" },
  { key: "comments", label: "Comments" },
  { key: "views", label: "Views" },
];

export default function TopPostsTab({ from, to }: Props) {
  const { accounts, accountId, setAccountId } = usePickedModel();
  const [by, setBy] = useState<TopBy>("purchases");

  const q = useTopPosts(accountId, by, from, to);
  const posts = useMemo(() => q.data ?? [], [q.data]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 p-3 bg-panel border border-border rounded-xl">
        <ModelSelect accounts={accounts} value={accountId} onChange={setAccountId} />

        <label className="flex flex-col gap-1 w-full md:w-auto">
          <span className="text-[10px] uppercase tracking-wide text-fg-dim">Rank by</span>
          <div className="grid grid-cols-4 gap-1 md:flex md:items-center">
            {METRICS.map((m) => (
              <Button
                key={m.key}
                type="button"
                variant={by === m.key ? "primary" : "secondary"}
                size="sm"
                onClick={() => setBy(m.key)}
                className={cn("px-1.5 py-2.5 md:px-3 md:py-1.5", by !== m.key && "border-border")}
              >
                {m.label}
              </Button>
            ))}
          </div>
        </label>

        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => q.refetch()}
          disabled={!accountId || q.isFetching}
          className="hidden md:inline-flex self-end border-border"
        >
          {q.isFetching ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {q.isError && (
        <div className="p-4 text-sm text-err border border-err/30 bg-err/10 rounded-xl">
          Failed to load top posts: {(q.error as Error)?.message || "unknown error"}
        </div>
      )}

      {!accountId ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          Pick a model to see top posts.
        </div>
      ) : q.isPending ? (
        <TableSkeleton rows={6} className="m-4" />
      ) : posts.length === 0 ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          No posts in this window.
        </div>
      ) : (
        <div className="space-y-3">
          {posts.map((p, i) => (
            <PostCard key={p.id} post={p} accountId={accountId} rank={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
