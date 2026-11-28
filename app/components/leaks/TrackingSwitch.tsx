"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IfSwitch } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";

import { afterWatchWrite } from "./leakKeys";
import { PAUSED, TRACKING_ON } from "./leakView";

export function TrackingSwitch({ creatorId, scopeAccountId, on, paused, canWrite }: {
  creatorId: string;
  scopeAccountId: string | null;
  on: boolean;
  paused: string | null;
  canWrite: boolean;
}) {
  const qc = useQueryClient();
  const flip = useMutation({
    mutationFn: (next: boolean) => relay.post(`/admin/leaks/watches/${creatorId}/tracking`, { on: next }, { accountId: scopeAccountId }),
    onSuccess: () => {
      void afterWatchWrite(qc, creatorId);
    },
  });
  const label = paused ?? (on ? TRACKING_ON : PAUSED);
  return (
    <div className="mt-2">
      {canWrite ? (
        <IfSwitch checked={on} onChange={(next) => flip.mutate(next)} loading={flip.isPending} label={label} aria-label="Tracking" />
      ) : (
        <p className="text-[14px] text-muted">{label}</p>
      )}
      {flip.error && <p role="alert" className="mt-1 text-[14px] text-err">{flip.error.message}</p>}
    </div>
  );
}
