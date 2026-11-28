"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IfButton, IfCard } from "@/components/ui/infloww";
import { relay } from "@/lib/relay";

import {
  CONTACT_CTA, followLine, hiddenUntil, leadLine, NOT_NOW, NOTICES_NEVER, OFFER_HEADING, REMOVAL_STARTING,
  type Removal, type RemovalOffer,
} from "./removalOffer";
import { dayLabel, viewerZone, when } from "./leakView";
import { StartRemovalPopup } from "./StartRemovalPopup";

export function RemovalArea({ creatorId, scopeAccountId, removal, offer }: {
  creatorId: string;
  scopeAccountId: string | null;
  removal: Removal | null;
  offer: RemovalOffer | null;
}) {
  const qc = useQueryClient();
  const [until, setUntil] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const snooze = useMutation({
    mutationFn: () => relay.post<{ offer_snoozed_until: string }>(
      `/admin/leaks/watches/${creatorId}/offer-snooze`, { snoozed: true }, { accountId: scopeAccountId }),
    onSuccess: (r) => {
      setUntil(r.offer_snoozed_until);
      void qc.invalidateQueries({ queryKey: ["leak-tracker", "watch", creatorId, scopeAccountId] });
    },
  });
  if (!removal || removal.view === "hidden") return null;
  const now = new Date();
  const tz = viewerZone();
  const updated = removal.notices_updated_at && when(removal.notices_updated_at, now, tz);
  return (
    <section aria-label="Removal" className="mt-4">
      <p className="text-[13px] text-muted">{updated ? `Notices updated ${updated}` : NOTICES_NEVER}</p>
      {removal.view === "starting" && <p className="mt-1 text-[14px] text-fg">{REMOVAL_STARTING}</p>}
      {until ? (
        <p role="status" className="mt-2 text-[14px] text-muted">{hiddenUntil(dayLabel(until, now, tz) ?? until)}</p>
      ) : offer && (
        <IfCard aria-labelledby={`removal-offer-${creatorId}`} className="mt-3 max-w-[560px]">
          <p className="text-[13px] text-muted">{offer.brand}</p>
          <h3 id={`removal-offer-${creatorId}`} className="text-[16px] font-medium text-fg">{OFFER_HEADING}</h3>
          <p className="mt-2 text-[14px] text-fg">{leadLine(offer)}</p>
          <p className="mt-1 text-[14px] text-muted">{followLine(offer.brand)}</p>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <IfButton variant="primary" aria-haspopup="dialog" onClick={() => setOpen(true)}>{CONTACT_CTA}</IfButton>
            <IfButton variant="link" disabled={snooze.isPending} onClick={() => snooze.mutate()}>{NOT_NOW}</IfButton>
          </div>
          {snooze.error && <p role="alert" className="mt-2 text-[14px] text-err">{snooze.error.message}</p>}
          {open && <StartRemovalPopup creatorId={creatorId} scopeAccountId={scopeAccountId} offer={offer} onClose={() => setOpen(false)} />}
        </IfCard>
      )}
    </section>
  );
}
