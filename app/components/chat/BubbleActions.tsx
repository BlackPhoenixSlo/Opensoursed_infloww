"use client";


import { useCallback, useRef, useState } from "react";
import { EllipsisVertical, Heart, Languages, MessageCircle, Pin } from "lucide-react";

import type { OFMessage } from "@/lib/relay";
import type { RunLabel } from "./MessageList";
import { cn } from "@/lib/utils";
import { MP } from "@/lib/messagesPro";
import { MENU, MENU_ITEM, MENU_ROW } from "./MenuParts";
import { useMenuDismiss } from "./useMenuDismiss";
import { fmtPrice } from "@/lib/format";

const ACTION = cn(MP.messageList.action, "grid place-items-center shrink-0");
const GREY = "text-[var(--inf-action,var(--color-fg-dim))] hover:text-fg";
const PRESSED = "text-[var(--inf-accent-text,var(--color-accent))]";
const ICON = MP.messageList.actionIcon;

export type TranslateState = "idle" | "failed";

export interface MessageDetailsInfo {
  sentBy: string | null;
  receipt: RunLabel["receipt"];
  unlocked: boolean;
}

export function fmtSent(iso?: string): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "—";
}

export function BubbleActions({
  msg, side, canPin, canReply, canLike, canUnsend,
  onTogglePin, onQuoteReply, onToggleLike, onUnsend, onSaveAsScript, details,
  translated, onToggleTranslate, translateState, className,
}: {
  msg: OFMessage;
  side: "left" | "right";
  canPin: boolean;
  canReply: boolean;
  canLike: boolean;
  canUnsend: boolean;
  onTogglePin?: (msg: OFMessage) => void;
  onQuoteReply?: (msg: OFMessage) => void;
  onToggleLike?: (msg: OFMessage) => void;
  onUnsend?: (msg: OFMessage) => void;
  onSaveAsScript?: (msg: OFMessage) => void;
  details?: MessageDetailsInfo;
  translated: boolean;
  onToggleTranslate?: () => void;
  translateState: TranslateState;
  className?: string;
}) {
  const [panel, setPanel] = useState<"menu" | "details" | null>(null);
  const menuOpen = panel === "menu";
  const menuRef = useRef<HTMLDivElement | null>(null);
  const closeMenu = useCallback(() => setPanel(null), []);
  useMenuDismiss(menuRef, panel !== null, closeMenu);

  const incoming = side === "left";
  const hasMenu = !incoming && (canReply || canPin || canUnsend || !!onSaveAsScript || !!details);
  const any = onToggleTranslate || (incoming ? canPin || canReply || canLike : hasMenu);
  if (!any) return null;

  const pin = (
    <button
      type="button"
      onClick={() => onTogglePin!(msg)}
      className={cn(ACTION, msg.isPinned ? PRESSED : GREY)}
      aria-label={msg.isPinned ? "Unpin" : "Pin"}
      aria-pressed={!!msg.isPinned}
      title={msg.isPinned ? "Unpin from chat" : "Pin to chat"}
    >
      <Pin aria-hidden className={ICON} />
    </button>
  );
  const translate = onToggleTranslate && (
    <button
      type="button"
      onClick={onToggleTranslate}
      className={cn(ACTION, translated ? PRESSED : GREY)}
      aria-label={translated ? "Show original" : "Translate"}
      aria-pressed={translated}
      title={translated && translateState === "failed" ? "No translation available"
        : translated ? "Show original" : "Translate to English"}
    >
      <Languages aria-hidden className={ICON} />
    </button>
  );

  function pick(action: (m: OFMessage) => void) {
    setPanel(null);
    action(msg);
  }

  return (
    <div
      role="group"
      aria-label="Message actions"
      className={cn(
        "flex items-center self-center shrink-0",
        incoming ? MP.messageList.actionsIn : MP.messageList.actionsOut, className,
        panel ? "md:opacity-100" : "md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100",
      )}
    >
      {incoming ? (
        <>
          {canPin && pin}
          {canReply && (
            <button
              type="button"
              onClick={() => onQuoteReply!(msg)}
              className={cn(ACTION, GREY)}
              aria-label="Reply"
              title="Quote-reply"
            >
              <MessageCircle aria-hidden className={ICON} />
            </button>
          )}
          {canLike && (
            <button
              type="button"
              onClick={() => onToggleLike!(msg)}
              className={cn(ACTION, msg.isLiked ? "text-[var(--inf-liked,var(--color-err))]" : GREY)}
              aria-label={msg.isLiked ? "Unlike" : "Like"}
              aria-pressed={!!msg.isLiked}
              title={msg.isLiked ? "Unlike" : "Like (or double-click bubble)"}
            >
              <Heart aria-hidden className={cn(ICON, msg.isLiked && "fill-current")} />
            </button>
          )}
          {translate}
        </>
      ) : (
        <>
          {translate}
          {hasMenu && (
            <div ref={menuRef}>
              <button
                type="button"
                onClick={() => setPanel((v) => (v ? null : "menu"))}
                className={cn(ACTION, panel ? "text-fg" : GREY)}
                aria-label="More message actions"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                title="More message actions"
              >
                <EllipsisVertical aria-hidden className={ICON} />
              </button>
              {menuOpen && (
                <div role="menu" className={cn(MENU, MP.ours.BubbleActions.menu)}>
                  {canReply && (
                    <button type="button" role="menuitem" className={MENU_ITEM} title="Quote-reply"
                            onClick={() => pick(onQuoteReply!)}>
                      Reply
                    </button>
                  )}
                  {canPin && (
                    <button type="button" role="menuitem" className={MENU_ITEM}
                            title={msg.isPinned ? "Unpin from chat" : "Pin to chat"}
                            onClick={() => pick(onTogglePin!)}>
                      {msg.isPinned ? "Unpin" : "Pin"}
                    </button>
                  )}
                  {onSaveAsScript && (
                    <button type="button" role="menuitem" className={MENU_ITEM}
                            title="Save this message (text, media and price) to Scripts"
                            onClick={() => pick(onSaveAsScript)}>
                      Save as script
                    </button>
                  )}
                  {details && (
                    <button type="button" role="menuitem" className={MENU_ITEM}
                            title="When it was sent, by whom, and whether it was seen"
                            onClick={() => setPanel("details")}>
                      Details
                    </button>
                  )}
                  {canUnsend && (
                    <button type="button" role="menuitem" className={cn(MENU_ROW, "text-err hover:bg-err/10")}
                            title="Unsend (within OF's 24h window)"
                            onClick={() => pick(onUnsend!)}>
                      Unsend
                    </button>
                  )}
                </div>
              )}
              {panel === "details" && details && (
                <div role="dialog" aria-label="Message details" className={cn(MENU, MP.ours.BubbleActions.menu)}>
                  <dl>
                    {([
                      ["Sent", fmtSent(msg.createdAt)],
                      ["Sent by", details.sentBy ?? "—"],
                      ["Seen", details.receipt === "seen" ? "Seen" : details.receipt ? "Not yet" : "—"],
                      ["Price", msg.price && msg.price > 0
                        ? `${fmtPrice(Math.round(msg.price * 100))} · ${details.unlocked ? "unlocked" : "not unlocked"}`
                        : "Free"],
                    ] as const).map(([label, value]) => (
                      <div key={label} className={cn(MP.ours.BubbleActions.detailsRow, "flex justify-between")}>
                        <dt className="text-fg-dim">{label}</dt>
                        <dd className="text-fg text-right">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
