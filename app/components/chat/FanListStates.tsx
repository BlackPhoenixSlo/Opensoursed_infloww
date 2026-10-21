"use client";

/**
 * FanListStates — what the Fan List shows in place of, before or after its
 * rows: the empty line, the cold-load skeleton and "Load more
 * conversations", in the Clone's text and geometry, and Focus mode's banner
 * in the kit's note geometry (docs/spec/phase-02-fan-list-pane.md, States and
 * Focus mode; Gap rows 26-29). FanList decides when each shows.
 */

import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const G = MP.fanList;

/** The Clone's skeleton holds six rows (`SKEL_ROWS`, mj:472; Gap row 27). */
const SKELETON_ROWS = 6;

/** The line an empty list shows, the Clone's (mj:575). Refresh lives in the
 *  sort line, so it has no button of its own (spec, States). `text` replaces
 *  the line when a narrowing (Online Fans) has emptied a loaded list. */
export function FanListEmpty({ text = "No conversations found" }: { text?: string } = {}) {
  return <div className={cn(G.empty, "text-fg-dim")}>{text}</div>;
}

/** Six placeholder rows at the Fan row's size while the first page loads. */
export function FanListSkeleton() {
  return (
    <div role="list" aria-label="Loading conversations" aria-busy="true">
      {Array.from({ length: SKELETON_ROWS }, (_, i) => (
        <div
          key={i}
          role="listitem"
          className={cn(G.skeletonRow, "flex items-center border-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))] animate-pulse motion-reduce:animate-none")}
        >
          <div className={cn(G.skeletonAvatar, "shrink-0 bg-bg-elev-1")} />
          <div className={cn(G.skeletonLines, "flex-1 min-w-0 flex flex-col")}>
            <div className={cn(G.skeletonBar, G.skeletonBarShort, "bg-bg-elev-1")} />
            <div className={cn(G.skeletonBar, G.skeletonBarLong, "bg-bg-elev-1")} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** The list's last line while more chats exist, the Clone's (mj:581). The
 *  count of chats loaded so far sits in its tooltip. */
export function LoadMoreConversations({ loaded, onClick }: { loaded: number; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${loaded} chats loaded`}
      className={cn(G.loadMore, "w-full text-center border-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))] text-[var(--inf-accent-text,var(--color-accent))] hover:bg-bg-elev-1")}
    >
      Load more conversations
    </button>
  );
}

/** Focus mode's banner at the top of the frozen rows: "{N} new messages"
 *  (spec, Focus mode). A click catches up: a refresh, then the live order.
 *  ASSUMPTION: its colours are the kit note's accent tint in our tokens
 *  (`border-accent/30 bg-accent/10 text-fg hover:bg-accent/15`), which the
 *  spec's colour mapping does not list. Rung 3 (ADR-0001 tokens); overturned
 *  by Phase 6's token pass. */
export function FocusModeBanner({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <div className="px-4 py-2">
      <button
        type="button"
        onClick={onClick}
        className={cn(G.focusBanner, "w-full flex items-start text-left border-accent/30 bg-accent/10 text-fg hover:bg-accent/15")}
      >
        {count} new messages
      </button>
    </div>
  );
}
