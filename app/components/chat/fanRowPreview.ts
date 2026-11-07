import type { OFChatItem } from "@/lib/relay";
import { ofPreviewText } from "@/lib/ofRichText";
import { sameUserId } from "@/lib/fanId";

type LastMessage = NonNullable<OFChatItem["lastMessage"]>;

/** What each preview marker means, in plain words (the preview's `title`). */
export const PREVIEW_MARKER_LABEL = {
  "🔒": "🔒 paid message (PPV)",
  "💰": "💰 tip",
  "📎": "📎 free media",
} as const;
type Marker = keyof typeof PREVIEW_MARKER_LABEL;

/** A PPV is `isFree === false` or a price above 0. Not `lockedText`: OF sets
 *  it on plain free texts too (price 0, isFree true: "😍", tips, chatter
 *  texts), which put a 🔒 on "you: hellooo". `isFree === false` alone is
 *  enough because OF's /chats `lastMessage` carries no `price`, and no stored
 *  OF message has isFree false with price 0. */
export function isPaidMessage(lm: LastMessage): boolean {
  return lm.isFree === false || (lm.price ?? 0) > 0;
}

function marker(lm: LastMessage): Marker | null {
  if (lm.isTip) return "💰";
  if (isPaidMessage(lm)) return "🔒";
  if (!lm.text && lm.mediaCount) return "📎";
  return null;
}

/** Tag the preview with "you:" when the last message came from us — this
 *  is huge for triage: at a glance you see whether the fan replied or is
 *  still waiting on us. The model account's id is the row's __accountId
 *  (which == that account's own creator id). Same `sameUserId` compare the
 *  yellow dot uses: this line said "you: ghj" while the dot beside it said
 *  "awaiting your reply" on the very same Fansly row, because only one of
 *  the two normalized the id. Markers: 💰 tip, 🔒 PPV, 📎 N media (media-only). */
export function previewText(c: OFChatItem): string {
  const lm = c.lastMessage;
  if (!lm) return "";
  const prefix = sameUserId(lm.fromUser?.id, c.__accountId) ? "you: " : "";
  const m = marker(lm);
  const mk = m ? `${m} ` : "";
  if (lm.text) return prefix + mk + ofPreviewText(lm.text);
  if (lm.mediaCount) return `${prefix}${mk}${lm.mediaCount} media`;
  return (prefix + mk).trim();
}

/** The preview's hover text: names the marker it shows, undefined without
 *  one (so the row's own tooltip still shows over the preview). */
export function previewTitle(c: OFChatItem): string | undefined {
  const m = c.lastMessage ? marker(c.lastMessage) : null;
  return m ? PREVIEW_MARKER_LABEL[m] : undefined;
}
