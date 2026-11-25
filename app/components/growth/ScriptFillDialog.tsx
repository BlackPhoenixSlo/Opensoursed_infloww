"use client";


import { useQueryClient } from "@tanstack/react-query";

import { DESCRIBE_TARGET, dialogFor, type FillDialogState } from "@/components/growth/scriptFillState";
import { IfButton, IfModal } from "@/components/ui/infloww";
import { fillPlanKey, useFillPlan } from "@/hooks/useSavedReplies";
import { useVaultSweep } from "@/hooks/useVaultSweep";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { cn } from "@/lib/utils";

export function ScriptFillDialog({ accountId, dialog, busy, onFill, onDescribeRefused, onClose }: {
  accountId: string | null;
  dialog: FillDialogState;
  busy: boolean;
  onFill: (sequence: string) => void;
  onDescribeRefused: (pin: Pick<FillDialogState, "sequence" | "req">, message: string) => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const planKey = fillPlanKey(accountId, dialog.sequence);
  const planQ = useFillPlan(accountId, dialog.sequence);
  const sweep = useVaultSweep({
    kind: "describe-all",
    accountId,
    settleKeys: [[...planKey], ["vault-describe-plan", accountId]],
  });
  const copy = dialogFor({
    status: dialog.status,
    plan: planQ.data,
    sweep: { running: sweep.running, starting: sweep.busy && !sweep.running, progress: sweep.progress },
    refusal: dialog.refusal,
    now: Date.now(),
  });

  async function describe() {
    const pin = { sequence: dialog.sequence, req: dialog.req };
    const refusal = await sweep.start({ target: DESCRIBE_TARGET });
    if (refusal) onDescribeRefused(pin, refusal);
    // The settle edge refreshes only on an observed running -> idle change; a start that resolves null (zero-work answer) needs this refresh.
    else void qc.invalidateQueries({ queryKey: [...planKey] });
  }

  const footer = (
    <>
      <IfButton onClick={onClose}>{copy.button ? "Cancel" : "Close"}</IfButton>
      {copy.button === "describe" && (
        <IfButton variant="primary" disabled={sweep.busy} onClick={() => void describe()}>Describe content</IfButton>
      )}
      {copy.button === "fill" && (
        <IfButton variant="primary" disabled={busy} onClick={() => onFill(dialog.sequence)}>Fill with content</IfButton>
      )}
    </>
  );

  return (
    <IfModal title={copy.title} width={480} onClose={onClose} footer={footer}>
      <div title={EXTRA_LABEL} aria-live="polite" className="space-y-2">
        {copy.note && (
          <div className={cn("text-sm", copy.note.tone === "warn" ? "text-warn" : "text-fg-dim")}>
            <div>{copy.note.text}</div>
            <div className="text-xs">{copy.note.detail}</div>
          </div>
        )}
        {copy.lines.map((line, i) => (
          <p key={i} className={i === 0 ? "text-fg" : "text-fg-dim"}>{line}</p>
        ))}
      </div>
    </IfModal>
  );
}
