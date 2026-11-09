"use client";

/** The Mass messages tab's hourly Auto-unsend card, one panel per model
 *  (moved out of MassMessagesTab.tsx as is). */

import { useEffect, useMemo, useReducer } from "react";

import { IfButton, IfSwitch } from "@/components/ui/infloww";
import { NumInput } from "@/components/ui/fields";
import {
  useAutomationRules,
  useCreateRule,
  useUpdateRule,
} from "@/hooks/useAutomations";
import {
  autoUnsendReducer, buildPayload, canSave, initialAutoUnsendForm, type ClassSetting,
} from "./autoUnsendForm";

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
  const noClass = !canSave(form);

  const save = () => {
    if (noClass) return;
    const payload = buildPayload(form);
    if (existing) {
      updateM.mutate({
        id: existing.id,
        is_enabled: enabled,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
      });
    } else {
      createM.mutate({
        account_id: accountId,
        kind: "unsend_messages",
        name: AUTO_RULE_NAME,
        every_seconds: AUTO_EVERY_SECONDS,
        payload,
        is_enabled: enabled,
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
      {([["text", "Free text-only"], ["img", "With image / video"], ["price", "PPV (priced)"]] as const).map(([cls, l]) => (
        <AutoClassRow key={cls} label={l} v={form[cls]}
          onOn={(on) => dispatch({ type: "classOn", cls, on })}
          onHours={(hours) => dispatch({ type: "hours", cls, hours })} />
      ))}
      <div className="flex items-center gap-3 pt-1 flex-wrap">
        <IfButton onClick={save} disabled={saving || noClass}>
          {saving ? "Saving…" : existing ? "Update" : "Save"}
        </IfButton>
        {noClass && (
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
