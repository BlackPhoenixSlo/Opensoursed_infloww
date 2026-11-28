"use client";

import { useState } from "react";

import { TableSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, IfButton, IfSegmented } from "@/components/ui/infloww";

import { leakKeys } from "./leakKeys";
import { DeleteWatch } from "./DeleteWatch";
import { IdentityForm, type IdentityStart } from "./IdentityForm";
import { LeakCoverageSection } from "./LeakCoverageSection";
import { LeakPages } from "./LeakList";
import { NO_PREVIEWS, previewTiles } from "./leakPreview";
import { PreviewGrid } from "./LeakPreviewTiles";
import { useLeakPages, useRefreshCheck } from "./leakRead";
import { RefreshButton } from "./RefreshButton";
import { headerFacts, NOT_CHECKED, NOT_TRACKED, PAUSED, pausedLabel, viewerZone, type Leak, type LeakPage, type LeakRosterRow } from "./leakView";
import { RemovalArea } from "./RemovalArea";
import { TrackingSwitch } from "./TrackingSwitch";

const EMPTY: IdentityStart = { username: "", verified: false, display_name: "" };

export type LeakViewMode = "list" | "google";

const VIEWS: { value: LeakViewMode; label: string }[] = [{ value: "list", label: "List" }, { value: "google", label: "Google" }];

export function LeakCreator({ creatorId, scopeAccountId, name, canWrite, brand, previews, view, onView, row, onDeleted }: {
  creatorId: string;
  scopeAccountId: string | null;
  name: string;
  canWrite: boolean;
  brand: string | null;
  previews: boolean;
  view: LeakViewMode;
  onView: (view: LeakViewMode) => void;
  row?: LeakRosterRow;
  onDeleted: () => void;
}) {
  const { watch, checking, expired, queued } = useRefreshCheck(creatorId, scopeAccountId);
  const google = useLeakPages<LeakPage>(leakKeys.google(creatorId, scopeAccountId), `/admin/leaks/watches/${creatorId}?preview=1`, scopeAccountId,
    previews && view === "google");
  const [editing, setEditing] = useState(false);

  if (watch.isPending) return <TableSkeleton rows={3} />;
  const w = watch.data?.pages[0];
  if (!w) return <EmptyState kind="error" className="mt-24" text={`Couldn't load ${name}.`} onRetry={() => void watch.refetch()} />;
  const close = () => setEditing(false);
  const now = new Date();
  const tz = viewerZone();
  const facts = row && headerFacts(row, now, tz);
  const paused = row ? pausedLabel(row, now, tz) : w.this_week?.state === "paused" ? PAUSED : null;
  const grid = (leaks: Leak[], more: boolean) => {
    const tiles = previewTiles(leaks, previews, creatorId, now, tz);
    if (tiles.length) return <PreviewGrid label={`${name} Google previews`} tiles={tiles} scopeAccountId={scopeAccountId} />;
    return more ? null : <p className="text-[14px] text-muted">{NO_PREVIEWS}</p>;
  };
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
          <TrackingSwitch creatorId={creatorId} scopeAccountId={scopeAccountId} on={w.identity.on} paused={paused} canWrite={canWrite} />
          {canWrite && w.synced && w.identity.on && !paused && (
            <RefreshButton key={creatorId} creatorId={creatorId} scopeAccountId={scopeAccountId}
              nextRefreshAt={w.next_refresh_at} pending={checking} onQueued={queued}
              expired={expired} onReadRetry={() => { void watch.refetch(); }} />
          )}
          {canWrite && (
            <div>
              <IfButton variant="link" className="mt-2" onClick={() => setEditing(true)}>Edit identity</IfButton>
              <DeleteWatch creatorId={creatorId} scopeAccountId={scopeAccountId} name={name} brand={brand} onDeleted={onDeleted} />
            </div>
          )}
          {w.lanes && <LeakCoverageSection lanes={w.lanes} />}
          <div className="mt-4">
            <IfSegmented aria-label="Leak view" options={VIEWS} value={view} onChange={onView} className="mb-3" />
            {view === "google" && !previews ? <LeakPages query={watch} render={grid} />
              : view === "google" ? (
                google.isPending ? <TableSkeleton rows={2} />
                  : google.data ? <LeakPages query={google} render={grid} />
                  : <EmptyState kind="error" className="mt-12" text="Couldn't load the Google previews." onRetry={() => void google.refetch()} />
              ) : (
              <LeakPages label={`${name} Leaks`} query={watch} />
            )}
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
