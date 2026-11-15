"use client";

/**
 * Full AI Chat's "Who Full AI answers when Live" (owner 2026-11-15), its own block above the Test chat, apart from the bot
 * config's Settings / Save / Roll back: who live answers has nothing to do with how the AI behaves, so the Test chat's
 * draft vs checkpoint never splits it, and Save / Roll back never move it. Both controls write `PUT config/audience`
 * (`useFullAiConfig.putAudience`): applied at once on every side, Live or not, not held by the settings' draft wait.
 *   Fans: which Fans live answers, by the Creator's OnlyFans fan lists (the custom lists of `/api/of/v2/lists`,
 *   `useFanLists`; the live owner check reads the same OF list ids, `full_ai_owner_io._listed`). A dialog sets each list
 *   to Include / Exclude / Neither; Save sends the whole `fans` object. Empty include = every Fan; exclude wins. The top
 *   "Fans & Following" row only reads the pick: Include while no list is included, Neither once one is; picking Include
 *   there clears the includes. It is never stored. No list = every Fan, Live or not (owner 2026-11-15); a failed
 *   Save shows above its Save.
 *   Top spend limit: dollars on the page, cents stored (`top_spend_cents`); 0 = no limit. Stored on blur / Enter; a
 *   refused entry (empty too) snaps back, a refused write shows beside the box; a stored one reads "Saved" until the
 *   next edit.
 * State: `fansForm.ts` (pure reducers: the pick, the save).
 */

import { useReducer, useState } from "react";

import { useFanLists } from "@/components/audience/fanLists";
import { ROW } from "@/components/automations/automationPage";
import {
  AUDIENCE_SAVE_IDLE, audienceSaveReducer, buildPayload, everyoneOn, fanRows, fansReducer, fansSummary,
  initFans, NO_FANS, sideOf, type FanSide, type StoredFans,
} from "@/components/automations/fansForm";
import { topSpendDollars, topSpendPatch, type FullAiConfig } from "@/components/automations/fullAiConfig";
import type { TestChatState } from "@/components/automations/fullAiTestChat";
import { IfButton, IfInput, IfModal, IfSegmented } from "@/components/ui/infloww";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";
import { useFullAiMode } from "@/hooks/useFullAiMode";

const SIDES: { value: FanSide; label: string }[] = [
  { value: "include", label: "Include" }, { value: "exclude", label: "Exclude" }, { value: "none", label: "Neither" },
];

type EveryoneSide = "include" | "none";

export const AUDIENCE_TITLE = "Who Full AI answers when Live";

/** The section: Fans and Top spend limit, off the stored config (every side holds the same values). The page titles
 *  it (`AUDIENCE_TITLE` on its block, above the Test chat). */
export function FullAiAudience({ accountId, state, cfg }: { accountId: string; state: TestChatState; cfg: FullAiConfigApi }) {
  const stored = state.checkpoint ?? state.draft;
  return (
    <section aria-label={AUDIENCE_TITLE} className="space-y-2">
      <FansRow accountId={accountId} stored={stored} cfg={cfg} />
      <TopSpendRow stored={stored} cfg={cfg} />
    </section>
  );
}

export function FansRow({ accountId, stored, cfg }: { accountId: string; stored: FullAiConfig | null; cfg: FullAiConfigApi }) {
  const [open, setOpen] = useState(false);
  const live = useFullAiMode(accountId).data?.mode === "live";
  const fans = stored?.fans ?? NO_FANS;
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">Fans</div>
          <div className="mt-0.5 text-[12px] text-muted">{fansSummary(fans)}</div>
        </div>
        <IfButton aria-label="Choose fans" disabled={stored === null} onClick={() => setOpen(true)}>Choose</IfButton>
      </div>
      {open && <FansDialog accountId={accountId} stored={fans} live={live} cfg={cfg} onClose={() => setOpen(false)} />}
    </div>
  );
}

function FansDialog({ accountId, stored, live, cfg, onClose }: {
  accountId: string; stored: StoredFans; live: boolean; cfg: FullAiConfigApi; onClose: () => void;
}) {
  const [pick, dispatch] = useReducer(fansReducer, stored, initFans);
  const [save, dispatchSave] = useReducer(audienceSaveReducer, AUDIENCE_SAVE_IDLE);
  const lists = useFanLists(accountId);
  const failed = !lists.isLoading && lists.data === undefined;
  const rows = lists.isLoading || failed ? [] : fanRows(lists.customLists, pick);
  const busy = save.phase === "saving";
  /** Store the pick (applied at once). */
  const onSave = async () => {
    dispatchSave({ type: "save" });
    const result = await cfg.putAudience({ fans: buildPayload(pick) });
    dispatchSave({ type: "result", result });
    if (result.kind === "ok") onClose();
  };
  return (
    <IfModal title="Fans" onClose={onClose} footer={
      <div className="w-full space-y-2">
        {save.phase === "idle" && save.error && <p role="alert" className="text-[12px] text-err">{save.error}</p>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <IfButton onClick={onClose}>Cancel</IfButton>
          <IfButton variant="primary" disabled={busy} onClick={() => void onSave()}>{busy ? "Saving…" : "Save"}</IfButton>
        </div>
      </div>
    }>
      <div className="space-y-3">
        <p className="text-[12px] text-muted">
          Save applies at once{live ? " and changes who Full AI answers right now" : ""}. Nothing included = every Fan. A Fan on
          an excluded list is never answered, even if another list includes him.
        </p>
        {failed && <p className="text-[12px] text-err">Couldn&apos;t read the fan lists.</p>}
        {lists.isLoading && <p className="text-[12px] text-muted">Reading fan lists…</p>}
        {!lists.isLoading && !failed && rows.length === 0 && <p className="text-[12px] text-muted">No fan lists on this account.</p>}
        {!lists.isLoading && !failed && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
            <span className="min-w-0 flex-1 truncate text-[14px] text-fg">Fans &amp; Following</span>
            <IfSegmented<EveryoneSide> aria-label="Fans & Following" value={everyoneOn(pick) ? "include" : "none"}
              options={[
                { value: "include", label: "Include", disabled: busy },
                { value: "none", label: "Neither", disabled: busy || everyoneOn(pick) },
              ]}
              onChange={(side) => { if (side === "include") dispatch({ type: "everyone" }); }} />
          </div>
        )}
        {rows.length > 0 && (
          <ul aria-label="Fan lists" className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-col gap-1.5 py-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-2">
                {/* Phone: the name (and count) on its own full-width line, the control below it. */}
                <span className="w-full min-w-0 break-words text-[14px] text-fg sm:w-auto sm:flex-1">
                  {r.name}
                  {r.count !== null && <span className="ml-1.5 text-[12px] tabular-nums text-muted">{r.count}</span>}
                </span>
                <IfSegmented aria-label={r.name} value={sideOf(pick, r.id)}
                  options={SIDES.map((s) => ({ ...s, disabled: busy }))}
                  onChange={(side) => dispatch({ type: "set", id: r.id, side })} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </IfModal>
  );
}

/** Top spend limit: stored on blur / Enter through the audience write; a refused entry snaps back. */
export function TopSpendRow({ stored, cfg }: { stored: FullAiConfig | null; cfg: FullAiConfigApi }) {
  const [save, dispatchSave] = useReducer(audienceSaveReducer, AUDIENCE_SAVE_IDLE);
  const dollars = topSpendDollars(stored);
  const commit = async (el: HTMLInputElement) => {
    const patch = topSpendPatch(el.value);
    if (patch === null) { el.value = dollars; return; }
    if (patch.top_spend_cents === stored?.top_spend_cents) return;
    dispatchSave({ type: "save" });
    const result = await cfg.putAudience({ top_spend_cents: patch.top_spend_cents });
    dispatchSave({ type: "result", result });
    if (result.kind !== "ok") el.value = dollars;
  };
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-[14px] text-fg">Top spend limit</div>
          <div className="mt-0.5 text-[12px] text-muted">A Fan who has spent this much is left to humans. 0 = no limit.</div>
        </div>
        <label className="flex items-center gap-1.5 text-[14px] text-fg">
          <span>$</span>
          <IfInput key={dollars} type="number" inputMode="decimal" min={0} step={0.01} aria-label="Top spend limit"
            className="w-28" disabled={stored === null || save.phase === "saving"} defaultValue={dollars}
            onChange={() => dispatchSave({ type: "edit" })}
            onBlur={(e) => void commit(e.currentTarget)}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
          <span role="status" className="w-12 text-[12px] text-muted">{save.phase === "saved" ? "Saved" : ""}</span>
        </label>
      </div>
      {save.phase === "idle" && save.error && <p role="alert" className="pb-2 text-[12px] text-err">{save.error}</p>}
    </div>
  );
}
