"use client";

/**
 * ReadyMadePanel — the ready-made posts & broadcasts page, pinned to one of
 * two rule kinds:
 *
 *   Auto Posts   (auto_posts)   — one post per rule, posted on the rule's
 *                                 schedule, optionally auto-deleted after N hours.
 *   Premade Mass (mass_premade) — one ready broadcast per rule, sent on the
 *                                 rule's schedule, optionally auto-unsent. My Automations calls it
 *                                 Auto Mass (/growth/auto-mass).
 *
 * Unlike the old fire-once tabs, these are now SAVED, persisted definitions
 * stored as `automation_rules` rows (reusing that table — no new schema). Each
 * saved rule shows what's queued next (`next_due_at` / `has_pending_job`) and a
 * compact strip of previous runs (from the executor's run log). "New / Edit"
 * opens ReadyMadeRuleEditor (the rule and its one post / message in one popup)
 * and persists it via the automation-rules create/update hooks; "Run now"
 * enqueues an immediate job off the saved rule.
 *
 * The panel is the page (`only`, My Automations > Auto Post / Auto Mass):
 * Infloww's legacy list page (page-parity ticket 16, copied from Smart Messages
 * › Automated Messages): a PageFrame with the creator column, a header with the
 * blurb as Learn's popover and the primary "New …", then an IF_TABLE of the
 * saved rules with previous runs in an expandable row.
 */

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

/** The empty list's line on what a rule does (and, for a mass, where a one-off send lives). */
const EMPTY_HELP: Record<Kind, React.ReactNode> = {
  auto_posts: "A rule publishes one post on its schedule, and can delete it after the hours you set.",
  mass_premade: (
    <>
      A rule sends one mass message on its schedule. For a one-off send, use{" "}
      <Link href="/growth/smart-messages" className="text-accent hover:text-accent-hover">Smart Messages</Link>.
    </>
  ),
};

/** The panel pinned to one rule kind: how My Automations > Auto Post
 *  (/growth/auto-post) shows the Auto Posts list, and > Auto Mass
 *  (/growth/auto-mass) the mass_premade list. It renders the page (its
 *  PageFrame and header) itself. */
export default function ReadyMadePanel({ only }: { only: Kind }) {
  // The creator column's pick, in `?creator=`.
  const creator = useAutomationCreator();
  const accountId = creator.accountId;

  const rulesQ = useAutomationRules(accountId);
  const runsQ = useAutomationRuns(200);
  const updateM = useUpdateRule(accountId);
  const deleteM = useDeleteRule(accountId);
  const runM = useRunRuleNow(accountId);

  // The open popup: a saved rule, a new one, or none.
  const [editor, setEditor] = useState<AutomationRule | "new" | null>(null);
  const editing = editor === "new" ? null : editor;
  const [deleting, setDeleting] = useState<AutomationRule | null>(null);
  const [rowErr, setRowErr] = useState<{ id: number; msg: string } | null>(null);

  const rules = useMemo(
    () => (rulesQ.data ?? []).filter((r) => r.kind === only),
    [rulesQ.data, only],
  );

  const closeEditor = () => setEditor(null);

  // Switching creators closes a half-open editor (its account would mismatch).
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
  // The help bot's "Do it for me" opens a new rule here, as the New button does.
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
