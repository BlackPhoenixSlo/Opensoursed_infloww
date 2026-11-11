"use client";

/** The help bot's earlier conversations, over the panel (AssistantWidget.tsx):
 *  newest first in day sections (assistantReducer `groupByDay`); a pick opens
 *  that thread. */

import { useRef } from "react";
import { X } from "lucide-react";

import { useMenuDismiss } from "@/components/chat/useMenuDismiss";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { groupByDay, type ThreadSummary } from "./assistantReducer";
import { focusLabel } from "./FocusLine";

/** Local time under a day section: "22:24". */
const TIME = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export function ThreadList({
  threads, active, accounts, onPick, onClose,
}: {
  threads: ThreadSummary[];
  active: string | null;
  accounts: AccountMeta[];
  onPick: (t: ThreadSummary) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useMenuDismiss(ref, true, onClose);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="Earlier conversations"
      className="absolute inset-0 z-20 flex flex-col bg-panel text-fg"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-5 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <h3 className="flex-1 text-[16px] font-semibold">Earlier conversations</h3>
        <button
          type="button"
          onClick={onClose}
          className="-mr-2 grid h-8 w-8 place-items-center rounded-md text-fg-dim hover:bg-bg-elev-1 hover:text-fg"
          title="Close"
          aria-label="Close earlier conversations"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-4">
        {groupByDay(threads, new Date()).map((g, i) => (
          <section key={`${i}-${g.label}`} aria-label={g.label} className="pt-3">
            <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted">{g.label}</div>
            {g.threads.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => onPick(t)}
                aria-current={t.id === active ? "true" : undefined}
                className={cn(
                  "flex w-full flex-col rounded-lg px-2 py-2 text-left hover:bg-bg-elev-1",
                  t.id === active && "bg-bg-elev-1",
                )}
              >
                <span className="truncate text-[13px] font-medium text-fg">{t.title}</span>
                <span className="truncate text-[11px] text-muted">
                  {focusLabel(t.focus, accounts)} · {t.count} question{t.count === 1 ? "" : "s"} · {TIME.format(new Date(t.last))}
                </span>
              </button>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
