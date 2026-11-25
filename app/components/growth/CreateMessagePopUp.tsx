"use client";


import { useCanOrFallback } from "@/hooks/useCan";
import { createContext, useContext, useState, type ReactNode } from "react";

import { LazyMassMessageComposer } from "@/components/compose/LazyMassMessageComposer";
import { IfButton, IfModal } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { PriorityMassComposer } from "./PriorityMass";
import { SM } from "./smartMessagesControls";

type ComposerMode = "standard" | "online" | "priority";

export default function CreateMessage({
  open, onClose, automatedMessageCards, accountId = null,
}: {
  open: boolean;
  onClose: () => void;
  accountId?: string | null;
  automatedMessageCards?: ReactNode;
}) {
  const [composer, setComposer] = useState<{ mode: ComposerMode; accountId: string | null } | null>(null);
  const massAllowed = useCanOrFallback(accountId, "mass_message");
  return (
    <>
      {open && (
        <CreateMessagePopUp
          massAllowed={massAllowed}
          automatedMessageCards={automatedMessageCards}
          onClose={onClose}
          onNext={(mode) => {
            onClose();
            setComposer({ mode, accountId });
          }}
        />
      )}
      {composer?.mode === "priority" && <PriorityMassComposer open initialAccountId={composer.accountId} onClose={() => setComposer(null)} />}
      {composer && composer.mode !== "priority" && (
        <LazyMassMessageComposer
          mode={composer.mode} labelExtras forcedAccountId={composer.accountId ?? undefined} onClose={() => setComposer(null)}
        />
      )}
    </>
  );
}

type Pick = { key: string; next: () => void };
const PickContext = createContext<{ picked: string | null; pick: (p: Pick) => void } | null>(null);

export function AutomatedCard({
  title, desc, tag, onNext, refusal,
}: {
  title: string;
  desc: string;
  tag?: string;
  onNext?: () => void;
  refusal?: string | null;
}) {
  const ctx = useContext(PickContext);
  const live = !!onNext && !refusal;
  return (
    <PopUpCard
      title={title}
      desc={desc}
      tag={tag}
      picked={live && ctx?.picked === title}
      onPick={() => { if (live && onNext) ctx?.pick({ key: title, next: onNext }); }}
      disabled={!live}
      refusal={refusal ?? undefined}
    />
  );
}

function PopUpCard({
  title, desc, tag, picked, onPick, disabled, extra, refusal,
}: {
  title: string;
  desc?: string;
  tag?: string;
  picked: boolean;
  onPick: () => void;
  disabled?: boolean;
  extra?: boolean;
  refusal?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={picked}
      disabled={disabled}
      title={refusal ?? (disabled ? "not wired" : extra ? EXTRA_LABEL : undefined)}
      onClick={onPick}
      className={cn(
        "flex flex-col items-start gap-1 rounded-lg border p-3 text-left text-sm transition-colors",
        picked ? "border-accent bg-accent/10" : "border-border hover:border-border-light",
        "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border",
      )}
    >
      <span className="flex items-center gap-2 font-medium">
        <span>{title}</span>
        {extra && <ExtraTag />}
      </span>
      {desc && <span className="text-xs text-fg-dim">{desc}</span>}
      {tag && <span className="rounded px-1.5 py-0.5 text-[11px] bg-accent/15 text-accent">{tag}</span>}
      {refusal && <span className="text-xs text-warn">{refusal}</span>}
    </button>
  );
}

function PopUpSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h3 id={id} className="text-[14px] font-semibold text-fg">{title}</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
    </section>
  );
}

function CreateMessagePopUp({
  automatedMessageCards, massAllowed, onClose, onNext,
}: {
  massAllowed: boolean;
  automatedMessageCards?: ReactNode;
  onClose: () => void;
  onNext: (mode: ComposerMode) => void;
}) {
  const [pick, setPick] = useState<Pick | { key: ComposerMode; mode: ComposerMode } | null>(null);
  const picked = pick?.key ?? null;
  const pickMode = (mode: ComposerMode) => setPick({ key: mode, mode });
  const next = pick && ("mode" in pick ? (massAllowed ? () => onNext(pick.mode) : null) : pick.next);
  const pickAutomated = (p: Pick) => setPick({ key: p.key, next: () => { onClose(); p.next(); } });
  return (
    <IfModal
      width={722}
      title={SM.popUpTitle.label}
      onClose={onClose}
      footer={(
        <>
          <IfButton onClick={onClose}>{SM.popUpCancel.label}</IfButton>
          <IfButton variant="primary" disabled={!next} onClick={next ?? undefined}>{SM.popUpNext.label}</IfButton>
        </>
      )}
    >
      <div className="space-y-6">
        {massAllowed && (
          <PopUpSection id="sm-create-mass" title={SM.popUpMass.label}>
            <PopUpCard title={SM.cardPriority.label} desc={SM.cardPriority.desc} picked={picked === "priority"} onPick={() => pickMode("priority")} />
            <PopUpCard title={SM.cardOf.label} desc={SM.cardOf.desc} picked={picked === "standard"} onPick={() => pickMode("standard")} />
            <PopUpCard title="Message online fans" picked={picked === "online"} onPick={() => pickMode("online")} extra />
          </PopUpSection>
        )}
        {automatedMessageCards && (
          <PickContext.Provider value={{ picked, pick: pickAutomated }}>
            <PopUpSection id="sm-create-automated" title={SM.popUpAutomated.label}>
              {automatedMessageCards}
            </PopUpSection>
          </PickContext.Provider>
        )}
      </div>
    </IfModal>
  );
}
