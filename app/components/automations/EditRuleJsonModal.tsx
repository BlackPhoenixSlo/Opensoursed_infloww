"use client";

/**
 * EditRuleJsonButton + EditRuleJsonModal — a raw-JSON editor for ONE automation
 * rule's payload (`steps_json`), for the bespoke single-rule tab (Auto stories)
 * that builds its payload with a custom form. It loads the account's rule of the given `kind`, lets an
 * owner hand-edit the payload object, validates it (parse + must be an object),
 * and PATCHes via the same /admin/automation-rules/{id} path the typed form uses
 * — server-side unknown keys pass through untouched, so hand edits are safe.
 *
 * Mirrors JsonConfigModal (the per-account config-blob editor) but targets a
 * rule row rather than a config surface. Single-rule assumption: these tabs keep
 * exactly one rule per (account, kind); if several exist we edit the first and
 * say so, and if none exists the button is disabled until the form saves one.
 */

import { useMemo, useState } from "react";
import { Braces } from "lucide-react";

import { RawJsonModal } from "@/components/automations/RawJsonModal";
import { IfButton } from "@/components/ui/infloww";
import {
  useAutomationRules,
  useUpdateRule,
  type AutomationRule,
} from "@/hooks/useAutomations";
import { parseJsonObjectOr } from "@/lib/rawJsonReducer";

export function EditRuleJsonButton({
  accountId,
  kind,
  label = "Edit raw JSON",
  className,
}: {
  accountId: string | null;
  kind: string;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rulesQ = useAutomationRules(accountId);
  const rules = useMemo(
    () => (rulesQ.data ?? []).filter((r) => r.kind === kind),
    [rulesQ.data, kind],
  );
  const rule = rules[0] ?? null;
  const disabled = !accountId || !rule;
  return (
    <>
      <IfButton
        variant="link"
        icon={Braces}
        disabled={disabled}
        onClick={() => setOpen(true)}
        className={className}
        title={
          !accountId
            ? "Pick an account first"
            : !rule
              ? "Save this automation once, then edit its raw JSON"
              : "Edit the raw JSON payload for this rule"
        }
      >
        {label}
      </IfButton>
      {open && rule && accountId && (
        <EditRuleJsonModal
          rule={rule}
          accountId={accountId}
          extraCount={rules.length - 1}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function EditRuleJsonModal({
  rule,
  accountId,
  extraCount,
  onClose,
}: {
  rule: AutomationRule;
  accountId: string;
  extraCount: number;
  onClose: () => void;
}) {
  const updateM = useUpdateRule(accountId);
  const [text, setText] = useState<string>(() =>
    JSON.stringify(rule.payload ?? {}, null, 2),
  );
  const [err, setErr] = useState<string | null>(null);

  const parseOrError = () => parseJsonObjectOr(text, "Payload", '{ "enabled": true }', setErr);

  function onSave() {
    setErr(null);
    const parsed = parseOrError();
    if (!parsed) return;
    updateM
      .mutateAsync({ id: rule.id, payload: parsed })
      .then(() => onClose())
      .catch((e: Error) => setErr(e.message || "Save failed"));
  }

  function reformat() {
    setErr(null);
    const parsed = parseOrError();
    if (parsed) setText(JSON.stringify(parsed, null, 2));
  }

  return (
    <RawJsonModal
      name={rule.name || rule.kind}
      subtitle={`acct ${accountId} · rule #${rule.id} (${rule.kind})${extraCount > 0 ? ` · +${extraCount} more rule(s) of this kind not shown` : ""}`}
      text={text}
      onText={(t) => {
        setText(t);
        if (err) setErr(null);
      }}
      error={err}
      busy={updateM.isPending}
      onReformat={reformat}
      onSave={onSave}
      onClose={onClose}
    />
  );
}
