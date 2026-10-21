"use client";

/**
 * MassMessagesSection — the body of Smart Messages' "Mass Messages" tab, laid
 * out from the Layout capture (`docs/infloww-layouts/growth-smart-messages.md`,
 * items #55 to #102; docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md).
 *
 * - The child pills, in the capture's order. "OF mass messages" opens first
 *   (#58); "Priority mass messages" lists one Creator's Priority mass message
 *   runs with their progress, Cancel and Resume (`PriorityMassRuns`).
 * - Under "OF mass messages": the capture's OF filter bar, every control Not
 *   wired (our list keeps its own filters), then today's sent history with its
 *   bulk unsend and the hourly Auto-unsend card (`MassMessagesTab`, mounted
 *   unchanged), because our sends are OF's `messages/queue`, the general inbox.
 * - The scheduled queue (`ScheduledTab`, unchanged) as its own list after the
 *   child, never under a send type: it holds direct and mass sends together.
 *   An Inflowwww extra.
 *
 * Takes no Creator: each panel picks its Creators (`useActiveAccounts`).
 */

import { useState } from "react";

import MassMessagesTab from "@/components/settings/MassMessagesTab";
import ScheduledTab from "@/components/settings/ScheduledTab";
import { IfBody, IfButton, IfInput, IfRangePicker } from "@/components/ui/infloww";
import { ExtraTag } from "@/components/ui/primitives";
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

/** Our extra lists' headings: a legacy section title, 16 / 600 T1, 24px above. */
function ExtraSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
        <ExtraTag />
      </div>
      {children}
    </section>
  );
}

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
        {/* The OF filter bar (#66, #73, #76, #77, #79), all 32px: fields 12px
         *  apart at the sides and 16px from the top (#74), labels 8px from
         *  their field (#75), buttons 8px apart (#78). The search box is 230px
         *  (#66), Sending Date antd's 250px range. Every control Not wired. */}
        <div className="flex flex-wrap items-center">
          <IfInput
            search
            aria-label={SM.search.label}
            placeholder={SM.search.label}
            disabled
            title="not wired"
            className="mx-3 mt-4 w-[230px] has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 has-[:disabled]:hover:border-border"
          />
          <div className="mx-3 mt-4 flex items-center gap-2">
            <label htmlFor="sm-mass-sending-date" className="text-[14px] text-fg">{SM.sendingDate.label}</label>
            <IfRangePicker id="sm-mass-sending-date" disabled title="not wired" />
          </div>
          <div className="mx-3 mt-4 flex items-center gap-2">
            <IfButton disabled title="not wired">{SM.reset.label}</IfButton>
            <IfButton variant="primary" disabled title="not wired">{SM.searchButton.label}</IfButton>
            <IfButton disabled title="not wired">{SM.exportButton.label}</IfButton>
          </div>
        </div>
        <MassMessagesTab />
      </div>

      <ExtraSection title="Every scheduled send, direct and mass">
        <ScheduledTab />
      </ExtraSection>
    </IfBody>
  );
}
