"use client";

/**
 * Full AI Chat's Fans row (live only): which Fans Full AI answers, by the Creator's OnlyFans fan lists (the custom lists
 * of `/api/of/v2/lists`, `useFanLists`; the live owner check reads the same OF list ids, `full_ai_owner_io._listed`).
 * A dialog sets each list to Include / Exclude / Neither; Save sends the whole `fans` object. Empty include = every
 * Fan; exclude wins. State: `fansForm.ts` (pure reducer). Edits the draft (`useFullAiConfig.edit`) and waits like the
 * other controls (`off`). The top "Fans & Following" row only reads the pick: Include while no list is included,
 * Neither once one is; picking Include there clears the includes. It is never stored.
 */

import { useReducer, useState } from "react";

import { useFanLists } from "@/components/audience/fanLists";
import { ROW } from "@/components/automations/automationPage";
import {
  buildPayload, everyoneOn, fanRows, fansReducer, fansSummary, initFans, NO_FANS, sideOf, type FanSide, type StoredFans,
} from "@/components/automations/fansForm";
import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import { IfButton, IfModal, IfSegmented } from "@/components/ui/infloww";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";

const SIDES: { value: FanSide; label: string }[] = [
  { value: "include", label: "Include" }, { value: "exclude", label: "Exclude" }, { value: "none", label: "Neither" },
];

type EveryoneSide = "include" | "none";

export function FansRow({ accountId, draft, off, cfg }: {
  accountId: string; draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi;
}) {
  const [open, setOpen] = useState(false);
  const stored = draft?.fans ?? NO_FANS;
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">Fans</div>
          <div className="mt-0.5 text-[12px] text-muted">{fansSummary(stored)} · live only</div>
        </div>
        <IfButton aria-label="Choose fans" disabled={off} onClick={() => setOpen(true)}>Choose</IfButton>
      </div>
      {open && (
        <FansDialog key={JSON.stringify(stored)} accountId={accountId} stored={stored} off={off} onClose={() => setOpen(false)}
          onSave={(fans) => { cfg.edit({ fans }); setOpen(false); }} />
      )}
    </div>
  );
}

function FansDialog({ accountId, stored, off, onSave, onClose }: {
  accountId: string; stored: StoredFans; off: boolean; onSave: (f: StoredFans) => void; onClose: () => void;
}) {
  const [pick, dispatch] = useReducer(fansReducer, stored, initFans);
  const lists = useFanLists(accountId);
  const failed = !lists.isLoading && lists.data === undefined;
  const rows = lists.isLoading || failed ? [] : fanRows(lists.customLists, pick);
  return (
    <IfModal title="Fans" onClose={onClose} footer={(
      <div className="flex flex-wrap items-center justify-end gap-2">
        <IfButton onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={off} onClick={() => onSave(buildPayload(pick))}>Save</IfButton>
      </div>
    )}>
      <div className="space-y-3">
        <p className="text-[12px] text-muted">
          Live only. Nothing included = every Fan. A Fan on an excluded list is never answered, even if another list includes him.
        </p>
        {failed && <p className="text-[12px] text-err">Couldn&apos;t read the fan lists.</p>}
        {lists.isLoading && <p className="text-[12px] text-muted">Reading fan lists…</p>}
        {!lists.isLoading && !failed && rows.length === 0 && <p className="text-[12px] text-muted">No fan lists on this account.</p>}
        {!lists.isLoading && !failed && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
            <span className="min-w-0 flex-1 truncate text-[14px] text-fg">Fans &amp; Following</span>
            <IfSegmented<EveryoneSide> aria-label="Fans & Following" value={everyoneOn(pick) ? "include" : "none"}
              options={[
                { value: "include", label: "Include", disabled: off },
                { value: "none", label: "Neither", disabled: off || everyoneOn(pick) },
              ]}
              onChange={(side) => { if (side === "include") dispatch({ type: "everyone" }); }} />
          </div>
        )}
        {rows.length > 0 && (
          <ul aria-label="Fan lists" className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="min-w-0 flex-1 truncate text-[14px] text-fg">
                  {r.name}
                  {r.count !== null && <span className="ml-1.5 text-[12px] tabular-nums text-muted">{r.count}</span>}
                </span>
                <IfSegmented aria-label={r.name} value={sideOf(pick, r.id)}
                  options={SIDES.map((s) => ({ ...s, disabled: off }))}
                  onChange={(side) => dispatch({ type: "set", id: r.id, side })} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </IfModal>
  );
}
