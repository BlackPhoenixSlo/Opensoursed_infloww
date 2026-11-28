"use client";

import { useState } from "react";

import { TableSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, IfButton } from "@/components/ui/infloww";

import { DeleteWatch } from "./DeleteWatch";
import { IdentityForm, type IdentityStart } from "./IdentityForm";
import { LeakCoverageSection } from "./LeakCoverageSection";
import type { LeakLane } from "./leakCoverage";
import { LeakPages } from "./LeakList";
import { useLeakPages } from "./leakRead";
import { headerFacts, NOT_CHECKED, NOT_TRACKED, pausedLabel, viewerZone, type LeakPage, type LeakRosterRow } from "./leakView";
import { RemovalArea } from "./RemovalArea";
import type { Removal, RemovalOffer } from "./removalOffer";
import { TrackingSwitch } from "./TrackingSwitch";

type LeakWatchRead = LeakPage & {
  tracked: boolean;
  identity: (IdentityStart & { platform: string; on: boolean }) | null;
  suggested: IdentityStart | null;
  synced: boolean;
  lanes: LeakLane[] | null;
  removal: Removal | null;
  offer: RemovalOffer | null;
};

const EMPTY: IdentityStart = { username: "", verified: false, display_name: "" };

export function LeakCreator({ creatorId, scopeAccountId, name, canWrite, brand, row, onDeleted }: {
  creatorId: string;
  scopeAccountId: string | null;
  name: string;
  canWrite: boolean;
  brand: string | null;
  row?: LeakRosterRow;
  onDeleted: () => void;
}) {
  const watch = useLeakPages<LeakWatchRead>(["leak-tracker", "watch", creatorId, scopeAccountId], `/admin/leaks/watches/${creatorId}`, scopeAccountId);
  const [editing, setEditing] = useState(false);

  if (watch.isPending) return <TableSkeleton rows={3} />;
  const w = watch.data?.pages[0];
  if (!w) return <EmptyState kind="error" className="mt-24" text={`Couldn't load ${name}.`} onRetry={() => void watch.refetch()} />;
  const close = () => setEditing(false);
  const now = new Date();
  const tz = viewerZone();
  const facts = row && headerFacts(row, now, tz);
  if (editing && canWrite) {
    return (
      <section aria-label={name}>
        <h2 className="mb-4 text-[16px] font-medium text-fg">{w.tracked ? `Edit ${name}` : `Track ${name}`}</h2>
        <IdentityForm
          key={String(w.tracked)}
          creatorId={creatorId}
          scopeAccountId={scopeAccountId}
          start={(w.tracked ? w.identity : w.suggested) ?? EMPTY}
          trimmed={w.lanes?.find((l) => l.lane === "google_full")?.trimmed ?? []}
          onDone={close}
          onCancel={close}
        />
      </section>
    );
  }
  return (
    <section aria-label={name}>
      <h2 className="text-[16px] font-medium text-fg">{name}</h2>
      {w.tracked && w.identity ? (
        <>
          <p className="mt-1 text-[14px] text-muted">
            @{w.identity.username}{w.identity.verified ? " · verified" : ""} · {facts ? `${facts.tracking} · ${facts.checked}` : NOT_CHECKED}
          </p>
          {facts?.counts && (
            <dl aria-label="Counts" className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
              {facts.counts.map(([label, value, note]) => (
                <div key={label} className="flex flex-col">
                  <dt className="text-[13px] text-muted">{label}</dt>
                  <dd className="text-[18px] font-medium text-fg">{value}{note && <span className="ml-1 text-[13px] font-normal text-muted">{note}</span>}</dd>
                </div>
              ))}
            </dl>
          )}
          <RemovalArea creatorId={creatorId} scopeAccountId={scopeAccountId} removal={w.removal} offer={w.offer} />
          {!w.synced && (
            <p role="status" className="mt-1 text-[14px] text-muted">
              Saved. It reaches {brand || "the removal service"} on the next sync.
            </p>
          )}
          <TrackingSwitch creatorId={creatorId} scopeAccountId={scopeAccountId} on={w.identity.on} paused={row ? pausedLabel(row, now, tz) : null} canWrite={canWrite} />
          {canWrite && (
            <div>
              <IfButton variant="link" className="mt-2" onClick={() => setEditing(true)}>Edit identity</IfButton>
              <DeleteWatch creatorId={creatorId} scopeAccountId={scopeAccountId} name={name} brand={brand} onDeleted={onDeleted} />
            </div>
          )}
          {w.lanes && <LeakCoverageSection lanes={w.lanes} />}
          <div className="mt-4">
            <LeakPages label={`${name} Leaks`} query={watch} />
          </div>
        </>
      ) : (
        <>
          <p className="mt-1 text-[14px] text-muted">{NOT_TRACKED}</p>
          {canWrite && <IfButton variant="primary" className="mt-3" onClick={() => setEditing(true)}>Track this Creator</IfButton>}
        </>
      )}
    </section>
  );
}
