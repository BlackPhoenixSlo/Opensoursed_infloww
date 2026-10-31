"use client";

import { PremadeForm } from "@/components/compose/PremadeForm";
import type { Kind } from "@/components/compose/premadeRows";

/** Modal wrapper around PremadeForm in return-payload (compose) mode. */
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
    <div className="fixed inset-0 z-50 bg-black/50 grid place-items-center p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[640px] max-h-[90vh] flex flex-col bg-panel border border-border rounded-xl shadow-2xl"
      >
        <header className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-fg-dim hover:text-fg text-lg leading-none w-11 h-11 -mr-2 -my-2 grid place-items-center shrink-0 md:w-auto md:h-auto md:mr-0 md:my-0 md:inline"
            title="Close"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          <PremadeForm
            kind={kind}
            forcedAccountId={accountId}
            initialPayload={initialPayload}
            onComposePayload={onComposePayload}
          />
        </div>
      </div>
    </div>
  );
}
