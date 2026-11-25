"use client";


import { useState, type ReactNode } from "react";
import { Plus } from "lucide-react";

import { CreatorRail } from "@/components/shell/CreatorRail";
import { IfButton, IfLearn, IfTabs, InflowwPageHeader } from "@/components/ui/infloww";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useTabParam } from "@/hooks/useTabParam";
import { SMART_MESSAGES_TABS, type SmartMessagesTab as TabKey } from "@/lib/pageTabs";

import AutomatedMessagesTab, { AutomatedEditor, AutomatedMessageCards, type WiredTrigger } from "./AutomatedMessagesTab";
import CreateMessage from "./CreateMessagePopUp";
import MassMessagesSection, { MassAutoUnsendSection, ScheduledSection } from "./MassMessagesSection";
import { SM } from "./smartMessagesControls";

const LOOKUP: Record<string, TabKey> = Object.fromEntries(SMART_MESSAGES_TABS.map((t): [string, TabKey] => [t.key, t.key]));

const LEARN_TIP = <>Automated messages go out on a trigger: a fan coming online, subscribing, buying, a sub nearing
  its end, expiring or renewing, a birthday. Mass messages go to the fans you pick, now or at a set time; Mass auto unsend
  takes them back after a while. Scheduled lists everything queued.</>;

export default function SmartMessagesPage({
  automatedMessageCards,
}: {
  automatedMessageCards?: ReactNode;
}) {
  const accounts = useActiveAccounts();
  const [picked, setPicked] = useState<string | null>(null);
  // One pick for every creator column and New Message, so a composer never opens on a Creator the page isn't showing.
  const accountId = accounts.some((a) => a.id === picked) ? picked : accounts[0]?.id ?? null;

  const bodies: Record<TabKey, ReactNode> = {
    automated: (
      <CreatorRail creators={{ accounts, value: accountId, onChange: setPicked }} top="96px">
        <AutomatedMessagesTab accountId={accountId} />
      </CreatorRail>
    ),
    mass: <MassMessagesSection />,
    unsend: <MassAutoUnsendSection accountId={accountId} onPick={setPicked} />,
    scheduled: <ScheduledSection />,
  };
  const [tab, setTab] = useState<TabKey>("automated");
  const [creating, setCreating] = useState(false);
  const [opened, setOpened] = useState<WiredTrigger | null>(null);

  useTabParam("tab", (v): v is string => Object.hasOwn(LOOKUP, v), (v) => setTab(LOOKUP[v]));

  return (
    <div className="flex min-h-full min-w-0 flex-col">
      <InflowwPageHeader
        title={SM.title.label}
        actions={(
          <>
            <IfLearn tip={LEARN_TIP}><span className="max-sm:sr-only">{SM.learn.label}</span></IfLearn>
            <IfButton variant="primary" icon={Plus} onClick={() => setCreating(true)} className="max-sm:px-2.5">
              <span className="max-sm:sr-only">{SM.newMessage.label}</span>
            </IfButton>
          </>
        )}
      />

      <IfTabs
        aria-label="Smart Messages"
        idPrefix="sm"
        tabs={SMART_MESSAGES_TABS.map((t) => ({ value: t.key, label: t.label }))}
        value={tab}
        onChange={setTab}
      />
      <div key={tab} role="tabpanel" id={`sm-panel-${tab}`} aria-labelledby={`sm-tab-${tab}`}
        className="flex min-w-0 flex-1 flex-col">
        {bodies[tab]}
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
