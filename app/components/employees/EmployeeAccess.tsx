"use client";

/**
 * The access limits of an Employee's login (`chatter` in the code and the Relay): AccessEditor sets the per-Employee
 * Creator and vault-folder limits (GET /admin/chatters/{id}/access, PUT …/account-access and …/folder-access), and
 * Manage employees opens it in the Access limits modal from a row's More menu (EmployeeModals.tsx). Adding an
 * Employee is EmployeeFormModal there.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { relay, type VaultListsResp } from "@/lib/relay";
import { fetchAllVaultLists } from "@/hooks/useVaultMedia";
import { useAccounts } from "@/hooks/useAccounts";
import { type FanId } from "@/lib/fanId";

interface AccessResp {
  account_ids: string[];
  folder_access: Record<string, number[]>;
}

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

interface FolderGrant {
  folder_id: FanId;
  folder_name: string | null;
}

interface FolderEntry {
  limit: boolean;
  grants: FolderGrant[];
}

export function AccessEditor({ chatterId, onClose }: { chatterId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const accountsQ = useAccounts();
  const ownerAccounts = accountsQ.data?.accounts ?? [];

  const accessQ = useQuery<AccessResp>({
    queryKey: ["admin", "chatters", chatterId, "access"],
    queryFn: () => relay.get<AccessResp>(`/admin/chatters/${chatterId}/access`),
    staleTime: 5_000,
  });

  const [limitModels, setLimitModels] = useState(false);
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(new Set());
  // Per-account folder limit state. Seeded from the server's folder_access.
  const [folderState, setFolderState] = useState<Record<string, FolderEntry>>({});
  const [seededFor, setSeededFor] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Seed local state once the server access payload lands (re-seed when the
  // editor is opened for a different chatter).
  if (accessQ.data && seededFor !== chatterId) {
    const d = accessQ.data;
    setLimitModels(d.account_ids.length > 0);
    setSelectedAccounts(new Set(d.account_ids));
    const fs: Record<string, FolderEntry> = {};
    for (const [aid, ids] of Object.entries(d.folder_access || {})) {
      fs[aid] = {
        limit: ids.length > 0,
        grants: ids.map((id) => ({ folder_id: id, folder_name: null })),
      };
    }
    setFolderState(fs);
    setSeededFor(chatterId);
  }

  // Accounts the chatter can actually see right now (drives which accounts
  // get a folder-limit control). Limit OFF ⇒ all of this owner's accounts.
  const visibleAccountIds = useMemo(() => {
    if (limitModels) return ownerAccounts.filter((a) => selectedAccounts.has(a.id)).map((a) => a.id);
    return ownerAccounts.map((a) => a.id);
  }, [limitModels, selectedAccounts, ownerAccounts]);

  const saveM = useMutation({
    mutationFn: async () => {
      await relay.put(`/admin/chatters/${chatterId}/account-access`, {
        account_ids: limitModels ? [...selectedAccounts] : [],
      });
      // Folder grants for every owner account, not just the visible ones — an
      // account de-selected from "Limit models" must have its prior folder
      // restriction cleared too (sends []), or stale grants resurrect.
      const visible = new Set(visibleAccountIds);
      for (const a of ownerAccounts) {
        const entry = folderState[a.id];
        await relay.put(`/admin/chatters/${chatterId}/folder-access`, {
          account_id: a.id,
          folders: visible.has(a.id) && entry?.limit ? entry.grants : [],
        });
      }
    },
    onSuccess: () => {
      setSavedAt(Date.now());
      setSaveErr(null);
      qc.invalidateQueries({ queryKey: ["admin", "chatters", chatterId, "access"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
    },
    onError: (e) => setSaveErr((e as Error).message || "save failed"),
  });

  // DA-2: an ON "Limit models" toggle with zero selections is not savable.
  const accountSelectionInvalid = limitModels && selectedAccounts.size === 0;
  // Same rule per-account for folders.
  const folderSelectionInvalid = visibleAccountIds.some(
    (aid) => folderState[aid]?.limit && (folderState[aid]?.grants.length ?? 0) === 0,
  );
  const cannotSave = accountSelectionInvalid || folderSelectionInvalid;

  // Editing any selection invalidates a prior "Saved." confirmation.
  const setFolderEntry = useCallback((aid: string, next: FolderEntry) => {
    setSavedAt(null);
    setFolderState((prev) => ({ ...prev, [aid]: next }));
  }, []);

  if (accessQ.isLoading) {
    return <div className="text-fg-dim text-xs">Loading access…</div>;
  }
  if (accessQ.error) {
    return <div className="text-err text-xs">{(accessQ.error as Error).message || "failed"}</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">Access limits</h4>
        <button type="button" onClick={onClose} className="text-[11px] text-fg-dim hover:text-fg">✕</button>
      </div>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={limitModels}
            onChange={(e) => { setSavedAt(null); setLimitModels(e.target.checked); }}
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
                  onChange={(e) => {
                    setSavedAt(null);
                    setSelectedAccounts((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(a.id);
                      else next.delete(a.id);
                      return next;
                    });
                  }}
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
        {visibleAccountIds.length === 0 && (
          <div className="text-[11px] text-fg-dim">
            {limitModels ? "Select a model above to set folder limits." : "No models available."}
          </div>
        )}
        {visibleAccountIds.map((aid) => {
          const a = ownerAccounts.find((x) => x.id === aid);
          return (
            <FolderLimit
              key={aid}
              accountId={aid}
              accountLabel={a?.nickname || aid}
              entry={folderState[aid] ?? { limit: false, grants: [] }}
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
        {saveErr && <span className="text-err text-[11px]">{saveErr}</span>}
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
            <div className="text-err text-[11px]">{(listsQ.error as Error).message || "failed"}</div>
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
