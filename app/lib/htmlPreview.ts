import { ofPreviewText } from "@/lib/ofRichText";

export function stripHtmlPreview(s: string, max: number): string {
  const plain = ofPreviewText(s);
  return plain.length > max ? plain.slice(0, max - 1) + "…" : plain;
}
