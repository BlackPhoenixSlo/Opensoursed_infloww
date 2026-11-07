"use client";

/**
 * One message's bubble in the Thread: its side, text, quote card, media,
 * PPV line, stickers, avatar, time and status rows and its action row.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { User } from "lucide-react";

import type { OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { giphyUrl } from "@/lib/ofMedia";
import { useCompactMedia } from "@/hooks/useCompactMedia";
import { useTranslations } from "@/hooks/useTranslations";
import { scriptDraftHasContent } from "@/lib/messageScripts";
import { BubbleStatusRow, BubbleTimeRow, timeRowShows } from "@/components/chat/BubbleMeta";
import { BubbleActions } from "@/components/chat/BubbleActions";
import { PpvStatusLine } from "@/components/chat/PpvStatus";
import { MP } from "@/lib/messagesPro";
import { MediaStrip } from "./MessageMedia";
import { QuoteCard, stripHtml, TranslatableText } from "./messageListParts";

export function Bubble({
  msg, replyTo, isOutgoing, isOptimisticOutgoing, accountId, fanId, ownerUserId,
  onRetry, onDiscard, onCancelScheduled,
  onToggleLike, onQuoteReply, onTogglePin, onUnsend, onSaveAsScript, onJumpTo,
  highlighted, isRealOutgoing, seenByPeer,
  eagerMediaIds, employeeLabel, threadTranslate, translateAllowed, runFirst, runLast, avatarUrl,
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
  /** The thread-wide translate mode is on. The bubble's own Translate toggle
   *  is OR-ed with it, and wins once pressed (Phase 4 spec F4). */
  threadTranslate: boolean;
  /** The Agency's AI translation switch allows this session to translate; off,
   *  the bubble's own Translate is not offered and sends nothing.
   *
   *  ASSUMPTION: the per-bubble Translate is hidden, not disabled, while the
   *  gate is off; story 56 names only the Composer's switch, which is disabled
   *  with its tooltip. Rung 5: the action row already omits Translate for a
   *  bubble with no text, so hiding needs no new disabled state. Overturned if
   *  the owner wants it shown disabled with "Turned off by your organization". */
  translateAllowed: boolean;
  /** The bubble starts its run; a later bubble of a run stacks 2px under the
   *  one before from md up (Part C, T11). */
  runFirst: boolean;
  /** The bubble ends its run, so its line holds the side's avatar and its
   *  column the run's time row; earlier bubbles of the run hold a spacer of
   *  the same width and no time row (spec F6, T12). */
  runLast: boolean;
  /** That side's avatar picture, or null for the fallback. */
  avatarUrl: string | null;
}) {
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  // Per-bubble translate (Phase 4 spec F4): null follows the thread-wide mode,
  // true or false is this bubble's own toggle. Its first press asks the same
  // module cache and relay call the thread mode uses, for this one text.
  const [ownTranslate, setOwnTranslate] = useState<boolean | null>(null);
  const strippedText = msg.text ? stripHtml(msg.text) : "";
  // The bubble's own toggle counts only while the gate allows translation;
  // `threadTranslate` arrives gated already.
  const own = translateAllowed ? ownTranslate : null;
  const ownTexts = useMemo(() => (own && strippedText ? [strippedText] : []), [own, strippedText]);
  const translationCache = useTranslations(ownTexts, own === true, accountId);
  const translated = (own ?? threadTranslate) && !!strippedText;
  const translation = translated ? translationCache.get(strippedText) ?? null : null;
  const translateFailed = translated && translationCache.has(strippedText) && translation === null;
  // Scroll into view when search picks this bubble. Defer to next tick so
  // the container's own scroll-restore effect doesn't fight us for the
  // scrollTop slot.
  useEffect(() => {
    if (!highlighted) return;
    const id = setTimeout(() => {
      bubbleRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    return () => clearTimeout(id);
  }, [highlighted]);

  const [compactMedia] = useCompactMedia();
  // Optimistic messages can't yet have a real fromUser.id matching
  // ownerUserId — treat tempId<0 as "I sent this".
  const side = isOutgoing || isOptimisticOutgoing ? "right" : "left";
  const failed = !!msg._failed;
  const pending = !!msg._pending && !failed;
  const scheduled = !!msg._isFutureScheduled;
  // OF only lets you like the OTHER party's messages. Hide the affordance
  // on outgoing bubbles even though `isLiked` may still appear there (if
  // the fan reacted to our message).
  const canLike = !!onToggleLike && !isOutgoing && !isOptimisticOutgoing && !scheduled;
  const canReply = !!onQuoteReply && !scheduled && !failed && !pending;
  // Pin works on both directions (unlike `like`, which is incoming-only).
  // Optimistic / failed / scheduled bubbles can't be pinned — they have
  // no real OF message id yet.
  const numericIdForPin = typeof msg.id === "number" ? msg.id : Number(msg.id);
  const canPin = !!onTogglePin && !scheduled && !failed && !pending
    && Number.isFinite(numericIdForPin) && numericIdForPin > 0;
  // Unsend: only on outbound bubbles with a real OF id. OF enforces the
  // ~24h edit window upstream — we surface a friendly error if the
  // request 4xxs rather than gating client-side, since the precise
  // window isn't echoed on the message payload.
  const canUnsend = !!onUnsend && (isOutgoing || isOptimisticOutgoing)
    && !scheduled && !failed && !pending
    && Number.isFinite(numericIdForPin) && numericIdForPin > 0;

  function onBubbleDoubleClick() {
    if (!canLike) return;
    onToggleLike!(msg);
  }

  // PPV: any positive price + isFree=false means this bubble was sold.
  // OF reports `isOpened=true` once the fan has paid. We render the
  // price tag + lock-state for both sides — outbound so the chatter
  // can see what they sent, inbound (rare; only on tip-back) for parity.
  const isPPV = !!msg.price && msg.price > 0;
  // Unlocked when EITHER OF reports it opened OR our ledger confirmed the
  // purchase (is_paid). The ledger stamp lands minutes before OF's isOpened
  // echoes back on a fresh fetch, so this makes a paid PPV unlock on the spot
  // instead of lingering "locked" on a cached bubble.
  const unlocked = isPPV && (!!msg.isOpened || !!msg.isPaid);
  // Outgoing PPV: we (the sender) own the content, so show thumbnails
  // even when the fan hasn't paid. Only incoming locked PPV shows the 🔒 tile.
  const unpaid = isPPV && !unlocked;
  const ours = isOutgoing || isOptimisticOutgoing;
  const locked = unpaid && !ours;

  // The run's time row (Part C, T12) under its last bubble. While it shows,
  // the Fan's avatar and the action row keep its room below them, so they
  // line up with the bubble, not the time row.
  const timeRow = {
    side, createdAt: msg.createdAt, scheduled, employeeLabel,
    receipt: isRealOutgoing && !pending && !failed ? (seenByPeer ? "seen" : "delivered") : null,
  } as const;
  const timeRoom = runLast && timeRowShows(timeRow) ? MP.messageList.timeRoom : undefined;

  // The Bubble action row (Phase 4 spec T1-T3): beside the bubble's column,
  // after it on the Fan's side and before it on ours. None while the message
  // is sending, failed or scheduled: OnlyFans does not have it yet.
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

  // The run's avatar (Phase 4 spec T5, T6): the Fan's at the left, ours at
  // the right, 36px, bottom-aligned with the bubble line. Without a picture
  // the Fan's is a plain circle and ours a person glyph on a grey circle.
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
            // Geometry: a PPV message is the Clone's `.ppv-mini` box (ML10),
            // with no tail; any other message is a bubble with its tail.
            isPPV
              ? cn("flex flex-col border-[var(--inf-ppv-border,var(--color-border))]", MP.messageList.ppv)
              : cn(MP.messageList.bubble, side === "right" ? MP.messageList.bubbleTailOut : MP.messageList.bubbleTailIn),
            side === "right"
              ? cn(isPPV ? "bg-[var(--inf-ppv,var(--color-accent))]" : "bg-accent", "text-white")
              : "bg-[var(--inf-bubble-in,var(--color-bg-elev-1))] text-fg",
            // Fan tip ("I sent you a $X.XX tip") — paint the bubble blue so
            // incoming money stands out at a glance, on either side.
            msg.isTip && cn("!bg-info/15 !text-info !border-info/40", MP.ours.MessageList.tipBorder),
            failed && "ring-1 ring-err/60",
            pending && !scheduled && "opacity-70",
            // Local-wait scheduled bubble: dashed outline + faded fill so
            // it's visually obvious this hasn't actually been sent yet.
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
              {/* Per-text FREE / PAID badge — only on outbound PPV bubbles.
               *  Free messages don't need a "FREE" tag (the bubble already
               *  has no PPV pill above it, so it'd be pure noise). */}
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
          {/* The card ends in its price and paid state, as the old Infloww
           *  overlay's `.ppv-mini .paid-tag` did; never the Fan's unlock bar. */}
          {isPPV && <PpvStatusLine price={msg.price!} paid={unlocked} />}
          {/* Who OF has on record as tagged in this send. Rendered from
           *  `releaseForms` — what OF STORED — and never from what we asked
           *  for, because those two disagreed silently for as long as the chat
           *  body shipped its ids in `userTags`. An operator who tags someone
           *  needs to see the tag land, not see their own click echoed back. */}
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
          {/* Heart sticker — anchored to the bubble's bottom-corner so the
           *  read state stays attached to the message it belongs to. */}
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
          {/* Pin sticker — top corner mirror of the heart. Tells the
           *  chatter at a glance which messages are pinned without
           *  having to open the pinned popover. */}
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
}
