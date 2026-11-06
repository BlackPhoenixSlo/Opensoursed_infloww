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

import { ofPlainText, ofPreviewText } from "@/lib/ofRichText";

/** A one-line preview of an OF body (every tag dropped, entities decoded, whitespace collapsed): lib/ofRichText. */
export const stripHtml = ofPreviewText;

/** OF HTML body → plain text keeping its line breaks (<br> and </p> → "\n"), tags dropped, entities decoded,
 *  trimmed: lib/ofRichText's `ofPlainText`. */
export const htmlToText = ofPlainText;
