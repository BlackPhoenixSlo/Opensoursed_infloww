"use client";


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
