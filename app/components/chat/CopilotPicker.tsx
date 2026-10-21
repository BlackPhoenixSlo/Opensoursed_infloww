"use client";

/**
 * CopilotPicker — the Composer's "AI" pill: Infloww's AI Copilot
 * (help.infloww.com articles 262036 and 262040). Click "AI", pick Casual,
 * Re-engage, Tip request or Sexting, and the Relay suggests three replies for
 * this Fan's thread (`POST /admin/copilot/{account}/{fan}/suggest`). Clicking
 * one inserts it at the cursor, where the employee edits it and presses Send;
 * nothing is ever sent from here. "Regenerate" asks again with the set on
 * screen as `avoid`, so the next set differs.
 *
 * One request per click: a mode generates only when picked, re-picking the mode
 * already on screen does nothing, and suggestions survive closing the panel.
 * The Composer keys this by account and Fan, so a Fan switch starts clean (an
 * answer still in flight lands on the unmounted picker and is dropped). Errors
 * print the Relay's sentence; a missing AI key is also announced app-wide by
 * the relay client (ApiKeyError).
 *
 * Opens UPWARD and right-aligned (the pill sits at the right end of the
 * Composer's button row). Closes on outside click.
 */

import { useEffect, useRef, useState } from "react";
import { Bot, RefreshCw } from "lucide-react";

import { relay } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";
import { cn } from "@/lib/utils";
import { PILL, PILL_ICON, PILL_LABEL } from "./ComposerToolbar";
import { MENU_BOX } from "./MenuParts";

export type CopilotMode = "casual" | "reengage" | "tip_request" | "sexting";

/** Infloww's four modes, in its order and with its labels. */
export const COPILOT_MODES: { id: CopilotMode; label: string }[] = [
  { id: "casual", label: "Casual" },
  { id: "reengage", label: "Re-engage" },
  { id: "tip_request", label: "Tip request" },
  { id: "sexting", label: "Sexting" },
];

interface SuggestResponse {
  mode: CopilotMode;
  suggestions: string[];
}

export interface CopilotPickerProps {
  accountId: string | null;
  fanId: FanId | null;
  /** Insert this suggestion into the Composer's text box. */
  onPick: (text: string) => void;
}

export function CopilotPicker({ accountId, fanId, onPick }: CopilotPickerProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<CopilotMode | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  async function generate(next: CopilotMode, avoid: string[]) {
    if (!accountId || fanId == null) return;
    setMode(next);
    setLoading(true);
    setError(null);
    setSuggestions([]);
    try {
      const res = await relay.post<SuggestResponse>(
        `/admin/copilot/${accountId}/${fanId}/suggest`,
        { mode: next, avoid },
        { accountId },
      );
      setSuggestions(res.suggestions ?? []);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "AI Copilot failed. Try again.");
    } finally {
      setLoading(false);
    }
  }

  function pickMode(next: CopilotMode) {
    if (loading || (next === mode && suggestions.length > 0)) return;
    void generate(next, []);
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={fanId == null}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="AI Copilot"
        className={cn(PILL, "bg-[var(--inf-ai-pill,var(--color-bg-elev-2))] text-[var(--inf-accent-text,var(--color-accent))]")}
      >
        <Bot {...PILL_ICON} />
        <span className={PILL_LABEL}>AI</span>
      </button>
      {open && (
        <div
          role="region"
          aria-label="AI Copilot"
          className={cn(MENU_BOX, "absolute bottom-full right-0 mb-2 w-80 max-h-96 p-2 z-50 text-xs")}
        >
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Reply style">
            {COPILOT_MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                aria-pressed={mode === m.id}
                disabled={loading}
                onClick={() => pickMode(m.id)}
                className={cn(
                  "px-2.5 py-1 rounded-full border text-xs disabled:opacity-60",
                  mode === m.id
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-border text-fg-dim hover:text-fg hover:border-accent",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>

          <div className="mt-2 space-y-1">
            {!mode && !loading && (
              <div className="text-fg-dim p-1">Pick a style to get 3 replies for this chat.</div>
            )}
            {loading && <div className="text-fg-dim p-1" role="status">Generating…</div>}
            {error && <div className="text-err p-1" role="alert">{error}</div>}
            {suggestions.map((s, i) => (
              <button
                key={`${i}:${s}`}
                type="button"
                onClick={() => {
                  onPick(s);
                  setOpen(false);
                }}
                className="block w-full text-left px-2 py-1.5 rounded border border-border hover:bg-bg-elev-1 hover:border-accent whitespace-pre-wrap leading-snug text-fg"
              >
                {s}
              </button>
            ))}
          </div>

          {mode && !loading && (
            <div className="mt-2 flex justify-end">
              <button
                type="button"
                onClick={() => void generate(mode, suggestions)}
                className="flex items-center gap-1 px-2 py-1 rounded text-fg-dim hover:text-fg hover:bg-bg-elev-1"
              >
                <RefreshCw size={12} aria-hidden />
                Regenerate
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
