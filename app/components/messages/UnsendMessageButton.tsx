"use client";


import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useActionAllowed } from "@/components/shell/useGrantedPages";
import { Button } from "@/components/ui/primitives";
import { MASS_PLACEHOLDER_MIN } from "@/hooks/useChatMessages";
import { useUnsendMessage } from "@/hooks/useUnsendMessage";
import type { PaidMessageRow } from "@/hooks/usePaidMessages";
import { RelayError, type OFMessage } from "@/lib/relay";
import { ifConfirm } from "@/components/ui/ifConfirm";

// OF allows an unsend for about a day after sending.
const UNSEND_WINDOW_MS = 24 * 3600 * 1000;

export function canOfferUnsend(row: PaidMessageRow): boolean {
  return (row.direction ?? "out") === "out" && !row.is_mass_summary && !row.mass_run_id
    && !row.is_unsent && row.message_id > 0 && row.message_id < MASS_PLACEHOLDER_MIN;
}

export default function UnsendMessageButton({ row }: { row: PaidMessageRow }) {
  const qc = useQueryClient();
  const { unsendOne } = useUnsendMessage(row.account_id, row.fan_id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mountedAt] = useState(() => Date.now());
  const sent = row.sent_at ? new Date(row.sent_at).getTime() : NaN;
  const expired = Number.isFinite(sent) && mountedAt - sent > UNSEND_WINDOW_MS;
  const allowed = useActionAllowed("unsend");

  const onClick = async () => {
    if (!(await ifConfirm("Unsend this message? The fan will no longer see it.", { danger: true }))) return;
    setBusy(true);
    setError(null);
    try {
      await unsendOne({ id: String(row.message_id) } as OFMessage);
      await qc.invalidateQueries({ queryKey: ["paid-messages"] });
    } catch (err) {
      setError(err instanceof RelayError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!allowed) return null;
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={onClick}
        disabled={busy || expired}
        title={expired ? "OnlyFans only lets a message be unsent for about a day after sending" : "Unsend this message"}
      >
        {busy ? "Unsending…" : "Unsend"}
      </Button>
      {error && <span className="text-[11px] text-err max-w-40 text-right">{error}</span>}
    </div>
  );
}
