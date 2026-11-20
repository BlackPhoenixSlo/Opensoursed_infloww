"use client";

/**
 * UnconfirmedSends — on Auto Funnel, one Creator's funnel / follow-up steps
 * whose send was interrupted. They are never auto-resent (a PPV must not go
 * out twice); the user retries each one, or says it went through (saved as sent,
 * never resent). A hint line shows a send to that fan the relay saw since.
 * State rules: ./unconfirmedSendsReducer.ts.
 * Renders nothing when there are none.
 */

import { Badge, Button } from "@/components/ui/primitives";
import { canAct, hintLine } from "@/components/automations/unconfirmedSendsReducer";
import { useUnconfirmedSends } from "@/hooks/useUnconfirmedSends";

const KIND_LABEL = { funnel: "Funnel", followup: "Follow-up" } as const;
const shortTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export function UnconfirmedSends({ accountId }: { accountId: string }) {
  const { rows, retry, dismiss } = useUnconfirmedSends(accountId);
  if (rows.length === 0) return null;
  return (
    <div
      role="status"
      data-testid="unconfirmed-sends"
      className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-fg space-y-2"
    >
      <div className="text-fg-dim">
        These steps were interrupted mid-send and are not resent automatically. Check the chat, then Retry if the fan didn&apos;t get it, or It went through if they did.
      </div>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} data-testid="unconfirmed-send-row" data-fan-id={r.fan_id} className="flex flex-wrap items-center gap-2">
            {r.state === "UNCONFIRMED"
              ? <Badge color="warn">May not have sent</Badge>
              : <Badge color="info">Sending</Badge>}
            <span>{KIND_LABEL[r.kind]} · fan {r.fan_id} · {r.step_label}</span>
            <span className="text-fg-dim">since {new Date(r.since).toLocaleString()}</span>
            {r.last_error && <span className="text-fg-dim truncate max-w-[24rem]" title={r.last_error}>{r.last_error}</span>}
            {r.state === "UNCONFIRMED" && (
              <>
                <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void retry(r)}>
                  {r.pending === "retry" ? "Retrying…" : "Retry"}
                </Button>
                <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void dismiss(r)}>
                  {r.pending === "dismiss" ? "Saving…" : "It went through"}
                </Button>
              </>
            )}
            {r.error && <span role="alert" className="text-err">{r.error}</span>}
            {hintLine(r, shortTime) && (
              <span data-testid="unconfirmed-send-hint" className="basis-full text-fg-dim truncate">
                {hintLine(r, shortTime)}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
