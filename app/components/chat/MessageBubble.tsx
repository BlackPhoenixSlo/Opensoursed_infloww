"use client";


import { memo, useEffect, useMemo, useRef, useState } from "react";
import { User } from "lucide-react";

import type { OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { giphyUrl } from "@/lib/ofMedia";
import { useCompactMedia } from "@/hooks/useCompactMedia";
import { useTranslations, type BubbleTranslation } from "@/hooks/useTranslations";
import { useFanLanguage } from "@/lib/fanLanguage";
import { scriptDraftHasContent } from "@/lib/messageScripts";
import { BubbleStatusRow, BubbleTimeRow, timeRowShows } from "@/components/chat/BubbleMeta";
import { BubbleActions } from "@/components/chat/BubbleActions";
import { PPV_BORDER, PPV_FILL, PpvStatusLine } from "@/components/chat/PpvStatus";
import { MP } from "@/lib/messagesPro";
import { ofPlainText } from "@/lib/ofRichText";
import { MediaStrip } from "./MessageMedia";
import { QuoteCard, TranslatableText } from "./messageListParts";

export const Bubble = memo(function Bubble({
  msg, replyTo, isOutgoing, isOptimisticOutgoing, accountId, fanId, ownerUserId,
  onRetry, onDiscard, onCancelScheduled,
  onToggleLike, onQuoteReply, onTogglePin, onUnsend, onSaveAsScript, onJumpTo,
  highlighted, isRealOutgoing, seenByPeer,
  eagerMediaIds, employeeLabel, threadTranslate, threadTranslation, translateAllowed, runFirst, runLast, avatarUrl,
}: {
  msg: OFMessage;
  replyTo: OFMessage["replyToMessage"] | null;
  isOutgoing: boolean;
  isOptimisticOutgoing: boolean;
  accountId: string | null;
  fanId: FanId | null;
  ownerUserId: number | null;
  onRetry: (tempId: number) => void;
  onDiscard?: (tempId: number) => void;
  onCancelScheduled?: (tempId: number) => void;
  onToggleLike?: (msg: OFMessage) => void;
  onQuoteReply?: (msg: OFMessage) => void;
  onTogglePin?: (msg: OFMessage) => void;
  onUnsend?: (msg: OFMessage) => void;
  onSaveAsScript?: (msg: OFMessage) => void;
  onJumpTo?: (messageId: number | string) => void;
  highlighted?: boolean;
  isRealOutgoing?: boolean;
  seenByPeer?: boolean;
  eagerMediaIds: Set<string>;
  employeeLabel?: string | null;
  threadTranslate: boolean;
  threadTranslation?: BubbleTranslation | null;
  translateAllowed: boolean;
  runFirst: boolean;
  runLast: boolean;
  avatarUrl: string | null;
}) {
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  const [ownTranslate, setOwnTranslate] = useState<boolean | null>(null);
  const strippedText = msg.text ? ofPlainText(msg.text) : "";
  const own = translateAllowed ? ownTranslate : null;
  const ownTexts = useMemo(() => (own && strippedText ? [strippedText] : []), [own, strippedText]);
  const [fanLanguage] = useFanLanguage(accountId, fanId);
  const translationCache = useTranslations(ownTexts, own === true, accountId, fanLanguage, fanId);
  const translated = (own ?? threadTranslate) && !!strippedText;
  const entry = !translated ? undefined
    : own === true ? (translationCache.has(strippedText) ? translationCache.get(strippedText) ?? null : undefined)
    : threadTranslation;
  const translation = entry ?? null;
  const translateFailed = translated && entry === null;
  useEffect(() => {
    if (!highlighted) return;
    const id = setTimeout(() => {
      bubbleRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    return () => clearTimeout(id);
  }, [highlighted]);

  const [compactMedia] = useCompactMedia();
  const side = isOutgoing || isOptimisticOutgoing ? "right" : "left";
  const failed = !!msg._failed;
  const pending = !!msg._pending && !failed;
  const scheduled = !!msg._isFutureScheduled;
  // OF only lets you like the other party's messages.
  const canLike = !!onToggleLike && !isOutgoing && !isOptimisticOutgoing && !scheduled;
  const canReply = !!onQuoteReply && !scheduled && !failed && !pending;
  const numericIdForPin = typeof msg.id === "number" ? msg.id : Number(msg.id);
  const canPin = !!onTogglePin && !scheduled && !failed && !pending
    && Number.isFinite(numericIdForPin) && numericIdForPin > 0;
  // OF enforces the ~24h unsend window upstream; a 4xx is surfaced, not gated here.
  const canUnsend = !!onUnsend && (isOutgoing || isOptimisticOutgoing)
    && !scheduled && !failed && !pending
    && Number.isFinite(numericIdForPin) && numericIdForPin > 0;

  function onBubbleDoubleClick() {
    if (!canLike) return;
    onToggleLike!(msg);
  }

  const isPPV = !!msg.price && msg.price > 0;
  // Ledger is_paid lands minutes before OF's isOpened echoes back.
  const unlocked = isPPV && (!!msg.isOpened || !!msg.isPaid);
  const unpaid = isPPV && !unlocked;
  const ours = isOutgoing || isOptimisticOutgoing;
  const locked = unpaid && !ours;

  const timeRow = {
    side, createdAt: msg.createdAt, scheduled, employeeLabel,
    receipt: isRealOutgoing && !pending && !failed ? (seenByPeer ? "seen" : "delivered") : null,
  } as const;
  const timeRoom = runLast && timeRowShows(timeRow) ? MP.messageList.timeRoom : undefined;

  const actions = !pending && !failed && !scheduled && (
    <BubbleActions
      msg={msg} side={side}
      canPin={canPin} canReply={canReply} canLike={canLike} canUnsend={canUnsend}
      onTogglePin={onTogglePin} onQuoteReply={onQuoteReply} onToggleLike={onToggleLike}
      onUnsend={onUnsend}
      onSaveAsScript={ours && scriptDraftHasContent(msg) ? onSaveAsScript : undefined}
      details={ours ? { sentBy: employeeLabel ?? null, receipt: timeRow.receipt, unlocked } : undefined}
      translated={translated}
      onToggleTranslate={strippedText && translateAllowed ? () => setOwnTranslate(!translated) : undefined}
      translateState={translateFailed ? "failed" : "idle"}
      className={timeRoom}
    />
  );

  const avatarSide = side === "right" ? MP.messageList.avatarOut : MP.messageList.avatarIn;
  const avatar = runLast ? (
    <div
      data-msg-avatar={side === "right" ? "creator" : "fan"}
      className={cn(
        MP.messageList.avatar, avatarSide, "shrink-0 self-end grid place-items-center overflow-hidden",
        side === "right"
          ? "bg-[var(--inf-creator-avatar,var(--color-bg-elev-2))] text-white"
          : cn("bg-[var(--inf-fan-avatar,var(--color-bg-elev-1))]", timeRoom),
      )}
    >
      {avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={avatarUrl} alt="" loading="lazy" className="size-full object-cover" />
      ) : side === "right" ? (
        <User aria-hidden className={MP.messageList.avatarGlyph} />
      ) : null}
    </div>
  ) : (
    <div aria-hidden="true" className={cn(MP.messageList.avatar, avatarSide, "shrink-0")} />
  );

  return (
    <div
      ref={bubbleRef}
      className={cn(
        "flex group relative",
        side === "right" ? "justify-end" : "justify-start",
        !runFirst && MP.messageList.runGap,
        highlighted && cn(MP.ours.MessageList.highlight, "ring-2 ring-info/60 transition-shadow"),
      )}
    >
      {side === "left" && avatar}
      {side === "right" && actions}
      <div className={cn("flex flex-col relative min-w-0", MP.messageList.bubbleColumn, MP.ours.MessageList.column)}>
        <div
          onDoubleClick={onBubbleDoubleClick}
          data-msg-id={String(msg.id)}
          className={cn(
            "relative whitespace-pre-wrap break-words",
            isPPV
              ? cn("flex flex-col", PPV_BORDER, MP.messageList.ppv)
              : cn(MP.messageList.bubble, side === "right" ? MP.messageList.bubbleTailOut : MP.messageList.bubbleTailIn),
            side === "right"
              ? cn(isPPV ? PPV_FILL : "bg-accent", "text-white")
              : "bg-[var(--inf-bubble-in,var(--color-bg-elev-1))] text-fg",
            msg.isTip && cn("!bg-info/15 !text-info !border-info/40", MP.ours.MessageList.tipBorder),
            failed && "ring-1 ring-err/60",
            pending && !scheduled && "opacity-70",
            scheduled && side === "right" &&
              cn("!bg-accent/10 !text-accent border-dashed border-accent/50", MP.ours.MessageList.scheduledBorder),
            canLike && "cursor-default select-text",
          )}
        >
          {replyTo && (
            <QuoteCard
              replyTo={replyTo}
              side={side}
              ownerUserId={ownerUserId}
              onClick={() => onJumpTo?.(replyTo.id)}
            />
          )}
          {msg.text && (
            <span className="inline-flex flex-wrap items-baseline gap-1.5 align-baseline">
              {(isOutgoing || isOptimisticOutgoing) && isPPV && (
                <span
                  className={cn(
                    MP.ours.MessageList.textBadge, "text-white shadow self-center",
                    msg.lockedText ? "bg-err" : "bg-[var(--inf-offline,var(--color-fg-dim))]",
                  )}
                  title={msg.lockedText ? "Text locked — fan must pay to read" : "Text was sent unlocked"}
                >
                  {msg.lockedText ? "PAID" : "FREE"}
                </span>
              )}
              <TranslatableText raw={msg.text} translation={translation}
                                textClassName={isPPV ? MP.messageList.ppvTitle : undefined} />
            </span>
          )}
          {msg.media?.length ? <MediaStrip msg={msg} locked={locked} accountId={accountId} fanId={fanId} isOutgoing={ours} eagerMediaIds={eagerMediaIds} /> : null}
          {isPPV && <PpvStatusLine price={msg.price!} paid={unlocked} />}
          {/* Render what OF STORED (releaseForms), never what we asked for: userTags silently disagreed. */}
          {msg.releaseForms?.length ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {msg.releaseForms.map((rf) => (
                <span
                  key={rf.id}
                  className={cn(MP.ours.MessageList.releaseTag, "inline-flex items-center bg-black/15")}
                  title={`Tagged on OnlyFans — ${rf.name || rf.id} (release form)`}
                >
                  <span aria-hidden>🏷</span>
                  {rf.name || `#${rf.id}`}
                </span>
              ))}
            </div>
          ) : null}
          {msg.giphyId ? (
            <a
              href={giphyUrl(msg.giphyId)}
              target="_blank"
              rel="noreferrer"
              className={cn(
                "block overflow-hidden",
                MP.ours.MessageList.gif,
                compactMedia ? MP.ours.MessageList.gifWidthCompact : MP.ours.MessageList.gifWidth,
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={giphyUrl(msg.giphyId)}
                alt="GIF"
                loading="lazy"
                className="w-full h-auto object-cover"
              />
            </a>
          ) : null}
          {msg.isLiked && (
            <span
              className={cn(
                "absolute", MP.ours.MessageList.heart,
                side === "right" ? MP.ours.MessageList.stickerOut : MP.ours.MessageList.stickerIn,
              )}
              title="Liked"
              aria-label="Liked"
            >
              <span className="inline-grid place-items-center w-4 h-4 rounded-full bg-panel border border-border text-err">
                ♥
              </span>
            </span>
          )}
          {msg.isPinned && (
            <span
              className={cn(
                "absolute", MP.ours.MessageList.pinSticker,
                side === "right" ? MP.ours.MessageList.stickerOut : MP.ours.MessageList.stickerIn,
              )}
              title="Pinned to chat"
              aria-label="Pinned"
            >
              <span className="inline-grid place-items-center w-4 h-4 rounded-full bg-panel border border-border text-[var(--inf-accent-text,var(--color-accent))]">
                📌
              </span>
            </span>
          )}
        </div>
        {runLast && <BubbleTimeRow {...timeRow} />}
        <BubbleStatusRow msg={msg} side={side} scheduled={scheduled} pending={pending} failed={failed}
                         onRetry={onRetry} onDiscard={onDiscard} onCancelScheduled={onCancelScheduled} />
      </div>
      {side === "left" && actions}
      {side === "right" && avatar}
    </div>
  );
});
