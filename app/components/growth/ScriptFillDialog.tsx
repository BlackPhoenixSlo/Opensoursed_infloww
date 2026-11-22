"use client";

/**
 * The Fill dialog (CONTEXT.md › Script fill; docs/spec/phase-02-button-and-popup.md): one `IfModal` that opens
 * only when a Fill cannot run. Its copy is `dialogFor` over the fresh Fill plan (read on every open), the Creator's
 * describe sweep and the last refusal; the page owns the state and this only calls back.
 *
 * "Describe content" starts describe-all with `target: 1000`; a refused start hands its sentence back
 * (`onDescribeRefused`). The settle edge refreshes the plan only on an observed running → idle change, so after
 * a start that resolves null the plan is refreshed here too (a zero-work answer, a sweep that ended between polls).
 * Nothing fills itself: "Ready to fill." waits for the press.
 */

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
  /** The Sequence's Fill or Undo is in flight. */
  busy: boolean;
  /** The dialog's "Fill with content": fills `dialog.sequence`. */
  onFill: (sequence: string) => void;
  /** A refused describe start, for the request whose dialog started it (`dialog.sequence`, `dialog.req`). */
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
