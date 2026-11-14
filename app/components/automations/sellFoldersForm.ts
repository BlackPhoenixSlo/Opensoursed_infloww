// Content folders picker (ticket 49): which vault folders / OF lists the
// selling turn may offer from. Include-only — the stored `exclude` rides
// along untouched because the config PUT replaces `folders` whole.

import type { FullAiConfig } from "@/components/automations/fullAiTestChat";

export type FolderRef = string; // "vf:<id>" | "of:<id>"
export type StoredFolders = NonNullable<FullAiConfig["folders"]>;
/** A draft with no `folders`: All. */
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
      // The boxes show empty while All is on, so the list is empty too: a tick after it starts clean.
      return { include: [], all: !s.all };
    case "reset":
      return initFolders(a.stored);
  }
}

export const canSubmit = (s: FolderPick) => s.all || s.include.length > 0;

export const buildPayload = (s: FolderPick, stored: StoredFolders): StoredFolders =>
  ({ include: s.all ? [] : [...s.include], exclude: [...stored.exclude] });
