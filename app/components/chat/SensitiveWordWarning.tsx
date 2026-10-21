"use client";

import { SENSITIVE_HIT_LEAD } from "@/lib/sensitiveWords";
import { cn } from "@/lib/utils";

/**
 * Infloww's sensitive-word notice: "Input contains prohibited language: [word] [word]",
 * shown under (or above) a composer's text while it holds a word from
 * Growth > Sensitive words. Nothing when `hits` is empty.
 */
export function SensitiveWordWarning({ hits, className }: { hits: readonly string[]; className?: string }) {
  if (hits.length === 0) return null;
  return (
    <div
      role="alert"
      data-sensitive-words
      className={cn(
        "flex flex-wrap items-center rounded px-2 py-2 text-xs border bg-err/10 border-err/30 text-fg",
        className,
      )}
    >
      <span>{SENSITIVE_HIT_LEAD}</span>
      {hits.map((w) => (
        <span key={w} className="ml-1.5 text-err">[{w.split(" ").filter(Boolean).join(" ")}]</span>
      ))}
    </div>
  );
}
