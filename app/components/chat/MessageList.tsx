"use client";

/**
 * MessageList — the message-history pane.
 *
 * Renders the OFMessage[] for one chat. Owns:
 *   • Scroll-only-if-at-bottom (snapshot the scroll position, stick to
 *     the bottom if the user was there OR initial load): useThreadPin,
 *     its decisions in threadPin.ts.
 *   • Load-older button at the top.
 *   • Per-message visual states: pending (faded), failed (red border +
 *     Retry button).
 *
 * Direction inference: `fromUser.id === ownerUserId` → outgoing (right-
 * aligned, accent bubble). Anything else → incoming (left-aligned).
 *
 * Empty/loading states pulled into the same component so the parent
 * doesn't have to switch. A bubble is MessageBubble.tsx, its media
 * MessageMedia.tsx, the small parts messageListParts.tsx.
 */

import { useMemo, type ReactNode } from "react";

import { describeLoadError, type OFMessage } from "@/lib/relay";
import { type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { useEffectiveTranslateMode } from "@/hooks/useTranslateMode";
import { useTranslations } from "@/hooks/useTranslations";
import { pickEagerMediaIds } from "@/components/chat/MediaTile";
import { automationLabel } from "@/components/messages/MessageRowGeneric";
import type { AttributionEntry } from "@/hooks/useChatAttribution";
import { withdrawnLines, type WithdrawnLine } from "@/lib/withdrawnLines";
import { MP } from "@/lib/messagesPro";
import { Skeleton } from "@/components/ui/Skeleton";
import { Bubble } from "./MessageBubble";
import {
  dateDividerLabel, DateSeparator, localDateKey, messageRuns, resolveSide, stripHtml, type RunLabel,
} from "./messageListParts";
import { useThreadPin } from "./useThreadPin";

// The public names that moved out (importers and tests reach them here).
export { dateDividerLabel, messageRuns, type RunLabel } from "./messageListParts";
export { mediaTileBox } from "./MessageMedia";

/** The Fan's read pointer from two copies (spec F28): the larger of the two,
 *  the one that is set, or null. OF's `lastReadMessageId` only grows, so the
 *  newer copy is the fresher one. */
export function newestReadPointer(a?: number | null, b?: number | null): number | null {
  if (a == null) return b ?? null;
  if (b == null) return a;
  return Math.max(a, b);
}


export interface MessageListProps {
  messages: OFMessage[];
  ownerUserId: number | null;  // the model account's OF user id
  accountId: string | null;    // for routing CDN urls through /img proxy
  /** Fan whose chat this is. Drives the per-tile BOUGHT/FREE/PAID badge
   *  overlay on sent message media (FanVaultHistory lookup is per-fan). */
  fanId?: FanId | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  onRetry: (tempId: number) => void;
  /** Drop a failed optimistic send (its "discard" control). */
  onDiscard?: (tempId: number) => void;
  /** Cancel a scheduled send by its server job id. Bubbles only render the
   *  cancel button when this is provided (and the row has a `_scheduleJobId`). */
  onCancelScheduled?: (jobId: number) => void;
  /** Double-click toggle for likes on incoming messages. Optional so
   *  read-only contexts (history search, etc.) can render the same list. */
  onToggleLike?: (msg: OFMessage) => void;
  /** Click "reply" on a bubble's hover toolbar. Parent stores the quoted
   *  context and renders it above the composer. */
  onQuoteReply?: (msg: OFMessage) => void;
  /** Click "📌 pin" / "📌 unpin" on a bubble's hover toolbar. Flips the
   *  pinned state on OF; parent owns the optimistic patch via the hook. */
  onTogglePin?: (msg: OFMessage) => void;
  /** Click "🗑 unsend" on a bubble's hover toolbar. Removes the message
   *  from this chat via OF's edit-window DELETE. Parent owns the
   *  optimistic-remove + "also unsend from everyone" follow-up prompt
   *  when the message turns out to be part of a mass send. Only shown
   *  on outbound bubbles — OF refuses unsend on incoming. */
  onUnsend?: (msg: OFMessage) => void;
  /** "Save as script" in our bubble's menu: the parent saves the message as
   *  a saved reply (roadmap W4 4.2). Absent, no menu item. */
  onSaveAsScript?: (msg: OFMessage) => void;
  /** Highlight a single message id (used by the search results panel
   *  click-to-jump). The bubble gets a transient ring + scrolls into view. */
  highlightId?: number | string | null;
  /** The OF chat's `lastReadMessageId` — the highest message id the fan
   *  has marked read. Drives the ✓✓ seen indicator on outgoing bubbles. */
  lastReadByPeerId?: number | null;
  /** Outbound-bubble employee attribution. Keyed by message_id (string).
   *  Null entries OR `display_name: null` mean "no label" (deleted
   *  employee or pre-DB-branch row) — the meta row guards on truthy
   *  display_name only. */
  attribution?: Record<string, AttributionEntry> | null;
  /** The Fan's avatar URL, on the last bubble of each of the Fan's runs; null
   *  or absent draws a plain circle (Phase 4 spec T5). */
  fanAvatar?: string | null;
  /** The Creator's avatar URL, on the last bubble of each of our runs; null
   *  or absent draws a person glyph (T6). */
  creatorAvatar?: string | null;
  /** Display name of the currently-picked employee. Used as the
   *  optimistic fallback for outbound bubbles that don't have a real
   *  message_id yet (tempId < 0) — the chatter sees their own name
   *  instantly without waiting for the attribution refetch. */
  currentEmployeeName?: string | null;
}

export function MessageList(props: MessageListProps) {
  const {
    messages, ownerUserId, accountId, fanId, isLoading, isError, error,
    hasOlder, loadingOlder, onLoadOlder, onRetry, onDiscard, onCancelScheduled,
    onToggleLike, onQuoteReply, onTogglePin, onUnsend, onSaveAsScript,
    highlightId, lastReadByPeerId,
    attribution, currentEmployeeName, fanAvatar, creatorAvatar,
  } = props;

  // 🌐 translate-to-English mode: batch-fetch translations for every loaded
  // text (keyed by stripped text, so optimistic-id churn is free); each Bubble
  // reads its entry from the same module cache, and the re-render this hook
  // makes when a batch lands repaints them. Off (default) costs nothing.
  // The effective mode holds the Agency's AI translation gate (spec phase-04).
  const { on: translateOn, allowed: translateAllowed } = useEffectiveTranslateMode(accountId);
  const translatableTexts = useMemo(
    () => (translateOn ? messages.filter((m) => m.text).map((m) => stripHtml(m.text)) : []),
    [messages, translateOn],
  );
  useTranslations(translatableTexts, translateOn, accountId);

  const { containerRef, topSentinelRef, showJumpLatest, autoPinActive, jumpToLatest, jumpToMessage } =
    useThreadPin({ messages, hasOlder, loadingOlder, onLoadOlder });

  // Eager-set: the two media tiles (most recent inbound + most recent
  // outbound) that fetch immediately on chat open. Everything else
  // lazy-loads via the per-tile IntersectionObserver. Recomputes only
  // when the messages array changes — the set is tiny so the downstream
  // .has() lookups in MediaStrip are O(1).
  const eagerMediaIds = useMemo(
    () => pickEagerMediaIds(messages, ownerUserId),
    [messages, ownerUserId],
  );

  // id → message lookup for resolving `replyToMessageId` in O(1). Built once
  // per messages change instead of an O(n) `all.find` inside the render
  // flatMap (which was O(n²) across the whole list).
  // STRING-keyed, not Number-keyed. A Fansly message id is a snowflake
  // (~9.5e17) well past JS's 2^53, so `Number(id)` collapses distinct ids onto
  // the same key and a quote-reply would resolve to the WRONG original. Same
  // class as the media-id fix (OFMedia.id widened to number|string, consumers
  // normalised to String()); OF ids are unaffected since String(n)===String(n).
  const byId = useMemo(() => {
    const m = new Map<string, OFMessage>();
    for (const msg of messages) {
      if (msg.id != null && String(msg.id) !== "") m.set(String(msg.id), msg);
    }
    return m;
  }, [messages]);

  // Empty / loading / error placeholders share the SAME flex sizing as
  // the populated branch below — without `flex-1 min-h-0` the column
  // collapses to the placeholder's natural height and the Composer
  // floats up into the middle of the pane until messages arrive.
  if (isLoading && messages.length === 0) {
    return (
      // The thread's bubbles as placeholder bars, theirs left and ours right, where the messages will be.
      <div role="status" aria-label="Loading messages" className="flex-1 min-h-0 flex flex-col justify-end gap-3 overflow-hidden p-4">
        {(["w-40", "w-56", "w-32", "w-48", "w-36"] as const).map((w, i) => (
          <Skeleton key={i} className={cn("h-9 rounded-2xl", w, i % 2 ? "self-end" : "self-start")} />
        ))}
      </div>
    );
  }
  // A refresh that fails is only fatal when there is NOTHING to show. If we
  // already hold cached history, the thread stays readable and the failure
  // becomes a strip at the top of it (below the AI status strip in the header)
  // — see `staleNotice` in the populated branch. A fan who deletes his OF
  // account 404s every poll forever; blanking the whole conversation on that
  // threw away the only remaining copy of it.
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

  // Each message's side, receipt and "Sent by" label, read once before the
  // render so the runs (whose last bubble holds the avatar) can group on them.
  const rows = messages.map((m) => {
    // Resolve the bubble side WITHOUT waiting on the async owner-id
    // fetch (the old `fromUser.id === ownerUserId` was null on first
    // paint → every bubble started left then jumped right). See
    // resolveSide: explicit `_side` (DB-seed rows from `direction`)
    // wins; live rows fall back to ownerUserId, which the parent now
    // hydrates synchronously from a per-account localStorage cache.
    const isOutgoing = resolveSide(m, ownerUserId) === "right";
    const isOptimisticOutgoing = (m._tempId ?? 0) < 0;
    // ✓✓ seen logic: only outgoing real-server messages with an id ≤ the
    // peer's lastRead pointer count as read. Optimistic ids (≤0) and
    // future-scheduled bubbles don't get a tick — they're not on OF yet.
    const numericId = typeof m.id === "number" ? m.id : Number(m.id);
    const isRealOutgoing = isOutgoing && Number.isFinite(numericId) && numericId > 0;
    const seenByPeer =
      isRealOutgoing && lastReadByPeerId != null && numericId <= lastReadByPeerId;
    // Outbound "Sent by {name}" label: prefer the server-side attribution
    // map (covers all chatters across the team); fall back to the picker's
    // current employee for optimistic bubbles whose real id isn't in the
    // map yet. Truthy display_name only — pre-DB-branch and deleted-
    // employee rows render nothing rather than "Sent by null".
    let employeeLabel: string | null = null;
    if (isOutgoing || isOptimisticOutgoing) {
      const entry = attribution?.[String(m.id)];
      // An automation send resolves display_name to the flat "Automation"
      // sentinel — prefer the specific automation name ("AI Chat",
      // "Auto-reply", …) so the bubble says which one actually sent it.
      const autoName = automationLabel(entry?.automation_kind);
      if (entry?.sender_name) {
        // Human mass broadcast: the backend denormalized "mass-kingsley1"
        // into sender_name (empty for 1:1 sends and automation-fired mass,
        // so this branch only fires for a human blast). Prefer it verbatim.
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
  // Withdrawn lines walk the days too: a line opens its own Date divider when
  // its day differs from the item above it, and the next message compares
  // against the line. Returns the nodes and the new "above" time.
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
      {/* Auto-pin indicator (briefly during the initial 5s window) +
       *  "↓ Latest" floating button (whenever the user is scrolled up).
       *  Both sit in an absolute layer over the scroll container so they
       *  don't shift the message column. Fix #11 — gives the user a
       *  visible cue that the view is heading to the latest message, and
       *  a manual escape if they get stranded mid-history. */}
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
      // overflow-anchor: none — Chrome's scroll-anchoring will fight our
      // manual pin when media loads above the fold ("bounce to middle"
      // bug, fix #11). We own scroll position via useThreadPin.
      style={{ overflowAnchor: "none" }}
      className={cn("h-full overflow-y-auto overflow-x-hidden overscroll-y-contain flex flex-col", MP.messageList.body)}
    >
      {/* The refresh failed but we still have history — say so WITHOUT taking
       *  the thread away. `sticky` (not `absolute`) so it never covers the
       *  first message and never shifts the column: it rides the top of the
       *  scroll viewport and scrolls with the content underneath it. */}
      {isError && (
        <div
          role="status"
          className={cn(MP.ours.MessageList.notice, "sticky z-20 bg-err/10 text-err",
                        "border-err/30 backdrop-blur-sm")}
        >
          {describeLoadError(error, "This fan's OnlyFans account no longer exists.")}{" "}
          <span className="text-fg-dim">Showing the last messages we saved.</span>
        </div>
      )}
      {/* Sentinel for IntersectionObserver auto-load + an explicit
       *  click-to-load button. Scroll-up alone isn't enough when the
       *  visible page is short (a chat with only a few recent messages
       *  doesn't produce a scrollbar, so the IO never fires); the button
       *  gives an unconditional way to pull older history. */}
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
            title="Load older messages"
          >
            {loadingOlder ? "Loading older…" : "↑ Load older messages"}
          </button>
        </div>
      ) : messages.length > 0 ? (
        <div className={cn(MP.ours.MessageList.start, "text-center text-fg-dim italic")}>
          Start of conversation.
        </div>
      ) : null}
      {messages.flatMap((m, i, all) => {
        const { isOutgoing, isOptimisticOutgoing, isRealOutgoing, seenByPeer, employeeLabel } = rows[i];
        // Day-boundary separator: a Date divider ("Today", "Sep 29") above the
        // first message of each new local day, walking top-down.
        const lines = withdrawnAt(i, i > 0 ? all[i - 1].createdAt : null);
        const prevCreatedAt = lines.above;
        const showDateSep =
          !!m.createdAt && (
            !prevCreatedAt ||
            localDateKey(prevCreatedAt) !== localDateKey(m.createdAt)
          );
        // Resolve the quoted message. OF sometimes only sends the id; fall
        // back to a cache walk in that case. Skipping the search when
        // `replyToMessage` is already populated keeps the common path cheap.
        let replyTo = m.replyToMessage ?? null;
        if (!replyTo && m.replyToMessageId) {
          const found = byId.get(String(m.replyToMessageId));
          if (found) {
            replyTo = {
              id: Number(found.id),
              text: found.text,
              fromUser: found.fromUser,
              createdAt: found.createdAt,
              mediaCount: found.mediaCount,
            };
          }
        }
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
            onRetry={onRetry}
            onDiscard={onDiscard}
            onCancelScheduled={onCancelScheduled}
            onToggleLike={onToggleLike}
            onQuoteReply={onQuoteReply}
            onTogglePin={onTogglePin}
            onUnsend={onUnsend}
            onSaveAsScript={onSaveAsScript}
            onJumpTo={jumpToMessage}
            highlighted={highlightId != null && String(highlightId) === String(m.id)}
            isRealOutgoing={isRealOutgoing}
            seenByPeer={seenByPeer}
            eagerMediaIds={eagerMediaIds}
            employeeLabel={employeeLabel}
            threadTranslate={translateOn}
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
