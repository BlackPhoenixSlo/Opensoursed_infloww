"use client";

/** The help bot's cosmetic cursor while "Do it for me" fills a form (useDoRunner.ts): an arrow, a small label bubble
 *  and a ripple per click. Fixed and `pointer-events:none` above every dialog, so it never takes a click itself; it
 *  glides between fields, or jumps under prefers-reduced-motion. */

import { cn } from "@/lib/utils";

export interface CursorState {
  x: number;
  y: number;
  label: string;
  /** Bumped per click: keys the ripple so each one replays. */
  clicks: number;
}

export function AgentCursor({ cursor }: { cursor: CursorState }) {
  return (
    <div
      data-agent-cursor
      aria-hidden
      className={cn(
        "pointer-events-none fixed left-0 top-0 z-[2100]",
        "transition-transform duration-300 ease-in-out motion-reduce:transition-none",
      )}
      style={{ transform: `translate(${Math.round(cursor.x)}px, ${Math.round(cursor.y)}px)` }}
    >
      {cursor.clicks > 0 && (
        <span
          key={cursor.clicks}
          className="absolute -left-3 -top-3 h-6 w-6 rounded-full bg-[#3563ff]/40 motion-safe:animate-ping [animation-iteration-count:1]"
        />
      )}
      <svg viewBox="0 0 24 24" className="relative h-6 w-6 drop-shadow-[0_2px_4px_rgba(0,0,0,0.45)]">
        <path d="M3 2l7.5 19 2.6-7.4L20.5 11z" fill="#111" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
      {cursor.label && (
        <span className="absolute left-5 top-5 whitespace-nowrap rounded-full bg-[#111] px-2.5 py-1 text-[12px] font-medium text-white shadow-lg">
          {cursor.label}
        </span>
      )}
    </div>
  );
}
