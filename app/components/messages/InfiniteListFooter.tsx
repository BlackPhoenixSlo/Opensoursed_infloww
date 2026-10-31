"use client";

/**
 * The foot of an infinite list: the sentinel that loads the next page as it scrolls into view
 * (useLoadMoreSentinel), a "Load more" button for keyboards and for a page that failed, and an end line once
 * there is no next page. Render it under the rows, only when there are rows.
 */

import { Button } from "@/components/ui/primitives";
import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";

interface Props {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
  /** The end line's words: the reports say "end of results", the post feeds "end of feed". */
  endLabel: string;
}

export default function InfiniteListFooter({ hasNextPage, isFetchingNextPage, fetchNextPage, endLabel }: Props) {
  const sentinelRef = useLoadMoreSentinel(hasNextPage, isFetchingNextPage, fetchNextPage);
  return (
    <>
      <div ref={sentinelRef} className="h-4" />

      {hasNextPage && (
        <div className="flex justify-center pt-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}

      {!hasNextPage && (
        <div className="text-center text-[11px] text-fg-dim py-2">
          {`· ${endLabel} ·`}
        </div>
      )}
    </>
  );
}
