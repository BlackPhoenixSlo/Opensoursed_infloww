"use client";

/**
 * Infloww's own layer beside OF's chat (its "Messages Basic" widget): on /of-manager/messages/chat?chat=<fan>, the
 * Messages Pro Fan insights column (FanDrawer, pinned) with the Scripts picker (TemplatePicker) over it. A picked script,
 * or an unsold PPV's "Send to chat", goes on the mirror's Chat draft (applyScript), shown in OF's composer in the frame.
 * Lg and up only, as Messages Pro's pinned column (below it nothing mounts or reads); its × folds it to a "Fan insights" button.
 */

import { useState, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useScope } from "@/contexts/ScopeContext";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { FanDrawer } from "@/components/chat/FanDrawer";
import { TemplatePicker } from "@/components/chat/TemplatePicker";
import { applyScript, type PickedScript } from "@/lib/ofMirrorChat";
import { chatPath, mirrorQuery } from "@/lib/ofMirrorData";
import { fanIdFromParam } from "@/lib/fanId";
import type { OFChatItem } from "@/lib/relay";

/** The chat page itself (not its State pages, whose dialogs sit over the composer). */
export const CHAT_SRC = "/of-mirror/pages/messages/chat.html";

export function OfChatSidePanel({ frameRef, src }: { frameRef: RefObject<HTMLIFrameElement | null>; src: string }) {
  const { accountId } = useScope();
  const fan = useSearchParams().get("chat");
  // As the inbox keys its fan (a number where it fits): one Fan insights cache.
  const fanId = fanIdFromParam(fan);
  const desktop = useIsDesktop();
  const on = desktop && src === CHAT_SRC && !!accountId && fanId !== null;
  // The same read as the chat's (useOfChat): one request, one cache.
  const chat = useQuery(mirrorQuery<OFChatItem>(accountId, on ? chatPath(fan!) : null, on)).data;
  const [open, setOpen] = useState(true);
  if (!on || !chat) return null;
  const pick = (t: PickedScript) => applyScript(window.sessionStorage, accountId!, fan!, t, frameRef.current?.contentDocument ?? null);
  if (!open)
    return (
      <div className="flex shrink-0 border-l border-border p-2">
        <button type="button" className="text-xs text-fg-dim hover:text-fg" onClick={() => setOpen(true)} data-testid="of-chat-panel-open">
          Fan insights
        </button>
      </div>
    );
  return (
    <div className="flex w-70 shrink-0 flex-col min-h-0" data-testid="of-chat-panel">
      <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-l border-b border-border">
        <TemplatePicker accountId={accountId} onPick={pick} messagesPro />
      </div>
      <div className="flex-1 min-h-0 flex">
        <FanDrawer pinned open onClose={() => setOpen(false)} accountId={accountId!} fanId={fanId!} chat={chat} onComposeWith={pick} />
      </div>
    </div>
  );
}
