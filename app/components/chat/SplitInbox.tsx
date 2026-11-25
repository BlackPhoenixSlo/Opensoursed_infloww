"use client";

/**
 * SplitInbox — the Split Inbox dialog an owner opens from the "All inboxes"
 * selector's "Split Inbox settings" (docs/spec/phase-02-fan-list-pane.md,
 * Split Inbox; ADR-0004). Its first section, "Choose the number of groups",
 * picks 1 to 9 groups for the Creator. Its second, "Reassign fans to
 * different groups", moves a loaded Fan to another group (story 50). Its
 * third, "Chatters", binds each chatter who can see this Creator to one group
 * ("All" = unbound); the relay then serves a bound chatter only that group's
 * Fans. One Save sends one PUT; on success the dialog closes, on failure it stays open with
 * the relay's error and nothing is applied (story 62).
 *
 * Every select takes the kit's `.fx-select` Geometry (Gap row 30: 38px tall,
 * radius 9, 13.5px, padding 0 32px 0 12px), `MP.fanList.splitSelect`; the
 * dialog's own box is ours (`MP.ours.SplitInbox`).
 */

import { useId, useMemo, useReducer } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { IfButton } from "@/components/ui/infloww";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { useRoster } from "@/hooks/useRoster";
import { useSplitInbox } from "@/hooks/useSplitInbox";
import type { FanId } from "@/lib/fanId";
import { relay } from "@/lib/relay";
import {
  groupOf, splitInboxKey, splitInboxQueryOptions, type SplitInboxConfig, type SplitInboxResponse,
} from "@/lib/splitInbox";
import { MP } from "@/lib/messagesPro";
import { cn } from "@/lib/utils";
import { useInflowwPalette } from "./InflowwPalette";
import {
  allChatterGroupOf, buildPayloads, initAllForm, scopeChatters, splitInboxAllFormReducer,
} from "./splitInboxAllForm";
import { buildPayload, chatterGroupOf, initForm, splitInboxFormReducer } from "./splitInboxForm";

const GROUP_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;
/** `.fx-select` (Gap row 30), shared by the count and every Fan's group. */
const SELECT_CLASS = cn(MP.fanList.splitSelect, "border-border bg-bg-elev-1 text-fg");

/** A Fan the Fan List has loaded, as it passes them in, in its order. */
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
  /** The Fans loaded in the Fan List, listed for reassigning (no search). */
  fans: SplitInboxFan[];
}) {
  // The Infloww palette when opened from Messages Pro; nothing anywhere else.
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
          {/* Mounted only while open; it shares the Fan List's Split Inbox query. */}
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
  /** The body's save mutation, so the dialog holds one query observer. */
  save: ReturnType<typeof useSplitInbox>["save"];
  onClose: () => void;
  fans: SplitInboxFan[];
}) {
  // Starts from the stored moves and bindings, so a Save never erases what
  // another device saved; every unmoved Fan keeps following the mod spread.
  const [form, dispatch] = useReducer(splitInboxFormReducer, stored, initForm);
  const { rows: roster } = useRoster({ includeDisabled: false });
  const chatters = useMemo(
    () => roster.filter((e) => e.kind !== "owner" && (e.account_ids == null || e.account_ids.includes(accountId))),
    [roster, accountId],
  );
  const headingId = useId();
  const reassignId = useId();
  const chattersId = useId();
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
      {groupCount > 1 && chatters.length > 0 && (
        <section aria-labelledby={chattersId} className="mt-4 flex flex-col gap-2">
          <h3 id={chattersId} className="text-sm font-medium">Chatters</h3>
          <ul className="max-h-48 overflow-y-auto flex flex-col gap-2">
            {chatters.map((c) => {
              const id = String(c.chatter_id);
              return (
                <li key={id} className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-sm">{c.display_name}</span>
                  <select
                    aria-label={c.display_name}
                    value={chatterGroupOf(form, id) ?? ""}
                    onChange={(e) => dispatch({
                      type: "bindChatter", chatterId: id, group: e.target.value === "" ? null : Number(e.target.value),
                    })}
                    disabled={save.isPending}
                    className={SELECT_CLASS}
                  >
                    <option value="">All</option>
                    {groups.map((n) => <option key={n} value={n}>Inbox {n}</option>)}
                  </select>
                </li>
              );
            })}
          </ul>
        </section>
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

const toStored = (results: { data?: SplitInboxResponse; error: Error | null }[]) => ({
  configs: results.map((r) => r.data?.config ?? null),
  error: results.find((r) => r.error && !r.data)?.error ?? null,
});

function SplitInboxAllBody({ accountIds, onClose }: { accountIds: readonly string[]; onClose: () => void }) {
  const { configs, error } = useQueries({
    queries: accountIds.map((id) => splitInboxQueryOptions(id)), combine: toStored,
  });
  const stored = useMemo(
    () => (configs.every((c) => c) ? new Map(accountIds.map((id, i) => [id, configs[i]!] as const)) : null),
    [accountIds, configs],
  );
  if (error) return <p role="alert" className="text-sm text-err">{error.message}</p>;
  if (stored) return <SplitInboxAllForm accountIds={accountIds} stored={stored} onClose={onClose} />;
  return <p className="text-sm text-fg-dim">Loading…</p>;
}

function SplitInboxAllForm({
  accountIds, stored, onClose,
}: { accountIds: readonly string[]; stored: ReadonlyMap<string, SplitInboxConfig>; onClose: () => void }) {
  const [form, dispatch] = useReducer(splitInboxAllFormReducer, stored, initAllForm);
  const { rows: roster } = useRoster({ includeDisabled: false });
  const chatters = useMemo(() => scopeChatters(roster, accountIds), [roster, accountIds]);
  const accounts = usePlatformAccounts();
  const qc = useQueryClient();
  const save = useMutation<void, Error, Map<string, SplitInboxConfig>>({
    mutationFn: async (payloads) => {
      const ids = [...payloads.keys()];
      const results = await Promise.allSettled(ids.map((aid) =>
        relay.put<SplitInboxResponse>(`/admin/split-inbox`, { account_id: aid, config: payloads.get(aid) })));
      const failed = ids.flatMap((aid, i) => {
        const r = results[i];
        return r.status === "rejected" ? [{ aid, reason: r.reason as unknown }] : [];
      });
      if (failed.length === 0) return;
      const nameOf = (aid: string) => accounts.find((a) => a.id === aid)?.nickname || aid;
      const first = failed[0].reason;
      throw new Error(
        `Not saved for ${failed.map((f) => nameOf(f.aid)).join(", ")}` +
        `${first instanceof Error ? `: ${first.message}` : ""}. The other models were saved.`,
      );
    },
    onSettled: (_d, _e, payloads) =>
      Promise.all([...payloads.keys()].map((aid) => qc.invalidateQueries({ queryKey: splitInboxKey(aid) }))),
  });
  const headingId = useId();
  const chattersId = useId();
  const { groupCount } = form;
  const groups = GROUP_COUNTS.slice(0, groupCount);
  const submit = () => save.mutate(buildPayloads(form, stored, chatters), { onSuccess: onClose });
  return (
    <>
      <p className="-mt-3 mb-4 text-sm text-fg-dim">Applies to all {accountIds.length} models</p>
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
        {groupCount > 1 && <p className="text-xs text-fg-dim">Move single fans from a model&apos;s own tab.</p>}
      </section>
      {groupCount > 1 && chatters.length > 0 && (
        <section aria-labelledby={chattersId} className="mt-4 flex flex-col gap-2">
          <h3 id={chattersId} className="text-sm font-medium">Chatters</h3>
          <ul className="max-h-48 overflow-y-auto flex flex-col gap-2">
            {chatters.map((c) => {
              const value = allChatterGroupOf(form, stored, c);
              return (
                <li key={c.id} className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-sm">{c.name}</span>
                  <select
                    aria-label={c.name}
                    value={value ?? ""}
                    onChange={(e) => dispatch({
                      type: "bindChatter", chatterId: c.id, group: e.target.value === "" ? null : Number(e.target.value),
                    })}
                    disabled={save.isPending}
                    className={SELECT_CLASS}
                  >
                    <option value="">All</option>
                    {value === "mixed" && <option value="mixed" disabled>Mixed</option>}
                    {groups.map((n) => <option key={n} value={n}>Inbox {n}</option>)}
                  </select>
                </li>
              );
            })}
          </ul>
        </section>
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
