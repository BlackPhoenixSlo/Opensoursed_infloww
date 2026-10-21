"use client";

/**
 * SplitInbox — the Split Inbox dialog an owner opens from the "All inboxes"
 * selector's "Split Inbox settings" (docs/spec/phase-02-fan-list-pane.md,
 * Split Inbox; ADR-0004). Its first section, "Choose the number of groups",
 * picks 1 to 9 groups for the Creator. Its second, "Reassign fans to
 * different groups", moves a loaded Fan to another group (story 50). One Save
 * sends one PUT; on success the dialog closes, on failure it stays open with
 * the relay's error and nothing is applied (story 62).
 *
 * Every select takes the kit's `.fx-select` Geometry (Gap row 30: 38px tall,
 * radius 9, 13.5px, padding 0 32px 0 12px), `MP.fanList.splitSelect`; the
 * dialog's own box is ours (`MP.ours.SplitInbox`).
 */

import { useId, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useSplitInbox, type SplitInboxConfig } from "@/hooks/useSplitInbox";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { useInflowwPalette } from "./InflowwPalette";

const GROUP_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;
/** `.fx-select` (Gap row 30), shared by the count and every Fan's group. */
const SELECT_CLASS = cn(MP.fanList.splitSelect, "border-border bg-bg-elev-1 text-fg");

/** A Fan the Fan List has loaded, as it passes them in, in its order. */
export interface SplitInboxFan {
  id: FanId;
  name: string;
}

/** The Split Inbox group (1 to N) a Fan belongs to: the Fan's explicit move
 *  when it is within range, otherwise a stable hash (32-bit FNV-1a) of the
 *  Fan id taken as text, modulo N, plus 1. Every Fan is in exactly one group,
 *  and a new split divides the Fans at once, the same way on every device
 *  (story 51). The id is never turned into a number, so a 19-digit id keeps
 *  its precision. */
export function groupOf(fanId: FanId, config: SplitInboxConfig): number {
  const n = config.group_count;
  const id = String(fanId);
  const moved = config.assignments[id];
  if (Number.isInteger(moved) && moved >= 1 && moved <= n) return moved;
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return ((hash >>> 0) % n) + 1;
}

export function SplitInbox({
  accountId, open, onClose, fans,
}: {
  accountId: string;
  open: boolean;
  onClose: () => void;
  /** The Fans loaded in the Fan List, listed for reassigning (no search). */
  fans: SplitInboxFan[];
}) {
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
  const palette = useInflowwPalette();
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(MP.ours.SplitInbox.dialog, "fixed z-50 border-border bg-panel text-fg shadow-xl outline-none")}
          style={palette}
        >
          <Dialog.Title className="mb-4 text-base font-semibold">Split Inbox settings</Dialog.Title>
          {/* Mounted only while open; it shares the Fan List's Split Inbox query. */}
          <SplitInboxBody accountId={accountId} onClose={onClose} fans={fans} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SplitInboxBody({
  accountId, onClose, fans,
}: { accountId: string; onClose: () => void; fans: SplitInboxFan[] }) {
  const { config, query, save } = useSplitInbox(accountId);
  if (config) return <SplitInboxForm stored={config} save={save} onClose={onClose} fans={fans} />;
  if (query.isError) {
    return <p role="alert" className="text-sm text-err">{query.error.message}</p>;
  }
  return <p className="text-sm text-fg-dim">Loading…</p>;
}

function SplitInboxForm({
  stored, save, onClose, fans,
}: {
  stored: SplitInboxConfig;
  /** The body's save mutation, so the dialog holds one query observer. */
  save: ReturnType<typeof useSplitInbox>["save"];
  onClose: () => void;
  fans: SplitInboxFan[];
}) {
  const [groupCount, setGroupCount] = useState(stored.group_count);
  // Starts from the stored moves, so a Save never erases moves saved from
  // another device; moving a Fan writes only that Fan's entry, and every
  // other Fan keeps following the hash spread.
  const [assignments, setAssignments] = useState(stored.assignments);
  const headingId = useId();
  const reassignId = useId();
  const draft = { group_count: groupCount, assignments };
  const groups = GROUP_COUNTS.slice(0, groupCount);
  // A lowered count drops every move above it; those Fans are spread again
  // by `groupOf` over the remaining groups (story 55).
  const submit = () => save.mutate({
    group_count: groupCount,
    assignments: Object.fromEntries(Object.entries(assignments).filter(([, g]) => g <= groupCount)),
  }, { onSuccess: onClose });
  return (
    <>
      <section aria-labelledby={headingId} className="flex flex-col gap-2">
        <h3 id={headingId} className="text-sm font-medium">Choose the number of groups</h3>
        <select
          aria-labelledby={headingId}
          value={groupCount}
          onChange={(e) => setGroupCount(Number(e.target.value))}
          disabled={save.isPending}
          className={SELECT_CLASS}
        >
          {GROUP_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </section>
      {/* With one group there is nowhere to move a Fan. */}
      {groupCount > 1 && (
        <section aria-labelledby={reassignId} className="mt-4 flex flex-col gap-2">
          <h3 id={reassignId} className="text-sm font-medium">Reassign fans to different groups</h3>
          <ul className="max-h-64 overflow-y-auto flex flex-col gap-2">
            {fans.map((f) => (
              <li key={String(f.id)} className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate text-sm">{f.name}</span>
                <select
                  aria-label={f.name}
                  value={groupOf(f.id, draft)}
                  onChange={(e) => {
                    const g = Number(e.target.value);
                    setAssignments((a) => ({ ...a, [String(f.id)]: g }));
                  }}
                  disabled={save.isPending}
                  className={SELECT_CLASS}
                >
                  {groups.map((n) => <option key={n} value={n}>Inbox {n}</option>)}
                </select>
              </li>
            ))}
          </ul>
        </section>
      )}
      {save.isError && (
        <p role="alert" className="mt-3 text-sm text-err">{save.error.message}</p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Dialog.Close asChild>
          <button
            type="button"
            className="px-3 py-1.5 rounded-md border border-border text-sm hover:border-border-light"
          >
            Cancel
          </button>
        </Dialog.Close>
        <button
          type="button"
          onClick={submit}
          disabled={save.isPending}
          className="px-3 py-1.5 rounded-md bg-accent text-sm text-white disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </>
  );
}
