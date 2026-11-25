"use client";


import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";

const G = MP.fanList;

const SKELETON_ROWS = 6;

export function FanListEmpty({ text = "No conversations found" }: { text?: string } = {}) {
  return <div className={cn(G.empty, "text-fg-dim")}>{text}</div>;
}

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

export function ShowMoreRows({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button
      type="button"
      data-show-more-rows
      onClick={onClick}
      className={cn(G.loadMore, "w-full text-center border-[color:var(--inf-rule,color-mix(in_oklab,var(--color-border)_40%,transparent))] text-[var(--inf-accent-text,var(--color-accent))] hover:bg-bg-elev-1")}
    >
      Show {count} more
    </button>
  );
}
