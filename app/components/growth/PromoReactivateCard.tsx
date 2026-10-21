"use client";

/**
 * PromoReactivateCard — settings for the automation that re-creates finished
 * promos (kind: "promo_reactivate").
 *
 * Infloww's "Auto-activate campaign" row (bundle: ProfilePromotionCampaign): the title, its T2 line and a switch
 * that turns the automation on or off (saved on toggle). Ours under it, labelled: the engine config (schedule,
 * dry-run, cycle cap); the per-campaign "Keep running" boxes in Campaign insights are the opt-in. Infloww's
 * "Offer expiration" select in this row is not built: the re-arm keeps each campaign's own.
 */

import { useEffect, useState } from "react";

import { Button, ExtraTag } from "@/components/ui/primitives";
import { IfSwitch } from "@/components/ui/infloww";
import { Field, NumInput, errMsg } from "@/components/growth/_bits";
import { RunStats, isDryRun } from "@/lib/runStats";
import { usePromotions } from "@/hooks/useGrowth";
import {
  useAutomationRules, useCreateRule, useUpdateRule, useRunRuleNow,
  type AutomationRule,
} from "@/hooks/useAutomations";

interface RForm {
  enabled: boolean;
  dryRun: boolean;
  everyMinutes: number;
  maxCycles: number;   // 0 = unlimited
}

function ruleToForm(rule: AutomationRule | null): RForm {
  const p = rule?.payload ?? {};
  return {
    enabled: rule?.is_enabled ?? false,
    dryRun: isDryRun(rule),          // default TRUE
    everyMinutes: rule?.every_seconds ? Math.max(1, Math.round(rule.every_seconds / 60)) : 60,
    maxCycles: typeof p.max_reactivations === "number" ? p.max_reactivations : 0,
  };
}

export default function PromoReactivateCard({ accountId }: { accountId: string | null }) {
  const promosQ = usePromotions(accountId);
  const armed = (promosQ.data?.campaigns ?? []).filter((c) => c.auto_reactivate).length;

  const rulesQ = useAutomationRules(accountId);
  const rule = (rulesQ.data ?? []).find((r) => r.kind === "promo_reactivate") ?? null;
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const runM = useRunRuleNow(accountId);
  const busy = createM.isPending || updateM.isPending;

  const [form, setForm] = useState<RForm>(ruleToForm(null));
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { setForm(ruleToForm(rule)); }, [rule?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = <K extends keyof RForm>(k: K, v: RForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    setErr(null); setMsg(null);
    if (!accountId) return;
    const every_seconds = Math.max(60, Math.round(form.everyMinutes) * 60);
    const payload = { max_reactivations: form.maxCycles, dry_run: form.dryRun };
    try {
      if (rule) {
        await updateM.mutateAsync({ id: rule.id, every_seconds, payload, is_enabled: form.enabled });
      } else {
        await createM.mutateAsync({
          account_id: accountId, kind: "promo_reactivate", name: "Keep promos running",
          every_seconds, payload, is_enabled: form.enabled,
        });
      }
      setMsg("✓ Saved.");
    } catch (e) { setErr(errMsg(e, "Save failed")); }
  }

  async function runNow() {
    if (!rule) { setErr("Save the automation first."); return; }
    setErr(null); setMsg(null);
    // Run now executes the SAVED rule — key the warning off the saved payload.
    const savedDryRun = isDryRun(rule);
    if (!savedDryRun && !window.confirm(
      "Check now uses the LAST SAVED config, which has dry-run OFF — any finished campaign marked “Keep running” will be re-created on OnlyFans. Continue?",
    )) return;
    try {
      await runM.mutateAsync(rule.id);
      setMsg(savedDryRun
        ? "✓ Dry run queued — it will report what it would re-create, and change nothing."
        : "✓ Checking now — finished campaigns get re-created within ~30s.");
    } catch (e) { setErr(errMsg(e, "Run failed")); }
  }

  const last = rule?.last_run;

  /** Infloww's switch saves on toggle: the rule's on/off, with the rest as last saved (a new rule takes the form's
   *  defaults, dry run on). */
  async function toggle(on: boolean) {
    setErr(null); setMsg(null);
    if (!accountId) return;
    set("enabled", on);
    try {
      if (rule) {
        await updateM.mutateAsync({ id: rule.id, is_enabled: on });
      } else {
        await createM.mutateAsync({
          account_id: accountId, kind: "promo_reactivate", name: "Keep promos running",
          every_seconds: Math.max(60, Math.round(form.everyMinutes) * 60),
          payload: { max_reactivations: form.maxCycles, dry_run: form.dryRun }, is_enabled: on,
        });
      }
    } catch (e) { set("enabled", !on); setErr(errMsg(e, "Save failed")); }
  }

  return (
    <section aria-label="Auto-activate campaign" className="space-y-4">
      {/* The bundle's row: 16 / 500 T1 and the switch right; the T2 line 4px under it. */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-[16px] font-medium text-fg">Auto-activate campaign</div>
          <p className="mt-1 text-[14px] text-fg-dim">Enable to automatically reactivate your promotions when they expire</p>
        </div>
        <IfSwitch aria-label="Auto-activate campaign" checked={form.enabled} disabled={busy || !accountId}
          onChange={(on) => void toggle(on)} />
      </div>

      {/* Ours under it, labelled: how the re-arm runs. */}
      <div className="space-y-3 rounded-lg border border-border p-4">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">Keep promos running <ExtraTag /></h3>
          <p className="text-xs text-fg-dim">
            OnlyFans ends a promo when its clock runs out or the claim cap fills. This
            re-creates any campaign you ticked <b>Keep running</b> below — same
            discount, same cap — so the offer never silently lapses.{" "}
            {armed > 0
              ? <span className="text-fg">{armed} campaign{armed === 1 ? "" : "s"} set to keep running.</span>
              : <span>Nothing is set to keep running yet — tick a campaign below.</span>}
          </p>
        </div>

        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={form.dryRun}
            onChange={(e) => set("dryRun", e.target.checked)}
            className="w-4 h-4 rounded accent-accent cursor-pointer" />
          Dry run <span className="text-[11px] text-fg-dim">(report only — creates nothing)</span>
        </label>

        <div className="grid gap-3 sm:grid-cols-2 max-w-md">
          <Field label="Check every (minutes)">
            <NumInput value={form.everyMinutes} min={1} onChange={(v) => set("everyMinutes", v)} />
          </Field>
          <Field label="Max re-arms each (0 = no limit)">
            <NumInput value={form.maxCycles} min={0} onChange={(v) => set("maxCycles", v)} />
          </Field>
        </div>

        {err && <div className="text-sm text-err">{err}</div>}

        <div className="flex items-center gap-2">
          <Button size="sm" onClick={save} disabled={busy || !accountId}>
            {rule ? "Save changes" : "Create automation"}
          </Button>
          {rule && (
            <Button size="sm" variant="ghost" onClick={runNow} disabled={runM.isPending}>
              {runM.isPending ? "Checking…" : "Check now"}
            </Button>
          )}
        </div>

        {msg && <div className="text-sm text-accent border-t border-border pt-3">{msg}</div>}

        {rule && last && (
          <div className="text-xs text-fg-dim border-t border-border pt-3">
            Last check: <span className="text-fg">{last.status}</span>
            <RunStats stats={last.stats} />
            {last.started_at && ` · ${new Date(last.started_at).toLocaleString()}`}
            {last.error_text && <span className="text-err"> · {last.error_text}</span>}
          </div>
        )}
      </div>
    </section>
  );
}
