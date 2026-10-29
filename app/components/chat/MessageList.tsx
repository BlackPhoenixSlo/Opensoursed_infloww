"use client";

/**
 * MessageList — the message-history pane.
 *
 * Renders the OFMessage[] for one chat. Owns:
 *   • Scroll-only-if-at-bottom (snapshot scroll position before merge,
 *     restore if user was at the bottom OR initial load).
 *   • Load-older button at the top.
 *   • Per-message visual states: pending (faded), failed (red border +
 *     Retry button).
 *
 * Direction inference: `fromUser.id === ownerUserId` → outgoing (right-
 * aligned, accent bubble). Anything else → incoming (left-aligned).
 *
 * Empty/loading states pulled into the same component so the parent
 * doesn't have to switch.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { User } from "lucide-react";

import { describeLoadError, type OFMedia, type OFMessage } from "@/lib/relay";
import { proxyImage } from "@/lib/mediaUrl";
import { type FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { giphyUrl, stillUrl } from "@/lib/ofMedia";
import { blurImageClass, useBlurMode } from "@/hooks/useBlurMode";
import { useCompactMedia } from "@/hooks/useCompactMedia";
import { useEffectiveTranslateMode } from "@/hooks/useTranslateMode";
import { useTranslations, type BubbleTranslation } from "@/hooks/useTranslations";
import { useFanVaultHistory } from "@/hooks/useFanVaultHistory";
import { MediaTile, pickEagerMediaIds } from "@/components/chat/MediaTile";
import { clipUrl, isVideoMedia, mediaCountLabel, VideoTileMarks, ViewerVideo } from "@/components/chat/MediaVideo";
import { automationLabel } from "@/components/messages/MessageRowGeneric";
import type { AttributionEntry } from "@/hooks/useChatAttribution";
import { withdrawnLines, type WithdrawnLine } from "@/lib/withdrawnLines";
import { scriptDraftHasContent } from "@/lib/messageScripts";
import { BubbleStatusRow, BubbleTimeRow, timeRowShows } from "@/components/chat/BubbleMeta";
import { BubbleActions } from "@/components/chat/BubbleActions";
import { useInflowwPalette } from "@/components/chat/InflowwPalette";
import { PpvStatusLine, ppvPriceLabel } from "@/components/chat/PpvStatus";
import { MP } from "@/lib/messagesPro";
import { Skeleton } from "@/components/ui/Skeleton";

/** The Fan's read pointer from two copies (spec F28): the larger of the two,
 *  the one that is set, or null. OF's `lastReadMessageId` only grows, so the
 *  newer copy is the fresher one. */
export function newestReadPointer(a?: number | null, b?: number | null): number | null {
  if (a == null) return b ?? null;
  if (b == null) return a;
  return Math.max(a, b);
}

/** A Date divider's label (Phase 4 spec T4, F5): "Today" on `now`'s local
 *  day, the short month and day ("Sep 29") on another day of `now`'s year,
 *  yesterday included, and the year added in another year ("Sep 29, 2025"),
 *  in the browser locale. */
export function dateDividerLabel(iso: string, now: Date): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (localDateKey(iso) === localDateKey(now.toISOString())) return "Today";
  return d.toLocaleDateString(undefined, d.getFullYear() === now.getFullYear()
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" });
}

/** What a bubble's time row shows besides the time: its "Sent by" label and,
 *  on our side, its receipt. */
export interface RunLabel {
  sentBy: string | null;
  receipt: "delivered" | "seen" | null;
}

/** A Thread's runs (Phase 4 spec, Interfaces): consecutive messages on one
 *  side, on one local day and in one displayed minute, with the same "Sent by"
 *  label and, on our side, the same receipt. A pending, failed or
 *  future-scheduled message is a run of its own. `labels[i]` is
 *  `messages[i]`'s. A run's avatar sits on its last bubble. */
export function messageRuns(messages: OFMessage[], ownerUserId: number | null, labels: RunLabel[]): OFMessage[][] {
  const runs: OFMessage[][] = [];
  let prev: string | null = null;
  messages.forEach((m, i) => {
    const key = m._pending || m._failed || m._isFutureScheduled ? null : runKey(m, ownerUserId, labels[i]);
    if (key !== null && key === prev) runs[runs.length - 1].push(m);
    else runs.push([m]);
    prev = key;
  });
  return runs;
}

function runKey(m: OFMessage, ownerUserId: number | null, label: RunLabel): string {
  const side = (m._tempId ?? 0) < 0 ? "right" : resolveSide(m, ownerUserId);
  const d = new Date(m.createdAt ?? "");
  const minute = Number.isNaN(d.getTime()) ? "" : `${localDateKey(m.createdAt!)}-${d.getHours()}-${d.getMinutes()}`;
  return JSON.stringify([side, minute, label.sentBy, side === "right" ? label.receipt : null]);
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

const AT_BOTTOM_PX = 80;

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

  const containerRef = useRef<HTMLDivElement | null>(null);
  const topSentinelRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);
  const lastLenRef = useRef(0);
  // True until the first non-empty message render has been pinned to the
  // bottom. Without this, the IntersectionObserver below fires the
  // moment the top sentinel becomes visible during the initial render
  // (when scrollTop is still 0), which yanks the view back to old
  // messages instead of letting the user see the newest ones.
  const firstLoadPendingRef = useRef(true);
  // "↓ Latest" affordance: shown when the user is scrolled up and there's
  // visible history above the fold. Doubles as the visual cue that the
  // initial auto-pin window is active (small label flips while pending).
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const [autoPinActive, setAutoPinActive] = useState(true);
  // Snapshot pre-render scrollHeight + scrollTop so a load-older insert
  // (which pushes content down) can keep the user's eye anchored on the
  // same message instead of jumping back to the bottom.
  const preMergeScrollRef = useRef<{ height: number; top: number } | null>(null);
  // Set true immediately before every programmatic `scrollTop = scrollHeight`
  // write (the 60Hz pin poll + the media-load RAF repin). The `scroll` event
  // those writes emit is indistinguishable from a user scroll, so the scroll
  // release handler consumes this flag to ignore our own writes — letting
  // genuine user scrolls (scrollbar-thumb drag, gutter click, momentum fling)
  // release the auto-pin even though they emit no wheel/touchmove/keydown.
  const programmaticScrollRef = useRef(false);

  // Capture scroll position BEFORE the next render commit.
  useLayoutEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    wasAtBottomRef.current =
      c.scrollHeight - c.scrollTop - c.clientHeight < AT_BOTTOM_PX;
    preMergeScrollRef.current = { height: c.scrollHeight, top: c.scrollTop };
  });

  // After render: decide between "stick to bottom" (initial / new message)
  // and "preserve anchor" (older page loaded at top).
  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const initial = lastLenRef.current === 0 && messages.length > 0;
    const grew = messages.length > lastLenRef.current && !initial;
    if (initial) {
      // Initial paint: hard-pin to the bottom now + next frame. A separate
      // ResizeObserver effect (below) keeps re-pinning while
      // firstLoadPendingRef stays true, so late-loading media that grow
      // the container after this point still land us at the bottom.
      const pinBottom = () => { c.scrollTop = c.scrollHeight; };
      pinBottom();
      requestAnimationFrame(pinBottom);
      // Hard backstop: release the auto-pin after 5s regardless of user
      // interaction, so a chat with media that never settles can't keep
      // yanking the view forever. 5s (was 2s) covers the common case of
      // 4-5 image thumbs loading sequentially on a cold tab — fix #11.
      const t = setTimeout(() => {
        firstLoadPendingRef.current = false;
        setAutoPinActive(false);
      }, 5000);
      lastLenRef.current = messages.length;
      return () => clearTimeout(t);
    }
    if (wasAtBottomRef.current) {
      c.scrollTop = c.scrollHeight;
    } else if (grew && preMergeScrollRef.current) {
      // Older page came in at the top — adjust scrollTop by the height
      // delta so the previously-visible message stays in view.
      const delta = c.scrollHeight - preMergeScrollRef.current.height;
      if (delta > 0) c.scrollTop = preMergeScrollRef.current.top + delta;
    }
    lastLenRef.current = messages.length;
  }, [messages]);

  // Late-arriving media (large images, video posters) grow the *content*
  // after the initial pin. A ResizeObserver on the container itself
  // doesn't fire (the container's borderBox stays constant — flex-1
  // inside a fixed-height column; only `scrollHeight` grows).
  //
  // Two-track re-pin for the first 5s of pendingRef:
  //   1. Per-frame poll (60Hz). Cheap, idempotent (scrollTop = scrollHeight
  //      is a no-op when already at bottom). Catches every layout shift
  //      including ones the load listener might race past — browser
  //      scroll anchoring, font swap, late-arriving DOM, mediastrip
  //      relayout. This was the bug behind fix #11's "bounce to middle".
  //   2. Capture-phase `load` listener on the container. <img>/<video>
  //      `load` doesn't bubble; capture phase lets us catch them all.
  //      Triggers an extra RAF pin so the visual snap happens the same
  //      frame the image paints, not at the next 16ms tick.
  const hasMessages = messages.length > 0;
  useEffect(() => {
    if (!hasMessages) return;
    const c = containerRef.current;
    if (!c) return;
    let rafId: number | null = null;
    const repin = () => {
      if (!firstLoadPendingRef.current) return;
      if (rafId != null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        if (firstLoadPendingRef.current) {
          programmaticScrollRef.current = true;
          c.scrollTop = c.scrollHeight;
        }
      });
    };
    // Image/video load events don't bubble — use capture-phase listener.
    const onMediaLoad = (e: Event) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.tagName === "IMG" || t.tagName === "VIDEO") repin();
    };
    c.addEventListener("load", onMediaLoad, true);
    // 60Hz poll for the first 5s. Stops as soon as pendingRef flips false.
    const pollId = window.setInterval(() => {
      if (!firstLoadPendingRef.current) {
        window.clearInterval(pollId);
        return;
      }
      programmaticScrollRef.current = true;
      c.scrollTop = c.scrollHeight;
    }, 16);
    // `wheel` / `touchmove` / `keydown` are user-only signals that release
    // the auto-pin immediately. They don't cover scrollbar-thumb drag,
    // scrollbar-gutter clicks or momentum/inertial flings the browser
    // dispatches only as `scroll` — those are handled by the guarded scroll
    // path in onScroll below (which distinguishes our own pin writes from a
    // real user scroll via programmaticScrollRef).
    const release = (e: Event) => {
      if (!e.isTrusted) return;
      firstLoadPendingRef.current = false;
      setAutoPinActive(false);
    };
    // A finger releases only once it moves more up/down than sideways: a
    // sideways swipe (the Thread's swipe back, kept or cancelled) is not a scroll.
    let touch0: { x: number; y: number } | null = null;
    const onTouchStart = (e: TouchEvent) => {
      const t = e.touches[0];
      touch0 = t ? { x: t.clientX, y: t.clientY } : null;
    };
    const onTouchMove = (e: TouchEvent) => {
      const t = e.touches[0];
      if (touch0 && t && Math.abs(t.clientY - touch0.y) <= Math.abs(t.clientX - touch0.x)) return;
      release(e);
    };
    c.addEventListener("wheel", release, { passive: true });
    c.addEventListener("touchstart", onTouchStart, { passive: true });
    c.addEventListener("touchmove", onTouchMove, { passive: true });
    c.addEventListener("keydown", release);
    // "↓ Latest" affordance: passive scroll listener tracks distance from
    // bottom so we can surface the jump button when the user scrolls up.
    // Toggling via state is fine — the button only re-renders, not the
    // bubble list.
    //
    // Also doubles as a release signal for scroll-only gestures (scrollbar
    // drag/gutter, momentum). Our own pin writes emit `scroll` too, but they
    // set programmaticScrollRef just before the write — so we consume that
    // flag and ignore them. A scroll that wasn't ours AND lands the user more
    // than AT_BOTTOM_PX from the bottom is genuine intent → release the pin.
    const onScroll = () => {
      const distance = c.scrollHeight - c.scrollTop - c.clientHeight;
      setShowJumpLatest(distance > AT_BOTTOM_PX * 4);
      if (programmaticScrollRef.current) {
        programmaticScrollRef.current = false;
        return;
      }
      if (firstLoadPendingRef.current && distance > AT_BOTTOM_PX) {
        firstLoadPendingRef.current = false;
        setAutoPinActive(false);
      }
    };
    c.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.clearInterval(pollId);
      if (rafId != null) cancelAnimationFrame(rafId);
      c.removeEventListener("load", onMediaLoad, true);
      c.removeEventListener("wheel", release);
      c.removeEventListener("touchstart", onTouchStart);
      c.removeEventListener("touchmove", onTouchMove);
      c.removeEventListener("keydown", release);
      c.removeEventListener("scroll", onScroll);
    };
  }, [hasMessages]);

  // Auto-load older when the top sentinel scrolls into view. Same pattern
  // as ChatList's infinite scroll, just inverted (top instead of bottom).
  //
  // Crucially we ignore intersections while `firstLoadPendingRef` is true
  // — on initial render the container is empty so the sentinel is
  // trivially visible, and without this gate the very first paint would
  // immediately fire loadOlder and yank the user away from the newest
  // messages before they could see them.
  useEffect(() => {
    const el = topSentinelRef.current;
    if (!el || !hasOlder) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (firstLoadPendingRef.current) return;
        if (entries.some((e) => e.isIntersecting) && hasOlder && !loadingOlder) {
          onLoadOlder();
        }
      },
      { root: containerRef.current, rootMargin: "200px 0px 0px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasOlder, loadingOlder, onLoadOlder]);

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
          onClick={() => {
            const c = containerRef.current;
            if (!c) return;
            c.scrollTo({ top: c.scrollHeight, behavior: "smooth" });
          }}
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
      // bug, fix #11). We own scroll position via the effects above.
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
            onJumpTo={(id) => {
              // Tapping the quote card scrolls to the original. Same logic
              // as search-result click: set highlightId via the existing
              // jump path — but since Bubble lives inside MessageList, we
              // simulate it by dispatching a click via DOM scrollIntoView.
              const el = containerRef.current?.querySelector(
                `[data-msg-id="${CSS.escape(String(id))}"]`,
              ) as HTMLElement | null;
              el?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
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

function Bubble({
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

function MediaStrip({ msg, locked, accountId, fanId, isOutgoing, eagerMediaIds }: {
  msg: OFMessage;
  locked: boolean;
  accountId: string | null;
  fanId: FanId | null;
  isOutgoing: boolean;
  eagerMediaIds: Set<string>;
}) {
  const items = msg.media ?? [];
  const [blurMode] = useBlurMode();
  const [compactMedia] = useCompactMedia();
  const blurCls = blurImageClass(blurMode);
  // Per-fan vault history → drives the green BOUGHT badge on outbound
  // PPV tiles. Only the outbound side queries — inbound media is the
  // fan's tip-back and our purchase signal doesn't apply.
  const fanVaultQ = useFanVaultHistory(accountId, fanId, isOutgoing && fanId != null);
  const isPPV = !!msg.price && msg.price > 0;
  const previewIds = msg.previews ?? [];
  // Attachments OF itself refused on a failed send; empty on every other
  // message. Same shape and same membership test as `previewIds` above — both
  // are "which of these tiles is special", and a bundle is small enough that a
  // Set would be ceremony.
  const refusedIds = msg._failedMediaIds ?? [];
  // Price label fits in the same 5-char corner pill as "BOUGHT" / "FREE".
  const priceLabel = msg.price != null ? ppvPriceLabel(msg.price) : "";
  // PPV gifts can attach 40+ items; rendering them all blows up the bubble
  // and floods the relay /img proxy. Cap at:
  //   • 2 tiles when the message is still locked (the lock icon repeats —
  //     beyond 2 it's pure noise)
  //   • 3 tiles for visible thumbnails (a clean 3-up row in the bubble)
  // The user expands to see the rest via the "+N more" pill.
  const LOCKED_CAP = 2;
  const IMAGE_CAP = 3;
  const cap = locked ? LOCKED_CAP : IMAGE_CAP;
  // The tiles OF actually refused, as an INTERSECTION with what this bubble
  // holds — never `_failedMediaIds` counted on its own. The count below and
  // the marks on the tiles are both driven from this one list, so they cannot
  // disagree; deriving the count from `msg.media.length` instead let the
  // footer claim "remove 1 of 4" over a row where nothing was marked.
  const sameId = (a: unknown, b: unknown) => a != null && b != null && String(a) === String(b);
  const refusedHere = items.filter((m) => m.id != null && refusedIds.some((r) => sameId(r, m.id)));
  // THE COLLAPSED VIEW CARRIES THE REFUSED TILES. Expansion is the operator's
  // alone again — a plain boolean, default closed — because the question "may a
  // tile OF named be hidden?" is no longer answered by state at all: a refused
  // tile is in the collapsed set by construction, so no click order can reach
  // it. Four earlier attempts all put that decision in a boolean and each fixed
  // one ordering while breaking another:
  //   • `expanded || refusedHidden` in `visible` — opened, but left `expanded`
  //     false, so neither "+N" nor "show less" rendered: pinned with no way back.
  //   • `useState(refusedHidden)` — read once at mount, and the live ordering
  //     mounts this strip on the PENDING bubble (appendLocal runs before the
  //     POST) then patches the row in place. Always read before the failure.
  //   • `override ?? refusedHidden` — tracked the prop, but nothing cleared the
  //     override, so one collapse taken mid-flight outranked every later refusal.
  //   • `refusedHidden || (override ?? false)` + a gated "show less" — no click
  //     could hide a mark, but the row then pinned open exactly as the first
  //     attempt did, on a bubble that can be neither retried away nor dismissed.
  // Slicing by MEMBERSHIP instead of by length dissolves the whole question: the
  // row collapses normally, "+N" and "show less" behave as they always did, and
  // the marked tile is simply always in view.
  const [expanded, setExpanded] = useState(false);
  // Pairs, not bare media: the collapsed set is no longer a prefix, so the
  // `visible[i] === items[i]` identity the lightbox relies on is gone. Each
  // entry carries its ORIGINAL index, which is what setLightboxIdx must store.
  const indexed = items.map((m, i) => [m, i] as const);
  const visible = expanded
    ? indexed
    : indexed.filter(([m, i]) => i < cap || (m.id != null && refusedIds.some((r) => sameId(r, m.id))));
  const hiddenCount = items.length - visible.length;
  // Click-to-zoom lightbox. Holds the index into `items` of the tile being
  // viewed full-res (null = closed) — taken from the pair above, never from the
  // map's own position, which no longer matches once a refused tile is pulled
  // forward into the collapsed set.
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  // Tile geometry (T-GRID): media renders as small, fixed-footprint
  // thumbnails so a bundle never towers over the bubble. Each tile's box
  // is computed up-front by mediaTileBox() from the payload's width/height
  // — NOT from <img> onload — so the layout is definite from first paint
  // and never reflows when the async bytes land. The image and EVERY
  // placeholder (lock / processing / skeleton) read the SAME box, so the
  // swap-on-load causes zero movement. flex-wrap lets 1–3 little tiles sit
  // in a row and wrap; a single image is just one small box (no half-bubble
  // crop). The fallback box (used when OF didn't size the media) is also
  // what the "+N more" pill and any unknown-dim tile claim.
  const fallbackBox = mediaTileBox(compactMedia, null, null);
  const countLabel = mediaCountLabel(items);
  return (
    <div className="mt-2">
      {countLabel && <div className={cn(MP.ours.MessageList.mediaCount, "opacity-70")}>{countLabel}</div>}
      <div className="flex flex-wrap gap-1.5">
        {visible.map(([m, i]) => {
          const isVideo = isVideoMedia(m);
          // A video's tile shows its poster frame, never the clip itself.
          const rawThumb = isVideo
            ? stillUrl(m)
            : m.files?.thumb?.url || m.files?.source?.url || m.url || null;
          const thumb = proxyImage(rawThumb, accountId);
          // A video's link and click target is its clip, which also lets a
          // clip OF sent no still for open from a bare ▶ tile.
          const clip = isVideo ? clipUrl(m) : null;
          const fullRaw = clip || m.files?.source?.url || rawThumb;
          const full = proxyImage(fullRaw, accountId);
          // One source of truth for the tile footprint. Aspect-fit inside the
          // max box when OF gave us dims (box matches the true ratio, so
          // object-contain shows the whole image with no bars); a neutral
          // fallback box (letterboxed) when dims are null.
          const box = mediaTileBox(compactMedia, m.width, m.height);
          // Three-state badge mirrors the composer: green BOUGHT > gray FREE
          // (preview teaser) > red $X (PPV locked). Free-message outbound
          // (price=0) gets a badge only if the fan has bought it from us
          // at some earlier point.
          const fanEntry = m.id != null ? fanVaultQ.data?.by_media[String(m.id)] : undefined;
          // Only assert BOUGHT once the per-fan vault query has actually
          // resolved — otherwise a free (price=0) tile paints with no badge
          // and then flashes one in when the async lookup lands. `isSuccess`
          // distinguishes "not loaded" from "confirmed not bought".
          const wasBought = fanVaultQ.isSuccess && fanEntry?.was_purchased === true;
          const inPreviews = m.id != null && previewIds.some((pv) => sameId(pv, m.id));
          const showBadge = isOutgoing && (wasBought || isPPV);
          const badge = (
            showBadge ? (
              <div
                className={cn(
                  MP.ours.MessageList.tileBadge, "absolute text-white shadow z-10 pointer-events-none",
                  wasBought
                    ? "bg-ok"
                    : inPreviews ? "bg-[var(--inf-offline,var(--color-fg-dim))]" : "bg-err",
                )}
                title={
                  wasBought
                    ? "BOUGHT — this fan has purchased this item"
                    : inPreviews
                      ? "Free preview — sent unlocked"
                      : "PPV-locked — fan hasn't unlocked this tile"
                }
              >
                {wasBought ? "BOUGHT" : inPreviews ? "FREE" : priceLabel || "PPV"}
              </div>
            ) : null
          );
          // OF named this exact id in `payload.removeFromInputMediaIds`, so say
          // it ON the tile: the failure line below can only repeat OF's
          // sentence, which talks about "media" without saying which — and a
          // bundle of near-identical thumbs is exactly where that fails the
          // operator (lib/sendFailure records what it cost on 2026-08-16).
          const wasRefused = m.id != null && refusedIds.some((r) => sameId(r, m.id));
          // Fansly locked media reports price=0 (so message-level `locked` is
          // false) but canView=false — treat per-media canView===false as
          // locked → 🔒 tile, not a grey skeleton. Guard on !isOutgoing: OF
          // media CAN carry canView:false, and message-level `locked` (l.655)
          // deliberately exempts outgoing so a chatter always sees the PPV they
          // sent — mirror that. Our own Fansly media is canView:true, so this
          // costs nothing on Fansly. (§1d — no purchasing; §1e OF-regression fix.)
          const mLocked = locked || (m.canView === false && !isOutgoing);
          // Everything painted ON the tile, as one node. The three branches
          // below differ in what they wrap, not in the chrome they carry, so
          // the chrome is composed once here — including the outline, which is
          // an inset element rather than a class so no branch has to grow a
          // conditional className for it.
          const overlays = (
            <>
              {badge}
              {/* A locked tile keeps its 🔒 in the centre; a refused one's
               *  REMOVE bar covers the duration's corner. */}
              {isVideo && <VideoTileMarks media={m} glyph={!mLocked} duration={!wasRefused} />}
              {wasRefused && (
                <>
                  <div className="absolute inset-0 rounded-md border-2 border-err pointer-events-none z-10" />
                  <div
                    className={cn(MP.ours.MessageList.refusedBar, "absolute bg-err/85 text-white text-center z-10 pointer-events-none")}
                    title="This attachment was refused — remove it and the rest of the bundle sends"
                  >
                    REMOVE
                  </div>
                </>
              )}
            </>
          );
          if (mLocked) {
            // Generic lock placeholder (incoming, unpaid). Same box as a
            // loaded tile would claim — its real dims don't matter until the
            // fan unlocks it, so the fallback/aspect box is fine.
            return (
              <div
                key={m.id ?? i}
                style={{ width: box.w, height: box.h }}
                className={cn(MP.ours.MessageList.lockedTile, "relative flex-none bg-black/30 grid place-items-center text-warn border-warn/30 overflow-hidden")}
              >
                {overlays}
                🔒
              </div>
            );
          }
          if (!thumb && !clip) {
            // Pre-thumb placeholder. Reserve the SAME box the loaded image
            // will take so the swap doesn't reflow.
            return (
              <div
                key={m.id ?? i}
                style={{ width: box.w, height: box.h }}
                className={cn(MP.ours.MessageList.pendingTile, "relative flex-none bg-bg/30 grid place-items-center text-center opacity-70 overflow-hidden")}
              >
                {overlays}
                …
              </div>
            );
          }
          const isEager = m.id != null && eagerMediaIds.has(String(m.id));
          return (
            <a
              key={m.id ?? i}
              href={full || thumb}
              target="_blank"
              rel="noreferrer"
              // Left-click opens the in-app full-res lightbox; ctrl/cmd/middle
              // click falls through to the href so power users can still pop a
              // raw tab. The href also keeps this keyboard-focusable.
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                e.preventDefault();
                setLightboxIdx(i);
              }}
              style={{ width: box.w, height: box.h }}
              // Fixed box (mediaTileBox) gives a definite footprint that the
              // skeleton and loaded image both fill via h-full, so the swap on
              // load causes zero reflow. object-contain shows the whole image:
              // for known dims the box matches the ratio (no bars); for unknown
              // dims it letterboxes inside the neutral fallback box.
              className="relative block flex-none overflow-hidden rounded-md bg-black/20 cursor-zoom-in"
            >
              {overlays}
              {thumb && (
                <MediaTile
                  mediaId={m.id ?? null}
                  proxiedUrl={thumb}
                  fallbackUrl={rawThumb ?? ""}
                  eager={isEager}
                  alt=""
                  className={cn("rounded-md border border-black/10 object-contain", blurCls)}
                />
              )}
            </a>
          );
        })}
        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            style={{ width: fallbackBox.w, height: fallbackBox.h }}
            className="flex-none rounded-md border border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-xs text-fg-dim flex items-center justify-center gap-1"
          >
            +{hiddenCount}
          </button>
        )}
      </div>
      {/* The count lives HERE, beside the tiles it counts, and reads off the
       *  same `refusedHere` the marks do. In the footer it was computed from
       *  `_failedMediaIds.length` over `msg.media.length` — two different sets,
       *  free to disagree, and they did: an id past the render cap (or an id
       *  OF names that this bubble never held) produced a confident number
       *  over an unmarked row, which is the exact "nothing says which" state
       *  this feature exists to end. */}
      {refusedHere.length > 0 && (
        <div
          // Carries its OWN background. This sits INSIDE the bubble, and a
          // failed send's bubble is `bg-accent text-white` — bare `text-err`
          // measured 1.26:1 there (it was 5.6:1 in the footer it moved from),
          // i.e. the one number this feature exists to show, unreadable. Same
          // treatment as the REMOVE bar on the tiles, for the same reason.
          className={cn(MP.ours.MessageList.refusedCount, "inline-block bg-err/85 text-white")}
          title="These exact attachments were refused — drop them and re-send; a plain retry sends the same bundle."
        >
          remove {refusedHere.length} of {items.length}
        </div>
      )}
      {/* "show less" sits OUTSIDE the tile row so it keeps its natural button
       *  height instead of inheriting a tile box. It needs no refusal-aware
       *  gate: collapsing returns to a set that still CONTAINS every refused
       *  tile, so there is no longer a state where it could hide a mark — the
       *  membership slice above is what makes that true. */}
      {expanded && items.length > cap && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className={cn(MP.ours.MessageList.showLess, "w-full border-border bg-bg-elev-1 hover:bg-bg-elev-2 text-fg-dim")}
        >
          show less
        </button>
      )}
      {lightboxIdx != null && items[lightboxIdx] && (
        <MediaLightbox
          items={items}
          accountId={accountId}
          index={lightboxIdx}
          onClose={() => setLightboxIdx(null)}
          onIndex={setLightboxIdx}
        />
      )}
    </div>
  );
}

/** Full-resolution click-to-zoom overlay. Portaled to <body> so no ancestor
 *  transform/overflow can clip it. Click the dimmed backdrop (or the ×, or
 *  Esc) to close; clicking the image itself does NOT close. ←/→ (and the
 *  on-screen arrows) page through every item in the bundle, wrapping at the
 *  ends. Loads the source/full URL — a genuinely higher-res asset than the
 *  in-bubble thumbnail — via a plain <img> (the relay /img endpoint serves
 *  bytes straight to src; no need for MediaTile's hash/abort plumbing here). */
function MediaLightbox({
  items,
  accountId,
  index,
  onClose,
  onIndex,
}: {
  items: OFMedia[];
  accountId: string | null;
  index: number;
  onClose: () => void;
  onIndex: (next: number) => void;
}) {
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  const [loaded, setLoaded] = useState(false);
  const count = items.length;
  const m = items[index];
  const fullRaw = m?.files?.source?.url || m?.files?.thumb?.url || m?.url || null;
  const full = proxyImage(fullRaw, accountId);
  // A video plays (or says it can't) in place of the image and its spinner.
  const isVideo = m != null && isVideoMedia(m);

  // Reset the spinner whenever we page to a different image.
  useEffect(() => {
    setLoaded(false);
  }, [index]);

  // Esc closes; ←/→ page (wrap). Bound at the document so it works no matter
  // where focus landed after the tile click — except on a focused video, whose
  // own controls seek with ←/→.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.target instanceof HTMLMediaElement) {
        if (e.key !== "Escape") return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (count > 1 && e.key === "ArrowLeft") {
        e.preventDefault();
        onIndex((index - 1 + count) % count);
      } else if (count > 1 && e.key === "ArrowRight") {
        e.preventDefault();
        onIndex((index + 1) % count);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, count, onClose, onIndex]);

  if (!full && !isVideo) return null;

  return createPortal(
    <div
      className={cn(MP.ours.MessageList.zoomBackdrop, "fixed bg-black/85 backdrop-blur-sm flex items-center justify-center")}
      style={palette}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        aria-label="Close image"
        className="absolute top-4 right-4 z-10 w-10 h-10 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-2xl leading-none"
      >
        ×
      </button>

      {count > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous image"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((index - 1 + count) % count);
            }}
            className="absolute left-3 top-1/2 -translate-y-1/2 z-10 w-11 h-11 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-3xl leading-none"
          >
            ‹
          </button>
          <button
            type="button"
            aria-label="Next image"
            onClick={(e) => {
              e.stopPropagation();
              onIndex((index + 1) % count);
            }}
            className="absolute right-3 top-1/2 -translate-y-1/2 z-10 w-11 h-11 grid place-items-center rounded-full bg-white/10 hover:bg-white/20 text-white text-3xl leading-none"
          >
            ›
          </button>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 text-white/80 text-xs bg-black/40 rounded-full px-3 py-1">
            {index + 1} / {count}
          </div>
        </>
      )}

      {/* Clicking the image must NOT close — only the backdrop does. */}
      <div className={cn(MP.ours.MessageList.zoomFrame, "relative")} onClick={(e) => e.stopPropagation()}>
        {/* Keyed by position: paging away unmounts the video, which pauses it. */}
        {isVideo ? <ViewerVideo key={index} media={m} accountId={accountId} /> : (
          <>
            {!loaded && (
              <div className="absolute inset-0 grid place-items-center text-white/70 text-sm">
                loading…
              </div>
            )}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={full}
              alt=""
              onLoad={() => setLoaded(true)}
              className={cn(
                MP.ours.MessageList.zoomImage, "object-contain transition-opacity duration-150",
                loaded ? "opacity-100" : "opacity-0",
              )}
            />
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** Side length (px) of an in-bubble media tile. compact → small, normal →
 *  larger. The two tile sizes are the only knobs. */
const COMPACT_TILE_PX = 64;
const NORMAL_TILE_PX = 155;

/** Displayed pixel footprint of an in-bubble media tile. Pure + exported as
 *  the testable seam for the T-GRID layout: the image AND every placeholder
 *  (lock / processing / skeleton) read the SAME box, so the async byte swap
 *  never reflows.
 *
 *  EVERY tile is a FIXED SQUARE — the size depends ONLY on the compact toggle,
 *  NOT on the media's width/height. This is deliberate: OF dimensions arrive
 *  late and best-effort (the client-measured PATCH lands after first paint),
 *  so any box derived from them would RESIZE when the dims show up — that's
 *  the lazy-load bounce. A constant square is reserved identically before and
 *  after the bytes/dims arrive, so messages never shift. The image fills the
 *  square via object-contain (whole image, letterboxed) so nothing is cropped.
 *  width/height are accepted (and ignored) so the signature stays stable. */
export function mediaTileBox(
  compact: boolean,
  _width?: number | null,
  _height?: number | null,
): { w: number; h: number } {
  const side = compact ? COMPACT_TILE_PX : NORMAL_TILE_PX;
  return { w: side, h: side };
}

function QuoteCard({
  replyTo, side, ownerUserId, onClick,
}: {
  replyTo: NonNullable<OFMessage["replyToMessage"]>;
  side: "left" | "right";
  ownerUserId: number | null;
  onClick: () => void;
}) {
  // Decide who originated the quoted message — same direction test the
  // host bubble uses. Label "You" vs the author name so the chatter can
  // tell at a glance whether they're replying to their own send or the fan.
  const fromOwner =
    ownerUserId != null && replyTo.fromUser?.id === ownerUserId;
  const author =
    fromOwner
      ? "You"
      : replyTo.fromUser?.name || replyTo.fromUser?.username || "fan";
  const preview = replyTo.text
    ? stripHtml(replyTo.text)
    : replyTo.mediaCount
    ? `(${replyTo.mediaCount} media)`
    : "(message)";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        MP.ours.MessageList.quote, "block w-full text-left",
        side === "right"
          ? "bg-white/10 border-white/60 hover:bg-white/15"
          : "bg-black/10 border-fg/40 hover:bg-black/15",
      )}
      title="Jump to quoted message"
    >
      <div className={side === "right" ? "font-semibold text-white" : "font-semibold text-fg"}>
        {author}
      </div>
      <div className={cn("truncate", side === "right" ? "text-white/85" : "text-fg-dim")}>
        {preview || "(empty)"}
      </div>
    </button>
  );
}

/** Which side a bubble sits on, resolved WITHOUT comparing ids against an
 *  async fetch. Priority:
 *   1. An explicit `_side` carried on the row — DB-seed rows derive it from
 *      the authoritative `direction` column (mapped in useChatMessagesLocal),
 *      so seeded text never has to wait on the owner id.
 *   2. Optimistic outbound (tempId < 0) — always ours, even before OF echoes
 *      a real fromUser.id.
 *   3. Live OF rows (no `direction`): compare fromUser.id to ownerUserId.
 *      ownerUserId is now hydrated synchronously from a per-account
 *      localStorage cache in ChatSurface, so the FIRST paint already has it
 *      and there is no left-then-right jump.
 *  relay.ts owns OFMessage; `_side` rides along as an optional intersection
 *  field rather than widening that shared type. */
function resolveSide(
  m: OFMessage,
  ownerUserId: number | null,
): "left" | "right" {
  const explicit = (m as { _side?: "left" | "right" })._side;
  if (explicit === "left" || explicit === "right") return explicit;
  if ((m._tempId ?? 0) < 0) return "right";
  return ownerUserId != null && m.fromUser?.id === ownerUserId ? "right" : "left";
}

/** OF returns message bodies as HTML — strip tags AND decode the most
 *  common entities so bubbles render as plain text without leaking
 *  `<br>` / `&amp;` artifacts. We avoid `dangerouslySetInnerHTML` so
 *  malformed input from OF can never inject markup into our chat. */
function stripHtml(s: string): string {
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

// Per-language color for the "(es)" tag — same code, same color everywhere so
// a chatter learns "amber = Spanish" at a glance. Unknown codes fall back to sky.
const LANG_TAG_COLOR: Record<string, string> = {
  es: "text-warn",
  sl: "text-accent",
  pt: "text-ok",
  fr: "text-info",
  de: "text-warn",
  it: "text-ok",
};

/** Bubble text with the 🌐 translate layer. When a translation exists and the
 *  detected language isn't English, render "(es)" (colored by language) + the
 *  English text; the original stays one hover away in the title tooltip.
 *  English / untranslated / toggle-off all render the plain original. */
function TranslatableText({ raw, translation, textClassName }: {
  raw: string;
  translation?: BubbleTranslation | null;
  /** On the text span only, never the language tag: a PPV's title weight (ML11). */
  textClassName?: string;
}) {
  const original = stripHtml(raw);
  const t = translation;
  const show = !!t?.text && t.lang !== "en"
    && t.text.trim().toLowerCase() !== original.trim().toLowerCase();
  if (!show) return <span className={textClassName}>{original}</span>;
  return (
    <>
      <span
        className={cn(
          MP.ours.MessageList.langTag, "self-center",
          LANG_TAG_COLOR[t.lang] ?? "text-info",
        )}
      >
        ({t.lang})
      </span>
      <span className={textClassName} title={original}>{t.text}</span>
    </>
  );
}

function localDateKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function DateSeparator({ label }: { label: string }) {
  return (
    <div
      className={cn("flex items-center select-none", MP.messageList.divider)}
      role="separator"
      aria-label={label}
    >
      <div className="flex-1 h-px bg-[var(--inf-date-rule,var(--color-border))]" />
      <span className={cn(MP.messageList.dividerLabel, "text-fg-dim")}>
        {label}
      </span>
      <div className="flex-1 h-px bg-[var(--inf-date-rule,var(--color-border))]" />
    </div>
  );
}
