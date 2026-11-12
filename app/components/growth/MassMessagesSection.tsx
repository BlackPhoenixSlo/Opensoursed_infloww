"use client";

/**
 * MassMessagesSection — the body of Smart Messages' "Mass Messages" tab, laid
 * out from the Layout capture (`docs/infloww-layouts/growth-smart-messages.md`,
 * items #55 to #102; docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md).
 *
 * - The child pills, in the capture's order. "OF mass messages" opens first
 *   (#58); "Priority mass messages" lists one Creator's Priority mass message
 *   runs with their progress, Cancel and Resume (`PriorityMassRuns`).
 * - Under "OF mass messages": the capture's OF filter bar over the sent
 *   history with its bulk unsend (`MassMessagesTab`, which owns both, so the
 *   bar's search and Sending Date filter the list), because our sends are OF's
 *   `messages/queue`, the general inbox. The hourly Auto-unsend card (one
 *   Creator at a time, picked in a creator column) and the
 *   scheduled queue are their own Smart Messages tabs, bodies below
 *   (`MassAutoUnsendSection`, `ScheduledSection`); Inflowwww extras.
 *
 * Takes no Creator: each panel picks its Creators (`useActiveAccounts`).
 */

import { useState } from "react";

import { CreatorRail } from "@/components/shell/CreatorRail";
import { AutoUnsendCard } from "@/components/settings/AutoUnsendPanel";
import MassMessagesTab from "@/components/settings/MassMessagesTab";
import ScheduledTab from "@/components/settings/ScheduledTab";
import { IfBody } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { cn } from "@/lib/utils";

import { PriorityMassRuns } from "./PriorityMass";
import { SM } from "./smartMessagesControls";

const OF_TAB_ID = "sm-child-of";
const OF_PANEL_ID = "sm-child-of-panel";
const PRIORITY_TAB_ID = "sm-child-priority";
const PRIORITY_PANEL_ID = "sm-child-priority-panel";

/** A child pill (#59 to #65): 28px high, 0 16px padding, 50px radius, 16px
 *  to the next, 14px; the active pill is filled and borderless. */
const PILL = "h-7 px-4 rounded-[50px] mr-4 border text-[14px]";

export default function MassMessagesSection() {
  const [child, setChild] = useState<"priority" | "of">("of");
  const pill = (on: boolean) => cn(PILL, on ? "border-transparent bg-accent text-white" : "border-border text-fg");
  return (
    // #55: the tab body's 16px 24px 24px padding.
    <IfBody className="pb-6">
      <div role="tablist" aria-label={SM.tabMass.label} className="flex items-center">
        <button
          type="button"
          role="tab"
          id={PRIORITY_TAB_ID}
          aria-selected={child === "priority"}
          aria-controls={PRIORITY_PANEL_ID}
          onClick={() => setChild("priority")}
          className={pill(child === "priority")}
        >
          {SM.childPriority.label}
        </button>
        <button
          type="button"
          role="tab"
          id={OF_TAB_ID}
          aria-selected={child === "of"}
          aria-controls={OF_PANEL_ID}
          onClick={() => setChild("of")}
          className={pill(child === "of")}
        >
          {SM.childOf.label}
        </button>
      </div>

      {child === "priority" && (
        <div role="tabpanel" id={PRIORITY_PANEL_ID} aria-labelledby={PRIORITY_TAB_ID}>
          <PriorityMassRuns />
        </div>
      )}

      {/* space-y-5: the gap today's page puts between its blocks, for the
       *  panels of ours mounted here (the capture has no value for elements
       *  it lacks). */}
      <div role="tabpanel" id={OF_PANEL_ID} aria-labelledby={OF_TAB_ID} hidden={child !== "of"} className="space-y-5">
        <MassMessagesTab />
      </div>
    </IfBody>
  );
}

/** The "Mass Auto Unsend Messages" tab: the creator column (`CreatorRail`, as Automated Messages') picks the
 *  Creator whose own hourly Auto-unsend form shows; each Creator keeps its own rule and its own Save. */
export function MassAutoUnsendSection() {
  const accounts = useActiveAccounts();
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = accounts.some((a) => a.id === picked) ? picked : accounts[0]?.id ?? null;
  return (
    <CreatorRail creators={{ accounts, value: accountId, onChange: setPicked, noAll: true }} top="96px">
      <IfBody className="pb-6"><AutoUnsendCard accountId={accountId} /></IfBody>
    </CreatorRail>
  );
}

/** The "Scheduled" tab: every queued send, direct and mass. */
export function ScheduledSection() {
  return <IfBody className="pb-6"><ScheduledTab /></IfBody>;
}
