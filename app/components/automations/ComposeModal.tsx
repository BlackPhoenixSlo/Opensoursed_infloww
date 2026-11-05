"use client";

import { PremadeForm } from "@/components/compose/PremadeForm";
import type { Kind } from "@/components/compose/premadeRows";
import { EDITOR_MODAL } from "@/components/automations/automationPage";
import { IfModal } from "@/components/ui/infloww";

/** The ready-made rule's content dialog: PremadeForm's body and its Reset / Use in rule footer in an IfModal. */
export function ComposeModal({
  kind,
  accountId,
  initialPayload,
  onClose,
  onComposePayload,
}: {
  kind: Kind;
  accountId: string;
  initialPayload?: Record<string, unknown>;
  onClose: () => void;
  onComposePayload: (payload: Record<string, unknown>) => void;
}) {
  const title =
    kind === "auto_posts" ? "Compose auto posts" : "Compose premade mass";
  return (
    <PremadeForm
      kind={kind}
      forcedAccountId={accountId}
      initialPayload={initialPayload}
      onComposePayload={onComposePayload}
      frame={({ body, footer, dirty }) => (
        // Escape never drops an edited draft; × and Cancel still close.
        <IfModal width={722} title={title} onClose={onClose} keyboard={!dirty} className={EDITOR_MODAL}
          footer={footer}>
          {body}
        </IfModal>
      )}
    />
  );
}
