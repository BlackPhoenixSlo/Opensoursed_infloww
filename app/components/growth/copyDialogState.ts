/**
 * Growth > Scripts' Copy dialog (`ScriptsImportDialogs.tsx` CopyScriptsDialog) as a pure reducer: the two linked
 * states the dialog gates its Confirm on — `allCreators` (Share to every owned Creator, resolved server-side) and
 * `picked` (the specific-creators multiselect) — plus `canSubmit` and `buildPayload`. The component only dispatches
 * and reads these; it holds no copy-submit logic of its own (CLAUDE.md reducer rule).
 *
 *   • Import from other creators: `picked` are the SOURCES, up to MAX_SOURCES (a pick past it is refused, `isFull`);
 *     `allCreators` is not offered.
 *   • Share: `picked` are the targets, OR `allCreators` ignores `picked` and the server resolves the full owned
 *     roster (the dialog's toggle). `allCreators` and the multiselect gate each other — on, the list is disabled.
 */

import type { SavedReplyCopy } from "@/hooks/useSavedReplies";

export const MAX_SOURCES = 5;

export type CopyMode = "import" | "share";

export interface CopyDialogState {
  mode: CopyMode;
  /** Share to every owned Creator (Share mode only); the server resolves the roster, so `picked` is ignored. */
  allCreators: boolean;
  /** The picked creators: sources (Import) or targets (Share, while `allCreators` is off). */
  picked: string[];
}

export type CopyDialogAction =
  | { type: "toggleAll"; on: boolean }
  | { type: "toggle"; id: string; on: boolean };

export function copyDialogInit(mode: CopyMode): CopyDialogState {
  return { mode, allCreators: false, picked: [] };
}

/** Import holds MAX_SOURCES sources: no more can be picked. */
export function isFull(s: CopyDialogState): boolean {
  return s.mode === "import" && s.picked.length >= MAX_SOURCES;
}

export function copyDialogReducer(s: CopyDialogState, a: CopyDialogAction): CopyDialogState {
  switch (a.type) {
    case "toggleAll":
      // Picked is left untouched (the list is disabled while on; buildPayload ignores it): turning the toggle
      // back off restores the earlier picks.
      return { ...s, allCreators: a.on };
    case "toggle": {
      if (a.on) return s.picked.includes(a.id) || isFull(s) ? s : { ...s, picked: [...s.picked, a.id] };
      return { ...s, picked: s.picked.filter((x) => x !== a.id) };
    }
  }
}

/** Whether the dialog's Confirm is enabled. Import: 1..MAX_SOURCES sources picked. Share: the roster toggle, or at
 *  least one target picked. */
export function canSubmit(s: CopyDialogState): boolean {
  if (s.mode === "import") return s.picked.length >= 1 && s.picked.length <= MAX_SOURCES;
  return s.allCreators || s.picked.length > 0;
}

/** The copy (`useCopySavedReplies`). Import: the picked sources → this Creator. Share: this Creator → the picked
 *  targets, or (with `allCreators`) no targets: the server resolves the owned roster. */
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
