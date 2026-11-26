"use client";


import type { Scope } from "@/contexts/ScopeContext";
import { useId, useMemo, useReducer, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { IfButton } from "@/components/ui/infloww";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { useSplitInboxes } from "@/hooks/useSplitInbox";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { RelayError } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { useInflowwPalette } from "./InflowwPalette";
import {
  allowedGroups, buildEdits, chatterGroupOf, fanGroupOf, GROUP_COUNTS, initialForm, scopeChatters, shownGroupCount,
  splitInboxFormReducer, widestGroupCount, type Stored,
} from "./splitInboxForm";

const SELECT_CLASS = cn(MP.fanList.splitSelect, "border-border bg-bg-elev-1 text-fg");

export interface SplitInboxFan {
  id: FanId;
  name: string;
  accountId: string | null;
}

export function SplitInbox({
  accountIds, scope, open, onClose, fans,
}: {
  accountIds: readonly string[];
  scope: Scope["kind"];
  open: boolean;
  onClose: () => void;
  fans: SplitInboxFan[];
}) {
  const palette = useInflowwPalette();
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(MP.ours.SplitInbox.dialog, "fixed z-50 border-border bg-panel text-fg shadow-xl outline-none")}
          style={palette}
        >
          <Dialog.Title className="mb-4 text-base font-semibold">Split Inbox settings</Dialog.Title>
          <SplitInboxBody accountIds={accountIds} scope={scope} onClose={onClose} fans={fans} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SplitInboxBody({
  accountIds, scope, onClose, fans,
}: { accountIds: readonly string[]; scope: Scope["kind"]; onClose: () => void; fans: SplitInboxFan[] }) {
  const accounts = usePlatformAccounts();
  const [{ targets, targetScope }] = useState(() => ({ targets: accountIds, targetScope: scope }));
  const { splits, save } = useSplitInboxes(targets, { refetchOnMount: "always" });
  const [stored, setStored] = useState<Stored | null>(null);
  const [round, setRound] = useState(0);
  const reads = [...splits];
  const fresh = reads.length > 0 && reads.every(([, r]) => r.status === "success" && !r.fetching && !r.failed);
  if (!stored && fresh) {
    setStored(new Map(reads.flatMap(([id, r]) => (r.status === "success" ? [[id, r.config] as const] : []))));
  }
  if (stored) {
    const reload = () => {
      setStored(null);
      setRound((r) => r + 1);
    };
    return <SplitInboxForm key={round} stored={stored} scope={targetScope} save={save} onClose={onClose} onStale={reload} fans={fans} />;
  }
  const failed = reads.flatMap(([id, r]) => (!r.fetching && r.failed ? [id] : []));
  if (failed.length) {
    const names = failed.map((id) => accounts.find((a) => a.id === id)?.nickname || id);
    return <p role="alert" className="text-sm text-err">Could not load Split Inbox settings for {names.join(", ")}.</p>;
  }
  return <p className="text-sm text-fg-dim">Loading…</p>;
}

function SplitInboxForm({
  stored, scope, save, onClose, onStale, fans,
}: {
  stored: Stored;
  scope: Scope["kind"];
  save: ReturnType<typeof useSplitInboxes>["save"];
  onClose: () => void;
  onStale: () => void;
  fans: SplitInboxFan[];
}) {
  const [form, dispatch] = useReducer(splitInboxFormReducer, initialForm);
  const { rows: roster } = useRoster({ includeDisabled: false });
  const accountIds = useMemo(() => [...stored.keys()], [stored]);
  const chatters = useMemo(() => scopeChatters(roster, accountIds), [roster, accountIds]);
  const headingId = useId();
  const reassignId = useId();
  const model = scope === "model" ? stored.get(accountIds[0]) : undefined;
  const groupCount = shownGroupCount(form, stored);
  const widest = widestGroupCount(form, stored);
  const groups = GROUP_COUNTS.slice(0, widest);
  const submit = () => {
    const edits = buildEdits(form, accountIds, scope);
    if (edits) {
      save.mutate(edits, {
        onSuccess: onClose,
        onError: (e) => { if (e instanceof RelayError && e.status === 409) onStale(); },
      });
    }
    else onClose();
  };
  return (
    <>
      {scope === "all" && <p className="-mt-3 mb-4 text-sm text-fg-dim">Applies to {accountIds.length === 1 ? "this model" : `all ${accountIds.length} models`} and new ones</p>}
      <section aria-labelledby={headingId} className="flex flex-col gap-2">
        <h3 id={headingId} className="text-sm font-medium">Choose the number of groups</h3>
        <select
          aria-labelledby={headingId}
          value={groupCount ?? ""}
          onChange={(e) => dispatch({ type: "count", n: Number(e.target.value) })}
          disabled={save.isPending}
          className={SELECT_CLASS}
        >
          {groupCount == null && <option value="" disabled>Mixed</option>}
          {GROUP_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        {scope === "all" && widest > 1 && <p className="text-xs text-fg-dim">Move single fans from a model&apos;s own tab.</p>}
      </section>
      {model && widest > 1 && (
        <section aria-labelledby={reassignId} className="mt-4 flex flex-col gap-2">
          <h3 id={reassignId} className="text-sm font-medium">Reassign fans to different groups</h3>
          <ul className="max-h-64 overflow-y-auto flex flex-col gap-2">
            {fans.filter((f) => f.accountId === accountIds[0]).map((f) => (
              <li key={String(f.id)} className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate text-sm">{f.name}</span>
                <select
                  aria-label={f.name}
                  value={fanGroupOf(form, model, f.id)}
                  onChange={(e) => dispatch({ type: "moveFan", fanId: String(f.id), group: Number(e.target.value) })}
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
      {widest > 1 && (
        <ChatterGroupsSection
          rows={chatters.map((c) => ({
            ...c, value: chatterGroupOf(form, stored, c), groups: allowedGroups(form, stored, c),
          }))}
          disabled={save.isPending}
          onBind={(chatterId, group) => dispatch({ type: "bindChatter", chatterId, group })}
        />
      )}
      {save.isError && (
        <p role="alert" className="mt-3 text-sm text-err">{save.error.message}</p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Dialog.Close asChild>
          <IfButton>Cancel</IfButton>
        </Dialog.Close>
        <IfButton variant="primary" onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </IfButton>
      </div>
    </>
  );
}

function ChatterGroupsSection({ rows, disabled, onBind }: {
  rows: readonly { id: string; name: string; value: number | null | "mixed"; groups: readonly number[] }[];
  disabled: boolean;
  onBind: (id: string, group: number | null) => void;
}) {
  const headingId = useId();
  if (!rows.length) return null;
  return (
    <section aria-labelledby={headingId} className="mt-4 flex flex-col gap-2">
      <h3 id={headingId} className="text-sm font-medium">Chatters</h3>
      <ul className="max-h-48 overflow-y-auto flex flex-col gap-2">
        {rows.map(({ id, name, value, groups }) => (
          <li key={id} className="flex items-center justify-between gap-3">
            <span className="min-w-0 truncate text-sm">{name}</span>
            <select
              aria-label={name}
              value={value ?? ""}
              onChange={(e) => onBind(id, e.target.value === "" ? null : Number(e.target.value))}
              disabled={disabled}
              className={SELECT_CLASS}
            >
              <option value="">All</option>
              {value === "mixed" && <option value="mixed" disabled>Mixed</option>}
              {groups.map((n) => <option key={n} value={n}>Inbox {n}</option>)}
            </select>
          </li>
        ))}
      </ul>
    </section>
  );
}
