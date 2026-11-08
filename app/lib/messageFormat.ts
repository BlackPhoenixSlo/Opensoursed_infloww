/**
 * messageFormat.ts — formatters shared by the /messages row components
 * (MessageRow, MessageRowGeneric, TipRow, TopTippersCard).
 *
 * These used to live as per-file `fmtPrice` / `stripHtml` copies that had
 * drifted apart — large amounts rendered differently between lists. One
 * copy here keeps every dollar figure identical; body previews are
 * lib/ofRichText's `ofPreviewText` / `ofPlainText`.
 */

/** The house money formatters: `fmtCents` for an aggregate (whole dollars, "$86" / "$1,234"), `fmtPrice` for a
 *  unit price (its real cents, "$9.99" / "$10"). */
export { fmtCents, fmtPrice } from "@/lib/format";
