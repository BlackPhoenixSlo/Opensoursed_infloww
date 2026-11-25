"use client";


import { Layers } from "lucide-react";

import { useScope } from "@/contexts/ScopeContext";
import { usePickAllModels } from "@/hooks/usePickAllModels";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

const ALL_MODELS_DETAIL = "All models";
export const GROUP_CHAT_DETAIL = "Add to group chat tab";

export function AllModelsTab() {
  const { pickAll } = usePickAllModels();
  const { scope } = useScope();
  const active = scope.kind === "all";
  return (
    <button
      type="button"
      onClick={pickAll}
      aria-pressed={active}
      title={extraTitle("All Models", ALL_MODELS_DETAIL)}
      className={cn(
        MP.windowHeader.allModels,
        "self-end inline-flex items-center whitespace-nowrap transition-colors",
        active ? "bg-accent text-white" : "bg-accent/15 text-[var(--inf-accent-text,var(--color-accent-hover))] hover:bg-accent hover:text-white",
      )}
    >
      <Layers aria-hidden className={MP.windowHeader.allModelsIcon} />
      All Models
    </button>
  );
}
