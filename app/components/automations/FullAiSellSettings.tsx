"use client";

/**
 * Full AI Chat's selling controls with their own state (ticket 49), items 7-8 of the settings list (`FullAiSettings`;
 * item 6, Sell, is an inline switch there):
 *   7. Content folders: which vault folders (`vf:<id>`) and OF lists (`of:<id>`) the selling turn may offer from.
 *      A checklist in a dialog, All by default, include-only: Save sends the whole `folders` object with the stored
 *      `exclude` carried over (the draft PUT replaces it whole) and is refused with nothing ticked and All off.
 *      State: `sellFoldersForm.ts` (pure reducer);
 *   8. Prepare content: harvest → describe + Jev flags → AI folders → feet pack, each step only if missing; the button is its only
 *      start, the step list polls every 2 s while it runs (`useFullAiPrepare`). It writes no config, so it does not
 *      wait on the draft.
 * Content folders edits the draft (`useFullAiConfig.edit`) and waits like the other controls (`off`).
 */

import { useReducer, useState } from "react";

import { ROW } from "@/components/automations/automationPage";
import {
  buildPayload, canSubmit, initFolders, NO_FOLDER_TEXT, NO_FOLDERS, sellFoldersReducer, type StoredFolders,
} from "@/components/automations/sellFoldersForm";
import type { FullAiConfig } from "@/components/automations/fullAiTestChat";
import { IfButton, IfModal } from "@/components/ui/infloww";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";
import { useFullAiPrepare, type PrepareStep } from "@/hooks/useFullAiPrepare";
import { useSellFolders, type SellFolder } from "@/hooks/useSellFolders";

export function ContentFoldersRow({ accountId, draft, off, cfg }: {
  accountId: string; draft: FullAiConfig | null; off: boolean; cfg: FullAiConfigApi;
}) {
  const [open, setOpen] = useState(false);
  const stored = draft?.folders ?? NO_FOLDERS;
  const n = stored.include.length;
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-sm text-fg">Content folders</div>
          <div className="mt-0.5 text-xs text-muted">{n === 0 ? "All" : `${n} picked`}</div>
        </div>
        <IfButton disabled={off} onClick={() => setOpen(true)}>Choose</IfButton>
      </div>
      {open && (
        <FoldersDialog key={JSON.stringify(stored)} accountId={accountId} stored={stored} off={off} onClose={() => setOpen(false)}
          onSave={(folders) => { cfg.edit({ folders }); setOpen(false); }} />
      )}
    </div>
  );
}

function FoldersDialog({ accountId, stored, off, onSave, onClose }: {
  accountId: string; stored: StoredFolders; off: boolean; onSave: (f: StoredFolders) => void; onClose: () => void;
}) {
  const [pick, dispatch] = useReducer(sellFoldersReducer, stored, initFolders);
  const folders = useSellFolders(accountId);
  const ok = canSubmit(pick);
  return (
    <IfModal title="Content folders" onClose={onClose} footer={(
      <div className="flex flex-wrap items-center justify-end gap-2">
        {!ok && <span role="status" className="text-xs text-warn">{NO_FOLDER_TEXT}</span>}
        <IfButton onClick={onClose}>Cancel</IfButton>
        <IfButton variant="primary" disabled={!ok || off} onClick={() => onSave(buildPayload(pick, stored))}>Save</IfButton>
      </div>
    )}>
      <div className="space-y-4">
        <label className="flex items-center gap-2 font-semibold">
          <input type="checkbox" checked={pick.all} onChange={() => dispatch({ type: "all" })} />
          All (every item in the vault)
        </label>
        {folders.error && <p className="text-xs text-err">Couldn&apos;t read the folders.</p>}
        {folders.loading && <p className="text-xs text-muted">Reading folders…</p>}
        <FolderGroup title="Vault folders" list={folders.vault} picked={pick.all ? [] : pick.include}
          onToggle={(ref) => dispatch({ type: "toggle", ref })} />
        <FolderGroup title="OF lists" list={folders.of} picked={pick.all ? [] : pick.include}
          onToggle={(ref) => dispatch({ type: "toggle", ref })} />
      </div>
    </IfModal>
  );
}

function FolderGroup({ title, list, picked, onToggle }: {
  title: string; list: SellFolder[]; picked: string[]; onToggle: (ref: string) => void;
}) {
  if (list.length === 0) return null;
  return (
    <fieldset className="space-y-1.5">
      <legend className="mb-1 text-xs text-muted">{title}</legend>
      {list.map((f) => (
        <label key={f.ref} className="flex items-center gap-2">
          <input type="checkbox" checked={picked.includes(f.ref)} onChange={() => onToggle(f.ref)} />
          <span className="min-w-0 flex-1 truncate">{f.name || f.ref}</span>
          <span className="text-xs tabular-nums text-muted">{f.count}</span>
        </label>
      ))}
    </fieldset>
  );
}

const STEP_LABEL: Record<PrepareStep["name"], string> = { harvest: "Harvest", describe: "Describe", folders: "Folders", feet: "Feet pack" };
const countsLine = (c: Record<string, number>) => Object.entries(c).map(([k, v]) => `${k} ${v}`).join(" · ");

export function PrepareRow({ accountId }: { accountId: string }) {
  const { run, running, readError, start } = useFullAiPrepare(accountId);
  const busy = running || start.isPending;
  return (
    <div className={ROW}>
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 py-2">
        <div className="min-w-0">
          <div className="text-sm text-fg">Prepare content</div>
          <div className="mt-0.5 text-xs text-muted">Harvest, describe, AI folders, feet pack; skips what is done. Nothing goes to OnlyFans.</div>
        </div>
        <IfButton disabled={busy} onClick={() => start.mutate()}>{busy ? "Preparing…" : "Prepare content"}</IfButton>
      </div>
      {(readError || start.isError) && (
        <p role="alert" className="pb-2 text-xs text-err">{start.error?.message || "Couldn't read Prepare content."}</p>
      )}
      {run && run.steps.length > 0 && (
        <ol aria-label="Prepare content steps" className="space-y-1 pb-3">
          {run.steps.map((s) => (
            <li key={s.name} data-testid={`prepare-${s.name}`} className="text-xs">
              <span className="text-fg">{STEP_LABEL[s.name]}</span>{" "}
              <span className={s.state === "failed" ? "text-err" : s.state === "done" ? "text-ok" : "text-muted"}>{s.state}</span>
              {Object.keys(s.counts).length > 0 && <span className="text-muted"> · {countsLine(s.counts)}</span>}
              {s.detail && <div className="text-fg-dim">{s.detail}</div>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
