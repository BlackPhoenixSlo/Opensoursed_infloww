/**
 * ThreadEmptyState — the Thread with no Fan selected, from lg up: lucide's
 * paper plane (the Clone's icon shape) over "Select any conversation to start" (`.empty`,
 * the deleted Clone's `messages.html:719-722`). Below lg the Fan List
 * fills the screen instead.
 */

import { Send } from "lucide-react";

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const G = MP.emptyState;

export function ThreadEmptyState() {
  return (
    <div data-mp-pane="thread" className={cn(G.root, "hidden lg:flex flex-col items-center justify-center flex-1 min-w-0 h-full text-fg")}>
      <Send aria-hidden className={cn(G.icon, "fill-[var(--inf-glyph-fill,var(--color-accent))] stroke-[var(--inf-glyph-stroke,var(--color-accent-hover))]")} />
      <p className={G.text}>Select any conversation to start</p>
    </div>
  );
}
