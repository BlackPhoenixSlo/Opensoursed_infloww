"use client";


import Link from "next/link";

import { Badge, Button } from "@/components/ui/primitives";
import { canAct, hintLine, isOpRow, showsRetry, type UnconfirmedView } from "@/components/automations/unconfirmedSendsReducer";
import { useUnconfirmedSends } from "@/hooks/useUnconfirmedSends";

const KIND_LABEL: Record<string, string> = { funnel: "Funnel", followup: "Follow-up", composer: "Chat message" };
const kindLabel = (kind: string) => {
  const words = kind.replace(/_/g, " ");
  return KIND_LABEL[kind] ?? words.charAt(0).toUpperCase() + words.slice(1);
};
const shortTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

// Interrupted sends are never auto-resent: a PPV must not go out twice; the user retries or marks it sent.
export function UnconfirmedSends({ accountId }: { accountId: string }) {
  const { rows, retry, dismiss, resolve } = useUnconfirmedSends(accountId);
  if (rows.length === 0) return null;
  const retryOff = rows.some((r) => r.retry_allowed === false);
  return (
    <div
      role="status"
      data-testid="unconfirmed-sends"
      className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-fg space-y-2"
    >
      <div className="text-fg-dim">
        {retryOff
          ? "These sends were interrupted and are not resent automatically. Check the chat or queue, then mark each one. To resend, write a new message."
          : <>These steps were interrupted mid-send and are not resent automatically. Check the chat, then Retry if the fan didn&apos;t get it, or It went through if they did.</>}
      </div>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.key} data-testid="unconfirmed-send-row" data-fan-id={r.fan_id} className="flex flex-wrap items-center gap-2">
            {r.state === "UNCONFIRMED"
              ? <Badge color="warn">May not have sent</Badge>
              : <Badge color="info">Sending</Badge>}
            <span>{rowLabel(r)}</span>
            <span className="text-fg-dim">since {new Date(r.since).toLocaleString()}</span>
            {!isOpRow(r) && r.last_error && <span className="text-fg-dim truncate max-w-[24rem]" title={r.last_error}>{r.last_error}</span>}
            {isOpRow(r) && (
              <Link
                data-testid="unconfirmed-send-link"
                href={r.link === "queue" ? "/growth/smart-messages" : `/messages-pro/${encodeURIComponent(accountId)}/${encodeURIComponent(r.fan_id)}`}
                className="underline underline-offset-2"
              >
                {r.link === "queue" ? "Open queue" : "Open chat"}
              </Link>
            )}
            {r.state === "UNCONFIRMED" && isOpRow(r) && (
              <>
                <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void resolve(r, "was_sent")}>
                  {r.pending === "was_sent" ? "Saving…" : "Was sent"}
                </Button>
                <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void resolve(r, "not_sent")}>
                  {r.pending === "not_sent" ? "Saving…" : "Not sent"}
                </Button>
              </>
            )}
            {r.state === "UNCONFIRMED" && !isOpRow(r) && (
              <>
                {showsRetry(r) && (
                  <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void retry(r)}>
                    {r.pending === "retry" ? "Retrying…" : "Retry"}
                  </Button>
                )}
                <Button size="sm" variant="secondary" disabled={!canAct(r)} onClick={() => void dismiss(r)}>
                  {r.pending === "dismiss" ? "Saving…" : "It went through"}
                </Button>
              </>
            )}
            {r.error && <span role="alert" className="text-err">{r.error}</span>}
            {!isOpRow(r) && hintLine(r, shortTime) && (
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

function rowLabel(r: UnconfirmedView): string {
  if (!isOpRow(r)) return `${kindLabel(r.kind)} · fan ${r.fan_id} · ${r.step_label}`;
  return r.link === "queue" ? kindLabel(r.kind) : `${kindLabel(r.kind)} · fan ${r.fan_id}`;
}
