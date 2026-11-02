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

/** OF HTML body → plain text keeping its line breaks (<br> and </p> → "\n"), tags dropped, the common entities
 *  decoded, trimmed. Whitespace inside is kept as is (`stripHtmlPreview` collapses it). */
export function htmlToText(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .trim();
}
