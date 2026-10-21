"use client";

/**
 * The Inflowwww extra of Messages Pro's Window header, All Models
 * (ADR-0003; docs/spec/phase-01-window-chrome-tabs.md, Inflowwww extras). It
 * sits first in the Window header, before the Creator tabs strip
 * (`AllModelsTab`; TODO.md B2, 2026-10-16: the way back to every Creator).
 * Group chat lives in the Chat header's Extras overflow; its tooltip's second
 * line is `GROUP_CHAT_DETAIL`. Each takes its tooltip from the catalogue
 * (`extraTitle`, with its old tooltip on the second line).
 */

import { Layers } from "lucide-react";

import { useScope } from "@/contexts/ScopeContext";
import { usePickAllModels } from "@/hooks/usePickAllModels";
import { MP } from "@/lib/messagesPro";
import { extraTitle } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

/** The two extras' old tooltips, their tooltips' second lines: the old
 *  roster icon's title and the old Chat header button's. */
const ALL_MODELS_DETAIL = "All models";
export const GROUP_CHAT_DETAIL = "Add to group chat tab";

/** All Models in the Window header, right after Home, always shown. */
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
