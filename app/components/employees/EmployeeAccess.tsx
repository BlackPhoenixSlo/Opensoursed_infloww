"use client";

/**
 * The access limits of an Employee's login (`chatter` in the code and the Relay): AccessEditor sets the per-Employee
 * Creator and vault-folder limits (GET /admin/chatters/{id}/access, PUT …/account-access and …/folder-access), and
 * Manage employees opens it in the Access limits modal from a row's More menu (EmployeeModals.tsx). Adding an
 * Employee is EmployeeFormModal there.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer } from "react";

import { Button } from "@/components/ui/primitives";
import { relay, type VaultListsResp } from "@/lib/relay";
import { fetchAllVaultLists } from "@/hooks/useVaultMedia";
import { useAccounts } from "@/hooks/useAccounts";
import { errText } from "@/lib/errText";
import { type FanId } from "@/lib/fanId";
import {
  accountsInvalid, buildPayload, canSubmit, employeeAccessReducer, NO_FOLDER_LIMIT,
  seedEmployeeAccess, visibleAccountIds, type AccessResp, type FolderEntry,
} from "@/components/employees/employeeAccessState";

// ── Access limits (Chatter Access, step 6.1) ────────────────────────
//
// Owner-set, per-Employee visibility limits. Two SUBTRACTIVE allowlists:
//   • Limit models — which of THIS owner's accounts the Employee sees (the
//     same allowlist as the Assigned Creators column).
//   • Limit folders — per allowed account, which vault folders the
//     Employee sees in the picker.
// Both default OFF (= full access). DA-2: an empty restricted set is never
// persisted — "see nothing" is Deactivate, not an empty allowlist. So when a
// "Limit …" toggle is ON, at least one selection is required to save.
// The draft (AccessDraft), its seeding and the save gate/payload: employeeAccessState.ts.

export function AccessEditor({ chatterId }: { chatterId: string }) {
  const accessQ = useQuery<AccessResp>({
    queryKey: ["admin", "chatters", chatterId, "access"],
    queryFn: () => relay.get<AccessResp>(`/admin/chatters/${chatterId}/access`),
    staleTime: 5_000,
  });

  // Once loaded the draft stays mounted (a failed background refetch keeps it too) and is seeded once: a refetch's
  // new `data` never reaches its reducer, so it cannot wipe edits.
  if (accessQ.data) {
    return <AccessDraft key={chatterId} chatterId={chatterId} initial={accessQ.data} />;
  }
  if (accessQ.error) {
    return <div className="text-err text-xs">{errText(accessQ.error)}</div>;
  }
  return <div className="text-fg-dim text-xs">Loading access…</div>;
}

function AccessDraft({ chatterId, initial }: { chatterId: string; initial: AccessResp }) {
  const qc = useQueryClient();
  const accountsQ = useAccounts();
  const ownerAccounts = accountsQ.data?.accounts ?? [];
  const ownerIds = ownerAccounts.map((a) => a.id);

  const [state, dispatch] = useReducer(employeeAccessReducer, initial, seedEmployeeAccess);
  const { limitModels, selectedAccounts, folders, savedAt, saveErr } = state;

  const visibleIds = visibleAccountIds(state, ownerIds);

  const saveM = useMutation({
    // Two writes (account-access, then folder-access per account), so a save can half land: the error says which.
    mutationFn: async () => {
      const p = buildPayload(state, ownerIds);
      try {
        await relay.put(`/admin/chatters/${chatterId}/account-access`, p.accounts);
      } catch (e) {
        throw new Error(`Accounts failed — ${errText(e, "save failed")}; folders not saved`);
      }
      try {
        for (const body of p.folders) {
          await relay.put(`/admin/chatters/${chatterId}/folder-access`, body);
        }
      } catch (e) {
        throw new Error(`Accounts saved; folders failed — ${errText(e, "save failed")}`);
      }
    },
    onMutate: () => dispatch({ type: "saveStart" }),
    onSuccess: () => dispatch({ type: "saveOk", at: Date.now() }),
    onError: (e) => dispatch({ type: "saveErr", msg: errText(e, "save failed") }),
    // Every outcome: a half-landed save changed the access too (and the list's Assigned Creators with it).
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "chatters", chatterId, "access"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });

  const accountSelectionInvalid = accountsInvalid(state);
  const cannotSave = !canSubmit(state, ownerIds);

  const setFolderEntry = useCallback(
    (accountId: string, entry: FolderEntry) => dispatch({ type: "folder", accountId, entry }),
    [],
  );

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={limitModels}
            onChange={(e) => dispatch({ type: "limitModels", on: e.target.checked })}
          />
          <span>Limit which models this employee sees</span>
        </label>
        <p className="text-[11px] text-fg-dim ml-6">
          Off = sees all of your models. To hide everything, deactivate the employee instead.
        </p>

        {limitModels && (
          <div className="ml-6 space-y-1.5 mt-2">
            {ownerAccounts.length === 0 && (
              <div className="text-[11px] text-fg-dim">You have no models to grant.</div>
            )}
            {ownerAccounts.map((a) => (
              <label key={a.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={selectedAccounts.has(a.id)}
                  onChange={(e) => dispatch({ type: "toggleAccount", id: a.id, on: e.target.checked })}
                />
                <span
                  className="inline-block w-2.5 h-2.5 rounded-full"
                  style={{ background: a.color || "#666" }}
                  aria-hidden
                />
                <span>{a.nickname || a.id}</span>
              </label>
            ))}
            {accountSelectionInvalid && (
              <p className="text-err text-[11px]">Pick at least one model, or turn the limit off.</p>
            )}
          </div>
        )}
      </div>

      <div className="space-y-3 border-t border-border/40 pt-3">
        <h5 className="text-xs font-semibold text-fg-dim">Folder limits (per model)</h5>
        {visibleIds.length === 0 && (
          <div className="text-[11px] text-fg-dim">
            {limitModels ? "Select a model above to set folder limits." : "No models available."}
          </div>
        )}
        {visibleIds.map((aid) => {
          const a = ownerAccounts.find((x) => x.id === aid);
          return (
            <FolderLimit
              key={aid}
              accountId={aid}
              accountLabel={a?.nickname || aid}
              entry={folders[aid] ?? NO_FOLDER_LIMIT}
              onChange={setFolderEntry}
            />
          );
        })}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button size="sm" onClick={() => saveM.mutate()} disabled={cannotSave || saveM.isPending}>
          {saveM.isPending ? "Saving…" : "Save access"}
        </Button>
        {savedAt && !saveM.isPending && <span className="text-ok text-[11px]">Saved.</span>}
        {saveErr && <span role="alert" className="text-err text-[11px]">{saveErr}</span>}
      </div>
    </div>
  );
}

function FolderLimit({
  accountId, accountLabel, entry, onChange,
}: {
  accountId: string;
  accountLabel: string;
  entry: FolderEntry;
  onChange: (aid: string, next: FolderEntry) => void;
}) {
  // Lazy: only fetch the model's folders when the limit is turned on.
  // Shared paginating fetcher — the grant list must show EVERY folder, and
  // a bare limit=50 fetch under this key would also poison the picker cache.
  const listsQ = useQuery<VaultListsResp>({
    queryKey: ["vault-lists", accountId],
    queryFn: () => fetchAllVaultLists({ accountId }),
    enabled: entry.limit,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  // Owner sees ALL custom folders (this fetch is owner-scoped, unfiltered).
  const folders = useMemo(
    () => (listsQ.data?.list ?? []).filter((l) => l.type === "custom"),
    [listsQ.data],
  );
  const selectedIds = useMemo(
    () => new Set(entry.grants.map((g) => g.folder_id)),
    [entry.grants],
  );

  // Backfill folder_name on grants that were seeded from the server with a
  // null name (DA-3 — names must round-trip to the denormalised column).
  useEffect(() => {
    if (!entry.limit || folders.length === 0) return;
    const nameById = new Map(folders.map((l) => [l.id, l.name] as const));
    let changed = false;
    const next = entry.grants.map((g) => {
      if (g.folder_name == null && nameById.has(g.folder_id)) {
        changed = true;
        return { folder_id: g.folder_id, folder_name: nameById.get(g.folder_id)! };
      }
      return g;
    });
    if (changed) onChange(accountId, { limit: entry.limit, grants: next });
  }, [folders, entry.limit, entry.grants, accountId, onChange]);

  function toggleLimit(on: boolean) {
    onChange(accountId, { limit: on, grants: on ? entry.grants : [] });
  }

  function toggleFolder(id: FanId, name: string, on: boolean) {
    const next = on
      ? [...entry.grants.filter((g) => g.folder_id !== id), { folder_id: id, folder_name: name }]
      : entry.grants.filter((g) => g.folder_id !== id);
    onChange(accountId, { limit: entry.limit, grants: next });
  }

  return (
    <div className="rounded-md border border-border/50 px-3 py-2">
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={entry.limit} onChange={(e) => toggleLimit(e.target.checked)} />
        <span className="font-medium">{accountLabel}</span>
        <span className="text-fg-dim">— limit folders</span>
      </label>
      {entry.limit && (
        <div className="ml-6 mt-2 space-y-1">
          {listsQ.isLoading && <div className="text-[11px] text-fg-dim">Loading folders…</div>}
          {listsQ.error && (
            <div className="text-err text-[11px]">{errText(listsQ.error)}</div>
          )}
          {!listsQ.isLoading && folders.length === 0 && !listsQ.error && (
            <div className="text-[11px] text-fg-dim">No custom folders on this model.</div>
          )}
          {folders.map((l) => (
            <label key={l.id} className="flex items-center gap-2 text-[11px]">
              <input
                type="checkbox"
                checked={selectedIds.has(l.id)}
                onChange={(e) => toggleFolder(l.id, l.name, e.target.checked)}
              />
              <span>{l.name}</span>
            </label>
          ))}
          {entry.grants.length === 0 && folders.length > 0 && (
            <p className="text-err text-[11px]">Pick at least one folder, or turn this off.</p>
          )}
        </div>
      )}
    </div>
  );
}
