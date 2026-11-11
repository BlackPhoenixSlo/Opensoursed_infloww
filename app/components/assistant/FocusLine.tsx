"use client";

/** "Currently selected: <focus>" above the help bot's composer
 *  (AssistantWidget.tsx). Presentation only: the focus rules are the reducer's
 *  (assistantReducer.ts, FOCUS / ROSTER). */

import { useCallback, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

import { useMenuDismiss } from "@/components/chat/useMenuDismiss";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import type { Focus } from "./assistantReducer";

/** "General", or the model's nickname. */
export function focusLabel(focus: Focus, accounts: AccountMeta[]): string {
  if (focus === null) return "General";
  const a = accounts.find((x) => x.id === focus);
  return a?.nickname || focus;
}

/** No captured session, or a deactivated Creator: the bot still answers about
 *  it (it reads the relay's rows, never OnlyFans), but nothing runs on it now. */
const offline = (a: AccountMeta) => !a.has_session || !a.is_active;

/** Click to focus the bot on General or one owned model (an offline one is
 *  marked). While a started chat holds off an app switch (`held`) to a model,
 *  it offers that model (`appFocus`) as a new chat. A move to all models (a
 *  page with no creator picker: Dashboard, Settings) offers nothing — the chat
 *  just stays on its model; New chat still lands on General. */
export function FocusLine({
  focus, accounts, canGeneral, started, held, appFocus, onPick, onNewChat,
}: {
  focus: Focus;
  accounts: AccountMeta[];
  canGeneral: boolean;
  started: boolean;
  held: boolean;
  appFocus: Focus;
  onPick: (f: Focus) => void;
  onNewChat: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useMenuDismiss(ref, open, useCallback(() => setOpen(false), []));
  const options: Array<AccountMeta | null> = [...(canGeneral ? [null] : []), ...accounts];
  const choose = (f: Focus) => { onPick(f); setOpen(false); };

  return (
    <div ref={ref} className="relative flex items-center gap-1.5 px-1 text-[11px]">
      <span className="shrink-0 text-muted">Currently selected:</span>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Help bot focus: ${focusLabel(focus, accounts)}`}
        title="What the help bot answers about"
        className="flex min-w-0 items-center gap-0.5 font-medium text-fg-dim hover:text-fg"
      >
        <span className="truncate">{focusLabel(focus, accounts)}</span>
        <ChevronDown className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {held && appFocus !== null && (
        <button
          type="button"
          onClick={onNewChat}
          className="ml-auto min-w-0 truncate rounded-full bg-bg-elev-1 px-2 py-0.5 font-medium text-fg-dim hover:text-fg"
          title="You switched model in the app; this chat stays on its own. Start a new chat about the app's model."
        >
          {focusLabel(appFocus, accounts)} in app · New chat
        </button>
      )}
      {open && (
        <div
          role="menu"
          aria-label="Focus the help bot on"
          className="absolute bottom-full left-0 z-30 mb-1.5 flex max-h-72 w-64 flex-col overflow-hidden rounded-xl border border-border bg-panel shadow-[0_8px_24px_rgba(0,0,0,0.18)]"
        >
          <div className="border-b border-border px-3 py-2 text-[11px] text-muted">
            {started ? "Picking another starts a new chat" : "Answer about"}
          </div>
          <div className="overflow-y-auto py-1">
            {options.map((a) => {
              const f = a?.id ?? null;
              const on = f === focus;
              return (
                <button
                  key={f ?? "general"}
                  type="button"
                  role="menuitemradio"
                  aria-checked={on}
                  onClick={() => choose(f)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-fg hover:bg-bg-elev-1"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{focusLabel(f, accounts)}</span>
                    {a === null && <span className="block text-[11px] text-muted">The manual only — no model&apos;s live data</span>}
                    {a !== null && offline(a) && (
                      <span className="block text-[11px] text-muted">Offline — no session, or deactivated</span>
                    )}
                  </span>
                  {on && <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
