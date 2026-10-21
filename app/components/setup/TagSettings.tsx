"use client";

/**
 * TagSettings — the Tag column's gear on Manage creators (creators-manage#35) and the Tag manager it opens: each Tag
 * with "used by N creators", Rename and Delete (Infloww's creator group CRUD, `/creator/group/rename|delete`; a Tag is
 * Infloww's `group`). A Tag lives on the accounts that hold it (useCreatorProfiles), so Rename and Delete rewrite every
 * profile holding it in one write, and a new Tag is still typed in a Creator's account details: a Tag nobody holds
 * has nowhere to live. A chatter's refused blob leaves the gear Not wired.
 */

import { Settings } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

import { FlowButton, FlowModal, toast } from "@/components/setup/creatorFlow";
import { useCreatorProfiles } from "@/lib/creatorProfiles";

const FIELD = "h-9 min-w-0 flex-1 rounded-lg border border-border bg-bg px-3 text-sm focus:border-accent focus:outline-none";

export default function TagSettings() {
  const profiles = useCreatorProfiles();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button" aria-label="Tag settings" title={profiles.wired ? "Tag settings" : "not wired"}
        disabled={!profiles.wired} onClick={() => setOpen(true)}
        className="text-fg-dim hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Settings className="h-4 w-4" aria-hidden />
      </button>
      {/* Portalled: the gear sits in a table head, whose type styles the modal must not take. */}
      {open && createPortal(<TagManager onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}

function TagManager({ onClose }: { onClose: () => void }) {
  const profiles = useCreatorProfiles();
  // The row being renamed or asked about; one at a time.
  const [row, setRow] = useState<{ tag: string; mode: "delete" } | { tag: string; mode: "rename"; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = (p: Promise<void>, done: string) => {
    setBusy(true);
    p.then(() => { toast(done); setRow(null); }, (e: Error) => toast(e.message, "err")).finally(() => setBusy(false));
  };
  /** "1 creator", "2 creators": how many hold the Tag `t`. */
  const holders = (t: string) => {
    const n = profiles.tagCounts[t] ?? 0;
    return `${n} creator${n === 1 ? "" : "s"}`;
  };
  return (
    <FlowModal title="Tag settings" onClose={onClose}>
      {profiles.tags.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-dim">No tags yet. Give a creator a Tag in its account details.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {profiles.tags.map((t) => {
            const r = row?.tag === t ? row : null;
            if (r?.mode === "rename") {
              const next = r.name.trim();
              // Another Tag's name would merge the two: refused, as Infloww refuses a duplicate group name.
              const taken = next !== t && profiles.tags.includes(next);
              const canSave = !busy && !!next && next !== t && !taken;
              const save = () => { if (canSave) run(profiles.renameTag(t, next), "Tag renamed"); };
              return (
                <li key={t} className="flex flex-wrap items-center gap-2 py-2">
                  <input
                    aria-label={`Rename ${t}`} autoFocus maxLength={32} value={r.name} className={FIELD}
                    onChange={(e) => setRow({ ...r, name: e.target.value })}
                    aria-invalid={taken}
                    onKeyDown={(e) => { if (e.key === "Enter") save(); }}
                  />
                  <FlowButton onClick={() => setRow(null)}>Cancel</FlowButton>
                  <FlowButton primary disabled={!canSave} onClick={save}>Save</FlowButton>
                  {taken && <p className="w-full text-xs text-err">A tag with this name already exists</p>}
                </li>
              );
            }
            return (
              <li key={t} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{t}</span>
                  <span className="text-xs text-fg-dim">
                    {r?.mode === "delete" ? `Remove this tag from ${holders(t)}?` : `Used by ${holders(t)}`}
                  </span>
                </span>
                {r?.mode === "delete" ? (
                  <>
                    <FlowButton onClick={() => setRow(null)}>Cancel</FlowButton>
                    <FlowButton stop disabled={busy} onClick={() => run(profiles.renameTag(t, ""), "Tag deleted")}>Delete</FlowButton>
                  </>
                ) : (
                  <>
                    <FlowButton onClick={() => setRow({ tag: t, mode: "rename", name: t })}>Rename</FlowButton>
                    <FlowButton onClick={() => setRow({ tag: t, mode: "delete" })}>Delete</FlowButton>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </FlowModal>
  );
}
