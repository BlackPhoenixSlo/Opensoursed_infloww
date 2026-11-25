"use client";


import { AiKeyNotice } from "@/components/AiKeyNotice";
import { FormBlock, NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { HeaderSwitch } from "@/components/automations/HeaderSwitch";
import { OnboardRecentCard } from "@/components/automations/OnboardRecentCard";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IfLearn } from "@/components/ui/infloww";
import { useAutomationRules, useSwitchKind } from "@/hooks/useAutomations";

const TITLE = "Gen-Info";
const KIND = "gen_info";

const LEARN = (
  <IfLearn tip={<>
    It lands on OnlyFans as <b>Name/City,Country/Age/Job</b>, for example <code>Garrett/Delta,Canada/30/Paramedic</code>.
    Only what he actually said is used; unknown parts are left out. A fan is (re)profiled once he has sent at least 8
    new messages, so a quiet fan costs nothing. It uses the AI (it spends credits); fans never see the nickname.
  </>}>
    <span className="max-sm:sr-only">Learn</span>
  </IfLearn>
);

export default function GenInfoPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators} actions={LEARN}><NoCreator loading={loading} /></PageFrame>;
  }
  // Keyed, so a switch in flight can never land on the next creator.
  return <GenInfo key={accountId} accountId={accountId} creators={creators} />;
}

function GenInfo({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const rulesQ = useAutomationRules(accountId);
  const switchKind = useSwitchKind(accountId);
  const rules = (rulesQ.data ?? []).filter((r) => r.kind === KIND);
  const rule = rules.find((r) => r.is_enabled) ?? rules[0] ?? null;
  const on = rules.some((r) => r.is_enabled);
  const generated = rule?.last_run?.stats?.generated;

  const actions = (
    <>
      {LEARN}
      <HeaderSwitch label={TITLE} checked={on} disabled={!rulesQ.isSuccess} loading={switchKind.isPending}
        onChange={(enable) => switchKind.mutate({ kind: KIND, enable })} />
    </>
  );

  return (
    <PageFrame title={TITLE} creators={creators} actions={actions}>
      <div className="max-w-[720px] space-y-8">
        <AiKeyNotice accountId={accountId} kinds={[KIND]} />

        <div className="space-y-2">
          <p className="text-[14px] text-fg">
            Every day, reads your fans&apos; chats and fills their nickname with name / city / age / job.
          </p>
          {rule?.last_run?.completed_at && (
            <p className="text-[12px] text-muted">
              Last run {new Date(rule.last_run.completed_at).toLocaleString()}
              {typeof generated === "number" && ` · ${generated} fan${generated === 1 ? "" : "s"} updated`}
            </p>
          )}
          {rulesQ.isLoadingError && (
            <p className="text-[12px] text-err">
              Couldn&apos;t read this creator&apos;s automations, so this can&apos;t say
              whether Gen-Info is on.
            </p>
          )}
          {switchKind.isError && (
            <p className="text-[12px] text-err">
              {switchKind.error?.message || "Couldn't switch Gen-Info."} Try again.
            </p>
          )}
        </div>

        <FormBlock title="Old fans">
          <OnboardRecentCard
            accountId={accountId}
            pushToOf
            action="Also run on old fans"
            intro={
              <>
                Optional, once: fans who were already in the account before the AI.
                Profiles them from their existing chat history and fills their
                nickname now, without waiting for new messages. They won&apos;t get
                Get to know fans chats.
              </>
            }
          />
        </FormBlock>
      </div>
    </PageFrame>
  );
}
