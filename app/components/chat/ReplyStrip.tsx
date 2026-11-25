import { Undo2 } from "lucide-react";

import type { OFMessage } from "@/lib/relay";
import { stripHtmlPreview } from "@/lib/htmlPreview";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

export interface QuotedReply {
  messageId: number | string;
  preview: string;
  authorName: string;
}

export function quoteFromMessage(msg: OFMessage): QuotedReply {
  const preview = stripHtmlPreview(msg.text || "(media)", 140);
  return {
    messageId: msg.id,
    preview,
    authorName: msg.fromUser?.name || msg.fromUser?.username || "fan",
  };
}

export function ReplyStrip({ quoted, onCancel }: { quoted: QuotedReply; onCancel: () => void }) {
  return (
    <div className={cn(MP.composer.replyStrip, "flex items-center bg-bg-elev-1 border-accent text-fg")}>
      <Undo2 aria-hidden className={cn(MP.composer.replyStripIcon, "flex-none text-[var(--inf-accent-text,var(--color-accent))]")} />
      <span className="min-w-0 flex-1 truncate">Replying to: {quoted.preview}</span>
      <button
        type="button"
        onClick={onCancel}
        className={cn(MP.composer.replyStripClose, "flex-none grid place-items-center text-fg-dim hover:bg-bg-elev-2 hover:text-fg")}
        aria-label="Cancel reply"
        title="Cancel reply"
      >
        ✕
      </button>
    </div>
  );
}
