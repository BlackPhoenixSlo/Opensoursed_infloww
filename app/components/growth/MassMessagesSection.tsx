"use client";


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

const PILL = "h-7 px-4 rounded-[50px] mr-4 border text-[14px]";

export default function MassMessagesSection() {
  const [child, setChild] = useState<"priority" | "of">("of");
  const pill = (on: boolean) => cn(PILL, on ? "border-transparent bg-accent text-white" : "border-border text-fg");
  return (
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

      <div role="tabpanel" id={OF_PANEL_ID} aria-labelledby={OF_TAB_ID} hidden={child !== "of"} className="space-y-5">
        <MassMessagesTab />
      </div>
    </IfBody>
  );
}

export function MassAutoUnsendSection({ accountId, onPick }: {
  accountId: string | null;
  onPick: (accountId: string) => void;
}) {
  const accounts = useActiveAccounts();
  return (
    <CreatorRail creators={{ accounts, value: accountId, onChange: onPick }} top="96px">
      <IfBody className="pb-6"><AutoUnsendCard accountId={accountId} /></IfBody>
    </CreatorRail>
  );
}

export function ScheduledSection() {
  return <IfBody className="pb-6"><ScheduledTab /></IfBody>;
}
