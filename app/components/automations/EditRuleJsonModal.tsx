"use client";


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
