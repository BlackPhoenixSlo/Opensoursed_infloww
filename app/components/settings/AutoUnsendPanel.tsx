"use client";

/** Smart Messages' "Mass Auto Unsend Messages" tab: the hourly Auto-unsend card, one panel per model. A model's
 *  class rows show only while its switch is on. */

import { useEffect, useMemo, useReducer } from "react";

import { IfButton, IfCard, IfHelp, IfSwitch } from "@/components/ui/infloww";
import { NumInput } from "@/components/ui/fields";
import { ExtraTag } from "@/components/ui/primitives";
import { useActiveAccounts } from "@/hooks/useAccounts";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
} from "@/hooks/useAutomations";
import {
  autoUnsendReducer, initialAutoUnsendForm, saveBody, type ClassSetting,
} from "./autoUnsendForm";

/** Auto-unsend automation: a scheduled `unsend_messages` rule per model, an hourly sweep that unsends broadcasts
 *  older than the set hours, by type (free text / image / PPV); a type left off is kept forever. An Inflowwww extra:
 *  Infloww has per-message Auto-unsend only, and no per-Creator sweep by message type
 *  (docs/spec/infloww-parity-round-2/phase-02b-auto-mass-messages.md). */
export function AutoUnsendCard() {
  const accounts = useActiveAccounts();
  return (
    <IfCard title={<span className="flex items-center gap-2"><span>Auto-unsend (automation)</span><ExtraTag /></span>}>
      <IfHelp className="mb-4">
        Runs hourly per model: unsends broadcasts older than the chosen hours, by type; an unchecked type is kept.
      </IfHelp>
      <div className="space-y-3">
        {accounts.length === 0 && (
          <div className="text-[14px] text-fg-dim">No active models.</div>
        )}
        {accounts.map((a) => (
          <AutoUnsendPanel key={a.id} accountId={a.id} label={a.nickname || a.id} />
        ))}
      </div>
    </IfCard>
  );
}

/** Name + cadence of the scheduled auto-unsend rule this tab manages (one
 *  `unsend_messages` automation_rules row per account, keyed by this name). */
const AUTO_RULE_NAME = "Auto-unsend mass";
const AUTO_EVERY_SECONDS = 3600; // hourly sweep

/** Per-model auto-unsend config. Reads/writes the single `unsend_messages` rule
 *  named AUTO_RULE_NAME for this account; the payload carries
 *  `policy.{mass_text_hours,mass_media_hours,mass_price_hours}` for the enabled
 *  classes (mirrors the backend sweep). */
export function AutoUnsendPanel({ accountId, label }: { accountId: string; label: string }) {
  const rulesQ = useAutomationRules(accountId);
  const createM = useCreateRule(accountId);
  const updateM = useUpdateRule(accountId);
  const existing = useMemo(
    () =>
      (rulesQ.data ?? []).find(
        (r) => r.kind === "unsend_messages" && r.name === AUTO_RULE_NAME,
      ),
    [rulesQ.data],
  );

  const [form, dispatch] = useReducer(autoUnsendReducer, initialAutoUnsendForm);
  const { enabled } = form;

  // Hydrate the form once from the saved rule when it first loads (the reducer ignores later loads).
  useEffect(() => {
    if (!existing) return;
    dispatch({
      type: "hydrate", isEnabled: existing.is_enabled,
      policy: (existing.payload?.policy ?? {}) as Record<string, number>,
    });
  }, [existing]);

  const saving = createM.isPending || updateM.isPending;
  const err = createM.error || updateM.error;
  const body = saveBody(form, !!existing);

  const save = () => {
    if (!body) return;
    if (existing) {
      updateM.mutate({ id: existing.id, every_seconds: AUTO_EVERY_SECONDS, ...body });
    } else if (body.payload) {
      createM.mutate({
        account_id: accountId,
        kind: "unsend_messages",
        name: AUTO_RULE_NAME,
        every_seconds: AUTO_EVERY_SECONDS,
        payload: body.payload,
        is_enabled: body.is_enabled,
      });
    }
  };

  return (
    <div className="rounded-md border border-border p-4 space-y-3 text-[14px]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <IfSwitch label={<span className="font-medium">{label}</span>} checked={enabled}
            onChange={(on) => dispatch({ type: "enabled", on })} />
          {existing?.is_enabled && (
            <span className="rounded-[4px] bg-accent/15 px-1.5 text-[12px] text-accent">Active</span>
          )}
        </div>
        <span className="text-[12px] text-fg-dim">Runs hourly</span>
      </div>
      {enabled && ([["text", "Free text-only"], ["img", "With image / video"], ["price", "PPV (priced)"]] as const).map(([cls, l]) => (
        <AutoClassRow key={cls} label={l} v={form[cls]}
          onOn={(on) => dispatch({ type: "classOn", cls, on })}
          onHours={(hours) => dispatch({ type: "hours", cls, hours })} />
      ))}
      <div className="flex items-center gap-3 pt-1 flex-wrap">
        <IfButton onClick={save} disabled={saving || !body}>
          {saving ? "Saving…" : existing ? "Update" : "Save"}
        </IfButton>
        {!body && enabled && (
          <span className="text-[12px] text-fg-dim">Turn on at least one class to save.</span>
        )}
        {err && <span className="text-[12px] text-err">{err.message}</span>}
        {existing?.last_run && (
          <span className="text-[12px] text-fg-dim">
            Last run: {existing.last_run.status}
            {existing.next_due_at
              ? ` · next ${new Date(existing.next_due_at).toLocaleTimeString()}`
              : ""}
          </span>
        )}
      </div>
    </div>
  );
}

function AutoClassRow({
  label, v, onOn, onHours,
}: {
  label: string;
  v: ClassSetting;
  onOn: (on: boolean) => void;
  onHours: (hours: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap md:flex-nowrap">
      <IfSwitch className="w-full md:w-52" label={label} checked={v.on} onChange={onOn} />
      <span className="text-fg-dim">after</span>
      <NumInput
        min={1}
        aria-label={`${label} hours`}
        className={v.on ? "w-20" : "w-20 opacity-50"}
        value={v.h}
        disabled={!v.on}
        onChange={onHours}
      />
      <span className="text-fg-dim">hours</span>
    </div>
  );
}
