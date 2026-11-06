"use client";

/** Hands the HTML's inline relay answers (lib/inlineBoot.ts) to the browser's first fetches of them. Rendered by the
 *  root layout before the providers, so its render runs before any probe's effect; draws nothing. */
import { seedInline, type InlineData } from "@/lib/inlineBoot";

export default function InlineBoot({ data }: { data: InlineData | null }) {
  if (data && typeof window !== "undefined") seedInline(data);
  return null;
}
