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

export function visibleAccountIds(
  s: Pick<EmployeeAccessState, "limitModels" | "selectedAccounts">, ownerIds: readonly string[],
): string[] {
  return s.limitModels ? ownerIds.filter((id) => s.selectedAccounts.has(id)) : [...ownerIds];
}

export function accountsInvalid(s: Pick<EmployeeAccessState, "limitModels" | "selectedAccounts">): boolean {
  return s.limitModels && s.selectedAccounts.size === 0;
}

export function foldersInvalid(s: EmployeeAccessState, ownerIds: readonly string[]): boolean {
  return visibleAccountIds(s, ownerIds).some((aid) => s.folders[aid]?.limit && s.folders[aid].grants.length === 0);
}

export function canSubmit(s: EmployeeAccessState, ownerIds: readonly string[]): boolean {
  return !accountsInvalid(s) && !foldersInvalid(s, ownerIds);
}

export function buildPayload(s: EmployeeAccessState, ownerIds: readonly string[]): {
  accounts: { account_ids: string[] };
  folders: { account_id: string; folders: FolderGrant[] }[];
} {
  const visible = new Set(visibleAccountIds(s, ownerIds));
  return {
    accounts: { account_ids: s.limitModels ? [...s.selectedAccounts] : [] },
    folders: ownerIds.map((aid) => {
      const entry = s.folders[aid];
      // grants go out for every owner account: a de-selected one must be cleared ([]) or stale grants resurrect
      return { account_id: aid, folders: visible.has(aid) && entry?.limit ? entry.grants : [] };
    }),
  };
}

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
      // an edit made while the save was in flight is not in it: no "Saved."
      return { ...state, savedAt: state.savingRev === state.rev ? action.at : null, saveErr: null };
    case "saveErr":
      return { ...state, savedAt: null, saveErr: action.msg };
  }
}
