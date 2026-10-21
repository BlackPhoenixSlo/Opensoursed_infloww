"use client";

/**
 * StatsRefreshButton — the reports' header Refresh, Infloww's 32px icon button (page-parity ticket 25): a filled
 * surface-level-02-emphasis-00 square (#2a2a2a on the page) with no border and an element-emphasis-00 glyph, as the
 * live v5.7.20 Employee reports capture samples it. It refetches every stats query now (useStatsRefresh), spinning while any is in
 * flight. Sales arriving refetch them on their own (useAccountStateEvents, `transaction_recorded`).
 */

import { useIsFetching } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";
import { useStatsRefresh } from "@/hooks/useStats";
import { cn } from "@/lib/utils";

export default function StatsRefreshButton() {
  const refresh = useStatsRefresh();
  const fetching = useIsFetching({ queryKey: ["stats"] }) > 0;
  return (
    <IfButton
      aria-label="Refresh"
      className="w-8 border-transparent bg-nav-surface px-0 text-nav-fg-active"
      onClick={() => refresh()}
      disabled={fetching}
      title={fetching ? "Refreshing…" : "Re-fetch all stats now"}
    >
      <RotateCw aria-hidden className={cn("h-4 w-4", fetching && "animate-spin")} />
    </IfButton>
  );
}
