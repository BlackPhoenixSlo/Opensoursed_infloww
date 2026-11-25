"use client";

import { SENSITIVE_HIT_LEAD } from "@/lib/sensitiveWords";
import { cn } from "@/lib/utils";

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
