"use client";


import { Button } from "@/components/ui/primitives";
import { useLoadMoreSentinel } from "@/hooks/useLoadMoreSentinel";

interface Props {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
  isError?: boolean;
  endLabel: string;
}

export default function InfiniteListFooter({
  hasNextPage, isFetchingNextPage, fetchNextPage, isError, endLabel,
}: Props) {
  const sentinelRef = useLoadMoreSentinel(hasNextPage, isFetchingNextPage, fetchNextPage, isError);
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
