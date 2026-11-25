"use client";


import { AiKeyNotice } from "@/components/AiKeyNotice";
import { NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { MassFunnelsTab } from "@/components/automations/FunnelEditor";
import { UnconfirmedSends } from "@/components/automations/UnconfirmedSends";
import { PageFrame } from "@/components/shell/PageFrame";

const TITLE = "Auto Funnel";

export default function AutoFunnelPage() {
  const { accountId, creators, loading } = useAutomationCreator();

  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}><NoCreator loading={loading} /></PageFrame>;
  }
  return (
    <MassFunnelsTab
      accountId={accountId}
      frame={(actions, body) => (
        <PageFrame title={TITLE} creators={creators} actions={actions}>
          <div className="space-y-4">
            <AiKeyNotice accountId={accountId} kinds={["reply_mass_funnel"]} />
            <UnconfirmedSends key={accountId} accountId={accountId} />
            {body}
          </div>
        </PageFrame>
      )}
    />
  );
}
