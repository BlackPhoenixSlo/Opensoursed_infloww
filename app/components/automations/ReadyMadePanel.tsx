"use client";


import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";

import { IfButton, IfLearn } from "@/components/ui/infloww";
import { PageFrame } from "@/components/shell/PageFrame";
import { ConfirmDelete, NoCreator, useAutomationCreator } from "@/components/automations/automationPage";
import {
  useAutomationRules,
  useDeleteRule,
  useRunRuleNow,
  useUpdateRule,
  type AutomationRule,
} from "@/hooks/useAutomations";
import { useAutomationRuns } from "@/hooks/useStats";
import { RuleTable } from "@/components/automations/RuleTable";
import { ReadyMadeRuleEditor } from "@/components/automations/ReadyMadeRuleEditor";
import { KIND_COPY } from "@/components/automations/readyMadeContent";
import type { Kind } from "@/components/compose/payloadRules";
import { useAgentPanel } from "@/components/assistant/agentBridge";

const EMPTY_HELP: Record<Kind, React.ReactNode> = {
  auto_posts: "A rule publishes one post on its schedule, and can delete it after the hours you set.",
  mass_premade: (
    <>
      A rule sends one mass message on its schedule. For a one-off send, use{" "}
      <Link href="/growth/smart-messages" className="text-accent hover:text-accent-hover">Smart Messages</Link>.
    </>
  ),
};

export default function ReadyMadePanel({ only }: { only: Kind }) {
  const creator = useAutomationCreator();
  const accountId = creator.accountId;

  const rulesQ = useAutomationRules(accountId);
  const runsQ = useAutomationRuns(200);
  const updateM = useUpdateRule(accountId);
  const deleteM = useDeleteRule(accountId);
  const runM = useRunRuleNow(accountId);

  const [editor, setEditor] = useState<AutomationRule | "new" | null>(null);
  const editing = editor === "new" ? null : editor;
  const [deleting, setDeleting] = useState<AutomationRule | null>(null);
  const [rowErr, setRowErr] = useState<{ id: number; msg: string } | null>(null);

  const rules = useMemo(
    () => (rulesQ.data ?? []).filter((r) => r.kind === only),
    [rulesQ.data, only],
  );

  const closeEditor = () => setEditor(null);

  useEffect(() => {
    closeEditor();
  }, [accountId]);

  async function toggle(rule: AutomationRule) {
    setRowErr(null);
    try {
      await updateM.mutateAsync({ id: rule.id, is_enabled: !rule.is_enabled });
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Toggle failed" });
    }
  }

  async function runNow(rule: AutomationRule) {
    setRowErr(null);
    try {
      await runM.mutateAsync(rule.id);
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Run failed" });
    }
  }

  async function remove(rule: AutomationRule) {
    setDeleting(null);
    setRowErr(null);
    try {
      await deleteM.mutateAsync(rule.id);
      if (editing?.id === rule.id) closeEditor();
    } catch (e) {
      setRowErr({ id: rule.id, msg: (e as Error)?.message || "Delete failed" });
    }
  }

  const runs = runsQ.data?.runs ?? [];
  const startNew = () => setEditor("new");
  useAgentPanel(only, accountId, startNew);
  const copy = KIND_COPY[only];

  return (
    <PageFrame
      title={copy.title}
      creators={creator.creators}
      actions={(
        <>
          <IfLearn tip={copy.blurb}><span className="max-sm:sr-only">Learn</span></IfLearn>
          <IfButton id={`rm-${only}-new`} variant="primary" icon={Plus} onClick={startNew} disabled={!accountId} className="max-sm:px-2.5">
            <span className="max-sm:sr-only">{copy.button}</span>
          </IfButton>
        </>
      )}
    >
      {accountId ? (
        <RuleTable
          kind={only}
          rules={rules}
          runs={runs}
          loading={rulesQ.isLoading}
          error={rulesQ.isError ? (rulesQ.error as Error)?.message || "Failed to load saved definitions" : null}
          empty={`No ${copy.plural} yet`}
          emptyHelp={EMPTY_HELP[only]}
          emptyAction={<IfButton variant="primary" icon={Plus} onClick={startNew}>{copy.button}</IfButton>}
          busy={{ toggle: updateM.isPending, run: runM.isPending, remove: deleteM.isPending }}
          rowErr={rowErr}
          onToggle={toggle}
          onRun={runNow}
          onEdit={setEditor}
          onDelete={setDeleting}
        />
      ) : <NoCreator loading={creator.loading} />}
      {editor && accountId && (
        <ReadyMadeRuleEditor
          key={editing?.id ?? "new"}
          kind={only}
          accountId={accountId}
          editing={editing}
          onClose={closeEditor}
        />
      )}
      {deleting && (
        <ConfirmDelete
          title={`Delete "${deleting.name}"?`}
          pending={deleteM.isPending}
          onConfirm={() => remove(deleting)}
          onClose={() => setDeleting(null)}
        >
          This stops the schedule.
        </ConfirmDelete>
      )}
    </PageFrame>
  );
}
