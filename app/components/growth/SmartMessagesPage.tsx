"use client";

/**
 * Growth > Smart Messages: the page frame, laid out from the Layout capture
 * (`docs/infloww-layouts/growth-smart-messages.md`; labels and sources in
 * `smartMessagesControls`). Phase 2b of
 * docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md builds it,
 * and Phase 2 (phase-02-growth-pages.md) fills its Automated Messages tab.
 * Page-parity ticket 08 puts it on Infloww's legacy primitives
 * (`@/components/ui/infloww`): full bleed, the 48px header, `IfTabs`.
 *
 * - The header row (`InflowwPageHeader`): the page title, the creator select
 *   24px beside it (#4), and at the row's right the bundle's right box (#18).
 *   On Automated Messages the select picks the Creator every read and write of
 *   that tab uses; on Mass Messages it is Not wired, as the panels there list
 *   every active Creator and take no Creator. The right box holds "Learn" (Not
 *   wired: the bundle opens Infloww's own blog) and "New Message", which opens the one
 *   "Create message" pop-up (`CreateMessagePopUp`), whose Automated messages
 *   section holds the Triggers' cards (`AutomatedMessageCards`): "Nudge" and
 *   "Subscriber welcome" open the Nudge and Delayed welcome rows' editors on
 *   the select's Creator, every other is Not wired.
 * - "Automated Messages" (`AutomatedMessagesTab`) before "Mass Messages", and
 *   the default, as the bundle opens Automated Messages first when it is shown
 *   (#7).
 *
 * `?tab=mass` opens Mass Messages, and so does `?tab=scheduled`: the old
 * `/settings?tab=mass` and `/settings?tab=scheduled` redirects pass their query
 * through (next.config.ts), so both must still land on mass messages now that
 * Automated Messages comes first.
 */

import { useState, type ReactNode } from "react";
import { Plus } from "lucide-react";

import { IfButton, IfCreatorSelect, IfLearn, IfSelect, IfTabs, InflowwPageHeader } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useTabParam } from "@/hooks/useTabParam";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

import AutomatedMessagesTab, { AutomatedEditor, AutomatedMessageCards, type WiredTrigger } from "./AutomatedMessagesTab";
import CreateMessage from "./CreateMessagePopUp";
import MassMessagesSection from "./MassMessagesSection";
import { SM, type CapturedControl } from "./smartMessagesControls";

type TabKey = "automated" | "mass";
type ParentTab = { key: TabKey; control: CapturedControl; body: ReactNode };

// `?tab=` values: each tab's key, and `scheduled`, an alias of Mass Messages.
const LOOKUP: Record<string, TabKey> = { automated: "automated", mass: "mass", scheduled: "mass" };

/** The header's creator select: 160px, the avatar alone below `sm` (ticket 00's phone rule). */
const CHIP = "w-14 sm:w-[160px]";

export default function SmartMessagesPage({
  automatedMessageCards,
}: {
  /** The Create message pop-up's "Automated messages" section, placed after
   *  "Mass messages"; by default the Triggers' cards (`AutomatedMessageCards`). */
  automatedMessageCards?: ReactNode;
}) {
  const accounts = useActiveAccounts();
  // The select's pick, else the first active Creator.
  const [picked, setPicked] = useState<string | null>(null);
  const accountId = picked ?? accounts[0]?.id ?? null;

  const tabs: ParentTab[] = [
    { key: "automated", control: SM.tabAutomated, body: <AutomatedMessagesTab accountId={accountId} /> },
    { key: "mass", control: SM.tabMass, body: <MassMessagesSection /> },
  ];
  const [tab, setTab] = useState<TabKey>("automated");
  const [creating, setCreating] = useState(false);
  // The pop-up's wired cards open their row's editor, on the select's Creator.
  const [opened, setOpened] = useState<WiredTrigger | null>(null);

  // useTabParam takes a type predicate; `in` is the whole check.
  useTabParam("tab", (v): v is string => v in LOOKUP, (v) => setTab(LOOKUP[v]));

  const current = tabs.find((t) => t.key === tab)!;
  return (
    <div className="flex min-h-full min-w-0 flex-col">
      <InflowwPageHeader
        title={SM.title.label}
        // The creator select (#4), 24px after the title: the picked Creator on
        // Automated Messages; on Mass Messages "All creators", ours, Not wired.
        extra={tab === "automated" ? (
          accounts.length === 0 ? (
            // "No creators" is the house's empty select, not the bundle's.
            <span title={EXTRA_LABEL} className="inline-flex">
              <IfCreatorSelect accounts={[]} value={null} onChange={() => {}} disabled className={CHIP} />
            </span>
          ) : (
            <IfCreatorSelect accounts={accounts} value={accountId} onChange={setPicked} className={CHIP} />
          )
        ) : (
          <span title="not wired" className="inline-flex">
            <IfSelect aria-label="Creator" disabled value="all" onChange={() => {}}
              options={[{ value: "all", label: "All creators" }]} className="w-[120px] sm:w-[160px]" />
          </span>
        )}
        actions={(
          <>
            {/* Learn (#11, #12-#14): the book and 14px M1 text, Not wired. */}
            <IfLearn><span className="max-sm:sr-only">{SM.learn.label}</span></IfLearn>
            {/* New Message (#15), 16px from Learn (#16); its icon alone below `sm`. */}
            <IfButton variant="primary" icon={Plus} onClick={() => setCreating(true)} className="max-sm:px-2.5">
              <span className="max-sm:sr-only">{SM.newMessage.label}</span>
            </IfButton>
          </>
        )}
      />

      <IfTabs
        aria-label="Smart Messages"
        idPrefix="sm"
        tabs={tabs.map((t) => ({ value: t.key, label: t.control.label }))}
        value={tab}
        onChange={setTab}
      />
      <div key={current.key} role="tabpanel" id={`sm-panel-${current.key}`} aria-labelledby={`sm-tab-${current.key}`}
        className="min-w-0">
        {current.body}
      </div>

      <CreateMessage
        open={creating}
        onClose={() => setCreating(false)}
        accountId={accountId}
        automatedMessageCards={automatedMessageCards ?? <AutomatedMessageCards onOpen={setOpened} accountId={accountId} />}
      />
      {opened && <AutomatedEditor trigger={opened} accountId={accountId} onClose={() => setOpened(null)} />}
    </div>
  );
}
