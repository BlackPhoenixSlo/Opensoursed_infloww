"use client";


import { useState } from "react";
import { Megaphone } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { IfButton } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";
import { ifAlert } from "@/components/ui/ifConfirm";

interface DetectResult {
  runs_created: number;
  rows_tagged: number;
}

interface Props {
  accountId?: string | null;
  disabled?: boolean;
}

export default function GroupMassButton({ accountId, disabled }: Props) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const qs = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
      const res = await relay.post<DetectResult>(`/admin/messages/detect-mass${qs}`);
      await qc.invalidateQueries({ queryKey: ["paid-messages"] });
      const n = res?.runs_created ?? 0;
      if (typeof window !== "undefined") {
        await ifAlert(
          n > 0
            ? `Grouped ${n} mass blast${n === 1 ? "" : "s"} (${res.rows_tagged} sends).`
            : "No new mass blasts to group.",
        );
      }
    } catch (e) {
      if (typeof window !== "undefined") {
        await ifAlert(`Couldn't group mass sends: ${(e as Error)?.message || "unknown error"}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <IfButton
      icon={Megaphone}
      onClick={onClick}
      disabled={disabled || busy}
      title="Collapse OF-native mass blasts (stored as per-fan rows) into one MASS row each"
    >
      {busy ? "Grouping…" : "Group mass sends"}
    </IfButton>
  );
}
