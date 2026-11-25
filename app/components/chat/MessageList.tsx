"use client";


import { useLayoutEffect, useMemo, useRef, type ReactNode } from "react";

import { describeLoadError, isRateLimited, type OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { useEffectiveTranslateMode } from "@/hooks/useTranslateMode";
import { useTranslations, type BubbleTranslation } from "@/hooks/useTranslations";
import { useFanLanguage } from "@/lib/fanLanguage";
import { pickEagerMediaIds } from "@/components/chat/MediaTile";
import { automationLabel } from "@/components/messages/MessageRowGeneric";
import type { AttributionEntry } from "@/hooks/useChatAttribution";
import { withdrawnLines, type WithdrawnLine } from "@/lib/withdrawnLines";
import { MP } from "@/lib/messagesPro";
import { ofPlainText } from "@/lib/ofRichText";
import { Skeleton } from "@/components/ui/Skeleton";
import { Bubble } from "./MessageBubble";
import {
  dateDividerLabel, DateSeparator, localDateKey, messageRuns, resolveSide, type RunLabel,
} from "./messageListParts";
import { useThreadPin } from "./useThreadPin";

export { dateDividerLabel, messageRuns, type RunLabel } from "./messageListParts";
export { mediaTileBox } from "./MessageMedia";

// OF lastReadMessageId only grows, so the larger copy is fresher.
export function newestReadPointer(a?: number | null, b?: number | null): number | null {
  if (a == null) return b ?? null;
  if (b == null) return a;
  return Math.max(a, b);
}


const NO_EAGER: Set<string> = new Set();

type ReplyTo = NonNullable<OFMessage["replyToMessage"]>;
const replyCards = new WeakMap<OFMessage, ReplyTo>();
function replyCard(found: OFMessage): ReplyTo {
  let card = replyCards.get(found);
  if (!card) {
    card = {
      id: Number(found.id),
      text: found.text,
      fromUser: found.fromUser,
      createdAt: found.createdAt,
      mediaCount: found.mediaCount,
    };
    replyCards.set(found, card);
  }
  return card;
}

export interface MessageListProps {
  messages: OFMessage[];
  ownerUserId: number | null;
  accountId: string | null;
  fanId?: FanId | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  hasOlder: boolean;
  loadingOlder: boolean;
  olderFailed?: boolean;
  headSettled?: boolean;
  onLoadOlder: () => void;
  onRetry: (tempId: number) => void;
  onDiscard?: (tempId: number) => void;
  onCancelScheduled?: (jobId: number) => void;
  onToggleLike?: (msg: OFMessage) => void;
  onQuoteReply?: (msg: OFMessage) => void;
  onTogglePin?: (msg: OFMessage) => void;
  onUnsend?: (msg: OFMessage) => void;
  onSaveAsScript?: (msg: OFMessage) => void;
  highlightId?: number | string | null;
  lastReadByPeerId?: number | null;
  attribution?: Record<string, AttributionEntry> | null;
  fanAvatar?: string | null;
  creatorAvatar?: string | null;
  currentEmployeeName?: string | null;
}

export function MessageList(props: MessageListProps) {
  const {
    messages, ownerUserId, accountId, fanId, isLoading, isError, error,
    hasOlder, loadingOlder, olderFailed = false, headSettled = false, onLoadOlder, onDiscard, onCancelScheduled,
    onToggleLike, onQuoteReply, onTogglePin, onUnsend, onSaveAsScript,
    highlightId, lastReadByPeerId,
    attribution, currentEmployeeName, fanAvatar, creatorAvatar,
  } = props;

  const { on: translateOn, allowed: translateAllowed } = useEffectiveTranslateMode(accountId);
  const translatableTexts = useMemo(
    () => (translateOn ? messages.filter((m) => m.text).map((m) => ofPlainText(m.text)) : []),
    [messages, translateOn],
  );
  const [fanLanguage] = useFanLanguage(accountId, fanId ?? null);
  const translationCache = useTranslations(translatableTexts, translateOn, accountId, fanLanguage, fanId ?? null);

  const { containerRef, topSentinelRef, showJumpLatest, autoPinActive, jumpToLatest, jumpToMessage } =
    useThreadPin({ messages, hasOlder, loadingOlder, olderFailed, headSettled, onLoadOlder });

  const handlersRef = useRef(props);
  useLayoutEffect(() => { handlersRef.current = props; });
  const stable = useMemo(() => ({
    onRetry: (tempId: number) => handlersRef.current.onRetry(tempId),
    onDiscard: (tempId: number) => handlersRef.current.onDiscard?.(tempId),
    onCancelScheduled: (jobId: number) => handlersRef.current.onCancelScheduled?.(jobId),
    onToggleLike: (m: OFMessage) => handlersRef.current.onToggleLike?.(m),
    onQuoteReply: (m: OFMessage) => handlersRef.current.onQuoteReply?.(m),
    onTogglePin: (m: OFMessage) => handlersRef.current.onTogglePin?.(m),
    onUnsend: (m: OFMessage) => handlersRef.current.onUnsend?.(m),
    onSaveAsScript: (m: OFMessage) => handlersRef.current.onSaveAsScript?.(m),
  }), []);

  const eagerMediaIds = useMemo(
    () => pickEagerMediaIds(messages, ownerUserId),
    [messages, ownerUserId],
  );
  const eagerKey = [...eagerMediaIds].sort().join(",");
  const eagerSet = useMemo(() => new Set(eagerKey ? eagerKey.split(",") : []), [eagerKey]);
  const eagerFor = (m: OFMessage): Set<string> =>
    m.media?.some((x) => eagerSet.has(String(x.id))) ? eagerSet : NO_EAGER;

  // String keys: Fansly snowflake ids exceed 2^53, Number() would merge distinct ids and quote the wrong original.
  const byId = useMemo(() => {
    const m = new Map<string, OFMessage>();
    for (const msg of messages) {
      if (msg.id != null && String(msg.id) !== "") m.set(String(msg.id), msg);
    }
    return m;
  }, [messages]);

  if (isLoading && messages.length === 0) {
    return (
      <div role="status" aria-label="Loading messages" className="flex-1 min-h-0 flex flex-col justify-end gap-3 overflow-hidden p-4">
        {(["w-40", "w-56", "w-32", "w-48", "w-36"] as const).map((w, i) => (
          <Skeleton key={i} className={cn("h-9 rounded-2xl", w, i % 2 ? "self-end" : "self-start")} />
        ))}
      </div>
    );
  }
  // A failed refresh is fatal only with nothing cached; a deleted fan 404s every poll forever and blanking the thread loses the only copy.
  if (isError && messages.length === 0) {
    return (
      <div className="flex-1 min-h-0 grid place-items-center p-8 text-center text-sm text-err">
        {describeLoadError(error, "This fan's OnlyFans account no longer exists.")}
      </div>
    );
  }
  if (messages.length === 0) {
    return (
      <div className={cn("flex-1 min-h-0 grid place-items-center text-center text-fg-dim", MP.messageList.meta, MP.ours.MessageList.empty)}>
        No messages yet
      </div>
    );
  }

  const rows = messages.map((m) => {
    const isOutgoing = resolveSide(m, ownerUserId) === "right";
    const isOptimisticOutgoing = (m._tempId ?? 0) < 0;
    const numericId = typeof m.id === "number" ? m.id : Number(m.id);
    const isRealOutgoing = isOutgoing && Number.isFinite(numericId) && numericId > 0;
    // Optimistic and scheduled bubbles are not on OF yet: no seen tick.
    const seenByPeer =
      isRealOutgoing && lastReadByPeerId != null && numericId <= lastReadByPeerId;
    let employeeLabel: string | null = null;
    if (isOutgoing || isOptimisticOutgoing) {
      const entry = attribution?.[String(m.id)];
      const autoName = automationLabel(entry?.automation_kind);
      if (entry?.sender_name) {
        employeeLabel = entry.sender_name;
      } else if (autoName) {
        employeeLabel = autoName;
      } else if (entry?.display_name) {
        employeeLabel = entry.display_name;
      } else if (isOptimisticOutgoing && currentEmployeeName) {
        employeeLabel = currentEmployeeName;
      }
    }
    return { isOutgoing, isOptimisticOutgoing, isRealOutgoing, seenByPeer, employeeLabel };
  });
  const runs = messageRuns(messages, ownerUserId, rows.map((r) => ({
    sentBy: r.employeeLabel,
    receipt: r.isRealOutgoing ? (r.seenByPeer ? "seen" : "delivered") : null,
  } satisfies RunLabel)));
  const withdrawn = withdrawnLines(messages, attribution);
  const withdrawnLine = (w: WithdrawnLine) => (
    <div key={`withdrawn-${w.id}`} role="note" data-withdrawn-id={w.id}
         className={cn(MP.ours.MessageList.withdrawn, "text-center text-fg-dim italic")}>
      {w.auto ? "Message withdrawn automatically" : "Message withdrawn"}
    </div>
  );
  const withdrawnAt = (before: number, above: string | null | undefined) => {
    const nodes: ReactNode[] = [];
    for (const w of withdrawn.filter((x) => x.before === before)) {
      if (w.createdAt && (!above || localDateKey(above) !== localDateKey(w.createdAt))) {
        nodes.push(<DateSeparator key={`sep-w${w.id}`} label={dateDividerLabel(w.createdAt, now)} />);
      }
      if (w.createdAt) above = w.createdAt;
      nodes.push(withdrawnLine(w));
    }
    return { nodes, above };
  };
  const runFirst = new Set(runs.map((run) => run[0]));
  const runLast = new Set(runs.map((run) => run[run.length - 1]));
  const now = new Date();

  return (
    <div className="flex-1 min-h-0 min-w-0 relative">
      {autoPinActive && (
        <div className={cn(MP.ours.MessageList.autoPin, "pointer-events-none absolute z-10",
                           "bg-[var(--inf-chip,var(--color-bg-elev-2))] text-[var(--inf-chip-text,var(--color-fg))]")}>
          ↓ Jumping to latest…
        </div>
      )}
      {showJumpLatest && (
        <button
          type="button"
          onClick={jumpToLatest}
          className={cn(MP.ours.MessageList.latest, "absolute z-10 bg-accent text-[var(--inf-on-accent,var(--color-bg))] shadow-md hover:opacity-90")}
          title="Scroll to the latest message"
        >
          ↓ Latest
        </button>
      )}
    <div
      ref={containerRef}
      // Chrome scroll anchoring fights useThreadPin when media loads above the fold.
      style={{ overflowAnchor: "none" }}
      className={cn("h-full overflow-y-auto overflow-x-hidden overscroll-y-contain flex flex-col", MP.messageList.body)}
    >
      {isError && !isRateLimited(error) && (
        <div
          role="status"
          className={cn(MP.ours.MessageList.notice, "sticky z-20 bg-err/10 text-err",
                        "border-err/30 backdrop-blur-sm")}
        >
          {describeLoadError(error, "This fan's OnlyFans account no longer exists.")}{" "}
          <span className="text-fg-dim">Showing the last messages we saved.</span>
        </div>
      )}
      <div ref={topSentinelRef} className="h-1 shrink-0" />
      {hasOlder ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => { if (!loadingOlder) onLoadOlder(); }}
            disabled={loadingOlder}
            className={cn(
              MP.messageList.loadOlder, "border-border bg-bg-elev-1/40",
              "text-fg-dim hover:text-fg hover:bg-bg-elev-1 transition-colors",
              loadingOlder && "opacity-60 cursor-wait",
            )}
            title={olderFailed ? "Retry loading older messages" : "Load older messages"}
          >
            {loadingOlder ? "Loading older…" : olderFailed ? "Couldn’t load older messages · Retry" : "↑ Load older messages"}
          </button>
        </div>
      ) : messages.length > 0 ? (
        <div className={cn(MP.ours.MessageList.start, "text-center text-fg-dim italic")}>
          Start of conversation.
        </div>
      ) : null}
      {messages.flatMap((m, i, all) => {
        const { isOutgoing, isOptimisticOutgoing, isRealOutgoing, seenByPeer, employeeLabel } = rows[i];
        const lines = withdrawnAt(i, i > 0 ? all[i - 1].createdAt : null);
        const prevCreatedAt = lines.above;
        const showDateSep =
          !!m.createdAt && (
            !prevCreatedAt ||
            localDateKey(prevCreatedAt) !== localDateKey(m.createdAt)
          );
        let replyTo = m.replyToMessage ?? null;
        if (!replyTo && m.replyToMessageId) {
          const found = byId.get(String(m.replyToMessageId));
          if (found) replyTo = replyCard(found);
        }
        const threadTranslation: BubbleTranslation | null | undefined =
          translateOn && m.text ? translationCache.get(ofPlainText(m.text)) : undefined;
        const bubble = (
          <Bubble
            key={String(m.id)}
            msg={m}
            replyTo={replyTo}
            isOutgoing={isOutgoing}
            isOptimisticOutgoing={isOptimisticOutgoing}
            accountId={accountId}
            fanId={fanId ?? null}
            ownerUserId={ownerUserId}
            onRetry={stable.onRetry}
            onDiscard={onDiscard && stable.onDiscard}
            onCancelScheduled={onCancelScheduled && stable.onCancelScheduled}
            onToggleLike={onToggleLike && stable.onToggleLike}
            onQuoteReply={onQuoteReply && stable.onQuoteReply}
            onTogglePin={onTogglePin && stable.onTogglePin}
            onUnsend={onUnsend && stable.onUnsend}
            onSaveAsScript={onSaveAsScript && stable.onSaveAsScript}
            onJumpTo={jumpToMessage}
            highlighted={highlightId != null && String(highlightId) === String(m.id)}
            isRealOutgoing={isRealOutgoing}
            seenByPeer={seenByPeer}
            eagerMediaIds={eagerFor(m)}
            employeeLabel={employeeLabel}
            threadTranslate={translateOn}
            threadTranslation={threadTranslation}
            translateAllowed={translateAllowed}
            runFirst={runFirst.has(m)}
            runLast={runLast.has(m)}
            avatarUrl={(isOutgoing || isOptimisticOutgoing ? creatorAvatar : fanAvatar) ?? null}
          />
        );
        if (!showDateSep) return [...lines.nodes, bubble];
        return [
          ...lines.nodes,
          <DateSeparator
            key={`sep-${m.id}`}
            label={dateDividerLabel(m.createdAt!, now)}
          />,
          bubble,
        ];
      })}
      {withdrawnAt(messages.length, messages.at(-1)?.createdAt).nodes}
    </div>
    </div>
  );
}
