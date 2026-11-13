"use client";

/**
 * PromoReactivateCard — Infloww's "Auto-activate campaign" row (bundle: ProfilePromotionCampaign): the title, its T2
 * line and a switch, the one place that runs the automation re-creating finished promos (kind: "promo_reactivate").
 * The switch saves on toggle; with no rule yet, switching on creates it with the defaults (dry run on, every 60 min,
 * no re-arm cap). Ours, labelled: a status line under the row (what is set to keep running, dry run, last check) and
 * a "Settings" pop-up beside the switch for the engine (dry run, schedule, cycle cap, Check now). The per-campaign
 * "Keep running" boxes in Campaign insights are the opt-in. Infloww's "Offer expiration" select in this row is not
 * built: the re-arm keeps each campaign's own.
 */

import { useEffect, useReducer } from "react";

import { ExtraTag } from "@/components/ui/primitives";
import { IfButton, IfHelp, IfModal, IfSwitch } from "@/components/ui/infloww";
import { Field, NumInput, errMsg } from "@/components/growth/_bits";
import { initialState, reactivateReducer, rulePatch } from "@/components/growth/promoReactivateForm";
import { RunStats, isDryRun } from "@/lib/runStats";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { usePromotions } from "@/hooks/useGrowth";
import { useAutomationRules, useCreateRule, useUpdateRule, useRunRuleNow } from "@/hooks/useAutomations";
import { ifConfirm } from "@/components/ui/ifConfirm";

export default function PromoReactivateCard({ accountId }: { accountId: string | null }) {
  const promosQ = usePromotions(accountId);
  const armed = (promosQ.data?.campaigns ?? []).filter((c) => c.auto_reactivate).length;

  const rulesQ = useAutomationRules(accountId);
  const rule = (rulesQ.data ?? []).find((r) => r.kind === "promo_reactivate") ?? null;
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const runM = useRunRuleNow(accountId);
  const busy = createM.isPending || updateM.isPending;

  const [{ form, settings, err, msg }, dispatch] = useReducer(reactivateReducer, null, () => initialState());
  useEffect(() => { dispatch({ type: "adopt", rule }); }, [rule?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  /** The rule updated, or created from the form (a new rule takes the form's defaults, dry run on). */
  async function write(patch: { is_enabled: boolean } & Partial<ReturnType<typeof rulePatch>>) {
    if (!accountId) return;
    if (rule) await updateM.mutateAsync({ id: rule.id, ...patch });
    else await createM.mutateAsync({ account_id: accountId, kind: "promo_reactivate", name: "Keep promos running", ...rulePatch(form), ...patch });
  }

  /** Infloww's switch saves on toggle: the rule's on/off, with the rest as last saved. */
  async function toggle(on: boolean) {
    dispatch({ type: "toggle", on });
    try { await write({ is_enabled: on }); } catch (e) { dispatch({ type: "toggleFailed", on, err: errMsg(e, "Save failed") }); }
  }

  async function save() {
    dispatch({ type: "clear" });
    try {
      await write({ is_enabled: form.enabled, ...rulePatch(form) });
      dispatch({ type: "saved" });
    } catch (e) { dispatch({ type: "failed", err: errMsg(e, "Save failed") }); }
  }

  const closeSettings = () => dispatch({ type: "closeSettings", rule });

  async function runNow() {
    if (!rule) return;
    dispatch({ type: "clear" });
    // Run now executes the SAVED rule — key the warning off the saved payload.
    const savedDryRun = isDryRun(rule);
    if (!savedDryRun && !(await ifConfirm(
      "Check now uses the LAST SAVED config, which has dry-run OFF — any finished campaign marked “Keep running” will be re-created on OnlyFans. Continue?",
    ))) return;
    try {
      await runM.mutateAsync(rule.id);
      dispatch({ type: "notice", msg: savedDryRun
        ? "Dry run queued — it will report what it would re-create, and change nothing."
        : "Checking now — finished campaigns get re-created within ~30s." });
    } catch (e) { dispatch({ type: "failed", err: errMsg(e, "Run failed") }); }
  }

  const last = rule?.last_run;
  const lastLine = rule && last && (
    <>
      Last check: <span className="text-fg">{last.status}</span>
      <RunStats stats={last.stats} />
      {last.started_at && ` · ${new Date(last.started_at).toLocaleString()}`}
      {last.error_text && <span className="text-err"> · {last.error_text}</span>}
    </>
  );

  return (
    <section aria-label="Auto-activate campaign" className="space-y-1">
      {/* The bundle's row: 16 / 500 T1 and the switch right; the T2 line 4px under it. */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[16px] font-medium text-fg">Auto-activate campaign</div>
          <p className="mt-1 text-[14px] text-fg-dim">Enable to automatically reactivate your promotions when they expire</p>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          {/* Ours: the engine's knobs. */}
          <IfButton variant="link" title={EXTRA_LABEL} disabled={!accountId} onClick={() => dispatch({ type: "openSettings" })}>
            Settings
          </IfButton>
          <IfSwitch aria-label="Auto-activate campaign" checked={form.enabled} disabled={busy || !accountId}
            onChange={(on) => void toggle(on)} />
        </div>
      </div>

      {/* Ours, one line: what the switch acts on and how it is set. */}
      <IfHelp data-promo-reactivate-status>
        {armed > 0
          ? <span className="text-fg">{armed} campaign{armed === 1 ? "" : "s"} set to keep running</span>
          : <span>Tick <b>Keep running</b> on a campaign in Campaign insights to re-create it when it ends</span>}
        {form.enabled && isDryRun(rule) && <span> · Dry run: reports only, creates nothing</span>}
        {lastLine && <span> · {lastLine}</span>}
      </IfHelp>
      {!settings && err && <div role="alert" className="text-[14px] text-err">{err}</div>}
      {!settings && msg && <div className="text-[14px] text-accent">{msg}</div>}

      {settings && (
        <IfModal
          title="Auto-activate settings"
          width={520}
          onClose={closeSettings}
          footer={(
            <>
              {rule && (
                <IfButton className="mr-auto" onClick={() => void runNow()} disabled={runM.isPending}>
                  {runM.isPending ? "Checking…" : "Check now"}
                </IfButton>
              )}
              <IfButton onClick={closeSettings}>Cancel</IfButton>
              <IfButton variant="primary" onClick={() => void save()} disabled={busy || !accountId}>Save</IfButton>
            </>
          )}
        >
          <div className="flex flex-col gap-5 text-[14px]">
            <p className="flex items-start gap-2 text-fg-dim">
              <span>Re-creates a finished campaign ticked <b>Keep running</b>, same discount and cap.</span>
              <span className="shrink-0 whitespace-nowrap"><ExtraTag /></span>
            </p>
            <div>
              <IfSwitch label="Dry run" checked={form.dryRun} onChange={(dryRun) => dispatch({ type: "edit", patch: { dryRun } })} />
              <IfHelp>Report only, creates nothing.</IfHelp>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Check every (minutes)">
                <NumInput value={form.everyMinutes} min={1} onChange={(everyMinutes) => dispatch({ type: "edit", patch: { everyMinutes } })} />
              </Field>
              <div>
                <Field label="Max re-arms each">
                  <NumInput value={form.maxCycles} min={0} onChange={(maxCycles) => dispatch({ type: "edit", patch: { maxCycles } })} />
                </Field>
                <IfHelp>0 = no limit.</IfHelp>
              </div>
            </div>
            {lastLine && <div className="text-[12px] text-fg-dim">{lastLine}</div>}
            {err && <div role="alert" className="text-err">{err}</div>}
            {msg && <div className="text-accent">{msg}</div>}
          </div>
        </IfModal>
      )}
    </section>
  );
}
