"use client";

/** FunnelEditor's step card: one reply / PPV step of a mass-message funnel, as a node on the steps timeline (Infloww
 *  Scripts' sequence steps). Closed it is one summary row (type, price / AI, the first line of copy); open it shows
 *  the type, the copy and, folded, the reply-check timing. */

import { useId } from "react";
import { ChevronDown, ChevronUp, Image as ImageIcon, Sparkles, Trash2 } from "lucide-react";

import {
  IfButton, IfHelp, IfInput, IfLabel, IfSegmented, IfSwitch, IfTextArea, type IfOption,
} from "@/components/ui/infloww";
import { VariantsField } from "@/components/compose/VariantsField";
import type { DraftStep } from "@/lib/funnelDraft";
import { cn } from "@/lib/utils";

/** reply_mass_funnel._step_texts: a static step sends its first 2 messages. */
const FUNNEL_STEP_MSGS = 2;
const DEFAULT_CHECKS = "2, 4, 10";

const KINDS: IfOption<DraftStep["kind"]>[] = [
  { value: "reply", label: "Reply" },
  { value: "ppv", label: "Paid PPV" },
];
const SOURCES: IfOption<"static" | "ai">[] = [
  { value: "static", label: "Write it" },
  { value: "ai", label: "AI writes it" },
];
/** Icon-only link actions: muted until hovered, thumb-sized below md. */
const ICON_ACTION = "w-8 text-muted hover:text-fg disabled:hover:text-muted max-md:h-10 max-md:w-10";

/** The closed card's one line: the first message, the AI prompt, or what is missing. */
function preview(step: DraftStep): string {
  if (step.generate) return step.prompt.trim() || "AI writes it (default persona)";
  return step.messages.map((m) => m.trim()).find(Boolean) || "No message yet";
}

export function StepCard({
  index, total, step, open, onToggle, onPatch, onRemove, onMove,
}: {
  index: number;
  total: number;
  step: DraftStep;
  open: boolean;
  onToggle: () => void;
  onPatch: (patch: Partial<DraftStep>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const isPpv = step.kind === "ppv";
  const id = useId();
  const price = step.price.trim();
  return (
    <li className="relative pl-10">
      {/* The timeline: a numbered node on the rail. */}
      <span aria-hidden className={cn(
        "absolute left-0 top-3 grid h-7 w-7 place-items-center rounded-full text-[12px] font-medium",
        isPpv ? "bg-accent text-white" : "border border-border bg-bg text-fg",
      )}>{index + 1}</span>
      <div className={cn("rounded-lg border border-border bg-bg", open && "border-accent/60")}>
        <div className="flex items-center gap-2 pr-2">
          <button type="button" aria-expanded={open} onClick={onToggle}
            className="flex min-h-[52px] min-w-0 flex-1 items-center gap-2 px-4 py-2 text-left">
            <span className="shrink-0 text-[14px] font-medium text-fg">Step {index + 1}</span>
            <span className={cn("shrink-0 rounded-2xl px-2 py-0.5 text-[12px]",
              isPpv ? "bg-accent/15 text-accent" : "bg-fg-dim/15 text-fg-dim")}>
              {isPpv ? `Paid PPV${price ? ` · $${price}` : ""}` : "Reply"}
            </span>
            {step.generate && <Sparkles aria-label="AI-written" className="h-3.5 w-3.5 shrink-0 text-accent" />}
            <span className="min-w-0 truncate text-[13px] text-muted">{preview(step)}</span>
          </button>
          <IfButton variant="link" icon={ChevronUp} aria-label="Move up" title="Move up"
            onClick={() => onMove(-1)} disabled={index === 0} className={ICON_ACTION} />
          <IfButton variant="link" icon={ChevronDown} aria-label="Move down" title="Move down"
            onClick={() => onMove(1)} disabled={index === total - 1} className={ICON_ACTION} />
          <IfButton variant="link" icon={Trash2} aria-label="Remove step" title="Remove step"
            onClick={onRemove} className={`${ICON_ACTION} hover:text-err`} />
        </div>

        {open && (
          <div className="space-y-4 border-t border-border px-4 pb-4 pt-4">
            <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
              <div>
                <IfLabel>Type</IfLabel>
                <IfSegmented aria-label="Step type" options={KINDS} value={step.kind} onChange={(kind) => onPatch({ kind })} />
              </div>
              {isPpv && (
                <div>
                  <IfLabel htmlFor={`${id}-price`}>Price (USD)</IfLabel>
                  <IfInput id={`${id}-price`} type="number" min={0} value={step.price}
                    onChange={(e) => onPatch({ price: e.target.value })} placeholder="default $24" className="w-32" />
                </div>
              )}
              {isPpv && (
                <IfSwitch label="Lock the text too" checked={step.lockedText}
                  onChange={(lockedText) => onPatch({ lockedText })} className="flex h-8" />
              )}
            </div>
            {isPpv && (
              <IfHelp className="flex items-center gap-1.5">
                <ImageIcon aria-hidden className="h-3.5 w-3.5 shrink-0" />
                The PPV media is picked per creator: the funnel&apos;s Media action.
              </IfHelp>
            )}

            <div className="space-y-2">
              <IfSegmented aria-label="Message source" options={SOURCES} value={step.generate ? "ai" : "static"}
                onChange={(v) => onPatch({ generate: v === "ai" })} />
              {step.generate ? (
                <div>
                  <IfTextArea id={`${id}-prompt`} aria-label="AI prompt" value={step.prompt}
                    onChange={(e) => onPatch({ prompt: e.target.value })} rows={2}
                    placeholder={isPpv ? "e.g. tease the PPV and create urgency…" : "e.g. flirt back and ask what he likes…"} />
                  <IfHelp>Guides the AI; blank uses the creator&apos;s persona. Uses your AI key per reply.</IfHelp>
                </div>
              ) : (
                // reply_mass_funnel sends static messages[:2], one after the other (_step_texts, _send_step).
                <VariantsField
                  id={`${id}-msg`}
                  label={isPpv ? "Sales copy" : "Message"}
                  variants={step.messages}
                  placeholder="Message…"
                  max={FUNNEL_STEP_MSGS}
                  help="Up to 2, sent one after the other."
                  onChange={(messages) => onPatch({ messages })}
                />
              )}
            </div>

            <details className="group text-[13px]">
              <summary className="cursor-pointer select-none text-accent hover:text-accent-hover">
                Reply checks: {step.intervals.trim() || DEFAULT_CHECKS} min
              </summary>
              <div className="mt-2">
                <IfLabel htmlFor={`${id}-every`}>Check for a reply after (minutes)</IfLabel>
                <IfInput id={`${id}-every`} value={step.intervals} onChange={(e) => onPatch({ intervals: e.target.value })}
                  placeholder={DEFAULT_CHECKS} className="w-full sm:w-64" />
                <IfHelp>Comma-separated gaps, the last repeats · blank = {DEFAULT_CHECKS}</IfHelp>
              </div>
            </details>
          </div>
        )}
      </div>
    </li>
  );
}
