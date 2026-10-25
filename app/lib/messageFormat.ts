/**
 * messageFormat.ts — formatters shared by the /messages row components
 * (MessageRow, MessageRowGeneric, TipRow, TopTippersCard).
 *
 * These used to live as per-file `fmtPrice` / `stripHtml` copies that had
 * drifted apart — large amounts rendered differently between lists. One
 * copy here keeps every dollar figure and body preview identical.
 */

/** The house money formatters: `fmtCents` for an aggregate (whole dollars, "$86" / "$1,234"), `fmtPrice` for a
 *  unit price (its real cents, "$9.99" / "$10"). */
export { fmtCents, fmtPrice } from "@/lib/format";

/** OF bodies arrive wrapped in <p>…</p>; trim the common cases for a denser
 *  preview. A full parser pass isn't worth it for short previews. */
export function stripHtml(s: string): string {
  return s.replace(/<\/?p[^>]*>/gi, "").replace(/<br\s*\/?>/gi, " ").trim();
}
