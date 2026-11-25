"use client";


import { ofmWritesStatus, useOfmWritesCreator, useSetOfmWritesCreator } from "@/hooks/useOfmWritesCreator";
import { CreatorSettingsPanel } from "@/components/settings/CreatorSettingsPanel";
import { localWhen } from "@/lib/format";

export default function OfmWritesTab() {
  return (
    <CreatorSettingsPanel title="OF Manager writes" emptyText="Select a creator to set its OF Manager writes"
      card={(accountId) => <OfmWritesCard accountId={accountId} />} />
  );
}

export function OfmWritesCard({ accountId }: { accountId: string }) {
  const q = useOfmWritesCreator(accountId);
  const setM = useSetOfmWritesCreator();
  const d = q.data;
  if (!d) return null;
  return (
    <div data-testid="ofm-writes-card" className="rounded-lg border border-border p-3 space-y-1 text-sm">
      <label className="flex items-start gap-2 font-medium text-fg">
        <input type="checkbox" data-testid="ofm-writes-box" className="mt-0.5 shrink-0"
          checked={d.forced_off} disabled={setM.isPending}
          onChange={(e) => setM.mutate({ accountId, forcedOff: e.target.checked })} />
        Keep OF Manager new writes off for this creator
      </label>
      <p data-testid="ofm-writes-status" className="text-xs text-fg-dim">{ofmWritesStatus(d)}</p>
      <p className="text-xs text-fg-dim">
        The OF Manager controls new to this app (Close all sessions, Block by country / IP, cover and avatar, Fully
        private and the rest) stay Not available for this creator while this is ticked; a page already open picks the
        change up within a minute of being the tab in front. The chat bubble shortcuts (countdown, Copy as draft, Unsend PPV) are only hidden:
        unsending is an older write, still in the message&apos;s ⋮ menu, and the server does not block it. Unticked,
        they follow the server&apos;s setting; this never turns them on.
      </p>
      {d.forced_off && d.changed_at && (
        <p data-testid="ofm-writes-who" className="text-xs text-fg-dim">
          Turned off by {d.changed_by ?? "unknown"} · {localWhen(d.changed_at)}
        </p>
      )}
      {setM.error && <p className="text-xs text-err">{setM.error.message}</p>}
    </div>
  );
}
