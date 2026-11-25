import { RotateCw } from "lucide-react";

import { IfButton } from "@/components/ui/infloww";
import { cn } from "@/lib/utils";

export function RefreshButton({ onClick, refreshing }: { onClick: () => void; refreshing: boolean }) {
  return (
    <IfButton onClick={onClick} disabled={refreshing}>
      <RotateCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} aria-hidden />
      {refreshing ? "Refreshing…" : "Refresh"}
    </IfButton>
  );
}
