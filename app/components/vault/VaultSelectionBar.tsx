"use client";

/** The grid's floating selection bar (#74, #75) and the drawer's Remove-from-vault control (#76), moved out of
 *  `VaultManagePanel`. */

import { useState } from "react";

import { FolderInput, Trash2 } from "lucide-react";

import { relay, type VaultMedia } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

/** #74, #75: the selection bar, 38px tall, 16px above the grid's foot, 20px left and 24px right: "Selected"
 *  and the count, then move (#77, "Add to category") and delete (#76). Ours follow, each titled as one. */
export default function VaultSelectionBar({
  count,
  hasFolders,
  busy,
  capped,
  capReason,
  onMove,
  onNewFolder,
  onDescribe,
  onClear,
}: {
  count: number;
  hasFolders: boolean;
  busy: string;
  capped: boolean;
  capReason: string;
  onMove: () => void;
  onNewFolder: () => void;
  onDescribe: () => void;
  onClear: () => void;
}) {
  return (
    <div className="absolute bottom-4 left-3 right-3 md:left-5 md:right-6 z-10 min-h-[38px] px-3 md:px-6 py-1 rounded-lg border border-accent/40 bg-panel/95 backdrop-blur-sm flex flex-wrap items-center gap-x-6 gap-y-1">
      <div className="flex items-center gap-1.5 text-sm font-medium">
        <span>Selected</span>
        <span>{count}</span>
      </div>
      {hasFolders && (
        // #74, #77: the move icon opens the "Add to category" modal.
        <button
          type="button"
          aria-label="Add to category"
          title="Add to category"
          onClick={onMove}
          disabled={!!busy}
          className="text-fg-dim hover:text-fg disabled:opacity-50"
        >
          <FolderInput size={18} aria-hidden />
        </button>
      )}
      {/* #76: OF's remove is one file at a time here (the drawer's "Remove from vault", which OF cannot
          undo); a batch of them is not built. */}
      <button
        type="button"
        aria-label="Delete"
        disabled
        title="not wired"
        className="text-fg-dim disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Trash2 size={18} aria-hidden />
      </button>
      <button
        type="button"
        onClick={onNewFolder}
        disabled={!!busy}
        title={EXTRA_LABEL}
        className="px-2.5 py-1 rounded-md text-xs border border-border bg-bg-elev-1 hover:text-fg"
      >
        New OF folder with these
      </button>
      <button
        type="button"
        onClick={onDescribe}
        disabled={!!busy || capped}
        title={capped ? `${EXTRA_LABEL}\n${capReason}` : EXTRA_LABEL}
        className="px-2.5 py-1 rounded-md text-xs border border-ok/50 bg-ok/10 text-ok hover:bg-ok/20 disabled:opacity-50"
      >
        {capped ? "Daily AI cap reached" : "Describe selected"}
      </button>
      {busy && <span className="text-xs text-fg-dim">{busy}</span>}
      <button
        type="button"
        onClick={onClear}
        title={EXTRA_LABEL}
        className="px-2 py-1 rounded-md text-xs text-fg-dim hover:text-fg"
      >
        Clear
      </button>
    </div>
  );
}

/** POST /admin/vault-ai/items/{id}/hide — OF's own "Remove from vault" (the same
 *  call the duplicates sweep uses). The media is HIDDEN on OF, not destroyed, so
 *  already-sent PPVs and live posts keep working — but OF exposes no unhide,
 *  which is why the UI confirms first. */
async function hideVaultItem(accountId: string, mediaId: number): Promise<void> {
  await relay.post(
    `/admin/vault-ai/items/${mediaId}/hide`,
    { account_id: accountId },
    { accountId },
  );
}

/** Remove-from-vault control. Two-step by design: this calls OF's own "Remove
 *  from vault", and OF exposes NO unhide — so a stray click must never be able
 *  to take media off the vault. The copy says exactly what happens (hidden, not
 *  destroyed; sent PPVs keep working) so the confirm is an informed one. */
export function VaultDeleteButton({
  media,
  accountId,
  onDeleted,
}: {
  media: VaultMedia;
  accountId: string;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function doDelete() {
    setBusy(true);
    setErr("");
    try {
      await hideVaultItem(accountId, media.id);
      onDeleted();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "remove failed");
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="px-3 py-1.5 rounded-md text-sm border border-err/50 bg-err/10 text-err hover:bg-err/20"
      >
        Remove from vault
      </button>
    );
  }
  return (
    <div className="w-full rounded-md border border-err/50 bg-err/10 p-2.5 space-y-2">
      <div className="text-xs text-err leading-snug">
        Remove <b>#{media.id}</b> from the OnlyFans vault? This uses OF&rsquo;s own
        “Remove from vault”, so it is <b>hidden, not destroyed</b> — already-sent
        PPVs and live posts keep working. <b>OnlyFans offers no undo.</b>
      </div>
      {err && <div className="text-xs text-err">{err}</div>}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={doDelete}
          className="flex-1 px-3 py-1.5 rounded-md text-sm border border-err/60 bg-err/20 text-err hover:bg-err/30 disabled:opacity-50"
        >
          {busy ? "Removing…" : "Yes, remove"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="px-3 py-1.5 rounded-md text-sm border border-border hover:bg-bg-elev-1 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
