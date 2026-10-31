"use client";

/** FunnelEditor's step card: one reply / PPV step of a mass-message funnel. */

import { Badge, Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import type { DraftStep } from "@/lib/funnelDraft";

/** reply_mass_funnel._step_texts: a static step sends its first 2 messages. */
const FUNNEL_STEP_MSGS = 2;

/** One step card: reply / PPV toggle + the per-kind fields. */
export function StepCard({
  index,
  total,
  step,
  onPatch,
  onRemove,
  onMove,
  onMsgChange,
  onMsgAdd,
  onMsgImport,
  onMsgRemove,
}: {
  index: number;
  total: number;
  step: DraftStep;
  onPatch: (patch: Partial<DraftStep>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  onMsgChange: (mi: number, val: string) => void;
  onMsgAdd: () => void;
  onMsgImport: (texts: string[]) => void;
  onMsgRemove: (mi: number) => void;
}) {
  const isPpv = step.kind === "ppv";
  return (
    <div className="border border-border rounded-md p-3 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-fg-dim">Step {index + 1}</span>
          <Badge color={isPpv ? "warn" : "muted"}>{isPpv ? "paid PPV" : "reply"}</Badge>
        </div>
        <div className="flex items-center gap-2 md:gap-1">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={index === 0}
            className="text-fg-dim hover:text-fg disabled:opacity-30 text-base px-2 py-1 min-w-10 min-h-10 md:text-xs md:px-1 md:py-0 md:min-w-0 md:min-h-0"
            title="Move up"
          >↑</button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            className="text-fg-dim hover:text-fg disabled:opacity-30 text-base px-2 py-1 min-w-10 min-h-10 md:text-xs md:px-1 md:py-0 md:min-w-0 md:min-h-0"
            title="Move down"
          >↓</button>
          <button
            type="button"
            onClick={onRemove}
            className="text-xs px-2 py-1 min-h-10 md:text-[11px] md:px-0 md:py-0 md:min-h-0 text-err hover:underline ml-1"
          >remove</button>
        </div>
      </div>

      {/* Reply / PPV toggle. */}
      <div className="flex items-center gap-1.5">
        <KindChip active={!isPpv} onClick={() => onPatch({ kind: "reply" })} label="Reply" />
        <KindChip active={isPpv} onClick={() => onPatch({ kind: "ppv" })} label="Paid PPV" />
      </div>

      {/* Poll intervals (the walker waits on a PPV step's cadence too). */}
      <label className="block space-y-1">
        <span className="text-[11px] text-fg-dim">
          Check for a reply every <span className="opacity-60">(minutes, comma-separated; blank = default 2, 4, 10)</span>
        </span>
        <Input
          value={step.intervals}
          onChange={(e) => onPatch({ intervals: e.target.value })}
          placeholder="2, 4, 10"
        />
      </label>

      {/* PPV: price + locked-text. MEDIA is per-model → set in the Media pane. */}
      {isPpv && (
        <div className="space-y-2">
          <label className="block space-y-1 max-w-[12rem]">
            <span className="text-[11px] text-fg-dim">Price (USD, whole)</span>
            <Input
              type="number"
              min={0}
              value={step.price}
              onChange={(e) => onPatch({ price: e.target.value })}
              placeholder="default $24"
            />
          </label>
          <div className="text-[11px] text-fg-dim italic">
            🖼 Media for this PPV step is set per model in the funnel&apos;s{" "}
            <span className="text-fg not-italic">Media</span> action (vault ids
            differ per account).
          </div>
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input
              type="checkbox"
              checked={step.lockedText}
              onChange={(e) => onPatch({ lockedText: e.target.checked })}
            />
            <span>Lock the text too (fan must pay to read the copy)</span>
          </label>
        </div>
      )}

      {/* Copy: AI-generate toggle, then either a prompt or a variant pool. */}
      <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
        <input
          type="checkbox"
          checked={step.generate}
          onChange={(e) => onPatch({ generate: e.target.checked })}
        />
        <span>Generate the {isPpv ? "sales copy" : "reply"} with AI</span>
      </label>

      {step.generate ? (
        <label className="block space-y-1">
          <span className="text-[11px] text-fg-dim">
            Prompt <span className="opacity-60">(optional — guides the AI; blank uses the default persona)</span>
          </span>
          <textarea
            value={step.prompt}
            onChange={(e) => onPatch({ prompt: e.target.value })}
            rows={2}
            placeholder="e.g. tease the PPV and create urgency…"
            className="w-full bg-bg border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
          />
        </label>
      ) : (
        <div className="space-y-1.5">
          <span className="text-[11px] text-fg-dim">
            {isPpv ? "Sales copy" : "Reply"} variants <span className="opacity-60">(one is sent at random; first ≤2 used)</span>
          </span>
          {step.messages.map((m, mi) => (
            <div key={mi} className="flex items-start gap-1.5">
              <textarea
                value={m}
                onChange={(e) => onMsgChange(mi, e.target.value)}
                rows={2}
                placeholder={step.messages.length > 1 ? `Variant ${mi + 1}` : "Message…"}
                className="flex-1 bg-bg border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:border-accent resize-y"
              />
              {step.messages.length > 1 && (
                <button
                  type="button"
                  onClick={() => onMsgRemove(mi)}
                  title="Remove this variant"
                  className="text-fg-dim hover:text-err text-sm leading-none mt-2"
                >×</button>
              )}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <button
              type="button"
              onClick={onMsgAdd}
              className="text-[11px] text-accent hover:underline"
            >
              + add variant{step.messages.length > 1 ? ` (${step.messages.length})` : ""}
            </button>
            {/* reply_mass_funnel sends static messages[:2] only. */}
            <ImportCaptionsButton current={step.messages} max={FUNNEL_STEP_MSGS} onImport={onMsgImport} />
          </div>
        </div>
      )}
    </div>
  );
}

function KindChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-2.5 py-1 rounded-full text-[11px] border transition-colors",
        active
          ? "bg-accent text-white border-accent"
          : "bg-bg-elev-1 text-fg-dim border-border hover:text-fg hover:border-fg-dim",
      )}
    >
      {label}
    </button>
  );
}
