"use client";

/**
 * PostsTab — the model's own feed, rendered inside the Messages page.
 *
 * Unlike the PPV/Tips/All tabs (DB aggregates that span "All models"),
 * posts come live off OF per-account, so this tab owns a single-model
 * picker that defaults to the first active account. Paged by
 * InfiniteListFooter.
 */

import { useMemo } from "react";

import { Button } from "@/components/ui/primitives";
import { PostCard } from "@/components/messages/PostCard";
import InfiniteListFooter from "@/components/messages/InfiniteListFooter";
import ModelSelect, { usePickedModel } from "@/components/messages/ModelSelect";
import { usePosts } from "@/hooks/usePosts";
import { TableSkeleton } from "@/components/ui/Skeleton";

export default function PostsTab() {
  const { accounts, accountId, setAccountId } = usePickedModel();

  const q = usePosts(accountId);
  const posts = useMemo(
    () => (q.data?.pages ?? []).flatMap((p) => p.posts),
    [q.data],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 p-3 bg-panel border border-border rounded-xl">
        <ModelSelect accounts={accounts} value={accountId} onChange={setAccountId} />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => q.refetch()}
          disabled={!accountId || q.isFetching}
          className="self-end border-border"
        >
          {q.isFetching ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {q.isError && (
        <div className="p-4 text-sm text-err border border-err/30 bg-err/10 rounded-xl">
          Failed to load posts: {(q.error as Error)?.message || "unknown error"}
        </div>
      )}

      {!accountId ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          Pick a model to see their posts.
        </div>
      ) : q.isPending ? (
        <TableSkeleton rows={6} className="m-4" />
      ) : posts.length === 0 ? (
        <div className="p-8 text-center text-sm text-fg-dim border border-border rounded-xl bg-panel">
          No posts on this account yet.
        </div>
      ) : (
        <div className="space-y-3">
          {posts.map((p) => (
            <PostCard key={p.id} post={p} accountId={accountId} />
          ))}

          <InfiniteListFooter
            hasNextPage={q.hasNextPage}
            isFetchingNextPage={q.isFetchingNextPage}
            fetchNextPage={q.fetchNextPage}
            endLabel="end of feed"
          />
        </div>
      )}
    </div>
  );
}
