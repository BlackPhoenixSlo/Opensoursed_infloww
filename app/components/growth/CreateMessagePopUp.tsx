"use client";

/**
 * Smart Messages' one "Create message" pop-up (#103 to #111 of
 * `docs/infloww-layouts/growth-smart-messages.md`; labels and sources in
 * `smartMessagesControls`), opened by the page's New Message, and the mass
 * composer it opens. Phase 2b of
 * docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md builds it;
 * it lives apart from `SmartMessagesPage` so that the page imports no mass
 * component directly (phase-02-growth-pages.md, "Mass tabs on Smart Messages").
 *
 * Its Mass messages section holds "Priority mass message" (one direct message
 * per fan, `PriorityMassComposer`), "OF mass message" (the mass composer's
 * standard mode) and "Message online fans" (its online mode, an Inflowwww
 * extra). A card picks, Next opens it, as the bundle's `xConfirmDisabled`
 * waits for a pick. Its Automated messages section is Phase 2's slot
 * (`automatedMessageCards`), after Mass messages as the bundle renders them;
 * empty, it renders nothing. The bundle puts "Start from scratch" and its
 * template line inside that section, so they are Phase 2's too. A card in the
 * slot (`AutomatedCard`) joins the same one pick, so Next opens whichever card
 * was picked last, Mass or Automated, as the bundle's one `qt` pick does
 * (index.9f50f370.js @14711600 onwards).
 */

import { createContext, useContext, useState, type ReactNode } from "react";

import { LazyMassMessageComposer } from "@/components/compose/LazyMassMessageComposer";
import { IfButton, IfModal } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

import { PriorityMassComposer } from "./PriorityMass";
import { SM } from "./smartMessagesControls";

/** The mass composer's modes, and "priority" for the Priority mass composer. */
type ComposerMode = "standard" | "online" | "priority";

/** The pop-up while `open`, and the composer its Next opens. */
export default function CreateMessage({
  open, onClose, automatedMessageCards, accountId = null,
}: {
  open: boolean;
  onClose: () => void;
  /** The page header's Creator: the Priority mass composer's "Post as" on open. */
  accountId?: string | null;
  /** Phase 2's cards for the "Automated messages" section, placed after "Mass messages". */
  automatedMessageCards?: ReactNode;
}) {
  const [composer, setComposer] = useState<ComposerMode | null>(null);
  return (
    <>
      {open && (
        <CreateMessagePopUp
          automatedMessageCards={automatedMessageCards}
          onClose={onClose}
          onNext={(mode) => { onClose(); setComposer(mode); }}
        />
      )}
      {composer === "priority" && <PriorityMassComposer open initialAccountId={accountId} onClose={() => setComposer(null)} />}
      {composer && composer !== "priority" && (
        <LazyMassMessageComposer open mode={composer} labelExtras onClose={() => setComposer(null)} />
      )}
    </>
  );
}

/** The pop-up's one pick, shared with the cards in the Automated messages
 *  slot: the picked card's key, and what Next does for it. */
type Pick = { key: string; next: () => void };
const PickContext = createContext<{ picked: string | null; pick: (p: Pick) => void } | null>(null);

/** A card of the Automated messages section. Wired (`onNext`), a click picks
 *  it and Next closes the pop-up and calls `onNext`; without `onNext` it is Not
 *  wired: `disabled`, `title="not wired"`, and it picks nothing. With a
 *  `refusal` (the bundle's free-page message) it is disabled and says why. */
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

/** One card of the pop-up: its title, second line and tag, as the bundle's
 *  card renders them, picked with a click. */
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

/** The one "Create message" pop-up (#103), 722px wide. */
function CreateMessagePopUp({
  automatedMessageCards, onClose, onNext,
}: {
  automatedMessageCards?: ReactNode;
  onClose: () => void;
  onNext: (mode: ComposerMode) => void;
}) {
  const [pick, setPick] = useState<Pick | null>(null);
  const picked = pick?.key ?? null;
  const pickMode = (mode: ComposerMode) => setPick({ key: mode, next: () => onNext(mode) });
  // An Automated card's Next closes the pop-up first, as a Mass card's does.
  // Its key is its title, which no Mass card's mode equals.
  const pickAutomated = (p: Pick) => setPick({ key: p.key, next: () => { onClose(); p.next(); } });
  return (
    // antd's modal at the bundle's 722px (`xTitle:"Create message"`).
    <IfModal
      width={722}
      title={SM.popUpTitle.label}
      onClose={onClose}
      footer={(
        // XModal's footer: Cancel then the confirm, right-aligned
        // (index.9f50f370.js @6780736, @6780813).
        <>
          <IfButton onClick={onClose}>{SM.popUpCancel.label}</IfButton>
          <IfButton variant="primary" disabled={!pick} onClick={() => pick?.next()}>{SM.popUpNext.label}</IfButton>
        </>
      )}
    >
      <div className="space-y-6">
        <PopUpSection id="sm-create-mass" title={SM.popUpMass.label}>
          <PopUpCard title={SM.cardPriority.label} desc={SM.cardPriority.desc} picked={picked === "priority"} onPick={() => pickMode("priority")} />
          <PopUpCard title={SM.cardOf.label} desc={SM.cardOf.desc} picked={picked === "standard"} onPick={() => pickMode("standard")} />
          {/* Ours, after the bundle's two. */}
          <PopUpCard title="Message online fans" picked={picked === "online"} onPick={() => pickMode("online")} extra />
        </PopUpSection>
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
