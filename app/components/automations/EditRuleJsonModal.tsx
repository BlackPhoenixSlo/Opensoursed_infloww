"use client";

/**
 * EditRuleJsonModal — a raw-JSON editor for ONE automation rule's payload
 * (`steps_json`), for the bespoke single-rule tab (Auto stories, its "More
 * actions" menu) that builds its payload with a custom form. It lets an owner
 * hand-edit the payload object, validates it (parse + must be an object),
 * and PATCHes via the same /admin/automation-rules/{id} path the typed form uses
 * — server-side unknown keys pass through untouched, so hand edits are safe.
 *
 * Mirrors JsonConfigModal (the per-account config-blob editor) but targets a
 * rule row rather than a config surface. Single-rule assumption: these tabs keep
 * exactly one rule per (account, kind); if several exist we edit the first and
 * say so, and with none the menu item is disabled until the form saves one.
 */

import { useState } from "react";

import { RawJsonModal } from "@/components/automations/RawJsonModal";
import { useUpdateRule, type AutomationRule } from "@/hooks/useAutomations";
import { parseJsonObjectOr } from "@/lib/rawJsonReducer";

export function EditRuleJsonModal({
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
