"use client";

import { RefreshCw } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

export function FolderRefreshButton({ refresh, fetching }: { refresh: () => unknown; fetching: boolean }) {
  return (
    <IfButton
      variant="link"
      onClick={() => void refresh()}
      disabled={fetching}
      title="Load folders again from OnlyFans"
      className="h-5 gap-1.5 font-normal"
    >
      <RefreshCw className={cn("h-3.5 w-3.5", fetching && "animate-spin")} aria-hidden />
      refresh
    </IfButton>
  );
}
