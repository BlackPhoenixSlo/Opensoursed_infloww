/**
 * AccessEditor's draft as a pure reducer — the "Limit models" toggle and
 * pick, the per-account folder limits, and the save verdict.
 *
 *   • `seedEmployeeAccess` builds the draft from GET …/access, seeded once by
 *     useReducer's initializer; a refetch's new `initial` (a save's
 *     invalidation, a focus refetch) is ignored; key={chatterId} reseeds only
 *     on Employee change.
 *   • Every edit (`limitModels`, `toggleAccount`, `folder`) clears `savedAt`
 *     and bumps `rev` — a "Saved." must not outlive the state it describes.
 *   • `saveStart` records the `rev` being saved; `saveOk` stamps `savedAt`
 *     only if no edit landed since (an edit made while the save was in flight
 *     is not in it, so Save stays offered), and clears `saveErr`; `saveErr`
 *     clears `savedAt` (a failed re-save used to show "Saved." beside it).
 *   • DA-2: an ON limit with zero picks is never savable (`canSubmit`).
 */

import { type FanId } from "@/lib/fanId";

export interface FolderGrant {
  folder_id: FanId;
  folder_name: string | null;
}

export interface FolderEntry {
  limit: boolean;
  grants: FolderGrant[];
}

export interface AccessResp {
  account_ids: string[];
  folder_access: Record<string, number[]>;
}

export interface EmployeeAccessState {
  limitModels: boolean;
  selectedAccounts: ReadonlySet<string>;
  folders: Record<string, FolderEntry>;
  savedAt: number | null;
  saveErr: string | null;
  /** Edit counter; `savingRev` is the one the in-flight save was built from. */
  rev: number;
  savingRev: number | null;
}

export type EmployeeAccessAction =
  | { type: "limitModels"; on: boolean }
  | { type: "toggleAccount"; id: string; on: boolean }
  | { type: "folder"; accountId: string; entry: FolderEntry }
  | { type: "saveStart" }
  | { type: "saveOk"; at: number }
  | { type: "saveErr"; msg: string };

export const NO_FOLDER_LIMIT: FolderEntry = { limit: false, grants: [] };

/** Accounts the Employee can see right now (drives which get a folder-limit
 *  control). Limit OFF ⇒ all of this owner's accounts, in owner order. */
export function visibleAccountIds(
  s: Pick<EmployeeAccessState, "limitModels" | "selectedAccounts">, ownerIds: readonly string[],
): string[] {
  return s.limitModels ? ownerIds.filter((id) => s.selectedAccounts.has(id)) : [...ownerIds];
}

/** DA-2: "Limit models" ON with zero picks. */
export function accountsInvalid(s: Pick<EmployeeAccessState, "limitModels" | "selectedAccounts">): boolean {
  return s.limitModels && s.selectedAccounts.size === 0;
}

/** Same rule per visible account for folders. */
export function foldersInvalid(s: EmployeeAccessState, ownerIds: readonly string[]): boolean {
  return visibleAccountIds(s, ownerIds).some((aid) => s.folders[aid]?.limit && s.folders[aid].grants.length === 0);
}

export function canSubmit(s: EmployeeAccessState, ownerIds: readonly string[]): boolean {
  return !accountsInvalid(s) && !foldersInvalid(s, ownerIds);
}

/** The PUT bodies. Folder grants go out for EVERY owner account, not just the
 *  visible ones — an account de-selected from "Limit models" must have its
 *  prior folder restriction cleared too (sends []), or stale grants resurrect. */
export function buildPayload(s: EmployeeAccessState, ownerIds: readonly string[]): {
  accounts: { account_ids: string[] };
  folders: { account_id: string; folders: FolderGrant[] }[];
} {
  const visible = new Set(visibleAccountIds(s, ownerIds));
  return {
    accounts: { account_ids: s.limitModels ? [...s.selectedAccounts] : [] },
    folders: ownerIds.map((aid) => {
      const entry = s.folders[aid];
      return { account_id: aid, folders: visible.has(aid) && entry?.limit ? entry.grants : [] };
    }),
  };
}

/** The draft as loaded: Limit models is on iff the server has an allowlist. */
export function seedEmployeeAccess(data: AccessResp): EmployeeAccessState {
  const folders: Record<string, FolderEntry> = {};
  for (const [aid, ids] of Object.entries(data.folder_access || {})) {
    folders[aid] = { limit: ids.length > 0, grants: ids.map((id) => ({ folder_id: id, folder_name: null })) };
  }
  return {
    limitModels: data.account_ids.length > 0,
    selectedAccounts: new Set(data.account_ids),
    folders,
    savedAt: null,
    saveErr: null,
    rev: 0,
    savingRev: null,
  };
}

/** Every edit goes through here: it clears the last "Saved.". */
function edit(state: EmployeeAccessState, patch: Partial<EmployeeAccessState>): EmployeeAccessState {
  return { ...state, ...patch, savedAt: null, rev: state.rev + 1 };
}

export function employeeAccessReducer(
  state: EmployeeAccessState, action: EmployeeAccessAction,
): EmployeeAccessState {
  switch (action.type) {
    case "limitModels":
      return edit(state, { limitModels: action.on });
    case "toggleAccount": {
      const selectedAccounts = new Set(state.selectedAccounts);
      if (action.on) selectedAccounts.add(action.id);
      else selectedAccounts.delete(action.id);
      return edit(state, { selectedAccounts });
    }
    case "folder":
      return edit(state, { folders: { ...state.folders, [action.accountId]: action.entry } });
    case "saveStart":
      return { ...state, savingRev: state.rev };
    case "saveOk":
      return { ...state, savedAt: state.savingRev === state.rev ? action.at : null, saveErr: null };
    case "saveErr":
      return { ...state, savedAt: null, saveErr: action.msg };
  }
}
