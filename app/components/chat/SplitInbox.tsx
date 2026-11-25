"use client";


import { useId, useMemo, useReducer } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { IfButton } from "@/components/ui/infloww";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { useSplitInbox, useSplitInboxes } from "@/hooks/useSplitInbox";
import type { FanId } from "@/lib/fanId";
import { groupOf, type SplitInboxConfig } from "@/lib/splitInbox";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { useInflowwPalette } from "./InflowwPalette";
import {
  allChatterGroupOf, allowedGroups, buildPayloads, GROUP_COUNTS, initialAllForm, scopeChatters, selectedGroupCount,
  shownGroupCount, splitInboxAllFormReducer,
} from "./splitInboxAllForm";
import { buildPayload, chatterGroupOf, initForm, splitInboxFormReducer } from "./splitInboxForm";

const SELECT_CLASS = cn(MP.fanList.splitSelect, "border-border bg-bg-elev-1 text-fg");

export interface SplitInboxFan {
  id: FanId;
  name: string;
}

export function SplitInbox({
  accountIds, open, onClose, fans,
}: {
  accountIds: readonly string[];
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
          {accountIds.length === 1
            ? <SplitInboxBody accountId={accountIds[0]} onClose={onClose} fans={fans} />
            : <SplitInboxAllBody accountIds={accountIds} onClose={onClose} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SplitInboxBody({
  accountId, onClose, fans,
}: { accountId: string; onClose: () => void; fans: SplitInboxFan[] }) {
  const { config, query, save } = useSplitInbox(accountId);
  if (config) return <SplitInboxForm accountId={accountId} stored={config} save={save} onClose={onClose} fans={fans} />;
  if (query.isError) {
    return <p role="alert" className="text-sm text-err">{query.error.message}</p>;
  }
  return <p className="text-sm text-fg-dim">Loading…</p>;
}

function SplitInboxForm({
  accountId, stored, save, onClose, fans,
}: {
  accountId: string;
  stored: SplitInboxConfig;
  save: ReturnType<typeof useSplitInbox>["save"];
  onClose: () => void;
  fans: SplitInboxFan[];
}) {
  const [form, dispatch] = useReducer(splitInboxFormReducer, stored, initForm);
  const { rows: roster } = useRoster({ includeDisabled: false });
  const chatters = useMemo(
    () => scopeChatters(roster, [accountId]),
    [roster, accountId],
  );
  const headingId = useId();
  const reassignId = useId();
  const { groupCount } = form;
  const draft = { group_count: groupCount, assignments: form.assignments };
  const groups = GROUP_COUNTS.slice(0, groupCount);
  const submit = () => save.mutate(buildPayload(form), { onSuccess: onClose });
  return (
    <>
      <section aria-labelledby={headingId} className="flex flex-col gap-2">
        <h3 id={headingId} className="text-sm font-medium">Choose the number of groups</h3>
        <select
          aria-labelledby={headingId}
          value={groupCount}
          onChange={(e) => dispatch({ type: "count", n: Number(e.target.value) })}
          disabled={save.isPending}
          className={SELECT_CLASS}
        >
          {GROUP_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </section>
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
      {groupCount > 1 && (
        <ChatterGroupsSection
          rows={chatters.map((c) => ({ ...c, value: chatterGroupOf(form, c.id), groups }))}
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

function SplitInboxAllBody({ accountIds, onClose }: { accountIds: readonly string[]; onClose: () => void }) {
  const accounts = usePlatformAccounts();
  const { stored, error, save } = useSplitInboxes(accountIds, (id) => accounts.find((a) => a.id === id)?.nickname || id);
  if (error) return <p role="alert" className="text-sm text-err">{error.message}</p>;
  if (stored) return <SplitInboxAllForm accountIds={accountIds} stored={stored} save={save} onClose={onClose} />;
  return <p className="text-sm text-fg-dim">Loading…</p>;
}

function SplitInboxAllForm({
  accountIds, stored, save, onClose,
}: {
  accountIds: readonly string[];
  stored: ReadonlyMap<string, SplitInboxConfig>;
  save: ReturnType<typeof useSplitInboxes>["save"];
  onClose: () => void;
}) {
  const [form, dispatch] = useReducer(splitInboxAllFormReducer, initialAllForm);
  const { rows: roster } = useRoster({ includeDisabled: false });
  const chatters = useMemo(() => scopeChatters(roster, accountIds), [roster, accountIds]);
  const headingId = useId();
  const groupCount = selectedGroupCount(form, stored);
  const maxGroupCount = shownGroupCount(form, stored);
  const submit = () => save.mutate(buildPayloads(form, stored, chatters), { onSuccess: onClose });
  return (
    <>
      <p className="-mt-3 mb-4 text-sm text-fg-dim">Applies to all {accountIds.length} models</p>
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
        {maxGroupCount > 1 && <p className="text-xs text-fg-dim">Move single fans from a model&apos;s own tab.</p>}
      </section>
      {maxGroupCount > 1 && (
        <ChatterGroupsSection
          rows={chatters.map((c) => ({
            ...c,
            value: allChatterGroupOf(form, stored, c),
            groups: allowedGroups(form, stored, c),
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
