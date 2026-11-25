"use client";

/**
 * Whether a composer for `accountId` may author OF rich text (bold, italic, OF's colours and sizes): only a Creator
 * whose Platform has `rich_text`. Fansly never gets OF markup (its scripts render as literal text in Infloww too,
 * docs/infloww-rich-text-rea.md §3), so there the "Aa" button and the toolbar are gone and a formatted script goes in
 * as its plain text. A Creator the cached list lacks (a cold cache) reads as the sidebar Platform's, so OnlyFans keeps
 * its toolbar while the list loads; an All-models composer passes its first sender.
 */
import { useAccountPlatform } from "@/hooks/useCan";
import { can, usePlatform } from "@/lib/platform";

export function useOfRichAllowed(accountId: string | null | undefined): boolean {
  const sidebar = usePlatform();
  return can(useAccountPlatform(accountId) ?? sidebar, "rich_text");
}
