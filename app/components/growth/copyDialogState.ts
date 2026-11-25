import type { SavedReplyCopy } from "@/hooks/useSavedReplies";

export const MAX_SOURCES = 5;

export type CopyMode = "import" | "share";

export interface CopyDialogState {
  mode: CopyMode;
  allCreators: boolean;
  picked: string[];
}

export type CopyDialogAction =
  | { type: "toggleAll"; on: boolean }
  | { type: "toggle"; id: string; on: boolean };

export function copyDialogInit(mode: CopyMode): CopyDialogState {
  return { mode, allCreators: false, picked: [] };
}

export function isFull(s: CopyDialogState): boolean {
  return s.mode === "import" && s.picked.length >= MAX_SOURCES;
}

export function copyDialogReducer(s: CopyDialogState, a: CopyDialogAction): CopyDialogState {
  switch (a.type) {
    // picked is kept so toggling off restores the earlier picks.
    case "toggleAll":
      return { ...s, allCreators: a.on };
    case "toggle": {
      if (a.on) return s.picked.includes(a.id) || isFull(s) ? s : { ...s, picked: [...s.picked, a.id] };
      return { ...s, picked: s.picked.filter((x) => x !== a.id) };
    }
  }
}

export function canSubmit(s: CopyDialogState): boolean {
  if (s.mode === "import") return s.picked.length >= 1 && s.picked.length <= MAX_SOURCES;
  return s.allCreators || s.picked.length > 0;
}

export function buildPayload(s: CopyDialogState, ctx: { accountId: string; ids?: number[] }): SavedReplyCopy {
  if (s.mode === "import") {
    return { fromAccountIds: s.picked, toAccountIds: [ctx.accountId], allCreators: false, ids: ctx.ids };
  }
  return {
    fromAccountIds: [ctx.accountId],
    toAccountIds: s.allCreators ? [] : s.picked,
    allCreators: s.allCreators,
    ids: ctx.ids,
  };
}
