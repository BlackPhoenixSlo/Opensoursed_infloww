"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { ArrowUp, ChevronLeft, LifeBuoy, X } from "lucide-react";

import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";
import {
  buildPayload, canSend, errorText, initialSupportState, messagesOf, supportReducer,
} from "./supportReducer";

export const SUPPORT_EMPTY = "Tell us what's missing or annoying — the team reads every message.";

export function SupportButton({ unread, onClick }: { unread: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative grid h-8 w-8 place-items-center rounded-md text-current hover:bg-white/10"
      title="Support — message the team"
      aria-label={unread ? "Support (new reply)" : "Support"}
    >
      <LifeBuoy className="h-[18px] w-[18px]" aria-hidden />
      {unread && <span className="absolute right-0.5 top-0.5 h-2.5 w-2.5 rounded-full bg-[#e5372f]" aria-hidden />}
    </button>
  );
}

export function SupportPanel({ frame, column, composerPad, inputText, unread, onBack, onClose, onRead }: {
  frame: string;
  column: string;
  composerPad: string;
  inputText: string;
  unread: number;
  onBack: () => void;
  onClose?: () => void;
  onRead: () => void;
}) {
  const [s, dispatch] = useReducer(supportReducer, initialSupportState);
  const listRef = useRef<HTMLDivElement | null>(null);
  const live = useRef(true);
  const loadedOnce = useRef(false);
  const wake = unread > 0;

  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);

  const load = useCallback(() => {
    dispatch({ type: "load_started" });
    void Promise.resolve()
      .then(() => relay.get<unknown>("/admin/support/thread"))
      .then((body) => {
        if (!live.current) return;
        dispatch({ type: "loaded", messages: messagesOf(body) });
        return relay.post<unknown>("/admin/support/read", {}).then(() => { if (live.current) onRead(); });
      })
      .catch((e) => { if (live.current) dispatch({ type: "load_failed", error: errorText(e) }); });
  }, [onRead]);

  useEffect(() => {
    if (loadedOnce.current && !wake) return;
    loadedOnce.current = true;
    load();
  }, [wake, load]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [s.messages]);

  const send = () => {
    if (!canSend(s)) return;
    const payload = buildPayload(s);
    dispatch({ type: "send_started" });
    void Promise.resolve()
      .then(() => relay.post<unknown>("/admin/support/messages", payload))
      .then((body) => { if (live.current) dispatch({ type: "sent", messages: messagesOf(body) }); })
      .catch((e) => { if (live.current) dispatch({ type: "send_failed", error: errorText(e) }); });
  };

  return (
    <div data-look="messenger" data-assistant-ui data-support
      className={cn("flex flex-col bg-panel text-fg overflow-hidden", frame)}>
      <div className="shrink-0 bg-[linear-gradient(180deg,#242424_0%,#2d2d2d_55%,var(--color-panel)_100%)] pt-[37px] pb-8 text-white">
        <div className={cn("px-10", column)}>
          <div className="flex h-8 items-center gap-3">
            <button
              type="button"
              onClick={onBack}
              className="-ml-6 grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
              title="Back to help"
              aria-label="Back to help"
            >
              <ChevronLeft className="h-5 w-5" aria-hidden />
            </button>
            <span className="text-[18px] font-bold">Support</span>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="-mr-4 ml-auto grid h-8 w-8 place-items-center rounded-md text-white hover:bg-white/10"
                title="Close"
                aria-label="Close help"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            )}
          </div>
          <p className="mt-2 text-[12px] text-white/60">Message the team behind the product</p>
        </div>
      </div>

      <div ref={listRef} className="-mt-4 flex-1 min-h-0 overflow-y-auto overscroll-contain pb-3">
        <div className={cn("px-5 flex flex-col gap-2", column)}>
          {s.phase === "loading" && s.messages.length === 0 && (
            <div className="px-1 text-[13px] text-fg-dim animate-pulse">Loading…</div>
          )}
          {s.phase !== "loading" && s.messages.length === 0 && !s.error && (
            <div className="rounded-2xl border border-border bg-bg-elev-1 px-4 py-3 text-[14px] text-fg-dim">{SUPPORT_EMPTY}</div>
          )}
          {s.messages.map((m) => (
            <div key={m.id} className={cn("flex flex-col gap-0.5", m.from === "me" ? "items-end" : "items-start")}>
              {m.from === "support" && <span className="px-1 text-[11px] text-muted">Support</span>}
              <div className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2 text-[13px] whitespace-pre-wrap break-words",
                m.from === "me" ? "rounded-br-md bg-fg text-panel" : "rounded-bl-md bg-bg-elev-1 text-fg",
              )}>
                {m.text}
              </div>
            </div>
          ))}
          {s.error && (
            <div role="alert" className="flex items-center gap-2 px-1 text-[12px] text-fg-dim">
              <span>{s.error}</span>
              {s.phase === "failed" && (
                <button type="button" onClick={load} className="underline hover:text-fg">Retry</button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-panel">
        <div className={cn("px-4 pt-2.5 pb-4", composerPad, column)}>
          <div className="flex items-end gap-2 rounded-3xl border border-border bg-panel py-1.5 pl-4 pr-1.5 focus-within:border-fg-dim">
            <textarea
              value={s.draft}
              onChange={(e) => dispatch({ type: "draft", text: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Message Support…"
              title="Goes to the product team. Enter to send · Shift+Enter for a new line"
              aria-label="Message Support"
              rows={1}
              className={cn(
                "flex-1 min-w-0 max-h-28 resize-none bg-transparent py-1.5 leading-5 text-fg placeholder:text-muted focus:outline-none [field-sizing:content]",
                inputText,
              )}
            />
            <button
              type="button"
              onClick={send}
              disabled={!canSend(s)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-fg text-panel transition-opacity disabled:opacity-25"
              aria-label="Send to Support"
              title="Send"
            >
              <ArrowUp className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
