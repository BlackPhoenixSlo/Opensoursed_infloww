import type { OFChatItem } from "@/lib/relay";
import { ofPreviewText } from "@/lib/ofRichText";
import { sameUserId } from "@/lib/fanId";

type LastMessage = NonNullable<OFChatItem["lastMessage"]>;

export const PREVIEW_MARKER_LABEL = {
  "🔒": "🔒 paid message (PPV)",
  "💰": "💰 tip",
  "📎": "📎 free media",
} as const;
type Marker = keyof typeof PREVIEW_MARKER_LABEL;

// Not lockedText: OF sets it on free texts too; /chats lastMessage has no price, so isFree === false is the PPV signal.
export function isPaidMessage(lm: LastMessage): boolean {
  return lm.isFree === false || (lm.price ?? 0) > 0;
}

function marker(lm: LastMessage): Marker | null {
  if (lm.isTip) return "💰";
  if (isPaidMessage(lm)) return "🔒";
  if (!lm.text && lm.mediaCount) return "📎";
  return null;
}

export function previewText(c: OFChatItem): string {
  const lm = c.lastMessage;
  if (!lm) return "";
  // Same sameUserId compare as the awaiting-reply dot, or the two disagree on Fansly rows.
  const prefix = sameUserId(lm.fromUser?.id, c.__accountId) ? "you: " : "";
  const m = marker(lm);
  const mk = m ? `${m} ` : "";
  if (lm.text) return prefix + mk + ofPreviewText(lm.text);
  if (lm.mediaCount) return `${prefix}${mk}${lm.mediaCount} media`;
  return (prefix + mk).trim();
}

export function fanRowPreview(
  c: OFChatItem, s: { typing: boolean; draft: string; selected: boolean },
): { text: string; title?: string; typing?: true } {
  if (s.typing) return { text: "is typing…", typing: true };
  if (s.draft && !s.selected) return { text: `[Draft] ${s.draft}` };
  const m = c.lastMessage ? marker(c.lastMessage) : null;
  return { text: previewText(c), title: m ? PREVIEW_MARKER_LABEL[m] : undefined };
}
