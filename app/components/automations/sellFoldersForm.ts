import type { FullAiConfig } from "@/components/automations/fullAiTestChat";

export type FolderRef = string;
export type StoredFolders = NonNullable<FullAiConfig["folders"]>;
export const NO_FOLDERS: StoredFolders = { include: [], exclude: [] };
export type FolderPick = { include: FolderRef[]; all: boolean };

export type Action =
  | { type: "toggle"; ref: FolderRef }
  | { type: "all" }
  | { type: "reset"; stored: StoredFolders };

export const NO_FOLDER_TEXT = "pick at least one folder, or All";

export const initFolders = (stored: StoredFolders): FolderPick =>
  ({ include: [...stored.include], all: stored.include.length === 0 });

export function sellFoldersReducer(s: FolderPick, a: Action): FolderPick {
  switch (a.type) {
    case "toggle": {
      const include = s.include.includes(a.ref) ? s.include.filter((r) => r !== a.ref) : [...s.include, a.ref];
      return { include, all: false };
    }
    case "all":
      return { include: [], all: !s.all };
    case "reset":
      return initFolders(a.stored);
  }
}

export const canSubmit = (s: FolderPick) => s.all || s.include.length > 0;

// The config PUT replaces `folders` whole, so the stored exclude rides along untouched.
export const buildPayload = (s: FolderPick, stored: StoredFolders): StoredFolders =>
  ({ include: s.all ? [] : [...s.include], exclude: [...stored.exclude] });
