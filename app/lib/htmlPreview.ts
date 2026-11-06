import { ofPreviewText } from "@/lib/ofRichText";

/** Plain-text preview from OF's HTML body — used for both quote previews
 *  and search match snippets. Cheap and intentionally lossy: anything
 *  beyond `max` is truncated with an ellipsis. */
export function stripHtmlPreview(s: string, max: number): string {
  const plain = ofPreviewText(s);
  return plain.length > max ? plain.slice(0, max - 1) + "…" : plain;
}
