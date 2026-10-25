"use client";

/**
 * My Automations > Gen-Info (ours; Infloww has no counterpart). The daily
 * `gen_info` automation (service/automations/gen_info.py) on a page of its own:
 * read each fan's chat, work out who he is, and write it into his OnlyFans
 * nickname as "Name/City,Country/Age/Job" (gen_info pushes the nickname and the
 * Fan notes itself, `_sync_of_fan_info`; nothing else has to be on).
 *
 * The switch is `useSwitchKind`, so the server picks the row, its daily cadence
 * and its name (automation_rules_api._CATALOG["gen_info"]); this page owns no
 * other knob. Under it, a one-shot for the fans already in the account before the
 * AI: `process_old_fans` over the N most recent (`OnboardRecentCard`).
 *
 * Restored from the short-lived Fan info page (b60d9839), pointed at gen_info.
 */


import { AiKeyNotice } from "@/components/AiKeyNotice";
import { FormBlock, NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import { OnboardRecentCard } from "@/components/automations/OnboardRecentCard";
import type { CreatorPick } from "@/components/shell/CreatorRail";
import { PageFrame } from "@/components/shell/PageFrame";
import { IfSwitch } from "@/components/ui/infloww";
import { useAutomationRules, useSwitchKind } from "@/hooks/useAutomations";

const TITLE = "Gen-Info";
const KIND = "gen_info";

export default function GenInfoPage() {
  const { accountId, creators, loading } = useAutomationCreator();
  if (!accountId) {
    return <PageFrame title={TITLE} creators={creators}>{!loading && <NoCreator />}</PageFrame>;
  }
  // Keyed, so a switch in flight can never land on the next creator.
  return <GenInfo key={accountId} accountId={accountId} creators={creators} />;
}

function GenInfo({ accountId, creators }: { accountId: string; creators: CreatorPick }) {
  const rulesQ = useAutomationRules(accountId);
  const switchKind = useSwitchKind(accountId);
  // "On" = a running gen_info row, the one the server wakes. No rows read yet
  // → the switch is disabled rather than claiming "off".
  const rules = (rulesQ.data ?? []).filter((r) => r.kind === KIND);
  const rule = rules.find((r) => r.is_enabled) ?? rules[0] ?? null;
  const on = rules.some((r) => r.is_enabled);
  const generated = rule?.last_run?.stats?.generated;

  return (
    <PageFrame title={TITLE} creators={creators}>
      <div className="max-w-[720px] space-y-8">
        <AiKeyNotice accountId={accountId} kinds={[KIND]} />

        <FormBlock title="Automation">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-2 text-[14px] text-fg-dim">
              <p className="text-fg">
                Every day, reads your fans&apos; chats and fills their nickname with
                name / city / age / job.
              </p>
              <p>
                It lands on OnlyFans as <b>Name/City,Country/Age/Job</b> — for example{" "}
                <code>Garrett/Delta,Canada/30/Paramedic</code>. Only what he actually
                said is used; unknown parts are left out. A fan is (re)profiled once he
                has sent at least 8 new messages, so a quiet fan costs nothing. It uses
                the AI (it spends credits); fans never see the nickname.
              </p>
            </div>
            <IfSwitch aria-label={TITLE} checked={on}
              disabled={!rulesQ.isSuccess} loading={switchKind.isPending}
              onChange={(enable) => switchKind.mutate({ kind: KIND, enable })} />
          </div>
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
