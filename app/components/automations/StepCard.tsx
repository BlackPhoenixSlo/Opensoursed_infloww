"use client";

/** FunnelEditor's step card: one reply / PPV step of a mass-message funnel. */

import { useId } from "react";
import { ChevronDown, ChevronUp, Image as ImageIcon, Trash2, X } from "lucide-react";

import {
  IfButton, IfHelp, IfInput, IfLabel, IfSegmented, IfSwitch, IfTextArea, type IfOption,
} from "@/components/ui/infloww";
import { ImportCaptionsButton } from "@/components/compose/ImportCaptionsButton";
import type { DraftStep } from "@/lib/funnelDraft";

/** reply_mass_funnel._step_texts: a static step sends its first 2 messages. */
const FUNNEL_STEP_MSGS = 2;

const KINDS: IfOption<DraftStep["kind"]>[] = [
  { value: "reply", label: "Reply" },
  { value: "ppv", label: "Paid PPV" },
];
/** Icon-only link actions: muted until hovered, thumb-sized below md. */
const ICON_ACTION = "w-8 text-muted hover:text-fg disabled:hover:text-muted max-md:h-10 max-md:w-10";

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
  const id = useId();
  return (
    <div className="space-y-4 rounded-md border border-border p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-medium text-fg">Step {index + 1}</span>
          <span className="rounded bg-accent/10 px-1.5 text-[12px] text-accent">{isPpv ? "paid PPV" : "reply"}</span>
        </div>
        <div className="flex items-center">
          <IfButton variant="link" icon={ChevronUp} aria-label="Move up" title="Move up"
            onClick={() => onMove(-1)} disabled={index === 0} className={ICON_ACTION} />
          <IfButton variant="link" icon={ChevronDown} aria-label="Move down" title="Move down"
            onClick={() => onMove(1)} disabled={index === total - 1} className={ICON_ACTION} />
          <IfButton variant="link" icon={Trash2} aria-label="Remove step" title="Remove step"
            onClick={onRemove} className={`${ICON_ACTION} hover:text-err`} />
        </div>
      </div>

      <IfSegmented aria-label="Step type" options={KINDS} value={step.kind} onChange={(kind) => onPatch({ kind })} />

      {/* Poll intervals (the walker waits on a PPV step's cadence too). */}
      <div>
        <IfLabel htmlFor={`${id}-every`}>Check for a reply every</IfLabel>
        <IfInput
          id={`${id}-every`}
          value={step.intervals}
          onChange={(e) => onPatch({ intervals: e.target.value })}
          placeholder="2, 4, 10"
          className="w-full"
        />
        <IfHelp>minutes, comma-separated · blank = 2, 4, 10</IfHelp>
      </div>

      {/* PPV: price + locked-text. MEDIA is per-model → set in the Media pane. */}
      {isPpv && (
        <>
          <div>
            <IfLabel htmlFor={`${id}-price`}>Price (USD)</IfLabel>
            <IfInput
              id={`${id}-price`}
              type="number"
              min={0}
              value={step.price}
              onChange={(e) => onPatch({ price: e.target.value })}
              placeholder="default $24"
              className="w-48"
            />
            <IfHelp>whole dollars</IfHelp>
            <IfHelp className="flex items-center gap-1.5">
              <ImageIcon aria-hidden className="h-3.5 w-3.5 shrink-0" />
              Media is set per model in the funnel&apos;s Media action.
            </IfHelp>
          </div>
          <IfSwitch label="Lock the text too (fan must pay to read)" checked={step.lockedText}
            onChange={(lockedText) => onPatch({ lockedText })} className="flex" />
        </>
      )}

      {/* Copy: AI-generate toggle, then either a prompt or a variant pool. */}
      <IfSwitch label={`Generate the ${isPpv ? "sales copy" : "reply"} with AI`} checked={step.generate}
        onChange={(generate) => onPatch({ generate })} className="flex" />

      {step.generate ? (
        <div>
          <IfLabel htmlFor={`${id}-prompt`}>Prompt</IfLabel>
          <IfTextArea
            id={`${id}-prompt`}
            value={step.prompt}
            onChange={(e) => onPatch({ prompt: e.target.value })}
            rows={2}
            placeholder="e.g. tease the PPV and create urgency…"
          />
          <IfHelp>Guides the AI; blank uses the default persona.</IfHelp>
        </div>
      ) : (
        <div>
          <IfLabel>{isPpv ? "Sales copy" : "Reply"} variants</IfLabel>
          <div className="space-y-2">
            {step.messages.map((m, mi) => (
              <div key={mi} className="flex items-start gap-1">
                <IfTextArea
                  value={m}
                  onChange={(e) => onMsgChange(mi, e.target.value)}
                  rows={2}
                  placeholder={step.messages.length > 1 ? `Variant ${mi + 1}` : "Message…"}
                  className="flex-1"
                />
                {step.messages.length > 1 && (
                  <IfButton variant="link" icon={X} aria-label="Remove this variant" title="Remove this variant"
                    onClick={() => onMsgRemove(mi)} className={`${ICON_ACTION} hover:text-err`} />
                )}
              </div>
            ))}
          </div>
          <IfHelp>One is sent at random; the first 2 are used.</IfHelp>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
            <IfButton variant="link" onClick={onMsgAdd}>
              Add variant{step.messages.length > 1 ? ` (${step.messages.length})` : ""}
            </IfButton>
            {/* reply_mass_funnel sends static messages[:2] only. */}
            <ImportCaptionsButton current={step.messages} max={FUNNEL_STEP_MSGS} onImport={onMsgImport} />
          </div>
        </div>
      )}
    </div>
  );
}
